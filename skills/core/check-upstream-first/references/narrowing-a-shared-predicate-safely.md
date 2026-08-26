# Narrowing a shared classifier without changing its other consumers

## The trap

You find a one-line bug. A predicate lumps two distinct conditions together:

```typescript
return code === "STREAM_READINESS_TIMEOUT" || code === "STREAM_EARLY_EOF";
```

One of those codes doesn't belong. The obvious fix is to delete it. **Check who else
reads that flag first.**

In the real case, the boolean this predicate produced fed **three** behaviors:

1. the whole-provider circuit-breaker gate (the buggy one)
2. a transient-retry decision (`isTransient = !isStreamReadinessFailure &&...`)
3. a round-robin semaphore cooldown

Deleting the `||` clause would have fixed (1) and **silently changed (2) and (3)** —
including a retry the user had explicitly asked to preserve two messages earlier. The
diff would have looked like a one-line fix and shipped a behavioral regression in two
unrelated subsystems.

## The method

```bash
# 1. Every caller of the predicate
grep -rn "isStreamReadinessFailureErrorBody" --include=*.ts src/ open-sse/ | grep -v node_modules

# 2. Every use of the VARIABLE the predicate populates — this is the step
# people skip, and it's where the other consumers hide
grep -n "isStreamReadinessFailure" open-sse/services/combo.ts
# 1511: const isStreamReadinessFailure = <- assignment
# 1715: isStreamReadinessFailure, <- breaker call (the bug)
# 1730: !isStreamReadinessFailure && <- transient retry
# 2836: !isStreamReadinessFailure && <- semaphore cooldown
# 2856: !isStreamReadinessFailure && <- second dispatcher's retry

# 3. Read each site and decide, per site, whether it wants the old or new semantics
```

Grepping the function name alone found 3 hits. Grepping the _variable_ found 5, and the
two extra ones were the whole reason not to edit the shared predicate.

## The fix shape: additive, not mutative

Leave the shared classifier alone. Add a **narrower** predicate and an **optional**
argument consumed only by the site that needs the distinction:

```typescript
// unchanged — the retry and cooldown paths still want both codes treated alike
export function isStreamReadinessFailureErrorBody(errorBody: unknown): boolean {... }

// new, strictly narrower
export function isStreamEarlyEofErrorBody(errorBody: unknown): boolean {... }

export function shouldRecordProviderBreakerFailure(args: {
  isStreamReadinessFailure: boolean;
  isStreamEarlyEof?: boolean; // <- optional: omitting it reproduces old behavior
...
}): boolean {
  return (
    (!args.isStreamReadinessFailure || args.isStreamEarlyEof === true) &&
... // every other AND-term still gates the result
  );
}
```

Properties that make this safe and reviewable:

- **`undefined !== true`**, so every existing caller that omits the arg behaves exactly
  as before. State that explicitly in the commit message and prove it with a test.
- **The override lifts exactly one AND-term.** Write a test per remaining term proving
  each still vetoes the result.
- **It's a diff a maintainer can reason about locally** — no need to audit the whole
  call graph to convince themselves nothing else moved.

## Look for existing precedent in the same function

Before inventing a shape, check whether the codebase already solved this. The same
function already carried `isProxyUnreachable?: boolean` — an additive optional override
lifting a _different_ AND-term, added by an earlier fix. Copying that pattern turned the
PR from "here's my approach" into "here's the approach you already use."

Equally valuable: check whether a **parallel code path** already has the behavior you're
adding. Here the single-model path's equivalent gate had no readiness exemption at all,
so a 502 early-EOF already tripped the breaker there. That reframed the PR from
"change your resilience policy" to "make these two paths consistent" — a much easier
review.

## Prove the bug before fixing it

Write the failing case against **unmodified upstream** first, so the claim isn't
theoretical:

```bash
git show upstream/release/vX.Y.Z:path/to/predicates.ts > /tmp/upstream.ts
# import from /tmp/upstream.ts in a scratch test, assert the WRONG behavior is present
```

A test that only passes after your fix proves the fix works. A test that demonstrates
the bug on untouched upstream code proves the bug **exists** — that's the one that
belongs in the issue/PR description.

Note: a RED run that fails with `SyntaxError: does not provide an export named...` is
**not** proof of a behavioral bug — it's proof your test imports something that doesn't
exist yet. Import the upstream copy directly to get a real behavioral RED.

## Pitfalls

- **Grepping the predicate name but not the variable it assigns to.** The extra
  consumers live at the variable's use sites.
- **Assuming one call site because the function is "obviously" specialized.** Large
  routing files often contain two or more near-duplicate dispatchers (priority vs
  round-robin) with subtly different behavior.
- **Making the new arg required.** That forces every caller to change and turns a
  contained fix into a wide diff.
- **Using a truthy check (`if (args.flag)`) instead of `=== true`.** Explicit
  comparison documents that `undefined` and `false` are intentionally equivalent.
