# Thread-map / open-loops inventory from the session DB

Use when asked to "inventory recent sessions", "map open threads", "find stalled loops",
or produce a status report across all recent Hermes activity. Verified working 2026-07-07.

## Where the data actually is

- **The real session store is `~/.hermes/state.db`** — tables `sessions` + `messages`
  (plus FTS mirrors).
- `~/.hermes/sessions.db` and `~/.hermes/session.db` **exist but are 0-byte decoys**
  (`.tables` returns nothing). Don't waste time on them; check file size first.
- `session_search()` with no args only browses the ~3 most recent sessions — fine for a
  peek, useless for a full inventory. Go straight to SQL for anything exhaustive.

## Key schema facts

`sessions`: `id`, `source` (telegram/cron/subagent/cli), `session_key`, `chat_id`,
`thread_id`, `title`, `message_count`, `started_at` (unix float), `end_reason`,
`parent_session_id`, `handoff_error`.

- `session_key` format for Telegram forum topics:
  `agent:main:telegram:group:<chat_id>:<thread_id>` (e.g. `...:-1001234567890:6330`).
- Many real telegram sessions have `session_key` **NULL** (DMs / non-topic) — query both
  keyed and unkeyed, filter by `source='telegram'`, don't rely on session_key alone.
- `messages.content` is sometimes a **JSON list of `{type,text}` chunks**, sometimes a
  plain string — always run it through a clean() helper (see below).
- "Last activity" must come from `MAX(messages.timestamp)`, not `sessions.started_at` —
  long-lived topic sessions started weeks ago can be active today.

## Recipe

1. **Recent sessions with real last-activity time** (10-day window shown):

```sql
SELECT s.id, s.session_key, s.source, s.title, s.message_count,
  datetime((SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id=s.id),
           'unixepoch','localtime') AS last_msg
FROM sessions s
WHERE s.source='telegram'
  AND (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id=s.id)
      > strftime('%s','now') - 864000
ORDER BY last_msg DESC;
```

2. **Exclude noise, but sanity-check it first.** Filter out `source IN ('cron','subagent')`
   for the map, but run one health check so the report can say "cron fleet fine":

```sql
SELECT end_reason, COUNT(*) FROM sessions
WHERE source='cron' AND started_at > strftime('%s','now')-864000
GROUP BY end_reason;
-- healthy ≈ all 'cron_complete', no error groups / handoff_error rows
```

3. **Classify each session by reading bookends via Python** (sqlite3 stdlib, no deps):
   first 1–2 user/assistant messages = goal; last 3–4 = where it left off.

```python
import sqlite3, json, time
db = sqlite3.connect('/Users/<person-a>/.hermes/state.db'); db.row_factory = sqlite3.Row
def clean(c):
    try:
        j = json.loads(c)
        if isinstance(j, list):
            return ' '.join(x.get('text','') for x in j if isinstance(x, dict))
    except Exception: pass
    return c or ''
msgs = db.execute("""SELECT role, content, timestamp FROM messages
    WHERE session_id=? AND role IN ('user','assistant')
    AND content IS NOT NULL AND content != '' ORDER BY timestamp""", (sid,)).fetchall()
# bookends: msgs[:2] and msgs[-4:]
```

4. **STALLED detection — read the last USER messages separately.** The strongest stall
   signal is the last user message being a question the assistant answered tersely, or
   the assistant's last message being "resend X / pick one / waiting on Y" with no user
   reply since. Query `role='user' ORDER BY timestamp DESC LIMIT 3` per session when the
   tail is ambiguous.

## Classification rubric (worked well)

- **FINISHED** — assistant delivered a verified artifact, user acknowledged or went quiet
  after delivery. Subcategory worth flagging: "done but awaits user's one click" (e.g.
  email draft verified in Drafts, never sent).
- **STALLED** — open loop: unanswered question to the user, assistant blocked and waiting
  (resend image, human login, headers never pasted), promised follow-up not done, or a
  negative result never confirmed by the user.
- **ONGOING** — live back-and-forth, or the session driving the current work.
- Superseded sessions (user said "Stop", then restarted the task in a new session) →
  mark superseded, point at the successor, don't count twice.

## Report shape that landed well

- Markdown file: STALLED section first (numbered, each with session id/key, goal,
  where-it-left-off, single next action) → ONGOING → FINISHED as a compact table →
  "Systemic observations" (shared blockers appearing across multiple threads — e.g. one
  degraded subsystem blocking 3 threads is the highest-leverage fix).
- Chat reply: compact list of STALLED items with one best next action each, plus cheap
  wins (pending drafts) and the systemic blocker.

## Pitfalls

- Large per-session dumps get truncated in terminal output — batch ~6 sessions per
  Python run with tight `[:300]`-ish truncation per message, run multiple passes.
- Untitled sessions (`title` NULL) are often the most important ones (brand-new active
  topics) — never skip NULL-title rows.
- A session's `message_count` includes tool messages; filter `role IN ('user','assistant')`
  when reading for meaning.
