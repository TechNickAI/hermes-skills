#!/usr/bin/env python3
"""Per-turn join: which skills were model-CHOSEN before an owner correction.

Reads a Hermes `state.db` read-only. Emits FACTS. Draws no conclusions.

Why this exists: `bump_use()` does not persist a session id, so usage counters
cannot answer "was this skill loaded on the turn that went wrong". But
`skill_view` tool calls DO sit in `messages.tool_calls` with a session_id and
timestamp, and owner corrections sit in the same table. That join is buildable,
and `skill_view` is specifically the MODEL-CHOSEN signal: it excludes cron and
slash-command forced injection, which is the confound that invalidates any
analysis built on `use_count`.

Read `correction-rate-confounds.md` before quoting any number this prints.
Hard tasks load more skills AND draw more corrections, so a high lift may mark
difficulty rather than a defective skill. Lift is a screen, not an effect.

Usage:
    python3 harvest.py --db ~/.hermes/profiles/<profile>/state.db
    python3 harvest.py --db <path> --sizes ~/.hermes/profiles/<profile>/skills
    python3 harvest.py --db <path> --json
"""

import argparse
import json
import os
import re
import sqlite3
import sys

# Sessions whose user turns are machine-authored. A cron prompt is not an owner
# correction, and counting it as one manufactures evidence.
NON_OWNER_SOURCES = ("cron", "subagent", "webhook")

# Source filtering is NOT sufficient on its own. Reviewer prompts, judge rubrics,
# system notes and cron replies are all written into `messages` with role='user'
# on interactive sources. Measured on one real profile: 2,096 of 9,032 role=user
# rows on cli+telegram opened with one of these preambles, and they are dense in
# exactly the vocabulary a correction detector looks for ("wrong", "you missed",
# "why did you") because critique prompts are ABOUT finding errors.
# The compaction blob is the highest-volume trap of all. It is written with
# role='user', it is not a cron/subagent source, and its own boilerplate says
# "Do NOT answer questions ... they were already addressed" plus "the latest
# user message WINS" -- so it matches correction patterns on text the OWNER
# NEVER WROTE. Measured on one real profile: 186 of 459 matched rows (40%)
# were compaction blobs, and removing them dropped the top-ranked skill from
# 3.41x lift to 1.04x. The entire ranking was an artifact of this one gap.
MACHINE_PREAMBLES = [
    r"^\[System note",
    r"^\[OUT-OF-BAND",
    r"^\[Automatic",
    r"^\[CONTEXT COMPACTION",
    r"^\[Conversation info",
    r"^\[The user sent a voice message",
    r"^Cronjob Response",
    r"^\[Replying to:",
    r"^You are ",
    r"^You will ",
    r"^Meta-review\b",
    r"^Review the\b",
    r"^Score \b",
]
MACHINE_RE = re.compile("|".join(MACHINE_PREAMBLES), re.IGNORECASE)

# Owner correction markers. Deliberately narrow: precision beats recall here,
# because a false positive becomes a fabricated finding about a real skill.
#
# A bare `\bwrong\b` is the trap. It looks like the most obvious correction word
# in the language and it matched 649 rows on a real profile, almost all of them
# reviewer prompts telling a seat to hunt for what is wrong. Every pattern below
# requires a second-person subject or an explicit repudiation, so the sentence
# has to be aimed AT the agent rather than merely discussing error.
CORRECTION_PATTERNS = [
    r"\bthat'?s (?:not right|not correct|wrong|incorrect)\b",
    r"\byou (?:were|are|got it) wrong\b",
    r"\byou (?:missed|forgot|skipped|ignored)\b",
    r"\bdon'?t do that\b",
    r"\bi (?:didn'?t|did not) ask\b",
    r"\bthat'?s not what i\b",
    r"\bnot what i asked\b",
    r"\bwhy did you\b",
    r"\bactually[,.]? (?:no|it'?s|that'?s)\b",
    r"\bthat'?s not true\b",
    r"\bis (?:that|this) (?:actually )?true\b",
    r"\bare you sure\b",
    r"\byou (?:said|claimed) .{0,40}\bbut\b",
]
CORRECTION_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE)

# Below this, a rate is noise. Reporting a 100% correction rate from 2 sessions
# is the fastest way to get a healthy skill rewritten for no reason.
MIN_SESSIONS = 25


def normalise_skill_name(raw):
    """Collapse the name variants an agent actually writes into one key.

    Agents call skill_view with the bare name, but also with the category
    prefix ("devops/fleet-management"), a colon form, a doubled form
    ("recall/recall"), trailing punctuation, and occasionally a whole sentence
    appended. Left unnormalised these split one skill across several keys, and
    every fragment lands under the per-skill session floor and vanishes from the
    report entirely — the skill looks unused rather than under-counted.
    """
    if not raw:
        return None
    name = str(raw).strip()
    # Drop anything after whitespace: agents append prose to the name.
    name = name.split()[0] if name.split() else ""
    # Take the last path/colon segment: "devops/fleet-management" -> the skill.
    name = name.replace(":", "/").rstrip("/").split("/")[-1]
    name = name.strip().strip(".!?,;\"'")
    return name or None


