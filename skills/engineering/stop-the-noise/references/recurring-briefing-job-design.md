# Designing a recurring briefing job (watch / digest / "tell me what changed")

Governs the class: **a scheduled job that watches an external world and tells a human what
changed** — model releases, dependency updates, competitor moves, price changes, security
advisories. These jobs fail in characteristic ways that are not obvious until a human is
already annoyed.

Derived from the 2026-08-15 model-watch build (the operator/the operations agent), where every rule below was a
correction the operator issued after seeing real output.

---

## 1. One job, one cadence, one question

A job whose remit mixes **discovery** ("find new things worth adopting") with **incumbent
tracking** ("did something we already run change?") gets scheduled at the faster cadence and
then manufactures discovery findings daily to justify the tick.

Split them:

| Question                               | Cadence | Scope                                             |
| -------------------------------------- | ------- | ------------------------------------------------- |
| Did something we ALREADY use change?   | daily   | bounded — enumerate incumbents, that IS the scope |
| Is there something new worth adopting? | weekly  | open-ended exploration                            |

Two rules when splitting:

- **Separate ledger files, always.** A shared dedupe ledger lets one job's entry silently
  suppress the other's alert about the same subject. The daily upgrade warning vanishes
  because the weekly discovery job already logged that name. Two files cannot do this.
- **Explicit hand-off clause in BOTH prompts.** "If you find X, that is the other job's —
  drop it." Without it the overlapping run reports the same finding twice, which is exactly
  the noise the split was meant to remove.

Ground the daily job's scope in a **pre-run script that dumps current live state** (see
`scripts/` pattern), not in the model's memory of what you run. The script output becomes the
definitive allowlist of what the job may report on.

---

## 2. The actionability gate — the single highest-value rule

> the operator, 2026-08-15: "I don't want to see a notification every day that it runs where I don't
> have to do anything. That's noise."

For every candidate finding the job asks: **does this change what the human would DO?**

REPORT only when there is a decision or an action:

- a deprecation/EOL date exists and we must move before it
- a pinned dependency has a successor and moving is a real judgment call
- a change is large enough to warrant reconsidering a choice
- something is actually broken or degrading

STAY SILENT on (these feel like content but are noise):

- "no forced moves", "nothing needs to change", "we are already up to date"
- **an automatic improvement that requires no config change and no decision.** A vendor
  price cut lands whether or not the human reads about it. This one is counterintuitive —
  it is genuinely interesting information — but interesting is not the bar. Actionable is.
- a temporary/promotional discount that expires on its own
- anything that self-corrects (see floating aliases below)
- a new capability with no use in the current setup
- status confirmations that the job ran

**Kill the TL;DR line.** A summary line forces prose even when the answer is "nothing", and
produces the specific artifact the operator rejected: _"TL;DR: No forced moves."_ Open with the most
actionable item or emit `[SILENT]`.

### Silent does not mean unrecorded

When the job suppresses a non-actionable finding, it should **still append it to the ledger
with a `(silent)` marker**. Otherwise it re-evaluates the same non-event tomorrow, and the
day after.

> Ledger writes are free; notifications are not.

This is the rule that lets the gate be aggressive without losing institutional memory.

---

## 3. Know which of your inputs are self-updating

**The defect that got caught, 2026-08-15:** the job recommended "upgrade
`~google/gemini-flash-latest` to Gemini 3.7 Flash". That ID is a _floating alias_ — it already
resolved to Gemini 3.7 Flash at the identical price. The job told the user to change a thing
into itself.

Root cause was the prompt, not the model: it was told to check every incumbent for a newer
version, and never told that some incumbents self-upgrade by definition. It followed
instructions into a nonsense conclusion.

**Rule:** before a watch job evaluates anything, classify each tracked item as
**PINNED** (will not move on its own; a successor is a real decision) or
**FLOATING** (an alias/rolling tag that resolves to newest; cannot be "behind").

Never recommend upgrading a floating alias to a specific version. A floating alias is
reportable only when:

- it is being **retired or repointed** by the provider, or
- the family it tracks changed price/limits enough to matter, or
- it silently moved to something **worse** — the real risk of a floating pin, and the one
  nobody thinks to watch for.

### Teach the PATTERN, never a hardcoded list

**the operator's follow-up correction, 2026-08-15** (after the first fix enumerated the four floating
IDs then in the stack): _"We're going to be adding more 'latest' prompts. I think it's a
terrible idea for you to hard code the specific models around that, and instead, you should
describe the pattern."_

This generalizes well beyond model IDs. Any time a recurring job must classify members of a
set the human is **actively growing**, a hardcoded roster is stale the day after you write it
— and a stale roster reintroduces the exact bug the rule was added to prevent, silently,
because the new member falls through the classifier unlabeled.

Write the prompt so the job **derives the classification each run from the live state dump**,
using a stated rule:

