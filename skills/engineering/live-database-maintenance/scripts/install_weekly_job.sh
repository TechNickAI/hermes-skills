#!/usr/bin/env bash
# Install a recurring per-profile maintenance job on ONE host.
#
# Run this ON each host (or: ssh <host> 'bash -s' < this_file -- /path/to/src).
# Idempotent: re-running REPLACES the job by name rather than duplicating it.
#
# Why per-host and not a central loop: a scheduler that SSHes into every member
# concentrates credentials and failure into one box. Each member runs its own
# copy against its own store.
#
# This only REGISTERS the recurring job. Any backlog catch-up is a separate,
# supervised step -- do not bundle a large one-off deletion into the installer.
#
# Adapt the marked constants; the structure is the reusable part.

set -euo pipefail

SRC_DIR="${1:-/tmp/maint-deploy}"
DRY="${DRY_RUN:-0}"

# ---- adapt these -----------------------------------------------------------
JOB_NAME="db-maintenance"
LAUNCHER="weekly_db_maintenance.py"          # bare FILENAME; cron never splits it
PAYLOAD=("dbmaint.py" "$LAUNCHER")           # files copied into each profile
DELIVER="telegram:-1000000000000:1"          # where failures go
BASE_HOUR=4                                  # Sunday 04:00 local
STAGGER_MIN=20                               # offset between co-tenant profiles
# ---------------------------------------------------------------------------

PY="$HOME/.hermes/hermes-agent/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

for f in "${PAYLOAD[@]}"; do
  [ -f "$SRC_DIR/$f" ] || { echo "missing $SRC_DIR/$f"; exit 2; }
done

slot=0
for base in "$HOME/.hermes" "$HOME"/.hermes/profiles/*; do
  [ -d "$base" ] || continue
  case "$base" in *profiles) continue;; esac
  [ -f "$base/state.db" ] || continue          # adapt: the per-profile marker

  name=$(basename "$base")
  [ "$base" = "$HOME/.hermes" ] && name="_root"

  minute=$(( (slot * STAGGER_MIN) % 60 ))
  hour=$(( BASE_HOUR + (slot * STAGGER_MIN) / 60 ))
  slot=$(( slot + 1 ))

  echo "=== $name -> Sunday ${hour}:$(printf %02d "$minute") ==="
  [ "$DRY" = "1" ] && continue

  mkdir -p "$base/scripts"
  for f in "${PAYLOAD[@]}"; do
    cp "$SRC_DIR/$f" "$base/scripts/$f"
    "$PY" -m py_compile "$base/scripts/$f"
  done

  MIN="$minute" HOUR="$hour" BASE="$base" \
  JOB_NAME="$JOB_NAME" LAUNCHER="$LAUNCHER" DELIVER="$DELIVER" "$PY" - <<'PYEOF'
import json, os, time, uuid, shutil

base = os.environ["BASE"]
expr = f"{os.environ['MIN']} {os.environ['HOUR']} * * 0"
job_name = os.environ["JOB_NAME"]

path = os.path.join(base, "cron", "jobs.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path):
    shutil.copy(path, path + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
    data = json.load(open(path))
else:
    data = {"jobs": []}

jobs = data.setdefault("jobs", [])

# Clone the key set of an existing no_agent job. A hand-written entry missing
# optional keys schedules correctly but renders "Next run: ?" in `cron list`,
# which reads exactly like a broken job and gets dismissed.
template = next((j for j in jobs if j.get("no_agent")), None)
job = {k: None for k in template} if template else {}

job.update({
    "id": uuid.uuid4().the co-tenant host[:12],
    "name": job_name,
    "schedule": {"kind": "cron", "expr": expr, "display": expr},
    "schedule_display": expr,
    "script": os.environ["LAUNCHER"],
    "no_agent": True,
    "deliver": os.environ["DELIVER"],
    "repeat": {"times": None, "completed": 0},
    "enabled": True,
    "state": "scheduled",
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "prompt": "", "skills": [], "context_from": [], "workdir": None,
})

jobs[:] = [j for j in jobs if j.get("name") != job_name]   # idempotent by name
jobs.append(job)
json.dump(data, open(path, "w"), indent=2)
print(f"  registered {job_name} ({expr})")
PYEOF
done

echo
echo "Verify by RE-READING each profile's stored jobs.json."
echo "next_run_at is null until the scheduler's next tick (~60-90s) -- that is"
echo "not a failed registration. Do not scrape 'cron list' with grep -A: it"
echo "bleeds into the following job's fields."
