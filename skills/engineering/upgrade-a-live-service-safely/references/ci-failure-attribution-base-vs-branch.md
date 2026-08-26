# Distinguishing your regression from a red base branch

## Why this matters

When you push a change and CI goes red, the default assumption — "I broke something" —
is wrong often enough to be expensive. Upstream branches on active projects are
frequently red from the maintainer's own recent commits. If you don't check, you either
waste hours "fixing" someone else's breakage, or you quietly weaken your own patch to
make an unrelated gate pass.

The reverse error is worse: assuming red is pre-existing when it isn't, and shipping a
real regression.

## The test: run the same check on the unmodified base

The only reliable answer comes from checking out the **exact base commit** with your
change absent, running the **same check CI ran**, and comparing.

```bash
# 1. What exactly did you change?
git diff --name-only HEAD~1 HEAD

# 2. Do the CI-flagged files appear in that list?
#    If none of them do, that's suggestive — but not proof. Prove it:

# 3. Run the failing check on the untouched base
git checkout -q upstream/release/vX.Y.Z
node --import tsx/esm --test tests/unit/<the-file-CI-flagged>.test.ts \
  2>&1 | grep -E "^ℹ (tests|pass|fail)"
#    -> 40 tests, 38 pass, 2 fail

# 4. Run the identical command on your branch
git checkout -q my-fix-branch
node --import tsx/esm --test tests/unit/<the-file-CI-flagged>.test.ts \
  2>&1 | grep -E "^ℹ (tests|pass|fail)"
#    -> 40 tests, 38 pass, 2 fail   <- identical => not yours
```

Identical pass/fail counts on both sides is the evidence. Anything else — "those files
look unrelated", "my change is only in the combo path" — is inference, not proof.

## 🔴 The base comparison controls for your DIFF, not for your ENVIRONMENT

Identical results on base and branch prove the failure is not caused by your
change. They do **not** prove the failure is a property of the codebase — both
runs share the same `node_modules`, the same interpreter, the same missing
packages.

Worked case: five API tests failed identically on base (`196 pass, 5 fail`) and
on branch (`203 pass, 5 fail`), all with `Cannot find package 'js-tiktoken'`.
That was reported as "pre-existing, not mine" — technically true and
substantively misleading. The checkout had been dragged from v3.8.7 to v3.8.50
without reinstalling, so `node_modules` was stale. Every one of the six
"missing" packages was already declared in `package.json`:

```
                        BEFORE npm install    AFTER
typecheck:core          7 errors              0 errors
tests/unit/api/**       196 pass, 5 fail      215 pass, 0 fail
```

A 28-second `npm install` cleared what had been reported as an environmental
blocker capping local verification.

**Before calling any failure pre-existing or unresolvable, check whether it is
just stale dependencies:**

```bash
# Are the "missing" modules actually declared?
python3 -c "
import json; p=json.load(open('package.json'))
deps={**p.get('dependencies',{}),**p.get('devDependencies',{}),**p.get('optionalDependencies',{})}
for m in ['pkg-a','pkg-b']: print(f'{m:32}', deps.get(m,'NOT DECLARED'))"
```

Declared but absent from `node_modules` ⇒ stale install, not a codebase fact.
Reinstalling is cheap and reversible; do it before writing the failure into a
report. The general rule: **a blocker you have not tried to clear is a
hypothesis, not a blocker.**

Note this cuts against the retry-vs-report instinct in the opposite direction
from flaky tests — here the _stable_ failure was the misleading one.

## Attribute the breakage to a commit

Once you've established it's pre-existing, find the cause. It strengthens your PR and is
a genuine contribution to the maintainer.

```bash
git log --oneline -5 upstream/release/vX.Y.Z | cat
git show --stat <suspect-sha> | head -15
```

In one real case the top two commits on the base branch were pushed by the maintainer
**the same day**, modified `chatCore.ts` and three test files, and accounted for every
failing test plus two file-size-baseline violations. Branching off that commit inherited
a red branch through no fault of the patch.

## Read the failure, not just the status

A red check is not one thing. Classify before reacting:

