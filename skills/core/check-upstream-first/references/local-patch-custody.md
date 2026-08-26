# Local patch custody on an editable checkout

What happens AFTER you decide a local patch is justified. The main skill stops at
"only if genuinely unfixed upstream — design a patch." This is the discipline for
the patch's whole life, and it is where a real failure happened.

Source session: 2026-08-14. the operator: **"GRRRRRRRR WHY DO WE HAVE LOCAL COMMITS?
This should not be happening."** He was right, and they were mine.

## The failure, exactly as it occurred

```
<sha> HEAD@{2026-08-07}: commit: fix(skills): resolve GitHub identifiers before skills.sh
<sha> HEAD@{2026-08-07}: commit: fix(skills): reject foreign identifiers in ClawHub
<sha> HEAD@{2026-08-07}: commit: fix(skills-guard): allow documented skill operations
<sha> HEAD@{2026-08-04}: clone: from github.com:NousResearch/hermes-agent.git
```

Cloned Aug 4 during a fleet upgrade. Three commits Aug 7. Nothing after. Seven
days later they existed in **exactly one place on earth**: `main` in one working
directory. Not upstream, not on the user's own fork, no branch, no stash, no PR.

Three compounding defects, each independently wrong:

1. **Committed directly to `main`** on a branch that tracks origin — guarantees
   permanent divergence and a collision at every future upgrade.
2. **Never pushed** — one `rm -rf`, disk failure, or "let's re-clone this" and
   good work is gone with no copy anywhere.
3. **Never PR'd** — the fixes were the entire point; sitting local they help
   nobody, including us.

The fixes themselves were legitimate (one was a destructive-overwrite bug with an
open upstream issue). **Good code abandoned in the wrong place is still a
failure.** The code quality is not the lesson.

## Why this is worse on an editable install

`pip install -e` means the checkout IS the deployment. Verified:

```bash
cd ~/.hermes/hermes-agent && export PATH="$PWD/venv/bin:$PATH"
python -c "import gateway; print(gateway.__file__)"
# -> ~/.hermes/hermes-agent/gateway/__init__.py
```

So local commits on `main` are not a git-hygiene nit. They are **modified
production code running live, with no upstream, no review, and no backup.** On
this host four gateways (the operations agent/a personal-assistant agent/a research agent/a monitoring agent) were running patched
`skills_guard` + `skills_hub` while the rest of the fleet was not — undocumented
fleet drift, self-inflicted, invisible until someone ran `git log origin/main..HEAD`.

This is the same class of finding that would warrant paging the captain if
discovered on a fleet box. Hold your own host to that standard.

## Rules

**Never commit to `main` on a tracking checkout.** Branch first, always:

```bash
git checkout -b fix/<short-slug>
```

**Push the same session you commit.** Non-negotiable. A local-only commit is
unbacked work, and "I'll push it later" is how a week passes. Pushing is
reversible and costs nothing:

```bash
git push -u fork fix/<short-slug>   # user's fork, not upstream main
```

**Every local patch carries an exit plan, recorded at creation:** upstream PR,
or an explicit dated decision to carry it. A patch with no exit plan becomes
permanent drift by default.

**A local patch is an ADMISSION, not an achievement.** The goal is always to
delete it by landing the fix upstream. Track it as debt.

## Detection — run this before any upgrade, and periodically

The whole audit is two commands. It should be reflex, not a special occasion.

```bash
cd ~/.hermes/hermes-agent
git fetch origin main -q
git rev-list --left-right --count origin/main...HEAD | awk '{print "behind:",$1," ahead:",$2}'
git log origin/main..HEAD --format="%h | %an | %ad | %s" --date=short
```

`ahead: 0` is the only healthy answer on a tracking checkout.

Across the fleet, catching drift and dirty trees together:

```bash
for h in hex ali a legacy-runtime agent thomas gil a personal-assistant agent; do
  printf "%-9s " $h
  ssh -o ConnectTimeout=8 -o BatchMode=yes $h '
    if [ -d ~/.hermes/hermes-agent/.git ]; then
      cd ~/.hermes/hermes-agent
      echo "$(git rev-parse --short HEAD) $(git branch --show-current) dirty=$(git status --porcelain|wc -l|tr -d " ")"
    else echo "NO GIT CHECKOUT"; fi' 2>&1 | tail -1
done
```

Real output showed **three different HEADs, uncommitted changes on three boxes,
and one host with no checkout at all.** Version skew across a fleet is normal
drift; uncommitted working trees are unowned changes nobody can attribute.

## Proving a commit exists nowhere else

Before deciding whether a local commit is safe to reset, establish custody. All
three checks, because each answers a different question:

```bash
# which local/remote refs contain it
git branch -a --contains <sha>

# is it upstream?  "No commit found for SHA" == not there
gh api repos/NousResearch/hermes-agent/commits/<full-sha> --jq .sha

# is it on the user's own fork?
gh api repos/<user>/hermes-agent/commits/<full-sha> --jq .sha

# was it ever referenced by a PR?
gh api 'search/issues?q=repo:NousResearch/hermes-agent+<full-sha>' --jq '.total_count'
```