def skill_views_by_session(conn, include_sources=None):
    """{session_id: [(timestamp, skill_name), ...]} for model-chosen loads."""
    q = """
        SELECT m.session_id, m.timestamp, m.tool_calls
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.tool_calls LIKE '%skill_view%'
    """
    params = []
    if include_sources:
        q += " AND s.source IN (%s)" % ",".join("?" * len(include_sources))
        params = list(include_sources)

    out = {}
    for sid, ts, raw in conn.execute(q, params):
        try:
            calls = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(calls, list):
            continue
        for call in calls:
            fn = (call or {}).get("function") or {}
            if fn.get("name") != "skill_view":
                continue
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if not isinstance(args, dict):
                continue
            name = normalise_skill_name(args.get("name"))
            if not name:
                continue
            # A skill_view with a file_path is a follow-up read of a reference
            # inside a skill already chosen. Counting it again double-counts.
            if args.get("file_path"):
                continue
            out.setdefault(sid, []).append((ts, str(name)))
    return out


def corrections(conn, include_sources=None):
    """[(session_id, message_id, timestamp)] for owner correction turns."""
    q = """
        SELECT m.session_id, m.id, m.timestamp, m.content
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.role = 'user' AND m.content IS NOT NULL
    """
    params = []
    if include_sources:
        q += " AND s.source IN (%s)" % ",".join("?" * len(include_sources))
        params = list(include_sources)

    out = []
    skipped_machine = 0
    for sid, mid, ts, content in conn.execute(q, params):
        text = (content or "").strip()
        if not text:
            continue
        if MACHINE_RE.match(text):
            skipped_machine += 1
            continue
        if CORRECTION_RE.search(text):
            out.append((sid, mid, ts))
    return out, skipped_machine


