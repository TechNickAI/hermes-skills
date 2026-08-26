---
name: check-upstream-first
description: >
  Use before debugging a framework or dependency bug from its source, and before
  writing any local patch. Establishes which install and version is actually
  running, then searches the project's issue tracker and release notes for an
  existing fix. Prevents the common waste of hand-patching a source tree that
  nothing executes, or shipping a fix for a bug that was resolved weeks ago.
version: 1.4.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags:
      [
        hermes,
        upstream,
        github,
        triage,
        gateway,
        telegram,
        slack,
        version,
        patch,
      ]
---

# Upstream Fix Before Local Patch

## Overview

A recurring, expensive failure mode: a framework symptom gets diagnosed from
source, a patch gets designed, and the effort is wasted because the bug was
**already fixed upstream** and the member is simply running an old release.

The inverse waste also happens: an agent hand-edits a source tree that **nothing
is running**, then reports the fix as applied.

**Order of operations is the whole skill:**

1. Attribute the RUNNING process to a real install path.
   🔴 **And before calling any member's install method a "regression", measure
   parity across ≥3 members.** A box differing from your memory is a hypothesis,
   not evidence. Twice in one session a member was wrongly reported as drifted
   when it was in fact the fleet standard (and the "fix" would have downgraded
   it). Corroborate with: does the running version even EXIST on PyPI? If not,
   pip cannot be the standard. Measure the install method on at least three
   machines before calling any single one a regression: one box differing from
   your memory is a hypothesis, not evidence.
2. Get the exact version + the latest upstream release.
3. Search upstream issues/PRs for the symptom.
   **Search OPEN PRs too, not just issues** — feature-gap prior art lives in PRs
   more often than issues, and an open-but-`dirty` PR may already contain your
   exact fix while being functionally abandoned. Check `mergeable_state`, age,
   and review-comment count before assuming a fix is inbound. See
   `references/reading-current-main-and-stalled-prs.md`.
4. Only if genuinely unfixed upstream — design a patch.

🔴 **Step 3 has a decisive sub-step: prove what is ACTUALLY upstream.** In a fork
clone, `origin/<branch>` is YOUR FORK's mirror and already contains your own
commits, so diffing against it reports "already upstream, nothing to PR" for
every local fix you hold. `git cherry` / patch-id is likewise unreliable after a
rebase — in one 2026-08-16 session it reported ALL FOUR local commits as already
upstream, including one whose buggy line was still sitting in the upstream file.
Answer the question with FILE CONTENT against a verified `upstream` remote:
`references/determining-what-is-actually-upstream.md`. Getting this wrong in the
"already fixed" direction talks the captain OUT of a real contribution — which is
what happened before the remote was re-checked.

**And step 5, which is where a real failure happened:** a local patch has a
CUSTODY obligation. Branch (never `main`), push the same session, record an exit
plan. Local commits abandoned on an editable checkout are unbacked, unreviewed
production code — see `references/local-patch-custody.md`.
🔴 **Never `git push -q`, and never believe exit 0.** A scratch clone made with
`git clone --shared <local-path>` inherits that PATH as `origin`, so a "successful"
push can land in a local repo and CI then fails with `upload-pack: not our ref`.
Assert with `git ls-remote <remote-url> refs/heads/<branch>`. Also covers the
`workflow`-scope rejection that fires when a rebase merely carried upstream
workflow commits into your push range (fix: `git bundle` the objects to a
scoped credential, never loosen creds on the host), and how to drop an
add/delete commit pair from a DEPLOYED branch while proving the no-op by
comparing TREE HASHES: `references/push-custody-and-history-rewrite.md`.

**Step 6, when the patch must run on a fleet:** base the branch on the RELEASE
TAG, not `main`, give every patch a written removal condition, and verify disk /
lineage / process / config as independent layers. See
`references/pinned-release-fork-model.md`.

**Step 7, before deploying a patch that DELETES or mutates user-visible data:**
run the deletion-safety pass in
`references/deletion-safety-in-message-pipelines.md`. A cleanup patch that is
correct in the common case can still erase the only copy of a user's content in
the edge case.

Cost of steps 1–3 is a couple of minutes. Cost of skipping them is a wasted
patch, wrong advice to the captain, and lost credibility.

🔴 **Before MERGING a PR that carries review comments, adjudicate them — green
checks plus outstanding comments is not a merge signal.** A branch that
refactored mid-review strands comments against deleted files (3 of 7 on one
2026-08-21 PR named modules that no longer existed), so pull the file list at
HEAD first and set those aside. Verify every surviving finding by EXECUTING the
input it describes, not by reading the diff; assert on the output string. Report
any finding that does not reproduce as such rather than accepting a false premise
or silently dropping it, and always run the negative control so you know the
check still fires. Clean `__pycache__` before trusting a repo's own PII/secret
scanner — a `.pyc` freezes the absolute build path and reads as a leak. See
`references/verifying-bot-findings-before-merge.md`.

## Prior art before build

The same waste has a second, larger shape: **designing a system that already
exists.** The operator's phrasing for this is blunt — _"Look at prior art on this.
What have we already built. Did you do a deep dive on what others have built?"_ —
and it usually arrives after a full design has been written.

Run BOTH sweeps before writing an architecture, in this order:

**1. What have WE already built?** Cheapest and most often skipped.

```bash
# own skills / config repos
ls ~/src/hermes-config/skills/ && ls ~/src/hermes-config/devops/
# the target host's own scripts and jobs — a monitoring system may already exist
ssh <host> 'ls -la ~/.hermes/scripts/*.py'
# framework internals: the capability may be core telemetry, not new code
ls ~/.hermes/hermes-agent/agent/monitoring/
grep -rn "<capability>" ~/.hermes/hermes-agent/agent/ --include=*.py -l
```