| Failure kind               | Example                                                      | Is it yours?                                                           |
| -------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Behavioral test            | a unit test asserting logic                                  | possibly — investigate hard                                            |
| Bookkeeping gate           | file-size baselines, changelog presence, lint-warning counts | usually a base-branch artifact; these drift when _anyone_ grows a file |
| **Registry/coverage gate** | "test file missing from `stryker.conf.json` tap.testFiles"   | **often genuinely yours** — see below                                  |
| Advisory / smoke           | jobs literally named `(advisory)`                            | non-blocking by design                                                 |
| Environment                | expired third-party session cookie in a test log             | never yours                                                            |

Bookkeeping gates are the most common false alarm. A "frozen file size" check fails for
whoever pushes next, not for whoever grew the file.

## The mirror-image error: a gate that IS yours

Attribution runs both ways. In one session two checks were red: `Build (advisory)`
(failing on 4 of 6 open PRs — provably not ours) and `Fast Quality Gates`, which said:

```
✗ 1 covering unit test(s) across 1 module(s) are missing from
  stryker.conf.json tap.testFiles.
  open-sse/services/comboPredicates.ts
    + tests/unit/stream-early-eof-breaker.test.ts
```

That one was real. Adding a test that covers a mutation-tested module requires
**registering it** so its mutant kills count. The tell: the precedent file the new
test was modeled on (`8376-econnrefused-breaker.test.ts`) was _already_ in that
list. **When you copy a test's structure, check what bookkeeping came with it.**

Verify the fix by running the _exact_ CI command locally, not a proxy:

```bash
node scripts/check/check-mutation-test-coverage.mjs --strict
# before: ✗ 1 covering unit test(s) missing   (reproduces CI)
# after:  ✓ No drift — every covering unit test is listed.  EXIT=0
```

A local red→green on the identical command is real evidence. "The change looks
right" is not.

## `queued` is not `failing` — check the runner pool before diagnosing

`gh pr checks` showed everything `pending 0` for 40+ minutes. That is not a
failure signal; jobs had never been _scheduled_.

```bash
gh run list --repo OWNER/REPO --limit 12 \
  --json status,conclusion,headBranch -q '.[] | "\(.status) \(.headBranch)"'
# all `queued`, including other contributors' branches  => pool saturated, not you
gh run list --repo OWNER/REPO --status in_progress --limit 5
# other PRs in_progress 29+ min => confirms a backlog
```

If newer PRs are queued _behind_ yours and unrelated branches are also stalled,
the constraint is org-level (runner capacity or billing), not your change.

**Build a watcher that can tell the two apart.** A poller that greps for a check
name logs blank lines when the check does not yet exist, then exhausts its
iterations having learned nothing. Distinguish explicitly:

```bash
if [ -n "$out" ]; then echo "$out"; case "$out" in *pass*) ...;; *fail*) ...;; esac
else [ $((i % 10)) -eq 0 ] && echo "still queued, gate not scheduled yet"
fi
```

## Don't let a JSON rewrite become the diff

Editing a config with `json.load`/`json.dumps` escaped every em-dash to `\u2014`
and produced **15 spurious changed lines** in a file that needed one. Prefer a
targeted single-line edit, and check whether a formatter complaint predates you:

```bash
git stash push file.json -q
npx prettier --check file.json   # same warning on untouched upstream => pre-existing
git stash pop -q
```

Leave pre-existing formatting alone — reformatting adds unrelated churn a
maintainer must review.

## Reporting it

Give the user the comparison, not the conclusion alone:

```
BASE (fix absent):  40 tests, 38 pass, 2 fail
OUR branch:         40 tests, 38 pass, 2 fail   <- identical
```

Then name the responsible commit and date. If you're about to open an upstream PR
against a base you know is red, say so in the PR description — otherwise the maintainer
sees a red PR and assumes it's yours.

## Pitfalls

- **Trusting "the flagged files aren't in my diff."** Necessary but not sufficient; a
  change can break a test in a file it doesn't touch. Run the base comparison anyway.
- **Rerunning CI hoping it goes green.** If it's deterministic, it won't; you've spent
  ten minutes and learned nothing.
- **Editing a baseline/allowlist file to make a gate pass.** That silently adopts
  someone else's debt into your PR and makes your diff look unfocused to a maintainer.
- **Blocking your own deploy on someone else's red branch.** If the failures are
  provably unrelated to the code path you're shipping, that's a decision to surface to
  the user with evidence, not a hard stop.
