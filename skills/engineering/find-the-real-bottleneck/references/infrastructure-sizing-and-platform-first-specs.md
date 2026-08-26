# Sizing and speccing infrastructure: measure, and check the platform first

Three failure modes hit in one session (one occasion) while sizing and speccing a
cloud host. All three produced confident, wrong recommendations the operator had
to push back on. All three are attribution failures: asserting a plausible
mechanism instead of measuring the real one.

## 1. Padding a spec instead of measuring it

Recommended 8 GB RAM and 60 GB disk. the operator: _"do we really need that much ram?
that much disk space?"_

Measuring took two SSH commands and cut the spec — and the bill — nearly in half:

```bash
ps -eo rss,comm --sort=-rss | head -8     # what actually holds memory
du -sh ~/.hermes/* | sort -rh | head      # what actually holds disk
free -m; df -h /
```

The agent gateway was **316 MB RSS**, not the multi-GB implicitly assumed. The
real memory driver was the desktop + browser, and the reference box's 12 GB of
disk was mostly a year of accumulated `state.db` plus an avoidable snap install.
Result: 8 GB → 4 GB, 60 GB → 30 GB, ~$73/mo → ~$28/mo.

**Never recommend a size you have not measured on a comparable live system.**
Padding reads as diligence and is actually an unpriced tax paid monthly.

**Corollary — report your estimate's error.** Post-build the disk landed at 51%,
not the predicted 5-6 GB, because a container image was 4.5 GB. Say so
explicitly rather than letting the earlier estimate quietly stand.

## 2. Falsifying your own cautionary tale before repeating it

Argued against burstable instances citing a fleet box pinned at 0 CPU credits
for 7 days. the operator: _"that box is not really used, its just basically idle."_

Chasing the contradiction found the real cause: a legacy hourly LLM health check
respawning constantly and consuming the box it monitored. The box was never
evidence about burstable workloads at all — the comparison was invalid, and the
recommendation stood on _better_ grounds once corrected.

**`ps %CPU` shows a LIFETIME AVERAGE and hides current bursts.** A long-running
process that was busy at boot looks busy forever; a process spawning and dying
every 5s barely registers. To find what is burning CPU _now_, delta
`/proc/<pid>/stat` fields 14+15 (utime+stime) over a fixed window:

```bash
declare -A t1
for p in /proc/[0-9]*; do pid=${p#/proc/}; [ -r $p/stat ] || continue
  set -- $(cat $p/stat 2>/dev/null); t1[$pid]=$(( ${14}+${15} )); done
sleep 10
for p in /proc/[0-9]*; do pid=${p#/proc/}; [ -r $p/stat ] || continue
  set -- $(cat $p/stat 2>/dev/null)
  d=$(( ${14}+${15} - ${t1[$pid]:-0} )); [ $d -gt 0 ] &&
    echo "$d $pid $(tr -d '\0' < /proc/$pid/comm)"
done | sort -rn | head
# 100 ticks over 10s == 1 full core
```

Also check `/proc/stat` user-vs-system split first: high `user` with no visible
long-lived process means short-lived respawns, which `top` snapshots miss.

**When a data point contradicts what the operator knows about their own system,
the data point usually needs explaining — not the operator.**

## 3. Reaching for known tools instead of what the platform ships

Recommended xrdp (forcing a **Microsoft** client on a **Mac** user — rejected
outright), then NoMachine (third-party freeware), then raw x11vnc + noVNC.

The first-party answer was free the whole time: **Amazon DCV**, AWS's own
remote-display protocol, free on EC2 (_"no additional charge to use Amazon DCV
on Amazon EC2"_), with a native Apple-Silicon client AND an HTML5 web client,
shipping `arm64.ubuntu2404.deb` packages.

**Before recommending a third-party tool, ask what the platform already being
paid for provides.** AWS, GCP, Azure, and GitHub ship first-party answers to
common problems that beat bolt-ons on integration, licensing, and support.

## Verify vendor claims against artifacts, not marketing pages

```bash
# HEAD returns 200 with size 0 on CDNs; a RANGE GET proves real bytes exist
curl -sS -o /dev/null -w '%{http_code} %{size_download}' -r 0-0 "$URL"   # want 206

# container images: read manifest platforms, never assume multi-arch
curl -sS -H "Authorization: Bearer $TOK" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  "https://registry-1.docker.io/v2/$REPO/manifests/$TAG" |
  python3 -c "import sys,json;[print(m['platform']) for m in json.load(sys.stdin).get('manifests',[])]"
```

This caught that `kasmweb/*` images are **x86_64-only** (all 68 tags amd64 — the
arch is in the tag names) while `linuxserver/chromium` publishes a real arm64
manifest. On Graviton that is the difference between working and not.

## Solve the stated problem, not the assumed one

A full XFCE desktop was designed before asking what the human would actually do
with it. the operator: _"I don't think she needs full desktop access, or am I missing
something."_

He was right. The hands-on need was **logging into sites so the agent inherits
the sessions** — a browser, not a desktop. Dropping the desktop removed an
entire software layer, ~400 MB of RAM, a display manager, and a class of failure.

**Ask what the human will DO on the machine before choosing the stack.** "Needs
a browser sometimes" and "needs a desktop" produce very different builds.

## Pricing: pull it live, per candidate

Never quote instance or storage pricing from memory — it moves, and it is
region-specific. The Pricing API is authoritative and answers in one call:

```bash
aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
  --filters "Type=TERM_MATCH,Field=instanceType,Value=$T" \
            "Type=TERM_MATCH,Field=regionCode,Value=$R" \
            "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" \
            "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
            "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
            "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" --max-results 1
```

Compare on-demand against the 1yr no-upfront RI in the same pass, and recommend
running on-demand for 30-60 days FIRST — buying a reservation before the shape
is known locks in the wrong box.

**Name the dominant cost line, even when it is not the one you were asked
about.** Here the infra was ~$28/mo while measured token spend for a comparable
personal agent was 3.4B input tokens in 30 days. Optimizing the instance type
while ignoring the model tier is optimizing the wrong number.
