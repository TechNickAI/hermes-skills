# Diagnosing SQLite corruption on a LIVE WAL database

**Reading a live WAL database while it is being written produces intermittent,
irreproducible "database disk image is malformed" errors on a perfectly healthy
file.** `?mode=ro` is the worst offender but it is **NOT the only cause** — read
the next section before you conclude you have fixed it. Acting on a false
reading nearly destroyed 417 rows of live production config.

## 🔴 Removing `?mode=ro` is necessary but NOT sufficient

A one occasion session read this document, removed `?mode=ro` from a staging
script, re-ran, and hit the identical error — then reported the fix as complete
before re-testing. The corrected model:

- `?mode=ro` **guarantees** torn reads (it cannot attach `-wal`/`-shm` at all).
  Removing it is required.
- Even with a normal connection **plus** `PRAGMA query_only=ON`, a _busy_ WAL
  database still yields torn reads **intermittently**.

Measured on the router, same file, seconds apart:

```
integrity_check on the LIVE file    ok, FAIL, ok, FAIL, FAIL, FAIL
integrity_check on a fresh COPY     FAIL, FAIL, ok, ok, ok, ok
sqlite3 CLI.backup 1 failure in 10
python.backup 0 failures in 10 — then failed in-script
```

**Every client is affected** — python 3.45, better-sqlite3 3.53, sqlite3 CLI
3.45 — because it is a property of reading a file under active write, not a bug
in any one library. Do not "fix" this by switching drivers: a driver that passes
ten trials will fail the eleventh. Ten trials is too few to characterize an
intermittent fault; do not reorder logic on that evidence and call it proven.

**The durable fix is a RETRY LOOP, not a better connection string.** Back up,
`integrity_check` the copy **in the same process**, retry on failure.
`scripts/stage_and_smoke.sh` implements this with 10 attempts — in the worked
case attempt 1 tore and attempt 2 verified clean.

## The definitive test: snapshot all three files, check the STATIC copy

`.backup()` on a busy database is itself subject to torn reads, so a failed
backup proves nothing about the source. Copy the main file **and both sidecars**
together, then check that static set — no live writer, no ambiguity:

```bash
cp storage.sqlite storage.sqlite-wal storage.sqlite-shm /tmp/snap/
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/snap/storage.sqlite')
print(c.execute('PRAGMA integrity_check').fetchone()[0])
print(c.execute('select count(*) from key_value').fetchone()[0])"
```

Worked case — the same database that had just failed four of six live checks:

```
snapshot integrity: ok    key_value: 577   (x4 runs, identical)
```

4/4 clean with stable row counts. **That settles it.** Row counts drifting
between _live_ reads (591 → 577 → 570) is normal under writes and is not
evidence of damage; what matters is that a static snapshot is self-consistent.

## The original false positive, in full

Read-only diagnosis of a live router DB reported catastrophic damage:

```
PRAGMA integrity_check ->
  Freelist: size is 267 but should be 268
  Tree 224 page 27539: btreeInitPage() returns error code 11
  ... 101 lines, 13 tables unreadable
```

Thirteen tables raised `database disk image is malformed` on `count(*)` --
including `usage_history`, `call_logs`, and `key_value` (which holds settings).
A `.dump` recovered only 170 `key_value` rows and terminated in
`ROLLBACK; -- due to errors`.

**All of it was an artifact.** The live database was perfectly healthy:

```
PRAGMA integrity_check   -> ok
PRAGMA quick_check       -> ok
PRAGMA foreign_key_check -> 0 violations
key_value                -> 587 rows (the dump had "recovered" 170)
all 13 "damaged" tables  -> read fine (usage_history 234,007 rows)
```

Had the "repair" proceeded from that dump, it would have **destroyed 417 rows of
real configuration to fix a problem that did not exist.**

## Why it happens

`sqlite3.connect("file:/path/db.sqlite?mode=ro", uri=True)` cannot properly
attach the `-shm` / `-wal` sidecar files. On a database being actively written it
reads a **torn view** of pages mid-write and reports malformation. The disk is
fine; the _snapshot_ is inconsistent.

