# Dashboard data freshness & honesty

For any read-only data dashboard (financial, monitoring, status) that renders from a DB or cache fed by an upstream pull. A beautiful dashboard fed stale data is actively _dangerous_ because it looks authoritative. Make staleness impossible to miss.

## The honesty pattern

1. **Every number carries an age.** Compute `ageDays(as_of)` for each dated input. Do not render a value without its freshness nearby.
2. **Color-code by staleness, with tight thresholds.** For a dashboard meant to be current: green ≤ 2 days, amber 3–7, red > 7. Loose thresholds let frozen numbers look live for weeks.
3. **One global "oldest input" banner at the top.** Scan all dated inputs, surface the single oldest with date + age, and list stale critical inputs. Make the banner red when any critical input is stale.
4. **Stale pills on headline cells.** Hero numbers get an inline `Nd old` pill when stale, so a glance cannot mistake old data for today's.
5. **Separate critical from nice-to-have inputs.** Red banners should be driven by stale critical inputs, not a stale optional watchlist row.

### Minimal JS sketch

```js
const ageDays = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86400000));
};
const freshness = (iso) => {
  const age = ageDays(iso);
  if (age === null) return { label: "no data", cls: "stale", age: null };
  if (age <= 2) return { label: "fresh", cls: "fresh", age };
  if (age <= 7) return { label: `${age}d old`, cls: "aging", age };
  return { label: `${age}d old`, cls: "stale", age };
};
// Banner: collect {label, iso, age, critical}, sort by age desc.
// worst = points[0]; cls = staleCriticals.length ? 'stale': worst.age > 2 ? 'aging': 'fresh'.
// Pill: if cls !== 'fresh' && age !== null -> `<span class="stale-pill ${cls}">${age}d old</span>`.
```

CSS: use `.freshness-banner.fresh/.aging/.stale` with green/amber/red backgrounds, plus `.stale-pill.aging/.stale`. A stale dot should be red, not neutral grey.

## Companion pitfall: upstream cron can lie about success

When a dashboard is fed by an LLM-wrapped Hermes cron job, cron `last_status: ok` means the _agent turn completed_, not that the wrapped data-write script succeeded. The script can return `rc=1` and write nothing while the job still logs ok.

- Diagnose by the DB's `last_updated` / newest `as_of`, not cron `last_status` alone.
- Read the cron transcript under `<profile>/cron/output/<job_id>/`; the agent output often contains the real failure.
- Browser-driven pulls commonly fail because the shared Chrome session logged out. The real fix is a human re-login, then rerun the pull.
- Patch pulls to classify failures accurately, e.g. `SESSION_DEAD` vs generic `PULL_FAIL`, so the alert tells the user the right action.

## Tone

Do not moralize about stale dashboards. The fix is: make age legible. A red banner saying `23d old` beats a pretty number that is silently frozen.
