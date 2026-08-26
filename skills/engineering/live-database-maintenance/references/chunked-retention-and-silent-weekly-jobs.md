# Chunked retention and the silent weekly maintenance job

Two patterns that turn a one-off cleanup into a recurring job nobody has to
babysit. Companion to `vacuum-lock-budget-and-write-patience.md` (why the lock
matters) and `silent-noop-retention-wrappers.md` (how wrappers lie).

Both were requested in the same words a user will likely use again: _"do it
more elegantly to catch up... delete in smaller chunks... vacuum manually.
Then the weekly job should be gentler."_

## Chunked deletion: slice by AGE, not by LIMIT

A single `prune --older-than N` against a backlogged profile is one enormous
DELETE — a long write lock, a large WAL burst, and FTS triggers churning
thousands of rows in one transaction. The instinct is `LIMIT`, but the Hermes
prune CLI has no `--limit`. It does have both time bounds, which is the better
primitive anyway:

```
--older-than 40 --newer-than 70     # only sessions aged 40-70 days
```

Walk the windows **oldest-first**, each its own subprocess and therefore its
own transaction:

```python
def _age_slices(oldest_days, floor_days, step_days):
    """(70,100), (40,70), (10,40) — oldest first, never crossing the floor."""
    slices, hi = [], oldest_days
    while hi > floor_days:
        lo = max(hi - step_days, floor_days)
        slices.append((lo, hi))
        hi = lo
    return slices
```

Three properties worth preserving:

- **Oldest-first** means an interrupted run already deleted the least valuable
  data. A partial catch-up is still a useful catch-up.
- **A pause between slices** (a few seconds) yields the write lock so the live
  gateway can drain its own queued writes instead of queuing behind you.
- **A wall-clock deadline** (`max_seconds`) stops cleanly and leaves the rest
  for the next run — bank progress rather than roll back. Check the deadline at
  the top of each slice, log what was done, and return normally; do not raise.

Derive the oldest bound from the data, not a guess:

```sql
SELECT MIN(COALESCE(last_activity_at, started_at))
FROM sessions WHERE source IN (...)
```

Tuning that worked: **30-day slices for a backlog catch-up**, **7-day slices
with a longer pause and a 15-minute deadline** for the recurring job. Chunking
should be default-on with `0` meaning "one unbounded delete" for the rare case
you want it.

## The weekly job says NOTHING when healthy

Wire the recurring job as a `no_agent` cron script: stdout is delivered to the
owner verbatim, and **empty stdout means nothing is sent at all**. No LLM, no
tokens, no bubble.

A weekly "pruned 240 sessions, all good" message fails the only test that
matters — _does this change what the owner would do?_ It does not, and it
trains them to ignore the channel where the real alert will eventually appear.

Speak for exactly the conditions that need a human:

| condition                        | why it is actionable                     |
| -------------------------------- | ---------------------------------------- |
| protected rows disappeared       | data loss — stop, a backup was preserved |
| run failed / unreadable report   | retention is silently not happening      |
| store still huge after retention | needs a supervised compaction window     |

Everything else returns 0 with no output.

Two refinements found by testing the launcher itself:

- **An unreadable report is a failure, not a healthy run.** If JSON parsing
  fails, say so. Silence must mean "verified healthy," never "could not tell."
- **A concurrent-run refusal is NOT a fault.** A manual run overlapping the
  schedule is expected; detect the lock-refusal message and exit silently
  rather than alerting on normal operator activity.

Test the silence contract explicitly — assert `stdout.strip() == ""` for the
healthy case. It is the single easiest behaviour to regress, because every
other change makes something _more_ verbose.

## Scheduling notes

- **Sunday 04:00 local** is a good default for weekly maintenance: low human
  activity and low scheduled-job overlap on most fleets. Confirm the target's
  own working hours first — a trading bot legitimately working 01:00-08:00
  needs a different slot, or retention-only.
- **Stagger co-tenant profiles.** Separate database files do not block each
  other in SQLite, but simultaneous rewrites contend for the same disk and each
  lock stretches past its prediction.
- **Cron `script` must be a bare FILENAME**, never a command line — the
  scheduler resolves it as a path and never splits it. Put the arguments inside
  the launcher script.
- When hand-writing a job into `cron/jobs.json`, **copy the full key set from a
  scheduler-created job**. A valid job with optional keys omitted
  (`last_status`, `model`, `origin`, …) rendered as `Next run: ?` in `cron
list` despite having a correct `next_run_at`. The job was always schedulable;
  the display was misleading — and "Next run: ?" is exactly the kind of thing
  that gets dismissed as broken or silently ignored.

## Practice on a low-stakes target first

Rehearse the whole path — deploy, dry-run, apply, verify, schedule — on one
real profile before the fleet. Verify on the box afterward, not from the
script's own report: protected-row count unchanged, `quick_check` ok, search
recall unchanged on sampled terms, service still active, and **backup and lock
files both cleaned up**. Checksum the deployed script against the source copy
so you know the thing you tested is the thing that will run.
