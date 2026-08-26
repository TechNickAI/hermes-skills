# Sibling call-site bug classes — when an upstream fix corrected ONE instance

## The shape

A maintainer fixes a real bug, writes a good commit message, adds a repro test —
and corrects **one call site of a defect that exists at several**. The fixed site
now carries an explanatory comment that reads as authoritative, while the unfixed
sibling sits a few dozen lines away in the SAME FILE with a docstring still
asserting the old, wrong contract.

This is the single highest-value thing to look for when you have a symptom and a
suspicion. It converts "is this a real bug?" into "here is your own commit, you
missed one" — which is near-trivial for a maintainer to review and accept.

## Worked example (the router, one occasion)

Symptom: a maintenance job aborted because `compression_run_telemetry.timestamp`
could not be verified as epoch seconds.

- **Writer** `src/lib/db/compressionRunTelemetry.ts` stamps `Date.now()` → ms
- **Cleanup** `src/lib/db/cleanup.ts` computed
  `Math.floor(Date.now()/1000) - days*86_400` → seconds

A ms timestamp is ~1000x any seconds cutoff, so `WHERE timestamp < cutoff` never
matched. The retention sweep — added specifically to bound DB growth and prevent
OOM — had been permanently inert.

**The decisive find:** ~90 lines earlier in the SAME FILE,
`cleanupDomainCostHistory()` had the identical bug, already fixed by an upstream
commit, with this comment left behind:

```
 * The `timestamp` column stores epoch milliseconds (saveCostEntry default
 * is Date.now()), so the cutoff must be in milliseconds to match. (#9625)
```

That fix changed exactly the line we needed changed, one function up, and stopped
there. Its repro test covered only `domain_cost_history`.

## How to hunt this deliberately

```bash
# 1. Find the fix for the sibling — search by the CORRECTED constant/idiom
git log <ref> --oneline -S "86_400_000" -- path/to/file.ts

# 2. Read what it changed vs what it left
git show <sha> --stat
git show <sha> -- path/to/file.ts | grep -E '^[+-]' | grep -vE '^[+-]{3}'

# 3. Enumerate every sibling in the same category (not just the docs' list)
grep -nE "Date\.now\(\)" path/to/file.ts

# 4. Confirm the sibling is still unfixed on CURRENT upstream, not your checkout
git show upstream/release/vX.Y.Z:path/to/file.ts | grep -n -A8 "<function>"
```

Step 3 matters most: list every member of the affected category from the CODE,
never from the feature's documentation or the original issue's description.

## A stale docstring is a smell, not a source

The unfixed site's docstring said _"Uses unix-epoch `timestamp` column
(INTEGER)"_ — actively wrong, and almost certainly why it survived review. When a
docstring and the writer disagree, **the writer wins**; a comment is a claim, an
INSERT is evidence. Fix the docstring in the same commit or the next reader
repeats the mistake.

## The test may encode the bug

After fixing the code, the pre-existing test suite for the ORIGINAL feature went
from 6/6 to 4/6. The two failures were correct:

```js
const nowSeconds = Math.floor(now / 1000);
insert.run(nowSeconds - 40 * DAY_SECONDS, 1000, 500); // seeds SECONDS
```

The test seeded the table in seconds while production wrote milliseconds — it had
been asserting the buggy behavior, which is why the bug survived a test suite
written specifically to cover it. Notably, the sibling's own fix had updated the
`domain_cost_history` line in that same test to `nowMilliseconds` and left the
telemetry line alone: **the incomplete fix extended into the tests too.**

🔴 When a green test starts failing after your fix, read the test's FIXTURE before
assuming your change is wrong. A test that seeds data in a format production never
produces is not protecting anything.

Fix it by seeding through the REAL writer where practical, so producer and
consumer can never silently diverge again:

```js
insertCompressionRunTelemetryRow({...});           // real producer stamps the unit
db.prepare("UPDATE... SET timestamp = ?").run(now - 40*DAY_MS, id); // backdate only
```

Add an explicit unit assertion so the test fails if the producer changes:

```js
assert.ok(row.timestamp > 1e12, "timestamp is not millisecond-scale");
```

## Mandatory: prove the repro test discriminates

A repro test that passes on both the broken and fixed code proves nothing. Run it
BOTH ways before committing:

1. Revert the fix → test MUST fail, and fail on the RIGHT assertion
   (`actual: 0, expected: 3` = the inert sweep, not `no such table`)
2. Restore the fix → test MUST pass

The first attempt at this failed with `Error: no such table` — a vacuous failure
that would have "passed the control" for entirely the wrong reason. The table was
created lazily by its own module rather than the core schema. **A control that
fails for the wrong reason is not a control.**

## Also verify the pre-existing baseline

After the fix, three unrelated suites failed. Before attributing them, clone
pristine upstream at the same ref and run them there:

```bash
git clone -q --shared <local-repo> base && cd base
git checkout -q <upstream-ref>
ln -s <path>/node_modules node_modules     # reuse deps, don't reinstall
npx tsx --test tests/unit/<suite>.test.ts
```

Identical failures on untouched upstream = pre-existing, not yours. Say so
explicitly rather than either hiding them or claiming them.
