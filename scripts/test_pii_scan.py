#!/usr/bin/env python3
"""Known-answer tests for scripts/pii_scan.py.

This gate has been wrong in BOTH directions historically, so every rule is
tested for what it must CATCH and what it must NOT flag. A scanner that returns
zero blockers is only meaningful if it has been shown to fail on real leaks.

Run: python3 scripts/test_pii_scan.py
"""
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pii_scan  # noqa: E402


def sev_for(text: str):
    """Return {rule_name: severity} for every rule matching text."""
    out = {}
    for name, rx, sev in pii_scan.COMPILED:
        if rx.search(text):
            out[name] = sev
    return out


# (sample, rule that must fire at BLOCKER, why it matters)
MUST_BLOCK = [
    ("Use when Nick asks for a multi-review", "person",
     "bare first name — the whole fleet's docs say 'Nick', not 'Nick Sullivan'"),
    ("Nick's framing: \"this is not a merge\"", "person", "possessive first name"),
    ("failure mode Nick named directly (2026-07-21)", "person", "first name in prose"),
    ("ask Julianna about the calendar", "person", "other household member"),
    ("`/Users/nick/.hermes/profiles/x/config.yaml`", "home-path", "absolute home path"),
    ("export HOME=/Users/nick (literal path)", "home-path",
     "home path with NO trailing slash — this evaded the original rule"),
    ("cd /home/deploy/src && ls", "home-path", "linux home path for a named user"),
    ("a 6-reviewer Lendy strategy panel", "venture", "venture/product codename"),
    ("the Fiddler knowledge folder", "venture", "venture codename"),
    ("carmentacollective/antevorta#17", "venture", "private org and repo slugs"),
    ("cryptoai and hangl-dashboard", "venture", "private project slugs"),
    ("run it on bosun first", "agent-name", "agent name"),
    ("https://omniroute.technick.ai/v1/messages", "private-domain", "private domain"),
    ("ssh 100.111.23.60", "network", "tailnet address"),
    ("token sk-abcdefghijklmnopqrstuvwx", "SECRET", "api key shape"),
]

# Text that must NOT trip a blocker — the gate is useless if it cries wolf.
MUST_PASS = [
    ("the interface exposes a namespace", "'ace' inside interface/namespace"),
    ("replace the workspace trace", "'ace' inside replace/workspace/trace"),
    ("/Users/<user>/.hermes/config.yaml", "documented placeholder path"),
    ("/Users/you/projects", "documented placeholder path"),
    ("/home/ubuntu", "generic cloud default user"),
    ("nickel and dime the budget", "'nick' as a substring of a real word"),
    ("a knickknack on the shelf", "'nick' inside knickknack"),
    ("St Nicholas Day", "'Nich' prefix of an unrelated word"),
    ("the corallium reef sample", "'cora' as a substring"),
    ("localhost:8080 and 127.0.0.1", "loopback is not PII"),
    ("example.com and github.com", "public domains"),
]

def main():
    fail = 0

    print("=== MUST BLOCK ===")
    for text, expect, why in MUST_BLOCK:
        got = sev_for(text)
        ok = got.get(expect) == "BLOCKER"
        fail += not ok
        print(f"  {'OK ' if ok else 'FAIL'} {expect:15} {text[:46]:48} {got or '{}'}")
        if not ok:
            print(f"       ^ {why}")

    print("\n=== MUST NOT BLOCK ===")
    for text, why in MUST_PASS:
        got = {k: v for k, v in sev_for(text).items() if v == "BLOCKER"}
        ok = not got
        fail += not ok
        print(f"  {'OK ' if ok else 'FAIL'} {text[:50]:52} {got or 'clean'}")
        if not ok:
            print(f"       ^ should be fine: {why}")

    # End-to-end: the CLI must exit non-zero on a real leak, or CI cannot gate.
    print("\n=== CLI gating ===")
    with tempfile.TemporaryDirectory() as d:
        bad = pathlib.Path(d) / "leak.md"
        bad.write_text("Use when Nick asks. Config at /Users/nick/.hermes/config.yaml\n")
        r = subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "pii_scan.py"), str(bad)],
                           capture_output=True, text=True)
        ok = r.returncode != 0
        fail += not ok
        print(f"  {'OK ' if ok else 'FAIL'} exits non-zero on a leaking file (got {r.returncode})")

        good = pathlib.Path(d) / "clean.md"
        good.write_text("Use when the operator asks. Config at /Users/<user>/.hermes/config.yaml\n")
        r = subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "pii_scan.py"), str(good)],
                           capture_output=True, text=True)
        ok = r.returncode == 0
        fail += not ok
        print(f"  {'OK ' if ok else 'FAIL'} exits zero on a clean file (got {r.returncode})")

    print("\nRESULT:", "ALL PASS" if not fail else f"{fail} FAILURES")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
