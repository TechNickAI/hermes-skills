#!/usr/bin/env python3
"""STT bake-off harness: local faster-whisper vs a cloud STT vendor.

Generalizes the 2026-08 ElevenLabs-vs-Whisper evaluation. Runs every engine
against the SAME audio file and reports transcript + wall-clock latency so the
comparison is like-for-like.

Usage:
    AUD=/path/to/voice.ogg ELEVENLABS_API_KEY=sk_... python3 stt_bakeoff.py

Run it with a Python that has faster-whisper installed (on a Hermes host that is
usually <hermes_home>/hermes-agent/venv/bin/python).

WHY THIS SHAPE
- Include the INCUMBENT and the free local-upgrade path as arms, not just
  old-vs-new. "Use the bigger model already on disk" deserves a fair test.
- Always report latency. A local model that is free but pegs the CPU for 60s
  per item is not viable on a host running production gateways.
- Prefer REAL user audio over synthetic TTS clips. Synthetic speech is cleaner
  than a real recording and will overstate the value of accuracy aids such as
  keyterm prompting.
- Best samples are ones with a KNOWN-WRONG prior result (a stored transcript
  annotated "possible mishearing"), which act as natural gold labels.
"""

import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

AUD = os.environ.get("AUD")
if not AUD or not os.path.exists(AUD):
    sys.exit("set AUD=/path/to/audio")

# Domain vocabulary the model would not otherwise know. Keep entries under 50
# chars. NOTE: measured impact on real audio was negligible-to-harmful; treat
# keyterms as opt-in and always A/B them rather than assuming they help.
KEYTERMS = [t for t in os.environ.get("KEYTERMS", "").split(",") if t.strip()]

results = {}


def timed(label, fn):
    t0 = time.time()
    try:
        txt = fn()
    except Exception as exc:  # noqa: BLE001
        txt = f"<ERROR: {exc}>"
    dt = time.time() - t0
    results[label] = {"text": txt, "secs": round(dt, 2)}
    print(f"\n=== {label}  ({dt:.2f}s) ===\n{txt}")


def local(model_name):
    """Local faster-whisper arm."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(AUD, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def scribe(use_keyterms):
    """ElevenLabs Scribe arm.

    Keyterms MUST be sent as repeated form fields. `keyterms_prompt=` and
    `keywords=` both return HTTP 200 and silently do nothing.
    """
    import requests

    key = os.environ["ELEVENLABS_API_KEY"]
    data = [("model_id", "scribe_v2")]
    if use_keyterms and KEYTERMS:
        data += [("keyterms", k.strip()) for k in KEYTERMS]
    with open(AUD, "rb") as fh:
        resp = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": key},
            data=data,
            files={"file": fh},
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


print(f"AUDIO: {AUD}  ({os.path.getsize(AUD)} bytes)")
timed("whisper-base (incumbent default)", lambda: local("base"))
timed("whisper-large-v3-turbo (free local upgrade)", lambda: local("large-v3-turbo"))
timed("scribe_v2 (no keyterms)", lambda: scribe(False))
if KEYTERMS:
    timed("scribe_v2 + keyterms", lambda: scribe(True))

out = os.environ.get("OUT", "/tmp/stt_bakeoff_result.json")
with open(out, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"\nsaved -> {out}")
