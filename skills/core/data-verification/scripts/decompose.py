#!/usr/bin/env python3
"""Decomposition arithmetic for the data-verification skill.

This exists for one reason: there is arithmetic here you cannot do by reading.

Deciding whether removing the largest of 200 rows flips a sign, recomputing a
statistic once per group to find which one drives it, or producing a p-value from
500 shuffles are all things that must actually be computed. Everything else in
this skill is prose, because a function wrapping a one-line comparison is ceremony
that makes a check feel done without doing anything.

Four analyses:

    concentration   does one row, or one group, carry the whole result?
    shuffle         does the finding survive destroying the structure it needs?
    selection       is the best of N variants better than the best of N coin flips?
    describe        is the mean a description of anything, or is this bimodal?

Every result prints its interpretation, and says plainly when the data is too
small or too degenerate to interpret. Standard library only.

    python3 decompose.py --demo
    python3 decompose.py concentration trades.csv --value pnl --label instrument
    python3 decompose.py shuffle returns.csv --value daily_return
    python3 decompose.py selection --sharpe 0.9 --tried 40 --periods 250
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------------------


def load_rows(path: str) -> list[dict]:
    """Read a CSV or JSON file into a list of dicts. JSON may be a list or {data: [...]}."""
    p = Path(path)
    if not p.exists():
        sys.exit(f"error: no such file: {path}")
    text = p.read_text()
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("data", "rows", "records", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            sys.exit("error: JSON must be a list of objects, or {data: [...]}")
        return data
    return list(csv.DictReader(text.splitlines()))


def numeric_column(rows: list[dict], field: str) -> list[float]:
    """Pull one numeric column, refusing to silently drop unparseable rows.

    Silently skipping bad rows is precisely the undeclared filter this skill warns
    about, so anything unparseable is an error naming the row.
    """
    if not rows:
        sys.exit("error: no rows")
    if field not in rows[0]:
        sys.exit(f"error: no column {field!r}. Available: {sorted(rows[0])}")
    out = []
    for i, row in enumerate(rows):
        raw = str(row.get(field, "")).strip().replace(",", "").replace("$", "")
        try:
            value = float(raw)
        except ValueError:
            sys.exit(
                f"error: row {i} has non-numeric {field!r}={row.get(field)!r}. "
                f"Decide what it means and encode it; dropping it silently would be "
                f"an undeclared filter."
            )
        if not math.isfinite(value):
            sys.exit(
                f"error: row {i} has {field!r}={value}. A NaN or infinity means an "
                f"upstream computation already failed. Fix the source."
            )
        out.append(value)
    return out


def _mean(xs) -> float:
    return sum(xs) / len(xs)


# --------------------------------------------------------------------------------------
# 1. concentration
# --------------------------------------------------------------------------------------


def concentration(values, labels=None) -> str:
    """Does one observation, or one group, carry the entire result?

    Two questions a mean never answers: would the finding survive removing the top
    contributor, and does the SIGN depend on it. The second is the Monday-morning
    test when `labels` names the suspected cause rather than the calendar.
    """
    n = len(values)
    if n < 3:
        return f"n={n} is too small to decompose. Report the observations individually."

    total = sum(values)
    lines = [f"n = {n}    total = {total:,.6g}    mean = {total / n:,.6g}"]

    # --- single-observation dominance
    idx = max(range(n), key=lambda i: abs(values[i]))
    top = values[idx]
    without = total - top
    mass = sum(abs(v) for v in values)
    share = abs(top) / mass if mass else 0.0
    who = f"{labels[idx]!r}" if labels else f"row {idx}"

    lines.append("")
    lines.append(f"Largest single observation: {who} = {top:,.6g}")
    lines.append(f"  {share:.1%} of total absolute magnitude")
    lines.append(f"  total without it: {without:,.6g}")

    if total and without and (total > 0) != (without > 0):
        lines.append(
            f"  >> THE SIGN DEPENDS ON THIS ONE OBSERVATION. {total:,.6g} becomes "
            f"{without:,.6g} without it. This is not a population effect. Report it "
            f"as one observation."
        )
    elif share >= 0.5:
        lines.append(
            f"  >> One observation is {share:.0%} of the magnitude. Attribute the "
            f"finding to it, or show the finding holds with it removed."
        )
    else:
        lines.append(f"  >> No single observation dominates (largest is {share:.0%}).")

    # --- group dominance
    if labels:
        counts = Counter(labels)
        eligible = [g for g, c in counts.items() if c / n <= 0.5]
        if not eligible:
            lines.append("")
            lines.append(
                f"No group holds 50% or less of the rows ({dict(counts)}), so removing "
                f"one always moves the number. Regroup by a finer key."
            )
            return "\n".join(lines)

        full = _mean(values)
        scored = []
        for g in eligible:
            kept = [v for v, lab in zip(values, labels) if lab != g]
            if kept:
                scored.append((abs(_mean(kept) - full), g, _mean(kept), counts[g]))
        scored.sort(reverse=True)
        shift, group, without_mean, group_n = scored[0]
        rel = shift / abs(full) if full else math.inf

        lines.append("")
        lines.append(f"Group with the most influence (of {len(counts)} groups):")
        lines.append(f"  {group!r} ({group_n} of {n} rows)")
        lines.append(f"  mean with it: {full:,.6g}   without it: {without_mean:,.6g}")

        if full and without_mean and (full > 0) != (without_mean > 0):
            lines.append(
                f"  >> REMOVING {group!r} FLIPS THE SIGN. The effect belongs to this "
                f"group, not to the population. Any conclusion about the whole "
                f"population is wrong as stated."
            )
        elif rel >= 0.5:
            lines.append(
                f"  >> Removing {group!r} moves the mean {rel:.0%}. Report the "
                f"conditional finding: the effect is concentrated here."
            )
        else:
            lines.append(
                f"  >> No single group dominates (largest shift {rel:.0%}). The effect "
                f"looks broad-based."
            )
        lines.append("")
        lines.append(
            "  Reminder: this is only meaningful if you grouped by the SUSPECTED "
            "CAUSE (instrument, customer, venue), not by the label you are about to "
            "blame (day of week, month)."
        )

    # --- tail dominance
    if n >= 20:
        k = max(1, n // 20)
        worst = sorted(values)[:k]
        worst_sum = sum(worst)
        lines.append("")
        lines.append(f"Worst {k} of {n} observations (bottom 5%): {worst_sum:,.6g}")
        if abs(worst_sum) > abs(total):
            lines.append(
                f"  >> TAIL-DOMINATED. The worst {k} exceed the entire result of "
                f"{total:,.6g}. The headline number is a statement about {k} "
                f"observations, not about the process. An expectancy that depends on "
                f"the tail not repeating is a bet on the tail, not an edge."
            )
        else:
            lines.append("  >> Result is not dominated by its worst observations.")

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# 2. shuffle (permutation control)
# --------------------------------------------------------------------------------------


def shuffle_test(values, statistic="trend", trials=500, seed=0) -> str:
    """Destroy the structure the claim depends on, and confirm the finding dies.

    If a statistic survives having its own premise shuffled away, it is measuring
    the pipeline rather than the world.
    """
    n = len(values)
    if n < 10:
        return f"n={n} is too small for a permutation test. Need at least 10."
    if trials < 19:
        return (
            f"trials={trials} cannot produce a p-value below {1 / (trials + 1):.3f}, "
            f"so this test could only ever return one answer. Use 200 or more."
        )

    def trend(xs):
        m = len(xs)
        mx = (m - 1) / 2
        my = _mean(xs)
        den = sum((i - mx) ** 2 for i in range(m))
        return sum((i - mx) * (x - my) for i, x in enumerate(xs)) / den if den else 0.0

    fns = {"trend": trend, "mean": _mean, "sum": sum}
    if statistic not in fns:
        sys.exit(f"error: statistic must be one of {sorted(fns)}")
    fn = fns[statistic]

    observed = fn(values)
    rng = random.Random(seed)
    pool = list(values)
    null = []
    for _ in range(trials):
        rng.shuffle(pool)
        null.append(fn(pool))

    extreme = sum(1 for v in null if abs(v) >= abs(observed))
    p = (extreme + 1) / (trials + 1)

    lines = [
        f"statistic: {statistic}   n = {n}   shuffles = {trials}",
        f"observed:  {observed:,.6g}",
        f"shuffled:  {min(null):,.6g} to {max(null):,.6g}",
        f"p-value:   {p:.4f}   ({extreme} of {trials} shuffles were at least as extreme)",
        "",
    ]

    if max(null) - min(null) == 0:
        lines.append(
            ">> DEGENERATE. Every shuffle returned the same value, so this statistic "
            "is invariant to the structure it claims to measure. It cannot be evidence "
            "for the claim. This is usually an algebraic identity, not a test."
        )
    elif p > 0.05:
        lines.append(
            f">> NOT DISTINGUISHABLE FROM SHUFFLED DATA (p={p:.3f}). The finding is "
            f"consistent with the ordering carrying no information."
        )
    else:
        lines.append(
            f">> Survives the shuffle (p={p:.3f}). The ordering carries information "
            f"a random arrangement does not."
        )

    lines.append("")
    lines.append(
        "CAVEAT: shuffling assumes rows are exchangeable. For autocorrelated time "
        "series this destroys real serial structure and overstates significance. "
        "If order matters in your data, use a block bootstrap instead. This script "
        "cannot detect that for you."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# 3. selection (multiple testing)
# --------------------------------------------------------------------------------------


def _erfinv(y: float) -> float:
    """Inverse error function via a rational seed plus Newton refinement."""
    if y <= -1:
        return -math.inf
    if y >= 1:
        return math.inf
    a = 0.147
    ln = math.log(1 - y * y)
    t = 2 / (math.pi * a) + ln / 2
    x = math.copysign(math.sqrt(max(math.sqrt(t * t - ln / a) - t, 0.0)), y)
    for _ in range(3):
        x -= (math.erf(x) - y) / (2 / math.sqrt(math.pi) * math.exp(-x * x))
    return x


def selection(sharpe: float, tried: int, periods: int) -> str:
    """Is the best of N variants better than the best of N coin flips?

    The expected maximum Sharpe from pure noise grows with the number of variants
    searched (Bailey & Lopez de Prado 2014). `sharpe` must be STANDARDIZED
    (mean/stdev per period), never a raw P&L or return: the ceiling is in
    standard-deviation units, so feeding it dollars is a units error.
    """
    if tried < 1 or periods < 2:
        return "error: need tried >= 1 and periods >= 2."
    if abs(sharpe) > 20:
        return (
            f"error: sharpe={sharpe:,.6g} is outside any plausible Sharpe range, so "
            f"this is almost certainly a raw P&L or return. The noise ceiling is in "
            f"standard-deviation units. Pass mean(returns)/stdev(returns) instead."
        )

    euler = 0.5772156649015329

    def z(p):
        return math.sqrt(2) * _erfinv(2 * p - 1)

    expected_max = (
        0.0
        if tried == 1
        else (1 - euler) * z(1 - 1 / tried) + euler * z(1 - 1 / (tried * math.e))
    )
    ceiling = expected_max * (1 / math.sqrt(periods - 1))

    lines = [
        f"best Sharpe:   {sharpe:,.4g}",
        f"variants tried: {tried}      periods: {periods}",
        f"noise ceiling:  {ceiling:,.4g}   (best of {tried} tries on pure noise)",
        "",
    ]
    if sharpe <= ceiling:
        lines.append(
            f">> AT OR BELOW THE NOISE CEILING. Searching {tried} variants produces a "
            f"best Sharpe near {ceiling:,.4g} even when every variant is worthless. "
            f"This is a selection artifact, not an edge."
        )
    else:
        lines.append(
            f">> Clears the ceiling for {tried} variants. Not proof of an edge, but "
            f"not explained by the search alone."
        )
    lines.append("")
    lines.append(
        "Count EVERY variant you tried and abandoned, not just the one you kept. "
        "Undercounting here is the most common way this check is defeated."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# 4. describe
# --------------------------------------------------------------------------------------


def describe(values) -> str:
    """Is the mean a description of anything, or does it describe no observation?"""
    n = len(values)
    if n < 8:
        return f"n={n} is too small to characterise a distribution."

    vals = sorted(values)
    mean = _mean(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    lines = [
        f"n = {n}   mean = {mean:,.6g}   median = {median:,.6g}   sd = {sd:,.6g}",
        f"min = {vals[0]:,.6g}   max = {vals[-1]:,.6g}",
        "",
    ]
    if sd == 0:
        lines.append(">> Zero variance. Every observation is identical.")
        return "\n".join(lines)

    skew = sum(((v - mean) / sd) ** 3 for v in vals) / n
    unique = sorted(set(vals))

    # Gap statistic on UNIQUE support points. Using every sorted observation would
    # make the typical spacing zero on any repeated-value data, so ordinary Likert
    # scores and rounded prices would read as infinitely bimodal. Deduplicating is
    # the whole fix: evenly spaced discrete data then has a gap ratio near 1 and
    # stays quiet on its own, with no special case for "discrete" needed.
    #
    # An earlier version also refused to run below 8 distinct values. Mutation
    # testing showed that guard was not merely untested but harmful: it suppressed
    # genuinely bimodal discrete data (a price ladder at 1,2,3 versus 50,51,52 is a
    # real two-mode population), while contributing nothing to the discrete cases it
    # was written for, which the deduplicated ratio already handles.
    if len(unique) < 3:
        lines.append(
            f">> Only {len(unique)} distinct value(s). Report the frequency table, not "
            f"a mean."
        )
        return "\n".join(lines)

    gaps = [(unique[i + 1] - unique[i], i) for i in range(len(unique) - 1)]
    # Deduplicating above guarantees every gap is positive, so no zero-filter is
    # needed here. Keeping both would be two mechanisms for one guard, and neither
    # would ever be exercised alone.
    spacings = sorted(g for g, _ in gaps)
    typical = spacings[len(spacings) // 2]
    biggest, at = max(gaps)
    ratio = biggest / typical if typical else math.inf
    left = sum(v <= unique[at] for v in vals) / n

    if ratio > 10 and 0.15 <= left <= 0.85:
        lines.append(
            f">> LOOKS BIMODAL. A gap of {biggest:,.6g} is {ratio:,.0f}x the typical "
            f"spacing, splitting the data {left:.0%}/{1 - left:.0%}. A mean of "
            f"{mean:,.6g} describes no observation. Split and report each mode."
        )
    elif abs(skew) > 2:
        lines.append(
            f">> HEAVY SKEW ({skew:+.2f}). Mean {mean:,.6g} vs median {median:,.6g}. "
            f"Report the median and the tail, not the mean alone."
        )
    else:
        lines.append(f">> Roughly symmetric (skew {skew:+.2f}). The mean is a fair summary.")
    if len(unique) <= 10:
        lines.append(
            f"   Note: only {len(unique)} distinct values. Consider a frequency table "
            f"alongside any summary statistic."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# demo + cli
# --------------------------------------------------------------------------------------


def demo() -> None:
    print("=" * 74)
    print("DEMO 1  The Monday-morning problem")
    print("=" * 74)
    print(
        "Losses look like they cluster on Monday. Grouping by the SUSPECTED CAUSE\n"
        "(the instrument) instead of the calendar shows what is really happening.\n"
    )
    rng = random.Random(11)
    vals, labels = [], []
    for _ in range(180):
        vals.append(rng.gauss(40, 60))
        labels.append("ordinary_trades")
    for _ in range(20):
        vals.append(rng.gauss(-900, 80))
        labels.append("weekly_contract_X")
    print(concentration(vals, labels))

    print()
    print("=" * 74)
    print("DEMO 2  A profitable average that is really nine bad trades")
    print("=" * 74)
    print()
    print(concentration([12.54] * 194 + [-202.5] * 9))

    print()
    print("=" * 74)
    print("DEMO 3  A statistic that cannot fail")
    print("=" * 74)
    print()
    print(shuffle_test([1.0, 5.0, -3.0, 9.0, 2.0, 7.0, -1.0, 4.0, 0.5, 6.0], "sum", 200))

    print()
    print("=" * 74)
    print("DEMO 4  The best of 200 variants")
    print("=" * 74)
    print()
    print(selection(0.28, 200, 60))


def selftest() -> int:
    """Assert each analysis on cases with a known right answer.

    Deliberately small. It exists so a change to this file cannot silently invert a
    verdict, not to prove the analyses are correct in general. Each case pairs a
    MUST-FIRE input with a MUST-NOT-FIRE input, because a checker that fires on
    everything is worthless in a quieter way than one that never fires.
    """
    rng = random.Random(11)
    cases = []

    # concentration: one group flips the sign, versus a broad-based effect
    vals = [rng.gauss(40, 60) for _ in range(180)] + [rng.gauss(-900, 80) for _ in range(20)]
    labels = ["ordinary"] * 180 + ["weekly_X"] * 20
    cases.append(("group flip fires", "FLIPS THE SIGN", concentration(vals, labels), True))
    broad = [rng.gauss(-120, 30) for _ in range(150)]
    cases.append(
        (
            "broad effect stays quiet",
            "FLIPS THE SIGN",
            concentration(broad, [f"g{i % 15}" for i in range(150)]),
            False,
        )
    )

    # concentration: single observation carries the sign
    cases.append(
        ("single row flip", "DEPENDS ON THIS ONE", concentration([-40, -35, -50, 1200]), True)
    )

    # tail dominance both directions
    cases.append(
        ("tail dominance fires", "TAIL-DOMINATED", concentration([12.54] * 194 + [-202.5] * 9), True)
    )
    cases.append(
        (
            "healthy book stays quiet",
            "TAIL-DOMINATED",
            concentration([rng.gauss(12, 8) for _ in range(300)]),
            False,
        )
    )

    # shuffle: degenerate statistic, and a real trend
    cases.append(
        ("identity detected", "DEGENERATE", shuffle_test(list(range(20)), "sum", 200), True)
    )
    trend_data = [rng.gauss(0, 1) + i * 0.4 for i in range(60)]
    cases.append(("real trend survives", "NOT DISTINGUISHABLE", shuffle_test(trend_data, "trend", 400), False))
    noise_rng = random.Random(0)
    noise = [noise_rng.gauss(0, 1) for _ in range(80)]
    cases.append(("noise flagged", "NOT DISTINGUISHABLE", shuffle_test(noise, "trend", 400), True))
    cases.append(("too few trials refused", "could only ever return one answer", shuffle_test([1.0] * 20, "mean", 5), True))

    # selection
    cases.append(("noise ceiling fires", "AT OR BELOW", selection(0.28, 200, 60), True))
    cases.append(("real edge passes", "AT OR BELOW", selection(1.2, 5, 250), False))
    cases.append(("raw PnL refused", "raw P&L", selection(609.60, 200, 203), True))

    # describe
    lo = [rng.gauss(-500, 25) for _ in range(30)]
    hi = [rng.gauss(500, 25) for _ in range(30)]
    cases.append(("bimodal detected", "LOOKS BIMODAL", describe(lo + hi), True))
    cases.append(("discrete data not bimodal", "LOOKS BIMODAL", describe([1, 2, 3, 4, 5] * 20), False))
    cases.append(
        (
            "genuinely bimodal discrete IS caught",
            "LOOKS BIMODAL",
            describe([1, 2, 3] * 20 + [50, 51, 52] * 20),
            True,
        )
    )
    cases.append(("integer counts stay quiet", "LOOKS BIMODAL", describe([0, 1, 2, 3] * 25), False))
    # Repeated values must be deduplicated before the gap statistic, or the typical
    # spacing is zero and every tied dataset reads as infinitely bimodal.
    cases.append(
        ("ties do not fake a gap", "LOOKS BIMODAL", describe([7.0] * 40 + [7.5] * 40 + [8.0] * 40), False)
    )
    # Concentration WITHOUT a sign flip: same-sign data where one row / one group
    # still carries most of the result. Only the share and influence branches can
    # catch these, so without them the checker silently downgrades to a sign test.
    cases.append(
        ("one row dominates without flipping", "is 87% of the magnitude", concentration([8700, 400, 300, 250, 200, 150]), True)
    )
    hot_rng = random.Random(31)
    hot_vals = [hot_rng.gauss(-20, 5) for _ in range(120)] + [hot_rng.gauss(-400, 20) for _ in range(15)]
    hot_labels = [f"desk_{i % 12}" for i in range(120)] + ["desk_hot"] * 15
    cases.append(
        ("one group dominates without flipping", "Report the conditional finding", concentration(hot_vals, hot_labels), True)
    )

    skewed_rng = random.Random(41)
    cases.append(
        (
            "heavy skew reported",
            "HEAVY SKEW",
            describe([math.exp(skewed_rng.gauss(0, 1.1)) for _ in range(300)]),
            True,
        )
    )
    cases.append(
        ("rounded prices not bimodal", "LOOKS BIMODAL", describe([10.25] * 30 + [10.5] * 30 + [10.75] * 30), False)
    )
    cases.append(
        ("normal data quiet", "LOOKS BIMODAL", describe([rng.gauss(50, 10) for _ in range(200)]), False)
    )

    # The file-parsing path: a silently skipped row is the undeclared filter this
    # whole skill warns about, so bad input must stop the run rather than shrink
    # the population without saying so.
    parse_cases = []
    try:
        numeric_column([{"x": "1.0"}, {"x": "N/A"}], "x")
        parse_cases.append(("bad row rejected", False))
    except SystemExit:
        parse_cases.append(("bad row rejected", True))
    try:
        numeric_column([{"x": "1.0"}, {"x": "nan"}], "x")
        parse_cases.append(("NaN rejected", False))
    except SystemExit:
        parse_cases.append(("NaN rejected", True))
    try:
        got = numeric_column([{"x": "$1,200.50"}, {"x": "-3"}], "x")
        parse_cases.append(("currency parsed", got == [1200.50, -3.0]))
    except SystemExit:
        parse_cases.append(("currency parsed", False))

    failed = 0
    for name, ok in parse_cases:
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")

    for name, needle, output, should_fire in cases:
        fired = needle in output
        ok = fired == should_fire
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"      expected {needle!r} {'present' if should_fire else 'absent'}")
    total = len(cases) + len(parse_cases)
    print(f"\n{total - failed}/{total} self-tests passed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decomposition arithmetic for the data-verification skill.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--demo", action="store_true", help="run worked examples, no data needed")
    parser.add_argument("--selftest", action="store_true", help="verify each analysis still fires correctly")
    sub = parser.add_subparsers(dest="cmd")

    c = sub.add_parser("concentration", help="does one row or group carry the result?")
    c.add_argument("file")
    c.add_argument("--value", required=True, help="numeric column")
    c.add_argument("--label", help="grouping column: the SUSPECTED CAUSE")

    s = sub.add_parser("shuffle", help="does the finding survive destroying its premise?")
    s.add_argument("file")
    s.add_argument("--value", required=True)
    s.add_argument("--statistic", default="trend", choices=["trend", "mean", "sum"])
    s.add_argument("--trials", type=int, default=500)
    s.add_argument("--seed", type=int, default=0)

    m = sub.add_parser("selection", help="best of N variants, or best of N coin flips?")
    m.add_argument("--sharpe", type=float, required=True, help="STANDARDIZED, not raw PnL")
    m.add_argument("--tried", type=int, required=True, help="every variant, including abandoned")
    m.add_argument("--periods", type=int, required=True)

    d = sub.add_parser("describe", help="is the mean a description of anything?")
    d.add_argument("file")
    d.add_argument("--value", required=True)

    args = parser.parse_args()

    if args.demo:
        demo()
        return 0
    if args.selftest:
        return selftest()
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "selection":
        print(selection(args.sharpe, args.tried, args.periods))
        return 0

    rows = load_rows(args.file)
    values = numeric_column(rows, args.value)

    if args.cmd == "concentration":
        labels = None
        if args.label:
            if args.label not in rows[0]:
                sys.exit(f"error: no column {args.label!r}. Available: {sorted(rows[0])}")
            labels = [str(r[args.label]) for r in rows]
        print(concentration(values, labels))
    elif args.cmd == "shuffle":
        print(shuffle_test(values, args.statistic, args.trials, args.seed))
    elif args.cmd == "describe":
        print(describe(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
