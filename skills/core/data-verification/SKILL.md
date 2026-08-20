---
name: data-verification
version: 1.0.0
description: >
  Use when an analysis is about to produce a number, a verdict, or a
  recommendation someone will act on: backtests, P&L, cost and fee models,
  yield and returns, screens, cohort comparisons, "is this strategy
  profitable", "why did we lose money on X". Runs a five-gate protocol that
  attacks the INPUTS and the QUESTION, not just the arithmetic, and ships an
  executable check library plus a replay eval harness so the gates are proven
  rather than promised.
license: MIT
metadata:
  hermes:
    tags:
      [
        data-quality,
        verification,
        analysis,
        statistics,
        backtesting,
        epistemics,
        decision,
      ]
    related_skills: [deep-dive, multi-review, moa-solve]
---

# Data Verification

Stop shipping numbers that are wrong in ways re-reading them cannot catch.

## Why this skill exists, in one finding

This skill was built from an audit of roughly 130,000 agent messages across four
agents and three separate conversation corpora. Every incident below is real, and
the audits are reproducible from the evidence files.

Across 24 verified incidents in one corpus, the taxonomy came out:

| root cause                                    | share |
| --------------------------------------------- | ----: |
| population / coverage bias                    |   33% |
| wrong metric, denominator, or units           |   25% |
| schema / provenance / parsing                 |   21% |
| accounting, duplicate credit                  |    8% |
| broken measurement instrument                 |    8% |
| causal attribution without execution evidence |    4% |

**Arithmetic errors: zero.** A second corpus (17 incidents) and a third
(8 incidents) landed in the same place. The conclusion is not subtle:

> The calculations were right. The inputs and the question were wrong.

Concretely, what that looks like:

- A divergence measured in **users** was compared against a spread measured in
  **contract price**, and the strategy was killed for having an edge "55x too
  small". Both numbers were correct. The comparison was meaningless.
- A round-trip cost measured on one population was imported into an analysis of a
  different population where the true cost was **13x lower**. That single input
  manufactured a wall that killed the project.
- A venue's **spot** volume was charted against its **perpetuals** price,
  producing a 16x-too-small series and a divergence that never existed. It was
  reported to a third party before anyone checked the magnitude.
- Lifetime P&L was reported as **+$1,086.86** by summing sell proceeds and
  settlement revenue without allocating basis. Correct figure: **-$120.84**. The
  sign was wrong, so the verdict was wrong.
- A strategy's behaviour was inferred from **open positions only**. Losers sold to
  zero had vanished from the table. The conclusion was the exact opposite of the
  truth.

Re-running any of those calculations reproduces the error perfectly.

## The rule that shapes everything below

> **Verification must come from outside the analysis.**

Intrinsic self-review does not reliably improve reasoning and often degrades it
(Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR
2024, arXiv:2310.01798). Correction works when it is grounded in an external
signal the model cannot fake: a test runner, a second data path, a shuffled
control (Gou et al., CRITIC, ICLR 2024).

So "let me double-check my work" is not a verification step. Re-reading your own
analysis, however carefully, is the one method the literature says does not work.
Every gate below either runs code or consults a source outside the analysis.

## About "check it three different ways"

The instinct is right and the naive version fails. Knight & Leveson (1986, IEEE
TSE SE-12(1):96-109) had 27 programmers independently implement one specification
and found their failures were **strongly correlated**, far above what
independence predicts, because they shared the same ambiguous spec. A 2026 replication
with coding agents found the same thing: 429 coincident failures where independence
predicted 115.

Three checks that share an assumption are one check. Three copies of you, or three
LLM calls on the same framing, agree cheaply and mean nothing. So:

**Vary the mechanism, not the effort.** The three ways must fail for unrelated
reasons:

1. **A different data path** — different source, different endpoint, different
   grain. Not a refactor of the same query.
2. **A different direction** — compute it backwards, or from an identity that must
   hold (`basis / (1 - cost) = breakeven`).
