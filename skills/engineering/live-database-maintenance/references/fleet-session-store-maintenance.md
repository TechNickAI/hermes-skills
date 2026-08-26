# Fleet-wide Hermes session-store maintenance

Use when several Hermes profiles accumulate large `state.db` files, cron/webhook-heavy profiles show write contention, or a one-profile pruning script needs to become a fleet-standard lifecycle.

## Read-only fleet audit first

Inventory every active profile, including co-tenant profiles on shared hosts. For each profile collect:

- `state.db`, `state.db-wal`, and `state.db-shm` sizes
- `PRAGMA page_count`, `page_size`, `freelist_count`, and `journal_mode`
- session/message counts grouped by `sessions.source`
- `sessions.auto_prune`, retention, vacuum, and cron-concurrency settings
- every maintenance job's stored schedule, script, timeout, last error, and latest saved output
- running process/install attribution and the exact gateway supervisor

Treat `last_status: ok` as scheduler status only. Read the latest output and host-side artifacts. An absent pruner is a finding; a lone pruner on one profile is not fleet coverage.

Do not infer reclaimable bytes from file size alone. FTS tables can dominate even when `freelist_count` is small. Use `dbstat` where available or an offline copy to measure table/index components.

## Classify data before choosing retention

Group sources into explicit policy classes:

- Human conversation: Telegram, Slack, CLI, and other owner-facing sessions. Preserve unless separately approved.
- Machine-generated: cron and subagent sessions. Usually eligible for short retention because final outputs already exist elsewhere.
- Webhook/API/batch: classify by producer and downstream value. Do not assume every webhook is disposable; distinguish transient event invocations from durable operational history.

Inspect actual `started_at`, `ended_at`, latest-message timestamps, and `end_reason`. Hermes pruning deletes ended sessions and ages them from recent activity. A count query that returns no old rows may mean sessions were never ended or the timestamp expression is wrong; it does not prove retention is working.

Deletion of historical sessions is an approval-gated data change. Report intended source filters, age windows, and dry-run counts before applying.

## Separate retention from compaction

Do not combine frequent deletion and full-file rewrites into one weekly in-gateway script.

### Online retention sweep

Run lightweight, source-scoped deletion on a daily or similarly appropriate cadence:

- use Hermes' supported session-prune API/CLI
- dry-run and record denominator before first application
- avoid `VACUUM` on every sweep
- emit explicit state even on failure (`probe_ok: false`), never silent success

Config-driven `sessions.auto_prune` is useful for uniform retention of all ended sessions, but it is not a replacement for source-specific policies. Verify the installed Hermes version and current docs before relying on a proposed cron-only retention key; upstream features may still be open PRs.

### Offline compaction

Run only when size/reclaimability warrants it, not merely because Sunday arrived. Candidate triggers include:

- database above a profile-class threshold
- meaningful reclaimable-page/index bloat
- WAL that remains abnormally large after ordinary checkpoints
- measured insert/search latency attributable to the store

Sequence:

1. Prove the gateway is serving and record process/start time.
2. Check room for a verified backup, the rewritten database, WAL, and safety margin. "Free space >= DB size" is not sufficient.
3. Create an online SQLite backup and independently verify it.
4. Stop exactly one target gateway and prove its full process tree is absent.
5. Checkpoint/truncate WAL.
6. Merge/rebuild FTS as appropriate, then `VACUUM`.
7. Start and prove process plus platform/application readiness.
8. Re-read DB/WAL sizes and run integrity checks.
9. Restore the verified backup if maintenance or restart verification fails.

Run profiles serially. On a shared host, never stop or mutate a sibling profile accidentally.

## Why maintenance must run outside the target gateway

A script launched by the target gateway's scheduler competes with that gateway for the same SQLite writer and can be killed by the scheduler timeout while holding expensive work. If the gateway wedges, the maintenance process and its recovery logic can disappear together.

Use an external orchestrator on an independent, always-up host. It should own timeout escalation, backup verification, stop/prove-gone/start recovery, and fleet-level reporting. A target-local deterministic helper is fine, but the controller must remain outside the service being maintained.

