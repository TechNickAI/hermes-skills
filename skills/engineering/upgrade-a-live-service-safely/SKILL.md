---
name: upgrade-a-live-service-safely
description: >
  Use when upgrading, rebuilding, or redeploying a service that is CURRENTLY
  SERVING production traffic — an LLM router, API gateway, web app, or any
  long-running daemon on a host you reach over SSH. Covers the build-in-place
  trap (build tooling that deletes the running service's working directory), CPU
  saturation starving both the service and sshd, detaching builds so an SSH pipe
  drop can't kill them mid-write, the release-dir + symlink swap pattern that
  makes rollback atomic, out-of-band health probing when you can no longer reach
  the box, and cloud-level reboot recovery. Also covers offloading the build to
  CI entirely (free arm64 GitHub runners), right-sizing a host by comparing
  runtime RSS against build peak, and smoke-testing a new release on a test port
  against a copy of the DB before swapping. Load this BEFORE running any build or
  install command on a host that is answering live requests.
version: 1.3.0
license: MIT
metadata:
  hermes:
    tags:
      [deploy, upgrade, outage, rollback, systemd, ssh, aws, production-safety]
    related_skills: [trust-framework]
---

# Upgrade a Live Service Safely

**Mission:** upgrade a service without taking it down — and when something does
go wrong, recover fast with a rollback you prepared _before_ you needed it.

🔴 **Load this skill and its `scripts/` BEFORE writing any deploy tooling.** On
One run spent ~40 minutes hand-rolling staging commands, skipped the test-port
smoke entirely, and was about to cut over to production before anyone checked
whether a packaged procedure already existed. It did: the bundled
`scripts/stage_and_smoke.sh` already contained the test-port instance, the
DB-copy isolation, the live-`MainPID` invariant, and the real-inference smoke —
none of which the hand-rolled version had. **Reach for the packaged script
before improvising one.** Adapting a proven script is faster than writing a
worse one, and the parts you would have skipped are exactly the parts that catch
problems.

The governing rule: **never let the build and the running service share a
directory, a CPU budget, or an SSH session.** Every serious outage in this class
comes from violating one of those three.

**The strongest version of that rule: don't build on the box at all.** Build in
CI (free arm64 runners on public repos), ship an artifact, unpack to a new
release dir, smoke it on a test port, then swap. Proven end-to-end —
see `references/ci-offload-build-and-stage.md`, with a copy-and-adapt
`templates/ci-standalone-build.yml` and `scripts/stage_and_smoke.sh`.
Filling that template in for a specific service — which facts to pull off the
live unit first, and the two asserts that make the artifact trustworthy — is
`references/adapting-the-ci-build-template.md`.
Before sizing a box for a build, measure the ratio: on the host
runtime RSS was 1.2 GB while the build peaked at 15 GB — 16 GB had been
provisioned purely to survive a monthly build.
🔴 **Adapt the packaged script by READING the unit, not guessing it.** One
`systemctl --user show <unit> -p ExecStart -p WorkingDirectory -p EnvironmentFiles --value`
answers entry point, env file, and working directory. Three failed staging runs
all came from skipping it: `source`-ing a file that systemd loads
via `EnvironmentFile=` (that is NOT shell — unquoted parens in user-agent values
are a bash syntax error but valid to systemd), running the entry relative to the
release root instead of `WorkingDirectory`, and inferring artifact layout from a
top-level `ls` when both releases carried both trees. Also covers why a
source-level string usually CANNOT serve as the discriminating assert (the
bundle is minified — `1000` became `1e3`, numeric separators vanished, and the
docstring compiled away entirely) and how to locate the compiled site via a log
or SQL literal that survives minification:
`references/adapting-stage-and-smoke-to-a-real-unit.md`.
🔴 **Getting deploy commits off the box is its own failure class.** A scratch clone
made with `git clone --shared <local checkout>` has `origin` pointing at the LOCAL
directory, so `git push -q` exits 0 having pushed nowhere and CI then fails with
`upload-pack: not our ref`. Never `-q` a push you intend to verify; assert with
`git ls-remote <real remote> refs/heads/<branch>`. A rebase onto a newer base also
carries upstream `.github/workflows/` changes, which a token without `workflow` scope
refuses — move the commits via `git bundle` to a host whose token has it rather than
re-provisioning credentials on production:
`references/adapting-the-staging-script-to-a-real-service.md`.
🔴 **A runner label is not a fixed machine size.** `ubuntu-24.04-arm` is
4 vCPU/16 GB on a PUBLIC repo and 2 vCPU/7.7 GB on a PRIVATE one, so moving a
workflow between repos can silently halve the build's memory and kill it with
**exit 143** (SIGKILL/OOM) and no compiler error. Print `nproc` + `free -h` in an
early step and compare against the measured build peak — details and the
sub-package-failure trap in `references/ci-offload-build-and-stage.md`.

🔴 **When your own assert fails a build, suspect the assert before the
artifact.** Two failed rounds on the same check means stop and switch to a
BEHAVIOURAL gate — make the program do the thing (open the DB, serve the
request) rather than inspecting what its compiled output looks like. Four CI
builds were burned iterating a static bundler check against an
artifact that was correct every time, while the substance signals stayed green
in every failed run. Fixtures you write yourself cannot falsify your own mental
model; only a known-bad and a known-good REAL artifact can. Full case, plus the
runtime-proof traps (wrapper vs child pid, prebuilt binary filename) and the
rule to demote every COPY of a bad check: `references/verification-that-discriminates.md`.

🔴 **A green backup job is not proof of a recoverable service.** Ask "what could
I NOT reconstruct from the backup alone?" and answer it by enumerating the app's
real inputs against the backup ROOT SET — never by reading the job's exit status.
Config living outside the data dir is invisible to a positive root assertion, and
when a datastore holds encrypted-at-rest secrets (`enc:v1:` tokens) the key
material is part of the backup set BY DEFINITION; ciphertext without its key
restores to nothing. Verify by round-trip restore + hash compare, not by reading
the manifest. Also covers a stale lock silently skipping `forget --prune` forever
while the job still exits 0:
`references/backup-restore-completeness-audit.md`.

🔴 **After the cutover, publish a before/after table on the SAME metrics, and do
not revert the workaround in the same change.** A performance hack added for the
bug you just fixed (a tmpfs RAM disk, a raised IOPS ceiling) stays until the new
build is live AND the fix is measured on the new pid — otherwise a rollback
lands on an unprotected host. A workaround also DISTORTS measurement: with the
DB on tmpfs, device-level `iostat` read ~0 KB/s while the real demand was a
231 MB/s burst every 3 minutes, so measure the BURST directly before sizing
storage down. And predict, before and after, what the fix will NOT improve —
`references/native-driver-fallback-memory-signature.md`.

**Then retire the workaround as its OWN change, decided by measurement.** The
trap is asking "is the workaround faster?" — it usually is, and that is the wrong
question. Measured here: tmpfs 32,434 vs EBS 8,382 SQLite ops/sec (3.9x), against
real demand of 0.83 writes/sec at the busiest minute in 24h — 10,099x headroom on
the _slower_ option, costing +0.033 ms per insert, or 0.0005% of a 5.6 s request.
The interleaved A/B protocol, peak-demand measurement, migration traps (remove
symlinks before copying or `cp` follows them onto themselves; stop the sync timer
first; assert the unit no longer references the mount), proving the new path is
in use via `/proc/<child-pid>/fd`, and the discipline of NOT claiming a latency
win the measurement does not support, are in
`references/retiring-a-performance-workaround.md`, with a runnable
`scripts/bench_storage.cjs`. Removing a workaround usually invalidates capacity
provisioned for it — re-derive that sizing, and check the cooldown (EBS
modifications lock for 6 hours) so you size once.

🔴 **A workaround's assumptions are ENCODED IN YOUR MONITORS — retire them in the
same change.** This is the step that gets skipped and it is the dangerous one.
Rules written during the incident describe the hack as permanent truth, and once
the hack is gone they become blind spots pointed at exactly the failure you most
need to see. Found live after removing a tmpfs DB mount: a
watchdog charter still said _"the DB is on tmpfs and gets fully rewritten, so
NEVER trust `quick_check` on the live file"_ — true while the hack existed, but
now it means **a real corruption signal gets dismissed as normal**. Alongside it,
a _"never alarm on `external`/`arrayBuffers`"_ rule that existed only to suppress
noise from the very bug just fixed, plus threshold checks on a mount that no
longer exists and now silently measure nothing. **Grep every monitor, charter,
runbook, and alert script for the removed component's name before you call the
migration done**, and treat any suppression rule as expiring with the bug it was
written to silence.

🔴 **Before a deploy, back up the state DB with the engine that WRITES it, and
prove each copy by opening it.** Two plausible methods produced corrupt copies
on one occasion: the host `python3` stdlib sqlite (3.45.1) made a backup of a DB
written by better-sqlite3 3.53.3 that **both** engines then read as
`SQLITE_CORRUPT`, and `VACUUM INTO` failed the same way. When the app is on a
full-rewrite driver (sql.js), every reader also hits **torn reads** — the live
file can even be observed at 0 bytes mid-write without any data being lost.
Backups must retry until `quick_check=ok` AND config-table row counts match.
Full pattern, plus the two independent probes for _which SQLite driver is
actually loaded in the running process_, and the rule that a performance
workaround stays until the fix is measured live:
`references/sqlite-backup-under-a-full-rewrite-driver.md`, with a ready-to-run
`scripts/backup_sqlite_multi.cjs` (N-way, retry-until-consistent, verifies by
opening each copy). Always land one copy **off-host** and grab the service
`.env` alongside it — config is what the user cannot rebuild.

**A migration to a new deploy mechanism can delete the working one.** On
one occasion a commit titled `ci: move owner-specific builds to the ops repo`
removed `standalone-build.yml` from the repo — but the new ops repo only held an
unfinished _container_ build, while the router still ran an unpacked standalone
bundle under `releases/`. Net effect: no way to produce a shippable artifact
without building on the live host, the exact thing that caused a 30-minute fleet
outage. Recover the proven workflow from the commit that built the running
release (`git show <deployed-sha>:.github/workflows/<file>`) rather than
reconstructing it, note in the commit message that it can be dropped once the
new path is proven, and confirm with the user which mechanism is actually live
before adopting the new one.

🔴 **This recurs, and the second time it recurred as a RESTORE-THEN-DELETE-AGAIN
pair.** On one occasion, `<sha>` _restored_ `standalone-build.yml` and then
`<sha>` ("ci: keep fork deployment automation in the ops repo") deleted it
again — so the branch HEAD had no tarball build while the ops repo still shipped
only a container. Skimming the log for "was it restored?" gives a false yes.
**Only the tree at the branch HEAD is authoritative.** Before planning any
deploy, run these three and state the answers explicitly:

```bash
# 1. what does the live unit actually execute?
systemctl --user cat <svc> | grep -E 'ExecStart|WorkingDirectory'
# 2. does the ref you intend to ship contain a build for THAT artifact shape?
git show origin/<ref>:.github/workflows/<file> >/dev/null 2>&1 && echo PRESENT || echo ABSENT
# 3. can the host even CONSUME the new artifact shape?
getent group docker # empty group => this user cannot run containers unprivileged
gh workflow list -R <owner>/<repo> --all | grep -i disabled
```

Check 3 is the one that gets skipped. A container artifact is a **different
deploy architecture**, not a drop-in for a symlink swap: it needs group
membership, a rewritten unit file, a new rollback story, and a registry pull
path. Never fold that migration into a deploy the user framed as "ship the new
code" — surface it as its own decision with options and let them choose. Note
also that workflows can exist but be `disabled_manually`, which `gh workflow
list --all` reveals and a tree listing does not.

**Verify that commits the live box has but the new branch "lacks" are real
losses.** `git rev-list <newref>..<deployed-sha>` listed two on one occasion. One
was a feature **reapplied** during the rebase under different SHAs — confirm by
grepping the _feature string_ in the new tree (`git show origin/<ref>:<path> |
grep -c FEATURE_FLAG`), never by SHA ancestry, since a rebase rewrites them.
Only the CI workflow was genuinely gone. Report "nothing is lost" only after
that per-commit check, and check whether the corresponding runtime config (an
env var the feature reads) is still set on the host.

**Extend the bundle asserts to cover what THIS deploy ships**, then prove the
assert works by running it against the currently-deployed bundle — the new
strings must be absent there and the pre-existing one present:

```
FOUND: <OLD_FIX_SYMBOL> ← old fix, already shipped
not found: no such (module|table): dbstat ← today's change, correctly absent
not found: <NEW_FLAG> ← today's change, correctly absent
```

Use `grep -rqsF` for any assertion string containing regex metacharacters; plain
`grep` would read `(module|table)` as a pattern and silently match nothing.
Validate the edited workflow before pushing: parse the YAML, extract the `run:`
block, and `bash -n` it.

🔴 **An assert validated only against FIXTURES is not validated.** Fixtures you
write encode the same mental model as the code you wrote, so they agree with
each other and are wrong together. On one occasion three revisions of one release
gate each FAILED A CORRECT ARTIFACT while passing 18/18 of their own fixture
tests — wrong chunk, then a generic webpack helper present in both bundles, then
per-file lookup of module ids that are global to the chunk graph. Each round
cost a full ~15 min CI build to discover. Rules: control-test in BOTH directions
against REAL artifacts (known-bad must FAIL, known-good must PASS); get the
known-good artifact in hand rather than iterating blind across CI round-trips,
or make the check PRINT the bytes it could not classify; **prefer a BEHAVIOURAL
gate over asserting compiler internals** — module ids and chunk layout are the
compiler's business, so gate on "open the database and round-trip a row", not on
bundle archaeology; fail closed on unknown; and when an assert fails ask _"is the
artifact wrong, or is my assert wrong?"_ before touching the artifact. Also
**locate build outputs by search, not a remembered path** — an assert on
`build/Release/*.node` reported MISSING one line before the module loaded fine
from `prebuilds/linux-arm64.node`. Full worked case:
`references/verification-that-discriminates.md`.

⚠️ **CI runner sizing differs between PUBLIC and PRIVATE repos.** The same label
`ubuntu-24.04-arm` yields a free 4 vCPU / 16 GB runner on a public repo and
2 vCPU / 7.7 GB on a private one. Moving a workflow from the public app repo to
a private ops repo therefore silently halves its memory, and a build that peaks
near 15 GB dies at **exit 143 (SIGKILL/OOM)** ten minutes into "Creating an
optimized production build" — with no OOM message, just the exit code. Echo
`nproc` and `free -h` in an early step so the runner's real size is in the log,
and use a larger-runner label (Blacksmith etc.) already proven in that repo.

🔴 **Assert native modules BY PATH, and prove they LOAD.** A feature-string
assert plus a `find -name '*.node' | wc -l` count both pass while the one native
module the app cannot run without is absent — the broken bundle had _more_
`.node` files than the working one (87 vs 81). Missing a compiled driver usually
does not crash the service; it silently drops to a slower fallback engine that
degrades days later as an unrelated-looking error. A transitive dep of a native
module is part of that module (`better-sqlite3` needs `bindings`, which needs
`file-uri-to-path`), and its absence reports as `Cannot find module
'better-sqlite3'` even though the directory is present. **After any cutover,
read the startup ENGINE/DRIVER-selection log lines, not just the `ready` line** —
a fallback ladder announces itself immediately above a cheerful "database
ready". Full recipe, asserts, and per-PID verification:
`references/native-module-completeness-in-bundles.md`.

🔴 **REFINEMENT (one occasion): "missing native module" is often a BUNDLING defect,
not an absent file.** Verified end-to-end on the live host: the addon was
present at v13.0.1, `linux-arm64.node` loaded by hand, and `createRequire`
resolved it from all five plausible anchors — yet the app logged `Cannot find
module 'better-sqlite3'` and fell to sql.js. Cause: webpack replaced the
_injectable loader itself_ with a stub whose only behavior is to throw, because
the call site passed the module name through a variable. **Do not stop at "is
the file on disk"** — that check exonerates the wrong suspect. Read the compiled
chunk and print the definition of the module id the call site references. The
four-step diagnosis (and why a naive `grep -c 'require("x")'` returns 726 hits
and the OPPOSITE conclusion), the fix (keep module names literal at each call
site; hoisting them into a constant re-breaks it), why unit tests pass either
way, and the four unrelated-looking symptoms one such defect produced —
"memory leak", write storm, backup corruption, latency creep — are in
`references/webpack-externals-stub-and-driver-fallback.md`.

🔴 **Before promising ANY upgrade, verify what the running process actually
executes.** A dependency compiled _into_ the interpreter (SQLite, OpenSSL, zlib)
is not versioned by the app release: the app version can be identical before and
after, the app's own updater will not fix it, and a package manager may have
already dropped a patched interpreter on disk while every live process keeps
executing the old, deleted inode. That combination makes a host read as "patched"
when it is still vulnerable — and makes "run the updater" a **false remedy**.
The per-PID probes (`/proc/<pid>/exe` on Linux, `lsof` txt segment on macOS), the
`(deleted)` tell, and the restart-not-upgrade conclusion are in
`references/runtime-vs-ondisk-version-verification.md`. Read it before scoping
any remediation as an upgrade — on one occasion it collapsed a four-host
coordinated upgrade into four restarts.

**Restarting a busy service over SSH needs a detached script, and success means
MainPID CHANGED** — not exit 0 and not `is-active`, which still reports `active`
while a unit drains. Foreground `ssh host 'systemctl restart X'` times out and
leaves the unit half-restarted with MainPID unchanged, which reads as a silent
no-op. Method, the lifecycle-guard workaround, and the buffered-output gotcha:
`references/restarting-busy-services-over-ssh.md`.

🔴 **A deploy artifact can contain a NESTED copy of its own runtime assets, and
the nested one is what gets served.** A Next.js `output: "standalone"` bundle
unpacks to both `.build/next/` and `.build/next/standalone/.build/next/` — and
systemd's `WorkingDirectory` points at the nested path. The assembly step can
leave that nested copy STALE while the outer one rebuilds cleanly, so a current
release serves weeks-old UI code while the release dir name, mtime, `BUILD_SHA`,
and health-endpoint version all read correct. A feature merged before the stale
cut renders fine, "proving" the deploy is healthy. On one occasion this hid a
missing dashboard provider for three weeks. **Compare `BUILD_ID` at BOTH levels
as a standing post-cutover check** — mismatch means the served bundle is stale,
and re-extracting the same (already-correct) CI artifact into a fresh release
dir fixes it with no rebuild. Generalize: verify the path the process actually
reads, not the path that shares its name.
`references/nested-bundle-staleness-and-control-tests.md`

🔴 **Run every presence/absence probe against a known-GOOD and a known-BAD
control before believing it.** In that same session `grep 'Provider not found'`
on a page "proved" a provider was missing — but the route is a client-rendered
shell, so a valid provider, a working control, and `bogus-provider-xyz` all
returned the byte-identical 629,808-byte response containing that string. The
probe had zero discriminating power and produced a wrong finding reported to the
user. If good and bad inputs return the same answer, the probe is broken — fix
the probe before touching the subject. Identical response sizes across every
input are themselves the tell. For client-rendered pages, grep the JS chunks the
page references, not its server HTML; prefer probes whose output differs in KIND
(0 chunks vs 1) over "contains a string that is always there."

**After cutover, prove the SHIPPED CHANGE is live — not merely that the service
booted.** Health-green plus a moved symlink is provenance, not proof. When the
endpoint your fix repairs sits behind session auth, a 401 is _zero_ evidence
either way, and "zero errors since restart" is meaningless if the before-window
was also zero. Grep the compiled bundle for the guard and run the same grep
against the rollback target to show the strings discriminate:
`references/proving-a-fix-is-live-post-cutover.md`.

🔴 **Migrations — not code — are the actual one-way door.** A symlink flip is NOT
a rollback once the new build has booted against the live DB. Snapshot the data
store immediately before cutover and restore code+data together. Full pattern,
including how to enumerate pending/destructive migrations before you commit:
`references/database-migrations-and-rollback.md`.

🔴 **Before acting on any "the database is corrupt" reading, take a SECOND
independent copy and re-check.** A `?mode=ro` URI connection against a live
WAL-mode SQLite database fabricates corruption that is not on disk — in the
worked case it reported 13 unreadable tables and a `ROLLBACK`-terminated dump,
while `integrity_check` on the live file returned `ok` and every table read
fine. Repairing from that dump would have destroyed 417 rows of live config to
fix a problem that did not exist. **Removing `?mode=ro` is necessary but NOT
sufficient**: a busy WAL database still tears reads _intermittently_ through
every client (python, better-sqlite3, and the CLI all flapped on the same file
minutes apart), so the durable fix is a retry loop with in-process verification,
and the settling test is snapshotting `db` + `-wal` + `-shm` together and
checking that static copy. The one-step falsifier, measured flap rates, the
correct probe, and the `.recover` / empty-database-passes-every-check traps:
`references/sqlite-live-wal-false-corruption.md`.

🔴 **Never `cp` a live WAL-mode database for backup/persist.** When a service
moves its SQLite store to a tmpfs RAM disk (systemd `mnt-<name>-ramdb.mount`)
with a `.persist` copy on real disk, a sync script that `cp`s the live file
while the app writes produces a torn copy that reads back as `database disk
image is malformed`. Use the online backup API and verify the copy before it
replaces the previous good one: `references/durability-mechanism-verification.md`.
Also size tmpfs against the engine's WRITE AMPLIFICATION, not the file size —
outgrowing the mount makes SQLite return exactly a disk I/O error.

⚠️ **CORRECTION (one occasion) to the earlier reading of this same incident.** A
prior pass concluded "the `cp` corrupted the persist twin, the RAM copy stayed
clean." **Both files were fine.** Snapshots of each passed `integrity_check` 3/3
— the malformed readings were torn reads of live files, in BOTH directions
(persist looked corrupt first, then RAM looked corrupt 20 minutes later). Acting
on either reading would have rebuilt a healthy database from another healthy
database. The real cause of the user-visible `disk I/O error` was a **missing
native SQLite driver** in the deployed bundle forcing a sql.js/WASM fallback
that rewrites the entire file on every persist —
`references/native-module-completeness-in-bundles.md`. Two standing lessons:
when a corruption reading flips direction between runs, the reading is the
defect; and a resource-exhaustion symptom can be a _downstream_ effect of a
packaging regression, so check which engine the process actually loaded before
sizing storage.

🔴 **A failing smoke check is a claim about your TEST before it is a claim about
the build.** Reproduce the check's mechanism in isolation before reporting a
defect. This session declared a good artifact broken because the streaming probe
piped curl into `head -c 300`: `head` closes the pipe, curl dies of SIGPIPE, and
the server logs `disconnect: request_signal_aborted` — which reads exactly like
a server bug. The same request captured to a _file_ returned 1602 bytes and 8
SSE events. **Never pipe a stream into `head`**; `read -n` and an early `break`
in a while-read loop kill the producer the same way. Ask "would this check pass
against the known-good build currently running?" before escalating. Two sibling
artifacts bit the same session — `EXIT=28` is curl timing out under staging load
(not the service dying), and a result variable computed but never read makes a
gate that cannot fail. All three, with the falsifiers:
`references/smoke-test-and-staging-script-artifacts.md`.

**Verify the fix by re-running, not by explaining.** Twice this session a
plausible cause was announced as resolved before retest: the `?mode=ro` removal
(the next run failed identically) and a driver reorder justified by ten trials
of an _intermittent_ fault. Both were genuine improvements; neither was the
cause. Ten trials cannot characterize a flapping failure — do not reorder logic
on that evidence and call it proven. When a fix lands, re-run the failing
operation end to end and quote the new output; when the retest contradicts you,
retract in the first line rather than stacking a second theory on the first.

**Scheduled DB retention pruning follows the same stop→mutate→restart
discipline.** the router's ~64 MB in-memory SQLite page cache means external
deletes while the router is running silently reappear on flush — the mutation
sequence must be stop→prove gone→delete+VACUUM→start, with a verified online
backup taken while the service is still healthy. Full playbook including the
12-table retention schema with per-table timestamp column/format mappings, the
`better-sqlite3`-only constraint, the recovery/rollback procedure, and the
cron-job creation pattern (one-shot validation → weekly reschedule):
`references/sqlite-retention-maintenance.md`.

**Before you conclude a red CI check is yours**, check out the pristine base ref and
run the same gate with your change absent. Bookkeeping gates (frozen file sizes,
changelog presence, lint-warning counts) fail for whoever pushes next, not whoever
caused the drift — and an active release branch is often already red from the
maintainer's own same-day commits:
`references/ci-failure-attribution-base-vs-branch.md`.

🔴 **Branch from the commit you actually RUN, not the checkout's HEAD or the
latest tag.** These routinely disagree: a deploy host's checkout said `3.8.49`
while the symlinked artifact reported `3.8.50`, built from a sha that did not
even exist in that checkout. Resolve it from the running service outward —
health-endpoint version → `current` symlink → `BUILD_SHA` → `git branch -a
--contains <sha>` — and verify the true upstream with `gh repo view --json
parent` rather than typing a remembered URL. Also: **before adding a "missing"
setting, trace all six links of its chain** (type → default → persistence →
startup application → runtime re-application → UI/API); a setting that appears
absent is often present and broken, and shipping a second mechanism beside a
defective one makes it worse.
`references/config-setting-chain-and-fork-prs.md`

🔴 **Fork patch custody is a release invariant, not branch trivia.** Before
cleaning or rebasing a fork, inventory fork-only behavior across all branches
and prove every production-critical semantic patch is carried by the active
release. Then verify the built artifact and running process separately: an
environment variable can remain configured while its reader is absent from the
deployed bundle. Cherry-picks also break original-SHA ancestry, so use symbols,
focused tests, patch identity, and carrier commits rather than
`merge-base --is-ancestor` alone. Full procedure:
`references/fork-patch-custody-and-live-proof.md`.

**Worked example:** `references/router-outage-postmortem.md` — a ~30-minute
fleet-router outage that hit every failure mode below at once, plus how Hermes
clients retry/fall back when their router dies (SDK `max_retries: 0` is
deliberate; policy lives in the outer conversation loop) and how to tell a merely
_idle_ downstream client from a genuinely broken one.

## Read the host's own runbook before you build

**And load this skill before you plan the deploy, not after the plan is
written.** On one occasion a full cutover plan was drafted from first principles —
backup, unpack, flip, verify — and only when the user asked "there is a skill
for this, are you using it?" did the session load it. The skill already carried
a proven `scripts/stage_and_smoke.sh` with a **test-port staging step against a
DB copy** that the hand-written plan omitted entirely; that step then caught a
smoke-gate defect before anything was promoted. If the task matches a skill's
trigger, load it _before_ designing the approach: `skills_list` is cheap and the
packaged scripts encode failures you will otherwise rediscover live.

Before diagnosing or building anything on a host you did not configure, look for
operator docs **on the box**: `/root/CLAUDE.md`, `~/CLAUDE.md`, `~/README`,
`~/scripts/`, `~/*-runbook.md`, and any watchdog's journal.

In the one occasion outage the host carried a `BUILD GOTCHAS` section naming the
exact trap that caused the incident (Turbopack OOMs the box; use webpack), plus
a ready-made `~/build-clean.sh`. It was never read. Three documented rules were
violated and the fleet went down.

Corollaries:

- **A project's own release script may ignore its own env guard.** `.env` set
  `APP_USE_TURBOPACK=0`, yet `npm run build:release` still invoked
  `next build --turbopack`. Verify the tool actually used by grepping the build
  log — assert it in CI so it can never regress.
- **Check for a supervising watchdog before doing anything unusual.** This host
  ran an agent every 15 min that killed rogue builds and paged the owner. It
  _correctly caught and killed_ the first build. A `setsid nohup` detached
  second build then **escaped the pkill** and caused the outage — the
  "clever" detachment defeated the safety system. Detach to survive an SSH pipe
  drop, but never to escape supervision; prefer the host's own build runner.
- **Check the cloud auto-recovery path before claiming credit for a fix.** A
  CloudWatch status-check alarm had already rebooted the box; the manual
  `aws ec2 reboot-instances` was not what recovered it.

## Diagnose from evidence on the box, not from inference

In that incident three successive root causes were asserted and published into a
skill before any measurement: "t4g CPU-credit exhaustion" (wrong — the host is
non-burstable), "vCPU saturation starved the process" (wrong — CPU was 32% idle
at the worst moment), and only then the truth: memory exhaustion → page-cache
eviction → 100% swap → ~1940 pages/s thrash.

The data was sitting on the box the whole time. `sysstat` keeps 10-minute
samples, so post-mortems are almost always possible:

```bash
sar -r -f /var/log/sysstat/sa<DD> -s 22:00:00 -e 23:00:00 # memory
sar -S -f /var/log/sysstat/sa<DD>... # swap used
sar -W -f /var/log/sysstat/sa<DD>... # swap in/out rate
sar -u -f /var/log/sysstat/sa<DD>... # cpu (%nice = build)
sar -q -f /var/log/sysstat/sa<DD>... # load + blocked
journalctl -k -b -1 | grep -i "out of memory\|killed process"
```

Distinguishing detail: **no OOM kill occurred.** The kernel never killed
anything, it just made everything unusably slow — worse than an OOM kill, which
would have killed the build and let the service recover unattended. "No OOM in
dmesg" does NOT rule out a memory failure.

**Rule: state a root cause only after a measurement supports it.** Say "I don't
know yet, pulling `sar`" instead of naming a plausible mechanism. A wrong
diagnosis written into a skill outlives the incident and misleads the next
session.

## Before you touch anything: the four preflight facts

Gather these first. Each one has burned a real deploy.

1. **How is the service actually supervised?**

   ```bash
   systemctl --user is-active <svc> # USER units are easy to miss
   systemctl is-active <svc> # system level
   systemctl --user cat <svc> # read WorkingDirectory + ExecStart
   ps -o pid,ppid,cmd -p <pid> # ppid → /usr/lib/systemd/systemd --user ?
   launchctl list | grep -i <svc> # macOS
   ```

   **A system-level `is-active` returning `inactive` does NOT mean unsupervised.**
   The unit may live in the user manager. Getting this wrong leads to a false
   "nothing will restart this if it dies" alarm — and to missing the fact that
   the unit's `WorkingDirectory` is about to be deleted by your build.

2. **What does the build command actually do first?** Read the package script.

   ```bash
   grep -A2 '"build:release"' package.json
   ```

   If it starts with `rm -rf <dir>` and `<dir>` is (or contains) the supervisor's
   `WorkingDirectory`, an in-place build **deletes the running service's
   filesystem out from under it.** The process survives on memory-mapped code, so
   everything looks fine — until the next restart, which cannot succeed. Your
   rollback window closed silently the moment the build started.

3. **What is the host's real capacity, and is it shared with the service?**

   ```bash
   nproc; free -m; uptime
   aws ec2 describe-instances --filters "Name=ip-address,Values=<ip>" \
     --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' --output table
   ```

   Do not reach for the "burstable instance exhausted its CPU credits"
   explanation without confirming the instance is burstable. On a **non-burstable**
   box (Graviton `r8g`/`m8g`, `c6a`, etc.) there is no credit mechanic at all —
   plain 2-core saturation is enough to starve both the service and sshd. Right
   symptom, wrong cause, wrong fix.

4. **Do you have a rollback you have actually tested?** See below.

## Snapshot before, always

```bash
TS=$(date +%Y%m%dT%H%M%SZ)
git rev-parse HEAD > ~/rollback-HEAD-$TS.txt
cp.env ~/rollback-env-$TS.bak
systemctl --user cat <svc> > ~/rollback-unit-$TS.service
tar czf ~/rollback-build-$TS.tar.gz.build dist # the artifact itself
# plus a DB/data backup if the upgrade runs migrations
```

Migrations matter: if the new version applies schema migrations, a code rollback
alone is **not** sufficient — the data may no longer be readable by the old
binary. Snapshot the DB whenever the release notes mention migrations.

## The deploy pattern: build into a NEW directory, flip a symlink

This is the structural fix. It makes "the service has no working directory"
impossible by construction.

```
srv/releases/v1.2.3-<sha>/ <- build output lands here
srv/current -> releases/v1.2.3-<sha>/
```

Point the supervisor's `WorkingDirectory` at `current`, never at a real build dir.

```bash
REL=~/srv/releases/v1.2.3-$(git rev-parse --short HEAD)
mkdir -p "$REL"
#... build into $REL, or unpack a prebuilt artifact into it...
ln -sfn "$REL" ~/srv/current # atomic flip
systemctl --user restart <svc> # seconds of downtime
```

Rollback = flip the symlink to the previous release dir and restart. Keep the
last 2–3 releases. There is never a moment where the live service has no
directory to run from.

## Build on a different host when the build is CPU-heavy

The symlink solves "no workdir." It does **not** solve CPU starvation — a
Next.js/webpack/Turbopack compile will still saturate a 2-core box and stall the
service sitting next to it. For heavy builds, build elsewhere and ship the
artifact:

```bash
# on a BUILD host — MUST match the target's OS and arch
npm ci && npm run build:release
tar czf app-build.tar.gz.build dist

# on the live host: unpack into a NEW release dir, then flip
scp app-build.tar.gz user@prod:/tmp/
ssh user@prod 'set -e; cd ~/srv
  REL=releases/v1.2.3-$(date +%Y%m%dT%H%M%SZ); mkdir -p "$REL"
  tar xzf /tmp/app-build.tar.gz -C "$REL"
  ln -sfn "$PWD/$REL" current
  systemctl --user restart <svc>'
```

### Choosing a build host: native modules make this OS+arch-specific

You cannot build a Linux artifact on macOS just because both are arm64. Native
addons compile or vendor per-platform:

```bash
find.build -name '*.node' | wc -l # count native binaries
ls node_modules/@img # sharp ships per-platform variants
find. -path '*better-sqlite3*' -name '*.node'
```

`better-sqlite3` compiles against the build platform; `sharp` installs only the
matching `sharp-<os>-<arch>` package. A macOS build produces
`sharp-darwin-arm64` and a Darwin `better_sqlite3.node` — both fail to import on
a Linux target. **Match `uname -sm` between build host and target.** Match the
Node major version too (ABI compatibility for native addons).

## Detach long builds from SSH

A build run as `ssh host 'npm run build'` **dies when the SSH pipe drops** — and
the pipe will drop precisely when the box gets starved, i.e. exactly when the
build is mid-write. That leaves a half-deleted, half-written artifact.

```bash
ssh host 'cd ~/app && setsid nohup npm run build:release \
  > /tmp/build.log 2>&1 < /dev/null &'
```

Then poll from separate short-lived SSH calls. Never hold a long-lived SSH
session open as the build's parent process. Prefer `background=true` +
`notify_on_complete=true` for the poller rather than blocking.

## When you lose the box mid-deploy

**Scope it from outside first.** Distinguish "process starved" from "host dead"
before reaching for a reboot:

```python
import socket
for port in (443, 22):
    s = socket.socket(); s.settimeout(10)
    try: s.connect(("<ip>", port)); print(port, "OPEN")
    except Exception as e: print(port, e)
    finally: s.close()
```

Both ports **open** but HTTP hanging ⇒ the reverse proxy is accepting and the app
process is starved. Ports refused/timing out at TCP ⇒ host or network problem.

Keep an out-of-band health poller running so you learn the instant it recovers,
rather than guessing:

```bash
for i in $(seq 1 60); do
  code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" https://host/healthz)
  echo "[$(date +%H:%M:%S)] http=$code"
  [ "$code" = "200" ] && { echo RECOVERED; break; }
  sleep 15
done
```

**Cloud reboot** when the box is unreachable and the build is unkillable:

```bash
aws ec2 reboot-instances --instance-ids <id> --region <region>
```

Note `reboot-instances` is **plural**; `reboot-instance` is not a valid
subcommand and prints the entire subcommand list at you. Find the instance from
its IP with `describe-instances --filters "Name=ip-address,Values=<ip>"`.

**Expect a recovery ladder, don't panic partway:** `000` (nothing listening) →
`502` (reverse proxy up, app still booting) → `200`. Allow ~2 minutes before
declaring the restore failed.

## Verification: exit 0 is not proof

After restoring or deploying, verify in this order — each step catches something
the previous one cannot:

1. **Supervisor state**, including restart count:
   ```bash
   systemctl --user show <svc> -p ActiveState,SubState,NRestarts,ExecMainStartTimestamp
   ```
   `NRestarts=0` means a clean start. A nonzero count means it crash-looped its
   way back up — technically "active," actually broken.
2. **Port listening** — `ss -tlnp | grep <port>`.
3. **Health endpoint**, probed 2–3× (handlers often lazy-load on cold start).
4. **A real end-to-end request that does actual work**, not just a liveness ping.
   A router must serve a real inference; an API must return real data.
5. **The UI/dashboard surface, if the app has one.** An API-only smoke test
   passes happily while the web UI is broken — in a Next.js/SSR app the pages
   are a _separate rendering path_ from the API routes, so bad static-asset
   paths or a failed server render show up nowhere in an API check. Assert the
   page returns real markup, not an error page, **and** that a static chunk
   actually serves:
   ```bash
   dash=$(curl -sL -m 25 "http://127.0.0.1:$PORT/dashboard")
   grep -q '<title>MyApp' <<<"$dash" \
     && ! grep -qiE 'Application error|__NEXT_ERROR' <<<"$dash"
   chunk=$(grep -oE '/_next/static/[^"]+\.(js|css)' <<<"$dash" | head -1)
   curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$chunk" # want 200
   ```
   **Probe the routes the app really uses.** My first pass reported
   `/en/dashboard` etc. as 404 failures — they 404 on the _live_ instance too,
   because that app doesn't use locale-prefixed routes. Always diff the new
   release against the CURRENTLY-RUNNING instance rather than against a guess;
   a difference is a regression, a matching result is just how the app works.
6. **Explicit restart-safety test.** Restoring an artifact is not the same as
   knowing it survives a restart. Restart once deliberately and re-verify. This is
   the step that proves the rollback is genuine rather than a process still
   running on deleted files.
7. **Downstream traffic resumed** — check the service's own logs/DB grouped by
   client, not just your own probe.

**Reuse ONE `verify()` function for staging AND production.** The same gate that
qualifies the release on the alt port must be the gate that qualifies it live,
and the same one the auto-rollback re-runs. Divergent checks are how a release
passes staging and fails prod. Proven shape: 8 checks — health, models list,
dashboard markup, static asset, 3× real inference across different backends,
streaming.

## Reporting verification status while a gate is still running

When asked "is this verified?" and the verifying job has not finished, report
what has actually reported and what has not. Partial verification is a legitimate
status; implying the pending steps passed is fabrication.

On one release build the lint tier (`actionlint`, `shellcheck -S
style`, `bash -n`, YAML parse) was green while the two load-bearing asserts — the
Turbopack rejection and the "fork fix present in bundle" grep — were still gated
behind a 15–25 min Next.js compile. The honest shape:

- **Step-level progress from the running job IS evidence.** "6 of 12 steps
  completed successfully" proves the workflow parses and its install flags work.
  Cite it as that, not as a verdict on the remaining steps.
- **Name the specific blocker and why you can't shorten it**, rather than padding
  with reassurance.
- **Lint is not execution.** `shellcheck -S style` passed on a deploy script that
  still contained a real defect in an untaken branch (the `cp` fallback in
  `scripts/stage_and_smoke.sh` — the sqlite3 CLI was absent on the target host, so
  the guard silently degraded to a page-tearing copy while printing success).
  After linting, deliberately exercise the failure paths the happy path misses.

## Reporting to the user during an incident

- **Say it plainly and early.** "The fleet router is currently down, I caused it,
  here's what's happening" beats optimistic silence. Do not bury an outage under
  progress narration.
- **Give the recovery ladder and a time bound**, not vague reassurance:
  "detached build will finish, expect ~15 min, if not recovered by then we reboot."
- **Name what you'd need from them** and why you can't do it yourself.
- **Correct your own diagnosis on the record** the moment it's disproved. Calling
  a non-burstable box "a t4g out of CPU credits" and then quietly moving on is
  worse than saying "I said credits, that was wrong, it's plain vCPU saturation —
  and the wrong reason matters because it changes the fix."
- **Verify the target when the user questions it.** If they spell a hostname
  differently, `dig +short` both spellings and confirm the instance ID before
  insisting you had the right box.

## Pitfalls

- **Load this skill and its `scripts/` BEFORE hand-rolling a deploy step.** In
  the one occasion session the agent hand-wrote staging and cutover logic, and the
  user had to ask "there is a skill for this are you using it" — twice. The
  packaged `scripts/stage_and_smoke.sh` already encodes the DB-copy retry, the
  test-port smoke gate, and the live-untouched assertions that the hand-rolled
  version was missing. Adapt the script's CONFIG block; do not reinvent it. When
  a step _is_ missing, patch the script so the fix is durable rather than
  re-deriving it next time.

- **Never infer pass/fail from a command's OUTPUT when you can read its exit
  code.** `npm run check:file-size` reports violations in Portuguese
  (`2 violação(ões)`, `✗`); a `grep -qiE "fail|error"` matched nothing and
  printed PASS for a gate that had actually failed and failed again in CI.
  Use `cmd && echo PASS || echo FAIL`. See
  `references/verifying-your-own-verification.md` for the full set of false-PASS
  and false-FAIL traps from a real deploy — broken gate variables, `head`
  killing SSE streams, auth gates that mask the code path you meant to test,
  and curl exit 28 misread as a failed deploy.

- **Reading a CANCELLED CI job as a FAILED one.** `gh pr checks` prints both as
  `fail`. A cancelled job carries **zero signal** about your code — it never
  finished compiling. Open the log and look for
  `##[error]The runner has received a shutdown signal` or
  `The operation was canceled` before citing it as evidence for or against a
  deploy. Counting a no-signal job as a data point builds a recommendation on
  sand; if you already cited it, correct it on the record.
- **Adopting the upstream project's own build job as your deploy pipeline.** It
  is tuned for the maintainer's goals, not your host's constraints — in the
  worked case upstream's advisory build ran `▲ Next.js (Turbopack)`, the exact
  bundler that OOM'd the router and caused the 30-minute fleet outage. Build from
  _your_ workflow with the assert-the-bundler step, and treat upstream's build
  result as informational only.
- **`rm -rf` inside a build script.** Read the script before running it. This is
  the single highest-value check in this document.
- **Guessing an upstream remote URL from memory.** `git remote add upstream
<recalled-url>` silently points your eventual PR at the wrong repo. Confirm
  the real parent with `gh repo view <owner>/<repo> --json parent` and prove it
  resolves with `git ls-remote --heads upstream` before relying on it.
- **Adding a setting that already exists.** Grep the type, default, persistence,
  boot path, applier, AND UI before writing new config plumbing. A numeric UI
  input's `|| <literal>` fallback that disagrees with the declared default will
  silently persist the wrong value the first time someone clears the field.
- **Assuming unsupervised because system-level `systemctl` says inactive.** Check
  `--user`.
- **Blaming CPU credits on a non-burstable instance.** Check the instance type.
- **Long-lived SSH as the build's parent.** A dropped pipe kills the build.
  Prefer the host's own build runner; detach with `setsid nohup` only when there
  is no runner AND no supervisor that must be able to see and stop the build.
  Detaching to survive an SSH drop is fine; detaching past supervision is how
  the outage above happened.
- **Cross-OS builds with native modules.** Match `uname -sm` and Node major.
- **Declaring success on exit 0 / HTTP 200 from a liveness route.** Do a real
  request and a deliberate restart.
- **Rollback that only covers code when migrations ran.** Snapshot data too.
- **Assuming the remote login shell is bash.** A deploy host's login shell may be
  zsh, so `ssh host '<bash syntax>'` dies with `zsh: command not found: mapfile`
  or `no matches found:`. Use `ssh host 'bash -s' <<'EOF'` for anything
  bash-specific. Related: **macOS bash is 3.2** and has no `mapfile`, so test
  bash-5 constructs on the Linux host, not locally.
- **Sourcing an `EnvironmentFile` with `set -a;..env`.** systemd's format
  permits unquoted values containing parens/spaces (e.g.
  `UA=claude-cli/2.1.207 (external, cli)`) that POSIX shell sourcing chokes on.
  Parse it line-by-line into an env array instead:
  ```bash
  ENV_ARGS=(); while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    ENV_ARGS+=("$line")
  done < "$APP_DIR/.env"
  nohup env "${ENV_ARGS[@]}" PORT=... node server.mjs &
  ```
- **`A && B || C` in a rollback path.** shellcheck SC2015 — `C` also runs when
  `A` succeeds but `B` fails. Never use it where the fallback is a rollback or a
  fatal; write `if/else`. Run `shellcheck -S style` on any deploy script; three
  real bugs surfaced this way in one session.
- **Prune logic that can delete the running release.** Guard it:
  `[[ "$(readlink -f "$old")" == "$(readlink -f "$CURRENT")" ]] && continue`, and
  test it with `current` deliberately pointed at an OLD release.
- **Adapting a template script without verifying the OUTPUT.** A patch script
  that aborts partway (a failed `assert`, an anchor already rewritten) leaves the
  file unmodified, and an un-gated `scp` on the next line ships the **unadapted
  template** — which then runs against `REPO="OWNER/REPO"`. Gate the upload on
  the adaptation succeeding (`python3 patch.py && scp...`) and verify the
  _uploaded_ file, not the local one: `ssh host 'grep -E "^(REPO|MARKER)="
/tmp/script.sh; bash -n /tmp/script.sh'`. Also **copy templates verbatim with
  `cp`, then patch** — round-tripping a script through a line-numbered reader and
  stripping prefixes by regex mangles quoting and produces a file that fails
  `bash -n`.
- **Pruning releases only after the restart.** Releases are multi-GB (~5.3 GB
  each here); three of them put the host at **94% / 3.1 GB free**. Prune
  superseded releases _before_ cutover — the pre-cutover DB snapshot needs room,
  and a service that boots into a full disk fails in a much worse way than a
  service that never restarted.
- **Announcing a root cause after fixing only the first plausible contributor.**
  This session did it three times in a row: `?mode=ro` was declared "the cause"
  of a backup failure (fixing it changed nothing), the sqlite3 CLI was declared
  the culprit on 10 trials (python failed later too), and streaming was reported
  FAILED when the test's own `| head -c 300` was killing curl with SIGPIPE. Each
  claim was plausible and each was wrong. **Re-run the failing operation after
  the fix, before reporting the fix.** If a diagnosis rests on N trials of an
  intermittent fault, say so and give N — ten trials cannot characterize a 1-in-10
  failure. And when a check fails, suspect the check itself before the subject:
  reproduce with the harness removed (write to a file instead of a pipe) to
  separate a real defect from a measurement artifact.
- **`find... | head -N | while read` in a `set -e` script.** `head` closes the
  pipe, `find` dies with SIGPIPE, and the script aborts with **exit 141** partway
  through — looking like the probe "found nothing" when it never finished. Write
  results to a temp file, then loop over the file. Related: `find <no matches> |
xargs file` invokes `file` with zero args, which dumps its full usage block
  into your report; guard with `-r` or test the list is non-empty.
- **Large inline heredocs through the terminal tool.** Non-trivial remote scripts
  can trip H‍ermes' hardline command-parser block. Reliable pattern:
  `write_file` locally → `scp` → `ssh host 'bash /tmp/script.sh'`. Bonus: each
  probe becomes re-runnable and diffable instead of retyped from scratch.
- **Fallback chains whose first rung points at the same host that just died.**
  When auditing outage resilience, confirm at least one rung leaves the failing
  system entirely.
- **Proposing releases+symlink to the operator.** He rejected it outright on one occasion:
  _"the releases thing is overkill and just winds up piling up shit. I don't
  need an atomic rollback, so let's just do one directory."_ Offer **one
  directory + `git reset --hard <sha>` + a deploy lock** (or Docker) instead —
  but still name the hazard the releases pattern existed to solve: `git pull`
  is not atomic, and a cron tick firing mid-pull can run a half-updated tree
  while performing irreversible actions. Keep the Unix identity separation; he did not
  object to that. Full pattern in
  `references/agent-edit-plane-vs-production-run-plane.md`.
- **Confirming a service stop by unit state.** `systemctl stop` on a busy agent
  gateway is asynchronous and can be **preempted** — it returns `Job canceled`
  while a long-running subprocess drains, and the unit then reports
  `active/disabled`, which reads like success. Capture `MainPID` _first_ and
  confirm the process is gone with `kill -0`. This and the rest of the
  move-a-live-stateful-service playbook (fencing by PID, semantic data
  validation instead of row counts, Postgres `PUBLIC` CONNECT isolation,
  diffing what you believe copied, migrated jobs carrying old-host paths,
  and why `RequiresMountsFor=` is silently inert in a systemd USER unit) is in
  `references/stateful-service-host-migration.md`.
- **Declaring a deploy script correct from a code read.** A script that reads
  correctly, passes `bash -n`, and has been reviewed can still fail seven
  distinct ways on first execution — `set -o pipefail` turning an empty `pgrep`
  into a fatal error mid-deploy (production stopped, no error text), a drain
  pattern matching the very service the script is responsible for stopping,
  `source activate` inheriting a stale `VIRTUAL_ENV`, a requirements-path miss
  that installs NOTHING and reports success. **Run the deploy against the real
  host, via the same sudoers path CI will use, before merging.** That plus the
  deploy-user permission architecture (scoped sudo both directions, `SETENV:`
  for `XDG_RUNTIME_DIR`, git's `safe.directory` ownership check) and the rule
  that a guard test must be proven able to FAIL by negative control, is in
  `references/deploy-script-hardening-and-ci-verification.md`.
- **A wrapper that resets the tree BEFORE the drain.** The classic
  `wrapper → git reset --hard → exec real_script` pattern is safe only when the
  wrapper resets a SEPARATE control clone. On a one-directory layout the wrapper
  is resetting the very tree the crons execute from, before the real script can
  stop the service or drain in-flight jobs — inverting the whole cron-safe
  window. Have the wrapper `git fetch` (writes only to `.git`) and extract the
  deploy script via `git show <sha>:ops/deploy.bash` into a tempdir; the deploy
  script then owns the reset, after the drain. Ordering IS the safety property.
  Two independent review bots flagged this High/P1 and both were right.
- **A drain pattern invented rather than derived.** Enumerate what the scheduler
  actually runs before choosing the regex: the real money jobs were shell
  wrappers (`<job_wrapper>.sh`, `<guard_job>.sh`), while the names I guessed
  (`<guard_runner>`, `<guard_exchange>`) were importable LIBRARIES matching no
  process at all. A drain that silently matches nothing is worse than none.
- **A drain that counts its own caller.** `pgrep -f <regex>` matches full
  command lines, so the ssh/bash wrapper _carrying_ the regex matches itself —
  the deploy reported "waiting on 2 running job(s)" for the full timeout with
  zero jobs running. Use `pgrep -a`, filter the command text (exclude the script
  itself, `pgrep`, `bash -c`), and verify by discrimination in BOTH directions:
  zero when idle, non-zero with a real job running. A drain that cannot see a
  running job is the failure that matters.
- **Restart logic keyed on "did I stop it" rather than the desired end state.**
  `if [ "$WAS_UP" = 1 ]` strands a service forever: a failed verify exits with it
  down, then the next successful deploy sees it already down, leaves the flag at
  0, and never starts it. Converge on the END STATE.
- **A drift/monitoring script hardcoded to the old host's paths.** It becomes a
  silent no-op exactly where it is now needed — or worse, prints
  `🔴 DEPLOY DRIFT: /old/path does not exist` and exits non-zero on a healthy
  host, and an alarm that cries wolf gets muted. Probe for the layout. Note a
  "read-only" checker may still need write access somewhere (`git fetch` writes
  `.git/FETCH_HEAD`); route just that call through the tree owner.
- **Changing a function signature without updating its test double.** Adding a
  `write=` kwarg broke `monkeypatch.setattr(mod, "_git", lambda *a:...)`; every
  call raised `TypeError`, `main()` swallowed it as a failed check and returned
  non-zero. Stubs need `*a, **k`.
- **Citing "zero errors" from a job that never ran.** A forced cron run that
  wrote no output file did not execute, so its clean error count proved nothing
  — the job record still held the stale pre-fix status. Confirm execution
  (success line + NEW artifact + flipped status) before interpreting silence.
  See `references/verifying-your-own-verification.md`.
- **Making the old host STAY dead after a migration.** `systemctl disable` does
  not prevent an explicit `start`, `mask` silently refuses when a real unit file
  exists, and the credential — not the service — is the layer that actually
  stops money. Playbook, including red-teaming your own fence, in
  `references/decommissioning-the-old-host.md`. That reference also covers three
  traps found on the one occasion shutdown: a format-match credential sweep on a
  SHARED home scrubs the CO-TENANT's live keys (and the damage is invisible
  because the running gateway holds creds in memory while only its cron jobs
  401); the agent's own internal cron keeps taking EXTERNAL actions (a job was
  posting replies to GitHub PRs from the decommissioned box); and **do not
  "repair" or restart a host you were told to shut down** — read-only plus
  exactly what was asked.
