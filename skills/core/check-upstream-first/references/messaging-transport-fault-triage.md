# Worked cases: Telegram flood-control + Slack Socket Mode flap

Both diagnosed on an assistant agent (Ali's Mac mini) one occasion. Both turned out to be
**already fixed upstream** — the member was running 0.18.2 while the fixes had
shipped. Recorded here so the next occurrence is a version check, not a
source-reading expedition.

---

## Case 1 — Telegram: long replies fail with "could not be sent"

### User-visible symptom

```
⚠️ Message delivery failed after multiple attempts. Please try again —
your request was processed but the response could not be sent.
```

Reported by Ali on ~6,900-char answers. The answer was generated fine; delivery
failed. Also presents as duplicate/truncated messages posted 3–4× with each copy
cut off at the same point.

### Mechanism

Progressive streaming edits (`editMessageText`) with the shipped defaults
(`streaming.buffer_threshold: 24`, `streaming.edit_interval: 0.8`) fire an edit
roughly every 24 characters. That spends the bot's per-chat Telegram rate budget
_before_ the final long message is sent. The final send then hits:

```
Flood control exceeded. Retry in 32 seconds
```

In the 0.18.x send loop (`gateway/platforms/telegram.py`, send/split/flood block
~lines 2454–2675), the flood handler read `retry_after` but the loop was capped
at 3 attempts (`for _send_attempt in range(3)`) with short exponential backoff
(~2s, ~4s) — far below the server's 25–37s. Retries fired too early, hit flood
control again, exhausted the budget, and the response was dropped.

Constants for orientation: `MAX_MESSAGE_LENGTH = 4096`,
`RICH_MESSAGE_MAX_CHARS = 32768`, `_SPLIT_THRESHOLD = 4000`.

The stream consumer has adaptive backoff and, after `_MAX_FLOOD_STRIKES`, sets
`_edit_supported = False` and falls back to sending each remaining slice as a
NEW message — that is the mid-word one-bubble-per-slice chunking artifact, and it
must NOT be treated as an acceptable recovery path.

### Already fixed upstream

| Item  | Detail                                                                                                               |
| ----- | -------------------------------------------------------------------------------------------------------------------- |
| Issue | **#46762** (P1) — "Telegram sendRichMessage flood-control retry ignores server retry_after and drops final response" |
| Fix   | **PR #52143 merged one occasion**, commit `404b06ac` — "honor server retry_after in Telegram flood control"          |
| Note  | PR #46774 (same title) remained **open**; the rebased #52143 carried the merge. Always confirm which one merged.     |

Related shipped fixes in the same family:

- **#48648** — infinite streamed duplication loop during 4096-char overflow
  (pre-flight overflow check ran on every streamed edit, even `finalize=False`)
- **#36965** — streaming edit transport duplicates final message when the
  cursor-strip edit is rate-limited
- **#25010** — streaming leaves incomplete partial message while final send is
  suppressed
- **#16668** — flood control leaves partial message + duplicate final response
- **#25188** — flood-control fallback stops coalescing tool progress and starts
  sending new messages

Still-open siblings worth knowing: #55761 (duplicate identical messages on short
text-only turns), #53449 (non-overflow replies duplicated when final delivery
flags are lost), #51828 (streaming truncation triggers full regeneration).

### Do NOT propose disabling streaming

the operator explicitly rejected it: **"I don't want streaming off. Try again."**
Setting `ui.platforms.telegram.streaming: false` does suppress the symptom, but
it removes a feature he wants. He had also previously rejected tuning
`streaming.buffer_threshold` as "cute but not what's going on."

The supported answer is the upstream `retry_after` fix — **take the version,
keep streaming on.**

Note there are two config surfaces and BOTH matter: the top-level `streaming:`
block and the per-platform `ui.platforms.telegram.streaming` override. A config
can show `streaming.enabled: false` and still stream to Telegram via the
override.

---

## Case 2 — Slack: endless "Socket Mode unhealthy" reconnect flap

### Log signature

```
ERROR slack_bolt.AsyncApp: Failed to connect (error: Session is closed); Retrying...
  .../slack_sdk/socket_mode/aiohttp/__init__.py, line 377, in connect
WARNING hermes_plugins.slack_platform.adapter: [Slack] Socket Mode unhealthy (transport disconnected); reconnecting
```

### Mechanism

`slack_sdk`'s aiohttp Socket Mode backend creates ONE `aiohttp.ClientSession` at
init and never recreates it after a disconnect. Once the websocket drops, every
subsequent `ws_connect()` fails immediately with `Session is closed` — the
session object is permanently invalidated. The watchdog detects "unhealthy" every
~15s and restarts into the same poisoned session. Infinite loop.

Upstream reports **242 unhealthy events/day** on a Mac that never sleeps.
an assistant agent logged 96 in a single file, flapping steadily for ~2.5 weeks
(one occasion → one occasion).

### Real impact — not log noise

Inbound Slack messages can be **silently missed** while the socket is dead.
Treat it as a delivery outage.

### Already fixed upstream

| Item       | Detail                                                                                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Issue      | **#46990** — "Slack Socket Mode aiohttp backend leaks closed sessions — persistent unhealthy reconnect loop" (closed one occasion)                                          |
| Fix        | **PR #47003** → rebased **#51623** — "prefer websockets socket mode backend"                                                                                                |
| Plus       | **#66645** "heal 'Session is closed' stuck reconnect loop"; **#69319** "Socket Mode health — fail-fast creds, session heal, staleness detection, clean shutdown, dedup TTL" |
| Ships with | **slack-sdk 3.43.0** (up from 3.40.1)                                                                                                                                       |

Related: #25476 (Socket Mode silently drops without auto-reconnect, no log at
default WARNING level), #14326 (gateway can remain "running" while Socket Mode is
dead).

### A restart does NOT fix this

It re-poisons a fresh session within a day or two. the operator called this correctly:
_"can do a restart… that's not what this is."_ The fix is the version.

---

## Verification after the upgrade

Filter strictly by timestamp — `tail` shows pre-restart lines and reads like the
bug survived:

```bash
awk '/^one occasion 10:(1[89]|[2-9][0-9])/' gateway.log | grep -c "Socket Mode unhealthy"
# after restart: 0   (was flapping at 09:28, 09:52, 09:52 immediately prior)
```

Healthy startup on 0.19.0:

```
✓ telegram connected                     (polling mode)
[Slack] Authenticated as @<agent> in workspace <workspace>
[Slack] Socket Mode connected (1 workspace(s))
✓ slack connected
Gateway running with 2 platform(s)
```

## gh CLI note

`gh issue view` / `gh pr view` fail on this repo with
`GraphQL: Projects (classic) is being deprecated... (repository.issue.projectCards)`.
Use `gh api repos/NousResearch/hermes-agent/issues/<n> --jq...` instead.
`gh search issues --repo...` works fine.