A single session found: an existing skill implementing the exact cheap-triage /
expensive-remediation tier being proposed, framework code already computing the
"job never ran" detection about to be hand-written, and a host script already
probing the user-facing paths. The correct output was _extend these_, not _build_.

**2. What has the FIELD already built?** Delegate a research pass with web tools
and ask specifically for measured results and named anti-patterns, not vendor
claims. Ask: what exists commercially, what exists open-source, **what has been
documented to fail**, what patterns the industry converged on, and what applies at
your scale. Insist on numbers with denominators; most vendor MTTR figures have none.

This routinely inverts a design. Published benchmarks turned an "agent fixes
problems" architecture into "agent diagnoses and proposes, auto-fix limited to a
rehearsed reversible set," and killed a planned statistical-baselining component
outright as counterproductive below ~5 machines.

**Report the sweep even when it shrinks your plan.** "Substantially less new code
than I wrote up" is a good outcome. Silently rebuilding existing work is not.

🔴 **Do not let one reviewer's line drive an architecture.** In the same session a
single review comment ("the LLM must never be the sensor") was over-applied into
removing the LLM entirely, discarding the judgment layer that was the entire point.
The owner's correction was that hallucination was never the concern, and that a
pure-Python rewrite was explicitly not wanted. Weigh review findings against the
owner's stated intent; a reviewer optimizes their lens, not your goal.

## When to Use

- **Before designing ANY new system, tool, or monitor** — not just before patching
  a bug. Search your own repos and the framework's source for the capability first.
  See "Prior art before build" below.
- Any gateway/platform transport fault on a fleet member (delivery failures,
  reconnect loops, adapter errors, duplicated or dropped messages).
- Before writing ANY local source patch to `hermes-agent`.
- When someone (including another fleet agent) reports "I patched X" — verify it
  landed somewhere live.
- When about to say "this is a framework bug, we should open a PR."

## Step 1 — Attribute the running process to a real install path

Do not analyze a source tree until you have proven the gateway runs from it.

```bash
ps aux | grep "gateway run" | grep -v grep      # read the argv path
lsof -p <PID> | grep -o "/Users/<u>/[^ ]*site-packages" | sort -u
```

**An editable git checkout inverts the usual answer — check for it before
assuming a checkout is inert.** With `pip install -e`, `site-packages` holds only
a `__editable__*.pth` finder and imports resolve straight into the working tree:

```bash
ls venv/lib/python*/site-packages/ | grep -E '__editable__|\.egg-link'
# then prove where imports actually land (PATH-shim to dodge the null-byte guard):
export PATH="$PWD/venv/bin:$PATH"
python -c "import gateway,hermes_cli; print(gateway.__file__, hermes_cli.__file__)"
```

If those print paths inside the checkout, **editing a file there IS deploying
it** — only a gateway restart is needed, no reinstall or copy step. Note the
argv may show a _system_ python (Homebrew) while the launchd/systemd unit
actually invokes the venv interpreter; read the unit, and trust the resolved
`__file__`, not the process name.

Before proposing any local patch to such a tree, capture three facts:

```bash
git status --porcelain | wc -l                              # uncommitted work
git log origin/main..HEAD --format='%h %an %ad %s'          # UNPUSHED commits
git fetch origin main -q
git rev-list --left-right --count origin/main...HEAD        # behind / ahead
```

Local commits that exist nowhere else change the recommendation: any
"just pull main" plan must preserve them, and they are one `rm -rf` from gone —
say so. A large `behind` count means "upgrade first" is a fleet project, not a
prerequisite for a small fix. Run the same three checks across every host before
generalizing; fleets drift (one host may have no checkout at all, which cannot
take a source patch and needs a different path entirely).

A stale `~/.h‍ermes/h‍ermes-agent` git checkout frequently coexists with the real
uv/pip package install, or is referenced in old notes after being deleted.

### Release-dir / symlink deploys: the deployed SHA is not checkout HEAD

The editable-checkout case above inverts one way; a **release-directory deploy
inverts the other way**, and it is the one that produced a wrong answer to the
captain on 2026-08-16. When a service runs from `releases/<build>` chosen by a
`current` symlink, the git checkout is a _build input_, not the running code —
and it can sit weeks behind while the deployed build is nearly current.

```bash
ls -l <app>/current                      # -> releases/standalone-<sha>
basename "$(readlink <app>/current)"     # the DEPLOYED build id
git log -1 --format='%h %ci %s' <sha>    # prove that sha is a real commit we have
git rev-list --left-right --count <sha>...upstream/release/vX.Y.Z   # ahead<TAB>behind
```

**What went wrong:** I reported "we are 1,131 commits behind upstream" after
reading `git log -1` in `~/src/the router` (HEAD three weeks old, parked on branch
`the operator/upgrade-v3.8.49-plus-fork`). The deployed build was **136 behind / 8
ahead**. the operator caught it: _"Is this really true? ... I think we just bumped
everything."_ The bug under investigation was real either way, but the version
claim — the thing that decides _upgrade vs patch_ — was off by ~1,000 commits.

Rules that follow:

- **Resolve the symlink before quoting any drift number.** A checkout HEAD date is
  not a deployment fact. If the release carries no build sentinel (`BUILD_SHA`,
  a `buildSha` health field), say so — its absence is _why_ the checkout looks
  authoritative, and it is worth fixing so the question is answerable at runtime.
- **Use `--left-right --count` (three dots), not a one-way count.** A fork is
  usually behind _and_ ahead; reporting only "behind" hides the fork deltas that
  determine whether an upstream PR will conflict.
- **Check whether the missing commits touch the file at issue** before claiming an
  upgrade would help:
  ```bash
  git log <deployed-sha>..upstream/release/vX.Y.Z --oneline -- <path/to/file.ts>
  ```
  Empty output means _upgrading does not fix this_ — decisive for "patch vs
  upgrade," and cheap.
