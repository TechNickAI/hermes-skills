# Hermes session prune and optimize semantics

Use this reference when auditing or planning `hermes sessions prune`, `optimize`, or `optimize-storage` against a profile store. Re-check the installed source before acting; names and line numbers drift by release.

## Installed-source audit map

Start with these functions and trace the live call chain rather than relying on help text:

- `hermes_state.py:SessionDB.__init__` and `_default_db_path` — database-path resolution.
- `hermes_cli/main.py:_apply_profile_override` — early `--profile` / `-p` handling and `HERMES_HOME` behavior.
- `hermes_cli/sessions_cmd.py:handle_sessions_command` — which `SessionDB` is opened and whether a `sessions_dir` is passed.
- `hermes_cli/session_filters.py:build_prune_filters` / `parse_point_in_time` — CLI time semantics.
- `hermes_state.py:SessionDB._prune_filter_where`, `list_prune_candidates`, and `prune_sessions` — exact selection and deletion SQL.
- `hermes_state.py:SessionDB._remove_session_files` and `_delete_unreferenced_system_prompts` — non-row cleanup.
- `hermes_state_search.py:SessionSearchMixin.optimize_fts` / `optimize_fts_storage` and `hermes_state.py:SessionDB.vacuum` — FTS merge, migration, checkpoint, and `VACUUM` behavior.
- `gateway/session.py:SessionStore._prune_stale_sessions_locked`, `_is_session_ended_in_db`, `_persist_routing_data`, and `_save_sessions_json` — routing and mirror implications.
- `tools/async_delegation.py` durable-ledger functions and `gateway/delivery_ledger.py` — out-of-band completion/delivery references.

Cite exact `file:function` and current lines in the audit report. Confirm the source revision/install path first.

## Selection contract

In the audited v0.20-era implementation:

- `_prune_filter_where` starts with `s.ended_at IS NOT NULL`; active/unended rows are structurally excluded even if ancient.
- `--older-than` / `--newer-than` bind **last activity**, computed as `MAX(messages.timestamp)` with `sessions.started_at` as the empty-session fallback.
- `--before` / `--after` bind `sessions.started_at`, not end time or last activity.
- Relative durations are converted from `time.time()` to epoch seconds; a bare numeric `--older-than` remains backward-compatible days.
- Bounds are asymmetric: upper bounds use `<`; lower bounds use `>=`.
- `ended_at` is only an eligibility gate. It is not the age value.

Always verify these expressions in the installed version and compare dry-run candidate IDs/counts with an equivalent `PRAGMA query_only=ON` query.

## Exact deletion surface to inspect

Typical prune behavior is:

1. Select matching ended session IDs.
2. Set surviving children's `parent_session_id` to `NULL` when their parent is selected.
3. Explicitly delete `messages` rows for each selected session.
4. Delete the corresponding `sessions` rows.
5. Remove now-unreferenced shared `system_prompts` rows.
6. Optionally remove transcript/request-dump files outside the DB transaction when `sessions_dir` is supplied.

Dependent effects:

- Message `AFTER DELETE` triggers issue FTS5 delete commands for the standard and, for non-tool rows, trigram indexes. Enumerate both virtual tables, triggers, and all shadow tables from `sqlite_schema`.
- `session_model_usage` is normally removed by `ON DELETE CASCADE`; confirm `PRAGMA foreign_keys=ON` on the actual connection rather than inferring from schema alone.
- Parent/child session links use `NO ACTION`; prune deliberately orphans surviving children rather than deleting a lineage recursively.
- Shared system-prompt cleanup can remove any globally unreferenced prompt, not merely one unique to the selected sessions.
- Routing, delivery, delegation, and compression-lock tables may contain session IDs without declared foreign keys. Prune does not automatically clean them; inspect each as a soft-reference dependency.

During an incremental FTS storage rebuild, delete triggers may be gated by rebuild high-water/progress metadata. Do not assume index cleanup occurred merely because canonical message deletion committed; settle or rebuild FTS before judging orphan/index space.

## Lifecycle safety gates

`ended_at IS NOT NULL` is necessary but not always sufficient for safe removal:

