# Pushing deploy branches from a scratch clone on the server

Deploy work often happens in a throwaway clone on the target host (rebasing,
patching, building an artifact). Getting those commits to GitHub has two silent
failure modes — both hit on one occasion, both cost a CI round-trip.

For the staging-script adaptation traps (env file, entry path, artifact layout)
see `references/adapting-stage-and-smoke-to-a-real-unit.md`.

## 1. `git push -q` hid a rejection — and the "push" went to the wrong place

A scratch clone made with `git clone --shared /path/to/local/checkout` has
`origin` pointing at **the local directory**, not GitHub. So:

```bash
git push -q origin HEAD:refs/heads/my-branch # exit 0, prints nothing
```

...reported success while pushing to the local checkout. The CI build then
failed with `fatal: remote error: upload-pack: not our ref <sha>`, because the
sha never reached GitHub.

Two rules:

- **Never `-q` a push you intend to verify.** Read the output.
- **Assert the ref landed on the REAL remote**, never infer it from exit code:
  ```bash
  git remote -v # know where origin actually points
  git ls-remote https://github.com/<owner>/<repo>.git refs/heads/<branch>
  ```
  Empty output means the branch does not exist there, whatever the push said.

## 2. Token lacked `workflow` scope

A rebase onto a newer upstream base carries upstream's `.github/workflows/`
changes. Pushing that with a token missing the `workflow` scope is refused:

```
! [remote rejected] HEAD -> <branch> (refusing to allow an OAuth App to create or
  update workflow `.github/workflows/ci.yml` without `workflow` scope)
```

**Do not weaken or re-provision credentials on the production host to work
around this.** Move the commits to a machine whose token already has the scope
(`gh auth status` lists them) and push from there:

```bash
# on the server
ssh host 'cd /tmp/work && git bundle create /tmp/x.bundle <upstream-base>..HEAD'
scp host:/tmp/x.bundle /tmp/

# locally, in a fresh clone of the real remote
git fetch /tmp/x.bundle 'HEAD:refs/heads/incoming'
git log --oneline origin/<base>..incoming # verify exactly your commits
git push origin incoming:refs/heads/<branch>
git ls-remote origin refs/heads/<branch> # confirm
```

`git bundle list-heads /tmp/x.bundle` tells you the ref names inside — a bundle
created from a detached/renamed branch may only carry `HEAD`, so
`git fetch <bundle> '+refs/heads/foo:...'` fails with `couldn't find remote ref`
while `'HEAD:refs/heads/incoming'` works.

## Before pushing, verify the branch is what you think

Two cheap assertions that catch a bad rebase:

```bash
git log --oneline origin/<base>..incoming # ONLY your commits, expected count
git ls-tree --name-only incoming:.github/workflows/ | grep -c <dropped-file>
```

The second matters when the branch deliberately **drops** something (e.g. a
fork-local CI workflow). Confirm the absence rather than assuming the rebase
preserved your intent.
