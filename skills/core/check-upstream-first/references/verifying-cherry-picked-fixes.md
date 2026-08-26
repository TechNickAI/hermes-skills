# Verifying a cherry-picked or locally-authored upstream fix

You found the upstream PR (or wrote the patch). Before claiming it works, the
test evidence has to be real. Two traps make a correct patch look broken and a
broken patch look fine.

## Use the repo's canonical runner, not bare `pytest`

Many projects ship a canonical test runner (e.g. `scripts/run_tests.sh`)
that is not a convenience wrapper — it
enforces **per-file process isolation**, `TZ=UTC`, `LANG=C.UTF-8`,
`PYTHONHASHSEED=0`, and blanked env vars, which is what CI does.

Running `python -m pytest tests/tools/ -k skill` by hand produced **14 failures**
in `test_skills_sync.py` / `test_skills_list_modified_diff.py` /
`test_skill_bundle_provenance.py`. Every one was **test-order pollution** — shared
module state leaking between files in a single process. The same tests under
`scripts/run_tests.sh`: **38 passed, 0 failed**.

Had I reported those 14 as regressions, I would have blamed my own patch for
someone else's cross-file leakage.

```bash
scripts/run_tests.sh tests/tools/test_skills_guard.py tests/tools/test_skills_hub.py
```

## Prove pre-existing failures with a pristine worktree

When failures DO appear, do not argue about whether they are yours. Check out the
merge-base commit into a throwaway worktree and run the identical command:

```bash
git worktree add --detach /tmp/baseline <merge-base-sha>
cd /tmp/baseline && <same test command> 2>&1 | grep '^FAILED' | sort > /tmp/fail_baseline.txt
cd <repo>          && <same test command> 2>&1 | grep '^FAILED' | sort > /tmp/fail_head.txt
comm -13 /tmp/fail_baseline.txt /tmp/fail_head.txt   # NEW failures — must be empty
comm -23 /tmp/fail_baseline.txt /tmp/fail_head.txt   # failures your change FIXED
```

Set-difference on sorted `FAILED` lines is the evidence. "Both runs had 14
failures" is _not_ — different sets of the same size would look identical.
Do not use `set -e` in that script: pytest exits non-zero on failure and would
abort before printing the comparison.

Clean up with `git worktree remove --force /tmp/baseline`.

## Bump the version when changing cached-verdict logic

`skills_guard.py` caches scan results keyed by scanner version. Editing a rule
without bumping `SCANNER_VERSION` leaves stale verdicts in place and the change
appears to do nothing. Any subsystem that memoizes on a version string has this
property — check for one before concluding your rule edit had no effect.

## Blocked ≠ overridable

A `dangerous` verdict from `skills_guard` **cannot** be forced past with
`--force`; only `caution` can. So a false positive that reaches `dangerous` is a
hard install failure, not a warning. That is why guard false positives are worth
fixing upstream rather than working around — there is no workaround.

## Setup, not a defect

If the canonical runner reports pytest missing, the profile venv simply lacks dev
extras. Install them into the venv the runner probes, then re-run:

```bash
VIRTUAL_ENV=$HOME/.hermes/hermes-agent/venv $HOME/.hermes/bin/uv pip install pytest pytest-asyncio pytest-timeout
```
