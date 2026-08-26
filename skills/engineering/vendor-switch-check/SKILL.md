---
name: vendor-switch-check
description: >
  Use when evaluating a new vendor, tool, or platform, or when someone proposes
  replacing one you already run. Tries to falsify the claimed advantage first —
  verify the capability exists on your actual plan, measure it on the real path,
  and price the switching cost — before designing any migration. Prevents adopting
  a tool for a feature it does not have, and prevents a migration whose payoff
  never gets measured.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags:
      [vendor, migration, evaluation, procurement, verification, methodology]
    related_skills: [prove-the-setting-works]
---

# Vendor Capability & Migration Audit

Triggers: "X is better than Y, should we switch?", "let's fully implement Z",
"evaluate this platform", "replace our current vendor", "consider adopting X",
"look at this product and see what we should pull into ours", "a friend built
this — what features should we steal?", "can we put this plugin into our repo?",
"copy it over and make it ours".

> **Adopting third-party CODE rather than a vendor SERVICE?** Read
> `references/adopting-third-party-code.md` FIRST. Different blockers, checked in
> a strict order: license → runtime compatibility → coupling surface → our own
> repo charter. Charter is the weakest argument and belongs last; a missing
> LICENSE file settles the question before any design discussion.

## Overview

"I'm told X is better than Y" is a hypothesis, not a brief. The job is to
falsify it, not confirm it. The expensive failure is not picking the wrong
vendor — it is migrating a working system on a justification that evaporates
under inspection, or shipping half a migration because one integration surface
silently did not exist.

Everything below is grounded in a real audit (ElevenLabs vs Vapi, 2026-08) where
the headline reason to migrate was already fixed in the incumbent, and the
"centralize through the router" plan was supported for one modality and absent
for another.

## Rule 0 — the stated reason to switch may already be fixed in the incumbent

**Inspect the CURRENT tool's live configuration before accepting it lacks a
capability.** Institutional memory records the day something failed, not the day
someone quietly fixed it.

Real case: a knowledge store recorded "this vendor can't do tone dialing" from one failed call,
and the migration case rested on ElevenLabs closing that gap. Querying the live
Vapi API showed `tools: [{"type":"dtmf"}]` on two assistants. The gap had closed
months earlier — the note even said _"our assistant isn't configured for it,"_
a config statement, not a platform limitation. The strongest argument for
migrating did not survive one API call.

1. Query the incumbent's live API/config for the capability. Not docs, not
   memory, not a stale runbook.
2. Re-read the original failure note. Distinguish **platform cannot** from
   **we had not configured it**.
3. If it was a config gap, the fix may be a config change, not a migration.

## Rule 1 — measure usage before migrating anything

Pull the incumbent's actual traffic/history before designing a migration.

Real case: Vapi call history returned `[]`. Zero calls. The plan was for a system
nobody used — converting the question from "which vendor?" to "do you want this
capability at all?", a better question with a cheaper answer.

- Zero usage → do not migrate. Decide revive vs retire (retire is ALWAYS-ASK).
- Low usage → migration cost likely exceeds benefit.
- Real usage → the comparison matters, and you have traffic to replay.

## Rule 1b — measure DEMAND for the feature, not just usage of the tool

A competitor's marketed feature is a hypothesis about _your_ needs, not evidence
of them. Before recommending you build or adopt something, count how often the
user actually asks for it. The user's own history is the cheapest available
falsification test — and it is usually sitting in a local SQLite database.

Real case: a competitor product markets "Timeline /
temporal awareness" as a headline pillar, and our store genuinely had no
queryable date field. The obvious recommendation was date-range querying. the operator
pushed back — _"I doubt that querying by date is actually useful"_ — so I counted
temporal patterns across **~7,000 real user messages**:

| pattern                                             | count | share  |
| --------------------------------------------------- | ----- | ------ |
| "change over time" (changed, updated, stale, newer) | 1,523 | 21%    |
| recency word (recent, latest, **still**, current)   | 658   | 9%     |
| relative window ("last week", "past month")         | 24    | 0%     |
| **"when did X happen"**                             | **1** | **0%** |

Date-range querying is a **non-feature** here — asked once in ~7,000 messages.
Building it would have shipped something never used, on a competitor's roadmap
rather than the user's need.

But 30% of messages _did_ carry temporal reference, and reading the actual hits
showed they overwhelmingly mean **"is this still true?"** — a _ranking_ problem
(prefer newer truth), not a _filtering_ problem (select a date range). Same
surface signal, completely different feature. **Read a sample of the matches
before naming the need**; the regex tells you a signal exists, not what it means.

Method — count against real history rather than reasoning from the feature name:

```python
import sqlite3, re
c = sqlite3.connect('file:<profile>/state.db?mode=ro', uri=True)
msgs = [r[0] for r in c.execute(
    "select content from messages where role='user' and content is not null")
    if r[0] and len(r[0]) < 3000]
for label, pat in PATTERNS.items():
    n = sum(1 for m in msgs if re.search(pat, m, re.I))
    print(f'{label:18}{n:5} ({100*n//len(msgs)}%)')
```

Corollaries:

- **Audit what you already have before adopting.** Four of the competitor's five pillars
  (persistent memory, model routing, memory approval, audit trail) were already
  implemented as well or better. Only one gap was real.
- **The competitor review can still be worth it** — its value was prompting a
  measurement of our own system, which surfaced a genuine defect (retrieval
  ranking superseded pages above their replacements). Report the measured defect,
  not the marketing feature.
- **When the user doubts a proposed feature, treat it as a testable claim.**
  Measure and report the number, including when it overturns your own proposal.

## Rule 2 — split the proposal into independent projects by blast radius

"Let's fully implement X" is almost never one project. Sequence by reversibility:

| piece                                              | risk                            | sequence |
| -------------------------------------------------- | ------------------------------- | -------- |
| swap an API call (transcription)                   | reversible, one config line     | first    |
| new greenfield feature (audio briefing)            | additive, no existing users     | early    |
| migrate a live external-facing surface (telephony) | one-way doors, external parties | last     |

Do the cheap reversible repair first. It buys real vendor familiarity before you
touch anything with a phone number or a customer on the other end.

**Number porting, account deletion, and anything an external party experiences
are one-way doors.** Run the new system in parallel on a second identifier and
cut over only after it wins on evidence.

## Rule 3 — measure the replacement on the USER'S OWN data

Vendor benchmarks and synthetic tests both mislead.

Real case: a synthetic macOS `say` clip suggested keyterm prompting was the
critical feature. On real voice notes, keyterms were **negligible on one sample
and actively harmful on another** (merged "HIJK, LMNOP" into "HJKLMNOP").
Shipping on the synthetic result would have promised a feature that made output
worse — and that the client could not even send.

- Hunt for existing real artifacts before asking the user to produce new ones
  (`find` for cached media, prior source files). Users often have months of
  material already on disk.
- **Prefer samples with a known-wrong prior result.** A stored transcript
  annotated _"likely a mishearing — flag for confirmation"_ is a natural gold
  label. Resolving a months-old open question is the most persuasive evidence
  available.
- Include the incumbent AND the free/local upgrade path as arms. "Use the better
  model you already have" deserves a fair test — and may lose on latency even
  when accuracy is close.
- Report wall-clock latency alongside quality. It flips conclusions: a free local
  model that pegs the CPU 60s per item is not viable on a host running
  production gateways.
- Explicitly retract predictions the measurement contradicts.

## Rule 4 — a platform is not monolithic; verify EACH surface in code

Never assume that because a router supports a vendor for one modality it supports
them for all.