3. **A destroyed premise** — shuffle away the structure the claim needs and confirm
   the result disappears.

If two agree and one dissents, **the dissent is the finding.** Do not average.

## The protocol

Five gates. Gates 1 and 2 are mandatory for every analysis and cost about five
minutes. Gates 3 to 5 fire on the trigger in their heading.

Run `scripts/checks.py` for the executable versions. Verdicts are `PASS`, `FLAG`,
`FAIL`, and a `PASS` means only that one named failure mode was ruled out. It is
never evidence the number is right.

---

### Gate 1 — PROVENANCE (mandatory, ~2 min)

The 79% of failures that arithmetic cannot catch. Before computing anything,
answer these in writing:

1. **What is the unit?** Write it next to every quantity. Then run
   `check_units()` before any comparison. Two numbers with different units cannot
   be compared, subtracted, or ranked, however tempting the arithmetic looks.
2. **What is the population?** Say which rows the number describes. Then run
   `reconcile_population()`: every row that left the source between query and
   conclusion must be named. An unexplained drop is a silent filter, and a silent
   filter is a hypothesis you did not declare. In one real case a `credit <= 0.05`
   skip removed 40.5% of days and correlated -0.471 with realized volatility: an
   undeclared low-volatility filter nobody chose.
3. **Is this cost/rate measured on THIS population?** An imported constant is
   guilty until re-derived in-population. This one line would have prevented the
   most expensive incident in the audit.
4. **Is it stock or flow?** A balance and a rate per day are different kinds of
   thing. Turnover is not capital. Transfer counts are not dollars moved.
5. **Does the field hold the series I think it holds?** State an expected
   magnitude range **before** looking, then `plausible_magnitude()`. A range
   chosen after seeing the value always contains the value.

> **Empty is not zero.** An HTTP 200 with an empty array means "no rows returned",
> which is indistinguishable from "no data exists", "your window is wrong", and
> "this endpoint has a retention cliff". A zero counts only after a
> **known-present control** passes in the identical call shape. In the audit, an
> empty response from a live endpoint was read as "the data was purged"; the data
> was on a historical endpoint that had never been called.

---

### Gate 2 — DECOMPOSITION (mandatory, ~2 min)

**This is the Monday-morning gate, and it is the one Nick named.**

You observe that losses cluster on Monday morning. The tempting conclusion is
"stop trading Monday morning". The true cause was one contract that happened to
trade every Monday. Monday was a _label on_ the cause, not the cause. Act on the
calendar and you keep the loss and lose the good Monday trades too.

Never report an aggregate without decomposing it first:

1. `concentration()` — does one row carry the result? If removing the largest
   observation **flips the sign**, you do not have a population effect. You have
   one observation, and you must report it as one observation.
2. `leave_one_out()` — group by the **suspected cause** (the instrument, the
   counterparty, the venue), never by the label you are about to blame. If
   removing one minority group flips or halves the statistic, the effect belongs
   to that group.
3. `distribution_shape()` — is the mean a description of anything? A bimodal
   population has a mean that resembles no observation in it. Report the modes.
4. `tail_dominance()` — is this edge-dominated or tail-dominated? A real strategy
   in the audit returned a mean of +$3.00 per lot, passed an edge-over-cost ratio
   of 3.33, and was still untradeable: the worst 5% of trades lost $1,821.75
   against a total profit of $609.60. The mean was a statement about nine
   observations that happened not to repeat.

> **Before blaming a grouping variable, name the mechanism.** "Losses cluster on
> Mondays" is an observation. "Mondays cause losses" is a causal claim needing a
> mechanism that survives removing the entities inside the group. If you cannot
> name the mechanism, you have found _where_ the cause sits, not _what_ it is.

---

### Gate 3 — TRIANGULATION (fires when the number drives a decision)

Reconcile against something built a different way. `reconcile()` reports the ratio
and names the likely culprit when it is a round factor: 10x, 100x, 252x
(daily-vs-annual trading days), 365x, 12x, 10,000x (basis points vs percent).

