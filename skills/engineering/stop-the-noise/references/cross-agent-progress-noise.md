# Cross-agent progress noise: when your chatter wakes someone else's agent

A third-party noise class, distinct from the two in the SKILL.md table. Here the
messages are not spam _to a human_ — they are inbound _events to a peer agent_, and
each one burns a full agent turn on a machine you may not own.

Verified live 2026-08-15 in a shared support room (the operations agent posting, a personal-assistant agent waking).

## Symptom

Two agents share a Telegram room. One is working a task and emitting visible
tool-progress lines ("📚 Reading skill …", "⏳ Working — 3 min — terminal"). The other
is configured mention-only and starts replying anyway, to nobody. From the human's
seat it looks like the two bots are talking to each other.

The owner's complaint arrives as a behavior problem ("you don't have the proper
response settings"), which points the investigation at the _responding_ agent's
`require_mention`. That is usually correct and is not the bug.

## Mechanism: two gates, both must be closed

**Gate 1 — response (Telegram adapter).** `_is_reply_to_bot()`
(`plugins/platforms/telegram/adapter.py:8515`, consulted at :9233) returns True as an
accept, AFTER the mention check:

```python
if self._is_reply_to_bot(message):
    return True
```

Progress messages land reply-anchored to the thread root, so the peer sees each one
as a reply to itself. `require_mention: true` does not cover this path.

**Gate 2 — authorization (`gateway/authz_mixin.py`).** `group_allowed_chats` /
`TELEGRAM_GROUP_ALLOWED_CHATS` is a **chat-scoped grant evaluated before the bot
check and before the no-user-id guard** (~:480-495). It authorizes _any sender in the
room_, bots included. `{PLATFORM}_ALLOW_BOTS` at :507 never gets a vote, because the
chat-scope grant already returned True above it — so `TELEGRAM_ALLOW_BOTS=none` (the
default) is not the protection it looks like.

## Diagnose from the receiver's log

Config reads innocent on both sides in this failure mode. Prove it from traffic:

```bash
grep -h "inbound message.*chat=<CHAT_ID>" ~/.hermes/logs/agent.log* \
  | grep -o "user=[^ ]* [^ ]*" | sort | uniq -c | sort -rn
```

A peer agent's display name in the `user=` column is the finding. Confirm each is
followed by a `response ready` for the same chat — that pairing proves turns are
being spent, not just messages observed.

## Fix both halves

**Receiver (stops the loop).** Remove the shared room from the chat-scope grant in
BOTH places; the env var silently outranks the YAML, so one alone leaves it open:

1. `telegram.group_allowed_chats` in `config.yaml`
2. `TELEGRAM_GROUP_ALLOWED_CHATS` in `.env`

Check `TELEGRAM_GROUP_ALLOWED_USERS` **before** removing the chat grant — it is a
separate per-user path, and the room's human owners must be listed there or the fix
locks them out of their own support channel. Leave `allowed_chats` alone; removing it
makes the agent deaf to the room instead of mention-only.

`.env` changes need a gateway restart; confirm a new pid and a clean
`Connected to Telegram (polling mode)`.

**Source (stops the noise).** The receiver fix ends the loop but leaves the clutter in
a human's room. Disabling visible interim/tool-progress output for that platform is
the other half — see `gateway-progress-noise-per-turn.md`. In a room the agent does
not own, offer this as a question rather than shipping it unasked.

## Pitfalls

- Treating this as purely the receiver's misconfiguration. Both agents contribute;
  fixing one leaves the other half live.
- Patching `config.yaml` or `.env` but not both.
- Reaching for `TELEGRAM_ALLOW_BOTS` — already restrictive, not the door that opened.
- Dropping the chat grant without first confirming per-user grants for the humans.
- Declaring done at "the loop stopped" while the progress spam continues in a
  non-technical owner's support room.
