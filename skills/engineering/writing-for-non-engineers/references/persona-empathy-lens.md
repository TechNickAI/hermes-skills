# The Persona / Empathy Review Lens

When an artifact will be read by a **specific real person**, add a review lens that reads
it _as that person_. This is the highest-yield lens for owner-facing documents, and it
catches things no technical lens will.

## When to use it

- Any document a non-technical owner will read
- Announcements, incident explanations, plans presented for approval
- Anything where the recipient's trust is already damaged
- Whenever success depends on how someone _feels_ reading it, not just whether it is
  correct

## Constructing the prompt

A generic "review as a non-technical user" produces generic feedback. Supply enough for
the model to actually inhabit the person:

1. **Who they are** — job, how they work, what device they read on, how much time they
   have. ("Working realtor, reads on her phone between showings, often in her car.")
2. **Their temperament** — how they respond to spin, formality, being managed. ("Sharp,
   direct, profane when frustrated, will instantly detect being patronized.")
3. **Their history with this system** — specific failures they experienced, concretely.
   Not "has had problems" but "was locked out of her own accounting software because the
   assistant retried a login."
4. **What they actually asked for**, quoted verbatim if available.
5. **Prior review feedback**, if this is a second pass. Naming what an earlier draft got
   wrong makes the next review sharper and prevents re-litigating settled points.

Then ask pointed questions rather than "give feedback":

- Does she feel **heard** or **handled**? Point to specific lines for each.
- What would she **skip**?
- Is the ask answerable, or does it require knowledge she doesn't have?
- Does this sound like they understand her problem, or like engineers enjoying an
  engineering problem?
- Anything condescending or over-explained?
- What ONE change would make this land better?

Always add: _"Be blunt. If it is good, say so plainly — do not manufacture criticism."_
Without this, the lens invents problems on a genuinely good draft.

## Run it twice

Draft → review-as-them → rewrite → **review again**. The second pass reliably catches one
more real thing. In practice it has caught a missing timeline ("she'll immediately ask
when this goes live") and passive voice weakening the core promise.

The second prompt should explicitly list what the first pass criticized and ask whether
the rewrite actually fixed it or merely trimmed words.

## What this lens finds that others don't

Real examples from one session, none raised by the technical lenses:

- A 16-item technical list handed to an owner "for review" — _"This is the operator and his bot
  showing me their homework."_
- Quoting the user's own frustrated profanity back at her — _"makes it look like you're
  building a psychological profile of them rather than fixing your
  software."_
- Reassurance reading as condescension — _"Do not talk to me like a therapist."_
- Asking her to prioritize engineering work — _"You just wrote a 4-page spec, YOU figure
  out what to build first."_
- A missing latency answer — _"Does this mean I wait 30 seconds in a driveway with
  clients?"_
- A proposed daily-login integration check that would have re-triggered the exact account
  lockout she had already suffered.

That last one matters: **the persona lens caught a technical safety bug** the engineering
lens missed, because she remembered being locked out and asked whether this would do it
again. It is not the "soft" review.

## Pairing with other lenses

Run in parallel with at least one technical lens and one adversarial/contrarian lens.
They disagree productively and about different things:

- **Persona** — will this land with the human?
- **Engineering** — will the mechanism actually work?
- **Contrarian** — should this be built at all?

A useful pattern is contrarian-says-don't-build while engineering-says-build-it-right:
both correct, in sequence. Resolve with a cheap falsification step before committing.

## Model diversity

Use different model families for different lenses. In practice the persona lens has been
strongest on Gemini Pro, the technical lens on Grok, and the honesty/accountability lens
on the main working model. Running all three of one family produces correlated blind
spots.
