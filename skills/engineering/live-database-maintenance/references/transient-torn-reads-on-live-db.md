# Transient torn reads on a continuously-written DB — retry SMALL, never copy

Sibling of `false-corruption-from-readonly-wal.md`. That one is about a
_fabricated_ corruption report from a bad snapshot method. This one is about a
**real but transient** read failure against a healthy database, and the
counterintuitive fix.

## Symptom

A monitor/probe intermittently dies with:

```
SqliteError: database disk image is malformed
    at Database.prepare (.../better-sqlite3/lib/methods/wrappers.js:5)
```

...while the service using that same database is perfectly healthy and serving
normally.

## Step 1: prove the DB is fine before touching anything

```python
src = sqlite3.connect(f"file:{P}?mode=ro", uri=True, timeout=15)
dst = sqlite3.connect("/tmp/snap.sqlite")
src.backup(dst); dst.close()          # online backup API = consistent
d = sqlite3.connect("/tmp/snap.sqlite")
print(d.execute("pragma quick_check").fetchone()[0])
```

Measured on the router One case: `quick_check = ok`, 7,009 quota rows intact.
Then loop a small read 12 times against the LIVE file:

```
10 ok, 2 FAIL "database disk image is malformed"  -> TRANSIENT
```

**A mix of ok and fail is the signature of a race, not corruption.** All-fail
would be corruption. Never plan repair off a single failed read.

## Why it happens

The writer commits continuously to a database with **no `-wal` sidecar** (here:
on a tmpfs ramdisk). A read-only opener lands mid-transaction and SQLite
reports the page it read as malformed. The next open usually succeeds.

- `busy_timeout` does **not** help — it guards LOCKS, not torn reads.
- `nolock=1` fails outright.

## THE COUNTERINTUITIVE PART — measure before you "fix" it

The obvious instinct is "stop racing the writer: snapshot the DB, then read the
snapshot." **That is worse, and it is worse for a principled reason.**

Measured on the same box, same minute:

| approach                                                  | success rate |
| --------------------------------------------------------- | ------------ |
| single small live read (`select count(*) from one_table`) | **10/12**    |
| `VACUUM INTO` snapshot, then read                         | **1/8**      |

**Exposure to the race scales with the number of pages you read.** A whole-DB
copy touches _every page_, so it maximizes the window in which the writer can
move underneath you. Copying enlarges the race instead of removing it.

(Python's `Connection.backup()` did succeed here where `VACUUM INTO` failed —
it retries pages internally — but it still copies ~420 MB to read a handful of
counters. Wrong tool for a probe.)

## The fix that works

Retry a **small** read, and force the tear to surface at OPEN time:

```js
function openDB() {
  let lastErr = null;
  for (let i = 0; i < 12; i++) {
    try {
      const d = new bsql(LIVE, { readonly: true });
      // Touch a real page NOW so a tear surfaces here, where retry is cheap --
      // not 15 queries deep into the report.
      d.prepare("SELECT count(*) n FROM quota_snapshots").get();
      return d;
    } catch (e) {
      lastErr = e;
      const until = Date.now() + 150 * (i + 1); // short backoff; writer txns are brief
      while (Date.now() < until) {}
    }
  }
  throw lastErr;
}
const D = openDB();
```

### Why open-time matters more than retry count

The broken version opened the DB once at module load, then ran ~20 queries. One
unlucky open killed the whole probe — and an _outer_ retry (re-running the whole
SSH probe) just re-raced from scratch. That is why the heavy report still failed
**with 5 outer retries already in place**.

Retry belongs at the smallest, cheapest unit of work. Outer retry is a useful
second layer, never the primary remedy.

### Probe weight predicts failure rate

A ~20-query probe fails far more often than a 1-query probe against the same
database. If one job on a DB fails constantly and a sibling job rarely does,
compare how many pages each reads before assuming they hit different problems.

## Verification standard

The race is intermittent (~2 in 12), so ONE clean run proves nothing. Require:

- the previously-100 %-failing job run repeatedly (here 5/5), and
- all jobs sharing the DB run several rounds (here 12/12 across 4 jobs).

If it recurs, the retry count is the dial. **Do NOT switch to a whole-DB copy** —
that was measured and is worse.

## Pitfall found by running, not reading

The backported retry called `time.sleep()` in a module that never imported
`time`. `ast.parse()` reported "syntax ok". A `NameError` on the retry path
would only fire _when a probe actually failed_ — i.e. exactly when the fix was
needed, and never during testing that only exercised the happy path.

**Syntax checks do not exercise code paths.** Exercise the error path
deliberately (call the retry function directly, or inject a failure) before
claiming a retry fix works.
