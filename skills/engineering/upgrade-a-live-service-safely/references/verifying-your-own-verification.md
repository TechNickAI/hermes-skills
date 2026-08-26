# Verifying your own verification

Every entry below is a real false-PASS or false-FAIL from a single 2026-08-03/04
deploy session. In each case the _check itself_ was broken, and the agent
reported its output as fact. The deploy was fine; the reporting was not.

## 🔴 Use the EXIT CODE, never a grep of the output

The single most damaging error of the session.

```bash
# WRONG — what I did
out=$(npm run check:file-size 2>&1)
echo "$out" | grep -qiE "fail|error" && echo FAIL || echo PASS
#   -> printed PASS
```

The tool reports in **Portuguese**: `[file-size] 2 violação(ões):` with `✗`
markers. No "fail", no "error". The grep matched nothing, so it printed PASS —
and the same gate failed in CI ten minutes later. I told the user five gates
passed. Three had failed.

```bash
# RIGHT
npm run check:file-size && echo PASS || echo FAIL
```

A command's exit code is its verdict. Output text is a localized,
implementation-defined courtesy. **Never infer pass/fail from output when `$?`
is available.** This generalizes past i18n: tools also print "error" in
non-fatal warnings, and print nothing at all on some failures.

## Prove a check can FAIL before trusting it passed

A check that cannot fail is not a check. Run every new assertion against input
you _know_ is bad and confirm it reports failure.

Session example that worked: three bundle assertions were tested against the
currently-deployed bundle, which contained one of the three markers:

```
FOUND    : <OLD_FIX_SYMBOL>          <- the old fix, present
not found: no such (module|table): dbstat   <- the new fix, correctly absent
not found: <NEW_FLAG>             <- the new fix, correctly absent
```

Correct in both directions, so the gate would genuinely have caught a bundle
that dropped either change. That two-minute test is what made the later
"assertions passed" claim meaningful.

## Adopted scripts: confirm every gate variable is actually READ

`stage_and_smoke.sh` set `SMOKE_FAIL=1` in four places and **never read it**.
Smoke failures were computed, then discarded; the script exited 0 and printed
"staged successfully". `shellcheck -S warning` caught it as `SC2034 (warning):
SMOKE_FAIL appears unused`.

Before running an inherited script against production, grep its own failure
flags:

```bash
grep -n 'FAIL\|ERR\|RC=' script.sh    # is each one ever tested?
shellcheck -S warning script.sh       # SC2034 = computed and thrown away
```

## `head`, `read -n`, and early `break` manufacture false failures on streams

```bash
curl -N ... | head -c 300 | grep -q "event:"   # FAILS on a healthy stream
```

`head` closes the pipe, curl dies on SIGPIPE, grep sees a truncated body. The
server logs `request_signal_aborted` — which reads like a server bug and is
actually the test hanging up. Capture to a file, then assert:

```bash
curl -N ... > /tmp/out.sse 2>&1
[ "$(grep -c '^event:' /tmp/out.sse)" -ge 2 ]   # >=2 proves it progressed
```

Verified: file capture gave 8 SSE events / 1602 bytes; the `head` pipeline
reported FAILED against the identical build.

## Don't diagnose from an auth gate you never passed

`GET /api/settings/database` returned **401** with an API key, because it wants
a dashboard session cookie. The 401 fires _before_ the handler runs, so it says
nothing about whether the fix works. Correct move was to read the compiled
bundle and diff old vs new:

```
NEW: catch(a){if(a instanceof Error&&/no such (module|table): dbstat/i.test(a.message))return!1;throw a}
OLD: unguarded  SELECT SUM(pgsize) ... FROM dbstat WHERE name = ?   (no guard string)
```

An endpoint returning the _same_ status before and after is not evidence either
way. Find a signal that differs between the two builds.

## Absence of an error is not evidence when nothing exercised the path

`journalctl | grep -c dbstat` returned **0 since cutover** — and also **0 in the
prior 2h on the broken build**, because nobody had loaded the settings page.
Comparing zero to zero proves nothing. Before citing "no errors", confirm the
code path actually ran in the window.

## 🔴 A forced job that produced no output NEVER RAN — check the artifact

The sharpest version of the rule above (2026-08-13). After restoring damaged
credentials I force-ran the agent's hourly cron job to prove auth worked, then
counted auth errors in the window:

```
post-restore 401s: 0
```

I reported that as proof the fix worked. **It was not.** The job had never
executed — no new file appeared under `cron/output/<job_id>/`, and the job
record still showed the _stale_ `status: error` from its last real run hours
earlier. Zero errors from a process that never started is absence of
information, exactly like an HTTP 000 or a timeout.

The user's delayed background notification is what surfaced it; otherwise a
false "verified" would have stood.

**Always confirm execution happened before interpreting its absence of errors:**

```bash
# 1. an explicit success line from the runner
h‍ermes cron run <job_id>          # -> "Ran now: succeeded."

# 2. a NEW artifact, newer than the change you are validating
find ~/.h‍ermes/cron/output/<job_id> -name '*.md' -newermt "<change time>"

# 3. the job record flipped, not just the log staying quiet
#    status: error -> ok, and the error field actually EMPTY
```

Only after all three does "0 auth failures" mean anything. The real re-run gave
`Ran now: succeeded`, one new output file, and `status: ok` with an empty error
field — versus 61 all-time 401s before.

