# Retention wrappers that report success while deleting nothing

A wrapper around a deletion CLI has a characteristic failure mode: it reports a
clean run, exits 0, and did nothing — or worse, deleted from somewhere else.
Every defect below was found in ONE session, three of them after the code
already had a passing test suite.

The through-line: **a retention job that silently no-ops looks exactly like a
healthy retention job with nothing to do.** Nobody investigates a green run.

## 1. The CLI rejects your invocation and exits 0

Measured with Hermes: `hermes -p _root sessions prune...` prints an argparse
usage banner and **exits 0**. A wrapper checking only `returncode` reports
success forever.

```python
if out.lstrip().startswith("usage:"):
    raise RuntimeError(f"rejected by the CLI (usage banner): {' '.join(cmd)}")
```

The root/default profile is selected by pointing `HERMES_HOME` at the profile
home with **no** `-p` flag. Impact when this was fixed: 4,610 previously
untouched cron sessions on a 2.7 GB database became eligible.

Generalization: **verify a flag combination against the live binary before
building a wrapper on it.** Do not assume a selector that works for one value
works for all of them.

## 2. The subprocess targets a different database than you inspect

If the parent resolves a path itself and the child resolves via its own
profile/env logic, they can disagree. Then every safety check reads database A
while deletion happens in database B, and the checks pass.

Pin it explicitly:

```python
env = dict(os.environ)
env["HERMES_HOME"] = str(profile_home(profile))
subprocess.run(cmd, env=env,...)
```

Do **not** rely on `HERMES_PROFILE` — the Hermes CLI silently ignores it.
`HERMES_HOME` is what actually decides which database is opened, and inheriting
whatever the scheduler exported is how a run drifts onto a bystander profile.

## 3. Parsing counts out of human-readable output

Two independent bugs here, both silent:

- **Do not infer identity from an id prefix.** Cron ids look like
  `cron_<hash>_<stamp>`, but subagent ids look like `20260701_103305_1d2614`.
  A parser matching `f"{src}_"` reported **0 while 124 sessions were really
  eligible**.
- **The apply path prints different output than the dry-run path.** With
  `--yes` the CLI prints only `Pruned N session(s).` and lists no rows, so any
  listing-based count returns 0 for a _successful_ deletion.

Fix: **reconcile against the database**, not stdout.

```python
before = _source_count(db, src)
subprocess.run(cmd,...)
deleted = before - _source_count(db, src)   # ground truth
```

And when you must parse (dry runs), **raise on unrecognised output** rather
than defaulting to 0:

```python
raise RuntimeError("could not parse output; refusing to report an unverified count")
```

Reporting 0 for text you did not understand is the exact behaviour that makes a
broken pruner look healthy for months.

## 4. Count-based safety invariants on a live database

"Protected row count before == after" is defeated by a concurrent writer: the
service creates one protected row while the buggy delete removes another. The
count matches and the loss is invisible.

Track **identities** and require a subset relation:

```python
before = _protected_ids(db)          # set of ids
...
lost = before - _protected_ids(db)
if lost:
    raise RuntimeError(f"{len(lost)} protected rows disappeared: {sorted(lost)[:5]}")
```

Arrivals during the run are legitimate; disappearances are not. Also use
`COALESCE(source,'')` in the predicate — a NULL column value falls through
`NOT IN (...)` under SQL NULL semantics and would be treated as prunable.

## 5. Ordering: back up before the FIRST destructive step

A backup taken only in the compaction branch is worthless if retention already
deleted rows and then timed out. Retention is destructive on its own.

Correct order for any `--apply` run: disk preflight -> verified backup ->
retention -> invariant check -> compaction -> integrity -> delete backup.

Two corollaries:

- **Evaluate the safety invariant on the failure path too.** A prune that
  deleted rows and _then_ raised is exactly when the check matters most. Catch,
  record the error, run the invariant, and only then re-raise.
- **Never delete the backup in a bare `finally`.** That removes the only good
  copy precisely when compaction failed and the database may be damaged.
  Delete it only on the proven-success path; preserve it on every exception
  regardless of a `--keep-backup` flag.

## 6. No cross-process lock

A duplicate scheduler dispatch or a manual run overlapping the scheduled one
interleaves two multi-step protocols on one file: racing each other's
before/after snapshots, contending during VACUUM, and unlinking a backup the
other run still needs. SQLite serializes individual transactions, not your
protocol.

```python
fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)   # held for the whole run
```

## 7. The launcher hardcodes which profile it maintains

Distinct from #2. There the _subprocess_ drifted onto a bystander database;
here the **launcher itself** never knew which profile it was for.

A recurring job is usually a zero-argument script — cron runs it with no
arguments and exports no profile name. So a launcher written while testing one
target acquires a default:

```python
PROFILE = os.environ.get("DBMAINT_PROFILE", "<profile>")   # WRONG
```

Deployed to a second host, every job on it maintains `a trading agent` — which does not
exist there, so the run does nothing and reports success. Caught only by
deploying to a differently-shaped profile (a _root_ profile on macOS) and
checking what it resolved.

Derive the target from the thing that actually identifies the store, and keep
an explicit override for manual runs and tests:

```python
def _detect_profile() -> str:
    if override:= os.environ.get("DBMAINT_PROFILE"):
        return override
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.name if home.parent.name == "profiles" else "_root"
```

Resolve co-located support scripts through the same variable, so a host running
several profiles picks up its own copy rather than a sibling's.

**The general rule: a fleet-wide script must not carry a default that names one
member.** If the default is wrong, the failure is silent everywhere except the
one host you developed on. Verify by running the resolver on at least two
differently-shaped targets and printing what each resolved — root vs named,
Linux vs macOS.

## Verification traps when checking the rollout

The verification step has its own silent-failure modes:

- **`grep -A<n>` around a job name bleeds into the next record.** Scraping
  `cron list` this way showed a next-run time belonging to a _different_ job,
  making correctly-scheduled jobs look wrong. Read the stored config value, not
  scraped console output, when the number matters.
- **A freshly written schedule reads back null.** `next_run_at` is populated by
  the scheduler on its next tick, tens of seconds later. Do not treat a null
  immediately after registration as a failed write — re-read before concluding.
- **A residual non-zero backlog right after a catch-up is normal**, because
  rows cross the age boundary continuously. Zero is not the success criterion;
  _no protected data lost_ is.

## Verification that actually proves it

Mutation-test every safety guard: revert it and confirm the suite goes red.
In this session that caught a test which passed with the fix removed — the
WAL-checkpoint test only fails when a **second connection is held open**,
because with a single connection the implicit close-time checkpoint masks the
bug (19 MB vs 0 MB in a direct A/B). A guard whose test passes when the guard
is deleted is not a guard.

Also assert on **behaviour, not source text**. A test that greps the source for
`'"--apply", action="store_true"'` still passes if someone adds
`default=True` — the strings survive, the behaviour inverts.
