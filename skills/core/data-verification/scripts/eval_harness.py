"""Eval harness for the data-verification checks.

Every scenario is a REPLAY of a real incident from the audit, or a deliberate
adversarial case built to break a check. Two classes of scenario, and both are
mandatory:

  CATCH   the check must FAIL or FLAG. A miss here means the skill would not have
          prevented the incident it was written for.
  QUIET   the analysis is sound. The check must PASS. A false alarm here is worse
          than useless, because a checker that fires on everything gets ignored,
          and then it protects nothing.

Run:  python3 scripts/eval_harness.py
Exit: 0 all scenarios behaved, 1 otherwise.
"""

from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from checks import (  # noqa: E402
    Check,
    check_units,
    concentration,
    distribution_shape,
    leave_one_out,
    multiple_testing,
    negative_control,
    plausible_magnitude,
    reconcile,
    reconcile_population,
    sensitivity,
    tail_dominance,
)

from typing import Callable

SCENARIOS: list[dict] = []


def scenario(name: str, kind: str, origin: str, expect: str | None = None, says: str | None = None):
    """Register a scenario.

    `expect` pins the exact verdict and `says` pins a substring of the diagnosis. Both
    are optional but strongly preferred: without them a scenario only asserts that
    SOMETHING fired, and a check can then fire for the wrong reason and still look
    green. Mutation testing surfaced exactly that hole, so the sharp scenarios pin
    both.
    """

    def wrap(fn):
        SCENARIOS.append(
            {"name": name, "kind": kind, "origin": origin, "fn": fn, "expect": expect, "says": says}
        )
        return fn

    return wrap


# --------------------------------------------------------------------------------------
# CATCH -- replays of real incidents
# --------------------------------------------------------------------------------------


@scenario("units: users vs contract price", "CATCH", "real incident, edge declared 55x too small")
def _():
    # A divergence measured in users was compared against a spread measured in
    # contract price, and the strategy was killed on the comparison.
    return check_units((0.108, "percent_of_users"), (5.9, "percent_of_contract_price"))


@scenario("cost from the wrong population", "CATCH", "real incident, friction 13x too high")
def _():
    # A round-trip cost measured on a volume-spike population was imported into an
    # analysis of a different population where the true cost was 0.4525%.
    return reconcile(0.7343, 0.4525, tolerance=0.05, name="friction_cost", unit="%")


@scenario("wrong series: spot volume on a perps venue", "CATCH", "real incident, 16x too small")
def _():
    # Charting a venue's spot volume against its perpetuals price manufactured a
    # divergence that did not exist. A pre-stated magnitude range catches it.
    return plausible_magnitude(
        value=0.9e9,
        expected_low=10e9,
        expected_high=40e9,
        what="daily perp volume for a top-5 perps venue",
    )


@scenario("break-even computed backwards", "CATCH", "real incident, self-contradicting brief")
def _():
    # Claimed break-even $1,290,000 against a $1,325,000 basis with 6% costs.
    # Identity: basis / (1 - cost) = 1,409,574.
    return reconcile(1_290_000, 1_325_000 / 0.94, tolerance=0.005, name="breakeven", unit="$")


@scenario(
    "Monday morning: calendar blamed for one instrument",
    "CATCH",
    "the failure Nick named",
    expect="FAIL",
    says="belongs to that group, not to the population",
)
def _():
    # Losses look like a Monday effect. They are one weekly-recurring contract.
    rng = random.Random(11)
    vals, labels = [], []
    for _ in range(180):
        vals.append(rng.gauss(40, 60))
        labels.append("other")
    for _ in range(20):
        vals.append(rng.gauss(-900, 80))
        labels.append("weekly_contract_X")
    # Grouped by the SUSPECTED CAUSE, not by the day of week.
    return leave_one_out(vals, labels, name="monday_effect")


@scenario(
    "aggregate is one trade",
    "CATCH",
    "sign flip on a single observation",
    expect="FAIL",
    says="sign of the result depends on a single observation",
)
def _():
    return concentration([-40, -35, -50, -28, -44, -39, 1_200], name="book_pnl")


@scenario(
    "one venue carries the volume",
    "CATCH",
    "concentration without a sign flip",
    expect="FLAG",
    says="of the absolute mass",
)
def _():
    # Same-sign population, no flip, but one row is 87% of the mass. The finding
    # belongs to that venue, not to 'the market'.
    return concentration([8_700, 400, 300, 250, 200, 150], name="venue_volume")


@scenario(
    "effect halves when one desk is removed",
    "CATCH",
    "influence without a sign flip",
    expect="FLAG",
    says="Report the conditional finding",
)
def _():
    # Every group loses money, so nothing flips sign, but one desk drives most of it.
    rng = random.Random(31)
    vals = [rng.gauss(-20, 5) for _ in range(120)]
    labels = [f"desk_{i % 12}" for i in range(120)]
    vals += [rng.gauss(-400, 20) for _ in range(15)]
    labels += ["desk_hot"] * 15
    return leave_one_out(vals, labels, name="desk_attribution")


