---
name: stop-the-noise
description: >
  Use when something is sending repeated, unwanted, or unread messages — a
  scheduled job that reports every run, a webhook firing once per event, progress
  commentary nobody asked for. Finds which source is actually producing the
  messages and silences it without muting real alerts. Prevents the two usual
  mistakes: counting duplicates while still delivering them, and muting the
  channel that carried the one message that mattered.
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags:
      [
        cron,
        webhook,
        notifications,
        noise,
        prompts,
        suppression,
        silent,
        loops,
        gateway,
        display,
        progress,
        telegram,
        wall-of-text,
      ]
---

# Agent Notification Suppression

Governs the class of task: **an agent is producing messages it should not be producing**,
and the driver is a scheduled job, a webhook route, or another event source running an
agent turn per event.

Also governs the inverse authoring task: writing a cron/webhook prompt whose _correct_
behavior is silence most of the time.

Deep-dive reference: `references/silence-token-notification-loops.md` — full diagnostic
walkthrough, the working prompt contract, and hot-reload semantics.

**At fleet scale, measure before you fix:**
`references/measuring-noise-before-fixing-it.md` — message-class taxonomy, the
failure-rate reframe (a reported "failed jobs are spamming me" measured at **0.12%**;
the flood was _successful_ output plus UI ephemera), telethon forum-audit recipes, and
the cross-owner volume check that catches an agent outshouting a client in their own
room. Skip it and you will fix the class the operator named instead of the class
producing the volume.

**Two different noise classes live under this skill. Pick the right one first:**

| Symptom                                                                                                   | Class                              | Read                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------------------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Repeated messages ACROSS runs/events; bot narrating its own silence                                       | prompt-surface flood               | rest of this file                                                                                                                                                                                                                                                                                                                                         |
| Many messages WITHIN one turn; "wall of text", "only show me the last one"                                | gateway display layer              | `references/gateway-progress-noise-per-turn.md`                                                                                                                                                                                                                                                                                                           |
| Two agents in a shared room replying to each other; a mention-only member answering nobody                | cross-agent wake loop              | `references/cross-agent-progress-noise.md`                                                                                                                                                                                                                                                                                                                |
| "Clean up / summarize / dedupe / delete / roll up this channel"; owner overwhelmed by accumulated history | channel cleanup + alarm escalation | `references/channel-cleanup-and-alarm-escalation.md` (policy), then `references/rollup-cards-not-deletion.md` (**what the owner usually actually wants — read FIRST**), then `references/post-hoc-channel-cleanup.md` (implementation), then `references/incremental-sweep-cursors-and-watermarks.md` (making it incremental without breaking escalation) |

| A wrapper/runner renders every event at one severity; "cron failed" on a job that worked; you BUILT dedup and the flood continued | severity from the wrong source | `references/severity-from-the-wrong-source.md` |
| "I keep telling you fix this or silence this"; owner wants YOU to do the triage they have been doing by hand; "is this urgency right?" | adjudicating delivered alerts as the operator | `references/auditing-delivered-alerts-as-the-operator.md` |

The fourth class is the one most likely to be built **backwards**, and there are two
distinct ways to get it wrong.

The sixth class is the **inverse of building suppression**: nothing needs designing
because the flood already happened and the owner has been triaging it by hand. They are
handing that judgement to you. Do not answer it with volume statistics — read the actual
delivered cards through **the owner's own account**, group by condition, and adjudicate
each one on _did this deserve to interrupt them_ and _was the urgency right_. Measured on
one fleet: **28 of 230 cron cards used CRITICAL framing and 2 earned it**, while unread
counts concentrated 24-of-26 into the two loudest rooms — alarm fatigue, measured. Getting
urgency wrong costs more than getting volume wrong: an owner told something is CRITICAL
who disagrees discounts the whole channel, not just that card.

The fifth class differs from all of these: the volume may be _correct_ — one message per
event — but every message renders at the wrong severity, or a counter you built was never
wired to a delivery gate. **Counting is not suppressing**: incrementing an occurrence
count and then delivering anyway ships a flood whose own cards read "Occurrence 28", so
the status output looks like the feature works. Prove suppression by counting actual
deliveries, and verify with fail → success → fail alternation, not repetition.

**Wrong #1 — deleting the evidence.** Collapsing repeated messages is the obvious design,
and it destroys evidence: a message repeated 54 times is usually an **unacknowledged
alarm**, not redundancy. Measured 2026-08-21 — a SEV-1 halt reprinted 54 times over 95
hours with zero owner response, and a a guard-failure line reporting an unmonitored condition
reprinted 29 times over 5 days while still broken. A dedupe janitor would have deleted the
only standing evidence of both. Never delete the newest copy of a repeating fault; attach
a count and escalate on age.