- **Check whether YOUR fork touches it too.** If the fork's ahead-commits never
  touch the file, it is pure upstream in your tree: a clean upstream PR with no
  rebase conflict. That is a stronger argument for going upstream than any
  generic preference.
- A stale checkout that anyone would naively read to answer "what are we running"
  is itself a hazard worth flagging to the captain, separately from the fix.

### Incomplete bug-class fixes: grep for the sibling call site

When you find a unit/format bug, **check whether the same bug was already fixed
elsewhere in the same file** — an accepted fix on a sibling is the strongest
possible argument for your PR, and its absence on your line is often the whole
story.

```bash
grep -nE "Date\.now\(\)" <file>        # cheap: find every cutoff computation
```

Live example (the router, 2026-08-16): `cleanupCompressionRunTelemetry` compared
millisecond-stamped rows against a **seconds** cutoff, so its retention sweep
deleted nothing, forever — and it exists specifically to bound storage and
prevent OOM. Thirty lines earlier, `cleanupDomainCostHistory` had the _identical_
bug, already fixed by upstream `#9625` with an explanatory comment. #9625's
repro test covered only its own table. Right diagnosis, one call site, sibling
missed. The docstring on the unfixed function still asserted the wrong contract
("Uses unix-epoch `timestamp`"), which is probably how it survived.

Cite the precedent commit in the PR — it reduces the review to "you missed one."

🔴 **Expect the EXISTING TEST SUITE to encode the bug.** After fixing the code,
the original feature's own test suite went 6/6 → 4/6. The failures were correct:
the test seeded the table in **seconds** while production wrote **milliseconds**,
so it had been asserting the buggy behavior all along — which is exactly how the
bug survived a suite written to cover it. The sibling's fix had even updated the
neighbouring line in that same test file and left this one alone: the incomplete
fix extended into the tests too. When a green test starts failing after your fix,
read its FIXTURE before assuming your change is wrong.

Full method — hunting siblings deliberately, the mandatory both-directions
control run (a repro test that passes on broken AND fixed code proves nothing),
the "control failed for the wrong reason" trap, seeding through the real writer,
and separating pre-existing baseline failures from your own:
`references/sibling-call-site-bug-classes.md`.

🔴 **The same stale checkout also poisons READING, not just patching.** Concluding
"this is still broken on main" from a local tree that is a week behind is an
unforced error on a repo merging ~1,400 PRs per release. Before any claim about
upstream state, diff the dates:

```bash
cd ~/.h‍ermes/h‍ermes-agent && git log -1 --format='%h %ci'
gh api repos/NousResearch/h‍ermes-agent/commits/main --jq '.sha[0:10] + "  " + .commit.committer.date'
```

If they differ, re-fetch the decisive file from `main` before forming a verdict.
Recipes, large-file gotchas, and the stalled-PR diagnostic are in
`references/reading-current-main-and-stalled-prs.md`.

**Live example (an assistant agent, 2026-07-30):** an agent hand-patched `telegram.py` in
the git checkout — 48 lines plus a test — while the gateway ran entirely from
`~/.local/share/uv/tools/hermes-agent/...`. The patch was **never live**. A
separate "you are 2,149 commits behind" analysis was computed against that same
tree, which nothing executed and which had in fact been removed.

Tracebacks in `gateway.error.log` name the real path — read them:

```
File ".../uv/tools/hermes-agent/lib/python3.11/site-packages/slack_sdk/socket_mode/aiohttp/__init__.py"
```

Also note: `hermes --version` can report `Install method: git` even on a pure uv
tool install. Do not use that field to determine install method.

## Step 2 — Version vs latest release

```bash
uv tool list                       # authoritative for uv installs
hermes --version
ls ~/.cache/uv/archive-v0          # shows upgrade HISTORY; a version never
                                   # fetched was never installed
gh api "repos/NousResearch/hermes-agent/releases/latest" --jq '{tag:.tag_name,published:.published_at}'
```

If the member is behind, the remaining steps usually resolve to "upgrade", not
"patch".

**Sweep for the drift that hides this** — exact-version pins (which make
`uv tool upgrade` a silent no-op), dead git checkouts, stale service
definitions, and shadowing user plugins. Check each of these read-only on every
machine you believe is current:

```bash
uv tool list                       # is the install exact-version pinned?
readlink -f "$(command -v <tool>)" # is the binary the one you think it is?
```

Run it after any rollout, and whenever a "I thought we upgraded that box"
discrepancy appears.

## Step 2b — Evaluating a thin ROLLUP release ("should we update?")

Some tags ship deliberately contentless notes. v2026.7.30 (v0.19.1) reads:

> Patch release... **Full curated release notes for this window will ship with
> v0.20.0** ... ~2,789 commits · ~4,748 files changed

A commit count is not a reason to upgrade. "Should we update?" is answerable only
by checking whether the release fixes something **we actually hit**. Two moves:

**1. Read commits touching the files you care about, not the notes.**

```bash
gh api "repos/NousResearch/hermes-agent/commits?sha=<tag>&path=hermes_cli/model_switch.py&since=<prev-release-date>&per_page=100" \
  -q '.[] | .commit.message | split("\n")[0]'
```

**2. Verify YOUR open gaps against the tag's source — don't infer from the log.**

```bash
gh api repos/NousResearch/hermes-agent/contents/<file>?ref=<tag> -q '.content' | base64 -d > /tmp/new.py
grep -n "<symbol>" /tmp/new.py
```

Worked example (2026-08-03): checked whether the two picker gaps were fixed at
v2026.7.30. `_KNOWN_KEYS` still had 22 keys with `enabled` absent, and
`include_moa=True` was still hardcoded at the `/model` call site. **Upgrading
would have bought back nothing** from that session's work — so the honest answer
was "don't upgrade for features; write the PR." Checking took ~2 minutes and
prevented recommending a fleet-wide upgrade on vibes.