@scenario(
    "signal indistinguishable from its shuffles",
    "CATCH",
    "non-degenerate null, high p",
    expect="FAIL",
    says="not distinguishable from shuffled data",
)
def _():
    # The statistic varies under shuffling, so it is not an identity, but the observed
    # value sits comfortably inside the null. This is the ordinary way a backtest is
    # noise: not broken, just not evidence. Seed 0 gives p=0.74, well clear of the
    # 0.05 boundary, so the scenario tests the branch rather than a coin flip.
    rng = random.Random(0)
    vals = [rng.gauss(0, 1) for _ in range(80)]

    def trend(xs):
        n = len(xs)
        mx = (n - 1) / 2
        my = sum(xs) / n
        num = sum((i - mx) * (x - my) for i, x in enumerate(xs))
        den = sum((i - mx) ** 2 for i in range(n))
        return num / den

    return negative_control(trend, vals, trials=400, seed=5)


@scenario(
    "mean of a bimodal book",
    "CATCH",
    "central tendency describing nothing",
    expect="FAIL",
    says="appears bimodal",
)
def _():
    lo = [random.Random(3).gauss(-500, 25) for _ in range(30)]
    hi = [random.Random(4).gauss(500, 25) for _ in range(30)]
    return distribution_shape(lo + hi, name="fill_quality")


@scenario("tail-dominated strategy", "CATCH", "real run: passes cost ratio, still untradeable")
def _():
    # The real completed run: n=203, 194 wins, total +$609.60, and the worst 5%
    # (10 trades) lose $1,821.75. It passes an edge/cost ratio of 3.33 and is still
    # not tradeable, because the headline mean of +$3.00 per lot is a statement about
    # nine observations that happened not to repeat.
    pnl = [12.54] * 194 + [-202.5] * 9
    return tail_dominance(pnl, name="spread_pnl")


@scenario(
    "skewed fee distribution, not bimodal",
    "CATCH",
    "skew branch: one long tail, no second mode",
    expect="FLAG",
    says="Heavy skew",
)
def _():
    # Log-normal-ish costs: no gap, no second mode, but the mean sits well above the
    # median and quoting it alone overstates the typical trade.
    rng = random.Random(41)
    return distribution_shape([math.exp(rng.gauss(0, 1.1)) for _ in range(300)], name="fee_dist")


@scenario(
    "a defensible specification crashes",
    "CATCH",
    "a spec that cannot run was never tested",
    expect="FAIL",
    says="Every defensible specification must at least run",
)
def _():
    def edge(threshold: float, window: int) -> float:
        if window == 0:
            raise ValueError("window must be positive")
        return 10.0 / window + threshold

    return sensitivity(edge, {"threshold": 0.2, "window": 10}, {"window": [0, 10, 20]})


@scenario(
    "losing book, tail carries the loss",
    "CATCH",
    "tail check must not exempt negative totals",
    expect="FLAG",
    says="tail is larger than the result",
)
def _():
    # Total is NEGATIVE and the tail still dominates it. An earlier version keyed the
    # branch on `total > 0` and silently exempted every losing book, which is the half
    # of the population where the question matters most.
    rng = random.Random(51)
    pnl = [rng.gauss(2, 1) for _ in range(190)] + [-400.0] * 10
    return tail_dominance(pnl, name="losing_book")


@scenario(
    "one extreme outlier is not a second mode",
    "CATCH",
    "mass-balance guard: a lone far point is skew, not a second mode",
    expect="FLAG",
    says="Heavy skew",
)
def _():
    # A single point sits far from a tight cluster. The gap is enormous relative to
    # typical spacing, but 1 of 60 observations is not a mode. The correct diagnosis is
    # heavy skew, not bimodality: the fix is 'report the median and the tail', not
    # 'split the population'. Without the mass-balance guard the check hands back the
    # wrong instruction, so this scenario pins the DIAGNOSIS, not just that it fired.
    rng = random.Random(52)
    return distribution_shape([rng.gauss(0, 0.4) for _ in range(59)] + [95.0], name="lone_outlier")


@scenario(
    "NaN must never receive a PASS",
    "CATCH",
    "adversarial review: corrupt input was silently certified",
    expect="FAIL",
    says="Non-finite input",
)
def _():
    # Every comparison against NaN is False, so a check written as a chain of
    # comparisons falls through to its success branch and certifies corrupt data.
    # This was a real defect in this module: multiple_testing(nan, 200, 60) returned
    # PASS. A verification tool that green-lights NaN is worse than none, because it
    # converts silent corruption into stated confidence.
    return multiple_testing(float("nan"), n_tried=200, n_obs=60)