**Wrong #2 — deleting at all.** When an owner says _"there's 95 messages about the same
thing and I don't want to see all 95"_, the deliverable is a card that **says 95**, not a
job that removes 94. Two builds were rejected before this landed. Telegram has a real
collapse primitive (`<blockquote expandable>`), and the industry model (Sentry issues,
PagerDuty dedup-vs-grouping) is one durable object per recurring thing, carrying a count,
edited in place. Read `references/rollup-cards-not-deletion.md` before writing any janitor
— it also carries the probed reaction/icon sets, the measured 4096-char and flood-control
limits, threshold-tuning data, and the **do-not-rename-forum-topics** rule.

**Wrong #3 — aggregating the wrong message class.** Rollup is for completed, recurring,
machine-emitted **outcomes**. Rolling up a live agent's interim progress (`terminal — 12×`,
`Queued for the next turn — 31×`) interferes with a turn in flight, tells the owner
nothing, and duplicates whatever already owns post-hoc channel cleanup. Exclude it
at the read layer. Ask "does something already handle this?" for _every_ message class the
tool touches, not once at the start — the same mistake arrives twice through different
doors (§1 and §4.5 of the reference).

**Wrong #4 — a menu of ways to avoid the problem.** `Ack / Snooze / Mute` are three
flavours of "go away" and none of them advance the work. Ship a button that ACTS —
**🔧 Fix it**, which hands the family to the agent that owns the room as a real task with
the count and occurrences as context — plus **one** dismissal affordance, reversible.

**Wrong #5 — deciding severity with a regex.** This is the one that gets shipped, tested,
and praised before anyone notices. A pattern matches scary _words_, so it graded a 61×
`"SEV-2 resolved — no money loss"` as CRITICAL and pinned it, graded a 126× routine
balance report as CRITICAL, and scored a genuinely failing job that never used an alarm
word as merely "warning". **Anything that decides what a HUMAN sees is a judgement, not a
pattern** — severity, priority, "does this matter", "is this the same issue", "should I
interrupt them". Use the model to READ the messages and grade
`act / watch / fyi / resolved`, where `fyi` and `resolved` render **nothing at all**.
Regex is for extracting known-shape tokens (a `job_id`, a timestamp), never for deciding
meaning or importance. Cost is not the constraint — ~25 families came to a few cents a day.
Full method, prompt, card shape, and the silent-pass bug class:
`references/llm-triage-not-regex-severity.md`.

The test before shipping any classifier: _would a person who read this message agree with
my classification?_ If that cannot be answered without reading it, the classifier has to
actually read it.

Before shipping any alarm-detection regex that gates deletion, run
`scripts/alarm_regex_fixture_test.py` — it tests **both** directions (real alarms must
match, prose about alarms must not). A greedy pattern flagged 385 ordinary conversational
messages as critical on one agent; only the negative fixtures exposed it.

The second class is tool-progress bubbles, heartbeats, status callbacks, and interim
assistant commentary from a single turn. `[SILENT]` and cron prompt contracts do not
apply to it at all — it is `display.*` config plus `gateway/stream_consumer.py`. Do not
run the diagnostic order below against it.

The third class is the same progress output arriving as **inbound events on another
agent's gateway**. It presents as a behavior complaint about the _replying_ agent, but
that agent's `require_mention` is typically correct — the opening is a chat-scoped
authorization grant that admits bots, combined with the adapter's reply-to-bot accept.
Diagnose from the receiver's inbound log, and fix the source's progress output too, not
just the receiver's grant.

A sibling concern — containing a runaway workload — covers the same event-storm root
cause when the presenting symptom is **cost, slowness, `database is locked`, or disk**
rather than user-visible noise. If a member is noisy _and_ unhealthy, read both — it is
usually one incident, not two.

## The one rule that explains most floods

Hermes suppresses delivery on an **exact token match only**:

```python
SILENT_MARKER = "[SILENT]"
_CRON_SILENCE_TOKENS = frozenset({"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"})
```

Any other text is a normal response and **gets delivered** — including a polite
sentence stating that the agent is staying quiet. "no notification needed",
"nothing to report", "staying silent — all healthy" are all **notifications**.

