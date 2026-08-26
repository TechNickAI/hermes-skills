#!/usr/bin/env python3
"""Prove empirically whether archiving a Hermes session hides it from search,
and whether pruning destroys it.

Run with the Hermes venv interpreter:

    ~/.hermes/hermes-agent/venv/bin/python verify_archive_vs_prune.py

Builds a scratch state.db in a temp dir. Touches nothing real. Expected output:

    search hits BEFORE archive: 1
    search hits AFTER  archive: 1
    archived flag in DB: 1
    list include_archived=False: 0
    list include_archived=True : 1
    search hits AFTER  prune  : 0
    RESULT: archive preserves search; prune destroys it.

API gotchas this script already accounts for (each cost a round trip when the
check was first written):
  * SessionDB(db_path=...) wants a pathlib.Path, not a str.
  * create_session() requires an explicit session_id as its first argument.
  * the writer is append_message(), not add_message().
  * end_session() requires an end_reason. prune_sessions() only considers ENDED
    sessions, so skipping this makes prune look non-destructive.
"""

import os
import pathlib
import sys
import tempfile
import uuid

HERMES = os.path.expanduser("~/.hermes/hermes-agent")
sys.path.insert(0, HERMES)

tmp = tempfile.mkdtemp()
os.environ["HERMES_HOME"] = tmp

from hermes_state import SessionDB  # noqa: E402

MARKER = "the zebra mnemonic quixotic marker"

db = SessionDB(db_path=pathlib.Path(tmp) / "state.db")
sid = str(uuid.uuid4())
db.create_session(sid, source="telegram")
db.append_message(sid, "user", MARKER)
db.end_session(sid, "completed")


def hits():
    return len(db.search_messages("quixotic", limit=10))


before = hits()
print("search hits BEFORE archive:", before)

db.set_session_archived(sid, True)
after_archive = hits()
print("search hits AFTER  archive:", after_archive)
print(
    "archived flag in DB:",
    db._conn.execute("select archived from sessions where id=?", (sid,)).fetchone()[0],
)
print(
    "list include_archived=False:",
    len(db.list_sessions_rich(limit=50, include_archived=False)),
)
print(
    "list include_archived=True :",
    len(db.list_sessions_rich(limit=50, include_archived=True)),
)

db.prune_sessions(older_than_days=0)
after_prune = hits()
print("search hits AFTER  prune  :", after_prune)

ok = before == 1 and after_archive == 1 and after_prune == 0
print(
    "RESULT: archive preserves search; prune destroys it."
    if ok
    else "RESULT: UNEXPECTED — re-read hermes_state_search.search_messages() before "
    "relying on the archive-is-safe claim."
)
sys.exit(0 if ok else 1)
