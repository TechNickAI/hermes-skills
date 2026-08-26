# Safely mutating a SQLite DB owned by a live process

Context: the router, `better-sqlite3`, DB at `~/.the router/storage.sqlite`.
Every external mutation attempt silently reverted. Everything below is measured.

## The symptom: deletes that vanish

```
Jul-20 rows: 22515 -> 0 (deleted 22515)
... 6 seconds later...
after 6s, Jul-20 rows: 22515 <-- RESTORED
```

July 20 data — a date the running router **cannot** be writing. So this is not
the app re-inserting. Something overwrote the file.

Earlier variants of the same failure:

- `sqlite3` CLI bulk delete reported 341,383 rows deleted; counts returned to
  original.
- Chunked 10k deletes counted 110k → 30k, then **jumped back to 100k**.
- A test table created externally vanished within 2 seconds.
- `PRAGMA wal_checkpoint` returned `{"log":0,"checkpointed":0}` with no
  `-wal`/`-shm` sidecars on disk, yet mtime updated every few seconds.

## The mechanism

The live process holds a **64 MB SQLite page cache**
(`cacheSize: 65536` in `src/types/databaseSettings.ts`). Your external write
lands on disk; the router still holds those pages in memory; on its next write it
flushes its stale pages over yours. Row counts even keep climbing
(246850 → 246855) while your delete evaporates.

`wal_checkpoint(TRUNCATE)` makes the delete **momentarily** visible —

```
before=22515 after_delete=0 after_checkpoint=0
t+0s (new connection): 0
```

— and then it reverts anyway once the router writes again. Checkpointing is not
a fix; it only narrows the window.

## The only reliable sequence

```
stop service → prove the process is gone → mutate → checkpoint → VACUUM → start
```

```bash
systemctl --user stop the router
for i in 1 2 3 4 5 6; do pgrep -f "dev/run-standalone" >/dev/null || break; sleep 2; done
pgrep -f "dev/run-standalone" >/dev/null && { echo "STILL RUNNING - abort"; exit 1; }
#... deletes via the app's own better-sqlite3...
# PRAGMA wal_checkpoint(TRUNCATE); VACUUM;
systemctl --user start the router
for i in $(seq 1 18); do
  [ "$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:PORT/api/health)" = 200 ] \
    && { echo "healthy"; break; }
  sleep 5
done
```

Measured downtime for a 520 MB DB: **~75 seconds** (deletes + 6.2s VACUUM). A
later 12-table run took ~2.5 min; a small single-key update took **17 seconds**.

**Verify persistence AFTER the restart, not before.** Pre-restart counts prove
nothing — the whole failure mode is post-restart reversion.

## Minimize the downtime window

Everything that can run while the service is up, must:

| Phase                                                 | Service     | Why                            |
| ----------------------------------------------------- | ----------- | ------------------------------ |
| Pre-flight: row counts, disk space, schema checks     | **running** | pure reads                     |
| Online backup (`.backup` API) — the slowest step      | **running** | 353 MB backup off the hot path |
| Backup verification (size 80–120%, `integrity_check`) | **running** | abort here costs zero downtime |
| STOP → deletes → checkpoint → VACUUM → START          | **stopped** | the only mutation window       |
| Post-flight counts, latency measurement               | **running** | pure reads                     |

Explicitly instruct any agent doing this: _"Do not do exploratory work, schema
discovery, or verification queries during the stopped window that could have been
done before stopping."_ Target: under 3 minutes.

## Use the app's own driver, not the CLI

The `sqlite3` CLI intermittently reported `database disk image is malformed` on a
DB that was **fine** (`PRAGMA integrity_check` on a clean snapshot = `ok`). It's a
transient torn read against a live writer. Use the app's `better-sqlite3` with a
retry loop:

```js
function go() {
  const D = require("better-sqlite3")(FILE, { readonly: true });
  /*... */ D.close();
  return r;
}
var r = null;
for (var i = 0; i < 10 && !r; i++) {
  try {
    r = go();
  } catch (e) {
    if (i == 9) throw e;
  }
}
```

## Column/format gotchas found by actually querying (never guess)

A 7-day retention purge across the 12 tables the app's own `runAutoCleanup()`
targets. Column names and time formats are **not** uniform:

```
quota_snapshots created_at ISO text
call_logs timestamp ISO text
usage_history timestamp ISO text
compression_analytics timestamp ISO text
mcp_tool_audit created_at ISO text <- NOT `timestamp`
a2a_task_events created_at ISO text <- NOT `timestamp`
memories created_at ISO text
domain_cost_history timestamp INTEGER epoch MILLISECONDS
compression_cache_stats created_at ISO text
xp_audit_log created_at TEXT 'YYYY-MM-DD HH:MM:SS' (no T/Z)
compression_run_telemetry timestamp INTEGER epoch seconds (VERIFY per source)
proxy_logs timestamp ISO text
```

A first pass using epoch **seconds** against `domain_cost_history` deleted **0
rows** and looked like "already clean." Only comparing the column type
(`PRAGMA table_info`) and `MIN`/`MAX` values against the cutoff exposed it:

```
domain_cost_history timestamp type: INTEGER
  min: 1784487629606 max: 1785781075850 <- 13 digits = milliseconds
```

**A delete that removes 0 rows is a claim to verify, not a result to report.**
Check whether the table is genuinely inside retention (`MIN(col)` newer than the
cutoff) before concluding nothing needed deleting.

## Results worth knowing

```
520 MB -> 331 MB (12 tables, 342k+ rows, VACUUM reclaimed 189 MB)
usage_history 247k -> 135k
compression_analytics 247k -> 135k
xp_audit_log 244k -> 127k
domain_cost_history 244k -> 134k (only after the epoch-ms fix)
compression_cache_stats 167k -> 90k
quota_snapshots 10k -> 4k
call_logs / proxy_logs unchanged — genuinely inside 7 days
```

Median endpoint latency roughly halved (2.2s → ~1.2s). Helpful, **not**
sufficient — see the sibling reference on the fsync write path.

## Scheduling this as recurring maintenance

Prefer an **agent-driven** job over a bash cron when the sequence involves
stopping production: an agent can diagnose and recover if the service doesn't
come back. Non-negotiable prompt elements:

- The page-cache mechanism, so the agent never "optimizes" away the stop.
- Full column/format table above.
- Use the app's driver + torn-read retry; never the CLI.
- Backup **before** stop; verify size band + `integrity_check`; **abort** if the
  backup doesn't verify — never proceed on an unverified backup.
- A safety invariant: _"once stopped, do not finish or abandon the run without
  attempting to start it and verifying health"_ — including after an SSH drop.
- Recovery: `journalctl` diagnosis → retry → preserve the failed DB under a
  diagnostic name → restore the verified backup → report loudly.
- Explicit: **`systemctl start` exiting 0 is not success.** Success = live
  process AND HTTP 200.
- Backup pruning (keep 30 days / minimum 4), or 350 MB backups accumulate.

### Cron mechanics traps

- A **one-shot** job scheduled N minutes out will simply not run if creation
  takes longer than N. Registration latency is real (a subagent took 13.5 min to
  create a job meant to fire in 5).
- Calling `run` on an already-elapsed one-shot **consumed and deleted it without
  executing** (`execution_success: false`, job gone from `jobs.json`).
- Register recurring (`0 9 * * 0`) from the start and trigger the validation run
  manually. Recovered the lost prompt from the file the subagent had written to
  `/tmp` — have subagents write long prompts to a file for exactly this reason.
- Verify the effect **on the target host** (backup file present, service restart
  timestamp, row counts), not from the job's own status field.