`git log --grep=<subject> origin/main` is a weak check on its own — upstream may
have fixed the same bug with different wording, and a subject match may be
coincidence. Confirm by reading the actual code path on current `main`.

## The other variant: patches you did NOT write

The audit above assumes the abandoned work is yours. Increasingly it is not —
an agent with terminal access can patch its own running source, and on an
editable install that is a live production deploy with no branch, no review,
and no author recorded anywhere except the log.

Found 2026-08-19 while recovering a fleet member: four modified files in its
checkout, uncommitted, on the pinned release branch, touching the exact gating
code implicated in the incident being investigated.

**Attribute before you act.** File mtimes plus the agent log answer it:

```bash
cd ~/.hermes/hermes-agent && git status --porcelain
for f in $(git diff --name-only); do stat -f "%Sm %N" "$f"; done

# what was that agent doing at that minute?
awk '$0 >= "<mtime minus 2min>"' ~/.hermes/logs/agent.log \
  | grep -iE "tool (patch|edit|write) (completed|returned)"
```

A run of `tool patch completed` entries under one session id, timestamped to
the same minutes as the file mtimes, is the attribution. Note that mtimes can
span _different days_ — a subset may predate the incident, meaning the
uncommitted state accumulated across sessions and nobody noticed.

**Verify the module that actually loads.** The checkout path and the imported
module name may differ (`plugins.platforms.telegram.adapter` vs a
`hermes_plugins.*` runtime alias). Confirm what the interpreter really reads,
and whether the patch is in it:

```bash
./venv/bin/python -c "
import importlib, inspect
m = importlib.import_module('plugins.platforms.telegram.adapter')
print('LOADED FROM:', m.__file__)
print('HAS PATCH:', '<distinctive comment>' in inspect.getsource(m.TelegramAdapter.<method>))
"
```

**Test before trusting, and falsify before shipping.** Unattributed patches may
be entirely correct — these were — but a green suite proves nothing if the new
test passes vacuously. Revert ONLY the patched file to its committed state,
re-run, and confirm the test FAILS; then restore:

```bash
cp <file> /tmp/patched.bak
git show HEAD:<file> > <file>
./venv/bin/python -m pytest <testfile> -q      # expect the new case to FAIL
cp /tmp/patched.bak <file>
git diff --stat <file>                          # confirm restored
```

If it passes with the patch reverted, the test does not exercise the fix.

**Report, do not silently adopt or silently revert.** Uncommitted edits to live
production code are a custody finding regardless of quality. State who made
them, when, what they do, whether they pass, and that they remain uncommitted —
then let the owner decide between committing them properly and reverting.
Restarting the service without saying so ships unreviewed code by omission.

## Recovery order when you find abandoned local commits

Reversible first. Do not lead with the destructive step.

1. **Push to a branch on the fork immediately.** Stops the
   one-`rm -rf`-from-gone problem. Locks in no decisions.
2. **Verify the fixes still apply** to current upstream `main` before PR'ing.
   After ~22,000 commits the surrounding file has usually moved; upstream may
   have solved part of it differently. (Observed: upstream added the same helper
   method to a _different_ source class while the buggy one was untouched.)
3. **Open the PR**, citing any related open issue.
4. **Only then** reset local `main` to origin so the checkout stops diverging.

Never propose step 4 first, and never propose dropping commits until you have
confirmed upstream actually solved the same problem in the same place.

## Reporting shape

When you find your own abandoned work, say plainly that it is yours. The reflog
names the author and the dates; hedging in front of evidence that specific reads
as evasion. Then give the recovery options ordered by reversibility.

Also: if memory already flagged the condition (it did here — _"Current
skills_guard fixes are local/unpushed"_), recording a symptom and not acting on
it is worse than never noticing. A memory entry is not a resolution.

## Checklist

- [ ] Branch created before the first commit; never commit to tracking `main`
- [ ] Pushed to the fork in the same session as the commit
- [ ] Exit plan recorded at creation (upstream PR, or dated carry decision)
- [ ] `git rev-list --left-right --count origin/main...HEAD` run before any upgrade
- [ ] Editable install verified — know whether the checkout IS the deployment
- [ ] Fleet swept for divergence AND dirty working trees, not just versions
- [ ] Custody proven (refs + upstream + fork + PR search) before any reset
- [ ] Uncommitted edits found on a fleet box ATTRIBUTED (mtimes + agent log)
      before acting, and reported as a finding even when the code is correct
- [ ] Patch confirmed present in the module the interpreter actually loads
- [ ] Any accompanying test falsified (revert file → test FAILS → restore)
      before the service is restarted
- [ ] Local patch tracked as debt with a plan to delete it
