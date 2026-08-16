#!/usr/bin/env python3
"""Serial PR-review-sweep runner.

Edit CONFIG at the top, or set matching environment variables, then run from a
Hermes terminal background session:

    python3 scripts/run_pr_review_sweep.py

The runner expects a scan JSON produced by the sweep triage step. It provisions a
fresh clone fallback workspace per PR, invokes Claude Code once per PR, verifies
that address-pr-comments was used by inspecting Claude JSONL, verifies the
original PR's unhandled count dropped to zero, and writes an incremental results
JSON so a long cron run has an audit trail even if interrupted.

This script is intentionally conservative: it serializes PR dispatches and never
merges anything.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# ---- CONFIG ---------------------------------------------------------------
SCAN_PATH = Path(os.environ.get("PR_SWEEP_SCAN", "/tmp/pr_review_sweep_scan.json"))
RESULTS_PATH = Path(os.environ.get("PR_SWEEP_RESULTS", "/tmp/pr_review_sweep_results.json"))
MAX_PRS_PER_RUN = int(os.environ.get("MAX_PRS_PER_RUN", "10"))
TIMEOUT_PER_PR_S = int(os.environ.get("TIMEOUT_PER_PR_S", "1800"))
FOLLOWUP_LABELS = [x.strip() for x in os.environ.get("FOLLOWUP_LABELS", "review-sweep").split(",") if x.strip()]
EXCLUDE_REPOS = {x.strip() for x in os.environ.get("EXCLUDE_REPOS", "").split(",") if x.strip()}
HOME = Path.home()
SWEEP_ROOT = Path(os.environ.get("SWEEP_ROOT") or (HOME / "dev" if (HOME / "dev").is_dir() and os.access(HOME / "dev", os.W_OK) else HOME / "pr-sweep-workspaces"))
# --------------------------------------------------------------------------


def run(cmd: list[str], *, cwd: Path, timeout: int, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd) + f"  # cwd={cwd}", flush=True)
    res = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
    if res.stdout:
        print(res.stdout[-4000:], end="" if res.stdout.endswith("\n") else "\n", flush=True)
    if res.stderr:
        print(res.stderr[-4000:], end="" if res.stderr.endswith("\n") else "\n", flush=True)
    if check and res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd, output=res.stdout, stderr=res.stderr)
    return res


def gh_json(args: list[str], *, timeout: int = 60):
    res = subprocess.run(["gh", *args], text=True, capture_output=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed rc={res.returncode}: {res.stderr[:1000]}")
    return json.loads(res.stdout or "null")


def gh_text(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], text=True, capture_output=True, timeout=timeout)


def zero_reaction_unhandled(owner_repo: str, pr: int, author: str) -> dict[str, list[dict]]:
    # --paginate: without it gh returns only the first 30 comments, so a
    # busy PR looks fully handled while later pages hold unanswered roots.
    pulls = gh_json(
        ["api", "--paginate", f"repos/{owner_repo}/pulls/{pr}/comments"], timeout=90
    )
    issues = gh_json(
        ["api", "--paginate", f"repos/{owner_repo}/issues/{pr}/comments"], timeout=90
    )
    # Some gh versions emit one array per page; flatten if so.
    if pulls and isinstance(pulls[0], list):
        pulls = [c for page in pulls for c in page]
    if issues and isinstance(issues[0], list):
        issues = [c for page in issues for c in page]

    # SKILL.md's definition of unhandled includes author engagement, not just
    # reactions: a root the author already replied to inline is handled.
    replied_to = {
        c.get("in_reply_to_id")
        for c in pulls
        if (c.get("user") or {}).get("login") == author and c.get("in_reply_to_id") is not None
    }
    line = [
        c
        for c in pulls
        if c.get("in_reply_to_id") is None
        and ((c.get("user") or {}).get("login") != author)
        and (((c.get("reactions") or {}).get("total_count") or 0) == 0)
        and c.get("id") not in replied_to
    ]
    # Issue comments are flat, so SKILL.md uses a timestamp heuristic: if the
    # author posted an issue comment AFTER this one, treat it as seen. Without
    # this the runner disagreed with triage_scan.py and with SKILL.md itself.
    author_last = max(
        [
            c.get("created_at") or ""
            for c in issues
            if (c.get("user") or {}).get("login") == author
        ],
        default="",
    )
    issue = [
        c
        for c in issues
        if ((c.get("user") or {}).get("login") != author)
        and (((c.get("reactions") or {}).get("total_count") or 0) == 0)
        and (c.get("created_at") or "") > author_last
    ]
    return {"line": line, "issue": issue, "pulls_all": pulls, "issues_all": issues}


def find_session(repo_name: str, pr: int) -> Path | None:
    # Claude normalizes project paths; repository dots may be encoded as hyphens
    # (e.g. heartcentered.ai -> heartcentered-ai). Search both forms.
    patterns = {repo_name, repo_name.replace(".", "-")}
    project_matches: set[str] = set()
    for normalized_name in patterns:
        project_matches.update(
            glob.glob(str(HOME / ".claude" / "projects" / f"*{normalized_name}-pr-sweep-{pr}*"))
        )
    projects = sorted(
        project_matches,
        key=os.path.getmtime,
        reverse=True,
    )
    for project in projects:
        sessions = sorted(glob.glob(os.path.join(project, "*.jsonl")), key=os.path.getmtime, reverse=True)
        if sessions:
            return Path(sessions[0])
    return None


def parse_session(session: Path | None) -> dict:
    info = {"session": str(session) if session else None, "skill_count": 0, "address_count": 0, "pr_links": []}
    if not session or not session.exists():
        return info
    text = session.read_text(errors="ignore")
    info["skill_count"] = text.count('"name":"Skill"') + text.count('"name": "Skill"')
    info["address_count"] = text.count("address-pr-comments")
    for line in text.splitlines():
        if '"type":"pr-link"' not in line and '"type": "pr-link"' not in line:
            continue
        num = re.search(r'"prNumber"\s*:\s*(\d+)', line)
        url = re.search(r'"prUrl"\s*:\s*"([^"]+)"', line)
        if num:
            link = {"prNumber": int(num.group(1)), "prUrl": url.group(1) if url else None}
            if link not in info["pr_links"]:
                info["pr_links"].append(link)
    return info


def add_labels(owner_repo: str, pr_number: int, labels: list[str]) -> dict:
    added, errors = [], []
    for label in labels:
        res = gh_text(["pr", "edit", str(pr_number), "--repo", owner_repo, "--add-label", label])
        if res.returncode == 0:
            added.append(label)
        else:
            errors.append({"label": label, "stderr": res.stderr[:500]})
    return {"ok": not errors, "added": added, "errors": errors}


def clean_workspace(path: Path) -> None:
    os.chdir(HOME)
    if path.exists() and "pr-sweep" in path.name:
        shutil.rmtree(path, ignore_errors=True)


def main() -> None:
    SWEEP_ROOT.mkdir(parents=True, exist_ok=True)
    scan = json.loads(SCAN_PATH.read_text())
    rows = [r for r in scan["rows"] if r["repo"] not in EXCLUDE_REPOS][:MAX_PRS_PER_RUN]
    summary = {
        "started_at": dt.datetime.utcnow().isoformat() + "Z",
        "scan": {k: scan.get(k) for k in ["since", "discovered", "scanned", "excluded_count"]},
        "selected_count": len(rows),
        "selected": [{"repo": r["repo"], "pr": r["pr"], "total": r["total"], "url": r.get("url")} for r in rows],
        "results": [],
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2))

    for idx, row in enumerate(rows, 1):
        owner_repo = row["repo"]
        _, repo_name = owner_repo.split("/", 1)
        pr = int(row["pr"])
        author = row.get("author") or ""
        workspace = SWEEP_ROOT / f"{repo_name}-pr-sweep-{pr}"
        result = {"repo": owner_repo, "pr": pr, "initial_unhandled": row.get("total"), "workspace": str(workspace)}
        print(f"\n=== [{idx}/{len(rows)}] {owner_repo}#{pr} ===", flush=True)
        try:
            clean_workspace(workspace)
            run(["gh", "repo", "clone", owner_repo, str(workspace)], cwd=HOME, timeout=300)
            run(["git", "checkout", "-b", f"pr-sweep-{pr}"], cwd=workspace, timeout=120)
            task = f"""