## Diagnose the write failure before planning cleanup

Hermes' user-facing "session storage could not be written… often a full disk" message is a symptom class, not a diagnosis. Before deleting anything, distinguish:

- capacity or permission failure
- SQLite logical corruption (`malformed`, `not a database`, failed integrity check)
- a maintenance rewrite or repair already in progress
- an earlier failure whose replacement database is now healthy

Correlate the screenshot time with gateway logs, service restarts, DB inode/size/header changes, repair artifacts, and errors _after_ the latest restart. Re-run a normal `query_only` read and bounded integrity check. Do not report a stale screenshot as current state after a verified repair has landed.

The SQLite database header's "last written using SQLite version" identifies a writer that touched that database image; it does **not** prove the current gateway process is still using that version. Verify the running unit's `ExecStart`, PID start time, and SQLite version from that exact interpreter. This distinction matters when a vulnerable long-lived process wrote corruption before an upgrade or restart.

Repeated corruption and excessive growth can coexist but require separate remedies. Retention/compaction reduces size and memory pressure; it does not repair a corrupted b-tree or prove the corruption bug is gone.

## Find retention blind spots quantitatively

A pruner that exits successfully can still lose ground. For every source, measure:

- session and message counts
- oldest/newest activity
- `SUM(length(messages.content))`, joined through the actual `sessions.id = messages.session_id` contract
- age-bucketed counts and bytes
- major table/index sizes via `dbstat` where safe

Compare every high-volume source against the pruner's explicit source list. Webhook/API/batch traffic is a common blind spot: thousands of short machine-generated invocations can dominate text and FTS storage while a cron/subagent-only pruner reports `ok`. Classify the producer before deletion, then obtain approval for source and retention window.

Estimate reclaim conservatively from measured table/index composition, not a fixed multiplier. State the multiplier as an estimate until an actual prune plus compaction measures the result.

Audit reporting parsers too. If the CLI prints `Pruned 46 session(s).`, a parser anchored to `^[0-9]+ session` returns zero despite successful deletion. Exercise parsers against real saved output and reconcile reported counts with before/after database counts. Scheduler `ok` plus a silent or zero-count report is not proof that retention worked.

Also inventory scheduler metadata separately from transcript storage. Disabled jobs may be operational clutter, but deleting 40 small job records will not materially shrink a multi-gigabyte FTS database. Treat job deletion as a configuration-history decision, not a storage fix.

## Timeout and FTS traps

- A fixed 900-second script timeout is not a valid budget for an 11+ GB FTS-heavy database. Benchmark backup, FTS merge/rebuild, and `VACUUM` on comparable storage before setting the deadline.
- Scheduler termination during a long optimize can leave a large WAL and prolonged lock contention even if SQLite remains logically intact.
- Historical trigram indexes retain old amplification until rebuilt. A newer trigger that stops indexing structured tool JSON slows future growth but does not shrink existing pages by itself.
- Disabling trigram search is a search-quality decision, not generic cleanup. Standard FTS remains, but substring/CJK behavior changes. Evaluate per owner/profile and verify the current installed implementation before rollout.
- `freelist_count` near zero does not mean a multi-GB FTS database is healthy or compact; live indexed content itself may be bloated.

## Verification and state contract

Each run should persist a compact record containing:

- `probe_ok`
- profile and host
- prune dry-run/mutation counts by source
- backup path, size, and integrity result
- before/after DB, WAL, SHM, and free-space values
- compaction reason/trigger
- stop, start, and healthy timestamps plus downtime
- post-start platform readiness
- rollback attempted/result

Alert only on an actionable failure, unsafe capacity, a gateway that did not return, or a decision requiring an owner. Stay silent on healthy no-op sweeps.

## Rollout order

Canary one operator-owned profile first. Validate recall, source filters, backup/restore, restart, and messaging readiness. Then roll through user-facing profiles serially, preserving each profile's local retention policy. Report a denominator covering every active profile, including already-small, unreachable, and pending members.
