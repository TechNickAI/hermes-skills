#!/usr/bin/env python3
"""Rank Hermes profiles as VACUUM candidates on THIS host.

Size is the wrong ranking key. What matters is:

  * freelist  -- the bytes you actually get back. A large file that was
                 compacted recently has ~0 freelist and is worth no lock at all.
  * human_1h  -- human sessions active in the last hour. This is the traffic an
                 exclusive write lock can actually harm; machine sessions are
                 replaceable.

Measured case this exists to prevent: the second-largest database on a host had
a 1 MB freelist (already compacted) while a smaller one had 1512 MB waiting.
Ranking by size would have spent a lock window to reclaim nothing.

Read-only. Touches nothing. Safe to run against live databases.

Usage:  python3 pick_vacuum_target.py [--seconds-per-gb 14.4]
"""

import argparse
import glob
import os
import sqlite3
import sys
import time

MACHINE_SOURCES = ("cron", "subagent")


def profiles():
    root = os.path.expanduser("~/.hermes")
    yield "_root", os.path.join(root, "state.db")
    for base in sorted(glob.glob(os.path.join(root, "profiles", "*"))):
        yield os.path.basename(base), os.path.join(base, "state.db")


def inspect(name, path, rate):
    if not os.path.isfile(path):
        return None
    now = time.time()
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.execute("PRAGMA busy_timeout=15000")
        free_pages = c.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = c.execute("PRAGMA page_size").fetchone()[0]
        placeholders = ",".join("?" for _ in MACHINE_SOURCES)
        human_1h = c.execute(
            f"SELECT count(*) FROM sessions "
            f"WHERE coalesce(source,'') NOT IN ({placeholders}) "
            f"AND coalesce(last_activity_at, started_at) > ?",
            (*MACHINE_SOURCES, now - 3600),
        ).fetchone()[0]
        last = c.execute(
            "SELECT max(coalesce(last_activity_at, started_at)) FROM sessions"
        ).fetchone()[0]
        c.close()
    except Exception as exc:  # a busy/locked db is information, not a crash
        return {"name": name, "error": str(exc)[:80]}

    size = os.path.getsize(path)
    reclaimable = free_pages * page_size
    live = max(size - reclaimable, 0)
    return {
        "name": name,
        "mb": size // 1048576,
        "reclaim_mb": reclaimable // 1048576,
        "pct": round(100 * reclaimable / size, 1) if size else 0.0,
        "human_1h": human_1h,
        "idle_min": round((now - float(last)) / 60, 1) if last else None,
        # Predict from LIVE bytes: VACUUM copies only live pages, which is why
        # a freshly pruned database finishes far faster than a cold benchmark.
        "lock_s": round(live / 1024 ** 3 * rate, 1),
        "worst_s": round(size / 1024 ** 3 * rate, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds-per-gb", type=float, default=14.4)
    args = ap.parse_args()

    rows = [r for r in (inspect(n, p, args.seconds_per_gb)
                        for n, p in profiles()) if r]
    good = [r for r in rows if "error" not in r]
    # Best candidate: most bytes back, least human exposure.
    good.sort(key=lambda r: (-r["reclaim_mb"], r["human_1h"]))

    print(f"{'profile':<12}{'size':>9}{'reclaim':>10}{'%':>7}"
          f"{'human/1h':>10}{'idle_min':>10}{'lock~':>8}{'worst':>8}")
    for r in good:
        print(f"{r['name']:<12}{r['mb']:>7}MB{r['reclaim_mb']:>8}MB"
              f"{r['pct']:>7}{r['human_1h']:>10}"
              f"{str(r['idle_min']):>10}{r['lock_s']:>7}s{r['worst_s']:>7}s")
    for r in rows:
        if "error" in r:
            print(f"{r['name']:<12}  ERROR: {r['error']}")

    if not good:
        return 1

    best = good[0]
    print()
    if best["reclaim_mb"] < 100:
        print("No worthwhile candidate: every profile has <100 MB reclaimable.")
        print("Run retention first -- it builds the freelist that VACUUM cashes in.")
        return 0

    print(f"Best candidate: {best['name']} "
          f"({best['reclaim_mb']} MB reclaimable, {best['pct']}% of file, "
          f"{best['human_1h']} human sessions in the last hour)")
    if best["human_1h"] > 0:
        print("  NOTE: this profile has recent human traffic. Prefer a quieter "
              "one, or wait for an idle window.")
    print(f"  Predicted lock ~{best['lock_s']}s "
          f"(worst case {best['worst_s']}s if freelist is stale).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
