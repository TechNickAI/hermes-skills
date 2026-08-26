# Read-only connect fails LAZILY — validate with a real query

Reinforces the `?mode=ro` rule in SKILL.md with the detail that makes the bug
expensive to find. Learned 2026-08 building diagnostic collectors that read live
Hermes databases.

## The trap

`sqlite3.connect()` is **lazy**. A `?mode=ro` URI against a live WAL database
**succeeds at connect time** and only raises on the first query:

```
sqlite3.OperationalError: unable to open database file
```

The cause is that WAL needs to create a `-shm` sidecar, which read-only mode
forbids. But the error surfaces at query time, in whatever code path happens to
run first.

## Why it defeats the obvious fallback

The natural defensive pattern is broken:

```python
# WRONG — the first candidate always "succeeds", so the fallback never runs
for uri in (f"file:{path}?mode=ro", f"file:{path}?immutable=1"):
    try:
        return sqlite3.connect(uri, uri=True)   # returns for mode=ro, then
    except Exception:                            # explodes later at query time
        continue
```

This produced a collector that failed identically after "fixing" it — the
fallback chain looked correct and never executed.

## The fix — validate inside the try

Every candidate connection must run a real query before being returned:

```python
def ro_connect(path, timeout=8):
    """Read-only connect that survives WAL.

    sqlite3.connect is LAZY: `mode=ro` succeeds at connect time and only raises
    'unable to open database file' on the first query, because a WAL database
    needs a -shm sidecar that read-only mode forbids. Each candidate must be
    validated with a real query before being returned.
    """
    last = None
    for uri in (f"file:{path}?mode=ro", f"file:{path}?immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=timeout)
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return con
        except Exception as e:
            last = e
    con = sqlite3.connect(str(path), timeout=timeout)
    con.execute("PRAGMA query_only=ON")
    con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    return con
```

`immutable=1` works where `mode=ro` fails, because it tells SQLite to skip WAL
and locking machinery entirely. It is only safe when you accept a possibly
slightly stale view — correct for diagnostics, wrong for anything transactional.

**General rule:** any lazily-initialized resource must be exercised inside the
`try` block that is supposed to catch its failure. Connect-only validation is
not validation.

## Related: FTS5 `integrity-check` is a WRITE

```sql
INSERT INTO tbl_fts(tbl_fts) VALUES('integrity-check');
```

Despite the name, this is a write statement. On a read-only handle it raises
`attempt to write a readonly database` — which a naive collector reports as
**CORRUPT**. That is a false positive on a perfectly healthy index.

Distinguish the two cases explicitly:

```python
try:
    con.execute(f"INSERT INTO {t}({t}) VALUES('integrity-check')")
    fact(f"fts_{t}", "ok")
except sqlite3.OperationalError as e:
    msg = str(e).lower()
    if "readonly" in msg or "attempt to write" in msg:
        n = con.execute(f"SELECT count(*) FROM {t} WHERE {t} MATCH 'the'").fetchone()[0]
        fact(f"fts_{t}", f"queryable(matches={n}, write-check-skipped)")
    else:
        fact(f"fts_{t}", f"CORRUPT: {e}")
```

Run the genuine integrity check on a writable handle during a deep/daily pass,
not on a frequent read-only tick.

## Cost gate for frequent readers

`PRAGMA quick_check` on a **5 GB** database took **41 seconds** — unacceptable
on a 15-minute tick, and it dominated total collector runtime.

Gate it: cheap readability probe every run, full integrity behind an explicit
`--deep` flag on a daily schedule.

```python
if DEEP or size_mb < 200:
    ic = con.execute("PRAGMA quick_check").fetchone()[0]
else:
    con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    ic = "readable(deep-check-skipped)"
```

Report the skip explicitly. A monitor that silently downgrades a check while
still reporting "ok" is manufacturing false assurance.
