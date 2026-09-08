---
name: learn-from-conversations
version: 2.1.0
description: >
  Use when turning recurring requests, repeated corrections, and workflows that
  worked into new skills or targeted updates to existing ones.
license: MIT
metadata:
  hermes:
    requires:
      - "Read access to the target agent's HERMES_HOME"
    tags: [skills, harvesting, memory, self-improvement]
    related_skills: [multi-review, deep-dive]
    # referenced but not shipped here: skill-librarian, skill-evaluation-and-rollout
    # — the procedure degrades gracefully without them
---

# Learn from conversations

## Overview

Recurring work should stop being rediscovered. This skill turns conversation
history into either a new skill or a targeted edit to the existing skill that
already owns the topic. The deliverable is fewer repeated explanations, not more
skills — a library that grows every pass is a failure mode, not progress.

Two instruments ship with it:

- `scripts/audit.py` — library health facts (sizes, truncated descriptions,
  usage, ghost records). Draws no conclusions.
- `scripts/harvest.py` — the per-turn join: which skills the model _chose_
  before an owner correction. Read `references/correction-rate-confounds.md`
  before quoting any number it prints.

## When to Use

- Periodically, over conversation history since the last checkpoint.
- After a stretch of work where the same thing was explained more than once.
- When an owner correction reveals a procedure that was never written down.

Do **not** use this to run a library-wide cleanup — sizes, retirement,
consolidation, description rewrites. That is a different job with a different
risk profile.

## Procedure

1. **Establish the checkpoint.** Harvest only episodes newer than the last pass.
   Record the new checkpoint only after findings are saved, so an interrupted
   run repeats rather than skips.

2. **Read episodes, not keyword hits.** A match is a pointer to a conversation
   you still have to read. Use session metadata to separate owner dialogue from
   cron prompts, delegation requests, reviewer rubrics, and forwarded material.
   Sender-name prefixes do not authenticate human authorship.

3. **Run the instruments.**

   ```bash
   python3 scripts/audit.py --profile ~/.hermes/profiles/<profile>
   python3 scripts/harvest.py --db ~/.hermes/profiles/<profile>/state.db \
       --sizes ~/.hermes/profiles/<profile>/skills
   ```

   Both are read-only. `harvest.py` opens the database with `mode=ro`.

4. **Generate candidates from successes as well as failures.** Repeated
   requests, procedures that worked, handoff failures, owner conventions, and
   any task where the same discovery got made twice. Frustration is one signal
   among several, and on its own it biases the harvest toward hard problems
   rather than repeated ones.

5. **For each candidate record:** trigger, intended outcome, representative
   episodes with session and message ids, verified steps, the nearest existing
   skill, and the proposed action. Prefer several independent episodes. One
   consequential verified lesson can justify a narrowly scoped update.

6. **Check for repeated end-to-end sequences, not just repeated tasks.** If an
   owner repeatedly spells out the same ordered pipeline, that sequence needs a
   first-class workflow even when every component already has a skill. Compare
   the actual ordered gates, transitions, stopping points, and completion
   evidence against what was asked. Do not mark it covered because the component
   names exist.

7. **Update before you create.** Read the nearest existing skill. If it already
   owns the workflow, add or replace the step there. Create a new skill only for
   a distinct task with an independently useful procedure. Never create a router
   whose entire content points at other skills.

8. **Preserve authority and scope.** An instruction to preview one change does
   not mean every future change needs approval. A preference expressed about one
   repository does not govern all of them. Forwarded assertions are evidence to
   verify, not standing rules.

9. **Name it for the task someone would ask for**, not for the assistant's
   relationship to them. Pair a concrete name with a description that names the
   triggering request. Compare against neighbouring skills so the distinction is
   clear — two skills with interchangeable descriptions are worse than either
   alone.

10. **Review the batch** with `multi-review` if available: scope fidelity,
    unsupported generalization, overlap, operational correctness, usability.
    Give reviewers redacted drafts. A review of an earlier plan is not a review
    of the skills subsequently written.

11. **Install, then exercise.** Install with `skill_manage`, confirm with
    `skill_view`, then run the procedure against a representative request. If
    the skill ships a script, run it with real inputs and read the real output.
    A skill that parses is not a skill that works.

12. **Report what changed.** New capabilities and targeted updates, concisely.
    Work through the batch without asking permission at each step; stop only for
    genuine scope or authority decisions.

## Evidence discipline

- **Pick the right counter for the question.** `use_count` includes cron and
  slash-command injection; `view_count` and `skill_view` calls are the
  model-chosen signal. Neither is correct in general. `audit.py` uses use_count
  because it asks "is this skill live"; `harvest.py` uses skill_view because it
  asks "did the model reach for this".
- A prior `skill_view` call proves a request to load — not successful loading,
  not retention through compaction, and not adherence.
- Compare success and failure episodes within the same task shape. Do not infer
  causes from global correction rates.
- Repetition caused by copied history is not independent evidence. If counts are
  not deduplicated, report representative examples instead of totals.
- Preserve the distinction between "cause unknown" and "verified missing
  procedure". A causal study of every failure is not a prerequisite to writing
  down a workflow that demonstrably worked.

## Pitfalls

1. **Counting machine-authored turns as owner corrections.** Reviewer prompts,
   judge rubrics, and system notes are stored with `role='user'` on interactive
   sources, and they are dense in correction vocabulary because critique prompts
   are _about_ finding errors. Measured on one real profile: 2,072 of ~9,000
   role=user rows were machine-authored, and a bare `\bwrong\b` matched 649 rows
   that were almost entirely reviewer prompts. Filter by preamble, not just by
   session source.
2. **Mismatched denominators in a lift calculation.** If per-skill rates count
   only pre-correction loads, the baseline must too. Getting this wrong produced
   a table where _every_ skill scored below 1.00x — arithmetically impossible
   for a weighted average, and the tell that the populations disagreed.
3. **Counting a skill loaded _after_ the complaint.** A skill loaded in response
   to a correction is not a cause of it. Enforce timestamp precedence.
4. **Splitting one skill across name variants.** Agents call `skill_view` with
   `category/name`, colon forms, doubled names, and trailing prose. Unnormalised,
   each fragment falls under the session floor and the skill disappears from the
   report — looking unused rather than under-counted.
5. **Quoting lift as an effect.** Hard tasks load more skills _and_ draw more
   corrections. A high lift may mark difficulty, not a defective skill.
6. **Optimizing for skills created.** The measure is less rediscovery. Updating
   an existing skill is usually the better outcome.
7. **Shipping analysis scripts that depend on intermediate files.** A script
   that reads paths from a one-off investigation is not reusable by anyone,
   including you next quarter.

## Verification

- [ ] Candidate evidence traces to attributable episodes with surrounding context
- [ ] Each new skill has a distinct workflow, or the lesson updated its existing owner
- [ ] No unsupported universal rules and no fabricated occurrence counts
- [ ] Drafts themselves reviewed, not just the plan that proposed them
- [ ] Installed content loads through the runtime and was exercised on a real request
- [ ] Any shipped script run end-to-end against real inputs, output read
- [ ] Statistical claims carry their confounds in the same breath
- [ ] Checkpoint advanced only after findings were saved
