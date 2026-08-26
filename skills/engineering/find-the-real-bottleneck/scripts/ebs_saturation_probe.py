#!/usr/bin/env python3
"""Prove whether an EBS volume is actually saturated, at percentile resolution.

Answers "should this box be on faster/local storage?" with numbers instead of
plausibility. See references/falsifying-a-hardware-premise.md.

Usage:
    python3 ebs_saturation_probe.py <volume-id> <region> [days] [--iops N] [--mbps N]

    python3 ebs_saturation_probe.py vol-0200b78c1a3672c01 ca-central-1 13

If --iops/--mbps are omitted the script reads the provisioned values from the
EC2 API, so the comparison is always against what you actually pay for.

WHY THIS EXISTS (two traps this encodes):
  1. CloudWatch rejects any single get-metric-statistics call asking for more
     than 1440 datapoints. 13 days at 300s = 3744 -> InvalidParameterCombination
     on the WHOLE call. We chunk by day and merge.
  2. A probe that can print "0 samples" for both 'idle' and 'my API call failed'
     is worthless. This one exits non-zero and refuses to compute statistics
     over an empty set.
"""
import argparse
import datetime
import json
import subprocess
import sys


def aws_json(args):
    p = subprocess.run(["aws"] + args + ["--output", "json"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:400])
    return json.loads(p.stdout or "{}")


def provisioned(volume_id, region):
    """Read provisioned IOPS/throughput. Comparing against the DEFAULT (3000)
    when the volume was already raised is a classic false alarm."""
    d = aws_json(["ec2", "describe-volumes", "--region", region,
                  "--volume-ids", volume_id])
    v = d["Volumes"][0]
    return v.get("Iops"), v.get("Throughput"), v.get("VolumeType"), v.get("Size")


def series(volume_id, region, metric, stat, start, end, period=300):
    """Fetch one metric, chunked by day to stay under the 1440-datapoint cap."""
    out, failures = {}, []
    day = start
    while day < end:
        chunk_end = min(day + datetime.timedelta(days=1), end)
        try:
            d = aws_json([
                "cloudwatch", "get-metric-statistics", "--region", region,
                "--namespace", "AWS/EBS", "--metric-name", metric,
                "--dimensions", f"Name=VolumeId,Value={volume_id}",
                "--start-time", day.strftime("%Y-%m-%dT%H:%M:%S"),
                "--end-time", chunk_end.strftime("%Y-%m-%dT%H:%M:%S"),
                "--period", str(period), "--statistics", stat,
            ])
            for dp in d.get("Datapoints", []):
                out[dp["Timestamp"]] = dp[stat]
        except RuntimeError as e:
            failures.append(f"{metric} {day:%Y-%m-%d}: {e}")
        day = chunk_end
    if failures:
        # Loud, not silent: a partial series must never masquerade as low load.
        for f in failures:
            print(f"!! {f}", file=sys.stderr)
    return out, failures


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(int(len(sorted_vals) * p), len(sorted_vals) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("volume_id")
    ap.add_argument("region")
    ap.add_argument("days", nargs="?", type=int, default=13)
    ap.add_argument("--iops", type=int, default=None)
    ap.add_argument("--mbps", type=int, default=None)
    ap.add_argument("--period", type=int, default=300)
    a = ap.parse_args()

    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=a.days)

    prov_iops, prov_mbps, vtype, size = (a.iops, a.mbps, "?", "?")
    try:
        p_i, p_m, vtype, size = provisioned(a.volume_id, a.region)
        prov_iops = a.iops or p_i
        prov_mbps = a.mbps or p_m
    except Exception as e:
        print(f"!! could not read volume config: {e}", file=sys.stderr)

    all_fail = []
    ro, f1 = series(a.volume_id, a.region, "VolumeReadOps", "Sum", start, end, a.period)
    wo, f2 = series(a.volume_id, a.region, "VolumeWriteOps", "Sum", start, end, a.period)
    rb, f3 = series(a.volume_id, a.region, "VolumeReadBytes", "Sum", start, end, a.period)
    wb, f4 = series(a.volume_id, a.region, "VolumeWriteBytes", "Sum", start, end, a.period)
    qd, f5 = series(a.volume_id, a.region, "VolumeQueueLength", "Average", start, end, a.period)
    all_fail = f1 + f2 + f3 + f4 + f5

    iops = sorted((ro.get(t, 0) + wo.get(t, 0)) / a.period for t in set(ro) | set(wo))
    mbps = sorted((rb.get(t, 0) + wb.get(t, 0)) / a.period / 1e6 for t in set(rb) | set(wb))
    q = sorted(qd.values())

    if not iops:
        print("FAILED: zero samples returned. This is absence of information, "
              "NOT evidence of low load. Check the volume id, region, and "
              "credentials before concluding anything.", file=sys.stderr)
        sys.exit(1)

    print(f"volume {a.volume_id}  type={vtype}  size={size}GB")
    print(f"window: {a.days} days, {a.period}s resolution, {len(iops)} samples")
    if all_fail:
        print(f"WARNING: {len(all_fail)} chunk(s) failed - series is INCOMPLETE, "
              f"percentiles understate true load")
    print(f"IOPS      p50={pct(iops,.50):>8.0f} p95={pct(iops,.95):>8.0f} "
          f"p99={pct(iops,.99):>8.0f} max={iops[-1]:>8.0f}   provisioned={prov_iops}")
    print(f"MB/s      p50={pct(mbps,.50):>8.1f} p95={pct(mbps,.95):>8.1f} "
          f"p99={pct(mbps,.99):>8.1f} max={mbps[-1]:>8.1f}   provisioned={prov_mbps}")
    if q:
        print(f"QueueLen  p50={pct(q,.50):>8.2f} p95={pct(q,.95):>8.2f} "
              f"p99={pct(q,.99):>8.2f} max={q[-1]:>8.2f}   (>1 = requests WAITING on disk)")
    print()
    if prov_iops:
        print(f"windows >80% provisioned IOPS ({int(prov_iops*0.8)}): "
              f"{sum(1 for x in iops if x > prov_iops*0.8)} of {len(iops)}")
        print(f"windows >50% provisioned IOPS ({int(prov_iops*0.5)}): "
              f"{sum(1 for x in iops if x > prov_iops*0.5)} of {len(iops)}")
    if q:
        print(f"windows with QueueLen >1:  {sum(1 for x in q if x > 1)} of {len(q)}")
    print()
    print("READING IT: QueueLength is the saturation signal, not raw IOPS. "
          "A p99 well under provisioned means storage CANNOT be the bottleneck. "
          "State the caveat if your window misses the known-busiest day.")


if __name__ == "__main__":
    main()