Generalization: **a metric computed over a window in which the code never ran is
not a measurement.** Before citing any count as evidence of a fix, prove the path
executed inside that window.

## A non-zero exit from a script's LAST command is not a failed deploy

Staging ended `EXIT=28`. 28 is curl's timeout code, from a `-m 10` health probe
that ran while a test instance was competing for a 2-vCPU box. All smoke checks
had already passed. Independent re-probe: `http=200` in 0.035s.

Read _which_ command produced the exit and what that tool's codes mean before
reporting failure — and re-probe independently.

## Batch-edit scripts: an assert that aborts still lets the next command run

```bash
python3 - <<'PY'
...
assert anchor in s     # raised -> file NEVER written
PY
scp file remote:/tmp/  # STILL RUNS, uploads the unmodified template
```

The upload "succeeded" and staging then ran the wrong file. Verify the
_artifact_ after transformation, not the transformation's apparent success:

```bash
ssh host 'grep -E "^(REPO|MARKER)=" /tmp/script.sh; echo "asserts: $(grep -c ASSERT /tmp/script.sh)"'
```

Check content on the remote side, never assume `scp` implies correctness.

## 🔴 A check that fails REPEATEDLY on good input is the defect — stop patching it

The mirror image of a false PASS, and more expensive because each round looks
like progress. 2026-08-14, deploying a router fix: a static check inspecting
compiled webpack output produced **four consecutive false BROKEN verdicts**
against an artifact that was correct the entire time. Each revision cost a full
~15 minute CI build to discover.

```
v1  required a real require() external in the driverFactory's own chunk
      -> webpack relocates it to a different module. FALSE BROKEN.
v2  rejected any file containing a missing-module throw-stub
      -> that stub is a generic helper present in the BROKEN and FIXED bundles.
         FALSE BROKEN.
v3  resolved the call site's module id, but searched only the SAME file
      -> webpack module ids are global to the chunk graph. FALSE BROKEN.
v4  resolved globally, still could not classify the createRequire shim the fix
      actually compiles to. FALSE BROKEN.
```

**Fixtures do not save you here.** Every revision shipped with unit fixtures, and
they passed 5/5, 9/9, 18/18. They passed because _the same author wrote the
fixture and the code from the same mental model_ — they agreed with each other
and both were wrong about the real artifact. Only the real bundle disagreed.

Three rules that follow:

1. **After the second false failure on known-good input, change the question,
   don't patch the answer.** Three data points saying "my checker is wrong" is a
   design signal, not a bug queue.
2. **Never gate a release on implementation internals you do not control.**
   Bundler module ids, minified symbol shapes, chunk layout, and codegen
   strategy all change without notice and are not the property you care about.
   The property you care about is _behavior_.
3. **Fixtures written by the author of the code under test are weak evidence.**
   They encode the author's assumption. A real known-bad artifact is strong
   evidence. Keep one and test against it.

### The fix: demote the fragile check, gate on behavior

The static check became **diagnostic only** — it prints, it never fails the
build, and it dumps the definition it could not classify so the shape is
learnable from one log instead of another CI round-trip:

```yaml
# DIAGNOSTIC, NOT A GATE.
node scripts/verify-driver-chunk.cjs "$BUNDLE/..." || true
```

The gate became a behavioral probe — open a database from inside the bundle,
create a table, insert, read it back, assert the value:

```bash
node -e "
  const B=require('better-sqlite3');
  const db=new B('/tmp/probe.sqlite');
  db.exec('create table t(x)'); db.prepare('insert into t values (?)').run(42);
  if (db.prepare('select x from t').get().x !== 42) process.exit(1);
"
```

That cannot be fooled by codegen, and it passed on the first try.

### Runtime proof beats static proof — and check the RIGHT process

The authoritative evidence was `/proc/<pid>/maps` showing the native module
actually `dlopen`'d, plus the absence of fallback lines in the boot log:

```
live (broken) : wreq-js.linux-arm64-gnu.node          <- no SQLite driver
staged (fixed): better-sqlite3/prebuilds/linux-arm64.node
```

Two traps in that check itself:

- **The entrypoint may be a wrapper.** `run-standalone.mjs` spawns the real
  server as a child; only the CHILD maps the driver. Checking the parent PID
  reported "not mapped" and read as a genuine failure. Check the parent _and_
  `pgrep -P <pid>` descendants.
- **Match the file that actually exists, not the name you expect.** The grep was
  for `better_sqlite3.node` while npm had installed
  `prebuilds/linux-arm64.node`. Same trap made a CI assert fail one line before
  the module loaded successfully. Locate native modules by directory search
  (`find <pkg> -name '*.node'`), never a hardcoded filename.

### Corroborate a suspicious verdict against an independent signal

When the static check said BROKEN, three independent signals said FIXED:
`arrayBuffers` 1,326 MB → 17 MB, WAL file present and small, zero full-file
rewrites in 10s. **One dissenting check against three agreeing measurements
means the check is wrong.** Weigh the evidence instead of deferring to whichever
tool is loudest.

## `node -e` needs the right CWD for local modules

`require('better-sqlite3')` from `$HOME` fails with `Cannot find module`; the
same call from the repo dir works. When a one-liner suddenly can't find a
module that plainly exists, check CWD before concluding the data is bad — this
one masqueraded as a torn-read for two retry cycles.
