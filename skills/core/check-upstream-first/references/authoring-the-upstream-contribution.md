# Authoring the upstream contribution (Step 5)

Steps 1–3 of the parent skill establish that a bug is genuinely unfixed upstream.
This covers what happens next: writing a patch a stranger will merge.

Worked end-to-end on the router `STREAM_EARLY_EOF` / circuit-breaker, 2026-08-01.

## the operator's required order

He was explicit: **do not open the upstream PR first.**

```
build + clean checks + multi-review
  -> merge to OUR fork
  -> deploy to OUR production
  -> verify against live traffic for ~a day
  -> only then upstream PR
```

Rationale: the PR description's strongest asset is "we run this in production."
Claiming a fix works before you've run it is exactly the credibility gap that
gets a drive-by PR closed.

## Establish the TRUE upstream before adding a remote

Do not infer the upstream URL from the project name, a docs link, or memory. In a
2026-08-03 session I added `upstream` pointing at a guessed org and it was simply
the wrong repository — silently wrong, since `git remote add` never validates.

Ask GitHub who the parent actually is:

```bash
gh repo view OWNER/REPO --json parent,name,owner
# -> {"name":"REPO","owner":{"login":"YOUR-ORG"},
#     "parent":{"name":"REPO","owner":{"login":"UPSTREAM-ORG"}}}
```

Then prove the remote resolves before trusting it:

```bash
git remote add upstream https://github.com/<parent-owner>/<repo>.git
git ls-remote --heads upstream | head -3     # empty/error => wrong URL
```

Note that `package.json` `repository.url` may point at the true upstream even when
your `.git/config` origin points at the fork — a useful cross-check, but confirm
with `gh` rather than treating either as authoritative alone.

While you are there, list the live branches: an active
`chore/bank-ratchet-vX.Y.Z` or `release/vX.Y.Z` is usually the correct base, not
`main`.

## Base the branch on the right ref

Upstream `main` may be **parked**. Real work lands on `release/vX.Y.Z`.

```bash
gh api repos/OWNER/REPO/branches --paginate --jq '.[].name' | grep release | sort -V | tail -5
```

Check open PRs that touch **the same function** before writing — they are both a
merge-conflict risk and a style template:

```bash
gh api -X GET search/issues -f q='repo:OWNER/REPO <filename> type:pr state:open' \
  --jq '.items[] | "\(.number) [\(.state)] \(.title)"'
gh api repos/OWNER/REPO/pulls/<n>/files --jq '.[].filename'
```

In the worked case, PR #9125 edited the exact predicate — reading it revealed the
maintainer's preferred shape (additive optional arg + a dedicated test file).

A local clone can be many versions stale. Verify before trusting it:

```bash
git log --oneline -1 && python3 -c "import json;print(json.load(open('package.json'))['version'])"
```

## Read the diff you'd be adopting, filtered

A release-to-release diff is mostly noise. Classify before reporting:

```bash
git diff --numstat upstream/release/vA...upstream/release/vB -- src/ open-sse/ \
  ':(exclude)src/i18n/messages/*' | awk -F'\t' '$1+$2>0'
```

Buckets that matter: **runtime code**, tests, CI/quality, docs/i18n. 253 files
collapsed to 40 runtime files / ~1,300 lines.

**Always check migrations explicitly** — they are the one-way door:

```bash
git diff --name-only upstream/release/vA...upstream/release/vB -- db/migrations/
# empty => rollback is a symlink flip
```

## The shared-predicate trap

The highest-value technical lesson. Before editing any classifier/predicate,
enumerate **every** consumer of it:

```bash
grep -rn "<predicateName>" --include=*.ts src/ open-sse/ | grep -v node_modules
grep -rn "<derivedFlagName>" path/to/consumer.ts
```

In the worked case `isStreamReadinessFailureErrorBody()` fed **three** behaviors:
the circuit-breaker gate, a transient-retry decision, and a round-robin semaphore
cooldown. Only the breaker needed the new distinction.

