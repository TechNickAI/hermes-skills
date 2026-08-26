# Unattended live `VACUUM`: operational review gates

Use this when reviewing a recurring maintenance job that intentionally leaves a SQLite-backed service running during `VACUUM`.

## Availability is bounded by the application's patience, not SQLite's connection timeout

Do not describe live `VACUUM` categorically as "a stall, not an outage." Establish:

1. The application's routine- and critical-write retry budgets.
2. Which writes are required to accept or complete a user request.
3. The user-visible behavior after those budgets expire.
4. Measured `VACUUM` and trailing-checkpoint duration on a representative database and storage class.

A connection `timeout`/`busy_timeout` limits how long the maintenance connection waits to acquire a lock; it is not a wall-clock deadline for a `VACUUM` already running. A multi-gigabyte rebuild can therefore outlast application retry budgets and turn a "stall" into failed requests or turns that must be resent.

For Hermes specifically, inspect the deployed version rather than assuming constants. A reviewed build used about 20 seconds for routine writes and 60 seconds for transcript-critical writes; exceeding the latter produced `session_persistence_failed` and a user-facing resend instruction.

## Disk gate must model all simultaneous copies

SQLite documents that ordinary `VACUUM` may itself require up to roughly twice the original database size in free space. If the job first creates a full backup, calculate pre-run space for:

- the full backup;
- SQLite's `VACUUM` temporary/rewrite requirement;
- existing and growing WAL;
- filesystem/OS reserve and unrelated host growth.

Therefore, a pre-run `2.5 × db_size` free-space rule can be unsafe: after the backup consumes `1 ×`, only `1.5 ×` remains for an operation documented to need up to `2 ×`. For a 6.7 GB database, `2.5 ×` is about 16.75 GB, while backup plus worst-case `VACUUM` is already near 20.1 GB before reserve.

Re-check space after backup creation and before compaction. Measure actual peak usage during canarying.

## Size alone is a poor compaction gate

A threshold such as "VACUUM every week when DB >= 500 MB" makes every permanently large database undergo weekly exclusive maintenance even when little space is reclaimable. Gate on expected reclaimable bytes and percentage, deletions/freelist evidence, minimum interval since the last successful compaction, and measured cost. Retention may run weekly while compaction runs only when benefit justifies disruption.

## Concurrency controls must be enforced

Nominally staggered schedules do not prevent overlap caused by overruns, retries, clock/scheduler behavior, or manual runs. Require:

- a per-database single-instance lock;
- a host-wide maintenance lease when multiple profiles share one disk;
- stale-lock and retry semantics.

Separate databases still compete for free space and I/O. Two jobs can both pass preflight and then exhaust the same volume.

## Do not amplify an existing incident

Before destructive work, fail closed when the service or host is already degraded: gateway not ready, elevated SQLite lock rate, platform backlog, disk/memory pressure, active conversation if required by the SLO, or another maintenance/incident flag. Skipping should emit one actionable failure signal, not an all-clear and not repeated noise.

## Silent success still needs a monitor

`probe_ok` and an exit code are payloads, not an alerting design. A recurring job needs an external consumer that:

- keeps healthy runs silent;
- records last success and key metrics;
- alerts once, with deduplication, on nonzero exit, `probe_ok=false`, stale/missed execution, repeated compaction skips, integrity failure, unsafe disk trend, or failed post-run readiness;
- preserves phase reached, profile/host, elapsed time, backup path, and recovery guidance in failure reports.

A scheduler's "dispatched" status is not proof the maintenance succeeded.

## Retention policy for machine sessions

Do not choose a short horizon solely because a session source is machine-generated. Ten days preserves only about one prior weekly cycle and can erase evidence before intermittent failures are investigated. A practical starting policy is:

- ordinary repetitive successful runs: at least 30 days;
- failed/anomalous runs or last-N executions per job: 60–90 days;
- compact summaries and operational metrics: longer;
- subagent work: separate policy from repetitive cron chatter.

Validate against actual incident-debugging and audit needs.

## Canary promotion gate

Before a large user-facing database:

1. Review fleet-wide dry-run counts and first-run backlog.
2. Benchmark a representative copy on the same storage class, including backup, prune, `VACUUM`, checkpoint, integrity check, peak disk, WAL, CPU, memory, and I/O latency.
3. Exercise a low-risk live canary by sending traffic during `VACUUM`; record maximum delay, failed writes/turns, and resend behavior.
4. Inject disk-gate failure, prune failure, lock timeout, integrity failure, and process interruption; prove the verified backup survives and alerts include its path.
5. Rehearse restore with external lifecycle control and post-restore service checks.
6. Observe at least one full scheduled interval without increased lock failures, ingress backlog, WAL growth, or search regressions.
7. Promote incrementally, with explicit pause criteria before the largest user-facing database.

## Operator documentation checklist

Documentation is outage-preventive only if it includes:

- measured disruption expectations and application retry budgets;
- enforced overlap prevention, not only advice to stagger;
- conservative disk math and reserve policy;
- degraded-host/active-incident skip conditions;
- backup retention on every failure path;
- an exact externally controlled restore runbook, including WAL/SHM handling and integrity/readiness verification;
- automated post-run application probes, not only database `quick_check`;
- silent-success alert routing and missed-run detection;
- staged rollout and rollback/pause criteria.