Cheapest sufficient triangulation, in order:

- **An identity that must hold.** Break-even is `basis / (1 - cost)`. Parts must
  sum to the whole. A share must be in [0, 1]. Nearly free, catches sign and
  direction errors.
- **A second data path.** A different endpoint or grain. Do not compare a vendor's
  number to the same vendor's number: in one incident two vendors' supply figures
  differed by definition ($90.3B vs $74.1B), so any ratio had to take numerator
  and denominator from the **same** vendor.
- **An order-of-magnitude estimate.** Compute what the answer should roughly be
  from first principles. This is what catches wrong-series errors.

---

### Gate 4 — PERTURBATION (fires when a threshold, window, or cutoff was chosen)

Every arbitrary choice is a fork in Gelman & Loken's garden of forking paths. One
path is not a finding.

- `sensitivity()` runs the full grid of defensible specifications and checks they
  agree on the **decision**, not on a digit. A miniature specification curve
  (Simonsohn, Simmons & Nelson, _Nature Human Behaviour_ 4:1208-1214, 2020;
  Steegen et al. 2016). If they disagree, report the conditional result or defend
  the chosen spec on grounds fixed **before** you saw the data.
- `negative_control()` destroys the structure the claim depends on and re-runs. If
  the statistic survives, it is measuring your pipeline, not the world. A real
  control in the audit passed on shuffled inputs **and on all-zero inputs**,
  because it was an algebraic identity. It tested arithmetic, not the strategy.
- `multiple_testing()` discounts the winner by how many variants were searched.
  The expected best-of-N from pure noise grows with N (Bailey & López de Prado,
  _Deflated Sharpe Ratio_, JPM 40(5):94-107, 2014). **Count every variant you
  tried and abandoned**, not just the ones you kept.

---

### Gate 5 — ADVERSARIAL READ (fires before an irreversible or external action)

Real money, an outside party, a kill decision. Hand the analysis to something that
did not produce it: `multi-review`, a different model family, or a colleague. Ask
for the specific thing, because "review this" gets you prose:

> "Find the input that would flip this conclusion. Check units, population,
> denominator, and time window first. Do not check my arithmetic."

**Direction-of-error audit.** For every assumption, ask which way its error runs.
In one incident a loss floor was called "generous to the strategy" when the
breakeven identity `L/(W+L)` means a larger assumed loss _raises_ the bar and
makes a kill _easier_. The assumption ran against the strategy, and the verdict
reversed once it was corrected. If all your assumptions happen to run the same
direction, you are not being conservative, you are steering.

## Reporting a verified number

Four things, always, in this order:

1. **The number**, with its unit and its population. "-$120.84 realized on 47
   settled positions", not "we lost money".
2. **How it was verified.** Which gates ran, what the second path was, what came
   back. Name the mechanism, not the effort.
3. **What would change it.** The specific input whose revision flips the
   conclusion.
4. **What is still unverified.** Every gate you skipped and why.

State the confidence the evidence supports, not the confidence that sounds
decisive. "Two independent paths agree within 0.1%" is a claim. "I checked
carefully" is not.

**And the discipline that costs the most trust when violated:** run the gates
**before** the first sentence about what the data says. Serial public correction,
where each message walks back the last, is a worse failure than a single wrong
answer, because it makes the reader into your QA layer. If a check that could
reverse your finding is still running, the finding is not ready.

## Using the scripts

```bash
# The check library. Import what you need; zero dependencies beyond stdlib.
python3 -c "import sys; sys.path.insert(0,'scripts'); from checks import *; \
            print(reconcile(0.7343, 0.4525, tolerance=0.05, name='cost'))"

# The eval harness: 31 scenarios replaying real incidents. Must exit 0.
python3 scripts/eval_harness.py
```

