#!/usr/bin/env python3
"""Rebuild a corrupt SQLite database into a fresh file, row by row.

Use when `integrity_check` reports STRUCTURAL damage (`invalid page number`,
`2nd reference to page`, `Rowid out of order`) rather than a damaged index
alone. VACUUM cannot fix that -- it rewrites the same broken structure -- and
repairing indexes over corrupt source data just re-derives the corruption.

This creates a NEW database and copies every readable row into it, so SQLite
builds fresh B-trees from scratch. The source file is never modified. Swapping
is a separate, explicit step.

Design notes, each of which was a real bug first:

* TEXT MUST STAY TEXT. `text_factory = bytes` looks like a safe defense against
  one undecodable row aborting a long copy, but it makes SQLite store every
  TEXT column as BLOB in the destination. The result passes integrity_check
  with search working, and the application reads it as EMPTY, because
  `where source = 'telegram'` matches zero BLOB rows. Use a lossy decoder.
* Views are recreated BEFORE indexes: an external-content FTS table resolves
  `content='<source>'` at CREATE time.
* A skip-prefix that excludes corrupt FTS tables also excludes any VIEW sharing
  that prefix, so the keep-list is explicit.
* Reads walk rowid ranges and BISECT on failure, down to a single row, so a
  corrupt page costs a few rows rather than a whole table. A single-query read
  that raises on the corrupt region yields ZERO rows for the entire table --
  measured: the same delta synced 0 rows as one query and 1,996 with bisection.
  Unreadable rows are COUNTED, never silently dropped.

Usage: rebuild_from_corrupt.py <source.db> <dest.db> [--fts-config FILE]

Without --fts-config the FTS tables are inferred from the source schema.
"""
import json
import os
import sqlite3
import sys
import time

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(2)

src_path, dst_path = sys.argv[1], sys.argv[2]
if os.path.exists(dst_path):
    print(f"ABORT: {dst_path} already exists")
    sys.exit(1)

src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
src.execute("PRAGMA busy_timeout=60000")

schema = src.execute(
    "select type, name, sql from sqlite_master where sql is not null"
).fetchall()

# FTS is derived; it gets rebuilt at the end. Copying a corrupt index would
# defeat the entire exercise. Virtual tables and their shadows are skipped.
fts_defs = [(n, " ".join(s.split())) for t, n, s in schema
            if t == "table" and s.strip().upper().startswith("CREATE VIRTUAL")]
fts_names = {n for n, _ in fts_defs}
shadow_prefixes = tuple(f"{n}_" for n in fts_names)

# ...but a VIEW that an external-content FTS reads may share the prefix and
# MUST be recreated. Keep anything that is not itself a vtable or shadow.
def _skip(typ, name):
    if name.startswith("sqlite_"):
        return True
    if name in fts_names:
        return True
    if name.startswith(shadow_prefixes) and typ == "table":
        return True
    return False


tables = [(n, s) for t, n, s in schema if t == "table" and not _skip(t, n)]
others = [(t, n, s) for t, n, s in schema if t != "table" and not _skip(t, n)]
# Views first: external-content FTS resolves its source at CREATE time.
others.sort(key=lambda x: 0 if x[0] == "view" else 1)

# Only AFTER the schema is read (as text) may row data be decoded leniently.
src.text_factory = lambda b: b.decode("utf-8", errors="replace")

print(f"tables to copy: {len(tables)}")
dst = sqlite3.connect(dst_path)
dst.execute("PRAGMA journal_mode=OFF")
dst.execute("PRAGMA synchronous=OFF")

report = {"tables": {}, "skipped_rows": 0, "started": time.time()}


def read_range(name, collist, lo, hi):
    """Read rowids [lo, hi) tolerating corrupt pages.

    Bisects on failure instead of scanning the whole window row-by-row, so a
    clean database pays one query per chunk and a damaged one narrows to the
    bad rows in log(n) steps. Returns (rows, unreadable_count).
    """
    try:
        return src.execute(
            f'select {collist} from "{name}" where rowid >= ? and rowid < ?',
            (lo, hi),
        ).fetchall(), 0
    except Exception:
        if hi - lo <= 1:
            return [], 1
        mid = (lo + hi) // 2
        a_rows, a_bad = read_range(name, collist, lo, mid)
        b_rows, b_bad = read_range(name, collist, mid, hi)
        return a_rows + b_rows, a_bad + b_bad