**Report shape the operator wants:** what's in it _for us_, what it does NOT fix, and the
risk. Not a changelog paraphrase.

## Step 2c — Read the INSTALL SPEC before recommending any upgrade

`hermes --version` does not tell you how the tool will resolve on reinstall. Read
the receipt:

```bash
grep requirements ~/.local/share/uv/tools/hermes-agent/uv-receipt.toml
```

Live finding (2026-08-03), the operations agent's Studio install:

```toml
requirements = [{ name = "hermes-agent", extras = ["mcp"], git = "https://github.com/NousResearch/hermes-agent.git" }]
```

Installed **from git**, with **only the `mcp` extra**. But `python-telegram-bot`
is declared solely under the `messaging` / `termux` / `slack` extras:

```bash
grep -E "^Requires-Dist: (python-telegram-bot|slack|discord)" \
  <site-packages>/hermes_agent-<ver>.dist-info/METADATA
```

So telegram was present **incidentally**, not because the install spec asked for
it — nothing guarantees it survives a reinstall. That is the
drop-messaging-extras outage in latent form (see
`references/uv-tool-pin-and-extras-traps.md`), and it makes "just run
`hermes update`" an unsafe recommendation on that box.

**Rule: before proposing an upgrade, diff the declared extras against the libs
the running gateways actually need.** A `Provides-Extra:`/`Requires-Dist:` read
is cheap; a fleet-wide Telegram outage is not. Recommend pinning extras
explicitly (`hermes-agent[messaging,mcp,...]@latest`), canary one host — a personal-assistant agent is
the designated canary — verify the platform libs on disk BEFORE restarting, then
fan out.

```bash
gh search issues --repo NousResearch/hermes-agent "flood control" --limit 15
gh search issues --repo NousResearch/hermes-agent "slack socket mode disconnect" --limit 10
gh api "repos/NousResearch/hermes-agent/issues/<n>" \
  --jq '{n:.number,state:.state,reason:.state_reason,title:.title,body:(.body[:1200])}'
gh api "repos/NousResearch/hermes-agent/issues/<n>/timeline" \
  --jq '.[] | select(.event=="cross-referenced" or .event=="referenced")
        | {ev:.event, sha:(.commit_id // null), src:(.source.issue.number // null), t:(.source.issue.title // null)}'
```

The **timeline** call is what surfaces the fixing PR. Then confirm it actually
merged — a cross-referenced PR may still be open while a _different_, rebased PR
carries the merge:

```bash
gh api "repos/NousResearch/hermes-agent/pulls/<n>" --jq '{state:.state,merged:.merged,merged_at:.merged_at}'
```

⚠️ **If `gh issue view` / `gh pr view` fails on this repo** with
`GraphQL: Projects (classic) is being deprecated ... (repository.issue.projectCards)`,
fall back to `gh api repos/.../issues/<n>` with `--jq` — it dodges the deprecated
field. Do not conclude the issue doesn't exist from a `gh ... view` failure.

This failure is **intermittent, not permanent** — as of 2026-08-01 both
`gh issue view --json` and `gh pr view --json` worked normally against this repo,
and `gh search issues --json number,title,state,createdAt` is a fast way to sweep
a symptom across many issues at once. Try the ergonomic command first; only fall
back to `gh api` when it actually errors.

Two worked cases with full log signatures, mechanisms, and the exact issue/PR
numbers: `references/messaging-transport-fault-triage.md`.