Deleting the offending clause would have been a true one-liner — and would have
silently changed retry semantics, including the retry the user had _explicitly
asked to keep two messages earlier_.

**The fix shape that survives review:** add a narrow new predicate plus an
**optional** argument, so omitting it reproduces prior behavior byte-for-byte.
Then say so in the PR body. This is the same producer→consumer discipline as
Step 3b, applied to a value with multiple consumers rather than none.

**Look for an existing code path that already does what you want.** Here the
single-model path (`shouldTripProviderBreakerForResult`) had no readiness
exemption at all — a 502 early EOF already tripped the breaker there. That
reframes the PR from "change your resilience policy" to "fix an inconsistency
with your own adjacent code," which is dramatically easier to accept.

## Prove the bug against UNMODIFIED upstream first

A test that fails only with a compile error is **not** a RED. Stashing the fix
gave `SyntaxError: does not provide an export named ...` — that proves nothing
about behavior.

Real RED: copy the untouched upstream file beside the test and assert the buggy
behavior explicitly.

```bash
git show upstream/release/vX:path/to/file.ts > /tmp/file.upstream.ts
# import from the .upstream copy, assert the WRONG result is what happens today
```

A passing "the bug exists" test against pristine upstream is the single most
persuasive artifact in the PR.

## Test file shape that reads as human

- One assertion per named behavior; descriptive names, **no issue numbers** in
  the titles when contributing from outside.
- Include a **regression test asserting the OLD call shape still yields the OLD
  result** — this is what proves the change is additive.
- Include one veto test per remaining AND-term (client abort, skip flags,
  request-scoped, same-provider, 429). These prove the override is narrow rather
  than a blanket bypass.
- Run the project's own gates, not your own: `npm run typecheck:core`,
  `npx prettier --check`, `npx eslint`. Prettier will reformat your call site —
  re-run tests after.

## Multi-review reviewers hallucinate on truncated diffs

Both reviewers in the worked session independently claimed a property was
undeclared in a function signature and that the tests "would not compile."
Both were wrong — the property was declared, `typecheck:core` was clean, and the
test they said would fail passed at runtime.

Cause: they were reasoning from diff hunks that showed only part of the type.

**Verify every reviewer defect against source before acting on it.** Three cheap
proofs: `grep` the declaration, run the project typechecker, run the test. Two
confident models agreeing is not evidence — they share the same truncated input.

When feeding a diff to reviewers, include the **full** function signature, not
just the changed hunk.

## Distinguish pre-existing CI failure from your own

A red check is not automatically yours.

```bash
git checkout -q upstream/release/vX && node scripts/check/<gate>.mjs; echo "BASE_EXIT=$?"
```

In the worked case `Fast Quality Gates` failed on file-size baseline drift in
three files the patch never touched — identical failure on pristine upstream.
Report it as pre-existing **and** note it in the PR body, because a reviewer
seeing red will otherwise assume it's the contribution.

**Cheaper discriminator when you can't run the gate locally: poll sibling PRs.**
If the same check is red on unrelated open PRs against the same base, it's the
repo, not you.

```bash
for pr in $(gh pr list --repo $R --state open --limit 6 --json number -q '.[].number'); do
  echo "PR #$pr: $(gh pr checks $pr --repo $R 2>/dev/null | grep -E '^<Check Name>' | awk '{print $2}')"
done
```

2026-08-02 on PR #9251: `Build (advisory)` red on #9251/#9247/#9246/#9242, green on
#9250 — a flaky Turbopack build affecting the whole repo. `Fast Quality Gates` was
red on ours alone. That split decided where to spend the effort.

## Adding a test can require registering it elsewhere

The one genuinely-ours failure on #9251:

```
✗ 1 covering unit test(s) across 1 module(s) are missing from
  stryker.conf.json tap.testFiles. Add them so their mutant kills count (--strict).
  open-sse/services/combo/comboPredicates.ts
    + tests/unit/stream-early-eof-breaker.test.ts
```

