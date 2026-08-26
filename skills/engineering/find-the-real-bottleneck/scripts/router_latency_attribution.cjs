#!/usr/bin/env node
/*
 * Router latency attribution: is the proxy slow, or are the upstreams slow?
 *
 * Usage (must run from a dir where better-sqlite3 resolves, e.g. the app's
 * standalone bundle dir):
 *   node router_latency_attribution.cjs [/path/to/storage.sqlite]
 *
 * WHY better-sqlite3 AND NOT python: a DB written by SQLite 3.53.x cannot be
 * safely read/copied by an older stdlib sqlite (3.45.x) — it yields files both
 * engines then report as SQLITE_CORRUPT. Use the engine the app itself uses.
 *
 * WHY THE RETRY LOOP: if the service fell back to the sql.js WASM driver, it
 * persists via db.export() + writeFileSync, rewriting the whole file several
 * times per second. Any reader can catch a torn write and see SQLITE_CORRUPT,
 * SQLITE_ERROR, or a short/0-byte file. That is NOT corruption. Retry.
 *
 * WHY STRING TIMESTAMPS: call_logs.timestamp is ISO-8601 TEXT. Epoch arithmetic
 * silently matches every row and makes all time windows return identical
 * numbers. Compare against .toISOString() instead.
 */
const B = require("better-sqlite3");

const DB = process.argv[2] || "/mnt/omniroute-ramdb/storage.sqlite";

function open() {
  let last;
  for (let i = 0; i < 60; i++) {
    try {
      const d = new B(DB, { readonly: true, fileMustExist: true });
      d.prepare("select count(*) c from call_logs").get(); // force a real read
      return d;
    } catch (e) {
      last = e;
    }
  }
  throw new Error(`no consistent read of ${DB}: ${last && last.message}`);
}

const iso = (secsAgo) => new Date(Date.now() - secsAgo * 1000).toISOString();
const pct = (sorted, p) =>
  sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))] : null;
const pad = (v, n) => String(v ?? "-").padStart(n);

const d = open();

// ---- 0. ALWAYS establish the retention window + timestamp unit first -------
const span = d.prepare("select min(timestamp) a, max(timestamp) b, count(*) n from call_logs").get();
console.log(`RETENTION WINDOW: ${span.a}  ->  ${span.b}   rows=${span.n}`);
if (typeof span.b !== "string") {
  console.log("!! timestamp is NOT a string - re-check windowing math before trusting output");
}
console.log("NOTE: if nested windows below return IDENTICAL counts, your filter is broken.\n");

// ---- 1. Volume + latency by window ----------------------------------------
console.log("=== volume + latency by window ===");
for (const [label, secs] of [["15 min", 900], ["1 h", 3600], ["6 h", 21600], ["24 h", 86400]]) {
  const r = d
    .prepare(
      `select count(*) n, cast(avg(duration) as int) avg_ms,
              sum(case when status>=400 then 1 else 0 end) errs
       from call_logs where timestamp >= ?`
    )
    .get(iso(secs));
  console.log(`  ${label.padEnd(7)} n=${pad(r.n, 6)} avg=${pad(r.avg_ms, 7)}ms errs=${r.errs}`);
}

// ---- 2. Percentiles (NEVER report the mean alone) --------------------------
for (const [label, secs] of [["1 h", 3600], ["6 h", 21600]]) {
  const durs = d
    .prepare(
      `select duration from call_logs
       where timestamp >= ? and duration is not null and status < 400 order by duration`
    )
    .all(iso(secs))
    .map((r) => r.duration);
  console.log(
    `\n=== percentiles last ${label} (success only) ===\n  n=${durs.length} p50=${pct(durs, 50)}ms ` +
      `p90=${pct(durs, 90)}ms p95=${pct(durs, 95)}ms p99=${pct(durs, 99)}ms max=${durs[durs.length - 1] ?? "-"}ms`
  );
}

// ---- 3. THE KEY PROBE: fast-provider control ------------------------------
// A provider returning sub-second through the SAME router exonerates the proxy.
console.log("\n=== by provider, last 1h  (look for a FAST control) ===");
for (const p of d
  .prepare(
    `select provider, count(*) n, cast(avg(duration) as int) avg_ms,
            sum(case when status>=400 then 1 else 0 end) errs
     from call_logs where timestamp >= ? group by provider order by n desc limit 12`
  )
  .all(iso(3600))) {
  console.log(`  ${String(p.provider).padEnd(13)} n=${pad(p.n, 5)} avg=${pad(p.avg_ms, 7)}ms errs=${p.errs}`);
}

// ---- 4. Normalize by output tokens: slow answer vs slow generation ---------
console.log("\n=== ms per output token, last 6h ===");
const rows = d
  .prepare(
    `select duration, tokens_out, provider from call_logs
     where timestamp>=? and status<400 and duration is not null and tokens_out > 50`
  )
  .all(iso(21600));
const byProv = {};
for (const r of rows) (byProv[r.provider] ||= []).push(r.duration / r.tokens_out);
for (const [p, arr] of Object.entries(byProv).sort((a, b) => b[1].length - a[1].length).slice(0, 8)) {
  arr.sort((a, b) => a - b);
  console.log(`  ${p.padEnd(13)} n=${pad(arr.length, 5)} p50=${pct(arr, 50).toFixed(1)}ms/tok p95=${pct(arr, 95).toFixed(1)}ms/tok`);
}

// ---- 5. Multi-day baseline: is today actually anomalous? ------------------
console.log("\n=== daily p50/p95 per top model (is today an outlier?) ===");
for (const m of d
  .prepare(`select model, count(*) n from call_logs where timestamp>=? group by model order by n desc limit 4`)
  .all(iso(86400 * 3))) {
  console.log(`  -- ${m.model}`);
  for (const dy of d
    .prepare(`select distinct substr(timestamp,1,10) day from call_logs where model=? order by day`)
    .all(m.model)) {
    const durs = d
      .prepare(
        `select duration from call_logs where model=? and substr(timestamp,1,10)=?
         and status<400 and duration is not null order by duration`
      )
      .all(m.model, dy.day)
      .map((r) => r.duration);
    if (durs.length < 20) continue;
    console.log(`     ${dy.day} n=${pad(durs.length, 5)} p50=${pad(pct(durs, 50), 6)}ms p95=${pad(pct(durs, 95), 7)}ms`);
  }
}

// ---- 6. Errors (a credential can expire quietly mid-investigation) --------
console.log("\n=== errors last 6h ===");
const errs = d
  .prepare(
    `select status, provider, error_summary, count(*) n from call_logs
     where timestamp >= ? and status>=400 group by status,provider,error_summary order by n desc limit 12`
  )
  .all(iso(21600));
if (!errs.length) console.log("  none");
for (const e of errs)
  console.log(`  ${e.status} ${String(e.provider).padEnd(12)} n=${pad(e.n, 4)} ${String(e.error_summary || "").slice(0, 80)}`);

console.log(
  "\nREMINDER: also probe the router's OWN overhead with a no-upstream endpoint:\n" +
    "  for i in $(seq 1 8); do curl -s -o /dev/null -w 'total=%{time_total}s\\n' http://127.0.0.1:PORT/api/monitoring/health; done\n" +
    "Discard the first sample (connection warm-up). Pair with `top -bn1` for idle%/load.\n" +
    "If request_type is NULL you cannot split streaming vs non-streaming - say so."
);

d.close();
