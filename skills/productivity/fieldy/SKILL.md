---
name: fieldy
description: >
  Use when reading conversations, transcripts, summaries, or action items captured by a
  Fieldy AI wearable note taker, or when the user mentions Fieldy, their wearable, or
  wants the record of something said in person rather than on a video call. Covers API
  key setup, the time-window query model, pagination, and the async-processing and
  speaker-labelling gotchas that make naive reads report incomplete data.
version: 1.0.0
license: MIT
platforms: [macos, linux]
compatibility: >
  Agent Skills standard. The bundled client is stdlib-only Python and needs no
  Hermes runtime; any agent that can run python3 and read an env var can use it.
metadata:
  hermes:
    tags: [fieldy, wearable, transcripts, recorders, integrations]
    requires:
      - "env: FIELDY_API_KEY (Fieldy app → Settings → Developer Settings)"
      - "Python 3.9+ (stdlib only, no third-party packages)"
    related_skills: []
---

# Fieldy

## When to Use

Use when the user mentions Fieldy, their wearable, or wants a real-world
(non-video-call) conversation transcript, summary, or the action items the
device captured. Also use when asked what was said in a specific in-person
meeting, hallway conversation, or errand.

Fieldy is a wearable AI note taker (pendant or wrist, Bluetooth to a phone) with
a companion desktop app that captures Zoom/Teams/Slack calls. It transcribes
conversations and generates summaries, keywords, quotes, speaker labels, and
action items. This skill reads that data over Fieldy's Public REST API.

If the user runs several capture devices (a meeting notetaker, a second pendant),
coverage differs by device. A gap in Fieldy is not evidence the conversation
never happened — check the other sources before concluding anything is missing.

## Setup

1. Open the **Fieldy mobile app** → **Settings** (gear icon) → **Developer
   Settings** → copy the API key. It starts with `sk-fieldy-` and is long-lived.
   The same screen exists in the desktop app.
2. Export it as `FIELDY_API_KEY`, or put it in a `0600` dotenv file and pass
   `--env-file /path/to/.env`. It is a bearer token for the user's entire
   personal conversation history — treat it like a password.
3. Verify: `python3 scripts/fieldy.py whoami` → returns `{"email": "..."}`.
   A wrong key returns HTTP 401 `{"code":"UNAUTHORIZED"}` with exit 1.

The client reads **only** the environment variable and an explicitly-passed
`--env-file`. It deliberately does not search config directories for a key:
an implicit scan on a multi-account machine can hand the caller a different
person's credential and silently return someone else's conversations. If several
agents share a host, give each one its own `FIELDY_API_KEY`.

## API facts

Verified against the live API and its published OpenAPI 3.1.1 spec.

- Base URL: `https://api.fieldy.ai/api/public/v2`
- Auth header: `Authorization: Bearer sk-fieldy-<key>`
- Rate limit: the API reference states **100 requests / 60s** followed by a 60s
  cooldown; the vendor's launch post says 30/min. Treat **30/min as the safe
  budget** and back off on `429`. The bundled client sleeps between pages and
  retries `429` with escalating delay — but only for `GET` (see Pitfalls).
- The API never legitimately redirects, and the client refuses redirects
  outright. This is a security control, not politeness: `urllib` replays request
  headers on a redirect, so a `302` to another host would hand that host the
  bearer token. Verified by test.
- There is **no search endpoint**. Every read is time-window based — pull a range
  and filter locally. Do not look for a `?q=` parameter; it does not exist.
- Interactive docs: `https://api.fieldy.ai/docs` (Scalar). The raw OpenAPI JSON
  is **not** served at `/openapi.json`, `/docs/json`, or `/docs/openapi.json`
  (all 404). It is embedded in the docs HTML as `const scalarConfig = {...}`,
  where the `content` key holds the whole spec as a JSON *string*. Extract with
  `json.JSONDecoder().raw_decode` on the text after that assignment, then a
  second `json.loads` on `content`. A cached inventory of every endpoint,
  parameter, and response schema is in `references/openapi-endpoints.md`.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/user/me` | returns `{email}` only — the cheapest auth probe |
| GET | `/conversations` | `startTime`+`endTime` **required**, ISO 8601; `mode=starts-in-range\|intersects-range`, `pageSize` max **50** (default **6**), `cursor`, `recordingSource=wearable\|phone\|desktop` |
| GET/PATCH/DELETE | `/conversations/{id}` | GET returns bare `null` for an unknown id, not a 404 |
| POST | `/conversations` | create |
| GET | `/transcriptions` | `startTime` required, `endTime` optional; `conversationId`, `recordingSource`, `order=asc\|desc`, `inclusive`, `pageSize` max **1000**, `limit` max 2000 |
| GET/POST/PATCH/DELETE | `/tasks`, `/tasks/{id}` | GET **requires** `status` (new/approved/completed/rejected/skipped/cancelled/expired) |
| GET/POST/PATCH/DELETE | `/speaker-profiles`, `/speaker-profiles/{id}` | |
| GET/POST/PATCH/DELETE | `/memory-templates`, `/memory-templates/{id}` | prompt templates that shape summaries |
| GET/POST/PATCH/DELETE | `/sharables`, `/sharables/{id}` | public share links; also `GET /sharables?conversationId=`, `GET /sharables/resolve?idOrUrl=` |

### Response shapes

- **Conversation**: `id, title, summary, content, startTime, endTime,
  type(FULL|BRIEF), keywords[], speakers[], quotes[{text,context}],
  location{address,coordinates,city,...}, locationId, templateId,
  calendarEventId, updatedAt`. `memorySpeakers` and `memoryTemplateId` are
  DEPRECATED aliases kept for old clients — use `speakers` and `templateId`.
- **Transcription segment**: `id, text, timestamp, speaker, speakerProfileId,
  start, end, createdAt, source, recordingSource`. `start`/`end` are seconds
  offset within the recording; `timestamp` is the absolute time.
- List responses are `{items: [...], nextCursor: string|null}`. Tasks return
  `{items}` with **no** cursor.

## Usage

```bash
S=path/to/scripts/fieldy.py

