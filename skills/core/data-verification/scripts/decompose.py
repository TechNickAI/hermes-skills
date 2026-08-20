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


def confound(values, label_a, label_b, name_a="A", name_b="B") -> str:
    """Two competing explanations for the same rows. Can the data separate them?

    This is the Monday-morning test made executable. If the losses blamed on Monday
    were really one contract that trades every Monday, then grouping by day and
    grouping by instrument BOTH flip the sign, and no amount of arithmetic on this
    dataset can tell you which one is the cause.

    The check that separates them is a cross-tabulation: does the blamed label still
    matter INSIDE the entity, and does the entity still matter INSIDE the label? A
    real weekday effect shows up across many instruments. A confound does not.
    """
    n = len(values)
    if not (n == len(label_a) == len(label_b)):
        return "error: values and both label lists must be the same length."
    if n < 12:
        return f"n={n} is too small to separate two explanations."

    def flips(labels):
        full = _mean(values)
        out = []
        for g in sorted(set(labels)):
            kept = [v for v, lab in zip(values, labels) if lab != g]
            if kept and full and (_mean(kept) > 0) != (full > 0):
                out.append(g)
        return out

    flip_a, flip_b = flips(label_a), flips(label_b)
    lines = [
        f"n = {n}   overall mean = {_mean(values):,.6g}",
        f"{name_a}: removing {flip_a or 'no group'} flips the sign",
        f"{name_b}: removing {flip_b or 'no group'} flips the sign",
        "",
    ]

    if not (flip_a and flip_b):
        lines.append(
            f">> Only one explanation flips the result, so they are separable here. "
            f"Attribute to it, and still name the mechanism before calling it a cause."
        )
        return "\n".join(lines)

    # Both flip. Cross-tabulate to see whether either survives holding the other fixed.
    lines.append(
        ">> BOTH EXPLANATIONS FLIP THE SIGN on the same rows. Cross-tabulating to see "
        "whether either survives holding the other fixed:"
    )
    lines.append("")

    cells = {}
    for v, a, b in zip(values, label_a, label_b):
        cells.setdefault((a, b), []).append(v)

    # Does label_b still separate INSIDE a single label_a group, and vice versa?
    def survives_within(outer, inner, outer_name, inner_name):
        verdicts = []
        for o in sorted(set(outer)):
            sub = [(v, i) for v, out_, i in zip(values, outer, inner) if out_ == o]
            groups = {}
            for v, i in sub:
                groups.setdefault(i, []).append(v)
            usable = {g: vs for g, vs in groups.items() if len(vs) >= 3}
            if len(usable) < 2:
                continue
            means = {g: _mean(vs) for g, vs in usable.items()}
            spread = max(means.values()) - min(means.values())
            verdicts.append((o, spread, means))
        if not verdicts:
            return (
                f"   {inner_name} within {outer_name}: not enough overlap to test. "
                f"The two explanations are collinear in this data."
            )
        worst = max(v[1] for v in verdicts)
        # Compare the within-cell spread against the BETWEEN-group spread that made
        # this explanation look causal in the first place. Dividing by the overall
        # mean would be a different question, and near a mean of zero it explodes.
        between = {}
        for v, i in zip(values, inner):
            between.setdefault(i, []).append(v)
        b_means = [_mean(vs) for vs in between.values() if len(vs) >= 3]
        baseline = (max(b_means) - min(b_means)) if len(b_means) >= 2 else 0.0
        rel = worst / baseline if baseline else math.inf
        if rel < 0.5:
            return (
                f"   {inner_name} within {outer_name}: spread collapses to "
                f"{worst:,.6g}, versus {baseline:,.6g} between groups "
                f"({rel:.0%}). {inner_name} does NOT survive holding "
                f"{outer_name} fixed, so it is the label, not the cause."
            )
        return (
            f"   {inner_name} within {outer_name}: spread {worst:,.6g} versus "
            f"{baseline:,.6g} between groups ({rel:.0%}). {inner_name} survives "
            f"holding {outer_name} fixed, so it may carry real signal."
        )

    verdict_a = survives_within(label_b, label_a, name_b, name_a)
    verdict_b = survives_within(label_a, label_b, name_a, name_b)
    lines.append(verdict_b)
    lines.append(verdict_a)
    lines.append("")

    a_survives = "survives" in verdict_a
    b_survives = "survives" in verdict_b
    collinear = "not enough overlap" in verdict_a or "not enough overlap" in verdict_b

    if collinear:
        lines.append(
            "   COLLINEAR. Every row of one explanation sits inside a single value of "
            "the other, so this dataset cannot separate them at any sample size. "
            "Report the attribution as UNRESOLVED and get data where they vary "
            "independently."
        )
    elif a_survives and not b_survives:
        lines.append(
            f"   RESOLVED: {name_a} survives holding {name_b} fixed, and {name_b} "
            f"does not survive the reverse. {name_b} is the LABEL; {name_a} is where "
            f"the effect lives. Acting on {name_b} would keep the real cause and "
            f"discard the innocent rows that share the label."
        )
    elif b_survives and not a_survives:
        lines.append(
            f"   RESOLVED: {name_b} survives holding {name_a} fixed, and {name_a} "
            f"does not survive the reverse. {name_a} is the LABEL; {name_b} is where "
            f"the effect lives."
        )
    elif a_survives and b_survives:
        lines.append(
            "   BOTH survive holding the other fixed, so each carries some independent "
            "signal. Report them jointly, and do not attribute the whole effect to "
            "either alone."
        )
    else:
        lines.append(
            "   NEITHER survives holding the other fixed. The apparent effect is "
            "carried by their combination, not by either explanation. Report as "
            "UNRESOLVED."
        )

    lines.append("")
    lines.append(
        "   Whatever the arithmetic says, the tie-break is MECHANISM: an instrument, "
        "a customer, or a venue can cause a loss; a weekday cannot. A grouping "
        "without a mechanism is a place where the cause sits, not the cause."
    )
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


