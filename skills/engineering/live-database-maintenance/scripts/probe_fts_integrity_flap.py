#!/usr/bin/env python3
"""Decide whether an FTS 'malformed inverted index' report is REAL or a
measurement artifact on a hot, live database.

Motivating case: a 2.95 GB Hermes state.db reported malformed inverted indexes
on two FTS5 tables, then returned 'ok' minutes later, then 'ok' on eight
consecutive samples. integrity_check reads a WAL snapshot while the service
commits FTS updates; a check landing mid-commit can observe a transiently
inconsistent index.

This probe answers three questions in the order that actually decides the case:

  1. Is the verdict STABLE or INTERMITTENT?  (repeated sampling)
  2. Is the BASE data intact?                (force-read every row)
  3. Do the FTS indexes answer real queries?  (MATCH on EVERY fts table)

Read-only throughout: opens with mode=ro so it can never write to a live db.

Usage:
    python3 probe_fts_integrity_flap.py /path/to/state.db [--samples 8]

Exit codes:
    0  stable ok, base data fully readable      -> artifact / healthy
    2  intermittent                             -> hot-db artifact, not damage
    3  consistently malformed, or base unreadable -> REAL damage, do not vacuum

Run it from a FILE on the host (scp it over), never as an inline `python3 -c`
inside an ssh loop -- nested quoting turns the body into a SyntaxError that
reads like a database result.

On a multi-GB database a single integrity_check(100000) takes minutes. Start
detached and poll:

    nohup python3 probe_fts_integrity_flap.py <db> > /tmp/probe.out 2>&1 &
    # then: wc -l < /tmp/probe.out ; pgrep -fc probe_fts_integrity_flap
"""

import argparse
import sqlite3
import sys
import time


def connect_ro(db, timeout=30):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=timeout)


def integrity(db):
    """Return the full integrity_check output as a list of strings."""
    con = connect_ro(db)
    try:
        # 100000 -- integrity_check TRUNCATES its output by default; read it all
        return [r[0] for r in con.execute(
            "PRAGMA integrity_check(100000)").fetchall()]
    finally:
        con.close()


def fts_tables(db):
    """Every FTS5 content table.

    Filtering on name.endswith('_fts') SILENTLY SKIPS messages_fts_trigram,
    which is routinely the table named in the original error. Detect by
    sqlite_master sql instead, and fall back to shadow-table naming.
    """
    con = connect_ro(db)
    try:
        rows = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        names = {n for n, _ in rows}
        out = []
        for n, sql in rows:
            if sql and "fts5" in sql.lower():
                out.append(n)
        if not out:  # older layouts: infer from shadow tables
            out = sorted({n.rsplit("_", 1)[0] for n in names
                          if n.endswith("_data")})
        return sorted(set(out))
    finally:
        con.close()


def probe_match(db, tables):
    con = connect_ro(db)
    results = {}
    try:
        for t in tables:
            try:
                n = con.execute(
                    f'SELECT count(*) FROM "{t}" WHERE "{t}" MATCH ?',
                    ("the",)).fetchone()[0]
                results[t] = ("ok", n)
            except Exception as e:
                results[t] = ("FAIL", str(e)[:80])
    finally:
        con.close()
    return results


def force_read_base(db, table="messages"):
    """Force-read every row. A count(*) is NOT this: a corrupt B-tree can
    report phantom rows it cannot actually produce."""
    con = connect_ro(db)
    try:
        try:
            total = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        except Exception as e:
            return {"ok": False, "error": f"count failed: {str(e)[:80]}"}
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
        pick = ", ".join(f'"{c}"' for c in cols[:6]) or "*"
        got = 0
        try:
            cur = con.execute(f'SELECT {pick} FROM "{table}"')
            while True:
                rows = cur.fetchmany(5000)
                if not rows:
                    break
                got += len(rows)
        except Exception as e:
            return {"ok": False, "count": total, "read": got,
                    "error": str(e)[:80]}
        return {"ok": got == total, "count": total, "read": got, "error": None}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--sleep", type=float, default=3.0)
    ap.add_argument("--table", default="messages")
    a = ap.parse_args()

    print(f"=== integrity_check x{a.samples} (is the verdict stable?) ===")
    verdicts, first_detail = [], None
    for i in range(a.samples):
        try:
            rows = integrity(a.db)
            v = "ok" if rows == ["ok"] else f"{len(rows)} issue(s)"
            if rows != ["ok"] and first_detail is None:
                first_detail = rows[:4]
        except Exception as e:
            v = f"ERR {str(e)[:50]}"
        verdicts.append(v)
        print(f"  sample {i + 1}: {v}", flush=True)
        if i < a.samples - 1:
            time.sleep(a.sleep)

    distinct = sorted(set(verdicts))
    stable = len(distinct) == 1
    print(f"\n  distinct verdicts: {distinct}")
    print(f"  {'STABLE' if stable else 'INTERMITTENT'}")
    if first_detail:
        print("  first reported issues:")
        for d in first_detail:
            print(f"    - {d[:100]}")

    print(f"\n=== base table '{a.table}' fully readable? (decides data loss) ===")
    base = force_read_base(a.db, a.table)
    if base.get("error"):
        print(f"  READ ERROR: {base['error']}")
    print(f"  count={base.get('count')} force-read={base.get('read')} "
          f"intact={base.get('ok')}")

    print("\n=== MATCH probe on EVERY fts table ===")
    tabs = fts_tables(a.db)
    if not tabs:
        print("  (no FTS tables found)")
    match = probe_match(a.db, tabs)
    for t, (status, extra) in sorted(match.items()):
        print(f"  {t:<28} MATCH {status}  {extra}")

    all_ok = all(v == "ok" for v in verdicts)
    match_ok = all(s == "ok" for s, _ in match.values()) if match else True
    print("\n=== VERDICT ===")
    if not base.get("ok"):
        print("  REAL DAMAGE: base table not fully readable. Do NOT vacuum.")
        sys.exit(3)
    if all_ok and match_ok:
        print("  HEALTHY: stable ok, base intact, indexes answer queries.")
        sys.exit(0)
    if not stable:
        print("  ARTIFACT: verdict flapped on a live db; base data intact.")
        print("  Hot-database measurement artifact, not disk damage.")
        sys.exit(2)
    print("  CONSISTENTLY MALFORMED with base data intact.")
    print("  FTS indexes are derived -- rebuild them; base rows are safe.")
    sys.exit(3)


if __name__ == "__main__":
    main()
