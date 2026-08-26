#!/usr/bin/env python3
"""Characterize what a Hermes agent ACTUALLY does, from its state.db.

Run this before sizing/rebuilding a host for an agent. The tool histogram tells
you the agent's kind; the cwd distribution tells you the working set, which is
what actually sizes the box. A huge tool count over a tiny working set means the
workload fits in page cache -- evidence against any IOPS-bound theory.

Usage (run ON the host, read-only):
    python3 agent_workload_profile.py [/path/to/state.db] [days]

Copy it over rather than pasting inline; Hermes' lifecycle guard inspects
referenced script TEXT and multiline heredocs over ssh can die on 'embedded
null byte':
    scp -q /private/tmp/agent_workload_profile.py host:/tmp/ \
      && ssh host 'python3 /tmp/agent_workload_profile.py'

TRAP THIS ENCODES: Hermes stores timestamps as EPOCH FLOATS, not ISO strings.
Comparing them to a date string silently returns zero rows, and slicing one as
text raises "TypeError: 'float' object is not subscriptable". Every time column
must be wrapped: datetime(<col>,'unixepoch').
"""
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/state.db"
days = int(sys.argv[2]) if len(sys.argv) > 2 else 60

# immutable=1 is the correct read-only mode for a WAL db with no live sidecars;
# plain mode=ro fails at first query because it may not create the -shm file.
con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
q = con.execute

D = "datetime(timestamp,'unixepoch')"      # messages
S = "datetime(started_at,'unixepoch')"     # sessions


def section(title):
    print(f"\n=== {title} ===")


section(f"message volume by day (last {min(days,45)}d)")
for r in q(f"select date({D}) d, count(*) from messages "
           f"where {D} > datetime('now','-{min(days,45)} day') group by d order by d"):
    print(f"  {r[0]}  {r[1]:>7}")

section("TOOL HISTOGRAM (last 30d) -- tells you the agent's KIND")
for r in q(f"select tool_name, count(*) from messages where tool_name is not null "
           f"and {D} > datetime('now','-30 day') group by 1 order by 2 desc limit 25"):
    print(f"  {str(r[0]):<28} {r[1]}")

section(f"WORKING SET: cwd distribution (last {days}d) -- this SIZES the box")
for r in q(f"select cwd, count(*) from sessions where {S} > datetime('now','-{days} day') "
           f"and cwd is not null group by 1 order by 2 desc limit 25"):
    print(f"  {str(r[0]):<52} {r[1]}")

section(f"git_repo_root (last {days}d)")
rows = list(q(f"select git_repo_root, count(*) from sessions "
              f"where {S} > datetime('now','-{days} day') and git_repo_root is not null "
              f"group by 1 order by 2 desc limit 20"))
print("  (none recorded)" if not rows else "")
for r in rows:
    print(f"  {str(r[0]):<52} {r[1]}")

section(f"WHO DRIVES IT: sessions by source (last {days}d)")
for r in q(f"select source, count(*), sum(message_count), "
           f"round(sum(coalesce(actual_cost_usd,estimated_cost_usd,0)),2) "
           f"from sessions where {S} > datetime('now','-{days} day') group by 1 order by 2 desc"):
    print(f"  {str(r[0]):<14} sessions={r[1]:<6} msgs={r[2]:<8} cost=${r[3]}")
print("  NOTE: sanity-check cost against a known scale. Observed telemetry bug:")
print("        one week summed to $484,539. Call an absurd figure a bug out loud.")

section(f"telegram chats (last {days}d)")
for r in q(f"select coalesce(display_name,chat_id), count(*), max({S}), sum(message_count) "
           f"from sessions where source='telegram' and {S} > datetime('now','-{days} day') "
           f"group by 1 order by 2 desc limit 15"):
    print(f"  {str(r[0])[:38]:<40} sess={r[1]:<5} last={str(r[2])[:16]} msgs={r[3]}")

section("subagent fan-out by week (drives peak RAM)")
for r in q(f"select strftime('%Y-W%W',{S}) wk, count(*), sum(message_count) from sessions "
           f"where source='subagent' and {S} > datetime('now','-{days} day') group by wk order by wk"):
    print(f"  {r[0]}  n={r[1]:<5} msgs={r[2]}")

section("models used (last 30d)")
for r in q(f"select coalesce(model,'?'), count(*) from sessions "
           f"where {S} > datetime('now','-30 day') group by 1 order by 2 desc limit 10"):
    print(f"  {str(r[0])[:44]:<46} {r[1]}")

section("last 20 sessions")
for r in q(f"select {S}, source, substr(coalesce(title,'?'),1,58), message_count "
           f"from sessions order by started_at desc limit 20"):
    print(f"  {str(r[0])[:16]} {str(r[1])[:10]:<11} m={str(r[3]):<5} {r[2]}")
