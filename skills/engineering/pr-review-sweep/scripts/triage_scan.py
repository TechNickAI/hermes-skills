#!/usr/bin/env python3
"""
Batch triage scan for pr-review-sweep step 2.

Discovers merged PRs in the lookback window across the configured orgs, then for
each PR counts UNHANDLED review comments (not from the PR author, zero reactions)
on BOTH endpoints:
  - line-level review comments: pulls/{pr}/comments (root only, in_reply_to_id == null)
  - issue-level general comments: issues/{pr}/comments

Prints one compact table sorted by total unhandled count, flagging only PRs with
unhandled > 0. Only flagged PRs proceed to the (serial) per-PR Claude dispatch.

Runs the ENTIRE scan in one pass — do NOT serial-loop `terminal` per PR. In the wild
this scanned 51 PRs in ~30s and reduced the dispatch decision to ~19 rows.

Run from `execute_code` (imports hermes_tools nowhere — pure subprocess + gh), or
adapt to a plain `python3 scripts/triage_scan.py` invocation. Requires `gh` authed.

Edit ORGS / LOOKBACK_DAYS / EXCLUDE to match the run's config knobs.
"""
import json
import os
import subprocess
from pathlib import Path

# --- config knobs (env overrides keep cron prompts authoritative) ---
ORGS = [x for x in os.environ.get("ORGS", "carmentacollective,TechNickAI").split(",") if x]
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))
SEARCH_LIMIT = int(os.environ.get("SEARCH_LIMIT", "200"))
EXCLUDE = {x for x in os.environ.get("EXCLUDE_REPOS", "TechNickAI/openclaw-config").split(",") if x}
OUTPUT_PATH = Path(os.environ.get("PR_SWEEP_SCAN", "/tmp/pr_review_sweep_scan.json"))
# --------------------------------------------------------------------------

since = subprocess.run(
    ["date", "-d", f"{LOOKBACK_DAYS} days ago", "+%Y-%m-%d"],
    capture_output=True, text=True,
).stdout.strip()

owner_args = []
for org in ORGS:
    owner_args += ["--owner", org]

prs = json.loads(subprocess.run(
    ["gh", "search", "prs", *owner_args,
     "--state", "closed", "--merged", "--merged-at", ">" + since,
     "--json", "number,title,repository,author,url,closedAt", "--limit", str(SEARCH_LIMIT)],
    capture_output=True, text=True, check=True,
).stdout)

if len(prs) >= SEARCH_LIMIT:
    print(f"WARNING: discovered PR count hit SEARCH_LIMIT={SEARCH_LIMIT}; older PRs may be omitted")


def gh_count(url, jq):
    """Return an int count from a gh api call, or (None, err) on failure."""
    # --paginate: gh returns 30 comments per page by default, so a busy PR
    # undercounts unhandled roots and the sweep can call the run "ok" while
    # later pages still hold unanswered comments.
    #
    # With --jq, gh applies the filter to EACH page and concatenates the
    # results, so a `| length` filter emits one number per page. Select the
    # objects here and count them in Python instead of summing jq output.
    # (`--slurp` would give one combined document but does not exist before
    # gh 2.40; this works on older CLIs too.)
    r = subprocess.run(
        ["gh", "api", "--paginate", url, "--jq", jq],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None, r.stderr.strip()[:120]
    # One id per matching comment, one per line, across every page.
    return len([ln for ln in r.stdout.splitlines() if ln.strip()]), None


def gh_count_slurped(url, jq):
    """Count with a filter that needs EVERY page in one document.

    The author-engagement rules compare each comment against the whole set (was
    this root replied to? is this older than the author's last comment?), so a
    per-page filter would give a wrong answer at page boundaries. Fetch all
    pages, concatenate into one array, then apply jq once.
    """
    r = subprocess.run(
        ["gh", "api", "--paginate", url], capture_output=True, text=True
    )
    if r.returncode != 0:
        return None, r.stderr.strip()[:120]
    # --paginate emits one JSON array per page, concatenated. Flatten them.
    dec, docs, s, i = json.JSONDecoder(), [], r.stdout.strip(), 0
    try:
        while i < len(s):
            obj, j = dec.raw_decode(s, i)
            docs.append(obj)
            i = j
            while i < len(s) and s[i] in " \n\r\t":
                i += 1
    except Exception as e:  # noqa: BLE001
        return None, f"pagination parse: {str(e)[:100]}"
    flat = [c for d in docs for c in (d if isinstance(d, list) else [d])]
    j = subprocess.run(
        ["jq", jq], input=json.dumps(flat), capture_output=True, text=True
    )
    if j.returncode != 0:
        return None, j.stderr.strip()[:120]
    try:
        return int(j.stdout.strip() or 0), None
    except ValueError as e:
        return None, str(e)[:120]


rows = []
scanned = 0
excluded_count = 0
for pr in prs:
    repo = pr["repository"]["nameWithOwner"]
    if repo in EXCLUDE:
        excluded_count += 1
        continue
    scanned += 1
    owner, name = repo.split("/")
    num = pr["number"]
    author = pr["author"]["login"]

    # Line comments: drop any root the author already replied to inline.
    # Needs the whole page set at once, so slurp with -s inside jq rather than
    # filtering per comment.
    line, e1 = gh_count_slurped(
        f"repos/{owner}/{name}/pulls/{num}/comments",
        f'(map(select(.user.login == "{author}" and .in_reply_to_id != null) '
        f'| .in_reply_to_id) | unique) as $replied '
        f'| map(select(.user.login != "{author}" and .in_reply_to_id == null '
        f'and ((.reactions.total_count // 0) == 0) '
        f'and (.id as $id | $replied | index($id) | not))) | length',
    )
    # Issue comments are flat, so use the skill's timestamp heuristic: drop any
    # comment the author posted an issue comment AFTER (they saw it, moved on).
    issue, e2 = gh_count_slurped(
        f"repos/{owner}/{name}/issues/{num}/comments",
        f'(map(select(.user.login == "{author}") | .created_at) | sort | last // "0") '
        f'as $author_last '
        f'| map(select(.user.login != "{author}" '
        f'and ((.reactions.total_count // 0) == 0) '
        f'and (.created_at > $author_last))) | length',
    )
    lc = line if isinstance(line, int) else 0
    ic = issue if isinstance(issue, int) else 0
    err = e1 or e2 or ""
    if lc > 0 or ic > 0 or err:
        rows.append({
            "repo": repo,
            "pr": num,
            "author": author,
            "line_count": lc,
            "issue_count": ic,
            "total": lc + ic,
            "error": err,
            "title": pr["title"],
            "url": pr["url"],
            "closedAt": pr["closedAt"],
        })

rows.sort(key=lambda row: -row["total"])
payload = {
    "since": since,
    "discovered": len(prs),
    "scanned": scanned,
    "excluded_count": excluded_count,
    "hit_limit": len(prs) >= SEARCH_LIMIT,
    "rows": rows,
}
OUTPUT_PATH.write_text(json.dumps(payload, indent=2))

print(f"Scanned {scanned} PRs (excluded {excluded_count}); JSON: {OUTPUT_PATH}\n")
print(f"{'repo':<30}{'PR':>5}{'line':>6}{'issue':>7}  title")
for row in rows:
    tag = ("ERR:" + row["error"]) if row["error"] else ""
    print(f"{row['repo']:<30}{row['pr']:>5}{row['line_count']:>6}{row['issue_count']:>7}  {row['title'][:40]}  {tag}")
print(f"\nFlagged {len(rows)} PRs with unhandled>0")
