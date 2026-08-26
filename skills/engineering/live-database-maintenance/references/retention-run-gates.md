# Retention-run verification matrix

| Gate              | Evidence required                                                                                | Failure action                                 |
| ----------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| Service preflight | Exact process fingerprint present; application HTTP health succeeds; latency recorded            | Abort without touching DB                      |
| Schema            | Every target table and timestamp column exists                                                   | Abort before backup/stop                       |
| Timestamp unit    | Producer expression + cleanup/query source + live `typeof`/sample/min/max agree                  | Abort on unresolved contradiction              |
| Disk              | Backup + VACUUM temporary image + reasonable margin fit                                          | Abort before backup/stop                       |
| Backup            | Online API completed; regular nonempty file; plausible size; reopened independently; checks `ok` | Remove partial; abort before stop              |
| Stop proof        | Supervisor stop issued and process fingerprint absent                                            | Do not mutate; recover service                 |
| Delete            | Exact allowlist, parameterized predicates, one transaction, `.changes` saved                     | Roll back transaction; enter recovery          |
| Checkpoint        | Process absent and checkpoint non-busy/successful                                                | Enter recovery; no more maintenance            |
| VACUUM            | Process absent before and after; command completed; DB closed                                    | Enter recovery                                 |
| Startup           | Exact process present and application HTTP health succeeds                                       | Recovery ladder, then backup restore if needed |
| Reconciliation    | Before counts, delete changes, post counts, and post-start insert arithmetic recorded            | Flag discrepancies                             |

## Seconds-versus-milliseconds contradiction pattern

A durable failure mode is inconsistent source code around one integer timestamp:

- the table schema says only `INTEGER`,
- an insert path uses `Date.now()` (milliseconds),
- a cleanup helper computes `Math.floor(Date.now()/1000)` (seconds),
- a separate reset path may label the same column `epochMs`,
- the live table has zero rows.

This evidence does **not** support either unit conclusively as the operational contract. The correct maintenance decision is to abort before stop and report the exact source expressions. Do not let an operator-provided expectation override contradictory checkout evidence, and do not infer safety from zero current rows—the next inserted row will still follow the producer.

## Online-backup failure interpretation

A backup call against a healthy live WAL database may return a transient corruption-shaped error. Handle two questions separately:

1. **May maintenance proceed?** No, not without a verified backup.
2. **Is the source DB proven corrupt?** Also no, not from one live backup/read error.

Retry according to the run's policy with fresh handles. If no verified backup can be produced, remove partial output, leave the router running, and report an abort before stop. Diagnose corruption only from repeatable, independently checked evidence.

## Factual abort report

For an abort before stop, include:

- outcome and exact blocking gate,
- whether any DB mutation occurred,
- whether a verified backup exists,
- all cutoff forms already computed,
- DB size and preflight table counts,
- preflight and final process/HTTP health,
- downtime explicitly as zero,
- no fabricated post-maintenance size/counts.
