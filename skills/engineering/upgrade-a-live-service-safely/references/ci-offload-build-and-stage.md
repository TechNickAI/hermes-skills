# Offloading the build to CI, then staging on a test port

The strongest fix for "the build takes down the service" is **don't build on the
box at all**. Proven end-to-end on the, one occasion.

Sequence: CI builds → uploads artifact → host downloads → unpack to a NEW
release dir → run on a TEST PORT against a COPY of the DB → verify → only then
swap. The live service is never touched until a human says go.

## Why this beats "build on a bigger box"

Measure before you size. On the host:

| metric                           |        value |
| -------------------------------- | -----------: |
| service steady-state RSS         |      1.11 GB |
| systemd all-time `MemoryPeak`    |      1.18 GB |
| worst runtime day (whole system) |      3.86 GB |
| the build                        | **15.04 GB** |

The instance had been upsized to 16 GB **solely to survive a monthly build**.
Runtime never needed a quarter of it. Moving the build off-box let the instance
drop two sizes (~$31/mo, ~$369/yr on that one host).

**Check this ratio whenever a box "needs" a lot of RAM.** Commands:

```bash
systemctl --user show <svc> -p MemoryPeak -p MemoryCurrent --value
ps -eo pid,rss,comm --sort=-rss | head -5
for d in $(seq 20 26); do sar -r -f /var/log/sysstat/sa$d 2>/dev/null \
  | grep -v Average | awk 'NR>3 {print $5}' | sort -rn | head -1; done
```

If peak-runtime ≪ peak-build, the box is mis-sized for its actual job.

Cloud note: **there is no "burstable RAM."** Burstable (T-family) instances burst
_CPU only_; memory is fixed at launch. The real options are stop→resize→start
(EIP survives), or a throwaway build instance (~$0.12 for 20 min).

## Picking the build host: correctness first, capacity second

Match the **runtime platform**, not the developer's laptop. Native modules are
compiled per-platform and will not load cross-OS.

| candidate                                                               | verdict                                                                                    |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| GitHub `ubuntu-24.04-arm` (4 vCPU/16 GB)                                | **best — ON A PUBLIC REPO ONLY.** See the sizing trap below.                               |
| a larger managed runner (Blacksmith `blacksmith-8vcpu-ubuntu-2404-arm`) | required when the workflow lives in a PRIVATE repo                                         |
| another Linux box, same arch                                            | fine — but it will also thrash; just harmless there                                        |
| the maintainer's macOS machine                                          | **never** — emits `sharp-darwin-arm64` + Darwin `better_sqlite3.node`; won't load on Linux |

Disqualify a build host on **arch/OS mismatch before** considering its specs.
`find <bundle> -name '*.node'` shows how many native modules are in play (37 in
this project — not a patchable one-off).

### 🔴 Trap: the SAME runner label is a different machine in a private repo

`ubuntu-24.04-arm` is a free **4 vCPU / 16 GB** runner on a public repo. On a
**private** repo the identical label yields **2 vCPU / 7.7 GB**. Nothing in the
workflow changes; the machine silently halves.

Hit on one occasion moving this exact workflow from the public app repo into a
private ops repo. The build died ten minutes into `Creating an optimized
production build` with:

```
##[error]Process completed with exit code 143
```

**Exit 143 = 128 + 15 = SIGTERM/SIGKILL — the OOM killer, not a build error.**
There is no compiler diagnostic to chase. Confirm by printing runner resources
in an early step and reading them off the log:

```yaml
- run: |
    echo "arch: $(uname -m) cores: $(nproc)"
    free -h
```

```
arch: aarch64 cores: 2
Mem: 7.7Gi Swap: 3.0Gi ← half of what the public runner gives
```

Rule: **when moving a workflow between repos, re-check the runner's real specs
against the build's measured peak.** A build that needs ~15 GB cannot run on a
7.7 GB runner regardless of what the label used to mean. `NODE_OPTIONS=
--max-old-space-size=8192` does not save it — that caps the JS heap, while the
memory is going to native bundler work.

Fixing it may also mean adopting whatever larger runner the repo already uses
for its other workflows (here Blacksmith, already proven by the sibling
container build) rather than provisioning something new.

### Trap: a pre-existing failure in an unrelated sub-package

`npm run build:cli` failed on a TypeScript/DTS error inside a workspace package
(`@the router/opencode-plugin`) that the deployed service never loads — the unit
runs `node dev/run-standalone.mjs` from the standalone bundle, and the live
`dist/` contained no such directory. The failure was pre-existing and unrelated
to the release.

Do not "fix" someone else's broken sub-package mid-deploy, and do not blanket
`|| true` the step either — it also assembles `dist/`, which IS shipped.
Distinguish the known failure from any other, and assert the output you actually
need:

```bash
if npm run build:cli 2>&1 | tee /tmp/cli.log; then
  echo "OK: clean"
else
  grep -q "Failed to build @scope/known-broken-pkg" /tmp/cli.log \
    || { echo "::error::failed for a DIFFERENT reason"; tail -40 /tmp/cli.log; exit 1; }
fi
[ -s dist/server.js ] || { echo "::error::dist/ missing"; exit 1; }
```

Verify the "never loaded" claim against the RUNNING deployment before relying on
it (`ls <live-release>/dist/`), not from the repo layout.

## The workflow (see `templates/ci-standalone-build.yml`)

Load-bearing parts, all of which caught something real:

- `runs-on: ubuntu-24.04-arm` — free on public repos; verify visibility first:
  `gh repo view OWNER/REPO --json visibility`
