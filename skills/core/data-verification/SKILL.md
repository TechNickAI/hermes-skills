---
name: data-verification
version: 2.0.0
description: >
  Use before reporting any number, verdict, or recommendation drawn from data:
  "is this profitable", "did X cause Y", "which cohort performs best", metrics
  reviews, backtests, cost models, funnel analysis, A/B results. Five questions
  that catch the errors re-checking arithmetic never catches, because the
  calculation is usually right and the input or the question is wrong.
license: MIT
metadata:
  hermes:
    tags:
      [data-quality, analysis, verification, statistics, epistemics, decision]
    related_skills: [deep-dive, multi-review, moa-solve]
---

# Data Verification

Your arithmetic is probably fine. That is not where analyses go wrong.

## The finding this is built on

An audit of ~130,000 agent messages across four agents looked for every case where
an agent reported a data conclusion that was later retracted. 49 verified
incidents. The taxonomy:

| root cause                                 | share |
| ------------------------------------------ | ----: |
| population / coverage bias                 |   33% |
| wrong metric, denominator, or units        |   25% |
| schema / provenance / parsing              |   21% |
| accounting, double-counting                |    8% |
| broken measurement instrument              |    8% |
| causal attribution without direct evidence |    4% |

**Arithmetic errors: zero.**

Every one of those incidents reproduces perfectly when you re-run the
calculation. That is why "let me double-check my work" never caught any of them,
and it is why this skill does not ask you to re-check your work.

What it asks instead: **is this number about what I think it is about?**

## The five questions

Answer 1 and 2 for every analysis. They take about three minutes and catch ~79%
of real failures. Reach for 3, 4, and 5 when their trigger fires.

---

### 1. Provenance: is this number about what I think it's about?

Write these down before computing. Writing them down IS the check, because a unit
or a population is not recoverable from the numbers afterwards.

- **What is the unit?** Write it next to every quantity, with its denominator.
  `usd` and `usd per share` are different units. `cents` and `dollars` are
  different units. Never compare two quantities until they carry the same one.
- **What is the population?** How many rows the source holds, how many reached
  your calculation, and the name of every filter between them. **An unexplained
  gap is a hypothesis you never declared.** In one real case a `credit <= 0.05`
  skip removed 40.5% of days and correlated -0.471 with volatility: an undeclared
  low-volatility filter nobody chose.
- **Is this rate, cost, or constant measured on THIS population?** An imported
  number is guilty until re-derived here. This one line would have prevented the
  single most expensive error in the audit.
- **Is it a stock or a flow?** A balance is not a rate. Turnover is not capital.
  Transfer counts are not dollars moved.
- **Does the field hold the series I think it holds?** State the magnitude you
  expect **before** looking. A range chosen after seeing the value always contains
  the value.

> **Empty is not zero.** An HTTP 200 with an empty array means "no rows returned",
> which is indistinguishable from "no data exists", "your window is wrong", and
> "this endpoint has a retention cliff". Before reporting a zero, run the same
> query against a case you know is populated. In the audit, an empty response was
> reported as "the data was purged"; it was on an endpoint nobody had called.

**What went wrong when people skipped this:** a divergence measured in _users_
compared against a spread measured in _contract price_, killing a strategy for an
edge "55x too small". A cost measured on one population imported into another
where the true cost was 13x lower, manufacturing a wall that ended a project. A
venue's _spot_ volume charted against its _perpetuals_ price, inventing a
divergence that never existed.

---

### 2. Decomposition: is the aggregate telling the truth about its parts?

**The Monday-morning problem.** Losses cluster on Monday morning. The tempting
conclusion is "stop trading Monday morning". The actual cause was one contract
that happened to trade every Monday. Monday was a _label on_ the cause, not the
cause. Act on the calendar and you keep the loss and lose the good Monday trades.

Before reporting any aggregate:

- **Does one row carry the result?** If removing the largest observation flips the
  sign, you do not have a population effect. You have one observation, and you
  must report it as one observation.
- **Group by the suspected cause, not by the label you're about to blame.** By
  instrument, counterparty, venue, customer. If removing one minority group flips
  or halves the number, the effect belongs to that group.
- **Is the mean a description of anything?** A bimodal population has a mean that
  resembles no member of it. Report the modes.
- **Is this edge-dominated or tail-dominated?** A real strategy in the audit
  averaged +$3.00 per trade, passed an edge-over-cost ratio of 3.33, and was
  untradeable: the worst 5% lost $1,821.75 against a total profit of $609.60. The
  average was a statement about nine trades that happened not to repeat.

> **Before blaming a grouping variable, name the mechanism.** "Losses cluster on
> Mondays" is an observation. "Mondays cause losses" is a causal claim that needs a
> mechanism surviving removal of the entities inside the group. Without one you
> have found _where_ the cause sits, not _what_ it is.

`scripts/decompose.py` does this arithmetic when the dataset is too large to
eyeball. See "When to reach for the script".