def ledger(opening, inflows, outflows, pnl, closing, tolerance=0.01) -> str:
    """Does the accounting close? opening + inflows - outflows + pnl == closing.

    The single largest sign error in the corpus was a P&L reported as +$1,086.86
    that was really -$120.84: sale proceeds and settlement were both counted as
    income while the cost basis was never allocated. No statistical check catches
    that, because the arithmetic on each piece was correct. Only the identity does.

    Every dollar must land in exactly one bucket. If the identity does not close,
    the residual IS the double-count, and its size usually names the mistake.
    """
    for label, value in [
        ("opening", opening), ("inflows", inflows), ("outflows", outflows),
        ("pnl", pnl), ("closing", closing),
    ]:
        if not math.isfinite(value):
            return f"error: {label}={value} is not a finite number."

    expected = opening + inflows - outflows + pnl
    residual = closing - expected
    scale = max(abs(closing), abs(expected), abs(inflows), 1e-9)
    rel = abs(residual) / scale

    lines = [
        f"opening {opening:>15,.2f}",
        f"+ inflows {inflows:>13,.2f}",
        f"- outflows {outflows:>12,.2f}",
        f"+ P&L {pnl:>17,.2f}",
        f"= expected {expected:>12,.2f}",
        f"  reported {closing:>13,.2f}",
        f"  residual {residual:>13,.2f}   ({rel:.2%} of scale)",
        "",
    ]
    if rel <= tolerance:
        lines.append(">> The identity closes. Every dollar is accounted for exactly once.")
        return "\n".join(lines)

    lines.append(
        f">> DOES NOT CLOSE. {residual:,.2f} is unexplained, which means a dollar is "
        f"counted twice, zero times, or in the wrong bucket."
    )
    if abs(residual - pnl) / scale <= tolerance:
        lines.append(
            "   The residual equals the P&L exactly. Classic double-count: the gain is "
            "in the closing balance AND added again as P&L."
        )
    elif pnl and abs(residual - 2 * pnl) / scale <= tolerance:
        lines.append("   The residual is twice the P&L. The gain is being counted three times.")
    elif inflows and abs(residual - inflows) / scale <= tolerance:
        lines.append(
            "   The residual equals inflows. Deposits are being treated as profit, or "
            "counted in both the balance and the P&L."
        )
    elif abs(residual + outflows) / scale <= tolerance:
        lines.append("   The residual is minus outflows. Withdrawals are being booked as losses.")
    else:
        lines.append(
            "   Check basis allocation first: proceeds counted as profit without "
            "subtracting what the position cost is the most common cause."
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
    vals, by_entity, by_label = [], [], []
    for i in range(180):
        vals.append(rng.gauss(40, 60))
        by_entity.append("ordinary_trades")
        by_label.append("Mon" if i % 5 == 0 else "Tue-Fri")
    for _ in range(20):
        # The problem contract happens to trade every Monday. That is a fact about
        # the CONTRACT, not about the day.
        vals.append(rng.gauss(-900, 80))
        by_entity.append("weekly_contract_X")
        by_label.append("Mon")

    print("--- grouped by INSTRUMENT (the entity that repeats) ---")
    print(concentration(vals, by_entity))
    print()
    print("--- grouped by DAY (the label you were about to blame) ---")
    print(concentration(vals, by_label))
    print()
    print(
        "BOTH flip the sign, on the SAME rows. The arithmetic cannot tell them\n"
        "apart, because the bad contract only traded on Mondays. Banning Monday\n"
        "keeps the loss (it trades again next Monday under another name) and gives\n"
        "up every good Monday trade. Only a mechanism separates these: a contract\n"
        "can cause losses, a weekday cannot. When two groupings both flip, you have\n"
        "found a confound, not a cause. Report it as unresolved and go find which\n"
        "one has a mechanism."
    )

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

    # confound: the Monday-morning problem must RESOLVE, and a real day effect
    # across many instruments must not be called a confound.
    cf_rng = random.Random(11)
    cv, ce, cl = [], [], []
    for i in range(180):
        cv.append(cf_rng.gauss(40, 60)); ce.append("ordinary"); cl.append("Mon" if i % 5 == 0 else "Tue")
    for _ in range(20):
        cv.append(cf_rng.gauss(-900, 80)); ce.append("weekly_X"); cl.append("Mon")
    cf_out = confound(cv, ce, cl, "instrument", "day")
    cases.append(("Monday confound resolves to instrument", "day is the LABEL", cf_out, True))
    cases.append(("confound names the mechanism rule", "a weekday cannot", cf_out, True))

    rv, re_, rl = [], [], []
    for i in range(200):
        mon = i % 5 == 0
        rv.append(cf_rng.gauss(-300 if mon else 60, 40))
        re_.append(f"inst_{i % 8}")
        rl.append("Mon" if mon else "Tue")
    cases.append(
        ("real day effect is not a confound", "Only one explanation flips", confound(rv, re_, rl, "instrument", "day"), True)
    )

    # ledger: the identity must close when it should and name the double-count when
    # it should not. This is the ONLY check covering the accounting bucket.
    # Perfectly collinear: the entity NEVER appears outside its label, so no dataset
    # of any size can separate them. This must be named, not silently resolved.
    col_v, col_e, col_l = [], [], []
    col_rng = random.Random(7)
    for _ in range(60):
        col_v.append(col_rng.gauss(50, 20)); col_e.append("normal_desk"); col_l.append("weekday")
    for _ in range(60):
        col_v.append(col_rng.gauss(-600, 20)); col_e.append("bad_desk"); col_l.append("weekend")
    cases.append(
        ("perfect collinearity named", "COLLINEAR", confound(col_v, col_e, col_l, "desk", "daytype"), True)
    )

    # A single row in its own cell must not be allowed to manufacture a within-group
    # spread. Without the minimum-cell guard this returns a confident verdict built
    # on one observation.
    thin_v, thin_e, thin_l = [], [], []
    thin_rng = random.Random(3)
    for i in range(100):
        thin_v.append(thin_rng.gauss(60, 15)); thin_e.append(f"e{i % 4}"); thin_l.append("Tue")
    for _ in range(12):
        thin_v.append(thin_rng.gauss(-800, 30)); thin_e.append("bad"); thin_l.append("Mon")
    thin_v.append(-40.0); thin_e.append("e0"); thin_l.append("Mon")
    cases.append(
        ("singleton cell cannot decide", "not enough overlap", confound(thin_v, thin_e, thin_l, "entity", "day"), True)
    )

    cases.append(("clean books close", "identity closes", ledger(1000, 500, 200, 130, 1430), True))
    cases.append(("broken books caught", "DOES NOT CLOSE", ledger(0, 5000, 0, 1086.86, 4879.16), True))
    cases.append(
        ("classic double-count named", "Classic double-count", ledger(1000, 0, 0, 250, 1500), True)
    )
    # Deposits booked as profit: 5000 in, no real gain, but 5000 also reported as
    # P&L, so the closing balance is 5000 higher than the identity allows.
    cases.append(
        ("deposits as profit named", "Deposits are being treated as profit", ledger(0, 5000, 0, 300, 10300), True)
    )
    cases.append(("non-finite ledger refused", "not a finite number", ledger(0, 0, 0, float("nan"), 100), True))

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

    cf = sub.add_parser("confound", help="two competing explanations: can data separate them?")
    cf.add_argument("file")
    cf.add_argument("--value", required=True)
    cf.add_argument("--group-a", required=True, help="e.g. the entity: instrument, customer")
    cf.add_argument("--group-b", required=True, help="e.g. the label: day_of_week, month")

    lg = sub.add_parser("ledger", help="does opening + in - out + pnl = closing?")
    lg.add_argument("--opening", type=float, required=True)
    lg.add_argument("--inflows", type=float, default=0.0)
    lg.add_argument("--outflows", type=float, default=0.0)
    lg.add_argument("--pnl", type=float, required=True)
    lg.add_argument("--closing", type=float, required=True)

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
    if args.cmd == "ledger":
        print(ledger(args.opening, args.inflows, args.outflows, args.pnl, args.closing))
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
    elif args.cmd == "confound":
        for col in (args.group_a, args.group_b):
            if col not in rows[0]:
                sys.exit(f"error: no column {col!r}. Available: {sorted(rows[0])}")
        print(
            confound(
                values,
                [str(r[args.group_a]) for r in rows],
                [str(r[args.group_b]) for r in rows],
                args.group_a,
                args.group_b,
            )
        )
    elif args.cmd == "describe":
        print(describe(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
