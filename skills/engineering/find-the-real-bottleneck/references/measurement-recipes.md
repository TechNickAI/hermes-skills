# Measurement recipes

Copy-paste probes. Each isolates ONE arrow in a causal chain. All verified
2026-08-03 against a live Node/Next.js LLM router on `m8g.large` (2 vCPU, 7.6GB).

---

## 1. Does X inflate the managed heap?

The decisive test for any "big data structure → GC pressure" claim.

```bash
node --expose-gc -e "
const b4=process.memoryUsage();
const D=require('better-sqlite3')(process.env.HOME+'/.the router/storage.sqlite',{readonly:true});
const s=D.prepare(\"SELECT key,value FROM key_value WHERE namespace='settings'\").all();
const mid=process.memoryUsage();
for(let i=0;i<20;i++) D.prepare('SELECT COUNT(*) n FROM usage_history').get();
const after=process.memoryUsage();
global.gc();
const gcd=process.memoryUsage();
const mb=x=>(x/1048576).toFixed(1);
console.log('heapUsed before='+mb(b4.heapUsed)+' mid='+mb(mid.heapUsed)+' after='+mb(after.heapUsed)+' postgc='+mb(gcd.heapUsed));
console.log('external '+mb(b4.external)+' -> '+mb(after.external));
console.log('arrayBuf '+mb(b4.arrayBuffers)+' -> '+mb(after.arrayBuffers));
D.close();"
```

Observed against a **245,000-row** table:

```
heapUsed before=3.6 mid=4.1 after=4.1 postgc=3.7
external 1.5 -> 1.5
arrayBuf 0.1 -> 0.1
```

**Interpretation:** zero movement. better-sqlite3 is a C library; rows never
enter the V8 heap. Table size cannot affect JS GC. Any recommendation resting on
that chain is void.

---

## 2. Is it burning CPU or waiting in line?

Splits "working hard" from "queued" — completely different fixes.

```bash
PID=<pid>
c1=$(awk '{print $14+$15}' /proc/$PID/stat)      # utime + stime, in clock ticks
t0=$(date +%s%N)
curl -s -m 60 -o /dev/null http://127.0.0.1:PORT/slow-route
t1=$(date +%s%N)
c2=$(awk '{print $14+$15}' /proc/$PID/stat)
HZ=$(getconf CLK_TCK)
echo "wall: $(( (t1-t0)/1000000 ))ms"
echo "cpu:  $(echo "scale=0; ($c2-$c1)*1000/$HZ" | bc)ms"
```

Observed:

```
wall time: 5,583 ms
CPU used:  2,360 ms      # 42%
```

**Interpretation:** `cpu << wall` → the process spent most of the request
_waiting_, not computing. Rules out compile/GC as the sole story and points at
queueing (single-threaded event loop, lock contention, or downstream I/O).

Rule of thumb: `cpu ≈ wall` → burning. `cpu << wall` → queued/blocked.

---

## 3. The do-nothing probe

Highest value-per-keystroke test in this file. Request something that executes
**no application code**: a 404 on a nonexistent static asset, or a bare redirect.

```bash
sleep 9   # ensure any short-TTL cache has expired
curl -s -m 30 -o /dev/null -w "404 static: %{http_code} %{time_total}s\n" \
  http://127.0.0.1:PORT/_next/static/chunks/does-not-exist.js
curl -s -m 30 -o /dev/null -w "redirect:   %{http_code} %{time_total}s\n" \
  http://127.0.0.1:PORT/dashboard
```

Observed:

```
404 static: 404 5.583361s
redirect:   307 4.529344s
```

**Interpretation:** a 404 on a missing file and a 307 redirect both took seconds.
Neither renders a page, queries a DB, or runs page code. Therefore the cost is
**not** in rendering, queries, or page code — it is upstream of all of them.
This single result invalidated an entire "cold cache → settings query → slow
page" theory.

---

## 4. Correlate latency with concurrency (not with cold/warm)

Under bursty load, cold-vs-warm is an illusion created by _when you sampled_.