Use the Skill tool to invoke the address-pr-comments skill with argument {pr}.

This skill is provided by the ai-coding-config plugin (globally installed). It knows the project's triage conventions and review standards. Do NOT manually triage — you MUST use the Skill tool to load and execute the address-pr-comments skill.

Repository: {owner_repo}
Original merged PR: #{pr} ({row.get('url')})
Initial unhandled comment count from the sweep: {row.get('total')} ({row.get('line_count')} line-level, {row.get('issue_count')} PR-level).

The orchestrator independently validated the final merged code before dispatch. Use this as triage guidance, but still execute the skill's own verification:
{row.get('triage_hint', 'No orchestrator triage hint was supplied.')}

If the skill creates fixes, they go in a new follow-up PR with labels: {FOLLOWUP_LABELS}.
Do NOT merge anything. Leave merge for human review.

Do NOT do a cascade sweep on the follow-up PR — just create it, close the loop on the original comments, and exit. Once the fix PR is created and the original comments are addressed, exit immediately — do not idle polling CI.
""".strip()
            start = time.time()
            proc = subprocess.Popen(
                ["claude", "--print", "--model", "sonnet", "--dangerously-skip-permissions", task],
                cwd=str(workspace),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                stdout, stderr = proc.communicate(timeout=TIMEOUT_PER_PR_S)
                timed_out = False
            except subprocess.TimeoutExpired:
                session_now = find_session(repo_name, pr)
                info_now = parse_session(session_now)
                if info_now["pr_links"]:
                    try:
                        stdout, stderr = proc.communicate(timeout=300)
                        timed_out = False
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                        timed_out = True
                else:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                    timed_out = True
            result.update({
                "claude_exit_code": proc.returncode,
                "claude_timed_out": timed_out,
                "elapsed_s": round(time.time() - start, 1),
                "claude_stdout_tail": (stdout or "")[-4000:],
                "claude_stderr_tail": (stderr or "")[-4000:],
            })
            sinfo = parse_session(find_session(repo_name, pr))
            result["session_info"] = sinfo
            followup = sinfo["pr_links"][-1] if sinfo["pr_links"] else None
            result["followup_pr"] = followup
            if followup and followup.get("prNumber"):
                result["label_result"] = add_labels(owner_repo, int(followup["prNumber"]), FOLLOWUP_LABELS)
            post = zero_reaction_unhandled(owner_repo, pr, author)
            result["post_unhandled"] = {"line": len(post["line"]), "issue": len(post["issue"]), "total": len(post["line"]) + len(post["issue"])}
            result["status"] = "ok" if proc.returncode == 0 and sinfo["skill_count"] > 0 and result["post_unhandled"]["total"] == 0 else "needs_attention"
        except Exception as exc:  # keep the sweep moving
            result["status"] = "error"
            result["error"] = repr(exc)
        finally:
            clean_workspace(workspace)
            result["finished_at"] = dt.datetime.utcnow().isoformat() + "Z"
            summary["results"].append(result)
            RESULTS_PATH.write_text(json.dumps(summary, indent=2))

    for pattern in [HOME / "dev" / "*pr-sweep*", HOME / "pr-sweep-workspaces" / "*pr-sweep*"]:
        for path in glob.glob(str(pattern)):
            shutil.rmtree(path, ignore_errors=True)
    summary["finished_at"] = dt.datetime.utcnow().isoformat() + "Z"
    RESULTS_PATH.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
