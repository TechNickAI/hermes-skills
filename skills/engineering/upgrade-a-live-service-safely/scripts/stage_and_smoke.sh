#!/usr/bin/env bash
# Stage a CI-built artifact and smoke-test it on a TEST PORT, without touching
# the live service. Proven against the production router.
#
# SAFETY INVARIANTS (all verified in-script):
#   - unpacks into releases/<name>/  (NEVER the live working directory)
#   - binds TEST_PORT, not the live port
#   - uses a COPY of the SQLite DB in a temp DATA_DIR (live DB untouched)
#   - records live MainPID before, asserts unchanged after
#   - never restarts/stops the unit, never moves the `current` symlink
#   - trap cleanup EXIT so the test process dies even on failure
#
# Usage: bash stage_and_smoke.sh <run-id> <artifact-name>
# ADAPT the CONFIG block for a different service.

set -euo pipefail

RUN_ID="${1:?need CI run id}"
ART="${2:?need artifact name}"

# ---- CONFIG (adapt) --------------------------------------------------------
REPO="OWNER/REPO"
REPO_DIR="$HOME/src/MyService"
SERVICE="myservice.service" # a --user unit in this pattern
ENV_FILE="$REPO_DIR/.env"
LIVE_DB="$HOME/.myservice/storage.sqlite"
ENTRY="dev/run-standalone.mjs"
HEALTH_PATH="/api/monitoring/health"
LIVE_PORT=20128
TEST_PORT=20129
MARKER="MY_FORK_MARKER" # string that proves the fork patch is in the bundle
# Space-separated model aliases for the [8b] inference smoke. Pick ones that
# route to genuinely DIFFERENT upstream backends, so one dead provider can't
# hide behind another that works.
SMOKE_MODELS="${SMOKE_MODELS:-claude-chat work simple grok}"
# ---------------------------------------------------------------------------

REL_ROOT="$REPO_DIR/releases"
STAGE="/tmp/stage-$$"
TEST_DATA="/tmp/testdata-$$"
TEST_LOG="/tmp/test-$$.log"

echo "=== STAGING (live service on :$LIVE_PORT untouched) ==="

echo "[0] pre-flight"
systemctl --user is-active "$SERVICE"
LIVE_PID=$(systemctl --user show "$SERVICE" -p MainPID --value)
echo "    live MainPID=$LIVE_PID (must not change)"

mkdir -p "$STAGE" "$REL_ROOT"

echo "[1] download artifact"
gh run download "$RUN_ID" -n "$ART" -R "$REPO" -D "$STAGE"

echo "[2] checksum"
if [ -f "$STAGE/${ART}.tar.zst.sha256" ]; then
  (cd "$STAGE" && sha256sum -c "${ART}.tar.zst.sha256")
fi

echo "[3] unpack into a NEW release dir"
REL="$REL_ROOT/$ART"
rm -rf "$REL"; mkdir -p "$REL"
tar --zstd -xf "$STAGE/${ART}.tar.zst" -C "$REL"
test -s "$REL/.build/next/standalone/server.js" || { echo "FATAL: no server.js"; exit 1; }

echo "[4] platform + patch sanity"
if find "$REL" -path "*sharp-darwin*" | grep -q .; then
  echo "FATAL: darwin native modules — wrong build platform"; exit 1
fi
# ADD ONE ASSERT PER CHANGE THIS DEPLOY SHIPS, not just the standing fork
# marker. Then prove each new assert works by running it against the CURRENTLY
# DEPLOYED bundle: the new strings must be ABSENT there and the standing one
# PRESENT. An assert that passes against both the old and new bundle is
# decoration. Use `grep -F` for any string containing regex metacharacters —
# plain grep reads "(module|table)" as a pattern and silently matches nothing.
# if/else, never `A && B || C` (SC2015): with `set -e` the || arm can fire on a
# successful match whose echo failed, aborting a good staging run.
if grep -rq "$MARKER" "$REL/.build/next/standalone" 2>/dev/null; then
  echo "    fork patch: PRESENT"