---

### 3. Triangulation — when the number drives a decision

Recompute it a different way. Not a refactor of the same query: **a different
mechanism**, or you have one check wearing two hats.

Cheapest first:

- **An identity that must hold.** Break-even is `basis / (1 - cost%)`. Parts sum
  to the whole. A share lands in [0, 1]. Free, and it catches sign and direction
  errors. One audit incident shipped a break-even _below_ the cost basis, in a
  document that contradicted itself two paragraphs apart.
- **A second data path.** A different endpoint, table, or grain. Do not compare a
  vendor's number to the same vendor's number. Two vendors' supply figures once
  differed by definition ($90.3B vs $74.1B), so any ratio had to take numerator
  and denominator from the same source.
- **An order-of-magnitude estimate from first principles.** This is what catches
  wrong-series errors.

**If the paths disagree, the disagreement is the finding.** Do not average. The
mean of a right answer and a wrong answer is a wrong answer.

#### On "check it three different ways"

Right instinct, and the naive version fails. Knight & Leveson (1986) had 27
programmers independently implement one specification; their failures were
**strongly correlated**, far above what independence predicts, because they shared
the same ambiguous spec. A 2026 replication using coding agents found 429
coincident failures where independence predicted 115.

Three checks sharing an assumption are one check. Three LLM calls on the same
framing are one check. **Vary the mechanism, not the effort.**

---

### 4. Perturbation — when you chose a threshold, window, or cutoff

Every arbitrary choice is a fork in Gelman & Loken's "garden of forking paths",
and one path is not a finding.

- **Run the defensible alternatives and check they agree on the DECISION**, not on
  a digit. If a cutoff of 0.20 says go and 0.25 says stop, you have a coin flip
  wearing a number. Report the conditional result, or defend the choice on grounds
  fixed before you saw the data. (Specification-curve analysis: Simonsohn, Simmons
  & Nelson 2020; multiverse analysis: Steegen et al. 2016.)
- **Destroy the premise and confirm the result dies.** Shuffle the structure your
  claim depends on and re-run. If the finding survives, it is measuring your
  pipeline, not the world. One real control in the audit passed on shuffled input
  **and on all-zero input**, because it was an algebraic identity: it tested
  arithmetic, not the strategy.
- **Discount by how many variants you searched.** The best of N tries on pure noise
  looks better as N grows (Bailey & López de Prado 2014). Count every variant you
  tried and abandoned, not just the one you kept.

---

### 5. Adversarial read — before anything irreversible

Real money, an outside audience, or a kill decision. Hand it to someone who did
not produce it, and ask for the specific thing, because "review this" gets prose:

> "Find the input that would flip this conclusion. Check units, population,
> denominator, and time window first. Do not check my arithmetic."

**Then audit the direction of your errors.** For every assumption, ask which way
it runs. In one incident a loss floor was called "generous to the strategy" when
the breakeven identity `L/(W+L)` means a larger assumed loss _raises_ the bar and
makes a kill _easier_. The assumption ran against the strategy and the verdict
reversed once corrected. **If every assumption happens to run the same direction,
you are not being conservative, you are steering.**

Note what the research says here: prompting a model to review its own reasoning
without external grounding does not reliably improve it and often degrades it
(Huang et al., ICLR 2024). Correction works when it is anchored to something the
model cannot fake: a second data path, a test runner, a shuffled control, another
reader. That is why every question above reaches outside the analysis.

---

## Reporting a verified number

1. **The number**, with unit and population. "-$120.84 realized across 47 settled
   positions", not "we lost money".
2. **How it was verified.** Which questions you answered and what the second path
   returned. Name the mechanism, not the effort.
3. **What would change it.** The specific input whose revision flips the call.
4. **What is still unverified.** Every question you skipped, and why.

State the confidence the evidence supports, not the confidence that sounds
decisive. "Two independent paths agree within 0.1%" is a claim. "I checked
carefully" is not.

**And the discipline that costs the most trust when broken:** finish the checks
_before_ the first sentence about what the data says. Serial public correction,
where each message walks back the last, is worse than one wrong answer, because it
turns the reader into your QA process.

## When to reach for the script

`scripts/decompose.py` exists for one reason: **there is arithmetic here you
cannot do by reading.** Deciding whether removing the largest of 200 rows flips a
sign, recomputing a statistic 15 times to find the group driving it, or generating
a p-value from 500 shuffles are all things that must actually be computed.

Everything else in this skill is deliberately prose, because it is either
judgment or a comparison you can already make. Whether `0.9e9` falls inside
`[10e9, 40e9]`, whether "users" and "contract price" are the same unit, whether
139 missing rows were declared: reading beats running code, and a function
wrapping a one-line comparison is ceremony that makes the check feel done.

```bash
python3 scripts/decompose.py --demo       # worked examples, no data needed
python3 scripts/decompose.py --selftest   # 25 assertions, verifies it still works
python3 scripts/decompose.py --help
```

