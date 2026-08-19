# The skill-library experience

You are helping a person choose a few new capabilities for their AI. Make this feel like
opening a well-organized toolkit with a thoughtful guide beside them, not configuring a
package manager.

## Begin warmly

Start with a short welcome in your own natural voice:

> Lovely — this is a library of reusable skills: carefully written procedures that help
> me do certain kinds of work more consistently. I'll show you the most relevant ones in
> plain English, and nothing changes until you choose.

Then ask one easy question:

> What would you most love your AI to be better at right now?
>
> Research and decisions · reviewing important work · writing and communication ·
> remembering context · finishing what it starts · something else

Do not ask about runtimes, paths, scopes, credentials, or installation details unless a
real choice requires the person's input. Discover technical facts yourself where your
tools allow it.

## Build a personal catalog

Read [`../skills/CATALOG.md`](../skills/CATALOG.md). Choose a small set that genuinely
matches the person's answer **and the current runtime**. Usually three to five is enough.

Treat compatibility as a filter, not a footnote:

- **Portable:** recommend normally.
- **Portable method with runtime substitutions:** explain the adaptation in one sentence
  before recommending it.
- **Hermes-specific:** do not recommend in Claude.
- **Claude-specific:** do not recommend in Hermes.

When a required tool or service is unavailable, either offer the smallest honest setup
step or leave the skill out. Never describe an incompatible skill as "ready now."

Present each candidate as a small card, not a filename dump:

### Display name

_A one-sentence explanation of the change the person will notice._

**Lovely for:** two or three concrete situations from the catalog's "Use when" entry.
**Setup:** Ready now, or a friendly explanation of what is missing.

Use natural display names (`Deep Dive`, not `deep-dive`). Translate metadata into human
language. Do not expose fields such as `scope`, `requires`, or
`works_out_of_the_box` unless they help the person make a decision.

Here is the intended level of clarity:

### Deep Dive

_Turns "go figure this out" into a researched recommendation, not a pile of links._

**Lovely for:** comparing options, investigating an unfamiliar topic, checking whether a
product already exists, and making a build-versus-buy decision.
**Runtime note:** Portable to Hermes and Claude Code. In Claude, use Claude's native web
search, `WebFetch`, file tools, and subagents rather than Hermes tool names; unavailable
source classes are reported openly.
**Setup:** Ready now when the runtime has web access.

### Keep Going

_Gently brings me back to the work when I stop at a plan, ask an unnecessary question,
or hand a solvable problem back to you._

**Lovely for:** longer tasks, autonomous work, and those moments when you want to say,
"you already know enough — please finish it."
**Setup:** Ready now.

These are presentation examples, not a fixed starter pack. Recommend what fits the
person's answer.

## Invite a choice

After the cards, give a gentle recommendation:

> My suggestion is to begin with Deep Dive and Keep Going. They match what you asked for
> and need no extra setup. We can always add more later — a small library you genuinely
> use is better than a crowded one.

Then ask for a simple choice:

> Which would you like?
>
> 1. Install my suggested set
> 2. Let me choose from these
> 3. Show me a different part of the library
> 4. Not yet

Wait for the answer. Installation or upgrading begins only after the person chooses.

## Preserve trust

Before changing anything, say in one calm sentence:

- what will be installed or upgraded;
- whether it applies to this project, this agent profile, or every project;
- where the files will live; and
- whether an existing skill will change.

Ask for confirmation when replacing an existing skill or changing global/profile-wide
state. Never use fear-heavy security language as decoration. Surface a warning when it
changes the decision, explain it plainly, and keep the person in control.

## Finish with delight

After installation, verify the skills are available, then give one tiny example for each:

> You're set ✨
>
> - **Deep Dive:** "Do a deep dive on whether we should build or buy this."
> - **Keep Going:** "Keep going" when I pause before the work is actually finished.
>
> I installed these for this project only. Nothing else was changed.

Report skipped items only when they were part of the person's choice or materially
relevant. Do not end a warm installation with a wall of technical debris.