else
  echo "FATAL: fork patch missing"; exit 1
fi

echo "[5] isolated test DB (online backup API, safe against a live writer)"
mkdir -p "$TEST_DATA"
# PREFER PYTHON over the sqlite3 CLI. Both expose the same online backup API,
# but the CLI's `.backup` intermittently aborts with "database disk image is
# malformed" against a busy WAL database — measured on the at
# 1 failure in 10 runs while python's Connection.backup() failed 0 in 10 on the
# same file, seconds apart. The database was healthy throughout
# (integrity_check ok, both before and after). Ordering the CLI first makes
# staging fail spuriously ~10% of the time and invites a false "the DB is
# corrupt" diagnosis.
#
# Never fall back to `cp` — it can tear a page mid-write on a live WAL
# database, producing a genuinely corrupt copy that the script then treats as
# valid. If no safe path exists, FAIL LOUDLY.
# Retry: against a continuously-written WAL database, .backup() intermittently
# reads a torn page set and raises "database disk image is malformed" even
# though the database is perfectly healthy. Measured on the:
# integrity_check on the LIVE file returned ok/FAIL/ok/FAIL/FAIL/FAIL across six
# consecutive runs, while the SAME database snapshotted to a static file passed
# 4/4 with identical row counts. Every client is affected (python 3.45,
# better-sqlite3 3.53, sqlite3 CLI 3.45) because it is a property of reading a
# file being written, not of any one library. Retry until a copy verifies.
if python3 -c "import sqlite3" 2>/dev/null; then
  TEST_DB_COPY="$TEST_DATA/$(basename "$LIVE_DB")"
  BACKUP_OK=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    rm -f "$TEST_DB_COPY" "$TEST_DB_COPY-wal" "$TEST_DB_COPY-shm"
    if python3 - "$LIVE_DB" "$TEST_DB_COPY" <<'PY'
import sqlite3, sys
# NOT ?mode=ro — a read-only URI connection cannot attach the -wal/-shm sidecars
# of a LIVE WAL database and reads a torn view. query_only=ON gives the
# read-only guarantee without breaking WAL attachment.
src = sqlite3.connect(sys.argv[1], timeout=60)
src.execute("PRAGMA query_only=ON")
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
# Verify in the SAME process: a copy that backed up cleanly can still be a torn
# snapshot, and an unreadable copy must never reach the smoke test.
chk = sqlite3.connect(sys.argv[2])
ic = chk.execute("PRAGMA integrity_check").fetchone()[0]
chk.close()
if ic != "ok":
    raise SystemExit(f"copy failed integrity_check: {ic[:80]}")
PY
    then
      echo "    online backup verified (python, attempt $attempt)"
      BACKUP_OK=1
      break
    fi
    echo "    attempt $attempt: torn read, retrying..."
    sleep 2
  done
  if [ "$BACKUP_OK" -ne 1 ]; then
    echo "FATAL: could not obtain a verifiable DB copy in 10 attempts."
    echo "       Snapshot the file+wal+shm together and integrity_check that"
    echo "       static copy before concluding the database is damaged."
    exit 1
  fi
elif command -v sqlite3 >/dev/null 2>&1; then
  echo "    WARNING: falling back to the sqlite3 CLI (intermittent on busy WAL)"
  sqlite3 "$LIVE_DB" ".backup '$TEST_DATA/$(basename "$LIVE_DB")'"
  python3 - "$TEST_DATA/$(basename "$LIVE_DB")" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
ic = c.execute("PRAGMA integrity_check").fetchone()[0]
c.close()
if ic != "ok":
    print(f"FATAL: test DB copy failed integrity_check: {ic[:100]}")
    sys.exit(1)
print("    test DB copy integrity: ok")
PY
else
  echo "FATAL: no safe SQLite backup path (need python3 or sqlite3 CLI)"; exit 1
fi

