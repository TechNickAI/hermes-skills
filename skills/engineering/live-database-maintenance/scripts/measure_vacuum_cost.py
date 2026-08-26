#!/usr/bin/env python3
"""Measure the REAL VACUUM cost of a database by timing it on a copy.

Why this exists: VACUUM duration cannot be predicted from file size. Measured
on one fleet in one afternoon, the same s/GB model produced a run 6x FASTER
than predicted and another 36% SLOWER. Fitting a live-bytes model does not
rescue it either -- the implied per-MB rates differed by 6x between two runs.

So do not model it. Copy the database, VACUUM the copy, and time that. The
copy runs with a cold page cache and no warm pages, which makes it a
CONSERVATIVE UPPER BOUND -- the right direction for a safety decision.

Takes no lock on the live database.

Usage:
    pick_vacuum_target.py measures WHICH database is worth compacting.
    This script measures HOW LONG that compaction will take.

    ./measure_vacuum_cost.py ~/.hermes/profiles/<name>/state.db
    ./measure_vacuum_cost.py ~/.hermes/state.db --keep   # keep the copy

Then feed the measured number into the real run as a budget, e.g.

    dbmaint.py --profile <name> --apply --max-lock-seconds <measured + margin>

Prefer that over --force-vacuum: an explicit measured budget still refuses a
run that turns out slower than expected, whereas --force-vacuum refuses
nothing.

Exit codes:
    0  measured successfully
    2  the COPY is malformed but the LIVE database is healthy (torn copy --
       harmless artifact of cp on a live WAL database; re-copy after a
       checkpoint, or use the online backup API)
    3  BOTH copy and live are malformed -- REAL CORRUPTION. Do not VACUUM.
       See references/corruption-blocks-compaction.md
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time


def _mb(n):
    return n // 1048576


def _integrity(path, read_only=True):
    """Return 'ok', or the error text. Never raises."""
    uri = f"file:{path}?mode=ro" if read_only else path
    try:
        c = sqlite3.connect(uri, uri=read_only)
        c.execute("PRAGMA busy_timeout=30000")
        try:
            return c.execute("pragma quick_check").fetchone()[0]
        finally:
            c.close()
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="path to the live state.db")
    ap.add_argument("--keep", action="store_true", help="keep the copy")
    ap.add_argument("--tmpdir", default=None, help="where to put the copy")
    args = ap.parse_args()

    src = os.path.expanduser(args.db)
    if not os.path.isfile(src):
        print(f"not a file: {src}", file=sys.stderr)
        return 1

    before = os.path.getsize(src)
    free = shutil.disk_usage(args.tmpdir or tempfile.gettempdir()).free
    # copy + rebuilt copy
    if free < before * 2.2:
        print(f"insufficient space for the copy: need ~{_mb(int(before * 2.2))} MB, "
              f"have {_mb(free)} MB", file=sys.stderr)
        return 1

    tmpdir = args.tmpdir or tempfile.mkdtemp(prefix="vacmeasure-")
    copy = os.path.join(tmpdir, "vactest.db")

    print(f"source: {_mb(before)} MB")
    shutil.copyfile(src, copy)

    try:
        c = sqlite3.connect(copy)
        c.execute("PRAGMA busy_timeout=60000")
        t = time.time()
        c.execute("VACUUM")
        elapsed = time.time() - t
        c.close()
    except sqlite3.DatabaseError as e:
        # A cp of a live WAL database is a torn snapshot, so a malformed COPY
        # proves nothing on its own. The live file is the arbiter.
        print(f"copy failed VACUUM: {e}")
        live = _integrity(src)
        for f in (copy, copy + "-wal", copy + "-shm"):
            if os.path.exists(f):
                os.remove(f)
        if live == "ok":
            print("live database quick_check: ok")
            print("-> TORN COPY (harmless). Re-copy after a checkpoint, or use "
                  "the online backup API.")
            return 2
        print(f"live database quick_check: {live}")
        print("-> REAL CORRUPTION. Do NOT VACUUM: a whole-file rewrite turns "
              "localized damage into total loss, and a backup taken now is a "
              "copy of the corruption.")
        print("-> Localize per table, then see "
              "references/corruption-blocks-compaction.md")
        return 3

    after = os.path.getsize(copy)
    if not args.keep:
        for f in (copy, copy + "-wal", copy + "-shm"):
            if os.path.exists(f):
                os.remove(f)

    print(f"MEASURED vacuum: {elapsed:.1f}s")
    print(f"copy: {_mb(before)} MB -> {_mb(after)} MB "
          f"(would reclaim ~{_mb(before - after)} MB)")
    print()
    print("This is a conservative upper bound (cold cache). Suggested budget:")
    print(f"  --max-lock-seconds {int(elapsed * 1.5) + 5}")
    if elapsed > 60:
        print("  ⚠ exceeds the 60s transcript-write cliff -- supervised window "
              "only, and confirm the humans are away.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
