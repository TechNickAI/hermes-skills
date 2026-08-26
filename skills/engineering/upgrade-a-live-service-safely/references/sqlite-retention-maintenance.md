# the router SQLite retention-maintenance cron

Created One case: a scheduled cron job that prunes the `storage.sqlite`
DB on a weekly cadence, deleting rows past a 7-day retention window across 12
telemetry/audit tables, then VACUUMing to reclaim space. Distinct from monitoring
(read-only probes) and deployment (fresh install) — this is the **mutate-the-live-DB
while the service is stopped** class. Companion to the `the router` skill (which is
manually authored and cannot be edited by curation — the router-specific learnings
go here with a cross-reference).

## Why the order is non-negotiable

the router keeps a ~64 MB SQLite page cache in memory. External deletes made while
the router is running **reappear** when the router flushes stale cached pages back
to disk. The only valid mutation sequence is:

```
stop service → prove process gone → mutate DB → start service
```

Never delete, checkpoint, VACUUM, replace, or restore the live DB while
`dev/run-standalone` (or `the router serve`) is running. The process match string
is `pgrep -f 'dev/run-standalone'`.

This is the same governing rule as the skill's main body — never let a mutation
and the running service share the same DB — applied to retention pruning rather
than a build/upgrade. The `sqlite-live-wal-false-corruption.md` reference in this
skill covers the related trap of `?mode=ro` URI connections fabricating corruption
on a live WAL database.

## Fixed targets (AWS EC2 production box)

- **DB**: `/home/ubuntu/.the router/storage.sqlite`
- **Repo providing better-sqlite3**: `/home/ubuntu/src/the router`
- **Backup directory**: `/home/ubuntu/the router-backups`
- **User service**: `the router` via `systemctl --user`
- **Process proof**: `pgrep -f 'dev/run-standalone'`
- **Health URL** (checked on the router): `http://127.0.0.1:20128/api/monitoring/health`
- **Retention**: exactly 7 days, one consistently computed UTC cutoff
- **SSH alias**: `the router` → `ubuntu@<router-host>`

## The `sqlite3` CLI prohibition

The `sqlite3` CLI intermittently reports a false/transient `database disk image is
malformed` on this DB even when snapshot integrity checks pass (see also
`sqlite-live-wal-false-corruption.md` in this skill). **Always use `better-sqlite3`
from inside `/home/ubuntu/src/the router`** for every SQLite operation: counts,
online backup, deletes, checkpoint, VACUUM, integrity checks. Prefer `node -e` with
inline JS; for complex scripts, write a `.cjs` file into the repo tree (`.cjs`
because the package is `"type":"module"`).

Retry read/open/count operations up to 10 times with a short delay, closing and
reopening the DB between attempts. Do not interpret one transient torn-read error
as corruption.

## The 12-table retention schema

Each table has a specific timestamp column and format. The cutoff instant is
`run_time - 7*24h`, derived into four representations:

| Representation               | Example                    | Used by                     |
| ---------------------------- | -------------------------- | --------------------------- |
| ISO UTC text                 | `2026-07-27T13:51:00.000Z` | most tables                 |
| SQL-style UTC text           | `one occasion 13:51:00`    | `xp_audit_log`              |
| epoch milliseconds (integer) | `1753624260000`            | `domain_cost_history`       |
| epoch seconds (integer)      | `1753624260`               | `compression_run_telemetry` |

Table/column/format mappings (verified one occasion):

| Table                       | Column                         | Format                              |
| --------------------------- | ------------------------------ | ----------------------------------- |
| `quota_snapshots`           | `created_at`                   | ISO text                            |
| `call_logs`                 | `timestamp`                    | ISO text                            |
| `usage_history`             | `timestamp`                    | ISO text                            |
| `compression_analytics`     | `timestamp`                    | ISO text                            |
| `mcp_tool_audit`            | `created_at` (NOT `timestamp`) | ISO text                            |
| `a2a_task_events`           | `created_at` (NOT `timestamp`) | ISO text                            |
| `memories`                  | `created_at`                   | ISO text                            |
| `domain_cost_history`       | `timestamp`                    | INTEGER epoch **ms**                |
| `compression_cache_stats`   | `created_at`                   | ISO text                            |
| `xp_audit_log`              | `created_at`                   | TEXT `YYYY-MM-DD HH:MM:SS` (no T/Z) |
| `compression_run_telemetry` | `timestamp`                    | INTEGER epoch **seconds**           |
| `proxy_logs`                | `timestamp`                    | ISO text                            |