**Never invent your own sentinel when authoring a prompt.** Writing `NO_REPLY_NEEDED`,
`NOTHING_TO_REPORT`, or any other plausible-looking token into a cron prompt teaches the
model to emit a string Hermes does not recognize, so the job delivers its full report
every single tick. Only the tokens in the frozenset above suppress; `[SILENT]` is the
one to write. Hermes already injects the correct instruction into every cron prompt —
read a saved run at `cron/output/<job_id>/*.md` to see the exact wording it uses, rather
than guessing at a token name.

## Diagnostic order

1. **Read the thread before reading logs.** The repeated wording usually names its own
   source. Grammatical, _varied_ prose that explains why it is quiet = prompt-authored.
   Byte-identical duplicates = transport/flood-control, a different problem.
2. **Grep prompt surfaces for the literal repeated phrase** — skills, `cron/jobs.json`,
   `webhook_subscriptions.json`. The phrase is very often written verbatim in a prompt.
3. **Use arrival pattern to pick the driver.** Bursts of 5–10 in the same second =
   event-driven (webhook/daemon per event). Regular intervals = cron.
4. **Scope to the affected thread.** "Only this thread" means enumerate every prompt
   surface whose delivery target is that chat/topic, and fix all of them.

## Authoring a suppression contract

Soft instructions fail. Use an explicit token contract with the consequence stated:

```
For EVERY routine outcome — including <enumerate the real reason codes> — your
ENTIRE response must be exactly:
[SILENT]
Nothing else. No 'no notification needed', no explanation, no parenthetical, no
trailing sentence. Any text other than the literal token [SILENT] is DELIVERED to
the owner's phone as a push notification. The default here is [SILENT]; speaking
is the rare exception.
```

Load-bearing parts: "your ENTIRE response must be exactly" (blocks token+commentary);
enumerating **real** reason codes seen in logs rather than a category the model must
classify into; naming the consequence; declaring silence the default.

## Pitfalls

- **No restart needed for prompt fixes.** `webhook_subscriptions.json` hot-reloads
  mtime-gated on every request; `cron/jobs.json` is re-read every scheduler tick.
  Patch, then watch the next event. Bouncing a gateway for prompt text is wasted risk.
- **Back up first.** These files hold live per-route HMAC secrets. Write
  `<file>.bak-<timestamp>`, and have the patch script `assert` the old text was found
  before replacing it.
- **A negative instruction leaves the phrase in the file.** After patching, grep still
  matches inside `No 'no notification needed'`. Verify by reading the rewritten rule,
  not by expecting a zero grep count.
- **The flood can be the cause of an apparent health problem.** Each webhook event
  spawns its own agent session; hundreds bloated a gateway to 703 MB RSS, triggered a
  `database is locked` storm on `state.db`, and crashed it — leaving orphaned webhook
  sessions and interrupted cron executions. If a member is noisy _and_ unhealthy,
  suspect one root cause, not two.
- **Do not silence a signal that carries money or risk.** Suppress routine/dedupe
  outcomes only. Budget exhaustion, execution exceptions, and exchange rejections stay
  loud.
- **An accepted risk re-raised every run is noise, not diligence.** A recurring job that
  re-reports a posture the owner has already looked at and accepted (a permissive file
  mode on a private single-tenant box, a known-idle host, a deliberate config) trains the
  reader to skim the whole report — which is how the _real_ finding gets missed. When the
  owner says "that's fine", fix it in two places: add the general rule to the skill that
  governs the check (so no member re-derives it), and write the host-specific fact into
  that member's own memory (so it stops re-deciding hourly). Ask once; never re-raise.
  Corollary: a finding whose severity depends on a **trust boundary the collector cannot
  see** — who can log into this box, whether the network is private — must be confirmed
  with the owner before it is ever escalated, not asserted from the raw fact alone.
- **Cron is the wrong first suspect for burst floods.** Enumerate _every_ prompt
  surface before patching. In the svc-copy case, six cron jobs targeted the affected
  thread and looked like plausible culprits — but the real driver was a **daemon
  POSTing to a webhook route once per event**. The tells: 5–10 messages inside the
  same second (far tighter than any cron interval), no `cron/output/<job_id>_*`
  files for the suspected jobs, and `systemctl --user list-units | grep -i <name>`
  showing a `… -> Hermes webhook` unit. Patching only the crons would have looked
  like a fix and changed nothing.
- **After fixing the noise, check the member's health.** The same per-event runs
  that spammed the user had already crashed the gateway. Quiet is necessary but not
  sufficient — verify RSS, lock counts, and startup warnings before declaring done.