- **A deploy that drains BEFORE it verifies leaves the service down on any
  verification failure.** Ordering matters as much here as in the reset-vs-drain
  trap above. a trading agent's `deploy.bash` pauses/drains the gateway, updates the tree,
  then runs the money-path import check — so when that check correctly refused a
  bad config (`<DB_PATH_ENV>` still pinned to the OLD host's path after a
  migration), the deploy aborted with the gateway never restarted. Unit sat
  `failed`, agent was offline, and nothing alerted. **The guard did its job; the
  ordering turned a safe refusal into an outage.** Two fixes, both cheap: run
  every check that does not require the new tree BEFORE the drain, and give the
  deploy an `EXIT` trap that converges the service back to its desired end state
  on any abort. When you find a service `failed` after a deploy, check
  `systemctl --user reset-failed` + `start` and confirm by MainPID, then treat
  the drain-before-verify ordering as the actual bug. Related: after any host
  migration, grep the codebase for the OLD host's absolute paths — a pinned-path
  assertion is exactly the kind of guard that survives the move and then fires.
- **Editing files directly in the production tree to make a "quick" change.** A
  subagent asked to write a rule into repo `AGENTS.md` edited it in place at the
  live deploy path on `main`, leaving a dirty working copy plus a stray `.bak`
  where the next `git reset --hard` would silently erase it. It also meant
  writing a "never touch main directly" rule by touching main directly. Route
  every repo change through the project's own workspace tooling (here
  `ops/new_workspace.sh`, an independent clone) and leave the prod tree clean —
  verify with `git status --short` returning empty. When delegating repo edits,
  say explicitly which tree to work in; a subagent will otherwise pick the one it
  found first.
