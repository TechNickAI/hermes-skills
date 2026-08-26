# Channel cleanup: repeated messages are alarms, not noise

Governs the class: **an owner is drowning in agent chat volume and asks for cleanup,
summarization, dedupe, roll-up, or deletion.** The obvious design — collapse repeats,
delete the copies — is backwards in the most dangerous way. Read this before building
any janitor, digest, or dedupe job against a live channel.

Derived from a fleet signal-management session (the operator/the operations agent), where the
measurement inverted the plan twice.

---

## 1. Measure the channel before designing anything

The owner's stated diagnosis is a _symptom report_, not a root cause, and it is usually
wrong about proportions. the operator opened with _"I regularly come back to see 10 failed cron
jobs spamming the channel."_

Measured reality across 11 forums, 7 days:

| Metric                                        | Measured                   |
| --------------------------------------------- | -------------------------- |
| Agent messages                                | 8,663                      |
| Cron **failure** rate                         | 5 / 4,002 runs = **0.12%** |
| Ephemeral (progress/queue/self-improve/empty) | 2,416 = 27.9%              |
| Near-duplicate substantive                    | 655 = 7.6%                 |

**Failures were 0.12% of runs.** Building error handling would have addressed almost
none of the flood. The noise was _successful_ jobs reporting success, plus per-turn UI
bubbles. Had the plan been written from the stated premise it would have shipped the
wrong system entirely.

Always produce this table first. It reframes the work and it is cheap.

### Classify by producer, not by appearance

A first pass classified messages by their **opening characters** (`💻`, `⏳`, `⏩`, `💾`).
That is fine for sizing classes, but it does **not** prove that a given config key kills
a given class. State that limitation out loud and prove attribution one variable at a
time before a fleet rollout, or the rollout is built on a correlation.

---

## 2. THE INVERSION: a message repeated N times is an unacknowledged alarm

This is the rule the whole reference exists for.

The dedupe instinct says: 54 copies of the same message is 53 messages of waste, collapse
them. **That is exactly backwards when the repeated message is a fault condition.**

Measured on a trading agent and a research agent:

- `SEV-1: Favorite Grinder halted` — reprinted **54 times over 95 hours**. The owner sent
  209 messages in that window, **none about it**. It resolved on its own.
- `GUARD CHECK FAILED (exit 2), the watched condition is unmonitored` — reprinted **29
  times over 5 days**, and was **still broken** at the time of measurement.

A dedupe-and-delete janitor would have destroyed the only standing evidence that
positions went unwatched for five days. The repetition _was the signal_ — it was the
system correctly refusing to shut up about an unresolved fault, and the human had
habituated past it.

**Rules that follow:**

- **Never delete the most recent copy of a repeating message.** Delete older copies,
  keep the newest, and attach a count.
- **Repetition count is a severity multiplier, not redundancy.** Render it:
  `🔴 SEV-1 — halted · 54th occurrence · first 08-17 18:08 · ongoing 95h · unacknowledged`
- **Escalate on age and count, not on novelty.** An alarm should get _louder_ the longer
  it goes unacknowledged. Volume-based collapse does the opposite: it makes a chronic
  fault quieter than a fresh one.
- **Track acknowledgment explicitly.** Owner replied in-thread, or the condition
  cleared → collapse to one resolved line. Never acknowledged and still firing → promote
  to a persistent surface that cannot scroll away.

**The diagnostic that finds this:** grep agent messages for fault tokens
(`SEV-1|HALT|BROKEN|FAILED|BLIND|ERROR`), then check whether the owner ever spoke in
that thread afterward. A high repeat count with zero owner response is a buried
incident, and finding one is more valuable than the cleanup job itself.

---

## 3. Deletion design: allowlist, archive, and the 48-hour wall

### Telegram's hard constraint