for name, ddl in tables:
    dst.execute(ddl)
    cols = [r[1] for r in src.execute(f'pragma table_info("{name}")').fetchall()]
    collist = ",".join(f'"{c}"' for c in cols)
    ph = ",".join("?" * len(cols))
    total = lost = 0

    try:
        max_rowid = src.execute(f'select max(rowid) from "{name}"').fetchone()[0] or 0
    except Exception:
        max_rowid = 0

    if max_rowid:
        step, lo = 2000, 0
        while lo <= max_rowid:
            hi = lo + step
            rows, bad = read_range(name, collist, lo, hi)
            lost += bad
            if rows:
                try:
                    dst.executemany(
                        f'insert or ignore into "{name}" ({collist}) values ({ph})',
                        rows,
                    )
                    total += len(rows)
                except Exception:
                    # A single unwritable row must not discard the batch.
                    for r in rows:
                        try:
                            dst.execute(
                                f'insert or ignore into "{name}" ({collist}) '
                                f"values ({ph})",
                                r,
                            )
                            total += 1
                        except Exception:
                            lost += 1
            lo = hi
        dst.commit()
    else:
        try:
            rows = src.execute(f'select {collist} from "{name}"').fetchall()
            dst.executemany(
                f'insert or ignore into "{name}" ({collist}) values ({ph})', rows
            )
            total = len(rows)
            dst.commit()
        except Exception as e:
            print(f"  {name}: FAILED {str(e)[:60]}")

    report["tables"][name] = {"copied": total, "lost": lost}
    report["skipped_rows"] += lost
    print(f"  {name}: {total} rows" + (f", {lost} unreadable" if lost else ""))

print("\nrecreating views/indexes/triggers...")
for typ, name, ddl in others:
    try:
        dst.execute(ddl)
    except Exception as e:
        print(f"  {typ} {name}: {str(e)[:60]}")
dst.commit()

print("\nrebuilding FTS from the clean copy...")
for name, ddl in fts_defs:
    t0 = time.time()
    try:
        dst.execute(ddl)
        dst.commit()
        dst.execute(f"INSERT INTO {name}({name}) VALUES('rebuild')")
        dst.commit()
        print(f"  {name}: {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"  {name}: FAILED {str(e)[:90]}")

print("\n=== verify the NEW file ===")
dst.execute("PRAGMA journal_mode=WAL")
rows = [r[0] for r in dst.execute("pragma integrity_check(100000)").fetchall()]
real = [m for m in rows if "never used" not in m and m != "ok"
        and not str(m).startswith("*** in database")]
print(f"  integrity: {real[:3] if real else 'ok'}")
print(f"  orphan pages: {len([m for m in rows if 'never used' in m])}")

# A green integrity_check does NOT prove the copy is usable. Census the column
# types: a TEXT->BLOB rebuild passes every structural check and reads as empty.
bad_types = []
for tbl, _ in tables:
    for col in [r[1] for r in dst.execute(f'pragma table_info("{tbl}")')]:
        try:
            kinds = dst.execute(
                f'select distinct typeof("{col}") from "{tbl}" limit 5'
            ).fetchall()
            if any(k[0] == "blob" for k in kinds):
                src_kinds = src.execute(
                    f'select distinct typeof("{col}") from "{tbl}" limit 5'
                ).fetchall()
                if not any(k[0] == "blob" for k in src_kinds):
                    bad_types.append(f"{tbl}.{col}")
        except Exception:
            pass
print(f"  TEXT->BLOB regressions: {bad_types or 'none'}")

dst.close()
src.close()

report["elapsed"] = round(time.time() - report["started"], 1)
report["dest_mb"] = os.path.getsize(dst_path) // 1048576
report["integrity_clean"] = not real and not bad_types
print(f"\n  new file: {report['dest_mb']} MB")
print(f"  unreadable rows total: {report['skipped_rows']}")
print(f"  elapsed: {report['elapsed']}s")

out = os.path.join(os.path.dirname(dst_path) or ".", "rebuild_report.json")
with open(out, "w") as fh:
    json.dump(report, fh, indent=1, default=str)
print(f"  report: {out}")

sys.exit(0 if report["integrity_clean"] else 1)
