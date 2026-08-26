---
name: writing-for-non-engineers
description: >
  Use when writing a plan, status report, incident summary, or recommendation for
  someone who does not work in the system being described. Leads with what changed
  for them, keeps the technical detail underneath, and gives them at most one real
  decision to make. Prevents the two failures that lose a non-technical reader: a
  wall of internals, and a list of options with no recommendation.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [communication, writing, owners, review, empathy, plans]
    related_skills: [multi-review]
---

# Owner-Facing Writeups

## When to use

Any document a **non-technical owner** will read and act on: a plan presented for
approval, a diagnostic writeup, an incident explanation, a proposal, or a "here is what
we're building for you" doc.

Triggers: "write this up for <owner> to review", "make a plan <owner> can look at",
"explain to <owner> what we're doing", or any deliverable where a non-operator's
approval or trust is the point.

## Overview

The owner (the person who lives with a fleet member but does not operate it) and the
operator have opposite needs. Writing one document for both fails both.

## The split-document pattern

One file, two clearly separated sections, **owner section first**:

```
# What we're building for <Agent>

**<Owner>: this one is for you. <Operator>'s version is below it.**

## <Owner>'s version
... 300-500 words, zero jargon, what they will notice...

---
---

## <Operator>'s version
... full technical detail, architecture, open questions...
```

They should never scroll past architecture to find their part.

## Writing the owner section

**Lead with the deal, in one sentence.**

> "Ace checks himself constantly. When something breaks, he tells you before you find
> it. If he can't fix it, the operator gets it — not you."

Everything else elaborates that sentence.

**Only list things they have personally experienced.** Voice messages failing, dashboards
dead, appointments shifted by a wrong timezone. Never log rotation, cache-read
percentage, cron, FTS integrity, "cruft".

**Tie each item to their consequence, not the mechanism.** Not "clock drift detection" —
"if the timezone drifts, your appointments shift and you look bad in front of clients."

**Show the literal message they will receive.** Quote the actual sentence the agent will
send when something breaks and when it recovers. That is what they are actually buying.

**Active voice, agent as subject.** "Ace tests your voice messages" — not "your voice
messages get tested." Passive makes it sound like an abstract IT process instead of
their assistant doing the work.

**Ask them at most ONE thing, and make it non-technical.** Good ask:

> "When a personal-assistant agent lets you down, say so in the moment — however you'd naturally say it. You
> don't need to know what broke."

**End with a falsifiable commitment.** "If you're still the one discovering problems in a
month, this didn't work and we'll say so." This is what makes the honesty read as real
rather than as pre-excusing failure.

**Include a timeline.** A business owner reading a plan immediately thinks "when is this
live?" Give a rough one even if uncertain.

**Answer speed/latency concerns proactively.** If the change adds delay, say what it
costs and what the fallback is. Someone in a driveway with clients needs an answer in
15 seconds.

## Multi-source project handoff briefs

Use this pattern when an owner-facing brief must synthesize notes, transcripts, models,
and task artifacts into one current reference.

1. **Inventory recursively, then inventory again before sign-off.** Record file count,
   dates, and source systems at the start. Re-run the inventory after drafting because a
   transfer corpus or sibling agent may add files while the task is active.
2. **Build an evidence matrix before prose.** Track current status, decisions, people and
   roles, money paths, external-party state, risks, planned work, and next actions. Give
   every claim a source date and confidence class: confirmed fact, reported plan,
   estimate, theory, or unresolved conflict.
3. **Prefer the newest direct evidence, not the neatest artifact.** A later firsthand
   update can supersede an older canonical project file. Keep the old claim visible only
   when the conflict matters operationally.
4. **Treat transcript attribution as evidence with its own reliability.** If speaker
   labels are known to be unreliable, state the substance as a shared-conversation claim.
   Attribute only where identity is independently clear.
5. **Separate status from intent.** "Plan to offer Monday" is not "offer submitted";
   "lender can issue a letter" is not "letter attached"; "theory that the roof needs
   work" is not an inspection finding. Write the latest confirmed state first, then the
   intended next move.