**Bots cannot delete messages older than 48 hours.** Server-side limit (Bot API
`deleteMessage` docs; tdlib issue #403), not a permission problem — verified even where
the bot holds `delete_messages=True` admin rights.

A **user account** has no such limit. So the architecture is forced:

- Steady-state janitor = rolling <48h window, deleting with **each agent's own bot
  credentials**. Nearly all the value lives here.
- Backlog cleanup = requires the owner's user session. Treat as a separate, explicitly
  approved, supervised operation. Do not put a human's personal account on a schedule.

**Where the job RUNS is a separate question from which credential deletes**, and the
obvious answer is wrong. A per-agent job on each agent's own host fails at rollout:
reading requires the owner's user session (bots cannot read history at all), and that
session exists on one machine. Bot tokens, however, are not host-bound — verified by
calling `getMe`/`getChat` with a remote agent's token from a different machine. So run
**one sweep centrally** that reads with the user session and deletes per-agent with each
agent's own token. See `post-hoc-channel-cleanup.md` for the config shape and the
credential-location test to apply before choosing where any fleet job runs.

Verify rights before promising anything:
`iter_participants(chat, filter=ChannelParticipantsAdmins())` exposes each admin's
`admin_rights.delete_messages`.

### Deletion is opt-in by pattern

Deletion is irreversible. Ship an **allowlist of patterns known to carry no information
by construction**, never a blocklist of "things that look unimportant":

- Tool-progress bubbles, queue/steer notices, self-improvement notes, empty/media-only.

**Never deletable, regardless of volume:** anything from a human, anything the owner
replied to, decisions/approvals/questions, error or exception output, money or trade
execution, pinned messages, and the newest copy of any repeating fault.

### Archive before delete

Write every message to a local per-profile transcript (id, sender, timestamp, full text)
and verify it is readable **before** issuing the delete. This makes deletion reversible
in _content_ even though it is irreversible in the platform. It is the difference
between a safe janitor and an unsafe one.

---

## 4. The re-entry surface: pin and edit, never post

The owner's real question is _"I often come back to the room and don't know how far to
go back."_

- **A summary that posts fresh each run becomes the noise it was built to fix.** Use ONE
  pinned message per room, **edited in place**.
- Structure: **Needs you** (open decisions) → **Changed** → **Handled** (counts only) →
  **Quiet since**.
- Pinned + edited means state is at the top regardless of absence length. No scroll
  boundary to find.

**"Since the owner's last message" is not a valid awareness boundary.** People read
without replying and use multiple devices. Use an explicit acknowledged checkpoint.

**Render a durable queue, not regenerated prose.** Open decisions need id, owner,
deadline, source, status — a brief the owner misses must not lose the decision.

---

## 5. Business hours and quiet hours

- **Deletion runs 24/7** — it is silent, so hours are irrelevant to it.
- **Summaries push only during business hours.** Overnight they update in place silently.
- Quiet hours suppress **delivery only** — never logging, never escalation.
- **Bypass list ignores quiet hours entirely:** money movement, auth failures, execution
  exceptions, exchange rejections, exposure/margin breaches, stale market data, clock
  skew, disk capacity, confirmed outages in the watched thing.
- Held non-urgent items **queue and deliver at open**. Suppressed-and-expired is how a
  real event vanishes.

---

## 6. Shared rooms: measure your own footprint

When a channel has other humans in it, audit **who is actually talking** before touching
anything.

Measured in a client's own support room, 14 days: **agent 671 messages, a second agent
280, the owner 122, the client herself 47.** The agent was the loudest voice in someone
else's room at 14x her volume.

- Volume alone does not prove the content was unwanted — sample content before claiming
  violations.
- The **conduct rule** needs no study: fleet-ops chatter does not belong in another
  person's room. An agent there speaks when spoken to, or when it has a finding that
  affects that person.
- Clean up **your own agents' clutter only**. Never another human's messages.
- No summary card into someone else's room without that owner's consent.
- Sampling other owners' rooms is for **sizing your own noise** — aggregate counts and
  class labels, not content harvested into a central store.

---

## Checklist

- [ ] Volume/failure/class table measured before any design work.
- [ ] Owner's stated diagnosis checked against measured proportions.
- [ ] Fault-token sweep run; repeat-count vs owner-response checked for buried incidents.
- [ ] Newest copy of every repeating message preserved; count attached; escalates on age.
- [ ] Acknowledgment tracked explicitly.
- [ ] Deletion allowlist-only; never-delete list enumerated.
- [ ] Archive written and verified readable before any delete.
- [ ] 48h bot limit respected; backlog sweep separated and explicitly approved.
- [ ] Re-entry surface is pinned-and-edited, not posted.
- [ ] Quiet hours gate delivery only, with an explicit bypass list.
- [ ] Shared-room footprint measured; own-clutter-only cleanup; no card without consent.
