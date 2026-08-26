---
name: live-database-maintenance
description: >
  Use when cleaning up, compacting, backing up, or restoring a SQLite database
  that a running service still holds open, or when one reports "database disk
  image is malformed". Covers measuring compaction cost before taking a lock,
  distinguishing a torn copy from real corruption, locating which table is
  damaged, and designing a retention policy. Prevents a maintenance window that
  takes down live traffic, and prevents a health check that reports ok on a
  broken file.
version: 1.5.0
license: MIT
metadata:
  hermes:
    tags: [sqlite, retention, vacuum, wal, backup, recovery, production-safety]
---

# Live Database Maintenance

## Mission

Perform bounded SQLite maintenance without letting a live process overwrite external changes, and leave the service healthy even when maintenance fails midway.

The governing sequence is:

**healthy preflight → verified backup → stop → prove process absent → mutate → start → prove process and application health**

Do not reorder it for convenience.

## Procedure

**Reading a database you only want to observe?** Two references cover the
read-only path specifically: `references/read-only-connect-lazy-failure.md`
(why `?mode=ro` fails _lazily_, so the obvious fallback chain never runs) and
`references/immutable-read-staleness-gating.md` (why an `immutable=1` fallback
is EXACT on a checkpointed database, and why warning "may be stale"
unconditionally makes a monitor cry wolf).

**Reviewing unattended maintenance that leaves the service live during
`VACUUM`?** Read `references/unattended-live-vacuum-operations.md` for the
application-write-patience test, conservative backup-plus-rebuild disk math,
enforced host concurrency, quiet failure monitoring, retention horizons,
canary promotion gates, and restore-runbook requirements. Its numeric
companion is `references/vacuum-lock-budget-and-write-patience.md` — measured
VACUUM cost (~14.4 s/GB), the write-patience constants that decide whether a
lock is a stall or an outage, and the prediction-gate code shape. 🔴 That file
now carries **two** corrections that invert naive planning: the rate is a worst
case, AND **you cannot predict this at all** — two real runs came in 6x fast
and 36% slow against the same model. The working method is to **`VACUUM` a
copy and time it**, then pass the measured number as
`--max-lock-seconds`; prefer that over `--force-vacuum`. It also covers ranking
candidates by **freelist and recent human traffic rather than size**, the
post-compaction verification battery, the live-reader WAL trap that makes a
successful run report _"reclaimed 0 MB"_, and why the compaction gate must be
evaluated **before** the backup is taken.
`scripts/pick_vacuum_target.py` is the read-only probe that ranks this host's
profiles that way. `scripts/measure_vacuum_cost.py` then answers _how long_ —
it VACUUMs a copy, prints a measured duration and a suggested
`--max-lock-seconds`, and distinguishes a harmless torn copy (exit 2) from
real corruption (exit 3) so a damaged database can never be fed into a
whole-file rewrite.

**Corrupting REPEATEDLY, and the service is an AGENT?** Read
`references/agent-cli-shellout-second-writer.md` first. A gateway that shells
out to its own CLI (a headless one-shot for a multi-model review panel) spawns a
**second OS writer against its own `state.db`** — proven in source at
`cli.py:4642`/`8566` and `hermes_state.py:2798`. ✅ The fix is **one seeded,
ephemeral `HERMES_HOME` per reviewer** (`config.yaml` + `.env` + `auth.json` at
`0600`, deleted after), measured at **peak 1 holder** per database. 🔴 A single
shared reviewer profile is NOT enough: 6 concurrent reviewers produced **6
simultaneous holders of one database** — the same bug, relocated. 🔴 Nor is a
bare `HERMES_HOME=$(mktemp -d)`: it returns `HTTP 401` **and exits 0**, silently
degrading a five-model panel to zero real reviewers. Also do not offer **MoA**
as the replacement — MoA broadcasts ONE prompt to N models, while a panel needs
N DIFFERENT prompts ("Grok, be critical" / "Claude, be empathetic") — and do not
plan around per-task model landing in `delegate_task`, which upstream has
refused across five PRs ("We do not want this"). That file carries the measured
comparison table, the three **bash trap failures** that make cleanup only
_appear_ to work (subshell self-destruct, traps not firing during a foreground
child, handlers that resume instead of exiting), the fail-closed rules that stop
the helper from causing the corruption it prevents, and the control-population
discipline that stops "write volume" from being blamed.

