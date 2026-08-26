# Green because the check only looked at what it already knew about

Read this when a check, sync, self-test, or monitor reports SUCCESS and you are
about to repeat that success to someone. This is the inverse of most of
`is-it-really-broken`: not a false BROKEN, but a **false GREEN produced by an
incomplete enumeration**.

## The shape

The code is correct. It parses correctly, compares correctly, exits 0 correctly.
The defect is that the list it iterated was written when the system was smaller,
and the system grew. Nothing errors, because the things outside the list do not
appear as failures — they do not appear at all.

This is much harder to catch than a bug, because **every signal you have says
healthy**, and a code review of the check finds nothing wrong with the check.

## Three instances from one session

All three shipped, all three passed review, all three reported success over a
real defect.

**1. A self-test wrote fixtures into the production database.**
The self-test isolated `STATE_DIR`, `LOG_DIR`, `LOCK_DIR`, the ledger, and the
ledger lock — a careful, deliberate list. An incident database was added to the
system later and was not added to that list. Every self-test run then recorded
its deliberately-failing fixtures (`st-fail`, `st-timeout`) as permanent open
incidents in whatever profile ran it. Measured: **2 phantom incidents on 12 of
12 profiles**, for jobs that exist nowhere.

**2. A deploy sync mirrored one file after the code grew into three.**
An autosync was written when the runner was a single `.py` file. The runner later
grew two imported modules. The merge reported success, the host ran the new
runner — and the modules were absent. Because the runner imports them defensively
(`try/except`, degrade rather than crash), it silently fell back to old behavior.
**420 runs, all success, no errors, and the feature that had just been reviewed
and merged was not executing.**

**3. A monitor summarized the subset it happened to read.**
Reported `552 runs, 0 failures` while covering 31 of 54 jobs, with a live job
failing 5 runs in a row unseen. Always print the denominator next to the count:
a rate without its population is not a measurement.

## Why availability-first error handling hides it

Instances 2 and 3 share an aggravating factor worth naming: the system was
_designed_ to degrade rather than fail. That is usually correct for uptime — you
do not want every money job dead because one import broke — but it converts a
loud failure into a silent one.

**Any `try/except ImportError: fallback` or `if not present: continue` is a place
where a defect can live indefinitely without producing a single error.** When you
write one, you owe it a corresponding check that asserts the good path is
actually active — not merely that nothing crashed.

Concretely: after "did it run?" always ask **"did it run the way the merge
intended?"** A version string, a feature flag readback, a capability probe. In
instance 2 the one-line probe that would have caught it was asking the loaded
module whether its optional sibling was present:

    HAVE_V2 = attr missing
    sev module = None

## The remedies

- **Treat any hardcoded list of things-to-handle as a liability with an expiry.**
  Name it as a constant (`JOBRUN_MODULES`, `ISOLATED_DIRS`) rather than inlining
  it, so growth has one obvious place to land, and so a test can assert the list
  matches reality.
- **Derive the list from the system where possible.** Enumerate the directory,
  read the registry, parse the imports — anything that grows automatically beats
  a list a human must remember to extend.
- **Test the absence case explicitly.** Delete one member and assert the check
  goes red. Instance 2's fix shipped with exactly this test, and it immediately
  caught a second bug: the modules were being _detected_ and then never synced,
  because the repair branch was gated on a condition that did not include them.
- **A missing member of a required set is an ERROR, not a skip.** A reviewer
  flagged this as P1 on the fix for instance 2: handling "module absent from the
  release" with `continue` reproduced the original bug one level up. Reproduced
  before fixing — the check returned **0, healthy**, on a genuinely broken
  release.

## The question to carry

When something passes, "did it pass?" is the wrong question. Ask:

> **What population did this examine, and who chose that population, and when?**

If the answer is "a list someone wrote at some point," find out when, and compare
it against the system as it exists now.