6. **Distinguish decisions from proposals and stale rows.** A dated decision log beats an
   older task table. Surface stale operational state explicitly when someone could act on
   it.
7. **Name the action owner and trigger.** Every next action should say who acts, when,
   and what evidence closes it. Group actions by phase such as before offer, during
   diligence, financing, and after clearance.
8. **Protect the owner from false precision.** Label models as models, quotes as quotes,
   and overlapping budget envelopes as non-additive. Do not turn wide research ranges
   into a single authoritative total.
9. **Run deterministic final checks.** Verify the requested path exists, required
   sections are present, forbidden style characters are absent, secrets and identifiers
   are removed, and the final file count matches the last inventory.
10. **Respect concurrent edits.** Before replacing an existing deliverable, read it. If
    a write tool reports a sibling modification or collision, stop, compare, merge
    deliberately, and verify the merged artifact rather than silently overwriting it.

A compact checklist and reusable section order live in
`references/multi-source-project-briefs.md`.

## Take the owner's own diagnosis literally before reframing it

When a non-technical owner tells you _why_ something is hard for them, that is primary
evidence, not a symptom to be reinterpreted. This section exists because the lesson had
to be learned twice in one conversation.

The owner said: _"it's easier to use ChatGPT than a personal-assistant agent due to the interface."_

**Reframe #1 (wrong):** "the interface is fine, the real problem is response speed."
She then itemized three concrete interface costs — having to create a topic before
asking, no automatic topic naming, no useful immediate answer. Two of the three were
genuinely interface. Her original diagnosis was more accurate than the correction.

**Reframe #2 (worse):** proposing she use direct messages to skip topic creation. Her
reply: _"I do need to create a topic. That's the only way to keep things organized.
Otherwise the discussions become a mess where nothing can be found again,
anything."_ The suggestion would have destroyed the organizing system she depends on.

The rules that follow:

- **The friction they name is real.** Do not convert "this is awkward to use" into "this
  is slow" because latency is the thing you know how to measure.
- **Never propose removing a workflow step until you know what that step buys them.**
  Topic creation looked like pure overhead; it was actually their retrieval system. Ask
  what a step is doing for them before offering to delete it.
- **Owners compare against a specific competing product.** When they say "ChatGPT does
  X," go look at what X actually is. Here it decomposed into: start typing immediately,
  good default answer, automatic naming. Three separable, buildable things.
- **Say plainly when they were right and you were not.** "You corrected me and you're
  right, I fixed the wrong problem" costs nothing and is the whole basis of the next
  report they bother to send you.

**Corollary — verify capability before proposing a build.** When the owner asked whether
a new plugin was needed, checking the live system showed the platform adapter already
supported the features, and the bot already held `can_manage_topics: True` admin rights.
The answer changed from "build a new plugin" to "wire up functions that already exist."
A capability check turns a speculative project into a small, upstreamable change.

## Never gate progress on a decision the owner cannot evaluate

This applies to live support replies, not just formal documents. It is the
highest-frequency version of the "don't hand them your homework" rule, and it
cost a full turn.

an owner's reaction: a "PATH fix" meant nothing to them, and the update read as machine
goop. Stop handing me decisions that have no meaning to me and stop gating your
progress on these meaningless decisions. Just fix what you can. If it's
material to me, explain why in language I can understand. If it's material,
high impact, technical and you really don't know, ask the operator."\*

The failure: she reported that her agent silently abandoned a task when one of
two requested tools broke. The reply diagnosed two genuine root causes, then
closed with _"Want me to go ahead with the PATH fix and write up the other two
for the operator?"_ — asking a non-technical owner to authorize a term she had no basis
to judge, on a reversible fix she had already implicitly requested by reporting
the bug in the first place.

Routing rule, in order:

1. **Reversible and inside your lane → just do it.** Config edits with a
   backup, restarts, path corrections, memory/instruction updates on an agent
   you administer. Reporting the bug WAS the authorization.