echo "[6] launch TEST instance on :$TEST_PORT"
cd "$REL/.build/next/standalone" || { echo "FATAL: standalone dir missing"; exit 1; }
# NOTE: do NOT `set -a; . .env`. systemd EnvironmentFile syntax permits unquoted
# values with parens/spaces (CLAUDE_USER_AGENT=cli/2.1 (external, cli)) which is
# a shell syntax error when sourced. Parse the way systemd does: split on first
# '=', take the rest literally, no shell evaluation.
ENV_ARGS=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
  k="${line%%=*}"
  v="${line#*=}"
  if [[ "$v" == \"*\" && "$v" == *\" ]]; then v="${v:1:${#v}-2}"; fi
  if [[ "$v" == \'*\' && "$v" == *\' ]]; then v="${v:1:${#v}-2}"; fi
  ENV_ARGS+=("$k=$v")
done < "$ENV_FILE"
echo "    parsed ${#ENV_ARGS[@]} env vars (systemd-style, no shell eval)"

nohup env "${ENV_ARGS[@]}" \
  PORT="$TEST_PORT" \
  DATA_DIR="$TEST_DATA" \
  BASE_URL="http://127.0.0.1:$TEST_PORT" \
  NODE_ENV=production \
  node "$ENTRY" > "$TEST_LOG" 2>&1 &
TEST_PID=$!
echo "    test PID=$TEST_PID log=$TEST_LOG"

cleanup() {
  echo "[cleanup] stopping TEST pid=$TEST_PID"
  kill "$TEST_PID" 2>/dev/null || true
  sleep 2
  kill -9 "$TEST_PID" 2>/dev/null || true
  rm -rf "$TEST_DATA" "$STAGE"
  echo "[cleanup] live: $(systemctl --user is-active "$SERVICE") (MainPID=$(systemctl --user show "$SERVICE" -p MainPID --value))"
}
trap cleanup EXIT

echo "[7] wait for readiness (max 120s)"
# READY flag is load-bearing: without it the loop falls through on timeout and
# every later check runs against a port that never opened, masking the real error.
READY=0
for i in $(seq 1 60); do
  if curl -sf -m 5 "http://127.0.0.1:$TEST_PORT$HEALTH_PATH" >/dev/null 2>&1; then
    echo "    UP after $((i * 2))s"; READY=1; break
  fi
  if ! kill -0 "$TEST_PID" 2>/dev/null; then
    echo "FATAL: test process died"; tail -30 "$TEST_LOG"; exit 1
  fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "FATAL: not healthy after 120s (alive but not serving)"; tail -40 "$TEST_LOG"; exit 1
fi

echo "[8] health"
curl -s -m 10 "http://127.0.0.1:$TEST_PORT$HEALTH_PATH" | head -c 400; echo

# A health endpoint proves the process booted, NOT that it can serve. On the
# 2026-08-01 the router cutover the staged instance passed [8] while /v1/models
# returned {"error":{"code":"AUTH_002"}} — the smoke had never exercised real
# inference. Pull a real key from the TEST DB copy (never the live one) and make
# actual requests across several backends before trusting the release.
echo "[8b] real inference across backends"
SMOKE_FAIL=0
KEY=$(python3 - "$TEST_DATA/$(basename "$LIVE_DB")" <<'PY'
import sqlite3, sys
try:
    # The test DB copy is static, but use the same safe pattern anyway so this
    # never gets copy-pasted onto a live file. See the backup step above.
    c = sqlite3.connect(sys.argv[1], timeout=60)
    c.execute("PRAGMA query_only=ON")
    r = c.execute("select key from api_keys where is_active=1 limit 1").fetchone()
    print(r[0] if r else "")
except Exception:
    print("")
PY
)
if [ -z "$KEY" ]; then
  echo "    WARNING: no API key in test DB — inference NOT verified"
  SMOKE_FAIL=1
else
  # ADAPT: model aliases that route to genuinely different upstream backends.
  for M in $SMOKE_MODELS; do
    printf "    %-14s " "$M"
    CODE=$(curl -s -m 120 -o /tmp/smoke-r.json -w "%{http_code}" \
      -X POST "http://127.0.0.1:$TEST_PORT/v1/messages" \
      -H "x-api-key: $KEY" -H "content-type: application/json" \
      -H "anthropic-version: 2023-06-01" \
      -d "{\"model\":\"$M\",\"max_tokens\":24,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ok\"}]}")
    SERVED=$(python3 -c "import json;print(json.load(open('/tmp/smoke-r.json')).get('model','?'))" 2>/dev/null || echo "?")
    echo "HTTP=$CODE served=$SERVED"
    [ "$CODE" = "200" ] || SMOKE_FAIL=1
  done
  # Streaming is a separate code path from non-stream; exercise it explicitly.
  #
  # 🔴 NEVER pipe a streaming response into `head`. `head -c N` closes the pipe
  # once it has N bytes, curl dies of SIGPIPE, and `grep -q` reports failure on
  # a truncated stream — while the server logs a client-side
  # "disconnect: request_signal_aborted" that reads exactly like a server bug.
  # Measured on the: the same request captured to a FILE
  # returned 1602 bytes / 8 SSE events (message_start, content_block_start,
  # ping, content_block_delta), while the `| head -c 300 |` form reported
  # FAILED every single time. That false negative blocked a good artifact and
  # sent the session hunting a defect that did not exist.
  #
  # Capture to a file, then assert on the saved bytes. Same rule for any
  # SSE / long-poll / tail-style check: `head`, `read -n`, and an early `break`
  # in a while-read loop all kill the producer and manufacture a failure.
  printf "    %-14s " "streaming"
  STREAM_OUT="/tmp/stream-$$.sse"
  curl -s -m 120 -N -X POST "http://127.0.0.1:$TEST_PORT/v1/messages" \
    -H "x-api-key: $KEY" -H "content-type: application/json" \
    -H "anthropic-version: 2023-06-01" \
    -d "{\"model\":\"${SMOKE_MODELS%% *}\",\"max_tokens\":20,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}]}" \
    > "$STREAM_OUT" 2>&1
  STREAM_EVENTS=$(grep -c '^event:' "$STREAM_OUT" 2>/dev/null || true)
  STREAM_EVENTS="${STREAM_EVENTS:-0}"
  # >=2 frames proves the stream actually progressed, not merely opened.
  if [ "$STREAM_EVENTS" -ge 2 ]; then
    echo "OK ($STREAM_EVENTS SSE events, $(wc -c < "$STREAM_OUT") bytes)"
  else
    echo "FAILED ($STREAM_EVENTS SSE events)"
    head -20 "$STREAM_OUT" | sed 's/^/      /'
    SMOKE_FAIL=1
  fi
  rm -f "$STREAM_OUT"
fi

# SMOKE_FAIL is load-bearing: without this gate the smoke results are computed
# and then discarded, so a release that fails every inference check still exits
# 0 and reads as "staged successfully".
if [ "$SMOKE_FAIL" -ne 0 ]; then
  echo "FATAL: smoke tests failed — this artifact must NOT be promoted"
  tail -30 "$TEST_LOG"
  exit 1
fi
echo "    all smoke checks passed"

echo "[9] verify LIVE was never disturbed"
NOW_PID=$(systemctl --user show "$SERVICE" -p MainPID --value)
if [ "$LIVE_PID" = "$NOW_PID" ]; then
  echo "    OK: live untouched ($LIVE_PID)"
else
  echo "    WARNING: live PID changed $LIVE_PID -> $NOW_PID"
fi
curl -s -m 10 -o /dev/null -w "    live :$LIVE_PORT health http=%{http_code}\n" \
  "http://127.0.0.1:$LIVE_PORT$HEALTH_PATH"

echo "=== staged at $REL — nothing swapped ==="
# Verify the caller's way: ssh host 'bash this.sh ... > /tmp/out 2>&1; echo "EXIT=$?"'
# (${PIPESTATUS[0]} inside a quoted ssh string expands LOCALLY and returns empty.)
