# Copied-database retention impact lab

Use this before deleting large classes of Hermes session history from a live profile. It validates selection semantics, database impact, integration invariants, runtime, and temporary disk demand without touching production.

## Safe lab sequence

1. Create an online SQLite backup from the live WAL database with `sqlite3.Connection.backup()`.
2. Reopen the backup independently and require `PRAGMA quick_check` or `integrity_check` to return `ok`.
3. Move a copy to a scratch host with ample disk when the production host is tight. Budget for source + sandbox + WAL + compacted image; a nominally safe delete can temporarily consume several additional gigabytes.
4. Record before-state counts and sizes:
   - database/page/freelist bytes
   - sessions and messages by source
   - ended versus `ended_at IS NULL`
   - system prompts and `session_model_usage`
   - FTS/trigram query results for representative terms
   - routing and dependent-table references
5. Run the installed Hermes CLI in an isolated `HERMES_HOME` against one copy to prove exact product behavior and candidate counts.
6. Run a batched equivalent against a second copy to quantify whether Hermes' implementation shape is operationally acceptable. Match the installed source contract exactly:
   - only `s.ended_at IS NOT NULL`
   - inactivity cutoff is latest message timestamp, falling back to `started_at`
   - orphan child `parent_session_id` references before parent deletion
   - delete messages before sessions
   - enable `PRAGMA foreign_keys=ON` so `session_model_usage` cascades
   - remove unreferenced `system_prompts`
   - let message DELETE triggers maintain standard FTS and trigram FTS
7. After deletion, require `foreign_key_check`, `quick_check`, zero orphan messages/usage/parents, unchanged protected-source counts, and working representative FTS queries.
8. Optimize FTS and `VACUUM` only in the isolated lab. Record delete time, vacuum time, peak WAL, and final file size.
9. Remove temporary on-host sandboxes promptly after measuring them, then verify production health and confirm its DB was untouched.

## Verified Hermes behavior and operational trap

Hermes' supported bulk prune semantics are functionally sound: active sessions are excluded; ended sessions age from latest activity; message DELETE triggers remove corresponding FTS rows; session usage cascades; children outside the deletion set are preserved by clearing their parent link; unreferenced prompt snapshots are removed.

The implementation may still be operationally unsuitable for a high-volume source. `SessionDB.prune_sessions()` iterates candidate session IDs and issues per-session message/session DELETEs inside one write transaction. In a production-shaped 5.39 GB copy containing 14,258 sessions and 455,613 messages, pruning ended cron, subagent, and webhook sessions inactive for seven days produced:

- 10,939 sessions and 92,897 messages deleted
- file size unchanged until compaction
- 5.39 GB -> 2.06 GB after FTS optimize + `VACUUM`
- integrity and foreign-key checks clean
- Telegram and CLI session counts unchanged

On a roomy scratch Mac, a batched equivalent deleted in about 64 seconds and vacuumed in about 6 seconds. The installed Hermes CLI against an isolated copy on the production Linux host took about 16 minutes and grew a roughly 3.3 GB WAL, temporarily pushing disk use from about 85% to 92%. Therefore, validate both semantic correctness and implementation shape; a correct API is not automatically a safe maintenance mechanism at scale.

## Historical ghost-session implication

Bulk prune deliberately ignores `ended_at IS NULL`. Old completed one-shot producers can therefore remain forever if an earlier runtime failed to close them. A copied production DB contained large old populations of webhook, cron, and subagent rows with null `ended_at`; Hermes' own webhook regression test documents this historical leak.

Do not solve this by deleting every old null-ended row. Classify against current routing, live ownership/process state, source-specific completion semantics, and latest activity. Close only machine sessions proven abandoned, then let the ordinary ended-session retention policy reap them. Treat Telegram and CLI null-ended sessions conservatively.

## Design consequence

For large machine-generated stores, prefer an external controller:

- online, source-scoped batched retention without daily vacuum
- offline compaction only when reclaimable space justifies it
- verified backup and rollback
- stop/prove-gone/start around the compacting rewrite
- production application readiness verification afterward

Keep cron output-file retention, execution-ledger retention, disabled job definitions, and session transcript retention as separate policies. Hermes may bound output by count and executions globally while the owner wants age-based retention; those are not equivalent.