- **Re-reporting the same blocker instead of escalating its COST.** When a
  deploy is gated on a user decision, the blocker does not stay static — the
  unfixed defect keeps causing incidents. On one occasion I reported the identical
  "no standalone artifact path" blocker three times across a session while, in
  parallel, the router was restarting on a ~12h cycle, a watchdog was paging the
  owner, and an automated escalation was burning Opus calls hunting a cause we
  had already found. Each report was accurate and each was framed as a status
  update. **A blocker's second mention should carry what it has COST since the
  first, not just restate the options.** Lead with the accumulating damage, keep
  the decision to one line, and say plainly how long the fix takes once approved
  ("~30 min, rollback is a symlink flip"). Also: when the user asks an unrelated
  question while a decision is pending, answer THAT question first and fully —
  appending the pending ask is fine, re-opening the whole blocker is not.
- 🔴 **THE ORIGINAL ASSIGNMENT IS THE APPROVAL. Do not re-ask for it.** Same
  session, the escalation above still under-diagnosed the failure. the operator's reply:
  _"when we started this project, the whole idea was that we would deploy the new
  upstream with our fixes applied. You were supposed to do that and make it live.
  Do that."_ The work had been authorized at the outset; I converted an
  **implementation obstacle** (the deleted CI workflow) into a **decision point**
  and handed it back three times. Restoring a deleted build workflow, choosing a
  runner label, and adapting a packaged staging script are all reversible,
  in-lane engineering — exactly the work that was assigned. The genuine approval
  gate on a deploy is the **irreversible cutover** (symlink swap, restart,
  anything touching live traffic), not the reversible preparation leading to it.
  Test before asking: _is this a new one-way door, or is it just the assigned job
  being harder than expected?_ If the latter, solve it and report what you did.
  Bounded autonomy means bold internally, careful externally — an obstacle inside
  an approved task is internal.
