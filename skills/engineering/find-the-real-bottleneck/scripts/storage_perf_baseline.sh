#!/bin/bash
# Storage/latency baseline harness for a synchronous-SQLite service on
# network-attached storage (EBS/EFS). Run the SAME script BEFORE and AFTER an
# infrastructure change (volume modify, pragma change, cleanup) so the two runs
# are directly comparable.
#
#   ssh HOST 'bash -s' < storage_perf_baseline.sh BASELINE
#   ...make ONE change...
#   ssh HOST 'bash -s' < storage_perf_baseline.sh AFTER
#
# Emits KEY=VALUE lines so runs can be diffed mechanically.
#
# WHY THIS EXISTS: measurements go stale fast. fsync p50 measured 77ms and then
# 1.03ms on the same host hours apart (after a DB cleanup + restart). Arguing a
# remediation from a stale number aims at the wrong target. Re-baseline
# IMMEDIATELY before proposing any change, and change ONE variable at a time.
#
# Tunables via env: DB_PATH, HEALTH_URL, TABLE, DEVICE, PROVISIONED_MBPS

set -u
LABEL="${1:-run}"
DB_PATH="${DB_PATH:-$HOME/.the router/storage.sqlite}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:20128/api/monitoring/health}"
TABLE="${TABLE:-usage_history}"
DEVICE="${DEVICE:-nvme0n1}"
PROVISIONED_MBPS="${PROVISIONED_MBPS:-125}"

echo "================= STORAGE PERF ($LABEL) ================="
date -u +"timestamp: %Y-%m-%dT%H:%M:%SZ"
echo

# ---------------------------------------------------------------- volume cfg
if command -v aws >/dev/null 2>&1; then
  echo "--- volume configuration (VolumeId Type Size IOPS Throughput) ---"
  TOK=$(curl -s -m 5 -X PUT http://169.254.169.254/latest/api/token \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null)
  IID=$(curl -s -m 5 -H "X-aws-ec2-metadata-token: $TOK" \
        http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null)
  REGION=$(curl -s -m 5 -H "X-aws-ec2-metadata-token: $TOK" \
        http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null)
  aws ec2 describe-volumes --filters "Name=attachment.instance-id,Values=$IID" \
    --query 'Volumes[0].[VolumeId,VolumeType,Size,Iops,Throughput]' \
    --output text --region "${REGION:-us-east-1}" 2>/dev/null | sed 's/^/  /'
  echo
fi

# ------------------------------------------------------- raw fsync latency
# THE dominant term for synchronous SQLite. Gates the whole Node event loop.
echo "--- raw fsync latency (60 samples, 4KB) ---"
python3 -c "
import os,time
f=os.open('/tmp/_perf_fsync',os.O_CREAT|os.O_WRONLY|os.O_TRUNC)
ts=[]
for i in range(60):
    os.write(f,b'x'*4096)
    t=time.time(); os.fsync(f); ts.append((time.time()-t)*1000)
os.close(f); os.unlink('/tmp/_perf_fsync')
ts.sort(); p=lambda q: ts[min(int(len(ts)*q),len(ts)-1)]
print('  FSYNC_P50_MS=%.3f' % p(.50))
print('  FSYNC_P90_MS=%.3f' % p(.90))
print('  FSYNC_MAX_MS=%.3f' % ts[-1])
"
echo

# --------------------------------------------------- sequential write bw
# If this UNDERPERFORMS the provisioned cap, the app is already eating the
# bandwidth -> direct evidence of contention on a saturated volume.
echo "--- sequential write (dd 512MB O_DIRECT) vs provisioned ${PROVISIONED_MBPS} MB/s ---"
dd if=/dev/zero of=/tmp/_perf_dd bs=1M count=512 oflag=direct 2>&1 \
  | tail -1 | sed 's/^/  DD_/'
rm -f /tmp/_perf_dd
echo

# ------------------------------------------------- sqlite insert benchmark
# >=5 alternating trials, MEDIAN reported. Single runs on network storage vary
# ~10x and can "prove" the reverse of the truth.
if [ -f "$DB_PATH" ] && command -v node >/dev/null 2>&1; then
  echo "--- sqlite insert (5 trials x 200, MEDIAN) ---"
  DB_PATH="$DB_PATH" TABLE="$TABLE" node -e "
  const Database=require('better-sqlite3');const fs=require('fs');
  const SRC=process.env.DB_PATH, T=process.env.TABLE, TMP='/tmp/_perf_bench.sqlite';
  function trial(){
    ['','-wal','-shm'].forEach(s=>{try{fs.unlinkSync(TMP+s)}catch(e){}});
    fs.copyFileSync(SRC,TMP);
    const D=new Database(TMP);
    D.pragma('journal_mode=WAL'); D.pragma('synchronous=NORMAL');
    const cols=D.prepare('PRAGMA table_info('+T+')').all().map(c=>c.name).filter(c=>c!=='id');
    const row=D.prepare('SELECT * FROM '+T+' LIMIT 1').get();
    const vals=cols.map(c=>row[c]);
    const st=D.prepare('INSERT INTO '+T+' ('+cols.join(',')+') VALUES ('+cols.map(()=>'?').join(',')+')');
    const t=process.hrtime.bigint();
    for(let i=0;i<200;i++) st.run(vals);
    const ms=Number(process.hrtime.bigint()-t)/1e6;
    D.close();
    ['','-wal','-shm'].forEach(s=>{try{fs.unlinkSync(TMP+s)}catch(e){}});
    return ms/200;
  }
  const r=[]; let guard=0;
  while(r.length<5 && guard++<25){ try{ r.push(trial()); }catch(e){} }
  r.sort((a,b)=>a-b);
  console.log('  runs: '+r.map(x=>x.toFixed(3)).join(', '));
  console.log('  SQLITE_INSERT_MEDIAN_MS='+(r[Math.floor(r.length/2)]||NaN).toFixed(3));
  " 2>&1
  echo
fi

# --------------------------------------------------- live disk write rate
echo "--- live disk write rate (20s) ---"
d1=$(awk -v d="$DEVICE" '$3==d{print $10}' /proc/diskstats)
sleep 20
d2=$(awk -v d="$DEVICE" '$3==d{print $10}' /proc/diskstats)
if [ -n "${d1:-}" ] && [ -n "${d2:-}" ]; then
  echo "  DISK_WRITE_MBPS=$(( (d2-d1)*512/20/1048576 ))"
else
  echo "  DISK_WRITE_MBPS=unavailable (device '$DEVICE' not in /proc/diskstats)"
fi
echo

# ------------------------------------------------- endpoint latency
# 12 samples 4s apart spans cache-warm and cache-cold windows (typical settings
# TTL is ~5s). Median + p90 are the numbers that matter, never a single sample.
echo "--- endpoint latency (12 samples, 4s apart) ---"
TIMES=""
for i in $(seq 1 12); do
  t=$(curl -s -m 45 -o /dev/null -w "%{time_total}" "$HEALTH_URL" 2>/dev/null || echo "NA")
  TIMES="$TIMES $t"
  sleep 4
done
echo "  samples:$TIMES"
echo "$TIMES" | tr ' ' '\n' | grep -E '^[0-9.]+$' | sort -n | awk '
  {a[NR]=$1}
  END{ if(NR>0){
    printf "  HTTP_MEDIAN_S=%.3f\n", a[int(NR/2)+1];
    printf "  HTTP_P90_S=%.3f\n",   a[int(NR*0.9)];
    printf "  HTTP_MAX_S=%.3f\n",   a[NR];
  }}'
echo
echo "================= END ($LABEL) ================="