**Reported `malformed inverted index` on a BUSY database — "is it corrupt
again?"** Read `references/transient-fts-malformed-on-hot-db.md` BEFORE
answering. On a hot database `integrity_check` reads a WAL snapshot while the
service commits FTS updates, so a check landing mid-commit can report malformed
inverted indexes and then return `ok` minutes later. Measured: two FTS tables
flagged, then eight consecutive `ok` samples on the same file, base data
`480,192 rows / 0 read errors`, and all 13 peer profiles clean. 🔴 Never answer
from ONE sample, decide data loss from the BASE table rather than the index
(FTS is derived and rebuildable), and enumerate FTS tables explicitly —
filtering on `endswith("_fts")` silently skips `messages_fts_trigram`, the very
table usually named in the error. `scripts/probe_fts_integrity_flap.py` runs
the whole decision (sampling + force-read + per-table MATCH) and exits 0/2/3 for
healthy / artifact / real damage.

**Corrupting REPEATEDLY?** Start with `references/recurrent-corruption-root-cause-triage.md`
and run its **one-command second-writer check before any volume analysis**:
`lsof -F pcfan <db>` exposes the fd access mode, and `u` means read/**write**.
A non-service process holding the database `u` is the lead — and it is
routinely a **child of the service itself** (an agent shelling out to the same
CLI against its own store).

To be precise about why that matters, because the folklore here is wrong:
**SQLite in WAL mode explicitly supports multiple processes** on one database.
Concurrent access is not itself corruption. What breaks is concurrent access on
top of one of these:

- **Locking that does not work.** WAL relies on POSIX advisory locks and shared
  memory in the `-shm` file. On a network filesystem, or a filesystem mounted
  `nolock`, the locks silently do nothing. WAL across a network mount is
  unsupported.
- **Sidecar files replaced underneath a live reader.** Copying, restoring, or
  `rsync`ing a `.db` while the `-wal`/`-shm` still belong to the old file gives
  processes two different views of one database.
- **Mixed SQLite builds** on the same file, where one side does not honour a
  format or locking mode the other assumes.
- **An application that assumes sole ownership** — a process that deletes,
  truncates, or rebuilds the file while another holds it open.

So the second-writer check is where to _start_, not the verdict. Confirm which
of the above is present before blaming SQLite settings, disks, or write volume.

**Database already damaged when you go to maintain it?** Read
`references/corruption-blocks-compaction.md`. 🔴 **Never `VACUUM` a database
that fails an integrity check** — a whole-file rewrite turns localized damage
into total loss, and `--keep-backup` only preserves a copy of the corruption.
That file has the localize-per-table procedure that distinguishes a
_rebuildable_ table (FTS shadows, operational queues) from an irreplaceable one
(`sessions`, `messages`), and the caveat that a torn `cp` of a live WAL
database produces a false malformed result — always re-check the live file
read-only before concluding anything. It also carries the **post-repair false
all-clear**: `quick_check` skips page-allocation analysis and
`integrity_check` truncates its output, so a repair can be reported clean while
orphaned pages remain. `scripts/locate_corruption.py` is the read-only probe
that automates all of this — it runs both checks unsliced, names the damaged
table, sorts damage into rebuildable vs precious, and reports `never used`
pages as leaked space rather than escalating them as corruption.

**About to swap a REBUILT file over a live one?** Read
`references/rebuilt-db-verification-before-swap.md`. 🔴 `integrity_check: ok` on
the new file proves nothing about data preservation — six real bugs there all
passed it, including `text_factory = bytes` turning every TEXT column into BLOB
(application reads the database as EMPTY) and **phantom rows**, where a corrupt
B-tree's `count(*)` exceeds what it can actually produce, so a naive count
comparison blocks the swap forever. Compare readable-to-readable, and keep the
abort-on-failure gate even when it is rejecting your own work.

**Repairing a corrupt FTS index, or swapping a rebuilt file in under an
auto-restarting service?** Read
`references/offline-fts-rebuild-and-file-swap.md`. 🔴 Several findings there
invert the obvious approach: when only FTS tables scan `BAD`, the damage may
still be **structural B-tree corruption in the base table** — prove it by
removing every FTS object and re-running `integrity_check` (a table that passes
`select count(*)` is NOT proven intact, because a sequential scan never walks
the broken interior pointers). And a corrupt fts5 vtable **cannot be
`DROP`ped** — dropping requires constructing it — so a cleanup that deletes
shadow tables on the `DROP` failure path leaves an unconstructable vtable that
makes `integrity_check` itself raise. 🔴 Most important for the SWAP step:
**`count(*)` on a corrupt B-tree reports PHANTOM rows it cannot produce**
(1,937 of them here), so a `new >= live count(*)` gate can never pass and reads
as data loss — compare _readable identity sets_ with a small bounded tolerance,
and name the unrecoverable ids. That file also covers the
`text_factory = bytes` trap (a rebuild that passes every check while storing
TEXT as BLOB, so the app reads the database as empty), why "missing rows" after
a snapshot rebuild are usually newer rows (diff by primary key, not count), why
a `max(rowid)` high-water mark is wrong for TEXT/composite keys, the
`Restart=always` drop-in that `systemctl mask` cannot replace, and attributing
write pressure against a control population.
`scripts/rebuild_from_corrupt.py` is the row-by-row rebuilder for that case —
it copies every readable row into a FRESH file so SQLite builds new B-trees,
counts unreadable rows instead of dropping them silently, recreates views
before external-content indexes, and fails non-zero on a TEXT→BLOB regression
that `integrity_check` would happily pass.

**Building a wrapper around a deletion CLI?** Read
`references/silent-noop-retention-wrappers.md` FIRST. It catalogs seven measured
ways such a wrapper reports success while deleting nothing — or deletes from
the wrong database — including CLI rejections that exit 0, id-prefix parsing,
count-based invariants defeated by a concurrent writer, a zero-argument
launcher whose hardcoded default profile makes it a no-op on every host but the
one it was written on, and the ordering rule that the verified backup must
precede the FIRST destructive step, not just compaction. Its closing sections
cover the verification traps — `grep -A` bleeding across records, a
freshly-written schedule reading back null, and why a residual backlog after a
catch-up is expected.

**Reporting retention results to a human?** Read
`references/hermes-session-retention-execution.md` — the interpretation traps
where correct output looks like a bug. An FTS recall drop must be GROUPED BY
SOURCE before it counts as data loss (300 -> 182 hits was alarming until the
losses proved to be entirely in deleted cron rows); prune skips unended
sessions so eligible counts legitimately undershoot the raw table; deleting
8,447 sessions freed only 478 MB because the remainder is FTS index; custom
sources mean allowlist-never-denylist; a profile CAN maintain its own store
(the lifecycle guard only blocks self-restart); and a freshly registered cron
job shows a null next-run until the scheduler's next tick.

**Turning a one-off cleanup into a recurring job?** Read
`references/chunked-retention-and-silent-weekly-jobs.md`. It covers slicing
deletion by AGE window rather than `LIMIT` (walked oldest-first, paused between
slices, with a wall-clock deadline that banks progress), and the `no_agent`
weekly job whose healthy runs emit NOTHING — plus the scheduling traps
(bare-filename `script`, the misleading `Next run: ?` display from an
incomplete hand-written job entry, staggering co-tenant profiles).
`scripts/install_weekly_job.sh` is the reusable per-host installer: it walks
that host's own profiles, copies the payload, and registers the job
idempotently by name with a stagger. Note that
`references/scheduling-recurring-maintenance.md` describes the _service-stopping_
case — its "run the job off-host, use an agent not a script" guidance INVERTS
for plain retention, which stops nothing and should run per-profile as a script.

1. **Preflight while serving traffic**
   - Prove the expected process exists and the application health endpoint succeeds.
   - Record HTTP latency, DB/WAL/SHM sizes, free disk, target-table counts, and schema columns.
   - Use the application's SQLite library/runtime when the host has known CLI/WAL inconsistencies.
   - Retry read/open/count probes by closing and reopening between attempts before diagnosing corruption.
   - 🔴 **Read the source comments of the maintenance command that ran before
     theorizing a cause.** A `disk I/O error` cascade traced to
     `journal_size_limit=-1`: `sessions optimize` (FTS merge + VACUUM) rewrote
     every page through the WAL and stranded a 3.07 GB WAL that filled the
     disk. The mechanism was already documented in `hermes_state.py`'s own
     comments. Two corollaries: **current free space does not exonerate the
     disk** (the WAL is checkpointed away by the time you look), and **deleted
     `-wal`/`-shm` descriptors on the live process are usually the self-heal
     reconnect, not an external `rm`** — treating them as root cause sends you
     hunting a deleter who does not exist.
   - 🔴 **A MIX of successful and failed reads means a transient race, not
     corruption.** See `references/transient-torn-reads-on-live-db.md` for a
     continuously-written DB (no `-wal` sidecar, e.g. on tmpfs) that returns
     "database disk image is malformed" on ~2 of 12 reads while `quick_check`
     on a consistent snapshot is `ok`. Critical measured counterintuition:
     "snapshot the DB and read that" is WORSE (1/8 vs 10/12) because exposure
     scales with pages read — a whole-DB copy touches every page. Retry a SMALL
     read at OPEN time instead; probe weight predicts failure rate.
   - 🔴 **Open with a normal connection + `PRAGMA query_only=ON`, never a
     `?mode=ro` URI, on a live WAL database.** See
     `references/read-only-connect-lazy-failure.md` — `mode=ro` fails LAZILY
     (succeeds at connect, raises on first query), which defeats the obvious
     try/except fallback chain. Also covers FTS5 `integrity-check` being a
     write (false CORRUPT on read-only handles) and gating `quick_check` on
     large DBs. The URI form fabricates corruption
     reports (see Pitfalls). Confirm any suspected corruption against a second
     independent copy before planning repair.

2. **Validate timestamp contracts before backup or stop**
   - Inspect the actual producer/INSERT expression, cleanup/query source, and live values.
   - Where rows exist, record `typeof`, representative values, `MIN`, and `MAX`.
   - If source paths disagree and the table is empty, abort rather than guessing. Empty data cannot resolve contradictory contracts.
   - Compute one cutoff instant and derive every needed representation from it.

3. **Check space conservatively**
   - Require room for a complete backup, a complete `VACUUM` temporary image, and margin.
   - Abort before stop if space is insufficient.

4. **Create and verify the backup while healthy**
   - Use SQLite's online backup API.
   - Require a regular, nonempty file of plausible size.
   - Independently reopen the backup read-only and require `quick_check`/`integrity_check` to return `ok`.
   - If backup creation or verification fails, remove partial output, leave the service running, and abort without mutation.

5. **Stop and prove stopped**
   - Record stop-command UTC and monotonic/epoch timing for downtime.
   - Stop through the service supervisor.
   - Poll the exact process fingerprint until no match remains.
   - If absence cannot be proven, do not mutate.

6. **Mutate only while process absence remains proven**
   - Use one transaction for the intended retention deletes and save each statement's `.changes`.
   - Do not expand scope or improvise alternate timestamp conversions after stop.
   - Check process absence again before checkpoint, before compaction, and after compaction.
   - Require a non-busy successful WAL checkpoint before `VACUUM`.

7. **Start and verify**
   - Record start-command UTC.
   - Poll for both expected process presence and application-level health—not merely a successful supervisor command.
   - Record healthy UTC, latency, and total downtime.
   - 🔴 **After REPLACING a database file, prove the process ATTACHED to it —
     process-present plus zero errors is not sufficient.** A service started
     while a multi-GB `cp` was still in flight opened the partial file, fell
     back to JSONL, and ran detached: `is-active` said `active`, the error
     count was `0` (it had stopped trying), and `integrity_check` on the file
     said `ok`. The falsifier is `lsof -p <pid> | grep state.db` returning
     handles (empty = detached). Poll for attachment instead of sleeping a
     fixed interval, and finish the copy before starting the service. Also
     attribute log lines to the LIVE pid — the draining old process logs its
     own failures and will make a good swap look broken. See
     `references/rowid-chunk-rebuild-from-corrupt-db.md`.

8. **Postflight reconciliation**
   - Re-read DB size and target counts with retry/reopen behavior.
   - Compare before count − delete changes against post-start count. Label positive differences as observed post-start inserts only when the arithmetic supports that; otherwise flag discrepancies without explaining them away.

## Recovery invariant

Once the service has actually stopped, no error path may simply return.

1. Stop further DB mutation and loudly enter recovery.
2. Collect supervisor status, recent journal, process state, DB/WAL/SHM metadata, free disk, and health errors without exposing secrets.
3. Attempt one clean stop/prove-gone/start/health cycle.
4. If still unhealthy, stop and prove absence; preserve the failed post-maintenance DB under a diagnostic name.
5. Restore the independently verified pre-maintenance backup, remove incompatible WAL/SHM files only while stopped, and preserve ownership and mode.
6. Start and require both process presence and application health.
7. If rollback also fails, report the service as still down prominently; never claim success from `start` exit status alone.

## Outage budgets for large databases

A safe sequence can still create an unacceptable outage if backup or integrity verification is unbounded. Before stopping a user-facing service, estimate or measure backup and `quick_check` duration against a copy. For multi-gigabyte databases on slow or contended storage:

- Give every backup, integrity check, checkpoint, and compaction an explicit wall-clock budget.
- Keep the restart failsafe outside the maintenance process. A process blocked in uninterruptible I/O may ignore termination, so its `finally` block is not a sufficient recovery mechanism.
- If the stopped-window budget expires, abort mutation and restore service first; schedule expensive verification or compaction for a separate maintenance window.
- Do not treat a completed file copy as a verified backup until an independent check completes, but do not keep the production service down indefinitely waiting for that check.
- After recovery, verify application-level readiness and a fresh error window, not only supervisor state.

For a live gateway with a huge WAL and lock storm, a restart may let SQLite recover/checkpoint the WAL without destructive file handling. Never manually delete `-wal` or `-shm` while any process holds the database.

## Scheduling this as a recurring job

Manual runs are fine once. The moment this becomes routine, it needs to be a
scheduled job — and the design constraint changes from "be safe" to
"be safe **and** minimize the outage."

### Order the sequence to shrink the stopped window

Total downtime is only steps 5–7. Everything else must happen while serving.
The single slowest step is usually the **online backup** (a 353 MB backup on a
331 MB DB), and it is explicitly safe to run against a live database. Putting it
before the stop is what takes a maintenance run from minutes to ~30–60 seconds.

```
1. PRE-FLIGHT <- RUNNING (counts, disk, schema/timestamp verification)
2. ONLINE BACKUP <- RUNNING (slowest step; verify 80-120% + integrity_check)
3. STOP <-- downtime begins
4. DELETE (one transaction)
5. wal_checkpoint(TRUNCATE) + VACUUM
6. START + poll health <-- downtime ends
7. POST-FLIGHT <- RUNNING (re-count, reconcile, prune old backups)
```

State the budget in the job prompt explicitly, and forbid discovery work inside
the window:

> Target total downtime under 3 minutes. Do not do any exploratory work, schema
> discovery, or verification queries during the stopped window that could have
> been done before stopping.

Without that sentence an agent will happily run `PRAGMA table_info` loops and
`typeof` probes _after_ stopping the service, because the prompt told it to
verify those things and never said when.

### Prefer an agent-run job over a bash cron

For a sequence that stops production and can strand the service, schedule an
**agent** (not a shell script) so something intelligent is present at the failure
point to read `journalctl`, retry, and roll back. The recovery invariant above is
only worth writing if something can actually execute it.

### Prune your own backups

Retention maintenance that never prunes its backups just moves the disk problem.
Each run here wrote ~350 MB. Add to post-flight: delete backups older than N days
while always keeping the most recent few regardless of age.

### Cron pitfalls that cost a run

- **A one-shot scheduled "a few minutes out" can be dead on arrival.** If the
  agent creating the job takes longer than the lead time (a subagent took 13.5
  minutes to register a job set to fire in 5), the window is already past at
  registration.
- **Triggering an already-expired one-shot can CONSUME it without running it.**
  Observed: `cronjob action=run` on an expired `repeat: once` job returned
  `execution_success: false` and the job vanished from `jobs.json` entirely — no
  execution, no job. Create the real **recurring** schedule first, then trigger a
  test run against that. A recurring job survives being fired.
- **Recover the prompt before recreating.** A long, carefully-built prompt is
  worth saving outside the scheduler. Check the authoring agent's scratch files
  (e.g. `/tmp/...-prompt.txt`) and its live transcript before rewriting from
  memory.
- **Audit the stored prompt, don't trust the creation report.** Read it back out
  of `jobs.json` and grep for each safety-critical element (stop, prove-gone,
  backup, abort-on-bad-backup, checkpoint, VACUUM, restart, health poll, recovery
  path, rollback). A creation call returning success says nothing about content.

### Verify the run from the host, not from job status

`last_status: ok` means the agent turn completed, not that maintenance worked.
Confirm on the target: service active, process present, health 200, DB size
changed, and a fresh backup file with the expected timestamp. If the job was
supposed to deliver a report and none arrived, say so plainly rather than letting
the host-side evidence imply the reporting path works.

## Pitfalls

- 🔴 **Diagnosing corruption from a `?mode=ro` URI connection on a live WAL
  database.** This manufactures _false_ corruption: `mode=ro` cannot properly
  attach the `-shm`/`-wal` sidecars, so it reads a torn mid-write view and reports
  page-level malformation that is not on disk. Observed: 101 lines of
  `btreeInitPage() returns error code 11` naming 13 real tables, every one failing
  `SELECT count(*)` — while the live database returned `integrity_check = ok` and
  every table read fine. **The falsifier is one cheap test: take a SECOND copy the
  same way.** A genuinely corrupt source corrupts every copy; one bad copy plus one
  clean copy means the snapshot is the fault. Use a normal connection with
  `PRAGMA query_only=ON`, or stop the service, before believing any corruption
  report. Full worked case, including how a `.dump` that "recovered" 170 of 587
  `key_value` rows would have destroyed 417 rows of live config to fix a
  non-existent problem: `references/false-corruption-from-readonly-wal.md`.
- 🔴 **External mutation while the application is running — CONFIRMED to silently
  REVERT, and the read-back lies.** A process with cached rows can flush stale
  state over external writes. Observed on the router: updated a combo row
  in `storage.sqlite` while the service ran, `SELECT`-verified the new value on
  disk (it was there), restarted, and the row came back with the ORIGINAL value.
  The service holds combos in memory and wrote its stale copy over the change on
  shutdown. **A read-back taken BEFORE the restart proves nothing** — the only
  valid verification is a read-back AFTER a restart cycle. Correct sequence is
  `stop → prove absent → write → start → re-read`. Symptom if you get this wrong:
  a "mystery revert" days later with no audit trail and a confident earlier report
  claiming success. Stop and prove absence first, every time, even for a one-row
  config edit that feels too small to warrant an outage (~13s here).
- **Treating one live-WAL backup/read error as corruption.** Retry with fresh handles and independent copies/checks. An unverified backup still blocks maintenance, but a transient error is not a corruption diagnosis.
- **Trusting a cleanup comment over producer code.** A column declared `INTEGER` does not say seconds versus milliseconds. Inspect the actual inserted value.
- **A `DELETE` reporting 0 changes is a RED FLAG, not a clean bill of health.** It usually means the cutoff representation is wrong for that column, not that the table is already within retention. Observed: `domain_cost_history` deleted 0 rows against an epoch-**seconds** cutoff, then deleted 109,796 rows against the correct epoch-**milliseconds** cutoff on the same data. Before accepting a zero, compare the cutoff against that table's own `MIN`/`MAX` — if `MIN` is far older than the cutoff and nothing deleted, the comparison is type-mismatched. Silent no-ops are the failure mode of scoped deletes; a wrong-format cutoff never errors, it just matches nothing.
- **Assuming every table in a cleanup routine shares one date column.** Enumerate the real column per table from the cleanup source. In one 12-table routine: most used `timestamp`, several used `created_at`, two (`mcp_tool_audit`, `a2a_task_events`) errored outright as `no such column: timestamp`, one used epoch milliseconds, and one used space-separated `YYYY-MM-DD HH:MM:SS` with no `T`/`Z`. Four distinct contracts in one routine.
- **Guessing from an empty table.** With no values to inspect, contradictory source evidence is unresolved—not harmless.
- **Aborting on an empty table and stopping there.** The abort is correct, but it is
  only half the job. A 0-row table whose producer and cleanup disagree on units means
  **the retention sweep has never worked** — the cleanup is inert, not idle. Observed
  one occasion on the router: `compressionRunTelemetry` stamps `Date.now()`
  (milliseconds) while `cleanupCompressionRunTelemetry` computed a **seconds** cutoff,
  so `timestamp < cutoff` could never match. That function exists specifically to bound
  storage and prevent OOM, so the guard had never fired. The table reading 0 rows is
  _why nobody noticed_, not evidence that it is fine.
  Follow-through when a contradiction forces an abort:
  1. Decide whether the mismatch makes the sweep **permanently inert** (a ms value is
     ~1000× any seconds cutoff — it can never match) versus merely wrong at the margin.
  2. `grep` the cleanup file for **every** cutoff computation. The same bug is usually
     present more than once, and one instance is often already fixed with an
     explanatory comment you can cite as precedent.
  3. Report it as a latent defect with its blast radius ("the OOM guard has never
     worked; nothing is accumulating yet"), and route the fix to the code owner —
     upstream if the file carries no local delta. Do not silently work around it by
     remapping the unit in your own job; that leaves the real guard broken.
  4. Offer the interim separately: the other tables in the routine are usually fine and
     can clean normally once the one bad table is excluded or its unit corrected.
- **Shell assignment via unquoted `eval`.** ISO/SQL timestamps containing spaces can become commands. Capture generated values line-by-line (for example with Bash `mapfile`) or emit structured JSON and parse it.
- **SQL string literals written with double quotes.** Modern SQLite may interpret them as identifiers. Prefer bound parameters, including metadata queries such as `WHERE type = ?` with `"table"` bound as data.
- **Losing SSH exit status while filtering login noise.** Capture output first or use `pipefail`; filter only for presentation.
- **Reporting malformed compact lists.** Keep one line per key fact/table when formatting could concatenate fields.

## Detailed reference

See `references/runtime-linked-sqlite-refresh.md` when an interpreter or native SQLite build was replaced under a running fleet service. It covers live-PID version proof, deleted inodes, per-profile gateway restarts, verified online backups, exact launchd label matching, drain-aware systemd restarts, and the evidence required before declaring the vulnerability removed.

See `references/retention-run-gates.md` for a condensed verification matrix and the source/data contradiction pattern that warrants an abort before stop.

See `references/scheduling-recurring-maintenance.md` for converting a hand-run
maintenance into a scheduled agent job: downtime accounting from a real run, the
post-registration prompt audit checklist, scheduler behaviour that can consume an
expired one-shot without running it, and backup pruning.

See `references/fleet-session-store-maintenance.md` when the problem spans several
Hermes profiles or a target-local pruner is contending with its own gateway. It
covers fleet inventory, source-class retention, external orchestration, separating
online deletion from conditional offline compaction, FTS/trigram bloat, timeout and
free-space traps, verification state, and serial canary rollout.

See `references/hermes-session-prune-and-optimize-semantics.md` for a source-first
audit of Hermes session prune/optimize behavior: exact selection timestamps,
canonical/FK/FTS/soft-reference deletion effects, webhook/cron/subagent completion
gates, gateway routing and `sessions.json`, and a fail-closed way to direct CLI
maintenance at a copied profile DB via an explicit throwaway `HERMES_HOME`.

🔴 See `references/stale-in-process-corruption-state.md` FIRST when a live
service writes `database disk image is malformed` continuously but the file
checks out clean from a separate process. Fourth failure class: the corruption
is cached in the incumbent PROCESS, not the file — typically because something
repaired the file underneath a long-running process. The falsifier is a real
INSERT+COMMIT from a fresh connection; if that succeeds, stop planning a repair,
the fix is a restart. Also covers why the in-place FTS self-heal cannot recover
(its detach step is itself a write, through the same poisoned connection), and
why an agent inside a Hermes gateway is correctly fenced from restarting one —
hand the user the command instead of retrying wrappers.

🔴 See `references/rowid-chunk-rebuild-from-corrupt-db.md` when corruption is
REAL and there is NO usable backup of that file, so restore+merge-forward is not
available. Covers the bounded rowid-window copy with bisect-on-damage (cursor
always advances, so a bad page costs one window), recovering 99.985% of 478k
rows; why external-content FTS5 corruption is ZERO data loss (rebuild from the
base table); `.recover` dead-ending on builds without `SQLITE_ENABLE_DBPAGE_VTAB`;
and the deleted-`-wal`/`-shm`-descriptor mechanism (`ls -l /proc/<pid>/fd | grep
deleted`) that corrupts a DB with no `dmesg` I/O errors and plenty of free disk.
Also two ways the REBUILD silently self-corrupts: `text_factory = bytes` turning
TEXT primary keys into BLOBs so `INSERT OR IGNORE` cannot dedupe (counts land at
exactly 2x, and a distinct-check against the rebuilt file PASSES — only
comparison against the source reveals it), and a skip-past-damage loop that spins
at 99.9% CPU forever. Both produced clean-looking progress logs.

🔴 See `references/corruption-recovery-and-merge-forward.md` when corruption is
REAL and confirmed (not the read-only artifact above — falsify with a second
independent copy first). Covers: why the Hermes "session storage could not be
written… often a full disk" error text misleads (host had 40 GB free while the
actual fault was b-tree corruption), localizing damage per-table so the intact
tables can be merged forward, why `sqlite3.recover` and row-by-row index salvage
both dead-end, and the restore-from-restic + merge-forward procedure that
recovered 20 h of post-backup writes with ~90 s downtime — including the
DETACH-before-write rule that stops one corrupt-table read error from poisoning
the entire merge transaction at commit.

See `references/pragma-tuning-and-inert-settings.md` when the question is
_performance_ rather than retention: reading live pragmas (and why they can
legitimately disagree with source defaults), benchmarking honestly on network
storage where jitter gives 10x spread within one config, cache-size sizing that
actually moved reads 33%, and the recurring bug class where an app exposes a
tunable whose configured value silently reverts on every restart because startup
applies the compiled-in default instead of the persisted one.

🔴 See `references/recurrent-corruption-root-cause-triage.md` when a database has
corrupted **more than once** and the ask is "why does this keep happening / what
is the long-term fix" rather than "recover this file". Covers: checking for an
in-flight repair by ANOTHER operator before touching anything; ruling the SQLite
library in/out honestly (the `walresetbug` fix landed in 3.51.3 — measure the
version the APP links, not the system CLI); ranking causes by log evidence count,
where `disk I/O error` preceding `malformed` means corruption is a SYMPTOM of the
disk filling; the three measured causes (unbounded `journal_size_limit`,
in-transaction FTS5 triggers, an external "read-only" CLI checkpointing a live
DB); measuring WHICH writer produces the bytes before blaming the obvious suspect;
answering "can we move to Postgres?" by measuring driver/abstraction/FTS coupling;
and the alarming-but-harmless WAL spike during a DELETE→WAL conversion.

🔴 See `references/write-contention-and-durability-on-money-paths.md` when the
database is the system of record for something irreversible (orders, payments,
approvals) and MANY processes write it. Different failure class from bloat: a
237 KB database with 35 writer modules lost live order records to `database is
locked`. Covers why file size is the wrong variable for a contention problem,
the WAL-is-on-but-`busy_timeout`-is-missing trap (the two lines sit adjacent, so
the pragma creates false confidence), why an engine migration does NOT fix a
swallowed write, the intent-record/idempotent-retry/loud-error requirements that
hold regardless of engine, and why blanket fail-closed strands live exposure.

## Designing a RETENTION POLICY (config), not running a one-off maintenance job

🔴 When the ask is "set up the ideal session-management config" for one host or
a whole fleet — rather than "clean up this database" — read
`references/session-retention-policy-design.md` FIRST. It carries the full
`sessions:` config table read from installed source (`auto_prune`,
`auto_archive`, `retention_days`, `vacuum_after_prune`, `min_interval_hours`,
the FTS and transcript-guard keys), the fleet-audit sweep shape, and the
pitfalls.

Two load-bearing findings from it:

- **Archive preserves search; prune destroys it.** `search_messages()` filters
  only on the MESSAGE columns `active`/`compacted` and never joins
  `sessions.archived`, so archiving is a listing-layer soft-hide with zero
  recall cost — the reversible default. Prove it rather than asserting it:
  `scripts/verify_archive_vs_prune.py` builds a scratch DB and demonstrates both
  directions in one run.
- **Count idle sessions before proposing `retention_days`.** Agent-fleet bloat
  is recent volume (cron/subagent chatter, 50-95% of messages), not old history.
  Measured across 14 profiles: sessions idle >90 days were 0 on most of them, so
  a 90-day prune would have deleted history and reclaimed nothing.
- 🔴 **`sessions.auto_prune` CANNOT do source-scoped retention.** Verified in
  the installed source: `maybe_auto_prune_and_vacuum(retention_days,
min_interval_hours, vacuum, sessions_dir, min_vacuum_interval_days)` takes
  **no source filter** — it calls `prune_sessions(older_than_days=...)` and
  nothing else. So `auto_prune: true` deletes aged HUMAN conversations on the
  same sweep as machine chatter, and it is the wrong lever whenever the policy
  is "delete cron/subagent, keep conversations." The CLI `hermes sessions
prune` _does_ support `--source`; drive that instead. Trap: **any filter
  suppresses the implicit 90-day default**, so `prune --source cron` with no
  age flag matches every cron session ever — always pass `--older-than`.
- **Archiving reclaims zero bytes.** `auto_archive` flips one bit and hides
  sessions from the resume picker; it changes no storage and no
  `session_search` recall. If the user's goal is disk, say so plainly rather
  than shipping archive as the answer.

## Sizing a database before proposing message/row deletion

Before planning any retention or archival work on a large database, measure
where the bytes actually ARE. Row-text totals and file size routinely disagree
by multiples, and acting on the wrong one produces a risky migration that
reclaims little.

Measured on a 5.86 GB Hermes `state.db` this way:

| component                                               | size        |
| ------------------------------------------------------- | ----------- |
| all message text (user + tool + assistant + tool_calls) | 1.93 GB     |
| `messages_fts_trigram_data`                             | **2.78 GB** |
| `messages_fts_data`                                     | 0.62 GB     |

The trigram index alone was larger than every message in the database. The
correct lever was rebuilding FTS without trigram (or `detail=none`) plus
`VACUUM` — reclaiming ~2.8 GB with zero data loss — and NOT the row-pruning
plan that had been drafted.

Measure with `sum(length(...))` grouped by role for text, and per-shadow-table
`sum(length(block))` for FTS internals. Try `dbstat` FIRST — it gives the
cleanest whole-file breakdown in one query and returned promptly on a 2.8 GB
database:

```sql
select name, sum(pgsize) s from dbstat group by name order by s desc limit 20;
```

It is a compile-time-optional virtual table, so fall back to the per-`_data`
`select count(*), sum(length(block))` form when it is missing or slow. State an
estimate as unverified until measured — a plausible-sounding "this will shrink
it to 300-600 MB" was off by several times here.

A second measured instance, on a 2.8 GB `state.db` (470k messages) that had
corrupted repeatedly: `messages` 1254 MB, `messages_fts_trigram_data` **1101 MB**
(40% of the file), `messages_fts_data` 349 MB. Same conclusion — the trigram
index rivals the data it indexes, and dropping it is the large lossless win. Two
independent hosts now show this shape, so **expect FTS to dominate a large Hermes
`state.db` and measure it before drafting any row-pruning plan.**

Within the message text itself, `role='tool'` was 611 MB of 725 MB total, led by
`read_file` (178 MB), `terminal` (152 MB) and `skill_view` (120 MB at a 15.9 KB
average). That makes **truncating stored tool output** a better lever than
deleting conversations — and it sidesteps the orphaned-tool-call hazard below
entirely, because you rewrite `content` rather than delete rows.

🔴 **Never prune `role='tool'` rows while keeping the preceding assistant
message.** Anthropic and OpenAI both hard-validate that an assistant message
carrying `tool_calls` is followed by matching tool responses; orphaning them
returns 400 and makes those sessions permanently un-resumable. Delete whole
conversational turns or rewrite the assistant row to drop `tool_calls` — or,
far better, discover that the bloat was index rather than rows and prune
nothing.
