# VACUUM lock duration vs. the application's write patience

Companion to `references/unattended-live-vacuum-operations.md`. That file gives
the operational review gates for unattended live compaction (disk math,
concurrency leases, incident skip conditions, canary promotion, alerting);
this one gives the **measured numbers** to plug into them and the code shape
for a prediction gate.

## Measured VACUUM cost (Hermes state.db, macOS, APFS, local SSD, one occasion)

Full sequence timed: `wal_checkpoint(TRUNCATE)` -> `VACUUM` ->
`wal_checkpoint(TRUNCATE)` -> `optimize`, on real copies of fleet databases.

| database                   | size    | total exclusive lock |
| -------------------------- | ------- | -------------------- |
| a research agent           | 1685 MB | 22.0 s               |
| a personal-assistant agent | 3505 MB | 49.3 s               |

**~14.4 seconds per GB**, roughly linear across this range. Re-benchmark per
storage class — this is local SSD and does not transfer to EBS or a network
volume.

### 🔴 That rate is a WORST CASE, not an estimate (measured correction)

Those benchmarks were run on **copies, with a cold page cache, before any
retention**. The first real production VACUUM told a very different story:

|                         | predicted | actual    |
| ----------------------- | --------- | --------- |
| studio `_root`, 2686 MB | 37.8 s    | **6.1 s** |

**6x faster than the model.** The reason is visible in the preflight: 1512 MB
of that 2686 MB file was already freelist, because retention had just run.
`VACUUM` copies only _live_ pages, so a database that was recently pruned
rebuilds far faster than a cold benchmark of the same nominal size.

Consequences for planning:

- **Keep the conservative rate as the unattended gate.** Refusing a job that
  would have been fine is cheap; taking a 90 s lock on a live user-facing
  agent is not. Do not "correct" `VACUUM_SECONDS_PER_GB` downward to make the
  gate more permissive.
- **Do not quote the prediction to a human as the expected cost** of a
  supervised window. Say "predicted ~90 s worst case, likely far less" — a
  6.7 GB store whose freelist is large may finish in well under 20 s.
- **Predict from live bytes, not file bytes,** when you want a rough steer:
  `(file_size - freelist_count * page_size)` is the volume actually copied.
  But see the next section — even that model does not hold.

### 🔴🔴 You cannot predict this. MEASURE ON A COPY. (second correction)

The "6x faster" result above tempted a generalization — _predictions are
pessimistic, expect it to finish early_ — and that generalization was told to
the user. **The very next VACUUM disproved it in the opposite direction:**

| database                         | live bytes | predicted | actual      |
| -------------------------------- | ---------- | --------- | ----------- |
| studio `_root`, 2686 MB          | 1174 MB    | 37.8 s    | **6.1 s**   |
| large user-facing agent, 6686 MB | 3941 MB    | 94.0 s    | **128.0 s** |

The second run was **36% SLOWER than predicted**, not faster. Fitting a
live-bytes model to rescue the situation does not work either — the implied
per-MB-live rates differ by **6x** between these two runs (0.0052 vs 0.0325
s/MB-live). Any "corrected" model that reproduces one point is simply tuned to
that point. Two data points, two different physics (page-cache state, host
load, concurrent readers, storage behaviour).

**The method that actually works — copy, then time the copy:**

```bash
cp state.db /tmp/vactest.db # see the torn-copy caveat below
python3 - <<'EOF'
import sqlite3, time
c = sqlite3.connect("/tmp/vactest.db"); c.execute("PRAGMA busy_timeout=60000")
t = time.time(); c.execute("VACUUM"); print(f"{time.time()-t:.1f}s")
EOF
rm -f /tmp/vactest.db*
```

Zero lock on the live database, and it yields a real number instead of a guess.
Measured this way, then compared against the subsequent production run:

| database                            | measured on copy | actual live run |
| ----------------------------------- | ---------------- | --------------- |
| a research agent, 1692 MB           | 16.6 s           | 7.0 s           |
| a personal-assistant agent, 3510 MB | 34.3 s           | 10.0 s          |

The copy is a **conservative upper bound** (cold cache, no warm pages), which
is exactly the right direction for a safety decision. Feed the measured number
into `--max-lock-seconds <measured + margin>` rather than reaching for
`--force-vacuum`. On a research agent the measured 16.6 s was already inside the
default 45 s gate, so no override was needed at all.

Report to the user as _"measured 34 s on a copy"_, never as a model output.

### Torn copies, and the corruption this method catches

`cp` of a live WAL database is **not** a consistent snapshot — the copy can
fail `VACUUM` with `database disk image is malformed` purely as an artifact.
Before concluding anything, run the same check against the **live** file
read-only. Two different findings:

- copy malformed, live healthy -> torn copy, harmless, re-copy after a
  checkpoint or use the online backup API
