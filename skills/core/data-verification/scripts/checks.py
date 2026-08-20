"""Executable checks for the data-verification skill.

Design premise, from the audit that produced this skill: the analyst who wrote the
number cannot be the one who certifies it by reading it again. Intrinsic self-review
of reasoning does not reliably improve accuracy and often degrades it (Huang et al.,
ICLR 2024). Every function here therefore returns a machine-checkable verdict from
data, never from an opinion about the data.

Zero dependencies beyond the standard library so it runs anywhere an agent runs.

Vocabulary
----------
FAIL      the claim is contradicted. Do not ship it.
FLAG      the claim may be true but is not established by this evidence. Investigate.
PASS      this specific failure mode was tested for and not found. Nothing more.

A PASS is never evidence the number is right. It is evidence that one named way of
being wrong was ruled out.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


# --------------------------------------------------------------------------------------
# result type
# --------------------------------------------------------------------------------------


@dataclass
class Check:
    """One verification result."""

    name: str
    verdict: str  # PASS | FLAG | FAIL
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """A Check is truthy only when it PASSED.

        This is convenient (`if check: ship()`) and it is a trap, so it is stated
        here rather than discovered later. A FAIL is FALSY, which means the natural
        early-return idiom is silently inverted:

            guard = _finite(name, x=x)
            if guard:            # WRONG: a FAIL guard is falsy, so this never fires
                return guard

        That exact line shipped in this module and disabled every non-finite guard
        at once, so NaN inputs were certified PASS. Always compare against None when
        a helper returns `Check | None`:

            if guard is not None:   # correct
                return guard

        `test_guard_returns_are_not_truthiness_checks` in the eval harness enforces
        this by scanning the source, because the behavioural symptom (NaN passing)
        can be fixed while the idiom that caused it survives elsewhere.
        """
        return self.verdict == "PASS"

    def __str__(self) -> str:
        return f"[{self.verdict}] {self.name}: {self.detail}"


class Report(list):
    """A list of Checks that knows whether the analysis may ship."""

    @property
    def failed(self) -> list[Check]:
        return [c for c in self if c.verdict == "FAIL"]

    @property
    def flagged(self) -> list[Check]:
        return [c for c in self if c.verdict == "FLAG"]

    @property
    def may_ship(self) -> bool:
        return not self.failed and not self.flagged

    def summary(self) -> str:
        counts = Counter(c.verdict for c in self)
        head = (
            f"{counts['PASS']} pass, {counts['FLAG']} flag, {counts['FAIL']} fail"
            f" -- {'MAY SHIP' if self.may_ship else 'BLOCKED'}"
        )
        body = "\n".join(f"  {c}" for c in self if c.verdict != "PASS")
        return head + ("\n" + body if body else "")


# --------------------------------------------------------------------------------------
# input hygiene
# --------------------------------------------------------------------------------------


def _finite(name: str, **named: float) -> Check | None:
    """Reject NaN and infinity before any check reasons about a number.

    This guard exists because of a specific defect found in adversarial review of
    this very module: `multiple_testing(nan, 200, 60)` returned PASS, because every
    comparison against NaN is False and the code fell through to the success
    branch. A verification tool that hands a green light to corrupt data is worse
    than no verification tool, since it converts silent corruption into stated
    confidence. NaN is never a valid input here; it is the residue of a division by
    zero, an empty aggregate, or a failed parse upstream, all of which are exactly
    the provenance failures this skill exists to catch.
    """
    bad = {k: v for k, v in named.items() if isinstance(v, float) and not math.isfinite(v)}
    if not bad:
        return None
    return Check(
        name,
        "FAIL",
        f"Non-finite input: {', '.join(f'{k}={v}' for k, v in bad.items())}. "
        f"NaN or infinity means an upstream computation already failed (division by "
        f"zero, empty aggregate, failed parse). Fix the source; do not verify around it.",
        {"non_finite": {k: str(v) for k, v in bad.items()}},
    )


def _finite_series(name: str, values: Sequence[float]) -> Check | None:
    """Same guard for a series. Reports position so the bad row can be found."""
    bad = [i for i, v in enumerate(values) if isinstance(v, float) and not math.isfinite(v)]
    if not bad:
        return None
    shown = bad[:5]
    more = f" (and {len(bad) - 5} more)" if len(bad) > 5 else ""
    return Check(
        name,
        "FAIL",
        f"Series contains {len(bad)} non-finite value(s) at index {shown}{more}. "
        f"An aggregate over NaN is not a number, and silently dropping those rows "
        f"would be the undeclared filter this skill exists to catch. Resolve them "
        f"explicitly, then re-run.",
        {"non_finite_count": len(bad), "first_indices": shown},
    )


# --------------------------------------------------------------------------------------
# LANE 1 -- RECONCILE. Does the number tie to something computed a different way?
# --------------------------------------------------------------------------------------


def reconcile(
    claimed: float,
    independent: float,
    tolerance: float = 0.001,
    name: str = "reconcile",
    unit: str = "",
) -> Check:
    """Tie a number to an independently derived value.

    `independent` must come from a different data path, not a refactor of the same
    code. Re-running your own pipeline is not reconciliation.
    """
    guard = _finite(name, claimed=claimed, independent=independent)
    if guard is not None:
        return guard
    if independent == 0:
        drift = abs(claimed)
        rel = math.inf if claimed else 0.0
    else:
        drift = claimed - independent
        rel = abs(drift / independent)

    if rel <= tolerance:
        return Check(
            name,
            "PASS",
            f"{claimed:,.6g}{unit} ties to {independent:,.6g}{unit} within {tolerance:.2%}",
            {"claimed": claimed, "independent": independent, "relative_drift": rel},
        )

    ratio = claimed / independent if independent else math.inf
    hint = ""
    for factor, label in (
        (10, "10x"),
        (100, "100x"),
        (1000, "1000x"),
        (10_000, "1e4, basis-points-vs-percent"),
        (60, "60x, seconds-vs-minutes"),
        (252, "252x, daily-vs-annual trading days"),
        (365, "365x, daily-vs-annual calendar days"),
        (12, "12x, monthly-vs-annual"),
    ):
        for candidate in (factor, 1 / factor):
            if candidate and abs(ratio / candidate - 1) < 0.02:
                hint = (
                    f" Ratio is ~{label}; suspect a unit or annualization error, "
                    f"not a data error."
                )
                break
        if hint:
            break

    return Check(
        name,
        "FAIL",
        f"{claimed:,.6g}{unit} does not tie to {independent:,.6g}{unit} "
        f"(off by {rel:.2%}, ratio {ratio:,.4g}).{hint}",
        {"claimed": claimed, "independent": independent, "relative_drift": rel, "ratio": ratio},
    )


def reconcile_population(
    analyzed_n: int,
    source_n: int,
    name: str = "population_reconcile",
    tolerance: float = 0.0,
) -> Check:
    """Every row that left the source must be accounted for.

    An unexplained gap between what the source holds and what you analyzed is a
    silent filter, and a silent filter is indistinguishable from a hypothesis you
    did not declare.
    """
    if source_n == 0:
        return Check(name, "FAIL", "Source population is zero; nothing to reconcile.", {})
    if analyzed_n < 0 or source_n < 0:
        return Check(name, "FAIL", "Negative row counts are not meaningful.", {})
    dropped = source_n - analyzed_n
    rate = dropped / source_n
    if abs(rate) <= tolerance:
        return Check(
            name, "PASS", f"All {source_n:,} source rows accounted for.", {"dropped": dropped}
        )
    return Check(
        name,
        "FAIL",
        f"{dropped:,} of {source_n:,} rows ({rate:.1%}) left the analysis unexplained. "
        f"Name the filter and show it is not correlated with the outcome.",
        {"analyzed_n": analyzed_n, "source_n": source_n, "dropped": dropped, "drop_rate": rate},
    )


# Canonical unit aliases. This is intentionally small and explicit rather than a
# pretend general-purpose dimensional-analysis engine. Unknown units are normalized
# lexically; known aliases collapse to the same canonical unit. A scale change
# (cents vs dollars, bps vs percent) remains DIFFERENT so the caller must perform
# and cite the conversion rather than letting this check do it invisibly.
_UNIT_ALIASES = {
    "$": "usd",
    "dollar": "usd",
    "dollars": "usd",
    "us_dollar": "usd",
    "usdollars": "usd",
    "¢": "usd_cent",
    "cent": "usd_cent",
    "cents": "usd_cent",
    "%": "percent",
    "pct": "percent",
    "percentage_point": "percent",
    "percentage_points": "percent",
    "bp": "basis_point",
    "bps": "basis_point",
    "basis_points": "basis_point",
}


def _canonical_unit(unit: str) -> str:
    """Normalize spelling, never scale.

    `$` and `usd` are aliases. `cents` and `usd` are not, because silently scaling
    during a verification check conceals the conversion the analysis is supposed to
    make explicit. Compound units retain their denominator: `usd` and
    `usd_per_share` are incompatible even though both contain dollars.
    """
    import re

    # Normalize visual ratio separators to the word `per` BEFORE collapsing the
    # remaining punctuation. `USD / share`, `usd-per-share`, and `usd_per_share`
    # should carry the same declared dimension.
    text = unit.strip().lower()
    text = re.sub(r"\s*/\s*", "_per_", text)
    text = re.sub(r"\s+-\s+|\s+per\s+", "_per_", text)
    text = re.sub(r"[\s-]+", "_", text)
    normalized = re.sub(r"_+", "_", text).strip("_")
    # Canonicalize each compound token, preserving per-unit dimensions.
    parts = normalized.split("_per_")
    return "_per_".join(_UNIT_ALIASES.get(p, p) for p in parts)


def check_units(*quantities: tuple[float, str], name: str = "units") -> Check:
    """Refuse to compare quantities carrying different units.

    This is the single highest-yield check in the module. In the audit that produced
    this skill, the most expensive error was comparing a figure denominated in users
    against a figure denominated in contract price and declaring an edge 55x too
    small -- arithmetic that was flawless and meaningless.

    This validates DECLARED units, not the truth of the declaration. If an analyst
    labels dollars-per-share as plain dollars, no function inspecting the number can
    recover the missing denominator. Gate 1 therefore requires the unit be written
    down from source metadata before computation. This function catches incompatible
    declarations and common alias noise; it cannot catch a lie in the label.
    """
    guard = _finite(name, **{f"q{i}": v for i, (v, _) in enumerate(quantities)})
    if guard is not None:
        return guard
    raw = [u for _, u in quantities]
    canonical = [_canonical_unit(u) for u in raw]
    units = set(canonical)
    if len(units) <= 1:
        unit = canonical[0] if canonical else ""
        aliases = sorted(set(raw))
        detail = f"All quantities in '{unit}'."
        if len(aliases) > 1:
            detail += f" Normalized aliases: {aliases}."
        return Check(name, "PASS", detail, {"canonical_unit": unit, "declared": raw})
    return Check(
        name,
        "FAIL",
        f"Comparing incompatible units: declared {raw}, canonical {canonical}. Convert "
        f"to one common unit through an explicit, cited conversion before comparing. "
        f"A denominator is part of the unit: usd and usd_per_share are not the same.",
        {"declared": raw, "canonical_units": canonical},
    )


# --------------------------------------------------------------------------------------
# LANE 2 -- DECOMPOSE. Is the aggregate telling the truth about its parts?
# --------------------------------------------------------------------------------------


def concentration(
    values: Sequence[float],
    labels: Sequence[Any] | None = None,
    threshold: float = 0.5,
    name: str = "concentration",
) -> Check:
    """Detect an aggregate that is really one or two rows wearing a costume.

    Answers the question a mean never answers: if the top contributor were removed,
    would the finding survive? Also catches the sign flip, where an aggregate is
    positive only because one huge winner offsets a broadly losing population.
    """
    vals = list(values)
    if not vals:
        return Check(name, "FAIL", "Empty series; no aggregate is defensible.", {})
    guard = _finite_series(name, vals)
    if guard is not None:
        return guard

    labels = list(labels) if labels is not None else list(range(len(vals)))
    total = sum(vals)
    ranked = sorted(zip(vals, labels), key=lambda p: -abs(p[0]))
    top_val, top_label = ranked[0]

    ex_total = total - top_val
    sign_flips = total != 0 and ex_total != 0 and (total > 0) != (ex_total > 0)
    share = abs(top_val) / sum(abs(v) for v in vals) if any(vals) else 0.0
    positives = sum(1 for v in vals if v > 0)
    ev = {
        "n": len(vals),
        "total": total,
        "top_label": top_label,
        "top_value": top_val,
        "top_share_of_absolute_mass": share,
        "total_excluding_top": ex_total,
        "sign_flips_without_top": sign_flips,
        "share_positive": positives / len(vals),
    }

    if sign_flips:
        return Check(
            name,
            "FAIL",
            f"The sign of the result depends on a single observation ({top_label!r}, "
            f"{top_val:,.6g}). Total {total:,.6g} becomes {ex_total:,.6g} without it. "
            f"This is not a population effect; report it as one observation.",
            ev,
        )
    if share >= threshold:
        return Check(
            name,
            "FLAG",
            f"{top_label!r} carries {share:.1%} of the absolute mass across n={len(vals)}. "
            f"Attribute the finding to that entity, or show it holds with the entity removed.",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"No single observation exceeds {threshold:.0%} of mass (top {share:.1%}, n={len(vals)}).",
        ev,
    )


def leave_one_out(
    values: Sequence[float],
    labels: Sequence[Any],
    statistic: Callable[[Sequence[float]], float] | None = None,
    name: str = "leave_one_out",
) -> Check:
    """Ask whether a grouping variable is the cause, or just where the cause was sitting.

    This is the Monday-morning test. When losses cluster on Monday, the honest
    question is not 'should we stop trading Monday' but 'does the Monday effect
    survive removing the one instrument that happens to trade every Monday'. If it
    does not, the calendar was a label on the cause, not the cause.

    Pass values grouped by the SUSPECTED CAUSE (the instrument, the counterparty),
    not by the grouping you are about to blame.
    """
    statistic = statistic or (lambda xs: sum(xs) / len(xs) if xs else 0.0)
    vals, labs = list(values), list(labels)
    guard = _finite_series(name, vals)
    if guard is not None:
        return guard
    if len(vals) != len(labs):
        return Check(
            name,
            "FAIL",
            f"values and labels disagree in length ({len(vals)} vs {len(labs)}); the "
            f"pairing is wrong and every attribution below it would be arbitrary.",
            {},
        )
    if len(vals) < 3:
        return Check(name, "FLAG", f"n={len(vals)} is too small to decompose.", {"n": len(vals)})

    full = statistic(vals)
    # Only consider groups that are a MINORITY of the data. Removing the majority
    # group necessarily moves the statistic a great deal, so without this guard the
    # check reliably names the biggest group as the culprit and the real culprit is
    # never surfaced. That defect fired on the first replay of the Monday-morning
    # incident, which is exactly the case the check exists to catch.
    counts = Counter(labs)
    eligible = [g for g, c in counts.items() if c / len(vals) <= 0.5]
    if not eligible:
        return Check(
            name,
            "FLAG",
            "No group holds 50% or less of the data; the population cannot be decomposed "
            "this way. Regroup by a finer key.",
            {"group_sizes": dict(counts)},
        )

    worst_label, worst_stat, worst_shift = None, None, -1.0
    for uniq in eligible:
        kept = [v for v, lab in zip(vals, labs) if lab != uniq]
        if not kept:
            continue
        stat = statistic(kept)
        shift = abs(stat - full)
        if shift > worst_shift:
            worst_label, worst_stat, worst_shift = uniq, stat, shift

    if worst_label is None:
        return Check(name, "FLAG", "Only one group present; nothing to leave out.", {})

    flips = full != 0 and worst_stat is not None and (full > 0) != (worst_stat > 0)
    rel = worst_shift / abs(full) if full else math.inf
    ev = {
        "statistic_full": full,
        "most_influential_group": worst_label,
        "statistic_without": worst_stat,
        "relative_shift": rel,
        "sign_flips": flips,
    }
    if flips:
        return Check(
            name,
            "FAIL",
            f"Removing group {worst_label!r} flips the statistic from {full:,.6g} to "
            f"{worst_stat:,.6g}. The effect belongs to that group, not to the population.",
            ev,
        )
    if rel >= 0.5:
        return Check(
            name,
            "FLAG",
            f"Removing group {worst_label!r} moves the statistic {rel:.0%} "
            f"({full:,.6g} -> {worst_stat:,.6g}). Report the conditional finding.",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"No single group moves the statistic more than 50% (max {rel:.0%}, "
        f"group {worst_label!r}).",
        ev,
    )


def distribution_shape(values: Sequence[float], name: str = "distribution_shape") -> Check:
    """Refuse a mean where the mean is not a description of anything.

    Catches heavy skew and suspected bimodality, the two cases where a central
    tendency is a number that no observation resembles.
    """
    guard = _finite_series(name, list(values))
    if guard is not None:
        return guard
    vals = sorted(values)
    n = len(vals)
    if n < 8:
        return Check(name, "FLAG", f"n={n} is too small to characterise a distribution.", {"n": n})

    mean = sum(vals) / n
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sd = math.sqrt(var)
    ev: dict[str, Any] = {"n": n, "mean": mean, "median": median, "sd": sd}

    if sd == 0:
        return Check(name, "PASS", "Zero variance; the mean is exact.", ev)

    skew = sum(((v - mean) / sd) ** 3 for v in vals) / n
    ev["skew"] = skew

    # Gap statistic. Compare the largest interior jump to TYPICAL adjacent spacing,
    # not to the IQR: when a distribution is cleanly bimodal the IQR spans the two
    # modes, so an IQR-relative test is largest exactly when the defect is worst and
    # silently passes. Median spacing is a within-mode scale and does not have that
    # blind spot.
    # Gap statistic on UNIQUE support points. Using every sorted observation makes
    # median_spacing zero on any repeated-value dataset, so ordinary Likert scores,
    # rounded prices, and integer counts all become "infinitely bimodal". Adversarial
    # review reproduced the false FAIL with `[1,2,3,4,5] * 20` and rounded prices.
    unique = sorted(set(vals))
    ev["unique_values"] = len(unique)
    if len(unique) < 8:
        # With fewer than eight support points there is not enough resolution for a
        # gap heuristic to distinguish a true mixture from ordinary discreteness.
        # Do not call it bimodal. The mean/median/skew diagnostics above are still
        # reported so the caller can choose a categorical analysis when appropriate.
        if abs(skew) > 2:
            return Check(
                name,
                "FLAG",
                f"Discrete support ({len(unique)} unique values) with heavy skew "
                f"({skew:+.2f}); a continuous bimodality test is invalid here. Report "
                f"the frequency table and median rather than the mean alone.",
                ev,
            )
        return Check(
            name,
            "PASS",
            f"Discrete support ({len(unique)} unique values); continuous bimodality "
            f"test not applied. Skew {skew:+.2f}; inspect the frequency table for modes.",
            ev,
        )

    gaps = [(unique[i + 1] - unique[i], i) for i in range(len(unique) - 1)]
    positive_spacings = sorted(g for g, _ in gaps if g > 0)
    median_spacing = positive_spacings[len(positive_spacings) // 2]
    biggest_gap, gap_at = max(gaps)
    ratio = biggest_gap / median_spacing
    ev["largest_gap_over_median_unique_spacing"] = ratio

    # Fraction of OBSERVATIONS on each side of the unique-support gap. A mode needs
    # mass: one point far from a tight cluster produces an enormous gap ratio but is
    # skew, not bimodality, and the two call for opposite fixes.
    split_value = unique[gap_at]
    left_share = sum(v <= split_value for v in vals) / n
    ev["mass_left_of_gap"] = left_share

    if ratio > 10 and 0.15 <= left_share <= 0.85:
        scale = (
            "unbounded relative to the typical spacing (the two groups have no internal "
            "spread)"
            if ratio == math.inf
            else f"{ratio:,.0f}x the typical spacing"
        )
        return Check(
            name,
            "FAIL",
            f"Distribution appears bimodal: an interior gap of {biggest_gap:,.6g} is "
            f"{scale}, splitting the population "
            f"{left_share:.0%}/{1 - left_share:.0%}. A mean of {mean:,.6g} describes no "
            f"observation. Split the population and report each mode.",
            ev,
        )
    if abs(skew) > 2:
        return Check(
            name,
            "FLAG",
            f"Heavy skew ({skew:+.2f}); mean {mean:,.6g} vs median {median:,.6g}. "
            f"Report the median and the tail, not the mean alone.",
            ev,
        )
    return Check(name, "PASS", f"Skew {skew:+.2f}, mean and median agree to within the spread.", ev)


def tail_dominance(
    pnl: Sequence[float], quantile: float = 0.05, name: str = "tail_dominance"
) -> Check:
    """Separate an edge-dominated result from a tail-dominated one.

    A strategy can pass an edge-over-cost ratio and still be untradeable because a
    handful of observations carry the entire loss. That distinction is the whole
    decision, and an average hides it.
    """
    guard = _finite_series(name, list(pnl))
    if guard is not None:
        return guard
    if not 0 < quantile < 1:
        return Check(name, "FAIL", f"quantile must be in (0,1), got {quantile}.", {})
    vals = sorted(pnl)
    n = len(vals)
    if n < 20:
        return Check(name, "FLAG", f"n={n} is too small to measure a tail.", {"n": n})

    k = max(1, int(n * quantile))
    worst = vals[:k]
    total, worst_sum = sum(vals), sum(worst)
    ev = {
        "n": n,
        "total": total,
        "tail_n": k,
        "tail_sum": worst_sum,
        "tail_share_of_total": worst_sum / total if total else math.inf,
    }
    # Compare magnitudes, not signed values. A tail larger than the whole result
    # dominates it whether the headline number came out positive or negative; keying
    # this on `total > 0` would silently exempt every losing book from the check.
    if abs(worst_sum) > abs(total):
        return Check(
            name,
            "FLAG",
            f"Tail-dominated: the worst {k} of {n} observations sum to {worst_sum:,.6g} "
            f"against a total of {total:,.6g}. The tail is larger than the result, so the "
            f"headline number is a statement about {k} observations, not about the strategy. "
            f"A positive expectancy that depends on the tail not repeating is a bet on the "
            f"tail, not an edge.",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"Worst {k} of {n} ({worst_sum:,.6g}) do not exceed the total result "
        f"({total:,.6g}) in magnitude.",
        ev,
    )


# --------------------------------------------------------------------------------------
# LANE 3 -- PERTURB. Does the conclusion depend on choices nobody defended?
# --------------------------------------------------------------------------------------


def sensitivity(
    fn: Callable[..., float],
    base_kwargs: dict[str, Any],
    grid: dict[str, Iterable[Any]],
    decision: Callable[[float], Any] | None = None,
    name: str = "sensitivity",
) -> Check:
    """Run every defensible specification and check they agree on the DECISION.

    A specification curve in miniature (Simonsohn et al. 2020; Steegen et al. 2016).
    You cannot claim a finding is robust while having tested exactly one arbitrary
    combination of thresholds, windows, and cutoffs.

    `decision` maps a result to the thing you would actually do, so the check tests
    whether the choice of specification changes the ACTION, not whether it perturbs
    a digit.
    """
    decision = decision or (lambda v: v > 0)
    keys = list(grid)
    combos: list[dict[str, Any]] = [{}]
    for k in keys:
        combos = [dict(c, **{k: v}) for c in combos for v in grid[k]]

    results = []
    for combo in combos:
        kwargs = dict(base_kwargs, **combo)
        try:
            val = fn(**kwargs)
        except Exception as exc:  # a spec that crashes is a spec that was never tested
            return Check(
                name,
                "FAIL",
                f"Specification {combo} raised {type(exc).__name__}: {exc}. "
                f"Every defensible specification must at least run.",
                {"failing_spec": combo},
            )
        results.append((combo, val, decision(val)))

    decisions = Counter(str(d) for _, _, d in results)
    agree = decisions.most_common(1)[0][1] / len(results)
    values = [v for _, v, _ in results]
    ev = {
        "n_specifications": len(results),
        "decision_agreement": agree,
        "value_min": min(values),
        "value_max": max(values),
        "decision_counts": dict(decisions),
    }
    if agree < 1.0:
        dissent = [c for c, _, d in results if str(d) != decisions.most_common(1)[0][0]]
        return Check(
            name,
            "FAIL",
            f"The decision is not robust: {agree:.0%} of {len(results)} defensible "
            f"specifications agree. Values span {min(values):,.6g} to {max(values):,.6g}. "
            f"Dissenting specifications: {dissent[:3]}. Report the conditional result, "
            f"or defend the chosen specification on grounds fixed before you saw the data.",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"All {len(results)} specifications agree on the decision "
        f"(values {min(values):,.6g} to {max(values):,.6g}).",
        ev,
    )


def negative_control(
    fn: Callable[[Sequence[float]], float],
    values: Sequence[float],
    trials: int = 500,
    seed: int = 0,
    name: str = "negative_control",
) -> Check:
    """Prove the instrument can return a null before believing it returned a signal.

    Shuffle away the structure the claim depends on and re-run. If the statistic
    survives destruction of its own premise, the statistic is measuring the pipeline,
    not the world. An instrument that has never returned a null has not been shown
    capable of returning one.
    """
    import random

    guard = _finite_series(name, list(values))
    if guard is not None:
        return guard
    # Below 19 trials the smallest attainable p-value, 1/(trials+1), cannot reach
    # 0.05, so the check could only ever return FAIL: an instrument that can return
    # exactly one answer, which is the defect this module exists to detect.
    if trials < 19:
        return Check(
            name,
            "FAIL",
            f"trials={trials} is too few: the smallest attainable p-value is "
            f"{1 / (trials + 1):.3f}, which cannot clear 0.05. Use at least 19 "
            f"(200+ recommended).",
            {"trials": trials},
        )
    rng = random.Random(seed)
    observed = fn(values)
    obs_guard = _finite(name, observed=observed)
    if obs_guard is not None:
        return obs_guard
    pool = list(values)
    null = []
    for _ in range(trials):
        rng.shuffle(pool)
        null.append(fn(pool))

    at_least = sum(1 for v in null if abs(v) >= abs(observed))
    p = (at_least + 1) / (trials + 1)
    spread = max(null) - min(null)
    ev = {"observed": observed, "p_value": p, "null_min": min(null), "null_max": max(null)}

    if spread == 0:
        return Check(
            name,
            "FAIL",
            f"The null distribution is degenerate: {trials} shuffles all returned "
            f"{null[0]:,.6g}. This statistic is invariant to the structure it claims to "
            f"measure, so it cannot be evidence for the claim.",
            ev,
        )
    if p > 0.05:
        return Check(
            name,
            "FAIL",
            f"Observed {observed:,.6g} is not distinguishable from shuffled data "
            f"(p={p:.3f}, null spans {min(null):,.6g} to {max(null):,.6g}).",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"Observed {observed:,.6g} exceeds {1 - p:.1%} of {trials} shuffles (p={p:.3f}).",
        ev,
    )


def multiple_testing(
    best_sharpe: float,
    n_tried: int,
    n_obs: int,
    name: str = "multiple_testing",
) -> Check:
    """Discount the winner by how many candidates were searched.

    The expected maximum Sharpe from pure noise grows with the number of trials
    (Bailey & Lopez de Prado 2014, deflated Sharpe ratio). A result that does not
    clear the noise ceiling for the number of variants tested is not a finding, and
    the count of variants includes every one you tried and abandoned.

    **`best_sharpe` must be a STANDARDIZED statistic** (mean / standard deviation,
    per period), not a raw P&L, return, or cost difference. The noise ceiling is
    derived in standard-deviation units, so feeding it a dollar amount or a raw
    return compares two different things and reproduces the exact units error this
    module exists to catch. Adversarial review found this: a mean return of 0.003
    was compared against a ceiling of 0.36 and killed as "noise", which is
    meaningless, while a $609.60 P&L sailed past the same ceiling.

    Convert first::

        sharpe = mean(returns) / stdev(returns)      # per period, then annualize
        multiple_testing(sharpe, n_tried=200, n_obs=len(returns))

    The guard below rejects the obvious raw-magnitude inputs, but it cannot catch a
    raw return that happens to look Sharpe-sized. Standardize deliberately.
    """
    guard = _finite(name, best_sharpe=best_sharpe)
    if guard is not None:
        return guard
    if n_tried < 1 or n_obs < 2:
        return Check(name, "FLAG", "Need n_tried >= 1 and n_obs >= 2.", {})
    if abs(best_sharpe) > 20:
        return Check(
            name,
            "FAIL",
            f"best_sharpe={best_sharpe:,.6g} is far outside the plausible range for a "
            f"Sharpe ratio, so this is almost certainly a raw P&L, return, or cost "
            f"difference. The noise ceiling is in standard-deviation units; comparing a "
            f"raw magnitude against it is a units error. Pass "
            f"mean(returns)/stdev(returns) instead.",
            {"best_sharpe": best_sharpe},
        )

    euler = 0.5772156649015329
    if n_tried == 1:
        expected_max = 0.0
    else:
        # E[max of n_tried standard normals], Bailey & Lopez de Prado eq. 8
        def z(p: float) -> float:
            return math.sqrt(2) * _erfinv(2 * p - 1)

        expected_max = (1 - euler) * z(1 - 1 / n_tried) + euler * z(
            1 - 1 / (n_tried * math.e)
        )
    # per-observation standard error of a Sharpe-like statistic
    se = 1 / math.sqrt(n_obs - 1)
    threshold = expected_max * se
    ev = {
        "best_sharpe": best_sharpe,
        "n_tried": n_tried,
        "n_obs": n_obs,
        "noise_ceiling": threshold,
    }
    if best_sharpe <= threshold:
        return Check(
            name,
            "FAIL",
            f"Best Sharpe {best_sharpe:,.4g} is at or below the {threshold:,.4g} expected "
            f"from the best of {n_tried} variants on pure noise with n={n_obs}. "
            f"This is a selection artifact, not an edge.",
            ev,
        )
    return Check(
        name,
        "PASS",
        f"Best Sharpe {best_sharpe:,.4g} clears the {threshold:,.4g} noise ceiling "
        f"for {n_tried} variants at n={n_obs}.",
        ev,
    )


def _erfinv(y: float) -> float:
    """Inverse error function, Newton refinement on a rational seed. Stdlib only."""
    if y <= -1:
        return -math.inf
    if y >= 1:
        return math.inf
    a = 0.147
    ln = math.log(1 - y * y)
    t1 = 2 / (math.pi * a) + ln / 2
    x = math.copysign(math.sqrt(max(math.sqrt(t1 * t1 - ln / a) - t1, 0.0)), y)
    for _ in range(3):
        err = math.erf(x) - y
        x -= err / (2 / math.sqrt(math.pi) * math.exp(-x * x))
    return x


# --------------------------------------------------------------------------------------
# order-of-magnitude gate
# --------------------------------------------------------------------------------------


def plausible_magnitude(
    value: float,
    expected_low: float,
    expected_high: float,
    what: str,
    name: str = "magnitude",
) -> Check:
    """State the range you expected BEFORE looking, then check.

    Cheapest check in the module and the one that catches wrong-series errors, where
    a plausibly named field holds a quantity from the wrong venue or the wrong
    denomination. Writing the expected range down first is what makes it work; a
    range chosen after seeing the value always contains the value.
    """
    guard = _finite(
        name, value=value, expected_low=expected_low, expected_high=expected_high
    )
    if guard is not None:
        return guard
    if expected_low > expected_high:
        return Check(
            name,
            "FAIL",
            f"Expected range is inverted: low={expected_low:,.6g} > "
            f"high={expected_high:,.6g}. No value can satisfy it, so the check could "
            f"only ever fail.",
            {},
        )
    if expected_low <= value <= expected_high:
        return Check(
            name,
            "PASS",
            f"{what} = {value:,.6g}, inside the pre-stated [{expected_low:,.6g}, "
            f"{expected_high:,.6g}].",
            {"value": value},
        )
    if value > expected_high:
        off = value / expected_high if expected_high else math.inf
    else:
        off = value / expected_low if expected_low else math.inf
    return Check(
        name,
        "FAIL",
        f"{what} = {value:,.6g}, outside the pre-stated [{expected_low:,.6g}, "
        f"{expected_high:,.6g}] by ~{abs(off):,.4g}x. Before adjusting the range, check "
        f"that the field holds the series you think it holds.",
        {"value": value, "expected_low": expected_low, "expected_high": expected_high},
    )