2. **Material to their experience → do it, then explain the CONSEQUENCE in
   their words.** Not "I patched the launchd plist PATH" — "iMessage works
   again, and I confirmed it by having him pull up your real conversation list."
3. **Material, high-impact, technical, genuinely uncertain → ask the operator, not the
   owner.** Escalation goes up the technical chain. An owner is not the
   tiebreaker on an engineering judgment call.
4. **Genuinely theirs to decide → ask, but frame it as an outcome choice**,
   never a mechanism choice. "Do you want him able to read your messages, or
   only send them?" is answerable. "Should I grant Full Disk Access to the venv
   interpreter?" is not.

**An approval gate is only legitimate when the recipient can weigh the
tradeoff.** A gate the owner cannot evaluate is not caution, it is offloading —
the same defect as handing them a technical list to prioritize, just wearing a
politeness costume. Bounded autonomy means asking _the person qualified to
answer_.

**Do not narrate the diagnosis as a menu.** Findings are not choose-your-own-
adventure. Fix what is fixable, verify it, report the resolved state. If
something is still blocked, name the ONE thing in the way and who owns it.

**When the correction lands, acknowledge in one line and go fix it.** A
paragraph agreeing with the criticism spends their patience a second time.
"Fair hit — fixing now", then real tool calls.

## Hard prohibitions

Each was caught by an empathy review before shipping.

**Never ask an owner to approve a fix named in jargon.** "Want me to go ahead
with the `<implementation term>` fix?" is the canonical form of the error above.
Just do it, then report the outcome they can feel.

**Never hand back a question you have the evidence to answer yourself.**

This is the highest-recurrence failure in proposal work, and it survives review because
it _looks_ like deference. A closing section titled "Open decisions", "Questions for
you", or "Your call" feels like respecting the owner's authority. It reads as homework.
Volume makes it worse: three questions is not three times as deferential as one, it is a
to-do list.

Measured on one run. A research-and-propose task closed with three open questions —
scope, backlog depth, and which rooms to touch. The operator's reply:

> "come on. be helpful. don't just come back to questions. Think empathetically about
> what I want and propose what the job would do."

Every one of those three was answerable from evidence already gathered in that same
session.

**Enforcement test before sending.** For each question in the draft ask: _do I have what
I need to pick the better option?_ If yes — **pick it, state the call and the reasoning,
and name what would change your mind.** Ship a question only when the answer genuinely
turns on the owner's private preference, risk appetite, or a real approval gate (money,
credentials, irreversible or externally visible action). Then ship **one**, in prose,
never as a bulleted section.

- Right: _"I'd start with ephemera-only for a week, because I'd rather find out my
  classifier disagrees with you while everything is still recoverable — say the word if
  you want it more aggressive."_ One call, made, fork named, reversible.
- Wrong: _"1. What scope? 2. How far back? 3. Which rooms?"_

**When asked to _propose_, the deliverable is the proposal in concrete detail** — what
the thing does step by step, with real numbers and real example output rendered as the
owner will see it. Not a decision framework for them to resolve. Show the actual card,
the actual message text, the actual counts. A proposal they can picture is one they can
approve; a framework is one more thing on their plate.

**The relapse pattern: the questions come back as soon as the work gets risky.** In the
same one occasion session, _after_ the correction above had already landed and been
acknowledged, the very next substantial deliverable closed with three more open
questions. The trigger was irreversibility — deletion, someone else's rooms, driving the
owner's personal account — and the questions felt like conscientiousness rather than
avoidance.

Stakes do not convert an answerable question into a legitimate gate. They raise the bar
on **evidence**, not on **who decides**. The correct move under risk is to pick the
reversible option, say why it is reversible, and start there:

> _\"I'd start with ephemera-only on your room for a week, because I'd rather find out my
> classifier disagrees with you while everything is still recoverable.\"_

That is a decision, a reason, and an implicit invitation to override — in one sentence,
with no question mark. Reserve the actual gate for the one thing that is genuinely not
yours: in that session, driving the owner's **personal user account** rather than the
agent's own credentials. One gate, named plainly, while everything else proceeded.

