#!/usr/bin/env python3
"""Locate corruption in a SQLite database, and classify what it costs.

``PRAGMA integrity_check`` tells you a database is malformed. It does not tell
you WHICH table, and that distinction decides the entire response: recreating
one rebuildable queue table is routine, losing a conversation history is not.

This full-scans every table so damage can be localized before anyone reaches
for a repair. Read-only -- it never writes to the database.

Two reporting traps this deliberately avoids (both produced a real false
all-clear):

* ``quick_check`` skips page-allocation analysis, so it returns a bare ``ok``
  on a file that ``integrity_check`` reports orphaned pages for. Both are run
  here.
* ``integrity_check`` truncates its output (100 messages by default), so the
  limit is raised and the categories are counted rather than sliced for
  display.

``never used`` pages are LEAKED SPACE, not data damage -- allocated in the file
but belonging to no table and absent from the freelist. VACUUM reclaims them.
They are reported separately so a 4 KB footnote is never escalated as a
corruption event.

Usage: locate_corruption.py [path/to/database.db]
"""
import os
import sqlite3
import sys

# Tables whose contents can be regenerated or safely lost: FTS shadow tables
# and operational queues. Anything else is treated as irreplaceable.
REBUILDABLE_SUFFIXES = ("_fts", "_data", "_idx", "_docsize", "_config", "_trigram")
REBUILDABLE_NAMES = {"delivery_obligations"}


def main(argv):
    db = os.path.expanduser(argv[1] if len(argv) > 1 else "~/.hermes/state.db")
    if not os.path.isfile(db):
        print(f"no such database: {db}")
        return 2

    print(f"database: {db}")
    print(f"size: {os.path.getsize(db) // 1048576} MB")
    for suffix in ("-wal", "-shm"):
        p = db + suffix
        if os.path.exists(p):
            print(f"  {suffix}: {os.path.getsize(p) // 1048576} MB")
    print()

    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.execute("PRAGMA busy_timeout=30000")

    print("=== whole-database verdict ===")
    # quick_check is NOT a cheap synonym for integrity_check; it answers a
    # narrower question and will pass on orphaned pages.
    try:
        print(f"  quick_check: {c.execute('pragma quick_check').fetchone()[0]}")
    except Exception as e:
        print(f"  quick_check: RAISED {type(e).__name__}: {str(e)[:60]}")

    orphaned, other = [], []
    try:
        rows = [r[0] for r in c.execute("pragma integrity_check(100000)").fetchall()]
        orphaned = [m for m in rows if "never used" in m]
        other = [m for m in rows if "never used" not in m and m != "ok"
                 and not m.startswith("*** in database")]
        print(f"  integrity_check: {len(rows)} message(s)")
        print(f"    orphaned 'never used' pages: {len(orphaned)}")
        print(f"    other problems: {other[:5] if other else 'NONE'}")
    except Exception as e:
        print(f"  integrity_check: RAISED {type(e).__name__}: {str(e)[:60]}")

    print()
    print("=== full-scan each table (this is what localizes it) ===")
    tables = [r[0] for r in c.execute(
        "select name from sqlite_master where type='table' order by name"
    ).fetchall()]
    bad = []
    for t in tables:
        try:
            c.execute(f'select count(*) from "{t}"').fetchone()
            print(f"  ok    {t}")
        except Exception as e:
            bad.append(t)
            print(f"  BAD   {t}: {str(e)[:60]}")

    print()
    print("=== FTS MATCH probe (a count can pass while MATCH throws) ===")
    for t in tables:
        if not t.endswith(("_fts", "_trigram")):
            continue
        try:
            c.execute(f"select rowid from {t} where {t} match 'the' limit 1").fetchone()
            print(f"  ok    {t} MATCH")
        except Exception as e:
            print(f"  BAD   {t} MATCH: {str(e)[:60]}")

    print()
    print("=== verdict ===")
    if not bad:
        if orphaned:
            ps = c.execute("pragma page_size").fetchone()[0]
            print(f"  no table is damaged. {len(orphaned)} orphaned page(s) "
                  f"= {len(orphaned) * ps // 1048576} MB of leaked space,")
            print("  reclaimable by VACUUM. This is not a corruption event.")
        else:
            print("  clean: no table raised, no orphaned pages")
    else:
        rebuildable = [t for t in bad
                       if t.endswith(REBUILDABLE_SUFFIXES) or t in REBUILDABLE_NAMES]
        precious = [t for t in bad if t not in rebuildable]
        print(f"  damaged: {bad}")
        print(f"  rebuildable (queue/index): {rebuildable or 'none'}")
        print(f"  PRECIOUS (do not drop):    {precious or 'none'}")
        print()
        print("  Do NOT vacuum a corrupt database -- a whole-file rewrite turns")
        print("  localized damage into total loss, and --keep-backup would only")
        print("  preserve a copy of the corruption. Byte-copy the file first.")
    c.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