```
FLOATING (self-upgrading; cannot be behind):
  - the ID contains the word `latest` anywhere (`-latest`, `:latest`, vendor pointers), and/or
  - the ID carries a leading tilde `~` (OpenRouter's floating-pointer marker)
  Check BOTH signals INDEPENDENTLY.

PINNED (frozen until a human edits it — where upgrade decisions actually live):
  - an explicit version number, a trailing date stamp, or a build/effort suffix
    on a concrete version
```

**Check each signal independently — verified, not assumed.** Measured against the live
OpenRouter catalog: 11 of 12 floating IDs carried _both_ a tilde and `-latest`, but
`openai/gpt-chat-latest` carried **only** `-latest` with no tilde. A classifier keyed solely
on the tilde would mislabel it PINNED and then emit the same nonsense "upgrade the alias"
recommendation on a different slot. Treat the presence of _either_ signal as floating.

**Give the ambiguous case a safe default.** Instruct: when a rule cannot settle an ID, resolve
against the live catalog; if still unsure, treat it as PINNED. A false "you should upgrade" on
a self-updating alias is worse than briefly not knowing — the first is confidently wrong and
erodes trust in the whole briefing, the second is merely incomplete.

**Purge lists from the ledger too, not just the prompt.** The dedupe ledger is the other place
a roster accretes. Replace any enumerated list there with the same pattern rule plus an
explicit "do not maintain a list here, it will go stale" note, or a future run will faithfully
consult the stale roster.

Verify against the live model API rather than assuming from the string shape.

**Related trap:** some IDs are _router-internal_ effort/tier aliases that are not public
upstream routes (e.g. an `-xhigh` or `-low` suffix on a real base model). Their absence from
the vendor API is EXPECTED, not a broken route. Write that into the prompt explicitly or the
job re-flags it as a defect every single run.

---

## 3b. Budget the search, and never narrate a tool failure to the human

Open-ended **discovery** jobs (the weekly half of the split) have no bounded input set, so
they can loop on searching in a way the bounded daily job never will. Observed 2026-08-15: the
weekly job made **50 repeated `web_search` calls**, tripped the Hermes per-turn guardrail
(`loop_web_search_cap`, enforced in `agent/tool_guardrails.py` — a cap of 0 disables it), died
with no analysis produced, and then delivered its own tool error as the user-facing response:

> _"I stopped retrying web_search because it hit the tool-call guardrail…"_

Two distinct defects, both in the prompt, both worth designing against up front.

### Give the job a search budget and a bulk-source-first strategy

A discovery prompt that just says "search for what's new" invites a query-by-query crawl that
either exhausts the guardrail or burns the run's time. Write into the prompt:

- **A hard call budget** well under the platform cap, stated as a number.
- **"Never repeat a query that returned nothing useful."** Repeating a failing query is the
  specific behavior that produces a runaway loop. Instruct: broaden the terms, switch vendor,
  or move on.
- **One bulk/catalog source before any search.** A single catalog endpoint that returns the
  whole set with attributes (pricing, context, `created` timestamp) replaces a dozen
  individual lookups and is authoritative for availability and price. Search is then only for
  what the catalog cannot answer — benchmarks, reputation, vendor announcements.
- **"If you exhaust the budget, stop and work with what you have."** Partial information is
  acceptable in a job that is allowed to find nothing.

The bounded daily job did not hit this, because its scope was pinned to a live-state dump of
~17 known items. **Scope grounding is also loop protection** — another reason to prefer it.

### A job failure is a THIRD noise class — suppress it

The actionability gate covers "nothing to report". It does not cover "I broke", and a failing
job will happily narrate its internal difficulties into the human's chat. That is the same
noise the job exists to avoid, wearing a different hat.

Write an explicit failure clause:

```
If a tool fails, a backend misbehaves, you hit the search budget, or you cannot complete
the analysis: DO NOT send a message about it. Respond with exactly [SILENT].
The run log preserves the details for later inspection.
ONLY exception: a positively confirmed problem affecting the thing being watched
(e.g. something we depend on was pulled by its provider) is a real finding — report it
as a finding, not as a tool complaint.
```

That exception matters: it keeps a genuine outage loud while silencing self-referential tool
chatter. Diagnose the failure from the stored run output at `cron/output/<job_id>/*.md`, which
is where it belongs — the operator reads run logs, the owner should not have to.

**Before blaming the tool, verify the tool.** Call the failing tool once directly. In this case
`web_search` returned clean results in ~2s, which proved the backend was healthy and the defect
was an unbounded retry loop the prompt permitted. Skipping that check invites writing down
"the search tool is broken", which is both wrong and durable in the worst way.

---

## 4. Schedule from measured release behavior, not intuition

Do not guess when to run a watch job. The data usually exists.

**Method used (OpenRouter):** pull the model catalog, read the `created` timestamp on every
entry, filter to the vendors that matter, convert to the human's local timezone, and build
day-of-week and hour-of-day histograms plus a **cumulative same-day capture curve**.

Findings from 239 releases over ~18 months, US Central:

- **69% land Tue–Thu. Only 12% land Fri–Sun.** The weekend is nearly empty — so a Monday
  digest is not catching a weekend pile-up, it is delivering Thursday's news four days late
  in the worst inbox moment of the week.