- 🔴 **A deploy that stops a unit OWNS restarting it — `Restart=always` will
  NOT.** systemd honors a client-requested `systemctl stop`, so when the deploy
  dies after stopping the service, nothing ever retries it and it stays down
  indefinitely. The tell on the failed unit is `NRestarts=0`. Recovery, the
  finish-vs-roll-back decision when the tree is already ahead of the recorded
  SHA marker (run the deploy's own gates by hand; check `git reflog --date=iso`
  for when HEAD actually moved), and the trailing-slash `.gitignore` pattern
  that CANNOT match a symlink — making a deploy fail at its OWN verify gate,
  repeatedly, after it has already stopped the service and reset the tree — are
  in `references/interrupted-deploy-recovery.md`. General rule: **when a deploy
  fails at a self-check, suspect the self-check** — ask what the deploy itself
  creates that its own verification will later reject. Also covers proving a
  service is really back when the expected log line does not exist (absence of
  an expected line is evidence of NOTHING; find an independent surface that
  only emits when the thing genuinely works).
- 🔴 **Sort deploy gates by what they READ, and run everything checkable before
  the drain.** A gate that only needs the new tree — module imports, env/config
  consistency, hardcoded path pins, dependency resolution — must run BEFORE the
  service is stopped. Verified in one case: a money-path import check correctly
  refused a deploy over a stale hardcoded path from the previous host, but it ran
  _after_ the drain, so a correct refusal left the agent down with nothing
  scheduled to restart it. "Refused to deploy" and "took the service down" must
  not be the same outcome. Note the blast radius when you find one: on an
  auto-deploy repo, EVERY subsequent merge to `main` knocks the service over the
  same way until the gate is fixed. Section 5 of
  `references/interrupted-deploy-recovery.md`.
