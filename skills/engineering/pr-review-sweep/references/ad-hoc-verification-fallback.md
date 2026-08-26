# Ad-hoc verification fallback for sweep/cascade edits

Use this when a sweep or cascade fix changed code but no canonical test/lint/build command is available or detected, or when the original workspace was already cleaned before Hermes' fresh-verification guard ran.

## Pattern

1. Do not claim suite green. Say this is **focused ad-hoc verification**.
2. Create a temporary Python verifier under `/tmp` using `tempfile` with a `hermes-verify-` filename prefix. Avoid hardcoded temp filenames like `/tmp/verify.py`.
3. The verifier should run focused behavior checks against the changed behavior:
   - Prefer existing workspaces when present.
   - If a changed workspace was cleaned, clone the repo to a temporary `hermes-verify-*` directory, check out the PR branch, and run the relevant focused tests there.
   - Print commit SHAs before tests so the evidence ties to the pushed code.
4. Clean up:
   - Remove temporary clones/directories.
   - Remove the temporary verifier script.
   - Optionally list `/tmp/hermes-verify-*.py` leftovers to prove cleanup.
5. Report exact commands and pass counts, but phrase the result as ad-hoc verification, not canonical CI/full-suite success.

## Minimal verifier skeleton

```python
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}  # cwd={cwd}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), text=True)
    if proc.returncode:
        raise SystemExit(proc.returncode)


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="hermes-verify-root-", dir="/tmp"))
    try:
        # clone/checkout if needed, then run focused pytest commands
        # run(["git", "rev-parse", "--short", "HEAD"], repo)
        # run(["python3", "-m", "pytest", "tests/test_specific.py::test_behavior", "-q"], repo)
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

Create and execute the file itself with an outer `tempfile.mkstemp(prefix="hermes-verify-", suffix=".py", dir="/tmp")`, then unlink it in `finally`.