Real case: the router lists ElevenLabs in `AUDIO_SPEECH_PROVIDERS` (22 entries,
TTS) but NOT `AUDIO_TRANSCRIPTION_PROVIDERS` (16 entries, STT). Production
`/v1/models` confirmed zero ElevenLabs entries. "One key, centrally routed" was
viable for TTS and impossible for STT.

1. Enumerate registry constants per modality and check membership
   programmatically — a shared grep mixes the lists and hides the gap.
2. Confirm against the LIVE deployment (`/v1/models`), not just the checkout.
3. Check whether combo/failover logic applies to that path at all. Audio proxy
   routes are often thin pass-throughs (~130 LOC) with none of the chat path's
   ladder logic. Grep for `combo|failover|strategy` before promising failover.
4. Report the gap as **config-shaped vs architectural**. A missing registry entry
   plus one handler alongside eight existing ones is a small upstream
   contribution — say so rather than declaring it impossible.

## Rule 5 — verify the CLIENT supports the feature, not just the vendor

Vendor API support does not mean your client sends it.

Real case: ElevenLabs supports keyterm prompting (1000 terms); Hermes's
ElevenLabs STT path sends only `model_id`, `tag_audio_events`, `diarize`,
`language_code`. **No keyterms support.** Read the client's request construction
before promising a vendor feature.

Verify base-URL overrides exist before designing centralized routing
(`stt.elevenlabs.base_url` did exist — but it was checked, not assumed).

## Rule 6 — silent-success API failure modes

Wrong-but-accepted parameters are the dangerous case.

Real case: `keyterms_prompt=` and `keywords=` both returned **HTTP 200 and
silently did nothing**. Only repeated `-F 'keyterms=X'` form fields worked.

- Never treat HTTP 200 as proof a parameter took effect. Verify by OUTPUT CHANGE
  against a control run.
- When a parameter appears inert, try alternate encodings (repeated fields vs
  JSON array vs comma string) before concluding it is unsupported.

## Rule 7 — report shape

Lead with the decision, then evidence, then explicitly what you did NOT verify.

- Open with the recommendation and the single strongest piece of evidence.
- Comparison tables with measured numbers, not adjectives.
- Name every unverified figure. Pricing scraped from a client-rendered page's
  embedded payload is NOT invoice-confirmed — say so.
- Label vendor claims as marketing and independent measurement as evidence,
  separately.
- State which of your own earlier claims the measurement overturned.
- End with the explicit approval gate (new spend, porting, deletion).

## Bundled scripts

- `scripts/stt_bakeoff.py` — like-for-like comparison harness (incumbent + free
  local upgrade + cloud vendor arms, wall-clock timed). Adapt the arms for other
  modalities; the SHAPE is the reusable part.
- `scripts/stt_verify.py` — runs a Hermes profile's REAL configured code path to
  prove a rollout landed. Use per profile and report the denominator.

## Pitfalls

- **Client-rendered pricing pages.** `web_extract` returns a shell. Prices live
  in the embedded framework payload (e.g. `self.__next_f`); unescape and regex
  with surrounding context so each number attributes to the right tier, or read
  the page's FAQ/schema block. Flag as not invoice-confirmed.
- **Free tiers are usually non-commercial with mandatory attribution.** Check
  before piloting anything user-facing.
- **Concurrency, not volume, often picks the tier.** For a fleet sharing one
  account, per-tier concurrent-request limits bind long before the monthly
  allowance. Compare concurrency to agent count.
- **Vendor comparison pages rank their own author first.** So do "top 10 tools"
  SEO farms. Discount both; prefer independent leaderboards and label which is
  which.
- **Search-heavy subagents hit tool-call caps.** Give researchers a hard search
  budget and point them at specific high-value URLs (`llms.txt`,
  `llms-full.txt`, doc paths) to extract directly rather than search for. Tell
  them to write findings to disk incrementally so a timeout still leaves usable
  material.
- **Salvage before re-dispatching.** A subagent that times out or blows its cap
  often still wrote a source cache or partial file. Check disk first — re-running
  costs more than reading what is there.