Reads CSV or JSON, or import the functions. Standard library only, no install.

```bash
# Does one row carry the result? Which group drives it?
python3 scripts/decompose.py concentration trades.csv --value pnl --label instrument

# Is the effect real, or does it survive destroying its own premise?
python3 scripts/decompose.py shuffle returns.csv --value daily_return

# Best of 40 variants, or noise?
python3 scripts/decompose.py selection --sharpe 0.9 --tried 40 --periods 250
```

It prints an interpretation with each number, and says plainly when a result is
too small or too degenerate to interpret. One file, standard library only, no
install.

**It cannot tell you which grouping is the cause.** Run the demo and you will see
grouping by `instrument` and grouping by `day` both flip the sign on the same
data, because the bad instrument only traded on Mondays. The arithmetic is
identical; only you know which one is a mechanism. That is the division of labour
in this skill: the script computes, you decide.

## Adapting this to your domain

The questions are the portable part. The examples are trading and finance because
that is the corpus that produced them; the failures are not.

| Question           | Trading                       | SaaS metrics                         | Experiments                     |
| ------------------ | ----------------------------- | ------------------------------------ | ------------------------------- |
| Population         | survivorship in closed trades | churned accounts dropped from cohort | dropouts excluded from analysis |
| Units              | dollars vs basis points       | MRR vs ARR vs bookings               | rate vs count                   |
| Wrong denominator  | turnover as capital           | active users over signups            | per-user vs per-session         |
| One row carries it | a single outsized trade       | one enterprise account is the growth | one site drives the effect      |
| Grouping ≠ cause   | "Mondays lose money"          | "Safari users churn"                 | "the Tuesday cohort responds"   |
| Empty is not zero  | retention cliff reads as zero | a broken event reads as no usage     | missing data reads as no effect |

If a question does not apply to your work, skip it deliberately and say so in the
writeup. Skipping is fine; skipping silently is not.

## Pitfalls

1. **Re-running the calculation.** It proves the arithmetic. All 49 incidents
   reproduce perfectly.
2. **Three correlated checks.** Knight-Leveson. Vary the mechanism.
3. **Averaging a disagreement.** Find the driver instead.
4. **A range chosen after seeing the number.** It always contains the number.
   Write it first or skip the check honestly.
5. **Counting only the variants you kept.**
6. **A control that has never returned a null.** If it cannot fail, its pass is not
   information. Feed it shuffled and zeroed input and confirm it fails.
7. **Reporting before the checks finish.** The most trust-destroying pattern in
   the entire audit.
8. **Explaining an artifact.** In one incident a wrong series produced a
   divergence, and a plausible reason for the divergence was invented before
   anyone checked whether the divergence was real. Validate the observation before
   explaining it.
9. **Thinking the skill's presence is the safeguard.** 345,000 words of correct
   guidance already sat on disk while these incidents happened. Guidance nobody
   runs is decoration.

## Honest limits

**Most of this is prompts, on purpose.** The largest failure class is prevented by
_declaring_ the unit, the population, and the expected magnitude before computing.
No function can recover them afterwards: nothing in a column of floats reveals
whether the values are users or contract prices, and `0.108` is untyped in every
dataset that has ever existed. If you skip the writing-down step, no tooling saves
you.

**Answering all five questions is not a correct answer.** It means these specific
failure modes were ruled out. The universe of ways to be wrong is larger.

**The thresholds in the script are conventions, not laws** (50% mass, p<0.05).
They are defensible defaults. Override them with a reason.

**`shuffle` assumes exchangeability.** A plain permutation destroys serial
structure, which is right for a cross-sectional claim and wrong for autocorrelated
time series, where a block bootstrap is the correct comparator. The script warns
about this; it cannot detect it for you.

## Sources

- Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024. https://arxiv.org/abs/2310.01798
- Knight & Leveson, "An Experimental Evaluation of the Assumption of Independence
  in Multiversion Programming", IEEE TSE SE-12(1):96-109, 1986.
  https://dx.doi.org/10.1109/TSE.1986.6312924
- Simonsohn, Simmons & Nelson, "Specification Curve Analysis", _Nature Human
  Behaviour_ 4:1208-1214, 2020. https://www.nature.com/articles/s41562-020-0912-z
- Steegen, Tuerlinckx, Gelman & Vanpaemel, "Increasing Transparency Through a
  Multiverse Analysis", 2016.
- Bailey & López de Prado, "The Deflated Sharpe Ratio", _Journal of Portfolio
  Management_ 40(5):94-107, 2014. https://ssrn.com/abstract=2460551
- Gelman & Loken, "The Garden of Forking Paths", 2013.
- For persistent pipelines rather than one-off analyses, adopt a real data-quality
  framework instead of hand-rolling: dbt tests (`unique`, `not_null`,
  `relationships`, `accepted_values`, source freshness), Great Expectations, Soda
  Core, or Pandera. This skill targets the analysis you run once and act on.
