# Adapting `stage_and_smoke.sh` to a real systemd unit

Three failures burned on the one occasion the router cutover while adapting the
packaged staging script. None reached production (live stayed HTTP 200
throughout), but each cost a full ~4-minute staging round-trip. All three come
from GUESSING the unit's contract instead of READING it.

## Read the unit first, adapt second

Before filling in the CONFIG block, pull the three facts that define how the
service is actually invoked:

```bash
systemctl --user show <unit> -p ExecStart -p WorkingDirectory -p EnvironmentFiles --value
```

Real output from the:

```
{ path=/usr/bin/node; argv[]=/usr/bin/node dev/run-standalone.mjs;... }
/home/ubuntu/src/the router/.env (ignore_errors=no)
/home/ubuntu/src/the router/current/.build/next/standalone
```

That single command answers entry point, env file, and working directory. Every
trap below is a case of not reading it.

## Trap 1 — NEVER `source` a file that systemd loads via `EnvironmentFile=`

`EnvironmentFile=` is **not shell**. systemd reads each line literally as
`KEY=VALUE`; it does not evaluate, word-split, or interpret metacharacters.
A shell `source` of the same file executes it.

Symptom:

```
/home/ubuntu/src/the router/.env: line 45: syntax error near unexpected token `('
```

Cause: browser user-agent values (`CLAUDE_USER_AGENT`, `CODEX_USER_AGENT`,
`QWEN_USER_AGENT`) contain unquoted parentheses. Perfectly valid to systemd,
a syntax error to bash. The staged process never launched.

The file is NOT malformed and must not be "fixed" — production reads it fine.
Parse it the way systemd does and hand it over with `env`:

```bash
ENV_ARGS=()
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue;; esac
  case "$line" in *=*) ENV_ARGS+=("$line");; esac
done < "$ENV_FILE"
ENV_ARGS+=("PORT=$TEST_PORT" "DATA_DIR=$TEST_DATA" "BASE_URL=http://127.0.0.1:$TEST_PORT")
echo "    loaded ${#ENV_ARGS[@]} env entries (systemd-style, no shell eval)"
env "${ENV_ARGS[@]}" node "$ENTRY" > "$TEST_LOG" 2>&1 &
```

Print the entry count. It is a cheap assertion that the parse produced something
(62 entries here); a silent 0 would otherwise launch a stripped process that
fails much later for an unrelated-looking reason.

Generalizes: the same rule applies to any file consumed by a non-shell loader —
Docker `--env-file`, Kubernetes `envFrom`, `python-dotenv`. Sourcing it in bash
to "check" it can both fail spuriously AND execute embedded substitutions.

## Trap 2 — the entry point is relative to `WorkingDirectory`

Failure:

```
Error: Cannot find module '/…/releases/standalone-<sha>/dev/run-standalone.mjs'
```

The script had `node "$REL/$ENTRY"`. The live unit runs `node dev/run-standalone.mjs`
with `WorkingDirectory=<release>/.build/next/standalone`. So the entry resolves
under the standalone dir, not the release root.

Mirror the unit exactly:

```bash
cd "$REL/.build/next/standalone"   # == WorkingDirectory
node "$ENTRY"                      # == argv, relative
```

The staged process should differ from production in exactly three things: port,
DATA_DIR, and BASE_URL. Anything else that differs is a bug in the adaptation,
not a property of the release.

## Trap 3 — do not infer artifact layout from `ls` of the top level

`ls releases/<new>/` printed only `dist`, which looked like a different layout
from the live release and sent me hunting a packaging change. It was not.

Both releases carry BOTH trees:

```
releases/<name>/dist/dev/run-standalone.mjs
releases/<name>/.build/next/standalone/dev/run-standalone.mjs   <- the one used
```

Resolve by `find` against the NEW artifact and the CURRENT release, then compare:

```bash
find releases/<new> -name run-standalone.mjs 2>/dev/null
find "$(readlink -f current)" -name run-standalone.mjs 2>/dev/null
```

If both lists match, the layout did not change and any error is in your paths.

## Making the discriminating assert actually discriminate

The SKILL body already says an assert that passes against old and new is
decoration. The subtlety worth recording: **a source-level string is often not
in the bundle at all**, because the deploy ships minified chunks.

First attempt used the literal `86_400_000` from the fix. It was PRESENT in the
already-deployed bundle — `jsdom`, `undici`, and `streaks.ts` all contain it.
Vacuous.

Neither did the source docstring survive: `grep` for the changed comment text
found nothing, because `src/lib/db/cleanup.ts` is compiled away.

The reliable move is to locate the compiled site by a string that MUST survive
minification — a log message or SQL literal — then read the real minified
arithmetic around it:

```bash
CHUNK=$(grep -rl "compression_run_telemetry older than" "$D" | head -1)
grep -ohE ".{200}DELETE FROM compression_run_telemetry" "$CHUNK" | head -1
```

Which exposed the actual old form:

```js
c = Math.floor(Date.now() / 1e3) - 86400 * b;
```

Note the minifier rewrote `1000` to `1e3` and dropped the numeric separators, so
neither the source spelling nor the constant would ever have matched. Assert on
the OLD form being ABSENT from that specific chunk:

```bash
OLD_CUTOFF_RE="Math\.floor\(Date\.now\(\)/1e3\)-86400\*[a-z]"
if grep -qE "$OLD_CUTOFF_RE" "$CHUNK"; then echo "FATAL: fix not in artifact"; exit 1; fi
```

Scope it to the chunk containing the change, not the whole bundle — an unrelated
seconds cutoff elsewhere would otherwise mask the result. Then validate the
assert against the CURRENTLY DEPLOYED bundle and confirm it REJECTS it. If it
does not reject the old bundle, it cannot prove anything about the new one.

Run the same assert again after cutover, against `current/`, as the proof the
fix is live rather than merely built.

## Verify a detached run the caller's way

Staging exceeds a 600s foreground tool timeout. Detach and poll the log:

```bash
ssh host 'nohup bash -c "bash /tmp/stage.sh ARGS > /tmp/out.log 2>&1; echo EXIT=\$? >> /tmp/out.log" >/dev/null 2>&1 &'
# then later
ssh host 'tail -30 /tmp/out.log'
```

Appending `EXIT=$?` INTO the log is what makes the outcome readable later —
without it a truncated tail is indistinguishable from a still-running job.
