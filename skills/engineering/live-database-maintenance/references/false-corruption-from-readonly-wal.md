# False corruption: `?mode=ro` URI against a live WAL database

A worked case where a production database was diagnosed as corrupt, a repair was
planned, and the database turned out to be **completely healthy**. The repair
would have destroyed real data.

## The false signal

An integrity check run through a read-only URI connection reported:

```
*** in database main ***
Freelist: size is 267 but should be 268
Tree 224 page 27539: btreeInitPage() returns error code 11
... 101 lines, 13 tables implicated
```

Mapping tree root pages to `sqlite_master` named real objects — `usage_history`,
`call_logs`, `key_value`, `model_capabilities`. Every one of them then failed a
`SELECT count(*)` with `database disk image is malformed`. That is a convincing
corruption picture: specific pages, specific tables, reproducible read failures.

**It was all an artifact of how the database was opened.**

## Root cause

```python
# WRONG on a LIVE, actively-written WAL database
sqlite3.connect("file:/path/storage.sqlite?mode=ro", uri=True)
```

A `?mode=ro` URI connection cannot properly attach and update the `-shm`/`-wal`
sidecars. Against a database being written concurrently it reads a **torn view**
of pages mid-write and reports malformation that does not exist on disk.

The service itself was serving traffic normally the entire time.

## The falsifier — one cheap test that settles it

**Take a second copy the same way. If the source were genuinely corrupt, every
copy would be corrupt.**

| test                                          | result                                    |
| --------------------------------------------- | ----------------------------------------- |
| live DB `integrity_check` (normal connection) | **ok**                                    |
| live DB `quick_check`                         | **ok**                                    |
| `foreign_key_check`                           | **0 violations**                          |
| all 13 "damaged" tables read live             | **all OK** — 234,007 / 100,013 / 587 rows |
| first online-backup copy                      | reported corrupt                          |
| **second copy, same method**                  | **ok**                                    |

One bad copy and one clean copy from the same source means the fault is in the
**snapshot**, not the disk. That asymmetry is the whole diagnosis.

## The trap inside the trap

The `.dump` output looked like corroborating evidence:

- ended in `ROLLBACK; -- due to errors`
- contained 16 `/****** CORRUPTION ERROR *******/` markers
- recovered only **170** `key_value` rows

The live table had **587** rows. Repairing from that dump would have silently
destroyed **417 rows of real configuration** — including live provider settings —
to fix a problem that did not exist.

A recovery dump that "loses" rows is evidence about the _dump_, not the database,
until the live table has been counted independently.

## Correct procedure

1. **Never** run `integrity_check` through `?mode=ro` on a live WAL database.
2. Use a normal connection with `PRAGMA query_only=ON`, or stop the service and
   check the quiesced file.
3. Before believing any corruption report, take a **second independent copy** and
   check that. Disagreement between copies ⇒ snapshot artifact.
4. Count rows on the **live** table before trusting any recovery dump's counts.
5. Only after live `integrity_check` returns non-`ok` does repair planning start.

```python
# RIGHT — read-only intent without breaking WAL sidecar attachment
c = sqlite3.connect("/path/storage.sqlite", timeout=60)
c.execute("PRAGMA query_only=ON")
c.execute("PRAGMA integrity_check").fetchone()
```

## Environment note (not a durable constraint)

If `sqlite3` CLI is absent, `apt-get install -y sqlite3` provides it. Note that
Ubuntu's build may lack the `sqlite_dbpage` virtual table, so `.recover` fails
with `sql error: no such table: sqlite_dbpage` while `.dump` still works. Prefer
the Python `sqlite3` module, which the application itself uses.

## Reporting lesson

The first report of this incident called the corruption "index-page scope only,
119/119 tables readable." That was wrong in both directions and came from the
same bad connection method. When the diagnosis reversed, the correction had to be
stated plainly — _"I was wrong, the database is not corrupt"_ — rather than
quietly folded into a status update. A reversed diagnosis is a finding; report it
as one.