Mutation-testing configs, coverage manifests, shard maps and `CODEOWNERS` keep their
**own list of test files**. A new test covering an already-instrumented module has to
join that list or its results silently don't count.

**The tell was available before CI ran.** The test was modeled on
`8376-econnrefused-breaker.test.ts`, and that file was already registered. When you
copy an existing test as a template, copy its _registrations_ too:

```bash
grep -rn "<template-test-basename>" --include="*.json" --include="*.yml" .
```

Then run the exact CI command locally rather than pushing speculatively:

```bash
node scripts/check/check-mutation-test-coverage.mjs --strict   # -> ✓ No drift, exit 0
```

**Two traps while making that one-line edit:**

- **A JSON round-trip rewrites the whole file.** `json.load` → mutate → `json.dumps`
  escaped every em-dash in the comment block (`—` → `\u2014`), yielding 15 unrelated
  changed lines. Revert and make a targeted single-line edit; then verify
  `grep -c '\\u' <file>` is 0 and the list is still sorted.
- **A formatter warning may predate you.** `prettier --check` flagged the edited
  file; stashing the change and re-running showed the untouched upstream file failed
  identically. Reformatting would have added churn to a one-line PR. Leave it, say why.

Finally: make the commit on the **PR's head branch**, not the base you were reading.
Confirm with `gh pr view <N> --json headRefName`. And after pushing, `pending 0` across
_all_ checks including other contributors' branches means a runner backlog — report
"pushed, verified locally, CI pending" rather than claiming green off a local run.

## Commenting on the sibling issue

When someone else filed a _different symptom of the same root cause_, comment
rather than filing a duplicate. Shape that worked:

1. "Seeing this too, on `<version>`" + your own field numbers.
2. Name the **shared root cause** and where your symptom diverges from theirs.
3. Point at the adjacent code path that already behaves correctly.
4. State plainly that your fix **will not** fix their symptom, and why.
5. Offer to test their patch.

Do **not** post it until your CI is green — announcing a working fix that a bot
then contradicts is worse than staying quiet.

## Contributing to EXISTING issues/PRs instead of opening your own

Default to joining existing threads. The operator's instruction was explicit:
_"Let's add our commentary to existing issues/PRs."_ Opening a fresh issue for a
gap already tracked in three places fragments the signal and reads as
not-having-looked.

**When an open PR already contains your exact fix, the author owns it.**
`hermes-agent` #22613 held the precise commit needed (`expose
commentary_message_ids`), stalled at `mergeable_state: dirty` for ~4 weeks with
zero review. Tempting to fork it and ship a clean version. Don't — ask first:

> "@author are you still working on this? Happy to help rebase, or — if you'd
> rather see it land in pieces — to split just the `<commit>` out as a focused
> PR with your authorship preserved via cherry-pick. Your call; I don't want to
> fork work you're still on."

Preserving authorship by cherry-pick is the repo-sanctioned move (`AGENTS.md`:
_"Salvage external work by cherry-picking so authorship survives"_). Forking a
live contributor's work turns a helpful comment into a hostile one.

**Diagnose WHY a good PR stalled and say it kindly but plainly.** #22613 was
+550/-20 bundling six unrelated concerns (queue-merge, cross-restart state file,
mono-formatting, approval-ack, always-on heartbeat collapsing). That is almost
certainly why nobody reviewed it. Critique the _bundle shape_, never the person,
and pair it with the smaller alternative.

**Audit "closed as implemented in #X" claims.** Maintainers close duplicates in
good faith on partial fixes. Here #21252 was closed as covered by #21186 — true
for three of five message classes, false for the one that mattered. That closure
is precisely _why_ the gap stayed invisible. Comment on the still-open sibling
to prevent the next triage sweep repeating it:

> "Flagging so this isn't closed as 'already implemented' on the strength of
> #21186 — one of the transient message classes was never wired up."

**One comment per thread, each scoped to that thread's own frame:**

| thread              | angle                                                   |
| ------------------- | ------------------------------------------------------- |
| the stalled PR      | your commit still applies + author etiquette ask        |
| the feature request | why the "already fixed" closure was incomplete          |
| the design issue    | scoping note — its acceptance criteria inherit the hole |

Do not paste one generic body three times.

## Mechanics: posting comments without mangling them

- **Never inline prose in the shell.** An `&` trips terminal backgrounding
  guards; an apostrophe breaks heredocs. Write each body to a file and use
  `gh issue comment <n> --repo <r> --body-file <f>.md`. Works for PRs too.
- **`gh issue view --comments` can hard-fail** on `projectCards` GraphQL
  deprecation. Read via REST instead:
  `gh api repos/<r>/issues/<n>/comments --paginate`.
- **`gh api ... --paginate` returns concatenated JSON arrays**, so a single
  `json.loads` raises `Extra data`. Fetch one page, or parse per page.
- **Fact-check your own draft before posting.** In this session a draft said
  "the other three transient classes" above a table listing four, and "one of the
  four" when five tracked call sites existed. Caught pre-send. A public comment
  citing file:line evidence is only as credible as its arithmetic.
- **Verify the post landed by reading it back**, not by exit code:

```bash
gh api repos/<r>/issues/comments/<comment_id> \
  --jq '"\(.user.login) \(.created_at) chars=\(.body|length)"'