- copy malformed **and live malformed** -> real corruption, and the copy just
  saved you from feeding a damaged file into a whole-file rewrite

The second case occurred on a live trading bot. Measuring on a copy caught it
_before_ any lock was taken. See
`references/corruption-blocks-compaction.md` for the localization procedure
and the stop rule.

## Choose the target by FREELIST and human traffic, not by size

Size alone picks the wrong database. Measured across one host on the same day:

| profile                    | size    | freelist    | human sessions last 1 h |
| -------------------------- | ------- | ----------- | ----------------------- |
| `_root`                    | 2686 MB | **1512 MB** | 0                       |
| a personal-assistant agent | 3510 MB | 1251 MB     | 2                       |
| a research agent           | 1692 MB | 251 MB      | 1                       |
| the operations agent       | 1782 MB | **1 MB**    | 1                       |

`the operations agent` is the second-largest file and has **nothing to reclaim** — it had been
compacted hours earlier. A size-ranked plan would have spent a lock window for
~0 bytes. `_root` was smaller than a personal-assistant agent yet the best candidate: biggest
freelist, and _zero human traffic in the last hour_.

Rank candidates by `freelist_count * page_size` (the bytes you actually get
back) and gate on recent human activity (the thing a lock can harm):

```sql
PRAGMA freelist_count; -- x PRAGMA page_size = reclaimable bytes
SELECT count(*) FROM sessions
 WHERE coalesce(source,'') NOT IN ('cron','subagent')
   AND coalesce(last_activity_at, started_at) > strftime('%s','now') - 3600;
```

## Verify a compaction, do not trust exit 0

`VACUUM` rewrites the entire file, so prove the result rather than assuming it.
The battery that passed on the run above:

- `PRAGMA integrity_check` — the **full** check, not `quick_check`
- `PRAGMA foreign_key_check` — must return no rows
- `PRAGMA journal_mode` — still `wal` (a rebuild can silently change it)
- `PRAGMA freelist_count` — now `0`, proving the rebuild actually happened
- an FTS `MATCH` query returning hits — the index survived the rebuild
- a real `INSERT` + `COMMIT` into a scratch table, then drop it — proves the
  database is **writable**, which no read-only pragma can tell you
- protected-source session count unchanged across the run
- the owning service still up, and **zero `database is locked` entries** in its
  logs for the window

Keep the pre-VACUUM backup (`--keep-backup`) until that battery passes and the
owner has confirmed. Reclaimed space is worthless if the file is subtly wrong.

### 🔴 A live reader makes the reported size a LIE

Immediately after `VACUUM` on a database whose service is still running, the
main file can still read at its **old** size with the rebuilt content sitting
in the WAL — because a live reader holding a snapshot turns the trailing
`wal_checkpoint(TRUNCATE)` into a partial no-op. Measured on a personal-assistant agent:

```
right after VACUUM: db 3510 MB wal 2264 MB -> report says "reclaimed 0 MB"
after reader released: db 2251 MB wal 0 MB -> actually reclaimed 1259 MB
```

A run that genuinely worked reports **zero reclaimed** and looks like a
failure. The `freelist_count` is the tell: it had already dropped to ~50, so
the rebuild plainly happened.

Fix in the tool, not in the operator's head — retry the checkpoint before
reading sizes, and surface the unsettled case rather than reporting a false
zero:

```python
WAL_SETTLE_ATTEMPTS, WAL_SETTLE_PAUSE = 6, 2.0
WAL_SETTLE_BYTES = 64 * 1024 * 1024

for _ in range(WAL_SETTLE_ATTEMPTS):
    if _size(Path(str(db) + "-wal")) < WAL_SETTLE_BYTES:
        break
    time.sleep(WAL_SETTLE_PAUSE)
    busy, _pages, _ck = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if not busy:
        break
else:
    report["wal_not_settled_mb"] =... # never report a silent 0
```

### Evaluate the compaction gate BEFORE taking the backup

A run that is going to _skip_ compaction does not need a full-size copy of the
database. Ordering the backup first wrote a needless **3.5 GB** file on a disk
the tool exists to free, and `--keep-backup` then left it there — so a refused
run made the problem worse. Compute the gate first and record whether the
backup was taken for a compaction that will actually run
(`backup_for_compaction: bool`), so the caller can clean up a backup that
covered nothing.

Note this does **not** relax the ordering rule for _destructive_ work: the
verified backup must still precede the first deletion. Only the decision of
_whether to back up at all_ moves earlier.

## The budgets that turn a stall into an outage

Verified in the deployed source (`hermes_state.py:2719-2720`):

```python
_WRITE_PATIENCE_S = 20.0 # routine session writes
_TRANSCRIPT_WRITE_PATIENCE_S = 60.0 # transcript-critical writes
_ACTIVITY_WRITE_PATIENCE_S = 0.5
```

