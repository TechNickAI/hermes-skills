# Merged is not deployed: success signals read from the wrong layer

The skill body covers a setting that fails to take effect. This reference covers the
same disease one layer out: **a change that lands in the repo, reports success at every
checkpoint, and is not running in production.**

Every case here shares one shape — **a success signal collected from a layer that cannot
observe the thing being claimed.** Exit code instead of work product. File presence
instead of runtime state. Merge status instead of deployed behavior.

---

## Case 1: the runner grew siblings and the deploy mirrored one file

A job runner started as a single `jobrun.py`. It later grew two modules it imports,
`jobrun_severity.py` and `jobrun_repair.py`. The host's autosync — written when the
runner was one file — still mirrored exactly that one file.

A PR merged. The deploy reported success. Measured on the host afterwards:

```text
<profile>/scripts/jobrun.py            exit_map: 10 hits   (v2, current)
<profile>/scripts/jobrun_severity.py   MISSING
<profile>/scripts/jobrun_repair.py     MISSING
```

**420 runs since the merge, all success, no errors in any alarm — and the feature that
had just been reviewed and merged was not running.**

The reason it was silent is worth internalizing: the runner imports its modules inside a
`try/except` and degrades instead of crashing, which is correct for availability and
catastrophic for visibility. Absence produced `HAVE_V2 = False`, `sev = None`, and v1
behavior under a v2 filename.

**Probe: ask the module, not the filesystem.**

```python
# not: does the file exist?
# but: what does the loaded runner believe about itself?
print("HAVE_V2 =", getattr(jobrun, "HAVE_V2", "attr missing"))
print("sev     =", getattr(jobrun, "sev", None))
```

**Rule:** when a component grows a dependency, every mirror, deploy, drift check, and
validation path that names the original file becomes incomplete _silently_. Grep for the
old filename and treat each hit as a site that now needs the set.

### The same bug one level up

The first fix detected missing modules on the _host_ but did `continue` when a module was
missing from the _release_. A reviewer flagged it P1, correctly. If a release drops a
module the runner still imports, the host keeps its own older copy — runner and modules
from different revisions, import succeeds, checks report success, production runs an
unreviewed combination.

Reproduced before fixing: repo missing the module, host holding an old copy, runner still
importing it → the drift check returned **0, healthy**.

Also fix the _validation_ path, not just detection. Staging skipped the absent module and
fell back to the live host copy, so the candidate under test was not the combination that
would ship. **An incomplete release cannot be validated, therefore cannot be promoted.**

---

## Case 2: `git push -q` exited 0 and pushed nothing

```bash
git commit -q -F /tmp/msg.md && git push -q 2>&1 | tail -2
# → prints the commit line, exits 0
```

The remote was still on the old SHA. `-q` had swallowed a real rejection.

**Never `-q` a push whose success you are about to report.** Confirm against the remote:

```bash
git ls-remote origin refs/heads/<branch> | cut -c1-40
git rev-parse HEAD | cut -c1-40
# these must match before you say "pushed"
```

---

## Case 3: the self-test polluted the production database

A runner's self-test carefully redirected `STATE_DIR`, `LOG_DIR`, `LOCK_DIR`, the ledger
and the ledger lock, precisely so its deliberately-failing fixtures could not be mistaken
for real incidents. An incident database was added later and was **not added to that
list**.

Result: every `--selftest` run wrote `st-fail` and `st-timeout` as permanent open
incidents into whatever profile ran it. Measured: **2 phantom incidents on 12 of 12
profiles**, for jobs that exist nowhere.

**Rule:** an isolation list is a set that must be maintained. Any new persistent store
added to a component silently escapes the existing test isolation. The fix shape is an
env override (`JOBRUN_INCIDENT_DB`) honored by the path resolver, set alongside the other
redirects.

It was found by a monitor reporting an open incident on a job that did not exist — which
is the argument for pointing a new monitor at your own work first.

---

## Case 4: `outcome='completed'` for an agent that changed nothing

A dispatched repair agent investigated correctly, found the failing script had no
repository to open a PR against, and refused to fabricate a change:

> "That's manufacturing a change, not fixing one. I stopped instead."

Recorded as `outcome='completed'` → incident moved to `review_pending`, a state meaning
"a patch awaits review" when no patch existed. **An honest refusal and a landed fix were
indistinguishable in the database**, and only the refusal leaves work still needing a
human.

Root cause: treating **process exit status as work product**. A subprocess exiting 0 tells
you the agent ran, never what it did.

Fix: make the worker _declare_ its outcome in a parseable line, and parse it rather than
infer:

```text
REPAIR-OUTCOME: patched <pr-url>       code changed, PR opened
REPAIR-OUTCOME: spec-defect <why>      the spec is wrong, not the code
REPAIR-OUTCOME: environmental <why>    credential/outage/disk, unpatchable
REPAIR-OUTCOME: not-reproducible <why> did not fail when run
REPAIR-OUTCOME: declined <why>         deliberately made no change
```

Only `patched` routes to review. A missing or invented declaration **fails closed** —
never assumed fixed. Read the **last** declaration in the output, so one quoted
mid-report cannot outrank the final verdict.

---

## Case 5: a test that only passes on one machine

Three tests failed locally and passed in CI. They compared against `HERMES_HOME` and fell
back to a host-specific profile path that does not exist elsewhere — so on any other
machine they compared against the wrong profile entirely.

Not a bug in the change. **A test whose result depends on the machine it runs on proves
nothing about the code**, in either direction: it will also pass spuriously.

Before accepting or dismissing a local failure, check whether the test resolves paths
from the environment, and confirm the pre-existing baseline by stashing your change and
re-running.

---

## The generalized check

Before reporting anything delivered, name the layer your evidence comes from and ask
whether that layer can observe the claim:

| Claim                      | Insufficient evidence      | Sufficient evidence                           |
| -------------------------- | -------------------------- | --------------------------------------------- |
| "It's pushed"              | `git push` exit 0          | `git ls-remote` SHA matches local HEAD        |
| "It's deployed"            | PR merged, deploy exit 0   | the running component reports its own version |
| "The feature is on"        | flag file / config present | the consumer reports its own resolved state   |
| "The agent fixed it"       | subprocess exit 0          | a parsed declaration of what it did           |
| "The job is healthy"       | no alarms fired            | the alarm path itself exercised recently      |
| "Tests confirm the change" | CI green                   | the test fails without the change             |

The last row is the cheapest and most skipped: **run the test against the unpatched code
and watch it fail.** A test that has never failed has never been shown to test anything.