```python
from checks import Report, check_units, concentration, reconcile_population

report = Report()
report.append(check_units((edge, "usd_per_contract"), (spread, "usd_per_contract")))
report.append(reconcile_population(analyzed_n=len(df), source_n=source_rows))
report.append(concentration(df["pnl"], df["instrument"]))

if not report.may_ship:
    print(report.summary())   # do not ship the conclusion
```

`Report.may_ship` is `False` if anything returned `FAIL` **or** `FLAG`. A `FLAG`
is not a warning to note and move past; it means the claim is not established by
this evidence.

## Verifying the verifier

The gates are only worth what their evidence is worth, so:

- **39 scenarios**, 27 `CATCH` (must fire) and 12 `QUIET` (must not fire). Most
  CATCH scenarios are replays of specific incidents from the audit. The QUIET half
  matters just as much: a checker that fires on everything gets ignored, and then
  it protects nothing.
- **Scenarios pin the diagnosis, not just the alarm.** Many assert the exact
  verdict and a substring of the message, because a check that fires for the wrong
  reason hands back the wrong fix.
- **27/27 mutation kill rate.** Every branch of every check was deliberately
  broken and the harness caught all 27. This is the only evidence that the
  scenarios test the checks rather than merely running them.

Mutation testing earned its keep during construction. It found:

- a `tail_dominance` branch keyed on `total > 0` that silently exempted every
  losing book, which is the half of the population where the question matters most;
- a `leave_one_out` that named the **majority** group as the culprit, since
  removing most of the data always moves the statistic most. It failed on the very
  Monday-morning replay it exists to catch;
- a bimodality test scaled against the IQR, which a clean bimodal split inflates,
  so the check was weakest exactly when the defect was worst;
- a redundant `interior` guard that no input could ever make binding.

Adversarial review then found the worst one. **Every non-finite guard was
disabled**, so `multiple_testing(nan, 200, 60)` returned `PASS`. The cause was
one idiom:

```python
guard = _finite(name, x=x)
if guard:            # a FAIL Check is FALSY, so this never fires
    return guard
```

`Check.__bool__` returns True only for `PASS`, which makes the natural early-return
idiom silently inverted. A verification tool that green-lights NaN is worse than no
tool, because it converts silent corruption into stated confidence.

Fixing the symptom was not enough. Mutation testing showed that reverting the idiom
left **every scenario green**, so the harness now carries
`test_guard_returns_are_not_truthiness_checks`, which scans the source. Testing a
mechanism rather than a behaviour is usually a proxy and usually wrong; it is
warranted here because the mechanism **is** the root cause and NaN-passing was only
one of its expressions.

Six real defects in checks that had already passed the whole suite. If you extend
`checks.py`, add the scenario **and** re-run the mutation sweep, or you have added
untested code to a skill whose entire purpose is not doing that.

## What this skill cannot do

Stated plainly, because a verification skill that oversells itself is the exact
failure it exists to prevent.

**The coverage is deliberately lopsided, and not in the direction you would
expect.** Provenance and population errors are ~79% of real incidents, but only 4
of the 11 checks target them (`check_units`, `reconcile`,
`reconcile_population`, `plausible_magnitude`). The other 7 are decomposition and
perturbation checks covering a much smaller share of incidents.

That is not an oversight, it is the shape of the problem. **A unit error is not
detectable from the data.** Nothing in a column of floats reveals that they are
users rather than contract prices; the number 0.108 is untyped in every dataset
that has ever existed. Same for population: a query returning 204 rows cannot know
that the source held 343. These errors are only catchable if the analyst **writes
down** the unit, the population, and the expected magnitude, at which point the
check becomes trivial.

So Gate 1 is mostly prompts, and it is mostly prompts on purpose. The 79% class is
prevented by declaration, not by computation. If you skip the writing-down step,
the four provenance checks have nothing to compare against and this skill degrades
to a statistics library, which would have caught almost none of the incidents that
motivated it.

**Non-finite input is rejected, not analyzed.** Every check returns `FAIL` on NaN
or infinity rather than reasoning about it. NaN in an analysis means an upstream
computation already failed, and verifying around it would launder a provenance
failure into a statistical result.

