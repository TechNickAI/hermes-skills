#!/usr/bin/env python3
"""Skill library health audit — collects FACTS, draws NO conclusions.

Every number here is measured against the live profile. The agent interprets;
this script never decides what to delete, merge, or rewrite.

Usage:
    python3 audit.py [--profile DIR] [--json]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

# Mirrors agent/skill_utils.py — keep in sync if Hermes changes.
EXCLUDED_DIRS = {
    ".git", ".github", ".hub", ".archive", ".curator_backups", ".venv", "venv",
    "node_modules", "site-packages", "__pycache__", ".tox", ".nox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "_attic",
}
SUPPORT_DIRS = ("references", "templates", "assets", "scripts")
DESC_LIMIT = 60          # SKILL_PROMPT_DESC_LIMIT — index truncates past this
MAX_CONTENT = 100_000    # MAX_SKILL_CONTENT_CHARS — writes past this are REFUSED
NEAR_CAP = 90_000


def parse_frontmatter(text):
    """Return (frontmatter_dict, body_len). Mirrors Hermes' tolerant parsing."""
    if not text.startswith("---"):
        return {}, len(text)
    m = re.search(r"\n---\s*\n", text[3:])
    if not m:
        return {}, len(text)
    raw = text[3:m.start() + 3]
    body_len = len(text) - (m.end() + 3)
    try:
        import yaml
        fm = yaml.safe_load(raw)
        if isinstance(fm, dict):
            return fm, body_len
    except Exception:
        pass
    fm = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith((" ", "-", "#")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip("'\"")
    return fm, body_len


def is_excluded(path, base):
    rel = os.path.relpath(path, base)
    return any(part in EXCLUDED_DIRS for part in rel.split(os.sep))


def collect(skills_dir):
    skills, excluded = {}, []
    for root, dirs, files in os.walk(skills_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        if "SKILL.md" not in files:
            continue
        path = os.path.join(root, "SKILL.md")
        if is_excluded(path, skills_dir):
            excluded.append(path)
            continue
        # A SKILL.md nested under another skill's support dir does not load.
        rel_parts = os.path.relpath(root, skills_dir).split(os.sep)
        if any(p in SUPPORT_DIRS for p in rel_parts):
            excluded.append(path)
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        fm, body_len = parse_frontmatter(text)
        name = os.path.basename(root)
        desc = str(fm.get("description") or "").strip().strip("'\"")
        skills[name] = {
            "path": path,
            "category": os.path.relpath(os.path.dirname(root), skills_dir),
            "size": len(text),
            "body_len": body_len,
            "desc": desc,
            "desc_len": len(desc),
            "truncated": len(desc) > DESC_LIMIT,
            "fm_name": fm.get("name"),
            "name_mismatch": bool(fm.get("name")) and fm.get("name") != name,
            "no_desc": not desc,
            "over_cap": len(text) >= MAX_CONTENT,
            "near_cap": NEAR_CAP <= len(text) < MAX_CONTENT,
            "platforms": fm.get("platforms"),
            "environments": fm.get("environments"),
        }
    return skills, excluded


def load_usage(skills_dir):
    """Hermes' own telemetry. Absence is a finding, not an error.

    Use `use_count` here, NEVER `view_count`, and never reconstruct usage by
    parsing skill_view calls out of state.db. Cron jobs preload skills via the
    job's `skills:` field, which increments use_count WITHOUT any skill_view
    tool call. Measured on one real profile: a research skill had use_count=39 /
    view_count=1 and had run that same day; a skill_view-based parse called it
    "never used" and would have proposed retiring a live weekly job's skill.

    The inverse holds for the per-turn join in harvest.py, which needs the
    MODEL-CHOSEN signal and therefore uses skill_view deliberately. Neither
    counter is the right one in general; pick by the question being asked.
    """
    p = os.path.join(skills_dir, ".usage.json")
    if not os.path.exists(p):
        return {}, "MISSING — no native telemetry at .usage.json"
    try:
        return json.load(open(p)), None
    except Exception as e:
        return {}, f"UNREADABLE: {e}"


def cron_referenced_skills(profile_dir):
    """Skills preloaded by a scheduled job. These are USED even at 0 views."""
    p = os.path.join(profile_dir, "cron", "jobs.json")
    if not os.path.exists(p):
        return set()
    try:
        data = json.load(open(p))
    except Exception:
        return set()
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    out = set()
    for j in jobs:
        if not isinstance(j, dict) or not j.get("enabled", True):
            continue
        for s in j.get("skills") or []:
            out.add(str(s).split("/")[-1].split(":")[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.environ.get(
        "HERMES_HOME", os.path.expanduser("~/.hermes")))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    skills_dir = os.path.join(args.profile, "skills")
    if not os.path.isdir(skills_dir):
        print(f"ERROR: no skills dir at {skills_dir}", file=sys.stderr)
        return 2

    skills, excluded = collect(skills_dir)
    usage, usage_err = load_usage(skills_dir)

    # Index cost: what ACTUALLY enters the system prompt (post-truncation).
    index_chars = 0
    for n, s in skills.items():
        d = s["desc"]
        shown = d[:DESC_LIMIT - 3] + "..." if len(d) > DESC_LIMIT else d
        index_chars += len(f"    - {n}: {shown}\n")

    # Reconcile telemetry against disk in BOTH directions.
    # SUM all key variants per skill (bare, "category/name", "category:name").
    # Taking max() across variants read a 558-use skill as use_count=2.
    # Track use and view SEPARATELY: use increments on cron/slash injection too,
    # so (use - view) is FORCED loads, not model-chosen routing. Measured on one
    # real profile: a safety skill showed 11,024 use / 1,867 view = 9,157 forced.
    used, viewed = {}, {}
    for key, rec in usage.items():
        if not isinstance(rec, dict):
            continue
        base = key.split("/")[-1].split(":")[-1]
        used[base] = used.get(base, 0) + (rec.get("use_count", 0) or 0)
        viewed[base] = viewed.get(base, 0) + (rec.get("view_count", 0) or 0)
    cron_skills = cron_referenced_skills(args.profile)
    # A skill preloaded by an enabled cron job is IN USE regardless of counters.
    never = sorted(n for n in skills
                   if used.get(n, 0) == 0 and n not in cron_skills)
    # Chosen ~0 but used a lot = forced-only: it is injected, never routed to.
    forced_only = sorted(
        ((used.get(n, 0) - viewed.get(n, 0), n) for n in skills
         if used.get(n, 0) - viewed.get(n, 0) > 50),
        reverse=True)
    ghosts = sorted(k for k in used if k not in skills)

    report = {
        "skills_dir": skills_dir,
        "live_skills": len(skills),
        "excluded_paths": len(excluded),
        "index_chars": index_chars,
        "index_tokens_est": index_chars // 4,
        "truncated": sorted(
            ((s["desc_len"], n) for n, s in skills.items() if s["truncated"]),
            reverse=True),
        "over_cap": sorted(
            ((s["size"], n) for n, s in skills.items() if s["over_cap"]),
            reverse=True),
        "near_cap": sorted(
            ((s["size"], n) for n, s in skills.items() if s["near_cap"]),
            reverse=True),
        "name_mismatch": [n for n, s in skills.items() if s["name_mismatch"]],
        "no_description": [n for n, s in skills.items() if s["no_desc"]],
        "never_used": never,
        "forced_only": forced_only,
        "ghost_usage_records": ghosts,
        "usage_error": usage_err,
        "categories": dict(Counter(s["category"] for s in skills.values())),
        "total_chars": sum(s["size"] for s in skills.values()),
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    r = report
    print(f"SKILL LIBRARY AUDIT — {skills_dir}")
    print("=" * 68)
    print(f"live skills            {r['live_skills']}")
    print(f"excluded (archive/etc) {r['excluded_paths']}")
    print(f"total on disk          {r['total_chars']:,} chars")
    print(f"index cost/turn        {r['index_chars']:,} chars "
          f"(~{r['index_tokens_est']:,} tokens) EVERY TURN")
    print()
    print(f"[ROUTING] truncated descriptions (>{DESC_LIMIT} chars): "
          f"{len(r['truncated'])} of {r['live_skills']}")
    for ln, n in r["truncated"][:10]:
        print(f"    {ln:5d}  {n}")
    print()
    print(f"[HARD CAP] at/over {MAX_CONTENT:,} chars — PATCHES SILENTLY FAIL: "
          f"{len(r['over_cap'])}")
    for sz, n in r["over_cap"]:
        print(f"    {sz:7d}  ({sz - MAX_CONTENT:+d})  {n}")
    print(f"[HARD CAP] within 10k of cap: {len(r['near_cap'])}")
    for sz, n in r["near_cap"][:10]:
        print(f"    {sz:7d}  {n}")
    print()
    print(f"[STRUCTURE] name/dir mismatch  {len(r['name_mismatch'])}")
    print(f"[STRUCTURE] missing description {len(r['no_description'])}")
    print()
    if usage_err:
        print(f"[TELEMETRY] {usage_err}")
    print(f"[USAGE] never used: {len(r['never_used'])} "
          f"(CANDIDATE signal only — safety/recovery skills are 0-load BY DESIGN)")
    print(f"[USAGE] FORCED-only (use-view >50 — injected by cron/slash, NOT "
          f"model-chosen): {len(r['forced_only'])}")
    for n_forced, n in r["forced_only"][:8]:
        print(f"    {n_forced:6d} forced  {n}")
    print(f"[USAGE] ghost records (telemetry without a skill on disk): "
          f"{len(r['ghost_usage_records'])}")
    print()
    print("Facts only. Falsify each before acting: check .archive/, platform and")
    print("environment gates, and config `skills.disabled` before calling anything broken.")
    print("NEVER infer adherence from these counts — a forced load says nothing")
    print("about routing, and none of this shows what was in context on a failing turn.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
