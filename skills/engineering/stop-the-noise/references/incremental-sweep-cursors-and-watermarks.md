# Incremental sweeps: cursors, watermarks, and the bugs they cause

Companion to `post-hoc-channel-cleanup.md`. That file covers building the
janitor and the classifier traps. This file covers what happens when you make
the sweep **incremental** — which you must, or every run reprocesses every
topic — and the class of bug that introduces.

These findings came out of two code-review rounds on a working implementation,
after the first version was already shipping and passing its own tests. Several
were regressions introduced _while fixing_ earlier findings.

## Walking topics without redoing work

Two independent gates, both required:

1. **Per-topic cursor** persisted in SQLite. Compare the topic's current head
   (`ForumTopic.top_message`) against the stored cursor and skip the topic
   without fetching a single message. Pass `min_id=cursor` to `iter_messages`
   so the server only returns what is new.
2. **Skip topics the owner has not caught up on** (see watermarks below).

Measured effect: steady state went from 22 topics walked to **0 walked, 22
skipped**.

**The pitfall that silently defeats the cursor:** only writing a cursor when a
topic yielded messages. Dormant topics never earn one and are re-walked
forever. That capped skipping at 6 of 22 until fixed. **Record the cursor at
the topic head even when the batch was empty.**

## Read watermarks beat presence

The intuitive "is the owner around?" signal is presence. It does not work:

`UserStatus` read through the **owner's own** session always reports
`UserStatusOnline`, because that session _is_ the owner being online. A bot
cannot read user status at all. Presence is unusable here.

Use `ForumTopic.read_inbox_max_id` — the highest message id the owner has read
in that topic, synced across their devices:

- Skip any topic with `unread_count > 0` entirely. Deleting or collapsing there
  destroys messages before they are ever seen.
- Inside a caught-up topic, hold any message with `id > read_inbox_max_id`.

This is a stronger guarantee than presence would have given: it is per-topic
and device-synced, not a global "was recently typing".

For a non-forum group use `GetPeerDialogsRequest(peers=[ent])`. Scanning
`get_dialogs(limit=N)` silently misses any chat outside that window, which on a
busy account means the room is skipped forever.

## Telethon call-shape gotchas

- `GetForumTopicsRequest` is under `functions.messages`, **not**
  `functions.channels`, and takes `peer=`, not `channel=`. Signature:
  `(peer, offset_date, offset_id, offset_topic, limit, q=None)`.
- `functions.channels` has no forum-topic methods at all — searching there and
  concluding forums are unsupported is a real dead end.

## The bug class incremental sweeps create

Making the sweep incremental changes what each batch contains, and **any logic
that reasons about repetition from the current batch quietly stops working.**

### Batch-local counting never fires

An alarm firing hourly appears as exactly one message per sweep. Escalation
logic comparing `len(group)` against a threshold sees `1` on every run,
forever. The tool reports success, its tests pass, and the thing it exists to
catch never triggers.

Derive count and elapsed span from **persisted state**, not the batch. Two
things that will keep it broken even after you "fix" it:

- **`hash()` is salted per process.** Used as a persistence key it writes a
  different row every run, so nothing accumulates. Use `hashlib`.
- **Taking `max()` of batch sizes** pins the count at 1 for the same reason
  batch-local logic fails. Counts must accumulate.

### Accumulating naively double-counts on retry

Once counts accumulate, a held cursor (see below) re-fetches the same messages,
and adding `n` per call inflates the total — which can trip escalation on
something that never actually repeated.

**Count distinct message ids**, in a `seen(chat, sig, msg_id)` table with
`INSERT OR IGNORE`. That makes observation idempotent under retry.

### Cursors must not advance past failed work

If archive verification or an API call failed, advancing the cursor means the
next run starts after that range and the failure can never be retried — and
with a 48h deletion window, never is literal. Hold the cursor and report it.

## Fail-closed branches

Each of these was a live path that could delete messages the owner had not
seen:

- **Lookup failure vs "not a forum."** Swallowing every exception and returning
  an empty list makes a transient API error indistinguishable from a plain
  group, fabricating `read_max=0 / unread=0`, which reads as "all read".
  Distinguish three cases: `CHAT_NOT_FORUM` → use chat-level read state; any
  other error → skip the chat entirely; success → use topic state.
  _Then check the fix:_ an over-broad "raise on every failure" makes genuine
  non-forum groups unreachable, so the fallback you just added never runs.
- **Owner replies.** A `replied_to` set computed for escalation but not applied
  to the deletion path leaves the owner's own reply pointing at a deleted
  message. Filter `protected = pinned | replied_to` **before** classification so
  it covers every downstream path, not just the one you were thinking about.
- **Dry-run writing state.** Gating cursor writes on `apply` but leaving
  `observe()`/`ack()` ungated lets a default dry-run permanently mark alarms
  acknowledged.

## Review lesson

Two independent bots flagged the same P1 (batch-local escalation). **Convergence
between independent reviewers is a strong signal the finding is real** — worth
acting on immediately, where a finding only one raises deserves a fixture test
first.

Equally: **re-verify every re-posted comment against the code at HEAD.** Review
bots re-anchor old comments to new line numbers after each push, and several
"findings" in round two were already fixed. Grep the current file before
re-fixing anything.

And expect round two to contain **regressions from round one**. Two of three
new findings were bugs introduced by the previous round's fixes. A second
review round on a safety-critical change is not optional.
