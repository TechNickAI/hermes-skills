#!/usr/bin/env python3
"""Sandbox config-lever probe harness.

Copies a profile's config.yaml into a throwaway HERMES_HOME, applies one or more
mutations, runs a REAL code path against each variant, and prints results side
by side with an unmutated baseline.

Use this instead of hand-rolling a probe each session, and instead of editing
the live config to find out what a key does.

Usage
-----
Import and call ``probe()`` with a mutation function and an inline snippet that
exercises the real code path::

    from probe_config_lever import probe, baseline

    CODE = (
        "import json;"
        "from hermes_cli.config import load_config;"
        "c=load_config();"
        "print('OUT'+json.dumps(sorted((c.get('providers') or {}).keys())))"
    )

    baseline(CODE)
    probe(lambda c: c['providers'].pop('gemini', None),
          CODE, note="remove providers.gemini")

Notes
-----
* Runs with the APPLICATION's interpreter (PY below), not system python — a
  system python3 lacks the package and its ImportError masquerades as a config
  error.
* ruamel round-trips so unrelated formatting/comments survive the mutation.
* Always compare against ``baseline()``; without a before/after you cannot
  attribute an observed difference to your edit.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

# Application interpreter. Override via HERMES_PY if the install moves.
PY = os.environ.get(
    "HERMES_PY",
    "~/.local/share/uv/tools/hermes-agent/bin/python3",
)
# Source profile whose config is copied. Override via PROBE_PROFILE.
PROFILE = pathlib.Path(
    os.environ.get("PROBE_PROFILE", "$HERMES_HOME")
)

_MARKER = "OUT"


def _run(tmp: pathlib.Path, code: str, timeout: int = 300) -> tuple[str, str]:
    """Execute *code* with HERMES_HOME pointed at *tmp*. Returns (stdout, stderr)."""
    proc = subprocess.run(
        [PY, "-c", code],
        env=dict(os.environ, HERMES_HOME=str(tmp)),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout, proc.stderr


def _extract(stdout: str):
    """Pull the JSON payload printed after the marker, if present."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(_MARKER):
            try:
                return json.loads(line[len(_MARKER):])
            except json.JSONDecodeError:
                return line[len(_MARKER):]
    return stdout.strip() or None


def _materialize(mutate: Optional[Callable]) -> pathlib.Path:
    """Copy config into a temp home and apply *mutate* to the parsed tree."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="probe_"))
    shutil.copy(PROFILE / "config.yaml", tmp / "config.yaml")
    if mutate is not None:
        import ruamel.yaml

        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True
        yaml.width = 4096
        with open(tmp / "config.yaml") as fh:
            cfg = yaml.load(fh)
        mutate(cfg)
        with open(tmp / "config.yaml", "w") as fh:
            yaml.dump(cfg, fh)
    return tmp


def probe(mutate: Optional[Callable], code: str, note: str = "", show_stderr: bool = False):
    """Apply *mutate* to a throwaway config copy and run *code* against it.

    ``mutate`` receives the parsed config tree and edits it in place. Pass
    ``None`` to run against an untouched copy (see :func:`baseline`).
    """
    tmp = _materialize(mutate)
    stdout, stderr = _run(tmp, code)
    result = _extract(stdout)
    label = note or ("baseline" if mutate is None else "mutation")
    print(f"\n=== {label}")
    if isinstance(result, list):
        for item in result:
            print("   ", item)
    else:
        print("   ", result)
    if show_stderr and stderr.strip():
        for line in stderr.strip().splitlines()[-3:]:
            print("    stderr:", line[:160])
    return result


def baseline(code: str, **kw):
    """Run *code* against an unmutated copy. Always capture this first."""
    return probe(None, code, note="baseline (unmutated)", **kw)


def matrix(cases: list[tuple[str, Callable]], code: str, **kw) -> dict:
    """Probe several levers and return {note: result}.

    Use when the question is "can X be turned off at all" — a single failed
    lever is not proof of impossibility. Prints a compact same/differs summary
    against the baseline so a silent no-op is obvious.
    """
    base = baseline(code, **kw)
    results = {}
    for note, mutate in cases:
        results[note] = probe(mutate, code, note=note, **kw)

    print("\n=== SUMMARY vs baseline")
    for note, res in results.items():
        verdict = "NO-OP (same as baseline)" if res == base else "changed"
        print(f"   {note:<44} {verdict}")
    return results


if __name__ == "__main__":
    # Self-check: prove the harness runs and the interpreter resolves.
    demo = (
        "import json;"
        "from hermes_cli.config import load_config;"
        "c=load_config();"
        "print('OUT'+json.dumps(sorted((c.get('providers') or {}).keys())))"
    )
    print(f"interpreter : {PY}")
    print(f"profile     : {PROFILE}")
    baseline(demo)
