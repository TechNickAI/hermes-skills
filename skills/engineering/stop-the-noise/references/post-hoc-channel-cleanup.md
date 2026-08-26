# Building the channel janitor: Telegram mechanics and classifier traps

Implementation companion to `channel-cleanup-and-alarm-escalation.md`. That file settles
**what** to build and why (measure first; repetition is an alarm; allowlist + archive;
pin-and-edit; shared-room conduct). This file records **how**, from probing the platform
live and shipping a working steward on one occasion.

Read the policy reference first. Everything here assumes those rules are already agreed.

## Probe, don't trust docs — the capability matrix

Measured live against a real forum, not read from documentation:

| Capability                                                              | Result                                                              |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Bot deletes its **own** message                                         | ✅                                                                  |
| Bot deletes message **>48h old**                                        | ❌ hard server-side limit                                           |
| Bot deletes **another bot's** message                                   | ❌ not even visible — `getChat` → `chat not found`                  |
| Bot reads channel **history**                                           | ❌ no Bot API method; `getUpdates` returns 0 against a live gateway |
| Owner user session, any age                                             | ✅ via telethon                                                     |
| Reactions per message from a bot                                        | **exactly 1** — 2 gives `REACTIONS_TOO_MANY`                        |
| `setMessageReaction` valid emoji                                        | **34 only**                                                         |
| `✅` and `👀` as reactions                                              | ❌ `REACTION_INVALID` — the two most intuitive choices both fail    |
| Working status reactions                                                | `🔥 👍 🥱 💯 🤔 ⚡ 🎉 😱 🤯 💔`                                     |
| `is_big` on a reaction                                                  | ❌ rejected                                                         |
| Clearing a reaction (`reaction=[]`)                                     | ❌ rejected                                                         |
| Pin / unpin (multiple)                                                  | ✅ newest wins in `getChat.pinned_message`                          |
| Edit in place, silent send, reply-to, HTML jump links, inline keyboards | ✅                                                                  |
| `editForumTopic` — **name** and **icon**, live                          | ✅                                                                  |
| `getForumTopicIconStickers`                                             | 112 custom emoji                                                    |
| Useful topic icons present                                              | `🔥 ❗️ ✅ 👀 💰 🔎 🧠 📈 📉 ⚡️`                                    |
| Topic icons **NOT** available                                           | `🔴 🟡 🟢 ⚠️ 🚨 📊 ⏳ 🛠 📌 😴`                                     |

Two consequences worth internalizing: a red/yellow/green topic-icon scheme **cannot be
built** (no colored circles), and `✅` works as a _topic icon_ but not as a _reaction_ —
the two emoji sets are different. Enumerate both before designing any visual language.

## The forced architecture

Bots cannot read history and cannot see rooms they are not in, so:

- **telethon user session = the eyes.** Reading, classification, and decisions.
- **each agent's own bot token = the hands.** Deletes only its own recent output, only in
  its own rooms.

Cleanup **acts** per-agent with each agent's own token. There is no central sweeper that
deletes with one credential — Telegram forbids it, independent of any fleet convention.

**But do not conclude the JOB belongs on each agent's host.** That design was tried and
failed at fleet rollout: remote hosts had neither telethon nor the owner's user session,
and the read side _requires_ that session, which exists in exactly one place. Copying it
to every machine would spray a personal credential across the fleet.

The resolving fact: **bot tokens are not host-bound.** Verified by fetching a remote
agent's token over SSH and successfully calling `getMe` plus `getChat` on its own room
from a different machine. So the working shape is:

> **Read once centrally with the owner's user session; act per-agent with each agent's
> own bot token.** One sweep, one job, a `chats` list of `{chat, bot_token}` objects.

This is a real exception to the usual "per-agent job on its own host" fleet convention.
That convention still holds wherever an agent can do the whole task with its own
credentials; it breaks precisely when one side of the task needs a credential that
exists in a single location. Name which credential each half of the work requires before
choosing where the job runs.

Two rollout mechanics worth keeping:

- **Enumerate agents from the platform, not from memory.** Map bot→room by measuring who
  actually posted (21 days of traffic), rather than assuming a naming convention. It also
  surfaces agents that post _nothing_: one fleet member turned out to be Discord-only
  with no Telegram token at all, so it correctly has nothing to steward — an absence that
  looks like an oversight until you check.
- **A token read over SSH may be display-redacted in tool output** while still being
  intact in-process. If a fetched token prints as `***`, check its length and call
  `getMe` before concluding it is missing — build the config in one process rather than
  echoing secrets between steps.

The 48h wall makes cadence non-negotiable: miss two hourly runs and that window is
permanently uncleanable by bot. Prefer a **deterministic script over an LLM turn** for
the mechanical pass — cheaper, faster, and it cannot decide to skip.

**Escalation state must persist OUTSIDE the scan window** (SQLite keyed on
`(chat, signature)` with first_seen/last_seen/count/acked). Deletion eligibility expires
at 48h; escalation must not. The real incident ran 95 hours, so a scan-window-bound tool
stops escalating exactly when staleness matters most.