@scenario(
    "NaN inside a series must never receive a PASS",
    "CATCH",
    "adversarial review: aggregate over NaN is not a number",
    expect="FAIL",
    says="non-finite value",
)
def _():
    return concentration([1.0, float("nan"), 2.0], name="corrupt_series")


@scenario(
    "a control that cannot clear its own threshold",
    "CATCH",
    "instrument that can only return one answer",
    expect="FAIL",
    says="too few",
)
def _():
    # With trials=5 the smallest attainable p-value is 1/6 = 0.167, so the check can
    # never return PASS however real the signal. An instrument with one reachable
    # verdict is not a test, and this module exists to catch exactly that.
    return negative_control(lambda xs: sum(xs), [1.0, 2.0, 3.0, 4.0], trials=5)


@scenario(
    "an expected range no value can satisfy",
    "CATCH",
    "inverted bounds make the gate unfalsifiable",
    expect="FAIL",
    says="inverted",
)
def _():
    return plausible_magnitude(5.0, expected_low=100.0, expected_high=1.0, what="rate")


@scenario(
    "values and labels of different lengths",
    "CATCH",
    "silent zip truncation would make attribution arbitrary",
    expect="FAIL",
    says="disagree in length",
)
def _():
    # zip() truncates silently, so without this guard the check would attribute the
    # effect using a pairing that is simply wrong.
    return leave_one_out([1.0, 2.0, 3.0, 4.0], ["a", "b"], name="mispaired")


@scenario(
    "negative row counts are not meaningful",
    "CATCH",
    "argument validation: a nonsense population must not be computed on",
    expect="FAIL",
    says="Negative row counts",
)
def _():
    return reconcile_population(analyzed_n=-5, source_n=10)


@scenario(
    "tail quantile outside (0,1)",
    "CATCH",
    "argument validation: quantile=0 selects no tail and would always pass",
    expect="FAIL",
    says="quantile must be in",
)
def _():
    return tail_dominance([1.0] * 30, quantile=0.0, name="bad_quantile")


@scenario("silent filter drops 40% of days", "CATCH", "real incident: undeclared vol filter")
def _():
    return reconcile_population(analyzed_n=204, source_n=343, name="trading_days")


@scenario(
    "statistic invariant to its own premise",
    "CATCH",
    "control passes on zeroed input",
    expect="FAIL",
    says="null distribution is degenerate",
)
def _():
    # An 'edge' that is an algebraic identity: it returns the same value however the
    # data is arranged, so it cannot be evidence of anything.
    return negative_control(lambda xs: sum(xs) - sum(xs), [1.0, 5.0, -3.0, 9.0], trials=50)


@scenario("threshold shopping flips the decision", "CATCH", "unchosen free parameter")
def _():
    def edge(threshold: float, window: int) -> float:
        return (threshold - 0.22) * 100 + (window - 20) * 0.5

    return sensitivity(
        edge,
        {"threshold": 0.25, "window": 20},
        {"threshold": [0.15, 0.20, 0.25, 0.30], "window": [10, 20, 30]},
    )


@scenario("best of 200 variants is noise", "CATCH", "selection bias, deflated Sharpe")
def _():
    return multiple_testing(best_result=0.28, n_tried=200, n_obs=60)


@scenario("annualization error caught by ratio hint", "CATCH", "252x daily-vs-annual")
def _():
    return reconcile(0.0432 * 252, 0.0432, tolerance=0.01, name="return", unit="")


# --------------------------------------------------------------------------------------
# QUIET -- sound analyses that must not trip
# --------------------------------------------------------------------------------------


@scenario("clean reconciliation", "QUIET", "two paths agree")
def _():
    return reconcile(1_066_316_027, 1_066_316_100, tolerance=0.001, name="fund_nav", unit="$")


@scenario("same units compare fine", "QUIET", "no false alarm on matching units")
def _():
    return check_units((0.42, "usd_per_contract"), (0.05, "usd_per_contract"))


@scenario("genuinely diffuse population", "QUIET", "no single row dominates")
def _():
    rng = random.Random(21)
    return concentration([rng.gauss(100, 15) for _ in range(200)], name="diffuse")


@scenario("real effect survives leave-one-out", "QUIET", "population effect, not one entity")
def _():
    rng = random.Random(22)
    vals = [rng.gauss(-120, 30) for _ in range(150)]
    labels = [f"inst_{i % 15}" for i in range(150)]
    return leave_one_out(vals, labels, name="broad_effect")


@scenario("well-behaved distribution", "QUIET", "mean is a fair summary")
def _():
    rng = random.Random(23)
    return distribution_shape([rng.gauss(50, 10) for _ in range(200)], name="normal")


@scenario("edge-dominated, not tail-dominated", "QUIET", "the good version of the same shape")
def _():
    rng = random.Random(24)
    return tail_dominance([rng.gauss(12, 8) for _ in range(300)], name="broad_edge")


