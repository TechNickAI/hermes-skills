# Correction-rate confounds

`harvest.py` prints a lift table. It is a screen for where to go read
conversations by hand. It is not a measurement of skill quality, and it cannot
on its own justify revising any skill. This file is the reason why.

## What the join actually is

`bump_use()` does not persist a session id, so usage counters cannot answer "was
this skill loaded on the turn that went wrong". But `skill_view` tool calls sit
in `messages.tool_calls` with a session id and timestamp, and owner corrections
sit in the same table. Joining them per session gives: _for each owner
correction, which skills did the model choose earlier in that same session_.

`skill_view` is the right signal precisely because it is model-chosen. Cron jobs
and slash commands preload skills via the job's `skills:` field, which increments
`use_count` without any tool call. Building this analysis on `use_count` mixes
forced injection into a measurement of routing, which is the confound that
invalidates the whole exercise.

## Confound 0: the compaction blob (found by this file's own procedure)

The first run of this join on a real profile ranked `deep-dive` top at 3.41x and
`multi-review` second at 2.26x. Both numbers were artifacts.

`[CONTEXT COMPACTION - REFERENCE ONLY]` handoff blobs are stored with
`role='user'` on interactive sources, and their own boilerplate contains "Do NOT
answer questions ... they were already addressed" and "the latest user message
WINS". That is correction vocabulary in text **the owner never wrote**. They were
not in `MACHINE_PREAMBLES`, so every long compacted session -- i.e. every hard,
skill-heavy session -- got scored as an owner correction.

Measured: 186 of 459 matched rows (40%) were compaction blobs. After filtering
them the baseline fell 8.4% -> 2.8%, `deep-dive` fell 3.41x -> 1.00x (dead
average), and the ranking reordered completely. Fixed in `harvest.py`.

The lesson generalises past this one pattern: **any machine-authored text that
survives the filter biases hardest toward the skills used in the longest
sessions**, because those sessions contain the most machine text. Before quoting
a ranking, dump the actual matched strings and read them. Do not trust the
regex's own count.

## Confound 1: difficulty, not defect

Hard tasks load more skills **and** draw more corrections. A skill that sits at
the top of the lift table may simply be the skill for the hardest system in the
environment — which is what you would expect whether or not it is any good.

Observed in practice: the highest-lift entries were the skills attached to the
most complex live system in the fleet, and the second-highest was a review
workflow that only gets invoked on contested work. Neither result distinguishes
"this skill misleads the agent" from "this work is hard".

There is no way to separate these from the join alone. Reading episodes is the
only way, and the join's job is to tell you which episodes to read.

## Confound 2: sessions double-count

A session that loaded five skills contributes to five per-skill rates. The rows
are not independent, so the table does not support significance testing, and the
per-skill rates cannot be summed or averaged into anything meaningful.

## Confound 3: small n

The script enforces a floor (`MIN_SESSIONS`) for exactly this reason. Below it, a
single unlucky session swings a rate by tens of percent. Raising the floor is
usually better than reporting a suggestive number from a handful of sessions.

There are no confidence intervals in the output. Do not add them without also
fixing the independence problem, or they will be wrong in a way that looks
rigorous.

## The size hypothesis failed its own test

A reasonable alternative explanation for recurring failures is that large skills
are unfollowable walls of text — "lost in the middle". The script's size-gradient
table tests it directly.

Measured on one real profile, there was **no size gradient**. The largest bucket
did not have the highest correction rate; a middle bucket did. If "too long to
follow" were the mechanism, the largest skills should have been worst, and they
were not.

That result is worth keeping for two reasons. First, it is a live example of
running a test you expect to _confirm_ someone else's hypothesis and watching it
fail. Second, it means neither the "skills loaded and ignored" explanation nor
the "skills too big to follow" explanation currently has support, and the honest
standing verdict on those recurring failures is **undetermined**.

## What survives

1. **Do not revise a skill on lift alone.** Use it to pick episodes to read.
2. **State the confound every time you quote a number from this table.** A lift
   figure repeated without its caveat becomes a fact in someone's memory within
   one hand-off.
3. **The next discriminating test**, if the position hypothesis is worth
   pursuing: within a single skill, do violated instructions sit in the head or
   the tail of the body? That tests position directly rather than by size proxy,
   and it is the only version of the claim this data can answer.

## What this does not touch

Mechanical findings from `audit.py` — truncated descriptions, name mismatches,
skills at the content cap — are independent of all of the above. A description
longer than the index limit is truncated in the system prompt regardless of any
correction analysis, and it can be fixed on that basis alone.
