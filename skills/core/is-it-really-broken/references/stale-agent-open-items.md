# Stale Agent Open Items — when an agent nags its owner about already-fixed things

## The class

An owner reports their agent is "spitting out off-topic messages" — typically a
short list of "two things still open" appended to unrelated work (drafting copy,
answering a question, running an errand).

The instinct is to treat this as a tone/prompting problem. It usually is not.
It is a **stale-state problem**: the agent is faithfully reporting an item from
its own `MEMORY.md` that was resolved but never marked resolved. Memory has no
expiry and no verification step, so a to-do written on Tuesday is repeated
forever until a human contradicts it.

**Treat every self-reported "still open" item as unverified.** The agent is not
lying; it is reading a note. Verify against live state before you relay it to the
owner, and before you accept the framing that the agent is malfunctioning.

Worked example (a personal-assistant agent on `an owner`). Reported to his owner mid-copy-draft:

> Two things still open whenever you want them:
>
> - The named-source-gate needs `hermes gateway restart` from a terminal outside Hermes to go live.
> - iMessage is still locked out — Full Disk Access is granted to the wrong Python interpreter.

Both were false. One had been resolved by an unrelated restart; the other was a
correct diagnosis of a _different_ fault that had since been superseded.

## Step 1 — Verify each claimed open item against live state

### "Plugin X still needs a gateway restart to activate"

The decisive comparison is **plugin file mtime vs. the running gateway's start
time**. If the gateway started _after_ the plugin was written, it is already
loaded, regardless of what memory says.

```bash
# plugin write time
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M" ~/.hermes/plugins/<name>/__init__.py \
                                     ~/.hermes/plugins/<name>/plugin.yaml \
                                     ~/.hermes/config.yaml
# running gateway start time (macOS)
ps -p "$(python3 -c 'import json;print(json.load(open("'"$HOME"'/.hermes/gateway.pid"))["pid"])')" \
   -o pid,lstart,etime
```

Then confirm with the authoritative readout:

```bash
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main plugins list | grep -A2 '<name>'
# → "enabled | 0.1.0 |... | user"
```

Do **not** try to infer plugin load from the gateway log — many gates log nothing
at all on successful registration (`grep -ci '<gate-name>' gateway.log` returned
`0` on a gate that was demonstrably live). Absence of a log line is not absence
of the plugin. `plugins list` + the mtime/start-time comparison is the proof.

Also do not try to import the plugin loader directly to check; module paths
differ between the CLI package and the plugin namespace (`No module named
'hermes'`, `cannot import name 'load_plugins'`). Use the CLI subcommand.

### "iMessage / chat.db is locked out"

Resolve the **live** interpreter and read `chat.db` as that exact binary. macOS
grants Full Disk Access per-interpreter-path, so the only meaningful test is the
one the gateway itself would run:

```bash
# what is the running gateway actually executing?
lsof -p <gateway_pid> | awk '/txt/ && /python/ {print $NF}' | head -1
readlink -f ~/.hermes/hermes-agent/venv/bin/python

# read chat.db as that interpreter
~/.hermes/hermes-agent/venv/bin/python -c '
import sqlite3
c = sqlite3.connect("file:'"$HOME"'/Library/Messages/chat.db?mode=ro", uri=True)
print("ROWS", c.execute("select count(*) from chat").fetchone())'
```

A row count means FDA is fine and the memory note is stale. Cross-check the raw
grant table when you want the full picture (`auth_value` 2 = granted, 0 = denied):

```bash
sudo -n sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" \
  "select client,auth_value from access where service='kTCCServiceSystemPolicyAllFiles'"
```

Expect several `0` rows for interpreters that are no longer used — an old denied
path in that table is not evidence the current one is denied.

## Step 2 — Distinguish the two macOS iMessage faults before reporting either

They produce the same owner-facing complaint and have opposite fixes:

| Symptom                                            | Cause                                | Fix                                                      |
| -------------------------------------------------- | ------------------------------------ | -------------------------------------------------------- |
| `imsg` **hangs**, zero output, zero stderr         | sandboxd deadlock                    | `sudo -n killall -9 sandboxd`, wait ~4s, re-probe        |
| `imsg` **errors** `authorization denied (code 23)` | TCC/FDA revoked for that interpreter | human click in System Settings; cannot be scripted (SIP) |

macOS has no `timeout`; bound every probe with
`perl -e "alarm 20; exec @ARGV" imsg chats --limit 1`.

Note the trap this creates for a repair watchdog: a watchdog that needs
`sudo killall -9 sandboxd` will report `repair failed` forever if it lacks
passwordless sudo for that command, while a human with sudo clears it in one
second. Read the watchdog's own state file and last cron output before believing
its verdict:

```bash
cat ~/.hermes/state/imsg-watchdog-last.txt
tail -20 "$(ls -t ~/.hermes/cron/output/<job_id>/* | head -1)"
```

## Step 3 — SSH probes do not prove permission health

Restating the general rule because it bit this exact investigation: over SSH the
responsible process is `sshd`, which holds Full Disk Access, so an `imsg` probe
run from your SSH session can pass while every launchd/cron invocation is denied.
Only output from a job that fired on its **own** schedule under launchd is
authoritative for a TCC fault.

The sandboxd fault is different — it is process-wide and affects SSH sessions
too, which is why an SSH `imsg` hang _is_ meaningful evidence of it.

## Step 4 — Fix the memory entry, not just the underlying fault

Clearing the fault without clearing the note guarantees the nagging resumes.
Rewrite the stale entries in place, and make the replacement carry:

1. **The resolution and its date**, stated first.
2. **An explicit "do not say X to the owner"** line — the false claim, named.
3. **The verification command** a future session should run before re-raising it.
4. **The remaining real failure mode**, if any, clearly separated from the
   resolved one.

Procedure, on the agent's own host:

```bash
cp ~/.hermes/memories/MEMORY.md ~/.hermes/memories/MEMORY.md.bak-<who>-<ts>
# write a python script locally, pipe it over, run it there:
ssh <host> 'cat > /tmp/fix_memory.py && python3 /tmp/fix_memory.py' <./fix_memory.py
```

The script should `assert` on the current text of each target line before
replacing it, and `assert` the output is not suspiciously shorter than the input.
Verify afterward that the line count is unchanged versus the backup.

Add a behavioral rule alongside the factual correction, e.g.:

> Never carry a resolved to-do forward into unrelated conversations — if an item
> is genuinely still open, it belongs in a direct reply about that item, not
> appended to creative or drafting work.

## Pitfalls

- **`$HOME/.hermes` may not be where you assume.** On a host where the agent is
  the default/root profile there is no `profiles/<name>/` directory at all;
  config, logs, and cron live directly under `~/.hermes`. Finding no profile dir
  is not evidence of a broken install.
- **Do not accept "the agent is malfunctioning" as the frame.** In this case the
  agent's reasoning was sound and its memory was wrong. Say so — it is a better
  answer for the owner than "he glitched", and it points at a fix that lasts.
- **Report the resolved items as resolved, in the owner's vocabulary.** Two plain
  sentences each: what he was saying, and what is actually true. Leave at most one
  genuine ask, and route infrastructure follow-ups (like missing sudo for a
  watchdog) to the technical owner rather than the non-technical one.
