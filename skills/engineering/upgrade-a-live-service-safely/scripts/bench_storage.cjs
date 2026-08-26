#!/usr/bin/env node
/*
 * A/B storage benchmark — run the SAME SQLite workload against two storage
 * backends back to back, so the only variable is the storage layer.
 *
 * WHY THIS AND NOT "watch production for a day"
 * Production comparison confounds storage with traffic volume, model mix, and
 * time of day. This isolates the storage layer: identical schema, identical
 * write pattern, identical driver, run minutes apart on the same host under the
 * same load.
 *
 * USAGE — always INTERLEAVE, never run all of A then all of B, or load drift
 * gets attributed to the backend:
 *
 *   for round in 1 2 3; do
 *     for tgt in /mnt/ramdisk "$HOME/.appdata"; do
 *       node bench_storage.cjs "$tgt" 3000
 *     done
 *   done
 *
 * MUST RUN WITH THE APP'S OWN DRIVER. Invoke it from the app bundle directory
 * so `require("better-sqlite3")` resolves to the same native module production
 * uses — a different SQLite version measures a different system, and a host
 * python/CLI sqlite may not even read a DB written by a newer embedded engine.
 *
 * ADAPT the schema and the workload mix to the real dominant write path of the
 * service under test. The point is to reproduce the real access pattern
 * (including WAL fsync behaviour), not to run a synthetic `dd`.
 */
const B = require("better-sqlite3");
const fs = require("fs");
const path = require("path");

const target = process.argv[2];
const N = parseInt(process.argv[3] || "2000", 10);
if (!target) {
  console.error("usage: bench_storage.cjs <dir> [n_ops]");
  process.exit(2);
}

const dbPath = path.join(target, `bench-${process.pid}.sqlite`);
const cleanup = () => {
  for (const f of [dbPath, dbPath + "-wal", dbPath + "-shm"]) {
    try { fs.unlinkSync(f); } catch {}
  }
};
cleanup();

const pct = (a, p) => (a.length ? a[Math.min(a.length - 1, Math.floor((p / 100) * a.length))] : 0);
const now = () => Number(process.hrtime.bigint()) / 1e6;

const db = new B(dbPath);
// Match production pragmas EXACTLY. A benchmark at different durability
// settings is measuring a different system.
db.pragma("journal_mode = WAL");
db.pragma("synchronous = NORMAL");

db.exec(`
  create table call_logs(
    id integer primary key, timestamp text, method text, path text, status integer,
    model text, provider text, duration integer, tokens_in integer, tokens_out integer,
    request_summary text, correlation_id text
  );
  create index idx_ts on call_logs(timestamp);
  create table usage_history(k text primary key, n integer, bytes integer);
`);

const ins = db.prepare(`insert into call_logs
  (timestamp,method,path,status,model,provider,duration,tokens_in,tokens_out,request_summary,correlation_id)
  values (?,?,?,?,?,?,?,?,?,?,?)`);
const ups = db.prepare(`insert into usage_history(k,n,bytes) values(?,1,?)
  on conflict(k) do update set n=n+1, bytes=bytes+excluded.bytes`);
const sel = db.prepare(`select count(*) c, avg(duration) d from call_logs where timestamp >= ?`);

const blob = "x".repeat(1024); // ~1KB payload, similar to real rows
const insLat = [], upsLat = [], selLat = [], ckptLat = [];

const t0 = now();
for (let i = 0; i < N; i++) {
  const ts = new Date(Date.now() - (N - i) * 1000).toISOString();

  let a = now();
  ins.run(ts, "POST", "/v1/messages", 200, "model-a", "provider-a",
          1000 + (i % 9000), 500 + (i % 4000), 100 + (i % 900), blob, `corr-${i}`);
  insLat.push(now() - a);

  a = now();
  ups.run(`provider-a:${i % 16}`, 1024);
  upsLat.push(now() - a);

  if (i % 25 === 0) {                    // reads, like dashboard/health polling
    a = now();
    sel.get(new Date(Date.now() - 3600e3).toISOString());
    selLat.push(now() - a);
  }
  if (i > 0 && i % 400 === 0) {          // the fsync-heavy path
    a = now();
    db.pragma("wal_checkpoint(PASSIVE)");
    ckptLat.push(now() - a);
  }
}
const wall = now() - t0;

const a = now();
db.pragma("wal_checkpoint(TRUNCATE)");   // heaviest fsync; prod does this on shutdown
const finalCkpt = now() - a;

const size = fs.statSync(dbPath).size;
db.close();

for (const arr of [insLat, upsLat, selLat, ckptLat]) arr.sort((x, y) => x - y);

// Plain key=value lines: greppable, no JSON parsing needed downstream.
const out = {
  target,
  ops: N,
  wall_ms: +wall.toFixed(1),
  ops_per_sec: +(N / (wall / 1000)).toFixed(1),
  // request-path cost — this is the number that reaches the user
  insert_p50: +pct(insLat, 50).toFixed(3),
  insert_p95: +pct(insLat, 95).toFixed(3),
  insert_p99: +pct(insLat, 99).toFixed(3),
  insert_max: +insLat[insLat.length - 1].toFixed(3),
  upsert_p50: +pct(upsLat, 50).toFixed(3),
  upsert_p95: +pct(upsLat, 95).toFixed(3),
  select_p50: +pct(selLat, 50).toFixed(3),
  select_p95: +pct(selLat, 95).toFixed(3),
  // BACKGROUND cost — weigh separately, it does not reach the user
  checkpoint_p50: +pct(ckptLat, 50).toFixed(3),
  checkpoint_max: ckptLat.length ? +ckptLat[ckptLat.length - 1].toFixed(3) : 0,
  final_truncate_ckpt_ms: +finalCkpt.toFixed(3),
  db_bytes: size,
};
for (const [k, v] of Object.entries(out)) console.log(`${k}=${v}`);

cleanup();
