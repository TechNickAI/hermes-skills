# Verifying bot findings before you merge

Measured on one run merging a skill PR with 7 outstanding review comments and all
checks green. Green checks plus outstanding comments is not a merge signal — the
comments have to be adjudicated, and most of them were already dead.

## First: which comments name files that still exist?

A branch that refactors mid-review strands every comment written against the old
layout. Here a commit ("make this a process, not a Python library") collapsed
three modules into one, and **3 of 7 comments pointed at deleted files**
(`scripts/checks.py`, `scripts/eval_harness.py`).

Cheapest possible triage — run this before reading a single line of comment prose:

```bash
gh pr view <N> --repo $R --json files -q '.files[].path'
```

Set aside every comment naming a path not in that list. This is a stronger filter
than the usual stale-line-anchor check, because the finding cannot be
re-verified at all — there is no code to run.

If the PR BODY still advertises the deleted files (this one described
`checks.py` and `eval_harness.py` in detail), the body is stale too. Say so
rather than assuming the described artifacts shipped.

## Then: execute the survivors, do not read them

For each finding on a file that still exists, run the exact input the bot
describes. Import the module and call the function directly:

```python
import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location("m", "path/to/module.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def cap(fn, *a, **k): # capture printed output
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            r = fn(*a, **k)
        return (buf.getvalue() or "") + ("" if r is None else str(r))
    except Exception as e:
        return f"RAISED {type(e).__name__}: {e}"
```

Check `inspect.signature()` first — guessing arity wastes a round trip
(`selection() missing 1 required positional argument: 'periods'`).

Assert on the OUTPUT STRING, not your reading of the branch:

```python
out = cap(m.selection, float("nan"), 100, 252)
print(">>> claims it clears:", "clear" in out.lower())
```

Four findings resolved in one script this way — all already fixed on the branch
(NaN inputs now refused, an exactly-cancelling remainder now caught, a
dead-end grouping path now running the tail check, and a
`not (flip_a and flip_b)` guard no longer claiming "only one flips" when
neither does). Reading the diff would have left each arguable.

## Report the finding that does not reproduce

One finding claimed a ledger's `scale` denominator collapses so a $1 error reads
as 100%. Actual output: `residual 1.00 (0.00% of scale)` — scale is the largest
term, not the collapsed net. The behavior it flagged (reporting DOES NOT CLOSE at
$1) turned out to be correct-by-design: passing the `materiality` argument
returned "closes within the stated materiality."

Say "the specific mechanism did not reproduce" plainly. Do not accept a false
premise into the record, and do not silently drop the comment either.

## Always run the negative control

Verifying only that the bad input is now rejected proves half the story. Also run:

- a genuinely broken input, to prove the check still FIRES
- the same input with the tolerance/materiality parameter set, to prove the
  suppression path works
- the skill's / repo's own self-test and full suite

A guard that rejects everything passes every "is it fixed?" probe and protects
nothing.

## Clean generated artifacts before trusting a scanner

Running the repo's scripts from a scratch clone left `__pycache__/*.pyc` files
whose frozen absolute path contained the working directory name. The repo's own
PII scanner then reported `blockers=1... 'bosun'` — an apparent secret leak,
seconds before merge.

The string was `/private/tmp/the operations agent-repo-review/.../decompose.py` inside a
gitignored `.pyc`, never in the PR. Diagnose in this order:

```bash
grep -n -i '<term>' path/to/source.py # is it in the SOURCE at all?
git check-ignore -v path/to/artifact.pyc # is the hit even tracked?
find. -name __pycache__ -type d -exec rm -rf {} +
```

Then re-run and confirm the count returns to baseline. A scanner hit on a
generated artifact is a measurement bug until proven otherwise.

## Merge checklist

- [ ] `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`
- [ ] File list at HEAD pulled; comments naming deleted files set aside as stale
- [ ] PR body checked against the real file list
- [ ] Every surviving finding EXECUTED, verdict asserted on output text
- [ ] Non-reproducing findings reported as such, not silently dropped
- [ ] Negative controls run (broken input still fires; tolerance path works)
- [ ] Repo suite + any self-test green, with generated artifacts cleaned first