@scenario("full population analyzed", "QUIET", "nothing silently dropped")
def _():
    return reconcile_population(analyzed_n=343, source_n=343)


@scenario("robust across every specification", "QUIET", "decision does not depend on the knob")
def _():
    def edge(threshold: float, window: int) -> float:
        return 50.0 + threshold + window * 0.01

    return sensitivity(
        edge,
        {"threshold": 0.25, "window": 20},
        {"threshold": [0.15, 0.25, 0.35], "window": [10, 20, 30]},
    )


@scenario("real signal beats its shuffles", "QUIET", "negative control does not over-fire")
def _():
    rng = random.Random(25)
    vals = [rng.gauss(0, 1) + i * 0.4 for i in range(60)]

    def trend(xs):
        n = len(xs)
        mx = (n - 1) / 2
        my = sum(xs) / n
        num = sum((i - mx) * (x - my) for i, x in enumerate(xs))
        den = sum((i - mx) ** 2 for i in range(n))
        return num / den

    return negative_control(trend, vals, trials=400)


@scenario("single hypothesis clears the bar", "QUIET", "no multiple-testing penalty when n_tried=1")
def _():
    return multiple_testing(best_result=0.30, n_tried=1, n_obs=200)


@scenario("magnitude inside a pre-stated range", "QUIET", "sanity gate does not nag")
def _():
    return plausible_magnitude(22.4e9, 10e9, 40e9, what="daily perp volume")


# --------------------------------------------------------------------------------------


def test_guard_returns_are_not_truthiness_checks() -> Check:
    """Source-level check: a `Check | None` guard must be compared against None.

    This is a STRUCTURAL test, not a behavioural one, and it is here deliberately.
    A `Check` is falsy when it FAILs, so `if guard: return guard` never fires and
    silently disables the guard. That shipped in this module and certified NaN as
    PASS across nine checks at once.

    A behavioural scenario (NaN must FAIL) proves the current call sites are fixed.
    It does NOT stop the idiom reappearing at the next guard someone adds, and
    mutation testing confirmed the gap: reverting the idiom left every scenario
    green. Testing the mechanism is warranted precisely when the mechanism is the
    root cause and the symptom is one of its many possible expressions.
    """
    src = (Path(__file__).parent / "checks.py").read_text()
    offenders = [
        (i, line.strip())
        for i, line in enumerate(src.splitlines(), 1)
        if re.match(r"\s*if (guard|obs_guard)\s*:\s*$", line)
    ]
    if offenders:
        listed = "; ".join(f"line {i}: {t}" for i, t in offenders[:5])
        return Check(
            "guard_idiom",
            "FAIL",
            f"{len(offenders)} guard(s) use truthiness instead of `is not None`, so a "
            f"FAIL guard is falsy and never returns: {listed}. Use `if guard is not None:`.",
            {"offenders": offenders},
        )
    return Check(
        "guard_idiom",
        "PASS",
        "All Check|None guards compare against None rather than truthiness.",
        {},
    )


SCENARIOS.append(
    {
        "name": "guards compare against None, not truthiness",
        "kind": "QUIET",
        "origin": "structural: the root cause of the NaN-passes defect",
        "fn": test_guard_returns_are_not_truthiness_checks,
        "expect": "PASS",
        "says": None,
    }
)


def main() -> int:
    passed = failed = 0
    misses: list[str] = []
    print(f"{'RESULT':<7} {'KIND':<6} SCENARIO")
    print("-" * 88)
    for sc in SCENARIOS:
        check = sc["fn"]()
        caught = check.verdict in ("FAIL", "FLAG")
        ok = caught if sc["kind"] == "CATCH" else not caught
        why = ""
        if ok and sc["expect"] and check.verdict != sc["expect"]:
            ok, why = False, f"expected verdict {sc['expect']}, got {check.verdict}"
        if ok and sc["says"] and sc["says"] not in check.detail:
            ok, why = False, f"diagnosis missing {sc['says']!r}"
        if ok:
            passed += 1
            print(f"{'ok':<7} {sc['kind']:<6} {sc['name']}")
        else:
            failed += 1
            misses.append(f"{sc['kind']} {sc['name']}: {why or check.verdict} -- {check.detail}")
            print(f"{'MISS':<7} {sc['kind']:<6} {sc['name']}  ->  {why or check.verdict}")

    print("-" * 88)
    catch_n = sum(1 for s in SCENARIOS if s["kind"] == "CATCH")
    print(
        f"{passed}/{len(SCENARIOS)} scenarios behaved "
        f"({catch_n} CATCH, {len(SCENARIOS) - catch_n} QUIET)"
    )
    if misses:
        print("\nProblems:")
        for m in misses:
            print(f"  - {m}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