Three more honest limits:

- **Thresholds are conventions, not laws.** 50% mass for concentration, 10x
  spacing for bimodality, `p > 0.05` for the null, `n_tried` counting for
  deflation. They are defensible defaults, not discoveries. Every one is a
  parameter, and by the skill's own Gate 4 an unchosen parameter deserves
  suspicion. Override them with a reason.
- **A `PASS` on all gates is not a correct answer.** It means the named failure
  modes were ruled out. The universe of ways to be wrong is larger than eleven.
- **`negative_control` has a real false-positive rate.** At the 0.05 boundary,
  roughly 1 in 20 genuinely null series will read as signal. That is the
  definition of the threshold, not a defect, and it is why a single passing
  control is not proof of an edge. It also needs at least 19 trials, since below
  that the smallest attainable p-value cannot reach 0.05 and the check could only
  ever return one verdict; it refuses rather than pretending.
- **`negative_control` shuffles.** A plain permutation destroys serial structure,
  which is right for a cross-sectional claim and wrong for one about autocorrelated
  time series, where a block or circular-shift null is the correct comparator. Pass
  a statistic that is meaningful under the null you actually want.

## Pitfalls

1. **Re-running the calculation.** Reproducing your own arithmetic proves the
   arithmetic. Every incident in the audit reproduces perfectly.
2. **Three correlated checks.** Knight-Leveson. Vary the mechanism or you have one
   check wearing three hats.
3. **Averaging a disagreement.** When paths disagree, find the driver. The mean of
   a right answer and a wrong answer is a wrong answer.
4. **Treating a `FLAG` as a note.** It means the claim is not established.
5. **A range chosen after seeing the number.** It always contains the number.
   Write it first or skip the check honestly.
6. **Counting only the variants you kept.** Multiple-testing correction needs
   every specification you tried, including the abandoned ones.
7. **A control that has never returned a null.** If it cannot fail, its pass is
   not information. Feed it shuffled and zeroed input and confirm it fails.
8. **Reporting before the gates finish.** The most trust-destroying pattern in the
   entire audit was serial correction across consecutive messages.
9. **Fitting an explanation to an artifact.** In one incident a wrong series
   produced a divergence, and a plausible reason for the divergence was invented
   before anyone checked whether the divergence was real. Validate the observation
   before explaining it.
10. **Assuming the skill's presence is the safeguard.** It is not. The audit found
    that 345,000 words of correct guidance already sat on disk while these
    incidents happened. Guidance nobody runs is decoration; the gates work only
    when executed.

## Sources

- Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024. https://arxiv.org/abs/2310.01798
- Gou et al., "CRITIC: LLMs Can Self-Correct with Tool-Interactive Critiquing",
  ICLR 2024.
- Knight & Leveson, "An Experimental Evaluation of the Assumption of Independence
  in Multiversion Programming", IEEE TSE SE-12(1):96-109, 1986.
  https://dx.doi.org/10.1109/TSE.1986.6312924
- Simonsohn, Simmons & Nelson, "Specification Curve Analysis", _Nature Human
  Behaviour_ 4:1208-1214, 2020. https://www.nature.com/articles/s41562-020-0912-z
- Steegen, Tuerlinckx, Gelman & Vanpaemel, "Increasing Transparency Through a
  Multiverse Analysis", 2016.
- Bailey & López de Prado, "The Deflated Sharpe Ratio", _Journal of Portfolio
  Management_ 40(5):94-107, 2014. https://ssrn.com/abstract=2460551
- dbt data tests (`unique`, `not_null`, `relationships`, `accepted_values`,
  source freshness). https://docs.getdbt.com/docs/build/data-tests
- Great Expectations (Apache-2.0, Python API), Soda Core (Apache-2.0, YAML/SodaCL),
  Pandera (dataframe schemas). Adopt one of these when the data is a persistent
  pipeline; the gates here target one-off analyses, where those frameworks' setup
  cost exceeds the analysis.