```bash
for i in $(seq 1 8); do
  c=$(ss -tn state established 2>/dev/null | grep -c ":PORT")
  t=$(curl -s -m 30 -o /dev/null -w "%{time_total}" http://127.0.0.1:PORT/api/health)
  echo "conns=$c  latency=${t}s"
  sleep 3
done
```

Observed:

```
conns=46  latency=1.768s
conns=44  latency=1.590s
conns=44  latency=4.792s
conns=44  latency=4.066s
conns=44  latency=2.141s
conns=44  latency=3.663s
```

**Interpretation:** latency swung 1.3–4.8s at essentially constant connection
count — noisy under sustained load, not a clean cold/warm split. The earlier
"4.83s cold vs 0.002s warm" reading came from sampling quiet gaps.

---

## 5. Component-in-isolation vs end-to-end

```bash
# the component
sqlite3 db.sqlite ".timer on
SELECT COUNT(*) FROM usage_history WHERE timestamp >= datetime('now','-24 hours');"
# the endpoint that supposedly depends on it
curl -s -m 45 -o /dev/null -w "%{time_total}s\n" http://127.0.0.1:PORT/api/stats
```

Observed: queries `0.002s`–`0.015s`; endpoint `5.8s`. A ~2000x gap exonerates
the database immediately and redirects the investigation.

---

## 6. Leak vs working set

```bash
for i in 1 2 3 4; do
  curl -s -m 20 http://127.0.0.1:PORT/api/health | python3 -c "
import sys,json; m=json.load(sys.stdin)['memoryUsage']
print(f\"rss={m['rss']/1048576:.0f} heap={m['heapUsed']/1048576:.0f} arrayBuf={m['arrayBuffers']/1048576:.0f}\")"
  sleep 30
done
```

Observed:

```
rss=3016 heap=387 arrayBuf=1071
rss=3016 heap=416 arrayBuf=1072
rss=3014 heap=379 arrayBuf=1067
rss=3019 heap=408 arrayBuf=1068
```

**Interpretation:** flat over 90s → working set, not a leak. `arrayBuffers`
at 1.07GB is in-flight stream payloads (avg request 130k input tokens, max
433k), which is genuine concurrent work, not garbage.

---

## 7. Amplification arithmetic for a cost spike

Count **ignition events** from state tables, not errors from logs.

```sql
-- how many distinct sessions/keys ever landed on the expensive path?
SELECT model_str, COUNT(DISTINCT session_id) sessions, COUNT(*) rows
  FROM session_model_history GROUP BY model_str ORDER BY rows DESC;

-- how many expensive calls resulted, since the first ignition?
SELECT COUNT(*) n, SUM(tokens_input) ti
  FROM usage_history
 WHERE provider='openrouter' AND model LIKE '%sonnet%'
   AND timestamp >= '<first ignition ts>';
```

Observed:

```
openrouter/~anthropic/claude-sonnet-latest   6 sessions
=> 452 calls, 105.4M tokens, ~$211    => 75x amplification per ignition
```

**Interpretation:** 6 root events produced 452 expensive calls. The story is the
**amplifier**, not the trigger. Also compare cache-read %: identical work at 0%
vs 86% cache differs ~7x in cost, so volume can look flat while spend explodes.

---

## 8. Ceiling-of-the-win before recommending a resize

```
router overhead (warm)      2.4 ms
upstream LLM (avg TTFT) 16,130 ms   (n=21,409 successful calls, 24h)
=> router = 0.015% of a request
```

Percentiles matter more than the mean: `p50=12,743ms p90=29,026ms p99=77,341ms`.

If the layer you'd upgrade is a rounding error, decline the spend and name the
price: `m8g.large $66/mo → m8g.xlarge $131/mo = +$66/mo for 0.015%`.

**Node-specific caveat:** extra vCPU does not speed up the main event loop.
Where the bottleneck is a saturated single JS thread, more cores cannot help —
only more processes (clustering) or cheaper per-request JS work will.
