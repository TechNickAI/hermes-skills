# Post-upgrade capability audit — "we upgraded, what are the goodies?"

The mirror image of pre-upgrade probing. Instead of _should we take this
release?_, the question is: the deploy already landed, we jumped several
releases, **what changed, what should we now enable, and what silently got
better?**

Same discipline as the rest of this skill — a feature is not a win because its
commit message says so. It is a win when this deployment's own telemetry says it
touches something real.

Learned from the one occasion the router jump (834 commits) where the user's literal
question ("what is this new checkbox?") correctly answered **do not enable it**,
and the actual wins were things nobody asked about.

## 1. Anchor on the deployed BUILD pair, not the version string

Same trap as "branching a fix off a version tag" in the parent skill. Both builds
in this audit reported `3.8.49` in `package.json`; they were 834 commits apart.

```bash
ls -l  <app>/current            # symlink -> releases/standalone-<sha>
cat    <app>/.previous_release  # standalone-<sha>  (the build you came FROM)
git rev-list --count <old>..<new>
```

Then reduce the log to something readable. The second grep is what turns 834
commits into a human-sized list:

```bash
git log <old>..<new> --format='%s' \
  | grep -iE '^(feat|fix|perf)' \
  | grep -viE 'i18n|translat|readme|docs|typo|lint|test|chore|deps|dependabot|bump|locale|style|refactor' \
  | sed 's/(#[0-9]*)//' | sort -u
```

Expect ~90 `fix(types):` commits in a large jump — real work, pure noise here.

## 2. Grade every candidate against LIVE telemetry

For each candidate feature, find the number in your own logs that justifies it,
or drop it. Worked examples:

| Candidate                 | Query that decided it                                               | Verdict                                                                                         |
| ------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Quota-only combo fallback | `status in (402,429)` → **3 total 429s** vs 117×499, 72×502         | **Reject** — our descents aren't quota-driven; this pins us to a dead provider during an outage |
| Slow-stream watchdog      | duration percentiles → p99 **71.8s**, max **901s**, 340 calls >120s | **Adopt** — aimed at our tail                                                                   |
| "Fixes 0% cache hit rate" | `cache_source` = `upstream` on **100%** of 100,004 calls            | Looks perfect — but see §4                                                                      |

A well-argued _reject_, with the number that rejected it, is a finding. Report it
alongside the adoptions rather than silently omitting it.

## 3. Read the failure path before recommending a resilience feature

Resilience features are rarely purely additive. Trace what the client actually
receives when the new mechanism fires.

The throughput watchdog aborts two different ways:

- **pre-commit** (holdback uncommitted, first ~750ms/64KB) → transparent re-open,
  invisible to the client;
- **post-commit** (every long-running stream) → attempts continuation, and when
  that refuses, **`controller.error()`** — a hard mid-stream failure.

Continuation refused on most of this fleet's traffic because it required
`emittedParsedOpenAi && !emittedToolCall`, and the dominant shapes were agentic
and tool-heavy. So the honest framing is _"converts stuck-for-15-minutes into
fails-at-2-minutes"_ — a good trade, stated plainly, not sold as free safety.

On first enable with reasoning-heavy traffic (slow tail averaged 5,045 reasoning
tokens), set warmup/window to **double** the defaults. Under-trigger first.

## 4. Verify the subsystem is actually RUNNING before crediting a fix

The self-correction from this session, and the highest-value rule here.

A commit titled "fixes 0% hit rate" is worthless if the subsystem is inert for an
unrelated reason:

```sql
select sum(hit_count) hits, count(*) n, max(created_at) newest from semantic_cache;
-- 1,438 lifetime hits, newest row 12 days old, ZERO new rows post-deploy
-- => frozen long before this release; the fix neither broke nor revived it
```

Rule: for any cache / index / queue feature, check **write recency** and whether
new rows appear after the deploy. Lifetime totals happily hide a subsystem that
stopped weeks ago. Recommending that fix as a win was wrong, and saying so
explicitly is part of the report.

## 5. Measure against a MATCHED baseline window

Absolute post-deploy numbers are meaningless alone. Compare the post-deploy
window to an equal-length window immediately before it. Report the full latency
curve and tail counts, never the mean.

Result shape from this audit: cache hit **74.9% → 92.3%** (driven entirely by one
provider, 49.2% → 90.7%), p99 **70.7s → 56.1s**, calls >300s **3 → 0**.

Two honesty rules that came out of it:

- **Never credit a change you enabled if it had not run yet.** The watchdog had
  fired **0 times** and 3,857 of 3,887 calls predated it. The gains were the
  release, not my change. Say which.
- **Never attribute a specific commit without a controlled repro.** Two commits
  could explain the cache jump; name both and state that you did not isolate it.

## 6. Explain per-connection noise before calling anything a regression

Raw success rate fell 99.77% → 99.51%, which reads as a regression. It was
_entirely_ 7×401 from one dead credential's connection-test polling. Excluding it:
99.69%, remainder client-side aborts.

`is_active` stays `1` on a dead credential — `test_status` / `last_error` are the
real health fields. Separate stale-credential polling from real traffic before
reporting a regression.