- 🔴 **When the SAME terminal state is reached TWICE by different routes, stop
  patching the routes and add a state assertion.** A periodic watchdog timer
  that asserts "this unit SHOULD be up" fixes the class; an `EXIT` trap in the
  deploy only fixes the failures that run _through_ the deploy. Two non-obvious
  traps that a naive implementation gets wrong: gate the deploy interlock on a
  live PROCESS (a flag file goes stale when the deploy dies and suppresses the
  watchdog forever), and treat `deactivating` as hands-off (a start issued
  mid-drain CANCELS the pending stop and kills in-flight work — recovery must
  never be more destructive than the outage). Includes the mandatory two-way
  counterfactual — liveness AND safety — in
  `references/supervisor-above-the-supervisor.md`.
- **"We're N releases behind — what should we turn on?"** Score every candidate
  against MEASURED traffic before recommending it, diff build-sha to build-sha
  (a `version` field names the release LINE, not what is deployed), read the
  code path so you can report a toggle's failure mode rather than its name, and
  **verify a fix is actually RUNNING before calling it a win** — a dormant
  subsystem makes its fix a no-op. Post-upgrade, compare against a MATCHED
  pre-deploy window, per lane, and never attribute a cause you did not isolate:
  `references/release-value-triage-and-post-upgrade-measurement.md`.
