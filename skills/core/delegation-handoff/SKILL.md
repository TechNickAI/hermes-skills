---
name: delegation-handoff
description: >
  Use when handing work to a background agent or subprocess, or when one comes
  back reporting success. Covers verifying the premise before dispatch, writing a
  brief the worker can finish inside its budget, and checking the artifact
  yourself afterward. Prevents acting on a self-reported success, since a worker
  claiming "uploaded" or "file written" is a claim, not evidence.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [delegation, subagent, orchestration, verification, background]
---

# Background Delegation Operations

How to dispatch fire-and-forget `delegate_task` subagents so the work actually lands.
Covers the parent's three jobs: **verify the premise before dispatch**, **write a brief the
child can finish inside its budget**, and **inspect artifacts and finish the last mile when
it can't**.

This is the orchestration discipline, not the implementation discipline. For the plan-execution
loop (fresh subagent per task, two-stage review), that lives in the bundled
`subagent-driven-development` skill.

## When to use

- The user says "do this with a background agent" / "don't clutter this thread."
- Any `delegate_task` dispatch that will run more than a couple of minutes.
- Any task phrased as "fix X" / "finish X" / "X is broken" where X's state is a _claim_
  rather than something you have measured.

---

## 1. Verify the premise BEFORE you dispatch

A brief is usually written from a one-line human summary or from a **previous session's
completion claim**. Both can be wrong. A subagent dispatched on a false premise will find a
way to "fix" something that isn't broken.

**Rule: spend 1–2 cheap read-only calls establishing ground truth first, then put the measured
facts into the brief flagged as "verified starting state — trust this."**

Two real examples from one session:

| Stated premise                                                        | Measured reality                                                                                                                                     | Cost of not checking                                                               |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| "Fix his missing API key"                                             | Key present in both shared and per-profile `.env`, byte-identical to canonical, live probe HTTP 200. Real cause was an unrelated per-turn guardrail. | Would have rotated a working credential fleet-wide and never found the real cause. |
| "All three traps are now written into the skill with tested snippets" | Live skill and repo copy were **byte-identical**, and neither mentioned any of the three traps. Nothing had ever landed.                             | Child would have hunted for a section to patch that did not exist.                 |

The second is the important class: **a prior session's completion claim is not evidence.**
When a task says "finish X" or "do X properly", diff the artifact before believing X exists.

```bash
# Cheapest possible premise check for "the skill already documents X"
diff -q "$LIVE/SKILL.md" "$REPO/skills/<name>/SKILL.md"
grep -n -iE 'term1|term2|term3' "$LIVE/SKILL.md"   # empty output = the claim was false
```