- Webhook and cron runners should end terminal sessions with explicit reasons (for example `webhook_complete` / `cron_complete`). Confirm the installed finalizer and inspect for historical ghost rows with `ended_at IS NULL`.
- Synchronous subagent children normally close their `SessionDB` session in a `finally` path. Parent/child transcript retention is separate from durable async-completion delivery.
- For async delegates, check `async_delegations.state`, `delivery_state`, claims, and origin/parent soft references. An ended parent can still have a terminal result pending delivery unless the lifecycle guarantees otherwise.
- Check `delivery_obligations` for pending/claimed work keyed to the same gateway route.
- Active compression locks are a separate soft-reference table. An ended row with a live lock is an inconsistency to investigate, not a candidate to force-delete.

Safe automation should exclude or abort on candidates with running/finalizing or pending/claimed external obligations, unless the installed code proves those states cannot coexist.

## Gateway routing and `sessions.json`

The transcript store and gateway routing index are separate concerns:

- `gateway_routing.entry_json` maps a messaging `session_key` to a session ID and has no FK to `sessions` in the audited schema.
- `sessions/sessions.json` is a legacy mirror of routing, not the transcript/session history list.
- Deleting a `sessions` row does not itself delete the routing row, rewrite `sessions.json`, or evict a running gateway's in-memory `SessionStore` entry.

Before pruning, count candidate IDs referenced by `gateway_routing`; treat any match as a routing-state inconsistency. Read both startup stale pruning and per-turn missing/ended-row behavior in the installed `SessionStore`. Do not assert that a missing session row is healed the same way as an ended row without reading `_is_session_ended_in_db` and the recovery path.

## Safely targeting a copied database

The ordinary `sessions prune`, `optimize`, and `optimize-storage` commands historically expose no direct `--db-path`. `SessionDB()` resolves `<HERMES_HOME>/state.db`.

For a copy-only investigation or destructive rehearsal:

1. Create a self-contained throwaway Hermes home with the copied `state.db` and any sidecars captured consistently by SQLite backup/snapshot semantics.
2. Invoke the installed CLI with an explicit `HERMES_HOME=/absolute/throwaway/home` and clear any sticky/global profile variables that could alter resolution.
3. Prefer an explicit `--profile/-p` only when intentionally targeting an existing named profile; it resolves under the profile root and is not an arbitrary DB-path flag.
4. Do **not** treat `HERMES_PROFILE` alone as the CLI's general database selector unless the installed `_apply_profile_override` explicitly reads it. In the audited implementation, early CLI routing is driven by `--profile/-p`, `HERMES_HOME`, and `active_profile`; other modules may use `HERMES_PROFILE` only as a label.
5. Before any mutation, use a harmless source-level resolver probe or read-only command and print/verify `SessionDB.db_path` equals the copied file. Abort on mismatch.
6. Ensure no gateway or scheduler shares the throwaway home. Copy tests should not touch production `sessions/`, routing JSON, or config.

Do not point `HERMES_HOME` at a directory containing only a copied filename with a nonstandard name: `SessionDB()` still expects `state.db`. Avoid configuration edits just to redirect a one-off rehearsal.

## Optimize distinction and risks

- `sessions optimize` generally performs FTS5 segment `optimize`, a best-effort WAL checkpoint, then full `VACUUM`. It is layout-only but lock- and disk-intensive.
- `sessions optimize-storage` is a resumable FTS layout migration/backfill/teardown and optional final `VACUUM`; it changes index schema/layout, not canonical conversation rows.
- Neither is a substitute for prune: deleting rows and reclaiming file bytes are separate phases.
- `VACUUM` needs substantial temporary disk and exclusive access; on WAL, readers can prevent checkpoint fold-back even after the logical page count shrinks.
- Measure result with SQLite page accounting and integrity/search probes, not only `stat(state.db)`.
- A live gateway makes copy targeting and offline rehearsal preferable; never infer safety from the CLI phrase "no data change," because maintenance still rewrites the full database and can block writers.

## Minimum audit output

Report:

- installed revision/path and exact CLI wrapper/interpreter
- resolved database path and profile-routing proof
- candidate time expression and ended-session gate
- affected canonical, dependent, FTS, shadow, and file artifacts
- counts of candidate soft references in routing/delegation/delivery/locks
- active/unended and source/end-reason distributions
- copy-target method plus a fail-closed path verification
- prune and optimize lock/disk/WAL/FTS risks

Keep evidence clearly separated from recommendations; a read-only audit must not execute prune, optimize, `PRAGMA optimize`, FTS integrity commands that write, schema initialization against production, or `VACUUM`.
