#!/usr/bin/env python3
"""Two-way fixture test for an alarm-detection regex.

WHY THIS EXISTS
A janitor/steward decides what may be deleted by asking "is this an alarm?".
Get that regex wrong in the permissive direction and you delete evidence of a
real fault; get it wrong in the greedy direction and every ordinary sentence
becomes "critical" and the escalation surface is useless.

Measured 2026-08-21: a first-pass regex matching any message CONTAINING
halt|escalat|broken|margin flagged 385 ordinary conversational messages on one
agent as critical. Anchoring to machine-emitted shapes brought it to 135 real
ones. The bug was only visible because both directions were tested.

RULE: never trust an alarm regex that has only been tested against alarms.
A pattern that matches every real alarm AND every sentence about alarms has
100% recall and no precision — it looks like it works.

USAGE
    python alarm_regex_fixture_test.py            # test the reference pattern
    python alarm_regex_fixture_test.py mymod.py   # import NEVER_TOUCH from a module

Exit code 0 = both directions clean. Non-zero = count of failures.
"""
from __future__ import annotations

import importlib.util
import re
import sys

# ---------------------------------------------------------------------------
# Reference pattern: anchors on ALL-CAPS alarm tokens, line starts, and known
# machine emission shapes rather than on any occurrence of an alarming word.
# ---------------------------------------------------------------------------
REFERENCE_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:⚠️|🔴|❌)?\s*"
    r"(?:SEV-[012]\b|[A-Z][A-Z ]*HALTED|[A-Z][A-Z ]*BROKEN|MONITOR BLIND|"
    r"HALT \(|CRITICAL:|FATAL:)"
    r"|\bSEV-[012]\b"
    r"|\b(?:MARGIN CALL|LIQUIDATION|EXPOSURE BREACH|DRAWDOWN LIMIT)\b"
    r"|(?:^|\n)\s*(?:⚠️\s*)?Cron '[^']+' failed"
    r"|\b(?:401|403)\s+(?:Unauthorized|Forbidden)\b"
    r"|\b(?:order|exchange)\s+reject(?:ed|ion)\b"
    r"|\bstale market data\b|\bclock skew\b|\bdisk (?:full|capacity)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Real machine-emitted alarms. Every one MUST match, or the janitor may delete
# standing evidence of an unresolved fault.
MUST_MATCH = [
    "Cronjob Response: Favorite Grinder entry\n-------------\n\n"
    "FAVORITE GRINDER HALTED — PM entry refused.\n"
    "  reason : SEV-1: intent target 25ct but exchange executed two",
    "⚠️ Cron 'Convexity Desk acting guard' failed: Script exited with code 2 "
    "stdout: GUARD CHECK FAILED (exit 2), the watched condition is unmonitored",
    "FAVORITE GRINDER MONITOR — 2026-01-15 07:31 UTC\n"
    "MONITOR BLIND   could not read the exchange: KalshiApiError: HTTP 500",
    "MEMECOIN BOOK HALTED\n  HALT (forward-looking): $-41.19 realized leaves $18.81",
    "CRITICAL: disk full on /dev/sda1",
    "order rejected by exchange: insufficient balance",
    "SEV-0 outage confirmed",
    "403 Forbidden returned by the broker API",
    "stale market data detected on feed 3",
]

# Ordinary agent prose that merely TALKS ABOUT faults. Every one MUST NOT match,
# or ~3x the real alarm volume floods the escalation surface as false positives.
MUST_NOT_MATCH = [
    "That changes the picture. CrawDadExecutor is shared across ~12 modules.",
    "Now the key architectural question — is CrawDadExecutor maker-tick-only?",
    "Here's the plain version, no jargon. The big picture: your research engine",
    "Killed. XTAL surveillance is gone. It was reporting on a token we hold zero of.",
    "That settles it. Here's the honest answer. No — about 90% on PM, one real gap",
    "I should escalate this to you before proceeding, but it can wait until morning.",
    "The halt cleared and entry is running on schedule again.",
    "Done. Deployed at f8fc92f and verified silent against live ARMED state.",
    "I'll check whether the margin requirements changed since last quarter.",
    "The guard was broken earlier but I fixed it and confirmed positions are watched.",
]


def load_pattern(module_path: str | None):
    """Import NEVER_TOUCH from a module path, or use the reference pattern."""
    if not module_path:
        return REFERENCE_PATTERN, "reference pattern"
    spec = importlib.util.spec_from_file_location("_probe", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pat = getattr(mod, "NEVER_TOUCH", None)
    if pat is None:
        raise SystemExit(f"{module_path} defines no NEVER_TOUCH")
    return pat, module_path


def main() -> int:
    pattern, label = load_pattern(sys.argv[1] if len(sys.argv) > 1 else None)
    failures = 0

    for text in MUST_MATCH:
        if not pattern.search(text):
            print(f"MISSED ALARM (must match): {text[:72]!r}")
            failures += 1

    for text in MUST_NOT_MATCH:
        if pattern.search(text):
            print(f"FALSE POSITIVE (must not match): {text[:72]!r}")
            failures += 1

    print(
        f"\n{label}: must_match={len(MUST_MATCH)} "
        f"must_not_match={len(MUST_NOT_MATCH)} failures={failures}"
    )
    if failures == 0:
        print("PASS — both directions clean.")
    else:
        print("FAIL — do not ship this pattern.")
    return failures


if __name__ == "__main__":
    sys.exit(main())
