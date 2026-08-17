# Decision Panel + Anti-Veto Aggregator (MoA "court" variant)

Session origin: <agent-d> Rumor Desk "court", 2026-07-21. The panel decides **whether to take a
bounded action** (make this trade), not **how to solve an open problem**. Same MoA skeleton
(proposers + aggregator) but the roles and aggregator math differ. This pattern generalizes to any
gated go/no-go: ship a release, approve a spend, greenlight a candidate, publish, send.

## Why this variant exists (the core failure it prevents)

If ANY seat can hard-veto, the panel NEVER acts. Give N critics a mandate to find a reason not to
act and all N find one — the system trends to permanent inaction, which is a failure _identical_ to
acting on junk. the operator's exact framing: "if you give 15 agents a reason to not trade an evaluation,
they're all gonna be able to find at least one reason to not trade." The aggregator must be
engineered against this bias, mechanically, not by vibes.

## The 5 conflicting seats (tool-armed; each does REAL research)

1. **bull** — strongest legitimate case FOR. Must cite a PRIMARY source (filing / data / release),
   not sentiment. If no real catalyst, say so honestly.
2. **bear** — strongest case AGAINST. CONSTRAINED: every point must be specific + falsifiable +
   flagged priced-in-or-not, and carry a DISCONFIRMER ("what evidence would make this NOT a risk").
   Generic "it might drop / it's risky" is forbidden.
3. **priced-in / market-structure** — has the move already happened? Quantify gap vs any target,
   run-up %, IV, short interest, days-to-cover. Answers "is there money LEFT" — separate from "is
   it real."
4. **catalyst-verifier** — is the signal REAL and CORRECTLY classified? Reads the actual
   document. Flags misclassification (amendment vs initial, insider vs outside-activist, debt-refi
   vs M&A, sentiment vs filing, stale vs fresh). **This is the ONLY seat allowed to hard-veto.**
5. **disconfirmation-scout** — the non-obvious trap the other four miss (known arb pattern, pump,
   value trap, stale rerun, single-counterparty concentration).

Separate three questions across these seats: **is it REAL? / is there UPSIDE LEFT? / should we
ACT?** A candidate can be real, have room, and still be a pass. Collapsing them lets a "no" on one
masquerade as a "no" on all.

## The aggregator (synthesizing judge) — anti-veto math

```
def adjudicate(verdicts):
    by = {v.seat: v for v in verdicts}
    # 1. HARD VETO is CORRECTNESS-ONLY. Check the veto flag on the CORRECTNESS seat ONLY.
    #    NEVER loop all seats for veto — that is the bug that lets a bear kill on pessimism.
    cv = by["catalyst_verifier"]
    if cv.hard_veto.trigger:
        return HARD_VETO(reason=cv.hard_veto.reason)
    # 2. bull strength (only if bull actually says act)
    bull = confidence(bull) * scale  if bull.verdict in (BET, STOCK-ONLY) else 0
    # 3. a bear/disconfirmation point SUBTRACTS only if specific & falsifiable
    #    & NOT priced_in & has a disconfirmer. Everything else = weight 0.
    bear_weight = 0.5 * count_valid(bear.points)
    disc_weight = 0.5 * count_valid(disconfirmation.points)
    # 4. priced-in penalty
    pin = 1.0 if priced_in.verdict==NO-BET else 0.5 if priced_in.verdict==STOCK-ONLY else 0
    score = bull - bear_weight - pin - disc_weight
    # 5. any STOCK-ONLY seat caps to a small/half action
    return TRADE if score>=1.0 and not stock_only else SMALL if score>=0.3 else PASS

def count_valid(points):   # the anti-doom filter
    return sum(1 for p in points
              if p.specific and p.falsifiable and not p.priced_in and p.disconfirmer)
```

Key invariants (each has a regression test):

- A **bear/priced-in/disconfirmation `hard_veto=true` is IGNORED**. Only catalyst_verifier vetoes.
- **Generic doom → weight 0.** A "specific" but **already-priced-in** risk → weight 0 too (no free ride).
- A real, specific, unpriced bear point **lowers** the score but cannot **veto**.

## Calibration guard (don't let the court quietly reject everything)

Target act-rate ~15-35% of panels reach TRADE/SMALL. If a whole batch passes nothing, that is a
PROCESS ALARM (miscalibrated judge or bad candidate feed) — surface and fix it. "Nothing qualified"
is NOT an acceptable steady state; an engine that never acts has failed like one that acts on junk.
On night one of the Rumor Desk the court correctly rejected all 23 — but that was flagged as a
_candidate-feed_ problem (form-type filter had no content signal), not accepted as normal.

## Learning loop (the moat)

Log every panel: candidate, 5 seat verdicts, judge score, decision, rationale → a `*_panels` table.
When the decision later RESOLVES, grade the panel (did ACT calls win, did PASS calls dodge losses).
Accumulate per-seat, per-class accuracy so the judge learns which seat to weight for which kind of
candidate. The proprietary edge is the calibrated court, not the raw candidates.

## Feeding the panel: coarse filter selects, panel decides

A cheap machine pre-filter (form-type, dedupe, freshness, exclusion lists) only decides **what
deserves a panel**. It must NEVER be mistaken for the decision. In the trading case the pre-filter
keyed on SEC form-type and scored "Uber acquires Delivery Hero" identically to "Vistra extended a
receivables facility" — both are 8-K item 1.01. Form/type is not signal; CONTENT is. The tool-armed
panel reading the actual document is what produces the decision.