- **One job doing two cadences is a noise defect.** A recurring job whose remit mixes
  _discovery_ (rare, exploratory — "find new things worth adopting") with _incumbent
  tracking_ (frequent, bounded — "did something we already run change?") gets scheduled
  at the faster cadence and then manufactures discovery findings daily to justify the
  tick. the operator's 2026-08-15 correction: split them into two jobs on two schedules —
  daily for "new versions of what we already use", weekly for "new things worth
  evaluating". Two rules when splitting:
  - **Give each job its own ledger file.** A shared dedupe ledger lets one job's entry
    silently suppress the other's alert about the same model family — the daily
    upgrade warning vanishes because the weekly discovery job already logged the name.
  - **Write an explicit hand-off clause into BOTH prompts** ("if you find X, that is
    the other job's — drop it"). Without it, the overlapping run reports the same
    finding twice, which is precisely the noise the split was meant to remove.
    Verify a fresh split by test-running the narrower job with a one-off instruction to
    name what it _discarded_ as out of scope; that, not its findings, proves the
    boundary holds.
    Full playbook for this whole job class — actionability gate, floating-alias trap,
    measured scheduling, boundary/silence testing:
    `references/recurring-briefing-job-design.md`.

- **"Interesting" is not the bar; ACTIONABLE is.** The subtlest noise in a recurring
  briefing is a true, genuinely useful finding that requires no decision — an automatic
  vendor price cut, a promo discount that expires on its own, a dependency that
  self-upgraded. It reads as valuable, so it survives review, and the human still ends
  up with a notification they can do nothing about. Gate every finding on _does this
  change what they would DO?_ and route the rest to the ledger with a `(silent)` marker
  so the job does not re-derive the same non-event tomorrow. Ledger writes are free;
  notifications are not. Also delete any TL;DR/summary line from such a prompt — a
  summary field forces prose even when the answer is "nothing", which is exactly how
  "TL;DR: no forced moves" gets delivered at 5pm.

- **Encode a classification RULE, never a hardcoded roster.** When a recurring prompt must
  sort items into classes (self-updating vs pinned, monitored vs ignored, owned vs
  third-party), the tempting fix after a misclassification is to enumerate the current
  members. the operator rejected exactly this on 2026-08-15: _"We're going to be adding more 'latest'
  prompts. I think it's a terrible idea for you to hard code the specific models around that,
  and instead, you should describe the pattern."_ A roster is stale the day after it is
  written, and its staleness is **silent** — new members fall through unlabeled and
  reintroduce the original bug. Write the classifier as a rule applied each run against a
  live state dump, check multi-signal rules on each signal **independently** (verify against
  real data — one real ID carried only one of two expected markers), and give the ambiguous
  case a safe default. Purge rosters from the dedupe ledger too, with a note saying not to
  reintroduce one — the ledger is the other place lists quietly accrete.

- **A job that BREAKS will narrate its own tool failure to the user.** The `[SILENT]`
  contract and the actionability gate both cover "nothing to report"; neither covers
  "I broke". Observed 2026-08-15: a discovery cron looped on `web_search`, hit the
  per-turn guardrail (`loop_web_search_cap`), produced no analysis, and delivered
  _"I stopped retrying web_search because it hit the tool-call guardrail…"_ as its
  user-facing message. That is a third noise class — self-referential tool chatter —
  and it needs its own explicit clause: tool failure, exhausted budget, or incomplete
  analysis all resolve to `[SILENT]`, with details left in
  `cron/output/<job_id>/*.md` for the operator. Carve out one exception so real outages
  stay loud: a positively confirmed problem _in the thing being watched_ is a finding,
  reported as a finding. Related: open-ended jobs need a stated search-call budget and a
  "never repeat a failing query" rule, or they loop into the guardrail. Before writing
  any of this off as a broken tool, **call the tool once directly** — in that incident
  `web_search` was healthy in ~2s, and the real defect was an unbounded retry the prompt
  allowed. See `references/recurring-briefing-job-design.md` §3b.

## Suppression can create blindness — four failure modes to design against

Found by an ops-risk review lens against a fleet-wide suppression plan that would
otherwise have shipped. Each is a case where the noise went away _and so did the signal_.

- **"Tool failure resolves to `[SILENT]`" is too broad as written.** The pitfall above is
  right that a job must not narrate its own tool trouble — but a collector that died
  cannot establish that the watched system is healthy, and silence then reads as "all
  clear". Split the rule: a monitor's _own_ transient failure is silent **but persists to
  the ledger and escalates after a bounded consecutive-failure or data-staleness
  threshold**. Silence with no staleness check is how a dead monitor looks identical to a
  healthy one for weeks.

- **Killing heartbeats removes the only liveness signal.** Disabling "still working"
  notifications (`agent.gateway_notify_interval: 0`) makes a hung job and a quiet healthy
  job indistinguishable. Move liveness to a logged internal heartbeat _with an actual
  watcher_ before removing the delivered one — and check whether existing `cron/output/`
  and gateway logs already satisfy this rather than building a second monitoring system.

- **Deleted messages leave no audit trail.** Once `cleanup_progress` deletes bubbles, a
  post-incident "were we warned and did we ignore it?" is unanswerable. Confirm existing
  logs cover suppressed output before widening deletion.

- **Quiet hours must suppress DELIVERY only** — never logging, never escalation. Give the
  do-not-silence reason codes an explicit bypass (a margin breach at 3am pages regardless
  of whether impact is visible yet), and **queue** genuinely non-urgent held items for
  delivery at the window's end. "Suppressed and expired" is how a real event vanishes.

**Enumerate do-not-silence as concrete reason codes per watched system, never as vague
categories.** "Money, auth, outages" is exactly the kind of phrasing a model rationalizes
its way around at 3am. For a trading fleet the list ran: money movement, auth failures,
execution exceptions, exchange rejections, risk/exposure limit breaches, margin and
drawdown thresholds, stale market data, clock skew, partial-fill and slippage anomalies,
disk capacity, reconnect storms, confirmed outages in the watched thing.

**Fixture safety:** force-running live jobs to test their silence contracts can fire real
pages, take real trading actions, and pollute ledgers. Run fixtures against a sandbox
profile or with delivery intercepted at the adapter, and prove zero production side
effects before the first run.

**Falsify in both directions.** A volume-reduction target alone cannot detect a
suppression that swallowed a real alert. Pair it with injected known-bad synthetic events
(a fake margin breach, a fake exchange rejection) and confirm they still page. A quieter
fleet that lost a real signal is a failure, not a success.

## Verification

- [ ] Every prompt surface targeting the affected thread was patched, not just one.
- [ ] Watched a real post-patch event go quiet (or confirmed a clean quiet window).
- [ ] Interesting/loud cases still speak — suppression was not widened to swallow them.
- [ ] A broken/incomplete run goes `[SILENT]` rather than narrating its own tool trouble.
- [ ] Reported honestly if quiet could not be distinguished from "no events occurred".
- [ ] Failure rate measured before blaming failures; if low, the reframe to _successful_
      output was stated explicitly.
- [ ] Do-not-silence list written as concrete reason codes, not vague categories.
- [ ] A dead monitor is distinguishable from a healthy quiet one (staleness/consecutive-
      failure escalation exists).
- [ ] Falsified in both directions — volume fell AND injected known-bad events still paged.
- [ ] Rooms containing other humans checked for per-sender volume, not just the operator's.
- [ ] Checked whether an existing tool already handles the class before building a second one.
- [ ] For "too many of the same message": shipped a card that STATES the count, not a deleter.
- [ ] No forum-topic renaming (see `references/rollup-cards-not-deletion.md` §4).
- [ ] Any clustering/fingerprint asserted in BOTH directions on known-same and known-different pairs.
- [ ] Card/summary threshold chosen from a printed distribution — the cards must not become the flood.
- [ ] Per-chat edit pacing proven against real flood control; 429 never falls back to sending new.
- [ ] Quiet hours checked against each agent's REAL working window, in the room's own timezone.
- [ ] Committed numbers split by measured vs asserted; unbuilt segments carry no figure.
- [ ] Severity/priority decided by a MODEL THAT READ THE TEXT, never a regex.
- [ ] `fyi`/`resolved` families render nothing — no card, no reaction, no ping.
- [ ] Card leads with what happened; the raw count is supporting evidence, not the news.
- [ ] No "still unacknowledged, N×" pings — say what was found or say nothing.
- [ ] The tool's own output excluded from its own scan (no self-ingestion loop).
- [ ] Any full-coverage pass is its OWN pass, not nested inside the cursor-gated loop.
- [ ] Output count checked against the denominator — an implausibly low count is a bug,
      not a quiet day.
- [ ] When auditing what was DELIVERED: identity proven as the operator's own account
      (`is_bot: False`) and stated in the report — a bot session audits a different view.
- [ ] Read watermarks reported by CONCENTRATION per room, not as a global unread rate;
      the loud rooms hoard the unread and that is the alarm-fatigue evidence.
- [ ] Repeated alarms disambiguated by whether their INTERNAL STATE MOVES between fires;
      identical numbers hours apart is re-detection or hours of inaction, never progress.
- [ ] Your own monitoring job included in its own audit, and its cadence checked against
      the arrival interval of what it watches (a 4h watch cannot catch 15-minute pages).