def skill_sizes(skills_dir):
    """{skill_name: size_bytes}. Absent dir is a finding, not an error."""
    sizes = {}
    if not skills_dir or not os.path.isdir(skills_dir):
        return sizes
    for root, dirs, files in os.walk(skills_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if "SKILL.md" in files:
            path = os.path.join(root, "SKILL.md")
            try:
                sizes[os.path.basename(root)] = os.path.getsize(path)
            except OSError:
                continue
    return sizes


def analyse(loads, corr_rows, sizes):
    corr_sessions = {sid for sid, _, _ in corr_rows}

    # PRECEDENCE MATTERS: only count a skill if it was chosen BEFORE the
    # correction. A skill loaded in response to the complaint is not a cause of
    # it, and counting it inverts the causal arrow.
    # One permanent cutoff at the FIRST correction throws away every later turn
    # of a long session. Measured on one real profile: 34 skill-load events
    # across 9 sessions were discarded, in sessions that had already been
    # counted as corrected — so the loads vanished while the correction stayed.
    # Segment instead: each correction opens a window back to the previous
    # correction, and a skill is credited if it was chosen inside that window.
    by_session = {}
    for sid, _mid, ts in corr_rows:
        by_session.setdefault(sid, []).append(ts)
    for sid in by_session:
        by_session[sid].sort()

    # The baseline MUST be computed over the same population the per-skill rates
    # are computed over, or every lift is silently wrong. Restricting per-skill
    # counts while leaving the baseline over all sessions made every lift <
    # 1.00x on a real profile — arithmetically impossible for a weighted
    # average, which is the tell that the denominators disagreed.
    sess_with = {}
    eligible = set()
    for sid, events in loads.items():
        stamps = by_session.get(sid)
        if not stamps:
            # No correction in this session: every chosen skill counts, and the
            # session is a clean negative for the baseline.
            if not events:
                continue
            eligible.add(sid)
            for _ts, name in events:
                sess_with.setdefault(name, set()).add(sid)
            continue
        # Credit a skill if it was chosen before ANY correction in the session,
        # not only the first. Precedence still holds per window: a skill loaded
        # in response to a complaint is never credited for that complaint.
        counted = {name for ts, name in events if ts < stamps[-1]}
        if not counted:
            continue
        eligible.add(sid)
        for name in counted:
            sess_with.setdefault(name, set()).add(sid)

    if not eligible:
        return None
    overlap = eligible & corr_sessions
    baseline = len(overlap) / len(eligible)

    per_skill = []
    for name, sids in sess_with.items():
        if len(sids) < MIN_SESSIONS:
            continue
        c = len(sids & corr_sessions)
        rate = c / len(sids)
        per_skill.append({
            "skill": name,
            "corrections": c,
            "sessions": len(sids),
            "rate": rate,
            "lift": rate / baseline if baseline else 0.0,
            "size": sizes.get(name),
        })
    per_skill.sort(key=lambda r: r["lift"], reverse=True)

    buckets = {"<20k": [], "20-50k": [], "50-90k": [], ">=90k": []}
    for row in per_skill:
        sz = row["size"]
        if sz is None:
            continue
        key = ("<20k" if sz < 20000 else "20-50k" if sz < 50000
               else "50-90k" if sz < 90000 else ">=90k")
        buckets[key].append(row)

    size_rows = []
    for key in ("<20k", "20-50k", "50-90k", ">=90k"):
        rows = buckets[key]
        if not rows:
            size_rows.append({"bucket": key, "skills": 0})
            continue
        tot = sum(r["sessions"] for r in rows)
        cor = sum(r["corrections"] for r in rows)
        size_rows.append({
            "bucket": key, "skills": len(rows), "sessions": tot,
            "corrections": cor, "rate": cor / tot,
            "lift": (cor / tot) / baseline if baseline else 0.0,
        })

    return {
        "sessions_with_a_chosen_skill": len(eligible),
        "of_those_with_a_correction": len(overlap),
        "baseline_correction_rate": baseline,
        "correction_messages": len(corr_rows),
        "correction_sessions": len(corr_sessions),
        "machine_authored_user_rows_skipped": None,
        "min_sessions_threshold": MIN_SESSIONS,
        "by_skill": per_skill,
        "by_size": size_rows,
        "skills_with_known_size": sum(1 for r in per_skill if r["size"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to a Hermes state.db")
    ap.add_argument("--sizes", help="skills dir, enables the size-gradient test")
    ap.add_argument("--all-sources", action="store_true",
                    help="include cron/subagent/webhook sessions (NOT owner dialogue)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print("ERROR: no database at %s" % db, file=sys.stderr)
        return 2

    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        sources = None
        if not args.all_sources:
            have = {r[0] for r in conn.execute("SELECT DISTINCT source FROM sessions")}
            sources = sorted(have - set(NON_OWNER_SOURCES))
            if not sources:
                print("ERROR: no owner-authored session sources in this db",
                      file=sys.stderr)
                return 2

        loads = skill_views_by_session(conn, sources)
        corr, skipped_machine = corrections(conn, sources)
    finally:
        conn.close()

    sizes = skill_sizes(os.path.expanduser(args.sizes) if args.sizes else None)
    report = analyse(loads, corr, sizes)
    if report is not None:
        report["machine_authored_user_rows_skipped"] = skipped_machine
    if report is None:
        print("No sessions with a model-chosen skill_view. Nothing to join.")
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    r = report
    print("PER-TURN JOIN — model-chosen skill loads before owner corrections")
    print("=" * 72)
    print("sessions with a chosen skill   %d" % r["sessions_with_a_chosen_skill"])
    print("  of those, with a correction  %d" % r["of_those_with_a_correction"])
    print("correction messages / sessions %d / %d"
          % (r["correction_messages"], r["correction_sessions"]))
    print("machine-authored user rows skipped %d"
          % r["machine_authored_user_rows_skipped"])
    print("BASELINE correction rate       %.1f%%"
          % (r["baseline_correction_rate"] * 100))
    print()
    print("%-40s %5s %7s %7s %6s" % ("skill", "corr", "sess", "rate", "lift"))
    print("-" * 72)
    for row in r["by_skill"][:18]:
        print("%-40s %5d %7d %6.1f%% %5.2fx"
              % (row["skill"][:40], row["corrections"], row["sessions"],
                 row["rate"] * 100, row["lift"]))
    if not r["by_skill"]:
        print("(no skill reached the %d-session floor)" % r["min_sessions_threshold"])
    print()

    if r["skills_with_known_size"]:
        print("SIZE GRADIENT — does correction rate rise with skill size?")
        print("%-10s %7s %9s %8s %7s %6s"
              % ("bucket", "skills", "sessions", "w/ corr", "rate", "lift"))
        print("-" * 56)
        for b in r["by_size"]:
            if not b["skills"]:
                print("%-10s %7d" % (b["bucket"], 0))
                continue
            print("%-10s %7d %9d %8d %6.1f%% %5.2fx"
                  % (b["bucket"], b["skills"], b["sessions"], b["corrections"],
                     b["rate"] * 100, b["lift"]))
        print()
    else:
        print("SIZE GRADIENT — skipped, pass --sizes <skills dir> to enable.")
        print()

    print("READ THIS BEFORE QUOTING ANY NUMBER ABOVE:")
    print("  Sessions double-count across skills, so these are not independent.")
    print("  Hard tasks load more skills AND draw more corrections, so lift may")
    print("  mark difficulty, not a defective skill. There are no confidence")
    print("  intervals here. This is a SCREEN for where to go read episodes by")
    print("  hand. It does not isolate skill quality and cannot on its own")
    print("  justify revising any skill.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