A third worked case — **Telegram MEDIA: attachment delivery** — demonstrates
the CLOSED ≠ FIXED trap at scale: five issues closed, five PRs opened, only
ONE merged (#34022), the rest closed unmerged while the issues were marked
resolved. The fix that shipped changed the validation model (denylist +
extensionless fallback) rather than adding extensions to a list. Full pipeline
anatomy (extraction → validation → dispatch), the `MEDIA_DELIVERY_EXTS` list,
the denylist, the sending contract, and every issue/PR number:
`references/chat-media-attachment-pipeline.md`.

## Step 3b — Prove the code path you're patching is actually CONSUMED

Steps 1–2 catch a patch in a tree nothing runs. This catches the subtler twin:
a patch in the **live** tree that still changes no behavior, because the value
it sets is computed and then never read.

Framework code accumulates fields that look load-bearing and are decorative.
Before designing any patch, trace the value from where it's produced to where it
is actually consumed:

```bash
grep -rn "<the_field_you_would_set>" agent/ --include=*.py
```

**If the only hits are the assignment and a debug/log line, the field is inert.**

Live example (2026-07-31). `agent/error_classifier.py` computes a rich
`ClassifiedError` with `retryable` / `should_compress` /
`should_rotate_credential` / `should_fallback`. I was one command away from
adding a status-code entry setting `should_fallback=True`, and would have
reported it shipped. The grep:

```
conversation_loop.py:2762:   ... classified.should_fallback,     # debug log ONLY
```

The actual failover decision, ~600 lines later, never consults it:

```python
_should_fallback = (is_rate_limited or (_is_transport_failure and retry_count >= 2))
# _is_transport_failure = {timeout, overloaded}
```

So every `should_fallback=True` the classifier produces — including for 401/403,
which an in-file comment claims triggers fallback — is decorative. A new
classifier entry compiles, classifies correctly, tests green, and does nothing.

**Why this matters beyond the one bug:** the honest fix (add the flag to the
disjunction) is no longer a targeted one-liner — it widens fallback for _every_
class carrying the flag simultaneously. Discovering that BEFORE writing the
patch changes both the risk assessment and who needs to approve it.

**Rule: a one-line fix that "obviously" works is exactly the shape that ships
inert.** Trace producer → consumer before promising it, not after.

**The twin failure — a value with MANY consumers.** Step 3b catches a flag that
nothing reads. The mirror case is a predicate that _several_ behaviors read, where
"just delete the offending clause" is a genuine one-liner that silently changes
two unrelated behaviors. Enumerate every consumer before editing any shared
classifier:

```bash
grep -rn "<predicateName>" --include=*.ts src/ open-sse/ | grep -v node_modules
```

Live example (the router, 2026-08-01): `isStreamReadinessFailureErrorBody()` fed
the circuit-breaker gate, a transient-retry decision, AND a round-robin semaphore
cooldown. Deleting `|| code === "STREAM_EARLY_EOF"` would have changed the retry
behavior the operator had explicitly asked to preserve two messages earlier. The safe
shape is a narrow new predicate plus an **optional** argument, so omitting it
reproduces prior behavior exactly.

Full method — enumerating consumers via the _variable_ not just the predicate name,
the additive-optional-arg shape, finding existing precedent in the same function, and
proving RED against unmodified upstream:
`references/narrowing-a-shared-predicate-safely.md`.

## Step 3d — A missing CAPABILITY is a tracker question, not a code question

Steps 3b/3c cover a broken thing. This covers a thing that _isn't there_, where
the failure mode is different: you read one code path, correctly conclude the
feature is absent, and then design an architecture around getting it added — or
around a workaround — without ever learning that upstream **deliberately refuses
it** and already documents a supported alternative.

**Code tells you what IS. The tracker tells you what is INTENDED. The docs tell
you what is SUPPORTED INSTEAD. Read all three before proposing an architecture.**

Live example (2026-08-22). `delegate_task` ignores a per-task `model` field.
Reading `tools/delegate_tool.py` proved it in two minutes: `creds` is resolved
once from `delegation.provider`/`delegation.model` and applied to every child in
the batch loop. Accurate — and nearly worthless on its own. The tracker showed:

- **five** PRs adding it: #17718, #23266, #25026, #34773, #36790
- an issue (#17685) with users reporting the field is _silently accepted and
  discarded_ — "our skill's entire model-assignment table is decorative"
- the maintainer closing #34773 with **"We do not want this"**
- the official docs stating the pin is global and naming the supported
  alternative outright: _"or hand the task to the kanban board, which does
  support a per-task model override"_

That reframes everything. It is not a gap to be patched or PR'd; it is a design
decision. Any plan premised on it landing is dead on arrival, and the honest
recommendation is the documented alternative — or, when that genuinely doesn't
fit the requirement, an isolated workaround owned by us.

```bash
# feature-gap prior art lives in PRs far more often than issues
gh search prs --repo <owner>/<repo> "<capability phrase>" --limit 20 \
  --json number,title,state,closedAt
# then read the CLOSING COMMENT on the most recent one — that is where the
# maintainer's actual position is, and it never appears in the code
gh api repos/<owner>/<repo>/issues/<n>/comments --jq '.[-3:] | .[] | .body[0:400]'
```

🔴 **Corollary: check whether a stale hierarchy in our own docs points at the
refused capability.** The `multi-review` skill ranked "native subagents with
per-task model override" as its **#1** execution path. Because that option has
never existed, the hierarchy silently fell through to #2 every single time — and
#2 was the unisolated path that corrupted a production database. A recommendation
whose first choice is impossible is not merely aspirational; it is a routing bug
that sends every reader to the fallback. When you confirm a capability is refused,
grep our own skills for guidance that assumes it.

🔴 **Do not answer a fan-out requirement with a broadcast feature.** The
appealing near-miss here was MoA, which is literally "ask N models and
synthesize." It cannot vary the _prompt_ per model, and the requirement was
different instructions per seat ("Grok, be critical" / "Claude, be empathetic").
Before offering an existing feature as the replacement, check it varies the
dimension the user actually named.

## Step 5 — If it IS unfixed: authoring the contribution

the operator's required order is **not** "open a PR." It is: build + clean checks +
multi-review → merge to our fork → run in OUR production → verify ~a day →
_then_ upstream PR.

Full playbook — choosing the base branch (upstream `main` is often parked; work
lands on `release/vX.Y.Z`), proving RED against unmodified upstream, test-file
shape, separating pre-existing CI failures from your own, commenting on a sibling
issue, and the anti-AI-slop wording rules — is in
`references/authoring-the-upstream-contribution.md`.

After upgrading and restarting, `tail`ing the error log shows **pre-restart**
lines and reads like the bug survived. Filter strictly by timestamps after the
restart minute before concluding anything:

```bash
awk '/^2026-07-30 10:(1[89]|[2-9][0-9])/' gateway.log | grep -c "Socket Mode unhealthy"
```

Healthy startup proves the platforms actually came up:

```
✓ telegram connected
[Slack] Authenticated as @<bot> in workspace <name>
[Slack] Socket Mode connected (1 workspace(s))
✓ slack connected
Gateway running with 2 platform(s)
```

## Step 3c — CLOSED ≠ FIXED. Verify against the INSTALLED source.

The most misleading upstream state is a bug with **multiple closed issues and no
merged fix**. Closed carries no guarantee: maintainers close as stale, duplicate,
or "superseded by #X" where #X also never landed. Issue count is a decoy —
three closed issues describing the same bug is evidence the bug is _real and
recurring_, not that it's solved.

**The only authoritative check is grepping the code the member actually runs.**

```bash
# 1. What version is live?
<venv>/bin/python -c "import importlib.metadata as m; print(m.version('hermes-agent'))"
# 2. Is that the latest? (PyPI, not training data)
python3 -c "import urllib.request,json;print(json.load(urllib.request.urlopen('https://pypi.org/pypi/hermes-agent/json'))['info']['version'])"
# 3. Does the fix exist in the INSTALLED file?
grep -nE "_reaper|_reap_idle|idle_timeout" <venv>/lib/python3.11/site-packages/agent/lsp/manager.py
```

If the fix symbols are absent from the installed source at the latest version,
**the bug ships today** — regardless of how many issues are closed.

Confirm the fixing PR's merge state explicitly; `CLOSED` with `merged=NEVER` is
the signature of a fix that was proposed and abandoned:

```bash
gh pr view <n> --repo NousResearch/hermes-agent \
  --json state,mergedAt -q '"state=" + .state + " merged=" + (.mergedAt // "NEVER")'
```

**Live example (a trading agent, 2026-08-01).** 24 orphaned `pyright-langserver`
processes, 2.1 GB RSS, oldest alive 21.7h. Three issues — #25016, #36681, #47314
— all CLOSED, all describing the same root cause precisely:
`agent/lsp/manager.py` defines `DEFAULT_IDLE_TIMEOUT = 600` and tracks
`_last_used`, but **no reaper task ever reads them**; `create_from_config()`
never reads `idle_timeout` from config. The fix PR #36684 was `CLOSED`,
`merged=NEVER`. Grepping installed 0.19.0 (the current PyPI latest) confirmed
zero `_reaper`/`_reap_idle` symbols. Closed issues, unfixed bug, still shipping.

**Corollary — don't propose the config knob without checking it's wired.**
Setting `lsp.idle_timeout` looks like the cheap fix, but issue #47314 states
`create_from_config()` never reads it. This is Step 3b (producer → consumer) in
config form: a config key that nothing consumes is inert. Verify before
recommending it, and say so honestly when it won't work.

When the operator rules out a remedy, the ruling holds — find a different fix, don't
re-propose the rejected one in new clothes.

- **"I don't want streaming off. Try again."** Disabling
  `ui.platforms.telegram.streaming` suppresses flood-control symptoms but was
  explicitly rejected. The supported answer was the upstream `retry_after` fix —
  take the version, keep streaming on.
- He also previously rejected tuning `streaming.buffer_threshold` as "cute but
  not what's going on." **Tuning an adjacent knob is not the same as finding root
  cause**, and presenting it as "the fix" costs credibility.
- When he says "a restart isn't what this is," believe it and look further. A
  restart on a poisoned Slack session genuinely does not fix it — it re-poisons
  within a day.

Related: when he supplies a correcting hint ("note the git checkout install vs
pip install", "are you sure you're looking in the right place?"), treat it as a
pointer to a real blind spot and re-verify from scratch rather than defending the
earlier finding. Both hints in the source session were correct.

## Local patches on someone else's box are debt, not a fix

⚠️ **Check `~/.hermes/plugins/` before concluding where a patch lives.** Platform
adapters are frequently **user plugins** (e.g.
`~/.hermes/plugins/platforms/telegram/adapter.py`), not package code. A patch
there is the one kind that DOES survive upgrades — and therefore permanently
shadows every future upstream fix to that adapter. Search both roots:

```bash
find ~/.local/share/uv/tools/hermes-agent ~/.hermes/plugins \
     -maxdepth 6 -iname "adapter.py" -path "*telegram*" 2>/dev/null
```

The log module namespace tells you which copy is live
(`hermes_plugins.platforms__telegram.adapter` = user plugin).

**Before promising a config-only replacement for custom code, verify the key
exists upstream and moves the gate in the direction you need:**

```bash
gh api "search/code?q=<config_key>+repo:NousResearch/hermes-agent" --jq '.total_count'
# 0 → local invention, not a supported setting. Say "there is no config-only
#     equivalent" rather than substituting a knob that only rhymes.
```

Names mislead: `mention_patterns` **widens** triggering and cannot narrow it;
`exclusive_bot_mentions` acts on a different axis entirely. Read the call site.
Full worked detail: `references/user-plugin-shadowing-and-config-only-limits.md`.

If a local source patch is genuinely warranted:

- It is **uncommitted debt on a keep-stable box**, reconciled on every upgrade.
- Reject new `HERMES_*` env vars for non-secret config — the repo rubric
  (`AGENTS.md`) says behavioral settings go in `config.yaml`.
- Prefer an upstream PR so the whole fleet gets it through a normal upgrade.
- Never make a local patch "live" by restarting an owner's box without the operator's go.

## Pitfalls

- **Analyzing a tree nothing runs.** Always Step 1 first. `cd` into a checkout
  succeeding is not proof it's the live code.
- **Quoting a drift number from checkout HEAD on a symlink deploy.** The mirror
  of the above, and it produces a _confidently wrong_ version claim rather than an
  obviously wrong one. Resolve `current` → `releases/<sha>` and count from that
  sha, with `--left-right --count`. Off-by-1000-commits was the real 2026-08-16
  result; it flips the upgrade-vs-patch recommendation. Then check whether the
  missing commits touch the file at all before claiming an upgrade helps.
- **Fixing a unit/format bug without grepping for its siblings.** The same bug
  usually exists more than once, and one instance is often already fixed with a
  comment you can cite. `grep -nE "Date\.now\(\)" <file>` costs nothing and turns
  a PR into "you missed one."
- **Patching a live tree at an inert call site.** The twin of the above: the
  code runs, but the field you set is never read at the decision point. Grep
  producer → consumer first (Step 3b). A "one-line fix" is the highest-risk
  shape for this.
- **Concluding "already fixed" from a closed issue alone.** Confirm the merge and
  that the fix is in a release the member actually has.
- **Treating CLOSED as FIXED.** The highest-confidence trap in this skill.
  Multiple closed issues on one symptom often means the bug is real, recurring,
  and _unfixed_ — the fix PR was closed unmerged. Grep the INSTALLED source for
  the fix symbols; that is the only authoritative answer. See Step 3c.
- **Recommending a config key that exists in docs/issues but is never read.**
  `lsp.idle_timeout` is the worked example — declared, tracked, never consumed.
  Verify the consumer before offering it as the cheap fix.
- **`tail` after restart showing old lines** → false "still broken" verdict.
  Filter by timestamp.
- **Reporting a fix as verified because a command exited 0.** Run the verify
  step; confirm the symptom is gone.
- **Stopping at the first plausible cause.** One user-visible symptom
  ("duplicated/sloppy output") had three independent root causes upstream. Name
  them as separate bugs and verify each with live evidence.
- **Upgrading without checking dependency extras.** A package reinstall can drop
  the messaging platform libs; restarting then takes the member fully offline.
  See `references/uv-tool-pin-and-extras-traps.md`.
- **Proposing a config key that doesn't exist upstream, or one that moves the
  gate the wrong way.** Verify with `gh api search/code` and read the call site.
  Fabricating a capability to satisfy "do it with config only" is worse than
  reporting the honest limit. See
  `references/user-plugin-shadowing-and-config-only-limits.md`.
- **Assuming a patch is dead because it's outside the package.** A `~/.h‍ermes/plugins/`
  patch is very much live and survives upgrades — the opposite of a dead git-checkout
  patch. Determine which case you're in before saying "that never applied."
- **Assuming a shipped feature covers every path it names.** A feature can be
  merged, documented, closed as "implemented", and enabled in config — and still
  be broken, because it wired only _some_ of the code paths in its own category.
  Live case: `cleanup_progress` tracked message IDs for tool-progress bubbles,
  heartbeats, and status callbacks (three call sites in `gateway/run.py`) but
  never for interim assistant commentary — `_send_commentary` recorded the
  message _text_ and dropped `result.message_id`. Flag on, docs correct in
  spirit, symptom fully present. Upstream had closed a related request as
  "implemented in #21186" on exactly that partial coverage.
  **Enumerate every producer in the category and confirm each one is handled.**
  A green flag plus a docs sentence is not proof; a `grep` for the tracking call
  across all sibling call sites is.
- **Reporting "the knobs don't exist" when the knob exists and is already on.**
  Check live config across every profile _before_ proposing new configuration —
  and check the OTHER user's config too. Here the operator had
  `cleanup_progress: true` while the person suffering most had it `false` with
  progress disabled entirely: same complaint, opposite root causes, one fix
  would not have served both.
- **`pgrep -f` matching unrelated system processes.** It returned `runningboardd`
  and produced a bogus "old_pid == new_pid" restart reading. Prefer
  `ps aux | grep "gateway run" | grep -v grep` and read the full argv path.
- **Keeping a patch written during a known-broken window.** Once the underlying
  fault is fixed, re-test before preserving the workaround forever.
- **Auditing only the active fork branch before cleanup.** The reason a fork
  exists may be preserved only on an older remote branch or merged fork PR.
  Before calling the active release clean, inventory fork-only behavior across
  all branches and prior PRs, build a custody list of required semantic patches,
  and prove each is carried by the active release. Then inspect the deployed
  artifact separately: a still-present environment variable is not evidence
  when its reader is absent from the running bundle. Cherry-picked patches need
  semantic/symbol/test proof because the original SHA will not be an ancestor.
- **Editing a shared predicate as if it had one consumer.** Grep every caller
  first. "Just delete that clause" is a one-liner that can silently change an
  unrelated retry/cooldown behavior — including one the captain explicitly asked
  you to keep.
- **Acting on a multi-review defect without verifying it.** Reviewers fed
  truncated diff hunks confidently invent missing type properties and predict
  compile failures that don't happen. Two models agreeing is not corroboration
  when they share the same truncated input. Prove each claimed defect with
  `grep` + the project typechecker + an actual test run before changing code.
- **Assuming a red CI check is yours.** Check out the pristine base ref and run
  the same gate; baseline drift in files you never touched is common on an
  active release branch. Report it as pre-existing and note it in the PR body.
- **Counting a CANCELLED job as a failure.** `gh pr checks` renders cancelled and
  failed identically as `fail`. Read the job log before citing it as evidence:
  `The runner has received a shutdown signal` / `The operation was canceled`
  means the job produced **no signal at all** about your code — it never finished
  compiling. Reporting it as a failure overstates the evidence against your own
  change, and it's the kind of sloppiness that erodes a report the captain is
  relying on. Also check _which tool_ the job used before trusting it as a build
  gate: an upstream advisory build may run a bundler your host has banned
  (Turbopack, in our case), so its artifact is unusable even when green.
- **A RED that's only a compile error.** Stashing your fix so the test fails on a
  missing export proves nothing about behavior. Prove the bug against an
  unmodified copy of the upstream file.
- **Proposing a plugin before checking the extension point exists.** "Write our
  own plugin instead of patching core" is the right instinct and often the wrong
  answer. Check whether the data the plugin needs is actually _reachable_: the
  value may live only in a method's local scope and be discarded, with no hook
  event carrying it. In one case reaching it required monkeypatching gateway
  internals — which is exactly what the rejected third-party plugin did across 13
  patch families and 16k lines. State the finding as "the extension point does
  not exist," not "a plugin is a bad idea."
- **Evaluating a third-party plugin without checking the LICENSE first.** A repo
  with **no LICENSE file** (`gh api repos/<o>/<r> --jq .license` → `null`) is
  default-copyright: no legal right to copy, modify, or vendor it, no matter how
  good it is. Check that before measuring anything else, then `requires-python`
  against the actual fleet interpreters — both are cheap disqualifiers.
- **Letting the lifecycle guard eat your command.** `cron/lifecycle_guard.py`
  pattern-matches command TEXT: a commit message containing "restart" is refused
  with "cannot restart or stop the gateway," and naming an interpreter path
  inline can raise `ValueError: embedded null byte`. Put prose in a file and use
  `git commit -F <file>`; put commands in a `.sh` and run that.
- **Reusing a scratch filename for commit messages.** A heredoc to a generic path
  like `/tmp/cm2.txt` can silently pick up a stale file from earlier work and
  commit the wrong message onto the right files. Use a dated, uniquely-named
  message file and verify with `git log -1 --format=%s` after committing.
- **Pushing a fix you wrote but never COMMITTED.** Editing a file, verifying it
  live, then pushing — while the change sat unstaged — ships the branch WITHOUT
  the fix. The fleet then fails verification on the exact symptom you just fixed,
  which reads like the fix doesn't work. `git status --porcelain` before every
  push, and confirm the fix is in the pushed object:
  `git show HEAD:path/to/file | grep -c '<new symbol>'`.
- **Verifying config before the code that READS it is deployed.** Config can be
  correct on every host while the consumer is absent, producing
  `cannot import name '_new_helper'`. Order: push code → fast-forward every host
  (skip dirty trees rather than clobbering) → assert identical SHA _and_ file
  hash → only then verify the config outcome.
- **Fighting the lifecycle guard's path matching.** The guard matches the live
  checkout path ANYWHERE in the command text, so
  `git -C /tmp/clone remote add src ~/.hermes/hermes-agent` is refused even though
  the target is the clone. Pass the live path as a script ARGUMENT instead of
  inlining it. Related: `git fetch <path> <bare-sha>` fails
  (`couldn't find remote ref` — bare SHAs are not fetchable refs), and cloning the
  full live repo can hang on `fetch-pack: unexpected disconnect`. The reliable
  move is `git format-patch -1 <sha> --stdout > /tmp/x.patch` then
  `git -C <clone> am /tmp/x.patch`, and run the suite IN the clone so the change
  is proven independent of uncommitted local state.
- **Adjusting a failing test on a security file instead of reading it.** A guard
  change made `test_single_file_scan` fail; the test was right and the change was
  over-broad (it demoted prompt-injection findings, and a skill's prose IS the
  model's instruction stream). A red test on a security boundary is evidence
  about the change, not an obstacle to it.

## Verification Checklist

- [ ] Running process attributed to a real install path (`ps` + `lsof`)
- [ ] **`git remote -v` inspected; the comparison ref is a VERIFIED upstream
      remote, never `origin/<branch>` inside a fork clone**
- [ ] **"Already upstream?" answered by FILE CONTENT (diff / symbol grep in both
      directions), never by `git cherry` or patch-id**
- [ ] **PR titles written as English symptom sentences, not `fix(scope):` — and
      the repo checked for a semantic-PR/commitlint title gate first**
- [ ] **Independent defects split into separate PRs; mixed commits split BY FILE
      (`git checkout <sha> -- <path>`), then leakage asserted at 0**
- [ ] **Release-dir deploy: `current` symlink resolved and the DEPLOYED sha (not
      checkout HEAD) used for every drift number**
- [ ] **Drift measured with `git rev-list --left-right --count <deployed>...<upstream>`
      so fork ahead-commits are visible, not just "behind"**
- [ ] **Missing upstream commits checked against the specific file at issue
      (`git log <deployed>..<upstream> -- <file>`) before claiming an upgrade fixes it**
- [ ] **Fork's own ahead-commits checked against that file (empty = clean upstream PR)**
- [ ] **Unit/format bug: file grepped for sibling call sites; any already-fixed
      sibling cited as precedent in the PR**
- [ ] Exact version recorded and compared to latest upstream release
- [ ] **Install-method parity measured across ≥3 members before any box is called
      a regression; target version confirmed to exist on PyPI before proposing a
      package cutover; dirty-tree files classified and wanted fixes saved as a
      patch**
- [ ] Local checkout HEAD date compared to upstream `main` before any claim about
      upstream state; decisive file re-fetched from `main` if they differ
- [ ] Upstream issues AND **open PRs** searched for the symptom (several phrasings)
- [ ] **Missing CAPABILITY (not a bug): tracker searched for prior-art PRs and the
      most recent CLOSING COMMENT read for the maintainer's position; docs checked
      for a named supported alternative; our own skills grepped for guidance that
      assumes the refused capability — Step 3d**
- [ ] Any candidate PR checked for `mergeable_state` + age + review-comment count
      before treating a fix as inbound
- [ ] "Implemented in #X" closures verified against the code paths actually covered
- [ ] Every producer in the affected category enumerated — not just the ones the
      feature's docs mention
- [ ] Live config checked across all relevant profiles (and the other user's)
      before proposing new configuration
- [ ] Fixing PR confirmed **merged** (not merely cross-referenced, not merely CLOSED)
- [ ] Fix symbols confirmed present in the INSTALLED source at the running version
- [ ] Any proposed config key confirmed to be READ by the code, not just declared
- [ ] Field/flag being patched traced producer → consumer (not inert)
- [ ] If upgrading: platform deps verified present BEFORE gateway restart
- [ ] Post-restart verification filtered by timestamp, not `tail`
- [ ] Captain's rejected remedies not re-proposed
- [ ] Owner-facing box: restart gated on the operator's go
- [ ] If a local patch was written: branched (never `main`), pushed to the fork
      the same session, exit plan recorded — `references/local-patch-custody.md`
- [ ] If the patch ships to a fleet: based on the release TAG, removal condition
      written, verifier validated in both directions —
      `references/pinned-release-fork-model.md`
- [ ] If the patch deletes/suppresses user-visible messages: deletion-safety pass
      run — `references/deletion-safety-in-message-pipelines.md`
- [ ] Third-party plugin considered? LICENSE and `requires-python` checked before
      any deeper evaluation
- [ ] Every local change COMMITTED before pushing (`git status --porcelain` clean),
      and the fix confirmed present in the pushed object
- [ ] Code deployed and host SHAs/file hashes matched BEFORE any config outcome
      is verified
- [ ] Any failing test on a security boundary read as evidence about the change,
      not adjusted to pass
- [ ] Checkout audited for pre-existing divergence
      (`git rev-list --left-right --count origin/main...HEAD` → `ahead: 0`)
