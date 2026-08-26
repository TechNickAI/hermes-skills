#!/usr/bin/env node
/*
 * A/B storage benchmark — run the SAME workload against two backends so the
 * only variable is the storage layer.
 *
 * USE WHEN deciding whether a storage workaround (RAM disk, faster volume tier,
 * cache layer) is still needed, or whether a slower/cheaper backend is adequate.
 *
 * WHY NOT `dd` OR A PRODUCTION COMPARISON
 * `dd` measures sequential throughput, which is not what a database does — it
 * does small writes with fsync barriers at WAL checkpoints, and THAT is where
 * network storage differs from RAM. Comparing production before/after instead
 * confounds storage with traffic volume, model mix, and time of day.
 *
 * RUN IT INTERLEAVED so load drift hits both arms equally:
 *   for r in 1 2 3; do
 *     for t in /mnt/ramdisk /home/ubuntu/.appdata; do
 *       node bench_storage.cjs "$t" 3000
 *     done
 *   done
 *
 * Report the WITHIN-arm spread alongside the BETWEEN-arm difference. If they are
 * comparable, the honest answer is "no measurable effect", not a ratio.
 *
 * PITFALL: run this from a directory where `require("better-sqlite3")` resolves
 * — node resolves from the SCRIPT's location, not the cwd. Copying the script
 * into the app bundle directory is the reliable fix.
 *
 * ADAPT the schema and write mix to the service under test. A benchmark on
 * different pragmas or a different row shape measures a different system.
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
// MUST match production pragmas — these dominate the result.
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

const blob = "x".repeat(1024); // ~1KB payload column, like a real request summary
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

  if (i % 25 === 0) {                    // periodic read, like health/dashboard polling
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
db.pragma("wal_checkpoint(TRUNCATE)");  // heaviest fsync; prod does this on shutdown
const finalCkpt = now() - a;

const size = fs.statSync(dbPath).size;
db.close();

for (const arr of [insLat, upsLat, selLat, ckptLat]) arr.sort((x, y) => x - y);

const out = {
  target,
  ops: N,
  wall_ms: +wall.toFixed(1),
  ops_per_sec: +(N / (wall / 1000)).toFixed(1),
  insert_p50: +pct(insLat, 50).toFixed(3),
  insert_p95: +pct(insLat, 95).toFixed(3),
  insert_p99: +pct(insLat, 99).toFixed(3),
  upsert_p50: +pct(upsLat, 50).toFixed(3),
  select_p50: +pct(selLat, 50).toFixed(3),
  checkpoint_p50: +pct(ckptLat, 50).toFixed(3),
  final_truncate_ckpt_ms: +finalCkpt.toFixed(3),
  db_bytes: size,
};

// KEY=VALUE lines: greppable, diffable, no JSON parsing downstream.
for (const [k, v] of Object.entries(out)) console.log(`${k}=${v}`);

cleanup();
