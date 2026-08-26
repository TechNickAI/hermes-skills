#!/usr/bin/env python3
"""Verify a Hermes profile's CONFIGURED STT path actually transcribes.

Runs the REAL tools.transcription_tools code path rather than a raw curl, so it
proves config + key + provider dispatch all work together for that profile.
This is the difference between "config written" and "verified working".

Usage:
    HERMES_HOME=/path/to/profile AUD=/path/to.ogg python3 stt_verify.py

Exits non-zero if transcription fails, so it can gate a rollout loop.

ROLLOUT PATTERN this supports (see the parent skill, Rule 2):
    1. back up config + .env per profile
    2. apply the change
    3. run THIS against every profile
    4. report the denominator ("12 of 12"), never assume

PORTABILITY: the sys.path insert below points at the Hermes checkout. When
running on a remote host whose checkout lives elsewhere, rewrite it first:
    sed "s|~/.hermes/hermes-agent|$HOME/.hermes/hermes-agent|g" \
        stt_verify.py > /tmp/stt_verify_local.py

PARSING NOTE: match fields with a regex anchored to the label
(e.g. r'provider\\s*:\\s*(\\S+)'). Splitting output lines on ":" breaks because
transcript text contains colons.
"""

import os
import sys
import time

sys.path.insert(0, "~/.hermes/hermes-agent")

AUD = os.environ.get("AUD")
if not AUD or not os.path.exists(AUD):
    sys.exit("set AUD=/path/to/audio")

from tools.transcription_tools import transcribe_audio  # noqa: E402

t0 = time.time()
res = transcribe_audio(AUD)
dt = time.time() - t0

ok = res.get("success")
print(f"HERMES_HOME : {os.environ.get('HERMES_HOME', '(default)')}")
print(f"success     : {ok}")
print(f"provider    : {res.get('provider')}")
print(f"seconds     : {dt:.2f}")
if ok:
    txt = res.get("transcript", "")
    print(f"chars       : {len(txt)}")
    print(f"transcript  : {txt[:400]}")
else:
    print(f"error       : {res.get('error')}")

sys.exit(0 if ok else 1)