When the premise turns out false, **say so plainly to the user** and reframe the task ("this is
a first implementation, not a patch"). Do not quietly proceed as if the summary was right —
the user is relying on your report to know the true state.

Corollary: this applies to the child's own report too. **Child summaries are self-reports, not
verified facts.** A child claiming "pushed" or "file written" may be wrong. For anything with an
external side effect, demand a verifiable handle (URL, PR number, absolute path) and check it
yourself.

**Second corollary — verify load-bearing NEGATIVES, not just positives.** "X does not exist",
"zero records found", "it never worked" are the claims most likely to be artifacts of the
child's query rather than facts about the world, and they are the ones that send the user off
to fix a non-problem or issue a credential they do not need. Measured 2026-08-15: a child
reported a model route did not exist and required an operator config change; two follow-up
queries found 24 successful calls on that exact route within the retained window. The child had
searched one namespace (`combos`) for something that lived in another (a direct provider model).

Rule: **re-run the single query behind any negative that ends in "needs the user".** One or two
calls. When your check overturns the child, say so explicitly in the report rather than quietly
presenting the corrected answer — the user needs to know the delegated result was wrong, not
just what the right answer is.

---

## 2. Write a brief the child can finish

### Budget it

**The wall-clock budget is fixed before you dispatch and you cannot raise it per call.**
`delegate_task` has no timeout parameter — the only lever is process-wide
`delegation.child_timeout_seconds`. Upstream default is _no_ cap; a child dying at a round
number usually means a profile set that key. See
`references/subagent-timeout-mechanics.md` for the three separate clocks (hard cap,
heartbeat staleness → gateway timeout, `terminal.timeout` on headless one-shots), how to
tell them apart, and the zero-API-call diagnostic dump.

Two consequences: size the brief to the cap you actually have, and **make partial work
survivable** — instruct the child to append findings to a workspace file as it goes, because
a hard kill discards its summary entirely. A review child that finds a real bug and is then
killed takes the finding with it.

**Fanning work out to parallel seats/workers yourself? Capture each one's exit code.** A
harness that backgrounds each `timeout`, never `wait`s a PID, and judges results by
`wc -c` cannot tell a silently-killed worker from one that returned an empty answer — both
are 0 bytes on both streams, and the script exits 0 either way. Measured 2026-08-15: a
review panel declared two seats "dead" while router logs showed both models answering
correctly for the full run, killed by the panel's own budget. `wait` each PID individually,
write `$?` to a file, and treat `rc=124` as "timed out at Ns", never as a verdict on the
worker. Also verify which model/provider ACTUALLY served each seat rather than trusting the
alias you requested. Full classification table, the unenforceable-rule lesson, and the
minimum viable harness: `references/parallel-seat-harness-exit-codes.md`.

A brief with six numbered steps where steps 1–3 are open-ended research will burn the tool
budget before step 5. Children hit the iteration cap during the **last** steps — which are
exactly the ones that make work visible (`pre-commit`, `commit`, `push`, `gh pr create`).

- Front-load cheap shipping steps: tell the child to commit incrementally as each file is
  finished rather than saving all git work for the end. A commit is cheap and recoverable;
  losing the run's output is not.
- Split research and shipping into two dispatches when discovery is genuinely open-ended.
- Assume you may need to finish the last mile yourself and leave the tree in a resumable state.

### Required brief ingredients

- **Verified starting state**, flagged as measured, so the child doesn't re-derive it or trust
  a stale summary.
- **Executed evidence, not plausible output**: "run it and paste the real output; if a snippet
  does not work, fix the snippet, do not soften the doc."
- **An explicit honesty escape hatch**: "if you cannot find the original error text, say so —
  do not invent error strings you did not observe." A child with no way to report a gap will
  fabricate to look complete. This works: in a real run the child reported it could not recover
  an original broken source and did not fake it.
- **Project rules the child cannot inherit.** Subagents read their prompt and nothing else. For
  a public repo, restate the PII rule _inside the brief_ — an omitted rule means real paths and
  names land on a public branch.
- **Skill names to load.** The cheapest possible context injection; a subagent will not
  proactively `skills_list`.
- **Explicit stop conditions**: "open the PR and stop, do not merge", "do not send any messages",
  "do not modify the live copy."

---

## 3. Finish the last mile

The child returns `status=completed` with a report ending "work is written but not committed,
pushed, or opened as a PR." That is a **finishable state, not a failure.** Picking it up is
usually 3–4 calls.

### Post-delegation inspection — always run this

Never trust the self-report about external side effects. Look at the artifacts:

```bash
cd "$WORKDIR" || { echo "WORKDIR MISSING"; exit 1; }
git branch --show-current
git status --porcelain                     # ' M' = modified unstaged, '??' = new, never added
git diff --stat
git ls-files --others --exclude-standard   # files the child created but never staged
```

`??` on a file the child said it "added" means the file exists but was never committed.

### Then complete the sequence

```bash
git add <paths>
pre-commit run --all-files      # formatting hooks may REWRITE files
git status --porcelain          # 'MM' / 'AM' = hook reformatted AFTER you staged
git add -A <paths>              # re-stage post-hook changes
git commit -F - <<'MSG'
...
MSG
git push -u origin "$(git branch --show-current)"
gh pr create --title "..." --body-file - <<'BODY'
...
BODY
```

**Pitfall — re-scan after hooks run.** Formatting hooks rewrite files _after_ staging (status
flips to `MM`/`AM`). Any content scan you ran pre-hook — PII, secrets, placeholder substitution
— must be re-run against `git diff --cached` before committing.

**Pitfall — `pre-commit` exit codes.** Its per-hook summary lines and its overall exit status
are separate signals, and grepping output for "Failed" is unreliable. Check the process exit
code and confirm the tree is in the state you expect afterward.

**Pitfall — inline payload limits.** Very large one-liners or heredocs can be refused by the
command parser. Prefer `--body-file` / `-F -` with stdin, or write the file with the file tool
and reference it, rather than a giant inline string.

---

## 3b. Steer a child that is succeeding too slowly

A child burning its budget on work that is _correct but unbounded_ will not fail loudly —
it will exhaust its iteration cap during the shipping steps and hand back a partial
result. Watch the live transcript for the shape: repeated `process(wait ...)` on one
long-running command is the tell.

Before intervening, distinguish **stuck** from **slow**, because they need opposite
responses:

```sh
P=$(pgrep -f <child-harness-name> | head -1)
pgrep -P $P | while read c; do ps -o pid,etime,command -p $c | tail -1; done
```

A live child process with a fresh `etime` means the subject is slow, not hung — one
verification script in this session legitimately ran 11 minutes because it called live
market APIs. Killing that is wrong. What was right was noticing the child had already
gathered **sufficient evidence** (15 of 15 parity runs passed) and was spending the rest
of its budget re-proving the same thing on progressively slower jobs.

Steer on the evidence threshold, not the clock:

- Name what has already been proven and declare it sufficient.
- Say **stop doing X** explicitly; a child will not infer that thoroughness has become
  the problem.
- Re-issue the remaining steps in order, since the child is mid-plan.
- Prefer `--dry-run`/validation for anything slow or irreversible in the remainder.

**Also steer when YOU find a bug in a shared tool mid-run.** Children copied the tool at
dispatch time and will keep using the broken version. Tell them what changed, where to
re-copy it, how to repair artifacts already produced, and — critically — how to _prove_
the repair rather than assume it.

**A steer is a request, not a guarantee.** Steering text is appended to the child's next
tool result; a child near the end of its plan may never reach a delivery boundary, and the
harness reports that as `missed_steer`. Even a delivered steer may be applied partially.
After any mid-run correction, **re-verify the corrected property yourself across every
artifact the children produced** — do not infer it from the steer being sent. In this
session a launcher-environment fix was steered to three children mid-run; the parent still
had to sweep all 39 generated launchers and prove the fix with a hostile-value probe.
Cheapest form is a single idempotent sweep that reports "N need the fix, M already
correct", run after the batch completes.

**Budget the verification, not just the work.** A brief that says "verify every migrated
job by executing it" is unbounded when the estate contains jobs that call live external
APIs. Cap it: verify a representative sample by execution, validate the rest, and say so
in the report.

---

A background dispatch returns immediately and its completion notice re-enters the conversation
whenever it finishes. If you kept working — polling the output file, inspecting artifacts —
you will often have **already read and reported the result before the notice shows up**.

Observed repeatedly on 2026-08-15: three separate completion notices landed for runs whose
output had already been read off disk and summarized. Re-summarizing each one would have told
the user the same thing twice and made a completed task look unfinished.

**Rule: on receiving a completion notice, first ask whether you already reported this run.**

- If yes → say so in one line and do not re-summarize. Optionally use the notice as a prompt to
  verify something you could not confirm earlier.
- If no → read the **artifact**, not the notice body. Completion notices are truncated
  (`… (truncated; full output: <path>)`). The truncated body is not the result; the file is.
- Match on the run identifier, not on vibes — the notice carries the dispatch id and the output
  path, and a job may have several runs in flight or in quick succession.

Corollary: when a notice arrives for work whose surrounding config you edited **while the run
was in flight**, the run executed against the _old_ config. Do not credit the result to the
edit. Verify the deployed definition contains the change, then re-run. (See
`stop-the-noise/references/recurring-briefing-job-design.md` §5 for the
prompt-edit-races-a-test case.)

---

## 5. Reporting back to the user

The user delegated to keep the thread clean, so the report is the whole product.

- **Lead with anything that contradicts the premise.** If the stated problem wasn't the real
  problem, that is the headline, not a footnote.
- Give the **denominator** ("11 of 11 profiles verified", not "all clean").
- Quote **real observed output** for the load-bearing claims — literal error text, HTTP status,
  exit codes.
- Name the **honest gaps** explicitly: what could not be verified, what a child could not
  recover, what will drift until the user pulls or merges.
- State the **stop point** and what is waiting on the user (PR open, not merged; live copy
  unchanged).

## Pitfalls

**Treating a completion claim as done.** The single highest-value check in this skill. Diff the
artifact.

**Letting a child's "completed" status imply the side effect happened.** Status reflects the
child's loop ending, not a push landing.

**Re-dispatching instead of finishing.** When the child got 90% there and stalled on shipping,
finishing it yourself is faster and cheaper than a second full dispatch with fresh context.

**Dropping project rules from the brief.** Public-repo PII rules, approval gates, and "do not
send messages" constraints do not travel with the child. Restate them every time.

**Scanning for secrets/PII only once.** Hooks reformat after staging; scan again on the cached
diff.

**Re-summarizing a completion notice you already reported on.** The notice is a delivery
mechanism, not a new event. Reconcile against what you already told the user before writing
another summary of the same run.

**Relaying a child's negative finding without re-running the query behind it.** Positives get
scrutinized because they claim a side effect; negatives slide through because "nothing there"
feels like a safe default. It is not — a wrong negative is what makes the user rotate a working
credential or change routing that was fine.

**Reading `status=completed` as "the plan finished".** A child can complete by exhausting
its iteration budget mid-plan (`exit_reason=max_iterations`), having done the work but
skipped its own verification steps. When the summary is thorough about _doing_ and thin
about _proving_, re-verify the artifacts yourself rather than inheriting its confidence.

**Letting a child act outside the brief without flagging it.** One child in this session
fixed a genuine pre-existing fault (a symlink to a missing script) that was not part of
its task. The fix was correct and the report disclosed it — that is the acceptable shape.
An undisclosed out-of-scope change is not, so read the summary for actions you did not
ask for and confirm each one.

**Accepting a child's stop-on-misbehavior verdict without re-measuring.** A child
correctly instructed to stop on anomaly will stop on _its own measurement error_ too. Two
hosts were left unmigrated here because a child's 120s harness ceiling scored a 20s script
as `rc=1`. The stop was disciplined; the finding was wrong. Re-run the specific
measurement behind any stop before accepting the host as blocked.

**Blaming a timeout on the framework before checking local config.** "Subagents time out at
N seconds" is almost always a value the fleet wrote into `config.yaml`, not an upstream limit.
Read `_get_child_timeout` and grep every profile before telling the user it is inherent.

**Promising a caller a dynamic or per-task timeout.** The schema has no such field. If a job
needs a scope-scaled budget, it has to run as a headless one-shot with an explicit terminal
`timeout=`, or be split into smaller dispatches.
