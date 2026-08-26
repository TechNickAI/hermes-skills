# When a component grows siblings, the sync that mirrors it does not know

A merge can report success, deploy cleanly, run thousands of jobs without a
single error — and the merged behaviour can be completely absent.

## The measured case (2026-08-24)

A scheduled-job runner grew from one file into a small package: `jobrun.py`
began importing `jobrun_severity` and `jobrun_repair`. The PR merged, the deploy
reported success, and on the host:

```
~/.hermes/profiles/<p>/scripts/jobrun.py          exit_map: 10 hits   (v2)
~/.hermes/profiles/<p>/scripts/jobrun_severity.py MISSING
~/.hermes/profiles/<p>/scripts/jobrun_repair.py   MISSING
```

420 runs since the merge, **all success**, nothing in any alarm — while the
feature that had just been reviewed and merged was not running at all.

The host's mirror/autosync watchdog was written when the runner was a single
file and still mirrored exactly that one file. Nothing in it was wrong; it was
simply complete for a shape the code had outgrown.

## Why nothing alarmed: defensive imports hide the gap

The runner imported its modules inside a `try/except` so a partial install would
degrade rather than take every job down. That is the right call for availability
and the wrong one for visibility:

```python
HAVE_V2 = False   # silently
sev = None        # every card renders with the OLD severity logic
```

**Availability-first error handling converts a deployment failure into an
invisible behaviour change.** The system keeps working, keeps reporting success,
and quietly does the old thing.

This is the same class as a self-test that isolates the ledger but not a
database added later: _the check reported success because it was only looking at
the thing it knew about._

## Detection: assert BEHAVIOUR, not file presence

`git rev-parse` on the release, or a `grep -c` for a new symbol in the entry
point, both pass here. Three layers must be asserted separately:

1. The **source** moved.
2. The **installed** artifact matches (metadata, siblings, permissions).
3. The **changed code path actually engages** — probe a flag the feature sets:

```python
import jobrun
print(getattr(jobrun, "HAVE_V2", "attr missing"))  # -> "attr missing"
print(getattr(jobrun, "sev", None))                # -> None
```

Add such a probe to the deploy check for any feature that can degrade silently.

## Fixing the sync: name the unit, gate on the whole unit

Treat the entry point and the modules it imports as **one unit**:

```python
JOBRUN_RUNNER  = "jobrun.py"
JOBRUN_MODULES = ("jobrun_severity.py", "jobrun_repair.py")
```

Four places must change together, and skipping any one leaves a half-fix:

1. **Detect** — a missing _or_ drifted module is drift. Report why it matters
   ("the runner silently falls back to the old behaviour without it"), not just
   that a file differs.
2. **Repair** — same direction (repo → host, never the reverse), same atomic
   copy.
3. **Validate** — stage the modules _alongside_ the candidate entry point.
   Previously validation ran the new entry point against whatever modules
   happened to be on the host, which is not the combination that will run.
4. **Gate** — the validate-before-promote branch must trigger on module drift
   too:

```python
if repair and (runner_stale or stale_modules or stale_specs):
```

Without that last line the modules were correctly _detected_ and then never
_synced_. The new tests caught it; reading the diff did not.

## Test-writing traps hit while proving this

**A comment-only change may be deliberately tolerated.** The first stale-module
test appended `# host-side drift` and asserted drift was reported. It failed —
and the code was right. Report mode compared _significant_ content so a reworded
comment never pages anyone, while repair mode compared exact bytes. The test
must make a **significant** change (`HOST_ONLY_DRIFT = True`), or it is testing
the wrong thing and fails in one mode while passing in the other. Read the
comparison function before asserting on drift.

**Seed the fixture as a genuinely in-sync pair.** A shared fixture that copies
only the entry point makes every new module test start from an accidental
missing-file state, so the tests pass for the wrong reason. Copy the whole unit
into both trees; tests that care about absence delete a file explicitly.

**Some tests are machine-dependent by design.** A mirror test that resolves
`HERMES_HOME` and falls back to a specific profile path will fail anywhere that
is not the production host — it is comparing against a tree that does not exist
locally. That is not a real failure; say so explicitly rather than "fixing" it,
and note that it needs to run in CI on the right host.

## Repo-owned runtimes: fix at the source, never on the host

When a host's runtime is mirrored from a repository with a tripwire test, a
host-side `cp` is reverted by design and is not a fix. Change it via PR to the
owning repository. Equally, when porting an upstream change into such a repo,
its local deltas are usually **deliberate** — read them before overwriting.

In this case the host copy carried a validation-suppression guard so a deploy's
own dry-run could not page the owner. Preserve such deltas verbatim and prove it
in both directions:

```
env set   -> notify_failure() == "suppressed_validating"
env unset -> notify_failure() reports a real status
```

**Do not splice Python source with regex.** An attempt to re-apply those guards
by regex produced an unterminated docstring that only surfaced at import. Use
exact string anchors taken from the file, `ast.parse()` the result before
writing, and then exercise the behaviour — a diff that looks right can still be
syntactically dead.
