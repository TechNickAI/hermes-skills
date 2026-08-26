# Determining what is ACTUALLY upstream

The question "is this fix already upstream?" decides whether you write a PR, skip
one, or carry a fork patch forever. It is easy to answer confidently and wrongly.
Both directions of error are expensive:

- **False "already upstream"** → you talk the operator OUT of a real contribution.
- **False "not upstream"** → you write a duplicate PR and look careless.

Both happened in a single session on 2026-08-16.

## Trap 1: `origin` in a fork clone is the FORK, not upstream

Clone `github.com/<you>/<project>` and `origin/release/vX` is **your fork's mirror
of that branch** — which already contains your own commits. Diffing against it
reports "identical, nothing to PR" for every local fix you have.

```bash
# WRONG — origin is your fork
git diff origin/release/v3.8.50 mybranch

# RIGHT — add the real upstream and compare against that
git remote add upstream https://github.com/<UPSTREAM_OWNER>/<repo>.git
git fetch upstream release/v3.8.50
git diff upstream/release/v3.8.50 mybranch
```

Symptom that should stop you: a fix you _know_ you wrote locally reports as
already present upstream, and a cherry-pick of it conflicts. If it were truly
upstream, there would be nothing to conflict with.

**Assert the remote before trusting any comparison:**

```bash
git remote -v | grep -E '^(origin|upstream)'
```

If `origin` points at an account you control, it is not upstream. Say which
remote you compared against when you report the result.

## Trap 2: `git cherry` / patch-id is unreliable after a rebase

`git cherry <upstream> <branch>` marks commits with `-` (equivalent patch already
upstream) or `+` (not upstream). After a rebase, context lines shift and patch-ids
stop matching the way you expect.

Measured in one session: `git cherry` reported **all four** local commits as
already upstream, including one whose fix was demonstrably absent — the buggy
line was still sitting in the upstream file.

**Do not use commit-level heuristics to answer a file-level question.**

## Ground truth: compare file CONTENT

```bash
# Is the fix present upstream? Ask the file, not the history.
diff <(git show upstream/release/vX:path/to/file.ts) \
     <(git show mybranch:path/to/file.ts) >/dev/null \
  && echo "IDENTICAL -> nothing to PR" \
  || echo "DIFFERS -> real delta"

# Even better: grep for the specific symbol/expression the fix introduces,
# and for the buggy expression it removes. Check BOTH directions.
git show upstream/release/vX:src/lib/db/stats.ts | grep -c "isDbstatAvailable"
git show upstream/release/vX:src/lib/db/cleanup.ts | grep -c "Math.floor(Date.now() / 1000)"
```

A new-symbol grep returning 0 upstream and >0 locally is decisive. So is the
buggy expression still being present upstream.

## The whole-fork version of the question

To enumerate every real delta a fork carries:

```bash
git fetch upstream <release-branch>
git rev-list --left-right --count upstream/<branch>...<forkbranch>   # left=upstream-only right=ours
git diff --stat upstream/<branch> <forkbranch>                        # the actual files
```

If `--stat` returns hundreds of files for a fork you believe carries a handful of
patches, you are comparing against the wrong ref. Recheck the remote before
reasoning about the output.

## Checklist

- [ ] `git remote -v` inspected; upstream remote is the real upstream owner
- [ ] Comparison run against `upstream/<branch>`, never `origin/<branch>` in a fork
- [ ] Verdict established by FILE CONTENT (diff or symbol grep), not `git cherry`
- [ ] Checked both directions: new symbol absent upstream AND old buggy form present
- [ ] Reported which remote and which method produced the verdict