Audit the draft for this specifically when the work is irreversible. That is exactly when
the pattern returns.

**Solve the verb they used, not the adjacent problem you know how to solve.** The same
one occasion session produced this correction one turn before the questions one. The owner
asked for _cleanup_: "summarization, cleanup, deleting of things that I don't need to
see, roll up." The plan that came back was a _prevention_ design — config keys and
silence contracts so agents would post less in future. Both are legitimate work; only
one was requested. His reply: _"you are reviewing these channels regularly and seeing —
what is the operator gonna see when he comes in here? Acting as an assistant to clean things up,
summarize, delete stuff that is useless."_

Prevention was the easier engineering problem and the one with tidy config levers, which
is exactly why it got substituted. Test the draft against the owner's **verbs**: clean
up, delete, summarize, and roll up are all operations on things that _already exist_. A
plan that only changes future behavior has answered a different question — and leaves
the accumulated mess they were actually staring at completely untouched. When both are
genuinely needed, ship the requested one first and name the other as a complement.

**Never hand an owner a technical list to review or prioritize.**

> "This is the operator and his bot showing me their homework. I don't need the blueprints to
> the smoke alarm, I just need you to install it and change the batteries."

Asking "which of these 16 matter most?" offloads engineering decisions onto someone who
cannot map their business problems to your buckets. Decide it yourself.

**Never quote their frustration or profanity back to them.**

> Stacking up seven verbatim quotes of an owner at their angriest reads as
> building a psychological profile of them rather than fixing your
> software. It shifts focus from your broken tech to my anger."

Use the complaints to drive the design. Quote at most one, and only if it is their
_request_ rather than their _anger_.

**No therapy-speak.** "None of this is your fault" / "your frustration is the correct
response" reads as being handled:

> "Do not talk to me like a therapist. Obviously it's not my fault the bot lied. I don't
> need your absolution."

Apologize once, plainly, for the cost. Then stop.

**No narrative about the team's analysis journey.** How you discovered the problem is
interesting to you and irrelevant to them. Two sentences max, at the end.

**Don't personify the agent to dodge responsibility.** "He kept retrying and locked you
out" hides the actor. Write "That was us." Personifying the assistant makes it the
offender and the team its concerned investigators.

**Don't send a recurring digest they didn't ask for.** To someone whose trust is already
damaged, a periodic automated list of what's broken is a spam bot reminding them the
system fails. If unsure, ask — and take "no" as the answer.

## Verify with the persona lens before sending

Never ship an owner-facing document without a review pass that reads it **as that
specific person**. See `references/persona-empathy-lens.md` for prompt construction.

Short version: supply their job, device, time pressure, temperament, specific failure
history, and what they actually asked for (quoted). Ask "does she feel heard or
handled?", "what would she skip?", "is the ask answerable?". Always add _"Be blunt. If
it is good, say so plainly — do not manufacture criticism."_

**Run it twice** — draft, review-as-them, rewrite, review again. The second pass
reliably catches one more real thing.

Run the persona lens **in parallel with** a technical lens and a contrarian lens; they
find different classes of problem.

## Pitfalls

- **The persona lens can catch technical bugs.** In one session it flagged a proposed
  daily-login integration check that would have re-triggered an account lockout the
  owner had already suffered — something the engineering lens missed. Do not treat it as
  the "soft" review.
- **Verify current state before proposing a fix.** Offering to fix something already
  fixed reads as not paying attention. Check the live system before writing "we will".
- **Check who is in the room before writing about someone.** Owners are often present in
  their own support threads. Writing clinical third-person analysis of someone sitting
  right there is a real and avoidable insult.

## Reference files

- `references/persona-empathy-lens.md` — how to construct and run the persona review
  lens, with real examples of what it catches.
- `references/owner-friction-is-primary-evidence.md` — worked case: an owner named an
  interface problem, it was reframed twice as something else, and both reframes were
  wrong. Includes the capability-check-before-building pattern.
