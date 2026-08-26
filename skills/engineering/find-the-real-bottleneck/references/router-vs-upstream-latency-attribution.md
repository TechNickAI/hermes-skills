# "Users say it's slow" — is it the proxy or the upstream?

Worked case: the router, one occasion. the operator asked "users are complaining
about response times — is that at the level?" Answer was _mostly no,
partly yes_, and every part of that needed a number.

The failure this prevents: agreeing with the framing. When the owner of a proxy
asks "is it my proxy", the socially easy answers are both wrong — "yes, and
here's a fix" (unmeasured) or "no, it's the upstream" (also unmeasured).

## The four probes, cheapest first

### 1. Pa personal-assistant agent's own overhead — hit an endpoint that touches no upstream

```bash
for i in $(seq 1 8); do
  curl -s -o /dev/null -w "total=%{time_total}s connect=%{time_connect}s\n" \
    http://127.0.0.1:PORT/api/monitoring/health
done
```

Result was `2.4ms` steady (first call 331ms = connection warm-up, discard it).
Pair with `top -bn1` for idle% and load average. 78% idle / load 0.53 alongside
2.4ms means **the proxy is not sitting on requests**. This single probe does
most of the work and takes ten seconds.

### 2. Fast-provider control — the strongest evidence available

The decisive comparison is _within the same router, same time window_:

| provider   | n (1h) |      avg |
| ---------- | ------ | -------: |
| codex      | 401    | 11,971ms |
| claude     | 202    | 11,716ms |
| openrouter | 44     | 15,733ms |
| gemini     | 16     |    768ms |
| cohere     | 16     |    794ms |

Gemini and Cohere returning in **<800ms through the identical code path**
exonerates the router more convincingly than any profiler. If the proxy were the
bottleneck, every provider would be slow. **Always look for a fast control in
the same dataset before reaching for instrumentation.**

### 3. Normalize by output tokens — slow answer vs slow generation

Raw duration conflates "the model wrote 2000 tokens" with "the model is slow".

```sql
select provider, duration, tokens_out from call_logs
where timestamp >= ? and status < 400 and duration is not null and tokens_out > 50
```

then `duration / tokens_out` per provider, percentiles in JS.

codex `30.0 ms/tok` p50, claude `17.3 ms/tok`. Those are **generation speeds**,
not proxy overhead. This reframes the user-facing answer: a long answer from a
30ms/tok model is inherently a 10-30s experience and no infrastructure change
fixes it.

### 4. Multi-day baseline — is today actually anomalous?

Per-model, per-day p50/p95 across the retention window. Today's
`gpt-5.6-sol-xhigh` p50 of 8,774ms was the **second fastest** of seven days
(range 8,774–11,863ms). Without this, "p50 is 8 seconds" sounds alarming.
**A complaint is not evidence of a regression.** Users complain when they notice,
not when the metric moves.

## The honest "partly yes": before/after a restart

The router _was_ contributing, and the way to prove it was a natural experiment:

```
BEFORE restart (13:17-13:47) n=190 p50=7509ms p95=30607ms
AFTER restart (13:47-14:17) n=116 p50=3576ms p95=25348ms
```

p50 halved across a restart that reclaimed ~3GB of leaked buffers. That is a
real secondary effect layered on genuinely slow upstreams. Report both — "no,
it's upstream" would have been a lie by omission.

**Look for free natural experiments** — restarts, deploys, failovers — before
constructing one. A watchdog restart is a controlled intervention someone else
already ran for you.

## Traps hit in this session

**ISO-string timestamps vs epoch math.** `call_logs.timestamp` is an ISO-8601
_string_. Arithmetic windowing (`where timestamp >= <now - 3600>`) silently
matched **every row**, so 15min / 1h / 6h / 24h / 72h all returned an identical
`n=100000 avg=10929ms`. Identical results across nested windows is the tell —
nested windows must produce strictly non-decreasing counts. Always print
`min(timestamp), max(timestamp), count(*)` first and eyeball the unit before
trusting any windowed aggregate. Correct form is string compare against
`new Date(Date.now() - secs*1000).toISOString()`.

**The row cap masquerades as a time window.** `call_logs` was retention-capped at
~100k rows spanning 6 days. "Last 6h" and "all time" returning the same count is
a retention artifact, not traffic.

**Report percentiles, never the mean.** avg 10,929ms vs p50 6,022ms / p95
29,189ms / max 205,913ms — the mean described no actual request.

**`request_type` was NULL for every row**, so streaming and non-streaming could
not be separated, and for streamed responses `duration` covers the entire stream
(inflating p95). State this limitation out loud; the provider comparison and
per-token math survive it because both are affected equally.

## Reusable probe

`scripts/router_latency_attribution.cjs` in this skill implements all four
probes with the torn-read retry loop needed against a live sql.js DB.

## Reporting shape that worked

1. Lead with the verdict and its qualifier ("mostly no — but partly yes").
2. Pa personal-assistant agent overhead number first (2.4ms) — it's the question actually asked.
3. Fast-provider control table — the exoneration.
4. Per-token normalization — reframes as model speed.
5. Multi-day baseline — kills the "it got worse" premise.
6. The honest partial-yes with its measurement.
7. What to tell users, plus the unrelated real finding (an expired credential
   surfaced during the sweep — report it, don't let it drown).
8. Name your own measurement limitation before someone finds it.
