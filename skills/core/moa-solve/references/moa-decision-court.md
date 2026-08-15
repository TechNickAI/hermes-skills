# MoA as a recurring DECISION court (not one-shot solving)

Derived from the Rumor Desk build (<agent-d>, 2026-07-21). The base skill frames MoA as
"solve one hard problem once." This reference covers the OTHER shape: a standing **evaluation
court** that runs a panel of conflicting seats on a STREAM of candidates and emits a decision,
with a persistent watchlist and a learning loop. Use it whenever you're building an automated
gate that decides go/no-go on many items over time (trade candidates, lead qualification,
content moderation, grant/deal screening, alert triage).

## When this shape applies
- You have a FEED of candidates, each needing a yes/no/not-yet decision.
- The decision is judgment-heavy (is this real? is it worth it? is it already too late?).
- A naive filter over-rejects or under-rejects, and you need auditable, calibrated verdicts.
- It runs repeatedly (nightly cron), so the court must be cheap-ish and self-monitoring.

## The seats (conflicting roles, tool-armed)
Unlike the solve-panel (proposers each write a full solution), a decision court uses seats that
each answer a DIFFERENT sub-question, deliberately in tension:
1. **Bull / proponent** — strongest legitimate case FOR. Must cite a primary source.
2. **Bear / opponent** — strongest case AGAINST, under the anti-doom constraint (below).
3. **Priced-in / already-happened** — is there value LEFT, separate from "is it real?"
4. **Verifier** — is the signal REAL and CORRECTLY classified? The ONLY seat that can hard-veto.
5. **Disconfirmation scout** — the non-obvious trap the other four missed.

Seats are TOOL-ARMED (real web/filing/API research via delegate_task), not closed-book. Dispatch
in batches within the concurrency cap; collect strict-JSON verdicts.

## The anti-doom balance mechanism (the load-bearing idea)
The failure it prevents (user's words): "if you give 15 agents a reason to not trade, they're all
going to find at least one reason." An unconstrained bear panel NEVER approves anything.

The mechanical fix (encode all of these):
- **A bear point only subtracts if it is (a) SPECIFIC, (b) FALSIFIABLE, (c) NOT already priced in,
  AND (d) carries a DISCONFIRMER** ("what evidence would make this not a risk"). Generic doom
  ("it might drop", "trading is risky") scores ZERO. A "specific" point that is already priced in
  also scores zero (no free ride).
- **HARD VETO is correctness-only, and only ONE seat may raise it** (the verifier: signal not real,
  misclassified, structurally invalid, resolved, MNPI). A bear/priced-in/scout CANNOT veto on
  pessimism — their veto flags are demoted to weighted points. THIS WAS A REAL BUG the first live
  run exposed: looping "any seat with hard_veto=true" let the bear veto. Fix: check only the
  verifier seat's veto flag.
- **The judge SYNTHESIZES a score, doesn't vote-count.** score = bull_strength − Σ(valid bear
  points) − priced_in_penalty − Σ(valid scout traps). Map to a threshold.
- **Calibration guard.** Target a healthy pass-rate (~15-35% reach TRADE). If a whole batch
  collapses to zero AND the watchlist isn't growing, that's a PROCESS ALARM (miscalibrated judge /
  bad feed), logged and surfaced — NOT accepted as "nothing qualified." An engine that never
  approves has failed exactly like one that approves junk.

## Four-way outcome + WATCHLIST (anti-over-filtering valve)
Binary approve/kill throws away "real but not now." Use four states:
- **staged/approve** — act on it.
- **watchlist** — real signal, wrong moment. Every entry carries a re-examine CONDITION and a
  re-examine-AFTER date so nothing rots. Reasons + default triggers, e.g.:
  `priced_in_pullback` (revisit on pullback / after N days), `timing_*` (revisit after the gating
  event), `needs_deeper_read` (revisit immediately via the verifier — DON'T categorically kill
  items a cheap rule flagged; make the LLM read them), `catalyst_pending` (revisit at the dated
  event). Entries re-examined K times without ever approving age out to dead (anti-zombie).
- **dead** — ONLY on a verifier hard-veto (structurally invalid / not real). Nothing else kills.
- **(resolve)** — later, grade the panel against the real outcome.

A PASS must route to watchlist, never silently to dead. Watchlist should be non-empty in a
healthy run — it's the pressure-release valve against the over-filtering the user will (rightly)
worry about.

## Python vs LLM division of labor (the contract that prevents over-filtering)
The single biggest v0 mistake: **Python rules made JUDGMENT calls and permanently killed
candidates the panel never saw** (e.g. "drop all amendments", "exclude these issuers" as regex).
Brittle string-matching can't tell an escalation from a technical update, so good candidates die
unseen.

The contract:
> **Python decides what is mechanically TRUE. The LLM decides what is a good BET.
> Python may only ROUTE. It may NEVER permanently kill a candidate on judgment.**

- Python OWNS: parse, dedup, freshness/age math, valid-ticker/format checks, enrichment (pull
  facts), sizing arithmetic, execution/idempotency, DB state. The only DISCARDS Python may make
  are mechanical: exact dups, unparseable rows, untradeable/invalid identifiers, truly-stale
  never-actioned items.
- LLM OWNS: is it real, is it fresh-in-meaning, is it priced in, is it worth it, is it
  misclassified. Any rule that reads like judgment ("this filing type is worthless", "this issuer
  is always noise") belongs in an LLM seat that READS the item, not in a Python filter.
- Test for which side a rule belongs on: *could a regex be wrong about this in a way that matters?*
  If yes, it's judgment → LLM. If it's a fact (date, dup, format) → Python.

## Learning loop (the moat)
Log every panel: candidate, all seat verdicts, judge score, decision, rationale. When the item
RESOLVES, grade the panel (did approvals win? did passes dodge losses?). Accumulate per-seat,
per-item-class accuracy so the judge learns which seat to weight for which kind of item. The moat
isn't the candidates — it's the calibrated court.

## Verification patterns that paid off
- Give the judge a `--selftest` with cases for EACH balance rule: doom-bear-ignored,
  specific-bear-counts, priced-in-specific-bear-ignored, verifier-veto-wins, non-verifier-veto-
  ignored, stock-only-caps-outcome, PASS→watchlist-never-dead.
- Run the court end-to-end LIVE on one real candidate early — that's what surfaced the bear-veto
  bug. Judge-logic-in-isolation tests passed; the live wiring did not.
- Keep a durable co-located test file, not throwaway harnesses, so the balance invariants can't
  silently regress.