## Classifier traps that produced real false positives

Every one of these was found by running against real traffic, not by review.

- **Alarm regexes must match machine-emitted SHAPES, not prose.** A first pass matching
  any message containing `halt|escalat|broken|margin|401|403` flagged **385** ordinary
  conversational messages on one agent as critical. Anchoring to ALL-CAPS tokens, line
  starts, `SEV-N`, and `Cron '<name>' failed` shapes brought it to 135 real ones.
  _"The halt cleared and entry is running again"_ is not an alarm.
- **Test the regex in BOTH directions** with real fixtures — a must-match list of real
  alarms and a must-not-match list of real conversational prose — before trusting it.
- **Do not normalize digits when clustering.** Mapping every number to `N` collides
  distinct order IDs, prices, and symbols into one "duplicate" cluster and can delete
  genuinely different alerts. Cluster on exact canonical text, whitespace-normalized only.
- **Key clusters by `(thread_id, signature)`**, never chat alone, or the sole copy in one
  forum topic gets deleted because a "survivor" exists in a different topic.
- **Emoji classification needs real codepoints.** `✍` is U+270D and `✏` is U+270F — a
  character class containing only one silently missed a whole family of progress bubbles
  that then appeared as bogus "escalations". Tolerate the optional variation selector
  (`\ufe0f?`), and match a **prefix shape** since the gateway truncates these strings.
- **Service messages leak into delete paths.** `MessageActionPinMessage` and friends
  report empty text and are not bot-deletable; treating them as ephemera archived records
  for messages that were never deleted. Skip anything with `action is not None`.
- **Classify by whole-message shape, not first character.** First-char dispatch breaks
  the moment a new prefix appears, and bypasses content inspection entirely.
- **Honour HTTP 429 `retry_after`.** A sweep touching hundreds of messages trips flood
  control; silently swallowing those failures makes partial cleanup report success. Exit
  non-zero when any requested mutation failed.

## Archive durability — "wrote a file" is not proof

- `flush()` + `os.fsync()` **before** any delete. A crash between write and delete loses
  the archive while the message is already gone.
- Verify by **re-reading and re-parsing every line**, asserting record count and IDs
  match. Merely re-opening and reading the file passes even after a partial write.
- **Refuse to delete when verification fails.** Do not rely on an unhandled exception.
- **Media is never auto-deleted.** A text-only archive records a chart-only alert as `""`
  then destroys it permanently. Hold anything with `media is not None` — including
  `MessageMediaUnsupported`, which the reader cannot even render. On this fleet that was
  138 messages on one agent alone.
- **Dry-run must not mutate the archive**, or repeated dry-runs accumulate records
  implying deletions that never happened.

## Verify the run — the tool's own counters lie

Do not trust reported success. Re-read every archived ID through the _reader_ session and
confirm it is actually gone from the platform.

On the first live run this surfaced **5 survivors out of 31** that the counters had
reported as deleted; they traced to service messages and unsupported media reaching the
delete path. That is a real classification bug the success counters concealed.

## UX layer worth not re-deriving

Prior art: _"Async agents need an inbox, not a chat"_ (tianpan.co, 2026-04) — for
long-running agents the transcript is the wrong product. An inbox commits to
**durability** (runs outlive the session), **notifiability** (completion is an event the
system fires, not a state the human polls), and **result-over-progress** framing. Chat
metrics like time-to-first-token and session length measure captivity, not utility.

GramIO's UX-patterns guide adds the complementary rule: **edit in place, don't spam new
messages** — one message lives and gets rewritten; new messages are for events only.
Applied here, the janitor's own summary must be a single pinned, edited message, or the
cleanup tool becomes a new noise source.

Surfaces this unlocks, all verified available:

- **Topic title + icon as an ambient status bar.** `editForumTopic` turns the forum list
  itself into a dashboard (`🔥 a research agent — 2 need you`) with nothing sent and nothing to
  open. Severity in the icon, count in the name. **Renaming a topic in a shared room
  changes what other people see — gate it on that room owner's consent.**
- **Reactions as read-state.** `🔥` unacknowledged+stale, `👍` owner replied, `💯` rollup
  survivor. Free, non-notifying, visible in place.
- **Inline buttons for the acknowledgment loop** (`[Ack] [Snooze 4h] [Fix it]`). The
  29-times-repeated guard kept escalating partly because acknowledging required typing a
  reply. One tap should end an escalation — this closes the loop the alarm data exposed.
- **Closing a forum topic sorts it to the bottom**, so dormant threads sink on their own.

## Rollout posture

Turn it on for **your own room first**, with `--apply` gated behind a clean dry-run, and
show the operator the archive before touching a room where a deleted message could matter
(live trading rooms, client rooms). Default `collapse_allowlist: []` so nothing collapses
until a specific signature is explicitly approved — ephemeral deletion alone is the
reversible starting point.
