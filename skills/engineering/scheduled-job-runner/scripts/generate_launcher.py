#!/usr/bin/env python3
"""Generate a filename-only Hermes cron launcher for jobrun."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def render_launcher(*, job_id: str, profile_home: Path, jobrun_path: Path) -> str:
    """Render a launcher with literal profile and runner paths.

    Hermes cron schedules a script filename rather than an argv vector. The
    generated launcher pins HERMES_HOME before executing ``jobrun --spec`` so a
    scheduler process running under another profile cannot resolve the wrong
    ``jobs.d`` directory.
    """
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id must contain only letters, digits, dot, underscore, or hyphen")
    profile = str(profile_home.expanduser().resolve())
    runner = str(jobrun_path.expanduser().resolve())
    return f'''#!/usr/bin/env python3
"""Generated launcher for jobrun spec {job_id!r}. Do not edit."""

import os
import sys

PROFILE_HOME = {json.dumps(profile)}
JOBRUN = {json.dumps(runner)}
os.environ["HERMES_HOME"] = PROFILE_HOME
os.execv(sys.executable, [sys.executable, JOBRUN, "--spec", {json.dumps(job_id)}])
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--profile-home", required=True, type=Path)
    parser.add_argument("--jobrun", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    body = render_launcher(
        job_id=args.job_id,
        profile_home=args.profile_home,
        jobrun_path=args.jobrun,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8")
    args.output.chmod(args.output.stat().st_mode | stat.S_IXUSR)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