**Pre-flight verification for `compression_run_telemetry.timestamp`**: verify both
the source in the checkout AND actual `typeof`, representative values, min, and max
where rows exist. It is expected to be INTEGER Unix epoch seconds. If source/data
do not support epoch seconds, abort before stopping; do not guess a cutoff
representation.

**Column-name traps**: `mcp_tool_audit` and `a2a_task_events` both have a
`timestamp` column, but the retention cutoff applies to `created_at`, not
`timestamp`. Getting this wrong deletes the wrong rows or no-ops silently.

## Full sequence

### 1. Pre-flight (router running)

- Confirm host reachable, process alive, health endpoint HTTP 200. Measure latency.
- Record DB byte size, free disk space, per-table row counts.
- Verify `compression_run_telemetry.timestamp` format (see above).
- Abort if disk space insufficient for backup + VACUUM temp.

### 2. Online backup (router still running)

- `better-sqlite3` online backup API (SQLite `.backup` equivalent) to
  `/home/ubuntu/the router-backups/storage.sqlite.preclean-<UTC ts>`.
- Verify backup exists, is 80–120% of live DB size, and passes `integrity_check`.
- Abort if verification fails — never proceed on an unverified backup.

### 3. Stop and prove stopped

- Record exact UTC stop-command time (epoch ms for downtime measurement).
- `systemctl --user stop the router`.
- Poll `pgrep -f 'dev/run-standalone'` until no match.
- If process won't die, abort without touching the DB.

### 4. Delete expired rows (service stopped)

- One `better-sqlite3` transaction, parameterized `DELETE... WHERE <col> < ?`.
- Save `.changes` per table.
- If any statement fails, transaction rollback → recovery.

### 5. Checkpoint and compact (still stopped)

- `PRAGMA wal_checkpoint(TRUNCATE)` — require non-busy result.
- `VACUUM` — wait for completion.
- Close DB cleanly.

### 6. Start and verify

- Record exact UTC start-command time.
- `systemctl --user start the router`.
- Poll health URL up to 90s for HTTP 200.
- Confirm `pgrep -f 'dev/run-standalone'` finds the process.
- Record total downtime (stop epoch → healthy HTTP 200).

### 7. Post-flight (router healthy)

- Re-record DB size + per-table row counts.
- Compute deltas, reconcile with `.changes` from the delete transaction.
- Distinguish post-start new inserts from deletion counts.
- Keep the verified backup; do not prune old backups in this job.

## Recovery: if the router fails to restart

1. Mark run as in recovery; no further DB mutations.
2. Inspect `systemctl --user status the router`, `journalctl --user -u the router`,
   process state, DB/WAL/SHM files, disk space, health errors.
3. Attempt safe recovery: stop/confirm gone, start again, poll health.
4. If still unhealthy: stop, prove gone, **restore the verified preclean backup**:
   - Preserve the failed post-clean DB under a diagnostic filename.
   - Restore backup to `/home/ubuntu/.the router/storage.sqlite`.
   - Remove incompatible `storage.sqlite-wal` and `storage.sqlite-shm` (only while
     process confirmed gone).
   - Preserve ownership/permissions.
   - Start service, poll health for another 90s.
5. If backup restore recovers health → report `ROLLED BACK/RECOVERED`.
6. If even the backup doesn't restore → report `CRITICAL: ROUTER STILL UNHEALTHY/DOWN`.
   Never claim success on `systemctl start` exit code alone — success requires both
   process presence AND HTTP 200 (same verification doctrine as the skill's main
   body: exit 0 is not proof).

## Cron job creation pattern

### The `cronjob` tool's model/provider/base_url are NOT agent-settable

The `cronjob` tool schema intentionally does NOT read `model`, `provider`, or
`base_url` from the agent's arguments. Per-job inference pins are user-owned
(set via dashboard, `hermes cron create/edit --model`, or hand-edited `jobs.json`).
The agent cannot pin a model for a maintenance job — if a specific model is needed,
tell the user to set it manually.

### 🔴 Create it RECURRING, then trigger the first run manually

**Do NOT use the "one-shot ISO timestamp ~5 minutes out, reschedule later"
pattern.** It was tried on one occasion and lost the job entirely:

- A subagent took **13.5 minutes** to register a job scheduled to fire in 5, so
  the window had already passed by the time it existed.
- Calling `cronjob(action="run", job_id=...)` on the missed one-shot **consumed
  and deleted it without executing** — `execution_success: false`, the router
  untouched, and no job left in `jobs.json`.

A one-shot is spent by any trigger, whether or not the work ran. Instead:

```
cronjob(action="create", schedule="0 9 * * 0",...) # real recurring cadence
cronjob(action="run", job_id="<id>") # immediate validation run
```