python3 $S whoami                                    # auth probe
python3 $S conversations --days 1 --text             # last 24h, readable
python3 $S conversations --start 2026-05-01T00:00:00Z --end 2026-05-07T23:59:59Z
python3 $S conversation <id>                         # one conversation, full JSON
python3 $S transcript --conversation-id <id> --text  # speaker-labelled transcript
python3 $S transcript --days 1 --source wearable --text
python3 $S tasks --status new
python3 $S speakers
python3 $S templates
python3 $S raw /sharables --param conversationId=<id>   # any endpoint
```

`--text` gives readable output on every subcommand; the default is JSON for
piping. `--text`, `--verbose`, and `--env-file` work on either side of the
subcommand.

`--limit` and `--page-size` exist only on `conversations` and `transcript`,
which are the paginated commands, and must be placed **after** that subcommand.
Passing them elsewhere is a hard argparse error rather than a silent no-op.
Pagination is automatic: the client follows `nextCursor` until the range is
exhausted, refuses to loop on a repeated cursor, and never requests a larger
page than `--limit` needs.

Mutating calls through `raw` require an explicit `--yes`.

## Workflow: "what did I discuss about X this week"

1. `conversations --days 7` as JSON, then filter locally on `title`, `summary`,
   `keywords`, and `quotes`. There is no server-side search, so the filtering is
   yours to do.
2. For each hit, `transcript --conversation-id <id> --text` to get the raw record.
3. Only then summarize. If the user asked what was actually *said*, do not
   answer from `summary` alone — that field is model output about the
   conversation, while the transcript is the conversation. Quote the transcript.

## MCP alternative

Fieldy also serves MCP at `https://api.fieldy.ai/mcp` (HTTP transport), offered
as a one-tap connector in Claude and ChatGPT. That path uses a browser-driven
OAuth handshake, and there is no documented way to authenticate it with a bare
`sk-fieldy-` key. **For an agent writing code, prefer the REST API.** Reach for
MCP only when the goal is Fieldy inside a chat client's connector UI.

## Pitfalls

- `startTime` and `endTime` on `/conversations` are **required**. A bare
  `GET /conversations` is a 400, not "everything".
- Default `pageSize` on conversations is **6**. An unpaginated call will happily
  report six conversations as though that were the whole week. Always follow
  `nextCursor`.
- `mode` defaults to `starts-in-range`, so a conversation that began before your
  window and ran into it is **excluded**. Use `intersects-range` when the
  question is "what was happening at 3pm" rather than "what started today".
- Transcripts are fetched by **time range**, not by conversation id alone. The
  spec describes `conversationId` as "legacy client input resolved to canonical
  recording source". Resolve the conversation first and pass its real
  `startTime`/`endTime`; do not assume the id filters on its own. Verified: a
  conversation-scoped fetch and a raw time-window fetch over the same interval
  returned identical segments.
- Processing is async after a recording stops ("Sending to Private Cloud" →
  "Transcribing" → "Generating Title"). A just-ended conversation can return a
  null `title`, null `summary`, empty `speakers[]`, and zero transcript segments.
  That is **not** an API failure and not an empty conversation — retry later
  before reporting nothing was captured.
- A recording has a 3-hour hard cap, so a long day is many conversations rather
  than one.
- The device only captures while transcription is running. A gap in the data
  means it was not recording, not that the API lost anything.
- Before any speaker profile exists, segments come back with `speaker:
  "Unknown"` and the conversation's `speakers[]` is empty. Once a profile is
  created, segments label as `Speaker 1`, `Speaker 2`, and so on. These are
  positional labels, not identities — a fresh account's only profile was named
  `User`. Do not promise "who said what" beyond what the labels support.
- `GET /conversations/{id}` with an unknown id returns HTTP 200 with a bare
  `null` body rather than a 404. Check for `None` explicitly or a downstream
  `conv["startTime"]` raises an opaque `TypeError`.
- Transcripts are verbatim, including profanity, false starts, and whatever was
  said near the device by people who did not know it was recording. Treat the
  content as sensitive by default and do not echo more of it than the task needs.
- `DELETE` and `PATCH` mutate the user's personal record, and `POST /sharables`
  mints a **publicly accessible link** to a private conversation. They are
  reachable only through `raw --method ... --yes`; there is no convenience
  subcommand for them by design. Never call one without an explicit instruction
  naming the target.
- **Only `GET` is retried.** A retried `POST`/`PATCH`/`DELETE` that actually
  succeeded before the connection broke repeats the side effect — for
  `POST /sharables` that means several public links to one private conversation.
  A failed mutation reports `Outcome UNKNOWN` and stops; reconcile state before
  trying again.
- Error output prints the endpoint path **without** the query string and redacts
  anything matching `sk-...`, because both can carry the key and API error
  bodies can quote transcript text. `--verbose` widens the echoed body; use it
  when debugging, not in normal operation.
- A time window is anchored to `--end`, so `--end <date> --days 7` means the
  seven days *before that date*. An earlier version anchored the lookback to
  now, which silently produced `start > end` — the API answers an inverted
  window with zero rows, and an agent then reports "nothing was discussed" when
  the query was simply malformed. Inverted or unparseable windows now exit 1.