## The falsifier: a second copy — but read the sample-size warning

**If the source were genuinely corrupt, every copy would be corrupt.** So a
single _clean_ copy is proof the source is fine.

⚠️ **The converse does NOT hold.** A single _failed_ copy proves nothing — copies
of this healthy database came back `FAIL, FAIL, ok, ok, ok, ok`. Two failures in
a row is still not evidence of damage. Take several, and prefer the static
snapshot test above when you need a real answer.

```python
import sqlite3
src = sqlite3.connect("/path/storage.sqlite", timeout=60)   # NOT ?mode=ro
src.execute("PRAGMA query_only=ON")
dst = sqlite3.connect("/tmp/repro.sqlite")
src.backup(dst); dst.close(); src.close()
print(sqlite3.connect("/tmp/repro.sqlite").execute("PRAGMA integrity_check").fetchone()[0])
```

In the worked case: copy #1 reported corruption, copy #2 returned `ok`. One bad
copy plus one clean copy from the same source means the fault is in the snapshot,
not the disk. That single test converted a "rebuild the database" plan into
"nothing is wrong."

## How to actually check a live SQLite database

```python
# RIGHT -- normal connection, read-only enforced by PRAGMA
c = sqlite3.connect("/path/storage.sqlite", timeout=60)
c.execute("PRAGMA query_only=ON")
c.execute("PRAGMA integrity_check").fetchone()

# ALSO RIGHT -- stop the service first, then any method works

# WRONG on a live WAL db -- fabricates corruption
sqlite3.connect("file:/path/storage.sqlite?mode=ro", uri=True)
```

Note the legitimate exception: `?immutable=1` is correct for **archived** copies
that lack their `-shm` sidecar and are guaranteed not to be written.

## Order of operations for any "the database is corrupt" report

1. `PRAGMA integrity_check` **on the live file** via a normal connection with
   `query_only=ON`. If `ok`, stop -- there is no corruption. **But a single
   FAIL here means nothing** on a busy database: this exact check returned
   `ok, FAIL, ok, FAIL, FAIL, FAIL` on a healthy file. Never escalate on one bad
   reading.
2. Snapshot `db` + `-wal` + `-shm` together and check the **static** copy
   (see above). This is the step that actually settles it. Only if _that_
   reports damage do you have a corruption finding.
3. Only if damage reproduces on the static snapshot: confirm which objects are
   affected by mapping `Tree <root>` numbers to names via
   `SELECT rootpage, type, name, tbl_name FROM sqlite_master WHERE rootpage IN (...)`.
4. Check whether the app even depends on the damaged objects before planning a
   repair (`grep` the built release for the table names).
5. Snapshot before any write. Never repair from a dump that ended in `ROLLBACK`.

**Do not assume torn reads track write volume.** The two failing runs in the
worked case were not the busy ones — the quietest hour measured (9,104 log lines
vs 24,276 at peak) produced a failure. Load correlation is a tempting story that
the data did not support.

## Tooling notes that cost time

- **`.recover` needs `sqlite_dbpage`**, a virtual table absent from some distro
  builds of the `sqlite3` CLI. It fails instantly with
  `sql error: no such table: sqlite_dbpage (1)` and writes a 0-byte output --
  whose `integrity_check` then cheerfully returns `ok`. **An empty database
  passes every integrity check.** Verify row counts, never just the check.
- A `.dump` that ends in `ROLLBACK; -- due to errors` is **not** a usable
  restore artifact. Grep for `/****** CORRUPTION ERROR *******/` markers and map
  each one to the table it sits in before trusting any of it.
- `dbstat` gives per-table page counts for sizing a prune:
  `SELECT count(*) FROM dbstat WHERE name='<table>'`.

## Report the correction plainly

When a diagnosis is retracted, say so in the first line -- "I was wrong, the
database is not corrupt" -- and show the falsifying evidence. Burying a retraction
under new findings is how a bad diagnosis survives into someone else's decision.
