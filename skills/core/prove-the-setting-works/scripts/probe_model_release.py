#!/usr/bin/env python3
"""Probe a NEW model release against the INCUMBENT before pinning it.

Why this exists
---------------
A version bump is an unverified config lever. The config parses, the call
returns 200, and the output can still be corrupted or 4x slower. Verified
One case: grok-4.6 leaked raw control tokens into user-facing prose on 2 of 4
trials while grok-4.5 was clean 4 of 4 -- every call HTTP 200. A single probe
would have passed it half the time.

What it checks
--------------
  * n trials per model, alternating candidate and incumbent on identical prompts
  * control-token / tool-directive leakage in the OUTPUT TEXT (not status)
  * per-trial latency, so "slower TTFT" reports become measured facts

Usage
-----
Edit CONFIG below, then run with the APPLICATION'S OWN interpreter so the real
credential resolver imports cleanly:

    cd ~/.hermes/hermes-agent && ./venv/bin/python probe_model_release.py

Adapt `call()` to whatever the real code path is. The default targets an xAI
Responses-style endpoint with a server-side tool; the STRUCTURE (alternating
trials, leak assertions, latency capture) is the reusable part, not the vendor.
"""

import json
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

APP_ROOT = "~/.hermes/hermes-agent"

CANDIDATE = "grok-4.6"   # the new release under evaluation
INCUMBENT = "grok-4.5"   # what is pinned today

TRIALS_PER_PROMPT = 2    # total trials per model = TRIALS_PER_PROMPT * len(PROMPTS)

PROMPTS = [
    "In one short sentence, what is xAI's newest Grok model?",
    "What are people saying about it this week? One sentence.",
]

# Server-side tool to exercise, or None for a plain completion.
TOOLS = [{"type": "x_search"}]

# Strings that must NEVER appear in user-facing output. Extend per vendor.
LEAK_MARKERS = (
    "<|",
    "|>",
    "<|eos|>",
    "render_inline_citation",
    "citation_id is",
)


# --------------------------------------------------------------------------
# Credential resolution -- use the APP'S resolver, never a hand-rolled key read
# --------------------------------------------------------------------------

def resolve_credentials():
    sys.path.insert(0, APP_ROOT)
    from tools.xai_http import resolve_xai_http_credentials  # type: ignore

    creds = resolve_xai_http_credentials()
    key = str(creds.get("api_key") or "").strip()
    base = str(creds.get("base_url") or "https://api.x.ai/v1").strip().rstrip("/")
    if not key:
        raise RuntimeError("no usable credential returned by the app resolver")
    return key, base, str(creds.get("provider") or "?")


# --------------------------------------------------------------------------
# One real call
# --------------------------------------------------------------------------

def call(model, prompt, key, base, timeout=180):
    """Return (seconds, text, raw). Adapt this to the real code path."""
    body = {"model": model, "input": prompt}
    if TOOLS:
        body["tools"] = TOOLS

    req = urllib.request.Request(
        f"{base}/responses",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read().decode())
    dt = time.time() - t0

    texts = []
    for item in raw.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text"):
                texts.append(part.get("text", ""))
    return dt, (texts[0] if texts else ""), raw


def leaks_in(text):
    return [m for m in LEAK_MARKERS if m in text]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    key, base, source = resolve_credentials()
    print(f"credential source : {source}")
    print(f"base_url          : {base}\n")

    summary = {}

    for model in (CANDIDATE, INCUMBENT):
        print(f"########## {model}")
        clean = leaked = failed = 0
        lats = []

        for qi, prompt in enumerate(PROMPTS, 1):
            for trial in range(1, TRIALS_PER_PROMPT + 1):
                try:
                    dt, text, _ = call(model, prompt, key, base)
                    lats.append(dt)
                    bad = leaks_in(text)
                    if bad:
                        leaked += 1
                        status = f"LEAK {bad}"
                    else:
                        clean += 1
                        status = "clean"
                    print(f"  q{qi} t{trial}  {dt:5.1f}s  {status}")
                    print(f"      {text[:150]}")
                except urllib.error.HTTPError as e:
                    failed += 1
                    print(f"  q{qi} t{trial}  HTTP {e.code}  {e.read().decode()[:200]}")
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"  q{qi} t{trial}  FAILED {type(e).__name__}: {e}")

        summary[model] = {
            "clean": clean,
            "leaked": leaked,
            "failed": failed,
            "lat_min": min(lats) if lats else None,
            "lat_max": max(lats) if lats else None,
        }
        print()

    print("=" * 62)
    print("VERDICT")
    for model, s in summary.items():
        total = s["clean"] + s["leaked"] + s["failed"]
        lat = (
            f"{s['lat_min']:.1f}-{s['lat_max']:.1f}s"
            if s["lat_min"] is not None
            else "n/a"
        )
        print(
            f"  {model:12} clean {s['clean']}/{total}  "
            f"leaked {s['leaked']}  failed {s['failed']}  latency {lat}"
        )

    cand = summary[CANDIDATE]
    inc = summary[INCUMBENT]
    print()
    if cand["leaked"] > inc["leaked"] or cand["failed"] > inc["failed"]:
        print("  DO NOT PIN. Candidate regresses against the incumbent.")
    elif cand["lat_max"] and inc["lat_max"] and cand["lat_max"] > 2 * inc["lat_max"]:
        print("  HOLD. Candidate is materially slower; decide with the owner.")
    else:
        print("  No regression observed in this sample. Small n -- say so.")


if __name__ == "__main__":
    main()
