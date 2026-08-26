# Running a fork as "release tag + reviewed patches"

The sanctioned shape when a local patch is genuinely justified and must run on a
fleet. Companion to `local-patch-custody.md`: that file covers the custody of an
individual patch, this one covers the _deployment model_ that carries patches
across hosts without becoming a fork you regret.

Source session: one occasion. the operator: _"I don't want to be running a fork of Hermes.
That's going to be a PITA."_ then, after seeing the release-pinned shape,
_"I'd prefer to stick to releases."_

## Base on the RELEASE TAG, never on `main`

The number that decides this: the live checkout was **21,966 commits behind
`origin/main`** but only **one release behind the latest tag**, and that tag was
itself only **236 commits** off main.

Quoting the distance-from-`main` figure as the upgrade cost is misleading and
scares everyone off a routine upgrade. Always compute both:

```bash
gh api repos/<org>/<repo>/releases/latest --jq '.tag_name + " " +.published_at'
gh api repos/<org>/<repo>/compare/<tag>...main --jq '{ahead:.ahead_by, behind:.behind_by}'
```

Tracking `main` on a repo merging ~1,400 PRs per release means rebasing against
constant churn. Tracking tags makes the upgrade bounded and schedulable.

**Peel the tag to a commit** — an annotated tag's `object.sha` is the tag object,
not the commit:

```bash
TAGSHA=$(gh api repos/<org>/<repo>/git/ref/tags/<tag> --jq '.object.sha')
COMMIT=$(gh api repos/<org>/<repo>/git/tags/$TAGSHA --jq '.object.sha')
gh api repos/<user>/<repo>/git/refs -f ref="refs/heads/fleet/<tag>" -f sha="$COMMIT"
```

## Fork sync: `gh repo sync` can silently no-op

It printed nothing and left the fork's `main` three months stale. Use the API and
**verify the sha actually changed**:

```bash
gh api repos/<user>/<repo>/merge-upstream -f branch=main
gh api repos/<user>/<repo>/commits/main --jq '.sha[0:10] + " " +.commit.committer.date'
```

## Every patch carries a removal condition

Record it in the docs at creation, in a table:

| Patch             | Why local                                                            | Removal condition                                                     |
| ----------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `fix(gateway): …` | Upstream issues #A/#B open; PR #C conflicted+unreviewed since <date> | Upstream merges an equivalent fix → drop and rebase onto next release |

A patch with no exit path is how a fork becomes permanent tax. Drop patches at
rebase time when upstream landed them — check each condition, do not carry by
reflex.

## Verify in independent layers — passing one proves nothing about the others

On an editable install the checkout IS the deployment, so disk state and process
state diverge silently. The symptom of a missed restart is identical to "the
patch didn't work." Build the verifier around that:

| Layer            | Check                                                  | Why the obvious check is insufficient                          |
| ---------------- | ------------------------------------------------------ | -------------------------------------------------------------- |
| `disk.commit`    | HEAD == expected sha                                   | —                                                              |
| `disk.marker`    | patched SOURCE contains the new symbol                 | a sha can be right while a bad cherry-pick left the code wrong |
| `disk.base`      | `git merge-base --is-ancestor <tag> HEAD`              | a branch NAME is not a fact; prove lineage to the release      |
| `proc.<profile>` | each gateway PID younger than the patched file's mtime | **catches "deployed but not live"**                            |
| `cfg.<profile>`  | the flag gating the patch is actually enabled          | the patch is inert without it                                  |

```bash
# lineage proof + exactly what rides on top of the release
git merge-base --is-ancestor <tag> HEAD && git log --oneline <tag>..HEAD
```

**Validate the verifier in BOTH directions before trusting it.** Run it against
an unpatched checkout and confirm it exits non-zero with `disk.marker ABSENT`;
run it against the patched tree and confirm PASS. A check that cannot fail is
decoration.

## Deploy script must REFUSE, not reset

Hard-fail (never `git reset --hard` past) on:

- a dirty working tree — someone hand-edited production; that may be an
  emergency fix made under pressure
- commits absent from the pinned branch — the exact failure in
  `local-patch-custody.md`

Destroying a human's un-backed work to satisfy a deploy script is worse than a
failed deploy.

Reinstall the editable package only when dependency metadata moved:

```bash
git diff <old> <new> --stat -- pyproject.toml setup.py
```

A minor release can change far more than a version string — v0.20.0→v0.20.1 moved
`cryptography` 48→50, `aiohttp` 3.14.1→3.14.3, `python-telegram-bot` 22.6→22.8
for CVEs. Reinstall **with the extras preserved** (`uv pip install -e '.[all]'`),
then re-read the installed versions; do not assume.

Note: a uv-managed venv has **no `pip` module** (`No module named pip`). Use
`uv pip install` with `VIRTUAL_ENV` set.

## Separating your regression from pre-existing failures

A full suite on a real release will have failures that are not yours. Do not
hand-wave this — prove it by running the SAME test list against the stock tag and
the patched tree in the SAME venv, then `diff` the two result files:

```
### DIFF (any line here = caused by our patch)
IDENTICAL - no regression from the patch
```

13 full-suite failures were all present on unmodified v0.20.1. Without the
side-by-side, that is indistinguishable from "my patch broke 13 tests."

## Staged rollout by blast radius

Message-deletion behavior lands in real people's chats. Order by whose chat
breaks, not by convenience:

1. operator's own agent — gated on a **live** multi-tool turn, observed
2. remaining operator-owned profiles on the same host — 24h clean
3. operator-controlled remote hosts — verify pass each
4. client-owned agents — explicit owner notice FIRST

Hosts with no git checkout cannot take a source patch; report them as
**excluded-by-install-method**, not as pending.

## Checklist

- [ ] Branch based on the release TAG, peeled to a commit, not on `main`
- [ ] Distance quoted from the TAG, not from `main`
- [ ] Fork sync verified by sha change, not by command exit
- [ ] Every patch has a removal condition recorded in docs
- [ ] Verifier checks disk / lineage / process / config separately
- [ ] Verifier validated in both directions before use
- [ ] Deploy script refuses dirty trees and unpushed commits
- [ ] Dependency metadata diffed; extras preserved on reinstall
- [ ] Pre-existing test failures proven by stock-vs-patched diff
- [ ] Rollout staged by blast radius, client-owned agents last
