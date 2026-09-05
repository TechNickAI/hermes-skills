#!/usr/bin/env python3
"""Checks for generated Hermes cron launchers."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SPEC = importlib.util.spec_from_file_location("generate_launcher", SCRIPTS / "generate_launcher.py")
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def check(name: str, condition: bool) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jobrun-launcher-") as raw:
        root = Path(raw)
        profile = root / "profiles" / "worker"
        runner = root / "skill" / "scripts" / "jobrun.py"
        body = launcher.render_launcher(
            job_id="daily-report",
            profile_home=profile,
            jobrun_path=runner,
        )
        check("launcher pins HERMES_HOME", 'os.environ["HERMES_HOME"] = PROFILE_HOME' in body)
        check("launcher carries literal profile", str(profile) in body)
        check("launcher carries literal runner", str(runner) in body)
        check("launcher passes spec", '"--spec", "daily-report"' in body)
        compile(body, "<generated-launcher>", "exec")
        check("launcher compiles", True)

        output = root / "daily-report.py"
        output.write_text(body)
        output.chmod(output.stat().st_mode | 0o100)
        check("launcher can be executable", os.access(output, os.X_OK))

        try:
            launcher.render_launcher(job_id="../bad", profile_home=profile, jobrun_path=runner)
        except ValueError:
            rejected = True
        else:
            rejected = False
        check("invalid job id rejected", rejected)

    print("\nAll launcher checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