- **Releases cluster in US Pacific mid-morning** (peak hour = 10am PT). A job running at
  10:00 local Central captured only ~37% of same-day releases; 17:00 captured ~90%.

Generalizable rules:

- Run a **daily** watch AFTER the vendor-timezone release window closes, not before it opens.
  Compute the cumulative capture curve and pick the knee.
- Run a **weekly** digest **downstream of the release bulk** (late in the work week), so it
  summarizes a complete cycle instead of splitting it. Never Monday morning — that is a pile
  landing at the human's least receptive moment.
- Use **odd minutes** (`:20`, `:45`) to dodge the top-of-hour cron pile, and check for
  collisions with existing jobs in that window.

**Verify the signal before trusting it.** Check whether a suspicious spike is a timestamp
artifact: count distinct minutes within the peak hour, and count entries at exactly
`00:00:00 UTC` (which indicates date-only rounding). A real spike is spread across minutes.

**State the method's limit.** A catalog `created` field is when the _aggregator listed_ the
model, which can trail the vendor's own announcement. Day-of-week signal is robust; hour
signal is directionally right but slightly lagged. Say so rather than overclaiming.

---

## 5. Test the boundary, not the findings

A fresh watch job's findings look fine on the first run. What you actually need to prove is
what it **refuses** to do.

- **Test the discard path.** Manually run with a one-off instruction to append a self-check
  naming every candidate it DISCARDED as out of scope and why. That, not its report, proves
  the lane boundary holds. (In the real test the job correctly discarded five new models as
  belonging to the weekly job.)
- **Test the silence path.** After the ledger is populated, run it again. The correct output
  is `[SILENT]`. Ask it to write its reasoning to a FILE while returning only the token, so
  the gate can be inspected without notifying the human. If it speaks anyway, the gate is
  too loose.
- **Verify the ledger write landed** — read the file. A job that claims "Ledger updated" has
  self-reported, which is not evidence.
- **Independently spot-check its most actionable numeric claim** against the live API. If it
  quotes a price, confirm the price. This is how you calibrate whether to trust its sourcing.

### Probe the specific rule you just changed

A generic re-run does not test a rule you just edited — it tests the job. After tightening a
classifier, write the test instruction to **interrogate the exact edge case that motivated the
change**, and require the job to answer it in words.

Concretely: after replacing a hardcoded roster with a pattern, the test asked the job to state
_which signal_ it used to classify each item, and to answer directly whether an ID containing
`latest` with **no** leading tilde would be FLOATING or PINNED. That is the one case a naive
reading gets wrong, so that is the case the test must force it to articulate.

Ask for the _signal_, not just the verdict. A job can reach the right label by luck or by
memorizing last run's answer; naming the deciding signal proves it applied the rule.

**Watch for the job narrowing your rule in its own words.** A run executed against the older
prompt wrote into its reasoning file: _"only leading-tilde `-latest` OpenRouter IDs are
floating aliases"_ — a stricter rule than the one intended, self-authored and stale-by-design.
Read the reasoning file for **restatements of the rule**, not only for conclusions. A job that
paraphrases your rule more narrowly than you wrote it will act on its paraphrase.

**Order of operations when a prompt edit races a running test.** A manual run reads the prompt
at dispatch time, so an edit landing mid-run is NOT under test. Either wait for the run to
finish before editing, or re-verify afterward that the deployed prompt contains the change
(grep the stored job definition for a distinctive phrase from the new text) and re-run. Do not
credit a passing result to an edit the run never saw.

---

## Checklist

- [ ] One question per job; discovery and incumbent-tracking are separate jobs.
- [ ] Separate ledger file per job; hand-off clause in both prompts.
- [ ] Scope grounded in a live-state pre-run script, not model memory.
- [ ] Actionability gate present, with the non-actionable cases enumerated explicitly.
- [ ] Automatic/no-decision changes routed to the ledger `(silent)`, not to the human.
- [ ] No TL;DR line.
- [ ] Tracked items classified PINNED vs FLOATING; no "upgrade the alias" recommendations.
- [ ] Classification stated as a PATTERN derived each run, not a hardcoded roster — in the
      prompt AND in the ledger.
- [ ] Multi-signal classifiers check each signal independently; ambiguous cases default to
      the safer label.
- [ ] Router-internal aliases pre-declared as expected, not defects.
- [ ] Open-ended/discovery jobs carry a stated search-call budget, a bulk-catalog-first
      instruction, and a "never repeat a failing query" rule.
- [ ] An explicit failure clause routes tool errors and incomplete runs to `[SILENT]`, with a
      carve-out for genuinely confirmed problems in the watched subject.
- [ ] Schedule derived from a measured release histogram, with the caveat stated.
- [ ] Boundary tested via discard self-check; silence tested via a populated-ledger rerun.
- [ ] The specific edge case behind the latest rule change was probed by name, asking for the
      deciding signal rather than the verdict.
- [ ] Confirmed the running job actually holds the edited prompt before crediting a test pass.
