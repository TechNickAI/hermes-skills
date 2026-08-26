# uv tool install traps: exact-version pins + dropped extras

Two independent traps that BOTH bit while upgrading an assistant agent (Ali's Mac mini)
0.18.2 → 0.19.0 on one occasion. Either one alone produces an upgrade that looks
successful but is a silent no-op — or that takes the member offline on restart.

---

## Trap 1 — an exact-version pin makes `uv tool upgrade` a silent no-op

**Symptom:** the operator was confident the box had already been upgraded ("I swear we
upgraded Ali already to 0.19"). It had not. `uv tool upgrade hermes-agent` ran,
churned a pile of transitive deps, exited 0 — and left `hermes-agent` on 0.18.2.

The hint is buried at the END of a long dependency diff, very easy to miss:

```
hint: `hermes-agent` is pinned to `0.18.2` (installed with an exact version pin);
      reinstall with `uv tool install hermes-agent@latest` to upgrade to a new version.
```

If the tool was originally installed with an exact pin
(`uv tool install hermes-agent==0.18.2`), `uv tool upgrade` will **never** move it
to a newer version. It only resolves transitive deps _within_ that pin — which is
why it produces a big, convincing-looking output.

**This is the likely explanation for any "I thought we upgraded that box" memory
that doesn't match reality.** A prior attempt would have looked like it worked.
Suspect it fleet-wide: if boxes were installed with exact pins, `uv tool upgrade`
has been quietly no-opping everywhere.

### Detect before trusting any upgrade

```bash
uv tool list                     # shows the actually-installed version
hermes --version                 # must agree
ls ~/.cache/uv/archive-v0        # upgrade HISTORY — if the target version was
                                 # never fetched, it was never installed
```

On an assistant agent the cache showed 0.14.0 → 0.15.1 → 0.15.2 → 0.17.0 → 0.18.0 →
0.18.2 and stopped. 0.19 had never been fetched. That was conclusive.

### Fix — force reinstall at latest (NOT `upgrade`)

```bash
uv tool install "hermes-agent@latest" --force
```

---

## Trap 2 — `--force` reinstall DROPS optional extras (takes the agent offline)

`uv tool install hermes-agent@latest --force` installs the **base package only**.
Every messaging platform lives in an extra, so immediately after:

```
MISS slack_sdk
MISS slack_bolt
MISS telegram
MISS discord
OK   websockets
```

**Restarting the gateway at this point takes the member completely offline** — no
Telegram, no Slack. On a user-facing keep-stable box that is a live outage.

The saving grace: the OLD process keeps running fine on the old code until you
restart, so there is a window to catch it. **Use it.**

`hermes-agent[all]` does NOT solve this (tried — deps still missing). Read the
declared extras from the installed metadata and name them explicitly:

```bash
SP=~/.local/share/uv/tools/hermes-agent/lib/python3.11/site-packages
grep -i "^Provides-Extra" $SP/hermes_agent-*.dist-info/METADATA
grep -iE "^Requires-Dist:.*(slack|telegram|discord)" $SP/hermes_agent-*.dist-info/METADATA
```

As of **0.19.0** the platform libs live in the **`messaging`** extra
(`python-telegram-bot[webhooks]`, `discord.py[voice]`, `slack-bolt`, `slack-sdk`),
with a separate **`slack`** extra that also pins `aiohttp`.

Working invocation:

```bash
uv tool install "hermes-agent[messaging,slack,cron,cli,voice]@latest" --force
```

This is also what pulls **slack-sdk 3.40.1 → 3.43.0**, the version carrying the
Socket Mode session-heal fix.

---

## Mandatory pre-restart dependency gate

Never restart the gateway until this prints all-OK:

```bash
SP=~/.local/share/uv/tools/hermes-agent/lib/python3.11/site-packages
for d in slack_sdk slack_bolt telegram discord websockets; do
  if [ -d "$SP/$d" ]; then echo "OK   $d"; else echo "MISS $d"; fi
done
```

## Back up before upgrading

```bash
TS=$(date +%Y%m%d-%H%M%S)
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak.preupgrade-$TS
cp ~/.hermes/.env        ~/.hermes/.env.bak.preupgrade-$TS 2>/dev/null || true
```

## Misc gotchas hit in the same session

- **`uv` may not be at `~/.local/bin/uv`.** On an assistant agent it was
  `/opt/homebrew/bin/uv` (Homebrew Cellar symlink). Resolve with `which -a uv`
  before scripting a path.
- **`uv pip index versions <pkg>` does not exist on uv 0.10.x** —
  `unrecognized subcommand 'index'`. Just install `@latest` and read what
  resolved.
- **`hermes --version` may report `Install method: git`** even on a pure uv tool
  install. Do not use that field to determine install method — use `ps`/`lsof` on
  the running PID.
- **`pgrep -f 'hermes_cli.main gateway run'` can match the wrong process**
  (it returned `runningboardd` PID 168 once). Cross-check with
  `ps aux | grep "gateway run" | grep -v grep` and `launchctl list | grep hermes`.
- **Restarting a gateway from inside that same gateway is blocked** ("cannot
  restart or stop the gateway from inside the gateway process"). For a REMOTE
  host, wrap the kickstart in a detached python/subprocess call over SSH:

  ```bash
  ssh <host> 'python3 - <<PY
  import os, subprocess, time
  subprocess.run(["/bin/launchctl","kickstart","-k",f"gui/{os.getuid()}/ai.hermes.gateway"], check=False)
  time.sleep(12)
  PY'
  ```

- **`hermes gateway status` may warn** _"Service definition is stale relative to
  the current Hermes install"_ after a package upgrade — the launchd plist still
  describes the previous install. Fix with the sanctioned command, not by
  hand-editing the plist (back it up first):

  ```bash
  TS=$(date +%Y%m%d-%H%M%S)
  cp ~/Library/LaunchAgents/ai.hermes.gateway.plist ~/.hermes/ai.hermes.gateway.plist.bak.$TS
  HERMES_HOME=$HOME/.hermes hermes gateway start   # prints "✓ Service started"
  hermes gateway status                            # expect: ✓ Service definition matches
  ```

  Verified on an assistant agent One case: went from ⚠ stale → ✓ matches, new PID.
  **Sweep this across the fleet after any rollout** — it drifts silently and only
  ever surfaces in `gateway status`. Observed stale on a personal-assistant agent (thomas) and Bob
  Steel (gil) while a personal-assistant agent/Dos (an owner) were fine, so it is per-box, not uniform.
  Note it restarts that member's gateway → owner-facing boxes need the operator's go.

- **The file-edit tool refuses to write Hermes config files.** Use
  `hermes config set...`, or patch via a python heredoc on the remote host.