- 🔴 **A merge can land INERT.** When a component grows from one file into a
  package, the sync/mirror that deploys it still knows only the file it was
  written for. Measured on one run: the entry point deployed as the new version
  while both modules it imports were MISSING from the host — 420 runs, all
  success, nothing in any alarm, and the just-merged feature was not running.
  Defensive imports (`try/except` around the new modules, so a partial install
  degrades instead of crashing) are what make it invisible: availability-first
  error handling converts a deployment failure into a silent behaviour change.
  Assert the changed code path ENGAGES (probe the feature's own flag), never
  just that a file or symbol is present. Covers naming the unit and gating
  detect/repair/validate/promote on the WHOLE unit (skipping the last gate
  detects drift and then never syncs it), plus the test traps: a comment-only
  change may be deliberately tolerated by report mode, fixtures must seed the
  full unit or tests pass for the wrong reason, and regex-splicing Python source
  produces breakage that only appears at import.
  `references/multi-file-components-and-partial-sync.md`
- 🔴 **Rolling ONE upgrade across N hosts is its own discipline.** Survey every
  host's `git status --porcelain` BEFORE touching any of them, and make the
  deploy script REFUSE a dirty tree so a batch loop fails closed on the one box
  that needs a human. On one occasion exactly one host of eight carried 66 lines
  of uncommitted owner fixes that existed nowhere else — including the fix
  stopping an agent from texting pairing codes to the owner's real contacts. A
  hard reset would have silently reverted them, and the tree looked like
  ordinary "drift". Also covers: verifying BEHAVIOR rather than string presence
  (source / installed metadata / actually invoking the changed code path are
  three separate layers, and a checkout can be new while
  `importlib.metadata.version` still reports the old release); proving restarts
  by PID CHANGE; the two readings that look like failures and are not
  (`Failed with result 'exit-code'` immediately BEFORE `Started` is the OLD
  process draining, and launchd's second column is the LAST exit code, not
  current state — confirm liveness with `ps` instead); why a restart that
  outlives your SSH timeout is UNKNOWN rather than failed, and must be re-read
  rather than retried on a money-adjacent box; and rescuing owner edits into the
  branch, proving preservation with an added-lines hash rather than a file hash
  since the files legitimately differ.
  `references/fleet-wide-rollout-and-verification.md`
- **Migrating a gateway/daemon without its env file.** The service can start
  clean, report `active`, and be functionally deaf. a trading agent came up on the new
  host with `Gateway running with 1 platform(s)` because the framework loads
  `~/.hermes/profiles/<p>/.env` and the env had been placed only at the app's
  shared path. Nothing errored. After any move, assert the PLATFORM COUNT and
  the connection lines in the log, not just unit state — and prefer a symlink
  from the expected location to the backed-up shared file so there is one source
  of truth.