- Reproduce the host's documented install flags exactly (`npm ci
--legacy-peer-deps --ignore-scripts`, then `npm rebuild <native-module>`).
- **Assert the build tool actually used.** An env guard like
  `APP_USE_TURBOPACK=0` did NOT hold through the project's own build
  script — the log still printed `▲ Next.js (Turbopack)`. Grep the log and fail
  the job:
  ```yaml
  - run: |
      if grep -qi "turbopack" /tmp/build.log; then
        echo "::error::Turbopack was used — it OOMs the target host."; exit 1
      fi
  ```
- **Assert platform + fork patches survived into the bundle**, before packaging:
  fail if `sharp-darwin-*` present; confirm the fork's marker string is in the
  output. Catching this in CI beats catching it on the box.
- `tar --zstd` + `sha256sum`, upload with `compression-level: 0` (already
  compressed).

## Pushing a workflow file: the `workflow` scope trap

`git push` is **rejected** when the token lacks `workflow` scope:

```
refusing to allow an OAuth App to create or update workflow
`.github/workflows/x.yml` without `workflow` scope
```

The server's `gh` often has `repo` but not `workflow`. Check with
`gh auth status` (it prints scopes). Fix without re-authing anything: pull the
branch to a machine that _does_ have the scope and push from there.

```bash
git remote add router user@host:/path/to/repo
git fetch router <branch>
git push origin router/<branch>:refs/heads/<branch>
```

A `push:` trigger on the branch fires the run automatically — no need to
`gh workflow run`, which 404s until the workflow file is registered on the
default branch.

## Staging on a test port (see `scripts/stage_and_smoke.sh`)

Non-negotiables that make this safe to run against production:

1. Unpack into `releases/<name>/`, **never** the live working directory.
2. Bind a **different port** (20129 vs live 20128).
3. Point `DATA_DIR` at a **copy** of the DB — use `sqlite3.backup` (safe
   against a live writer), not `cp`.
   **The `sqlite3` CLI is often NOT installed on minimal server images.**
   `command -v sqlite3` silently fails and a naive fallback to `cp` can tear a
   page mid-write on a live WAL database — the stage script runs "successfully"
   against a corrupted copy. Python's stdlib `sqlite3` is always present and
   exposes the same online backup API:
   ```python
   import sqlite3
   src = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
   dst = sqlite3.connect(test_db)
   src.backup(dst); dst.close(); src.close()
   ```
   If neither `sqlite3` CLI nor `python3` is available, **fail loudly** — never
   fall through to `cp`.
4. Record the live `MainPID` **before** and assert it is unchanged **after**.
5. `trap cleanup EXIT` so the test process dies even on failure.
6. Never touch the unit file, the `current` symlink, or `systemctl restart`.

### Trap: `.env` is systemd `EnvironmentFile` syntax, not shell

`set -a;..env; set +a` **fails** on values systemd accepts unquoted:

```
CLAUDE_USER_AGENT=claude-cli/2.1.207 (external, cli)
  → syntax error near unexpected token `('
```

Parse it the way systemd does — split on the first `=`, take the rest
literally, no shell evaluation — then hand it to `env`:

```bash
ENV_ARGS=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
  k="${line%%=*}"; v="${line#*=}"
  if [[ "$v" == \"*\" && "$v" == *\" ]]; then v="${v:1:${#v}-2}"; fi
  if [[ "$v" == \'*\' && "$v" == *\' ]]; then v="${v:1:${#v}-2}"; fi
  ENV_ARGS+=("$k=$v")
done < "$ENV_FILE"
nohup env "${ENV_ARGS[@]}" PORT=$TEST_PORT node server.js > "$LOG" 2>&1 &
```

Verified against parens, spaces, `"quoted"`, `'single'`, `a=b=c`, empty values,
and junk lines.

### Trap: readiness loops that fall through silently

A `for … break` poll loop with no flag **continues past the loop** when it times
out, so the checks after it run against a port that never opened and report
confusing downstream failures instead of the real one. Always set a flag:

```bash
READY=0
for i in $(seq 1 60); do
  if curl -sf -m 5 "$HEALTH" >/dev/null 2>&1; then READY=1; break; fi
  kill -0 "$PID" 2>/dev/null || { echo "FATAL: process died"; tail -30 "$LOG"; exit 1; }
  sleep 2
done
[ "$READY" -eq 1 ] || { echo "FATAL: never healthy"; tail -40 "$LOG"; exit 1; }
```

This is a _class_ of bug — any bounded retry loop needs the same flag.

## Verify with an exit code, not by reading output

`echo "EXIT=${PIPESTATUS[0]}"` inside a quoted `ssh "..."` command **expands
locally and returns empty**. Reading "looks successful" out of stdout is not
verification. Redirect output and capture `$?` in the remote shell:

```bash
ssh host 'bash script.sh > /tmp/out.txt 2>&1; echo "EXIT=$?"'
```

## Prove the thing you linted is the thing that ran

After pushing, confirm the local file is byte-identical to the commit that
produced the artifact — otherwise the lint result describes a different file:

```bash
gh api "repos/OWNER/REPO/contents/PATH?ref=<sha>" --jq '.content' \
  | base64 -d > /tmp/pushed.yml
diff /tmp/pushed.yml PATH && echo "identical to what built"
```

## Static checks worth installing

`brew install shellcheck actionlint`. Run `shellcheck -S style` (strictest tier)
and `actionlint`. On this session both came back clean at `style` — yet a real
fall-through bug still existed, because it lived in an **untaken branch**.
Linters do not exercise logic. After linting, deliberately re-read and
unit-test the failure paths that the happy-path run never touched.
