#!/usr/bin/env python3
"""Mutation-test the data-verification checks.

This is a tiny, purpose-built mutation runner rather than a dependency on mutmut or
cosmic-ray. It rewrites one exact branch at a time, runs eval_harness.py, and then
restores checks.py byte-for-byte even on interruption.

Success means every planted defect made the harness exit nonzero. It does NOT mean
every possible mutation was tried; the catalog targets the branches and historical
defects this library claims to prevent.

Run from anywhere:
    python3 scripts/mutation_sweep.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKS = HERE / "checks.py"
HARNESS = HERE / "eval_harness.py"

# name, unique regex, replacement. Keep each mutation as small as possible so a
# failure identifies the scenario that protects one branch.
MUTATIONS = [
    ("units always pass", r"    if len\(units\) <= 1:", "    if True:"),
    (
        "unit canonicalizer drops per-dimension",
        r"    return \"_per_\"\.join\(_UNIT_ALIASES\.get\(p, p\) for p in parts\)",
        '    return _UNIT_ALIASES.get(parts[0], parts[0])',
    ),
    ("reconcile tolerance is infinite", r"    if rel <= tolerance:", "    if True:"),
    ("concentration never flags", r"    if share >= threshold:", "    if False:"),
    ("concentration ignores sign flip", r"    if sign_flips:", "    if False:"),
    ("leave-one-out ignores sign flip", r"    if flips:", "    if False:"),
    ("leave-one-out ignores influence", r"    if rel >= 0\.5:", "    if False:"),
    (
        "leave-one-out blames majority group",
        r"    eligible = \[g for g, c in counts\.items\(\) if c / len\(vals\) <= 0\.5\]",
        "    eligible = list(counts)",
    ),
    ("leave-one-out silently truncates labels", r"    if len\(vals\) != len\(labs\):", "    if False:"),
    ("bimodality detector disabled", r"    if ratio > 10 and 0\.15", "    if False and 0.15"),
    ("bimodality ignores mass balance", r"0\.15 <= left_share <= 0\.85", "True"),
    ("discrete-support guard disabled", r"    if len\(unique\) < 8:", "    if False:"),
    (
        "skew detector disabled",
        r"    if abs\(skew\) > 2:\n        return Check\(\n            name,\n            \"FLAG\",\n            f\"Heavy skew",
        "    if False:\n        return Check(\n            name,\n            \"FLAG\",\n            f\"Heavy skew",
    ),
    ("tail detector disabled", r"    if abs\(worst_sum\) > abs\(total\):", "    if False:"),
    (
        "tail detector exempts losing books",
        r"    if abs\(worst_sum\) > abs\(total\):",
        "    if total > 0 and abs(worst_sum) > total:",
    ),
    ("tail quantile guard disabled", r"    if not 0 < quantile < 1:", "    if False:"),
    ("sensitivity accepts disagreement", r"    if agree < 1\.0:", "    if False:"),
    (
        "sensitivity swallows ordinary crashes",
        r"        except Exception as exc:",
        "        except ZeroDivisionError as exc:",
    ),
    ("negative control ignores p-value", r"    if p > 0\.05:", "    if False:"),
    ("negative control ignores degenerate null", r"    if spread == 0:", "    if False:"),
    ("negative control accepts too few trials", r"    if trials < 19:", "    if False:"),
    ("multiple-testing penalty disabled", r"    if best_sharpe <= threshold:", "    if False:"),
    ("multiple-testing accepts raw PnL", r"    if abs\(best_sharpe\) > 20:", "    if False:"),
    ("population reconciliation disabled", r"    if abs\(rate\) <= tolerance:", "    if True:"),
    ("negative row counts accepted", r"    if analyzed_n < 0 or source_n < 0:", "    if False:"),
    ("magnitude gate disabled", r"    if expected_low <= value <= expected_high:", "    if True:"),
    ("inverted magnitude range accepted", r"    if expected_low > expected_high:", "    if False:"),
    (
        "finite scalar guard disabled",
        r"    bad = \{k: v for k, v in named\.items\(\) if isinstance\(v, float\) and not math\.isfinite\(v\)\}",
        "    bad = {}",
    ),
    (
        "finite series guard disabled",
        r"    bad = \[i for i, v in enumerate\(values\) if isinstance\(v, float\) and not math\.isfinite\(v\)\]",
        "    bad = []",
    ),
    (
        "Check guard truthiness regression",
        r"    if guard is not None:\n        return guard",
        "    if guard:\n        return guard",
    ),
]


def main() -> int:
    original = CHECKS.read_bytes()
    source = original.decode()
    survivors: list[str] = []
    try:
        for name, pattern, replacement in MUTATIONS:
            mutated, count = re.subn(pattern, replacement, source, count=1)
            if count != 1:
                print(f"ERROR    {name}: mutation pattern matched {count} times")
                survivors.append(name)
                continue
            CHECKS.write_text(mutated)
            run = subprocess.run(
                [sys.executable, str(HARNESS)],
                cwd=HERE,
                capture_output=True,
                text=True,
            )
            killed = run.returncode != 0
            print(f"{'killed' if killed else 'SURVIVED':<9} {name}")
            if not killed:
                survivors.append(name)
            CHECKS.write_bytes(original)
    finally:
        CHECKS.write_bytes(original)

    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} mutants killed")
    if survivors:
        print("Survivors:")
        for name in survivors:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
