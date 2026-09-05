#!/usr/bin/env python3
"""Regression checks for canonical jobrun merge invariants."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing as mp
import os
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / "jobrun.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _append_worker(ledger: str, lock: str, start, count: int) -> None:
    module = _load(f"jobrun_append_{os.getpid()}")
    module.LEDGER = Path(ledger)
    module.LEDGER_LOCK = Path(lock)
    module.STATE_DIR = Path(ledger).parent
    start.wait()
    for index in range(count):
        module.append_ledger({"event": "job.finished", "worker": os.getpid(), "index": index})


def _prune_worker(ledger: str, lock: str, start, rounds: int) -> None:
    module = _load(f"jobrun_prune_{os.getpid()}")
    module.LEDGER = Path(ledger)
    module.LEDGER_LOCK = Path(lock)
    module.STATE_DIR = Path(ledger).parent
    module.LOG_DIR = Path(ledger).parent / "logs"
    module.LEDGER_MAX_LINES = 100_000
    start.wait()
    for _ in range(rounds):
        module.prune_state()


def check(name: str, condition: bool) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    jobrun = _load("jobrun")

    check("_lines strips blanks", jobrun._lines(" one\n\n two ") == ["one", "two"])
    check("_is_success recognizes generic success", jobrun._is_success("completed successfully"))
    check("_looks_like_failure recognizes an error", jobrun._looks_like_failure("ERROR: write failed"))
    check(
        "failure detail ignores later success",
        jobrun._failure_detail(
            "",
            "ERROR: write failed\ncleanup completed successfully\n",
        )
        == "ERROR: write failed",
    )
    check(
        "stdout failure beats stderr",
        jobrun._failure_detail("FAILED: source unavailable\n", "ERROR: generic\n")
        == "FAILED: source unavailable",
    )

    with tempfile.TemporaryDirectory(prefix="jobrun-merge-") as raw:
        root = Path(raw)
        script = root / "tripwire.py"
        script.write_text("import sys; print('new condition'); sys.exit(10)\n")
        state = root / "state"
        jobrun.HERMES_HOME = root
        jobrun.SPEC_DIR = root / "jobs.d"
        jobrun.STATE_DIR = state
        jobrun.LOG_DIR = state / "logs"
        jobrun.LOCK_DIR = state / "locks"
        jobrun.LEDGER = state / "runs.jsonl"
        jobrun.LEDGER_LOCK = state / "runs.jsonl.lock"
        os.environ["HERMES_HOME"] = str(root)
        os.environ["JOBRUN_INCIDENT_DB"] = str(state / "incidents.db")

        spec = jobrun.Spec(
            {
                "job_id": "tripwire",
                "script": str(script),
                "runtime": "python",
                "exit_map": {"10": "noteworthy"},
            }
        )
        check("noteworthy run maps to success", jobrun.run(spec) == jobrun.EXIT_OK)
        rows = [json.loads(line) for line in jobrun.LEDGER.read_text().splitlines()]
        finished = next(row for row in rows if row.get("event") == "job.finished")
        check("persisted terminal row carries severity", finished.get("severity") == "noteworthy")
        check("persisted terminal row carries reason", bool(finished.get("reason_code")))
        check("noteworthy event is recorded", any(row.get("event") == "job.noteworthy" for row in rows))

    with tempfile.TemporaryDirectory(prefix="jobrun-concurrency-") as raw:
        root = Path(raw)
        ledger = root / "runs.jsonl"
        lock = root / "runs.jsonl.lock"
        workers, per_worker, prune_rounds = 4, 150, 100
        ctx = mp.get_context("spawn")
        start = ctx.Event()
        children = [
            ctx.Process(
                target=_append_worker,
                args=(str(ledger), str(lock), start, per_worker),
            )
            for _ in range(workers)
        ]
        children.append(
            ctx.Process(target=_prune_worker, args=(str(ledger), str(lock), start, prune_rounds))
        )
        for child in children:
            child.start()
        start.set()
        for child in children:
            child.join(30)
        check("concurrency workers exit", all(child.exitcode == 0 for child in children))
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        check("concurrent prune loses no rows", len(rows) == workers * per_worker)

    print("\nAll merge regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