Past those, the write fails and **the user's turn dies with a session-storage
error and must be resent** — a long "typing" pause followed by a failure, not a
transparent delay. So: a lock shorter than the budget is a stall; a lock longer
than the budget is a temporary service outage. Read these constants out of the
build you are actually running rather than trusting the numbers above.

A connection `timeout=` governs how long a caller waits for a lock, **not** how
long `VACUUM` itself may run. There is no execution deadline on the statement.

## Prediction gate

```python
VACUUM_SECONDS_PER_GB = 14.4
MAX_UNATTENDED_LOCK_SECONDS = 45.0 # margin under the 60 s cliff

def predicted_lock_seconds(db_bytes):
    return (db_bytes / 1024**3) * VACUUM_SECONDS_PER_GB
```

Predict the lock **before** taking it and refuse unattended compaction above
the budget. Report a machine-readable `needs_supervised_window: true` rather
than silently freezing a live agent, and give the operator an explicit
`--force-vacuum` override for supervised windows.

Implementation trap: setting `should_vacuum = False` to skip can fall into a
generic `else` branch that overwrites the specific skip reason with something
bland like "below threshold". Track the refusal in its own flag so the report
says why it was refused.

Projected across a real 14-profile fleet at the measured rate:

| profile                    | size   | predicted lock | unattended?        |
| -------------------------- | ------ | -------------- | ------------------ |
| large user-facing agent    | 6.7 GB | ~93 s          | refused            |
| a personal-assistant agent | 3.5 GB | ~49 s          | borderline         |
| trading bot                | 3.0 GB | ~42 s          | ok, but money path |
| the operations agent       | 2.2 GB | ~32 s          | ok                 |
| a research agent           | 1.7 GB | ~23 s          | ok                 |

Treat that table as a **triage gate only** — which databases need a human in
the loop — never as an estimate of what any single run will cost. The actuals
came in at 128 s, 10 s, 6.1 s and 7.0 s against those predictions. The gate
was still right: it refused the 6.7 GB store, whose real lock (128 s) did
exceed the 60 s cliff and did produce write failures.

### The gate works; the override is the risk

The 45 s refusal is not an obstacle to route around. Two measured outcomes
from one afternoon:

- a personal-assistant agent predicted 49.4 s, was **refused**, and the operator misread it as a
  failed run. Correct behaviour. Re-running with a _measured_
  `--max-lock-seconds 60` completed in 10 s.
- the 6.7 GB store was forced through with `--force-vacuum` on explicit owner
  approval during a confirmed idle window. Lock ran 128 s and the logs show
  exactly the predicted failure:

```
WARNING hermes_state: async token accounting: apply failed
  (session=cron_...): database is locked (another Hermes process held the
  state.db write lock for over 60s — likely a long maintenance operation)
WARNING run_agent: Session DB append_message failed: database is locked
```

Blast radius there was one cron session and two errors over 2.6 s, with zero
human sessions affected — because the window was chosen while the owner was
verifiably away. Had a human been mid-conversation, that would have been their
turn failing. **Prefer a measured `--max-lock-seconds` over `--force-vacuum`;
reserve the override for windows where you have confirmed the humans are
absent, and report the lock-error count afterwards either way.**

## Retention is not subject to this

Deleting rows is a series of short transactions, not a whole-file rewrite.
Source-scoped retention is safe at any database size; only compaction needs the
lock budget. When a store is too big to compact unattended, **still run
retention** — that is where growth is stopped. Splitting the two lets you ship
the safe half immediately instead of blocking everything on the risky half.

## Expectation-setting on reclaim

Measured: pruning **8,447 sessions** from a 2.25 GB store reclaimed **478 MB**,
leaving 1.77 GB. Most of the remainder was FTS index, not conversation.

Say this to the user up front. Retention **stops growth**; it does not shrink a
store back to nothing. If the headline gigabyte number is the actual goal, the
bigger lever is the trigram index (see the sizing section in SKILL.md) — and
that is a search-quality tradeoff, not free cleanup.

### Retention alone moves the file size by ZERO

State this plainly _before_ running a fleet-wide catch-up, or the result reads
as a failure. Across ten profiles (~37,000 sessions deleted), **every single
run reported an unchanged MB figure**:

```
ali 9,385 pruned -> 1396 MB -> 1397 MB
a personal-assistant agent 6,234 pruned -> 3509 MB -> 3510 MB
an owner 9,743 pruned -> 6686 MB -> 6686 MB
```

Deleted pages become freelist _inside_ the file; only `VACUUM` returns them to
the filesystem. A user watching disk usage will conclude the job did nothing.

The payoff arrives at compaction, and it is large precisely _because_
retention ran first — the studio root profile went **2686 MB -> 1171 MB, 56% of
the file**, because retention had converted 1512 MB into freelist. Sequence the
story that way: retention builds the freelist, VACUUM cashes it in.
