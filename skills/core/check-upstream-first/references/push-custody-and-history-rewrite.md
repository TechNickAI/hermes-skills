# Push custody: proving code left your machine, and rewriting published history

Companion to `local-patch-custody.md`, which covers WHY a patch must be pushed
the same session. This covers the mechanics of proving it actually was, plus
safely dropping commits from a branch whose sha is currently deployed.

Both failures below are from one occasion and both produced a confident, wrong
"pushed" claim.

## `git push -q` will hide a real failure — never use it

The push appeared to succeed. CI then failed with:

```
fatal: remote error: upload-pack: not our ref <sha>...
```

Cause: the scratch clone had been made with `git clone --shared /path/to/local`,
so its `origin` pointed at **the local checkout it was cloned from**, not GitHub.
The push genuinely succeeded — into a local repository. Exit code 0, `-q`
swallowed the destination, and the object never left the box.

A clone made from a local path inherits that path as `origin`. Always confirm the
destination before believing a push:

```bash
git remote -v # is origin actually the REMOTE?
git push origin HEAD:refs/heads/<branch> # no -q — read the output
git ls-remote <remote-url> refs/heads/<branch> # the sha MUST come back
```

The `ls-remote` is the assertion. Everything before it is a claim.

Generalizes to the whole class: **verify a side effect at its destination, not by
the exit status of the command that was supposed to cause it.**

## `workflow` scope blocks pushes that merely REBASE over workflow files

```
! [remote rejected] refusing to allow an OAuth App to create or update
  workflow `.github/workflows/ci.yml` without `workflow` scope
```

The subtlety: the branch's own commits touched no workflow file. The rebase had
carried upstream commits that did, and the push range included them. Any pushed
range containing a `.github/workflows/**` change needs the scope, regardless of
who authored the change.

Do NOT loosen credentials on the production host to get past this. Move the
objects to a credential that already has the scope:

```bash
# on the host
git bundle create /tmp/x.bundle <base>..HEAD

# on the scoped machine
scp host:/tmp/x.bundle /tmp/x.bundle
git bundle list-heads /tmp/x.bundle # bundle ref may just be HEAD
git fetch /tmp/x.bundle 'HEAD:refs/heads/incoming'
git push origin incoming:refs/heads/<branch>
```

`git bundle list-heads` first — a bundle created from a detached or differently
named branch will not expose the ref name you expect, and
`git fetch <bundle> 'refs/heads/foo:...'` fails with `couldn't find remote ref`.

Check which credential has the scope before choosing where to push from:

```bash
gh auth status # look for 'workflow' in the token scopes line
```

## Dropping an add/delete pair, safely, from a deployed branch

A file added in one commit and deleted in a later one is dead weight in the
history. To drop both:

```bash
git rebase --onto <before-the-add>~1 <the-delete-commit> <branch>
```

**Prove it was a no-op by TREE HASH, not by reading the diff.** The trees must be
byte-identical to the currently deployed commit:

```bash
git rev-parse <deployed-sha>^{tree}
git rev-parse HEAD^{tree} # must match exactly
git diff <deployed-sha> HEAD | wc -l # must be 0
```

Matching tree hashes are the only proof that rewriting history left the shipped
artifact untouched. `git diff --stat` printing nothing is weaker evidence — it is
easy to run against the wrong pair of refs and read the emptiness as success.

### Sequencing when the branch's sha is currently deployed

Rewriting history changes every subsequent sha, so the deployed sha stops being
reachable from the branch. That degrades provenance exactly when you most need it.

- Push the rewritten history to a **NEW branch** first. Never force-push over the
  branch whose sha is live.
- Keep the old release directory on disk — it is the rollback.
- Prefer bundling the drop into an upgrade you are already deploying: the branch
  gets rewritten once, one deploy instead of two, and the new artifact's name
  matches its commit. Doing the cleanup as a standalone force-push spends a
  history rewrite for zero functional gain and orphans the live sha until the
  next deploy.

### Check whether a fork commit became redundant

After rebasing onto a newer upstream, confirm each fork commit still carries
value — upstream may have shipped the same feature under the same name:

```bash
git grep -l "<FEATURE_FLAG_OR_SYMBOL>" <upstream-ref>
```

Empty output means the fork commit is still doing real work. A hit means compare
implementations before carrying yours forward; you may be maintaining a duplicate.
