# Release value triage and post-upgrade measurement

For "we just upgraded / we're behind N releases — what's in it for us?" and
for proving what an upgrade actually did once it is live.

Worked one occasion on an 834-commit jump between two standalone builds of a
self-hosted LLM router. The user's framing: _"five brownie points for
everything I find interesting, -1 for things you bring forward that suck."_
That scoring is the whole point — an unfiltered feature list is negative
value.

## 1. Establish the real endpoints first

A `version` field usually names the release LINE, not what is deployed. On a
standalone-release layout the truth is the `current` symlink:

```bash
ls -l <app>/current # -> releases/standalone-<sha>
cat <app>/.previous_release # the build you came FROM
git rev-list --count <old-sha>..<new-sha>
```

Diff **build sha to build sha**, not tag to tag, or you will report on
commits that were never running.

## 2. Filter to signal

```bash
git log <old>..<new> --format='%s' \
  | grep -iE '^(feat|fix|perf)' \
  | grep -viE 'i18n|translat|readme|docs|typo|lint|test|chore|deps|dependabot|bump|locale|style|refactor' \
  | sed 's/(#[0-9]*)//' | sort -u
```

Then drop, without listing them: third-party integrations you do not use,
type-only commits, gamification, desktop/Electron. **Stating "I deliberately
left these out" is worth more than enumerating them.**

## 3. Score each candidate against MEASURED traffic

This separates a useful answer from a changelog paste. For every candidate,
query the service's own telemetry to find whether the condition it fixes
actually occurs in this deployment.

```sql
select status, count(*) from call_logs where timestamp > ? group by status;
select provider, count(*) n, sum(tokens_in) ti, sum(tokens_cache_read) cr
  from call_logs where timestamp > ? and tokens_in > 0 group by provider;
select duration from call_logs where timestamp > ? and duration is not null
  order by duration; -- compute p50/p95/p99/max in code, never the mean
```

A feature is only interesting if a number here moves.

Worked example: a **quota-only fallback** toggle looked attractive, but the
deployment had logged **3 total 429s** against 117× 499 / 72× 502 / 28× 524.
Enabling it would have pinned traffic to a dead provider during an outage
instead of shedding — the exact inverse of a fix applied two weeks earlier.
**Recommending against something, with the counts, scores better than
recommending it.**

## 4. Read the code path before recommending a toggle

A setting's name does not tell you its failure mode. Trace what happens when
it fires, and report the asymmetry. The slow-stream watchdog above aborts
transparently _before_ the stream holdback commits, but _after_ commit it
calls `controller.error()` — a hard mid-stream failure — unless a
continuation path applies, and that path refused for the dominant traffic
shape (tool-calling agents). That is a real trade, not pure added safety, and
it belongs in the recommendation rather than in the aftermath.

Widen conservative defaults when your workload's normal behavior resembles
the thing being detected (e.g. long reasoning phases vs a "no useful output"
watchdog), and say why in a comment next to the setting.

## 5. Measure with a MATCHED baseline

Compare the post-deploy window against the **same-length window immediately
before the deploy**, on the same metrics. Absolutes alone mean nothing.

Report per provider/lane, not only in aggregate — aggregates hide which lane
moved. Example: cache hit 74.9% → 92.3% overall, but the mover was one
provider at 49.2% → 90.7% while another was already healthy and flat.

## 6. Do not claim a cause you did not test

When several commits plausibly explain an improvement, name them as
candidates and state plainly that the specific cause was not isolated. An
untested attribution is a fabrication that future sessions will inherit.

## 7. Verify a "fix" is actually RUNNING before calling it a win

The lesson that cost a point in that session. A commit fixing a
semantic-cache 0%-hit-rate bug was reported as a goodie. Checking afterwards:

```sql
select count(*), sum(hit_count), max(created_at) from semantic_cache;
-- rows present, but newest row was 12 days old
select cache_source, count(*) from call_logs where timestamp >= ? group by cache_source;
-- 'upstream' on 100% of calls → subsystem dormant
```

The fix changed nothing because the feature was not running. **A fix in the
diff is not a fix in production.** For every claimed improvement, find the
table, counter, or log line proving the subsystem is live before presenting
it — and when you got it wrong, correct it explicitly rather than quietly.

Same discipline for anything you just enabled: "0 fires in 20 minutes" is
_expected_, not validation. Say so instead of implying it proved the change.

## Reporting shape

- Lead with the specific thing asked about, answered concretely.
- Every recommendation carries the measurement that justifies it.
- Name what you deliberately excluded.
- Name what you did NOT verify, in its own sentence.
- Corrections to your own earlier claims are stated outright, not buried.
