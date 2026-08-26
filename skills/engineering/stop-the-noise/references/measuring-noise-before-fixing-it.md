# Measuring the flood before fixing it

The rest of this skill is about _mechanism_ — which knob silences which class. This file
is the phase that comes BEFORE any of that: **quantify the noise, by class, per source,
against a real baseline.** Skipping it means fixing the class the user complained about
rather than the class actually producing the volume.

Measured 2026-08-21 across an 11-forum Telegram fleet. Every number below is an output
of the method, kept as calibration for what "normal" looks like at this scale.

## Why measure first

The operator's stated cause is a hypothesis, not a diagnosis, and it is frequently the
wrong one — because failures are _memorable_ while routine success is _invisible_.

Real example: the complaint was "I come back to 10 failed cron jobs spamming the
channel." Measured failure rate across 4,002 runs was **5 — 0.12%**. The flood was
entirely **successful jobs reporting success**, plus per-turn UI ephemera. Had the fix
followed the complaint, it would have addressed ~0.1% of the volume and the operator
would have concluded the work didn't help.

**Rule: before designing suppression, compute the failure rate.** If it is low, say so
explicitly and re-aim at healthy output. This reframe is usually the single most valuable
thing the session produces, and it lands better _because_ it contradicts the brief with a
number.

## The class taxonomy

Classify every message; report volume in BOTH messages and characters. They rank
differently and the difference is the whole argument — ephemera dominate message count,
prose dominates the reading burden.

| Class            | Recognizer                                     | Fix layer                    |
| ---------------- | ---------------------------------------------- | ---------------------------- |
| `tool_progress`  | opens with a tool glyph (💻 🔧 🔍 📖 ✏️ 🌐 📝) | `display.*` config           |
| `queue_status`   | opens `⏳` / `⏩`                              | `display.*` config           |
| `cron_output`    | opens `Cronjob Response`                       | prompt `[SILENT]` contract   |
| `self_improve`   | opens `💾`                                     | `display.*` config           |
| `empty_or_media` | no text body                                   | usually benign               |
| `substantive`    | everything else                                | job scope, not suppression   |
| `OWNER`          | sender is the human                            | the denominator that matters |

Baseline observed over 7 days: 8,787 agent messages, of which 2,427 (27.6%) were pure
ephemera and 5,467 were substantive prose totaling **2.31 MB**. The owner himself sent
12.5% of traffic in his own channels.

**The owner-share metric is the one to lead with.** "You are 12.5% of your own channels"
communicates the problem faster than any absolute count.

## Honest limits of glyph classification

Classifying by opening characters is cheap and good enough to _size_ classes. It does
**not** establish which config key or which job produced a given message.

Do not claim "setting key K removes N messages" from glyph counts alone — that is
correlation dressed as causation, and a review panel will (correctly) reject it. Either
trace messages to producing job IDs, or state the projection as a hypothesis and prove it
by changing **one key at a time** against a measured before/after.

Related trap: `interim_assistant_messages` prevents creation while `cleanup_progress`
deletes after send. A send-only counter cannot distinguish them — measure both messages
_sent_ and messages _retained_.

## Weak proxies that look like measurements

- **Presence of `[SILENT]` in a prompt is not evidence a job is quiet.** A job can carry
  the token and ignore it, or lack it and never have anything to say. Force-run against a
  healthy fixture and an actionable fixture, then score real output.
- **A count of enabled jobs is not a count of talkers.** Check the delivery target;
  jobs routed to `local` produce no chat volume at all. Observed split: 118 enabled,
  92 delivering to Telegram, 26 local.

## The cross-owner check — run this every time

When any room contains a human other than the agent's primary operator, compute
**per-sender volume in that room** and compare the agent against the room's owner.

Observed: in a client's own support room, the visiting ops agent had posted **671**
messages over 14 days against the room owner's **47** — 14x her own volume, in her room.
The operator had not asked about this and did not know.

This finding is usually higher severity than the operator's own inbox, because it
degrades someone else's experience and their trust in a system they did not choose. Look
for it proactively; it never appears in the brief.

Caveat to keep honest: volume disparity proves _loudness_, not _inappropriateness_.
Content-sample before asserting that N messages were violations. The conduct rule needs
no study, though — fleet-ops chatter does not belong in another person's support room.

## Reading Telegram forums with telethon

Operational details that cost time to rediscover:

- **A bot session cannot enumerate dialogs.** `iter_dialogs` raises
  `BotMethodInvalidError`. Auditing an operator's channels requires their **user**
  session. Probe candidate `.session` files for the authorized one rather than guessing:

  ```python
  await c.connect()
  if await c.is_user_authorized():
      me = await c.get_me()          # check me.bot
  ```

- **Forum topic ID** comes off the reply header, and both fields matter:

  ```python
  rt = getattr(m, "reply_to", None)
  topic = (rt.reply_to_top_id or rt.reply_to_msg_id) if rt else 0
  ```

- **Cap iteration and break on a date cutoff**, not on limit alone — a busy forum will
  exhaust a 3,000-message cap inside the window and silently understate volume. If a
  forum hits the cap, say so; the true number is higher.
- `asyncio.get_event_loop()` is removed on modern Python. Use `asyncio.run(main())`.
- Enumerating 30 days across many forums takes minutes. Run it once, write results to a
  file, and iterate on the file.

## Counting active threads

"I don't know how far back to scroll" is a distinct complaint from volume, and it needs
its own number: **distinct topics with activity in the window.**

Observed: 99 active topics in 7 days across 8 forums (147 touched in 30 days). That
number, not the message count, is what justifies any roll-up work — and if it is small,
the roll-up is not warranted.

## Overnight / business-hours slice

Bucket agent messages into the operator's local hours before proposing quiet hours.
Some overnight volume is legitimate and expected (a trading agent working an overnight
market); moving it would break the work. Separate _movable_ from _deadline-driven_ rather
than proposing a blanket window.

## Reporting shape

Lead with the table of measured numbers, then the reframe, then the plan. The measurement
is what makes the reframe survive contact with an expert operator who is certain the
problem is something else.