`action="run"` on a **recurring** job executes now and leaves `next_run_at`
intact — you get the validation run and the schedule from one registration.
Confirm with `last_status: "ok"` **and** `execution_success: true`; either alone
can mislead.

**Recover the prompt if a job is lost.** A ~10k-char self-contained prompt is
expensive to regenerate. Subagents that build cron jobs should write the prompt
to a file (`/tmp/<name>-prompt.txt`); it survives the job's deletion and can be
read straight back into a new `cronjob(action="create")`. Grep the delegation
live transcript for the path:

```bash
grep -oE "/[A-Za-z0-9._/-]+\.(md|txt)" \
  ~/.hermes/profiles/<p>/cache/delegation/live/<deleg_id>/task-0.log | sort -u
```

### Verify a delegated cron prompt yourself before letting it run

Never trust a subagent's report that a maintenance job is safe. Read the stored
prompt out of `jobs.json` and assert the safety-critical elements are present —
this catches a plausible-looking prompt that silently omits the stop step:

```python
j = [x for x in json.load(open('cron/jobs.json'))['jobs']
     if x.get('job_id') == JOB_ID][0]
p = j['prompt']
for name, needle in [
    ("stop service", "systemctl --user stop the router"),
    ("verify gone", "pgrep"),
    ("backup first", "preclean"),
    ("abort if bad", "ABORT"),
    ("VACUUM", "VACUUM"),
    ("restart", "systemctl --user start the router"),
    ("health poll", "monitoring/health"),
    ("no CLI", "better-sqlite3"),
    ("torn-read retry", "malformed"),
    ("epoch ms gotcha", "MILLISECOND"),
    ("recovery", "journalctl"),
    ("restore on fail", "restore"),
]:
    print(("OK " if needle in p else "MISSING"), name)
```

Note `jobs.json` is `{"jobs": [...]}` — a **list**, not a dict keyed by id.

### State the downtime cost before firing a validation run

This job stops the router for the whole fleet. Say so and get a yes before
triggering it mid-day, and confirm the prompt puts the expensive work _outside_
the outage window (pre-flight + the ~350 MB online backup happen while the
service is still healthy; only delete/checkpoint/VACUUM run stopped). Add an
explicit instruction to the prompt so a future agent cannot drift:

> Target total downtime under 3 minutes. Do not do any exploratory work, schema
> discovery, or verification queries during the stopped window that could have
> been done before stopping.

Measured result with that ordering: backup at 19:10:36, healthy again at
19:11:37 — **well under a minute** of actual outage.

### Prune old backups in the same job

The original prompt kept every ~350 MB backup forever. Add: delete backups older
than 30 days, always keeping the 4 most recent regardless of age.

### Deliver to origin

Use `deliver="origin"` (or omit `deliver` on a messaging platform) so the
maintenance report routes back to the chat that created the job.

### Prompt must be self-contained

Cron jobs run in a fresh agent session with no chat context. The prompt must contain
everything the agent needs: SSH alias, host IP, DB path, repo path, table mappings,
recovery procedure, and the report format. The full prompt for the first job is
~10,165 chars and can be reused verbatim for the weekly version.

### Remote execution rules

- SSH alias `the router` → `ubuntu@<router-host>`.
- Remote login shell is **zsh** — every remote bash payload must use:
  `ssh the router 'bash -s' <<'EOF'... EOF`
- Filter harmless SSH/login noise: `grep -viE "gitstatus|setopt|exec zsh|GITSTATUS"`
  while preserving the real exit status.
- For complex Python/JS probes, `scp` a file rather than inline heredocs —
  nested quotes break (same lesson as `router-outage-postmortem.md`).

## Job registered (validated one occasion)

- **job_id**: `dcd5beba61b6`
- **Name**: `the router-weekly-db-maintenance`
- **Schedule**: `0 9 * * 0` (Sundays 09:00 Central — low traffic)
- **Repeat**: forever · **Deliver**: `origin`
- **enabled_toolsets**: `["terminal", "file"]` (trims input-token overhead)
- **Validation run**: triggered via `action="run"`; backup
  `storage.sqlite.preclean-20260803T191036Z` (353 MB), service healthy again at
  19:11:37 UTC, HTTP 200 in 0.010s.

A predecessor job (`276de6bbc81c`) was registered as a one-shot and destroyed by
the missed-window trap above — see that section before creating another.

**Verify the outcome on the host, not from the delivered report.** The
`deliver: origin` message did not arrive in the originating thread on the
validation run; the run was confirmed instead by checking the backup file
timestamp, `systemctl --user show the router -p ActiveEnterTimestamp`, and a live
health probe. Treat missing delivery as a reporting gap, not a failed run —
but always confirm from the box.
