# Write contention and swallowed writes on a money/ledger path

Use when a SQLite database is the system of record for something with real-world
consequence (orders, payments, approvals, dispatches) and many processes write
it. This is a DIFFERENT failure class from retention/compaction bloat: the
database can be tiny and perfectly healthy and still lose records.

## The failure shape

Observed 2026-08 on a live trading agent:

```
'database is locked' (two occurrences, 30 days apart on separate dates)
"Both buys reached Kalshi, but their local order/signal provenance was
 dropped. I rebuilt both records from immutable exchange fills."
```

The external action SUCCEEDED and the local ledger LOST the record. A human had
to reconstruct state from the counterparty's data. That is the signature: an
irreversible external side effect committed, its local trace did not.

## Size is not the relevant variable

The instinct to say "the DB is only 237 KB, SQLite is fine" is wrong, and a
reviewer made exactly that argument in this session before being overturned.

**SQLite's single-writer lock does not care how large the file is.** A 10 KB
database with 35 concurrent writer modules contends exactly as hard as a 10 GB
one. File size is a valid argument about _volume_; it says nothing about
_concurrency_.

Diagnostic question that separates the two: **is the symptom slow queries
(volume) or `database is locked` / lost writes (contention)?** Only the first
is answered by size.

## Check these three things, in order

### 1. Is WAL on?

```python
c.execute("pragma journal_mode").fetchone()[0] # want: wal
```

WAL lets readers and one writer proceed concurrently. Often already enabled —
do not stop here and declare it handled.

### 2. Is `busy_timeout` set on the CONNECT call?

This is the one that is usually missing, and it is easy to miss because the WAL
pragma sitting two lines away creates a false impression of diligence:

```python
# what you find (line 124) — no timeout, takes the ~5s default and gives up
c = sqlite3.connect(str(db_path))
c.execute("PRAGMA journal_mode=WAL") # line 126, looks reassuring

# what it should be
c = sqlite3.connect(str(db_path), timeout=30.0)
c.execute("PRAGMA busy_timeout=30000")
```

Grep for `sqlite3.connect` across the production tree and check EVERY call
site, not the one you happened to open. Count the writers:

```bash
grep -rl "<db_basename>" <prod_tree>/*.py | wc -l
```

35 writers against one lock is a design fact worth stating in the writeup.

### 3. Is a failed write swallowed?

**This is the real root cause, and it survives an engine change.** Migrating to
Postgres removes the lock class; it does NOT stop a bare `except` from
discarding the next failure for an unrelated reason.

Required regardless of engine:

1. Write the **intent record before** the external call, not after.
2. Make the post-result write **idempotent and retried** (deterministic client
   order ID / natural key + a unique constraint, so a retry cannot duplicate).
3. A failed ledger write is a **loud error**, not a log line. If the ledger
   cannot record it, that is an incident, not a warning.

State machine worth insisting on: `intent -> submitted -> acknowledged`, with
reconciliation against the external system at startup **before** any retry.
Otherwise a crash between external-ack and local-commit produces an unknown
order that a retry duplicates.

## Fail-closed needs to be split, not blanket

"Refuse to act while the ledger is unreachable" is correct for
risk-INCREASING actions and dangerous for risk-REDUCING ones. During a database
outage, existing exposure still needs cancels, exits, and protective actions.
A blanket fail-closed converts a minor DB blip into stranded, unmanaged
exposure.

- risk-increasing (new entries, new spend): fail closed.
- risk-reducing (cancel, exit, flatten, protect): emergency path with a durable
  local outbox, reconciled afterward.

## Frequency is the wrong severity axis

Two occurrences in 30 days of retained logs reads as rare. It is not, for two
reasons: log retention **undercounts** (you only see failures a log/audit
happened to capture), and the severity is _silent loss of a money record_, not
a retry. Judge this class by consequence, not by count.

## Pitfalls

- **Reading the WAL pragma and stopping.** WAL on + no `busy_timeout` is the
  common broken state, and the two lines usually sit next to each other.
- **Arguing from file size.** See above. Wrong variable for this failure.
- **Believing an engine migration is the fix.** It removes one failure class
  and leaves the durability bug intact.
- **Fixing only the connect you opened.** Enumerate all writers.
- **Blanket fail-closed.** Strands live exposure.
- **Treating "the counterparty had the truth so we recovered" as an
  all-clear.** Reconstruction worked here because an external authoritative
  source existed. That is luck about system shape, not a property of the code.

## Cheap mitigation vs correct fix

If a rebuild or migration is weeks out, set `busy_timeout` NOW — it is a
reversible one-line change per call site that addresses most of the observed
lock failures immediately. Then do the intent-record/idempotent-retry/loud-error
work, which is required whatever engine you land on. Do not let a scheduled
future migration defer a ten-minute mitigation on a live money path.
