#!/usr/bin/env node
/*
 * backup_sqlite_multi.cjs — pre-deploy N-way backup of a live SQLite state DB.
 *
 * WHY THIS EXISTS (all three learned the hard way):
 *
 *  1. Back up with the engine that WRITES the db. A backup made by a different
 *     SQLite version can be unreadable by BOTH engines afterwards. Observed:
 *     host python3 = 3.45.1, app better-sqlite3 = 3.53.3; the python-made copy
 *     read SQLITE_CORRUPT everywhere. The source was fine the whole time.
 *
 *  2. If the app is on a full-rewrite driver (sql.js: db.export() +
 *     fs.writeFileSync of the WHOLE file on every debounced write), readers hit
 *     TORN READS. A copy can fail with SQLITE_CORRUPT / SQLITE_ERROR, or come
 *     out short, purely because it landed in a write window. Retry.
 *     `VACUUM INTO` is NOT safer here; it fails the same way.
 *
 *  3. Verify a copy by OPENING it and counting rows, never by exit code or
 *     file size. Exclude high-churn tables from the equality gate or every
 *     backup "fails".
 *
 * RUN IT FROM INSIDE THE APP BUNDLE so `require("better-sqlite3")` resolves:
 *   cd <app>/.build/next/standalone && node backup_sqlite_multi.cjs
 *
 * Configure via env:
 *   LIVE_DB   path to the live database              (required)
 *   TABLES    comma-separated config tables to gate on
 *   TARGETS   comma-separated destination paths
 */
const B = require("better-sqlite3");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const LIVE = process.env.LIVE_DB;
if (!LIVE) {
  console.error("FATAL: set LIVE_DB");
  process.exit(2);
}
const STAMP = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z");

// Gate on CONFIG tables — the ones whose loss would mean rebuilding by hand.
// Deliberately exclude churny telemetry tables (call_logs, events, metrics).
const TABLES = (process.env.TABLES || "combos,provider_connections,api_keys")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const TARGETS = (
  process.env.TARGETS ||
  [
    `${process.env.HOME}/backups/predeploy-${STAMP}/state.sqlite`,
    `/var/tmp/predeploy-${STAMP}.sqlite`,
  ].join(",")
)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const MAX_TRIES = Number(process.env.MAX_TRIES || 40);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function inspect(p) {
  const d = new B(p, { readonly: true, fileMustExist: true });
  try {
    const qc = d.pragma("quick_check")[0].quick_check;
    const counts = {};
    for (const t of TABLES) counts[t] = d.prepare(`select count(*) c from ${t}`).get().c;
    return { qc, counts };
  } finally {
    d.close();
  }
}

async function consistentSourceRead() {
  for (let i = 1; i <= MAX_TRIES; i++) {
    try {
      const s = inspect(LIVE);
      if (s.qc === "ok") return s;
    } catch (_) {
      /* torn read */
    }
    await sleep(1500);
  }
  throw new Error("never got a consistent read of the live DB");
}

async function snapshotWithRetry(dst, expect) {
  for (let i = 1; i <= MAX_TRIES; i++) {
    try {
      if (fs.existsSync(dst)) fs.unlinkSync(dst);
      const src = new B(LIVE, { readonly: true, fileMustExist: true });
      try {
        await src.backup(dst);
      } finally {
        src.close();
      }
      const got = inspect(dst);
      if (got.qc === "ok" && JSON.stringify(got.counts) === JSON.stringify(expect)) {
        console.log(`  attempt ${i}: OK counts=${JSON.stringify(got.counts)}`);
        return true;
      }
      console.log(`  attempt ${i}: mismatch qc=${got.qc} counts=${JSON.stringify(got.counts)}`);
    } catch (e) {
      console.log(`  attempt ${i}: torn read (${e.code || e.message})`);
    }
    await sleep(1500);
  }
  return false;
}

const sha = (p) => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");

(async () => {
  console.log(`LIVE: ${LIVE}`);
  const src = await consistentSourceRead();
  console.log(`=== source truth ===\n  quick_check=${src.qc} counts=${JSON.stringify(src.counts)}`);

  const results = [];
  for (const dst of TARGETS) {
    console.log(`\n=== backup -> ${dst} ===`);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    const ok = await snapshotWithRetry(dst, src.counts);
    results.push({ dst, ok, sha: ok ? sha(dst) : "-", size: ok ? fs.statSync(dst).size : 0 });
  }

  console.log("\n=== SUMMARY ===");
  let all = true;
  for (const r of results) {
    console.log(`  ${r.ok ? "OK  " : "FAIL"} ${String(r.size).padStart(12)} ${r.sha.slice(0, 16)} ${r.dst}`);
    all = all && r.ok;
  }
  // Distinct hashes across copies are EXPECTED when churny tables move between
  // snapshots; the gate is quick_check + config-table counts, not hash equality.
  console.log(`\nALL_BACKUPS_VERIFIED=${all}`);
  console.log("REMINDER: also copy one backup OFF-HOST, plus the service .env.");
  process.exit(all ? 0 : 1);
})();