```

- **Public comments post under the operator's identity.** Show drafts before
  sending, flag anything that critiques a named contributor, and confirm no
  PII/paths/fleet specifics leaked. "Self-hosted multi-agent Telegram
  deployment" is safe; hostnames and `/Users/<name>/` paths are not.

## Anti-AI-slop wording

the operator's stated belief: PRs that read as AI-generated get disregarded.

Tells to avoid: emoji headers, "Summary/Changes/Impact" boilerplate scaffolding,
bulleted restatement of the diff, hedging ("this should probably"), and
enthusiasm. Prefer:

- Lead with the **field incident** and hard numbers (counts, windows, the state
  that was wrong), not with a description of the code change.
- Plain first-person operator voice: "we got hit by", "our numbers", "I've got a
  fix running on our production router this week."
- Say what you **deliberately did not change** — it signals you understood the
  blast radius.
- Concrete verification list with real command names and pass counts.
- No adjectives about the quality of your own patch.

## PR TITLES: English sentences, not Conventional Commit prefixes

the operator's explicit instruction (2026-08-16): _"I don't actually like using the fix
prefix and all of the Git standard prefixes. I want to have English-friendly,
human review-friendly pull request titles."_

Write the title as **the symptom a maintainer would recognize**, not a taxonomy
label:

| Instead of                                     | Write                                                                               |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| `fix(db): tolerate missing dbstat vtab`        | Database settings page returns HTTP 500 when SQLite lacks the optional dbstat table |
| `fix(db): align cleanup cutoff with ms column` | Compression telemetry retention has never deleted a row (same unit bug as #9625)    |

Citing the sibling issue number **in the title** does real work: it tells the
reviewer in one line that this is a known, already-accepted bug class.

**Check for title enforcement before choosing** — some repos gate on
`semantic-pull-request` / commitlint and an English title fails CI:

```bash
for w in $(git ls-tree --name-only upstream/<branch>:.github/workflows/); do
  git show upstream/<branch>:.github/workflows/$w \
    | grep -qiE "semantic-pull-request|pr-title|commitlint|conventional" && echo "HIT: $w"
done
```

No hit means English titles are safe. If there IS a hit, tell the operator the
constraint rather than silently reverting to prefixes.

**The prefix may still be required elsewhere.** This repo's `changelog.d/`
fragments are machine-aggregated into `CHANGELOG.md` and their documented format
keeps `- **fix(db):** ...`. Human-facing title ≠ machine-facing fragment; read
`changelog.d/README.md` (or equivalent) and follow each convention where it applies.

## Optimizing for the approver's experience

the operator: _"think about a high-quality experience for the approver. That's actually
the thing that I want the most."_

**1. Lead with their symptom, not your diff.** Open with what a user experiences
— a page that 500s, a table that grows forever. Code comes after.

**2. Argue from the project's own history.** The strongest possible case is one
where you never ask to be believed:

- _"#9625 fixed this identical unit mismatch in the sibling function 90 lines
  earlier in this same file, and left a comment explaining it."_
- _"#7313 added exactly this guard to the `COUNT(_)`path in this function; the`dbstat` path simply sat outside it."\*

Find these with `git log -S<symbol>` and `git log --oneline <file>` before writing.

**3. Explain why it survived.** If a test existed and passed, say what the test
got wrong. Here `#6848`'s test seeded epoch **seconds** while production wrote
**milliseconds** — so it asserted a true-but-irrelevant thing and the retention
path looked covered. Fixing that test is often the more durable half of the PR,
because otherwise the next person "fixes" the failing test back toward the bug.

**4. Show the test FAILING, not just passing.** Include the reverted-fix output
verbatim (`actual: 0, expected: 3`) beside the passing run. A test that only ever
passes proves nothing about the bug.

**5. Name the risk yourself, before review does.** e.g. _"after merge the first
sweep on a long-running instance deletes everything older than the window in one
pass — worth an operator note in release notes."_ Volunteering the sharp edge
buys more trust than a clean-looking PR.

**6. Offer the reasonable alternative you rejected.** _"If you'd prefer `null`
over `0` to distinguish unavailable from empty, that's a one-line change."_
Pre-answers the most likely review comment.

**7. State that it runs in production, and how you found it.** One line, factual,
at the end of reviewer notes.

## Grouping: separate PRs unless causally linked

Default to **one PR per independent defect**, even when they land in the same
subsystem and you have them on one branch. The approver can merge one and reject
the other without untangling anything.

Group into a single PR only when the parts are causally linked — a source fix
plus the test correction that explains why the bug survived belong together,
because splitting them leaves a broken test on `main` between merges.

Also: a commit that mixes concerns (docs for feature A + config for feature B)
must be **split by file** across the PRs, never dropped whole into one:

```bash
git checkout -q -B pr-a upstream/<branch>
git cherry-pick <fix> <test>
git checkout <mixed-commit> -- path/to/only-this-prs-file    # not the whole commit
```

Then verify no unrelated content leaked in:

```bash
git diff --name-only upstream/<branch> pr-a | grep -cE "<other-feature-files>"   # expect 0
```

## Pushing PR branches: the `workflow` scope trap

A rebase onto a newer upstream picks up upstream's `.github/workflows/` changes.
Pushing those requires a token with `workflow` scope, or the push is **rejected**:

```
! [remote rejected] HEAD -> branch (refusing to allow an OAuth App to create or
  update workflow `.github/workflows/ci.yml` without `workflow` scope)
```

Check with `gh auth status` (look for `workflow` in Token scopes). If the host
running the build lacks it, do not weaken credentials there — move the commits to
a machine that has it via a bundle:

```bash
# on the build host
git bundle create /tmp/prs.bundle --branches
# locally
scp host:/tmp/prs.bundle /tmp/ && git fetch /tmp/prs.bundle '+refs/heads/x:refs/heads/x'
git push origin x:refs/heads/feature-branch
```

🔴 **`git push -q` hides rejections.** In this session a `-q` push "succeeded"
(exit 0) while pushing to a clone whose `origin` was a **local path**, not GitHub.
The CI build then failed with `upload-pack: not our ref`. Always verify the ref
actually landed on the real remote:

```bash
git ls-remote https://github.com/<owner>/<repo>.git refs/heads/<branch>
```

Empty output means the push did not land, whatever the exit code said.
