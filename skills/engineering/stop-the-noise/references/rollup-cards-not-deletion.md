# Channel volume: AGGREGATE into a card, do not delete

Governs: **owner says "I don't want to see all 95 of these"**. Read this BEFORE
`post-hoc-channel-cleanup.md` — that one is about removing messages, and removal is
almost never what the owner is asking for.

Derived from the 2026-08-21/22 session where two successive builds were rejected before
the third was accepted.

---

## 1. The correction that cost two rebuilds

The owner's literal words:

> "If I go into a message and there's 95 messages about the same thing, I don't want to
> see all 95. I want to see, _'Hey, there were 95 of these messages, the operator. You might want
> to look at this.'_"

That is **aggregation with a survivor that states the count**. It is not deletion.

The first build shipped an ephemera deleter (progress bubbles, terminal echoes) behind an
allowlist. The owner's response was blunt: those are already removed as part of the
[other] skill that does cleanup of interim messages. So no, no, no, turn that off."\*

**Two lessons, both general:**

- **Check what already handles this class before building.** A separate cleanup skill
  already removed interim messages. Building a second, dumber copy of that logic is how
  two systems end up disagreeing about the same messages.
- **When an owner describes a symptom with a number in it ("95 messages"), the number is
  the spec.** The deliverable is a thing that says "95", not a thing that makes 95
  messages disappear.

---

## 2. Telegram actually has a collapse primitive

`<blockquote expandable>` (Bot API 7.3+, entity type `expandable_blockquote`) renders
collapsed to ~3 lines with tap-to-expand. This is the platform's real answer to "can
Telegram collapse messages" — verified live, not from docs.

```
🔥 <b>Favorite Grinder entry</b> — <b>191×</b> in 7d
<i>Aug 15 04:25 → Aug 21 22:51 · unacknowledged</i>
<blockquote expandable>08-21 22:51  …
08-21 22:36  …
… and 41 earlier</blockquote>
```

**Measured limits:**

| Fact                                                  | Value                                           |
| ----------------------------------------------------- | ----------------------------------------------- |
| Message cap                                           | 4096 chars (`Bad Request: message is too long`) |
| 95 _verbose_ lines (~68 chars)                        | 6,418 chars → **rejected**                      |
| 95 _compact_ lines (`08-21 14:07 order 8931 refused`) | 3,023 chars → fine                              |

So render occurrences compactly, cap at a safe ~3600 chars for HTML-entity headroom, and
append `… and N earlier`. Do not paginate to an external archive — the whole point is not
sending the owner somewhere else.

---

## 3. Probe the interaction surface; do not assume it

Everything below was probed live against a real chat. Several assumptions were wrong.

| Capability                    | Result                                                               |
| ----------------------------- | -------------------------------------------------------------------- |
| `editMessageText` on the card | ✅ count updates in place, **no new notification**                   |
| `pinChatMessage`              | ✅ multiple pins coexist per topic                                   |
| Inline keyboard buttons       | ✅ — this is what closes the ack loop                                |
| `setMessageReaction`          | ✅ but **exactly one** emoji; `max_reaction_count: 11`               |
| Valid reactions (probed 53)   | `👍 👎 ❤ 🔥 🎉 😁 🤔 🤯 😱 🤬 😢 💯 ⚡ 🍌 🏆 💔 🤨 😐 🍓 💋`        |
| **Invalid** (33 rejected)     | `👀 ✅ 🥳 😴 🤝 🫡 🆒 😍 …` — `REACTION_INVALID`                     |
| `getForumTopicIconStickers`   | 112 icons; **no `🔴 🟡 🟢 ⚠️ 🚨`** — no traffic-light scheme         |
| Bot reads history             | ❌ impossible — `getForumTopics`/`getChatHistory` return `Not Found` |

`✅` is valid as a forum-topic _icon_ but rejected as a _reaction_ — different sets.
Never carry an emoji assumption across surfaces.

**Buttons are the highest-leverage element** — but only if one of them _does something_.

A guard failure repeated 29 times because acknowledging required typing a reply, so the
first build shipped `[👍 Ack] [💤 Snooze 4h] [🔕 Mute 7d]`. That was rejected:

> "On the first one, ack, snooze four hours, and mute seven days. That's somewhat helpful,
> but how about a button that says **'fix it'**? I don't need snooze and mute, we just want
> one. I think completely reconsider what these actual choices are. A 'fix it' button would
> be genuinely useful."

**All three buttons were flavours of "make this go away."** None advanced the work. A card
exists because something is repeatedly wrong; the primary action must be to _act on it_.

Shipped shape:

| Button         | Does                                                                                                                                                                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **🔧 Fix it**  | Posts a real task into the topic addressed to the agent that owns the room, carrying count, span, and recent occurrences, with an explicit "find the root cause and fix it; if you cannot, say what is blocking you — do not simply acknowledge" |
| **🧿 Explain** | Asks the same agent for a short plain-language answer: what is it, why is it repeating, does it matter, what would you do                                                                                                                        |
| **✓ Dismiss**  | The single quiet option, replacing Ack + Snooze + Mute                                                                                                                                                                                           |
| **↩ Reopen**  | Shown after dismiss/handoff — the quiet action is always reversible                                                                                                                                                                              |

**General rule: one dismissal affordance, not three.** Snooze and mute are the same verb at
different durations; shipping both plus Ack is a menu of ways to avoid the problem. Spend
the button real estate on the action that closes the loop instead. The agent already lives
in that room — handing it the work is one `sendMessage`, not an integration.

---

## 4. DO NOT RENAME FORUM TOPICS

Ambient status in the topic name (`🔥 a trading agent — 2 need you`) reads well in a design doc and
was explicitly killed in production:

> "I also now see a bunch of places where you are changing the topic, and you're abusing
> that, it's going to get annoying real fast... And right now, it looks like there's a bug
> where you're changing the topic to the exact same topic... The topic renaming thing is
> annoying as fuck."

What went wrong, and why it is structural rather than a fixable bug:

- The suffix re-applied on **every sweep** and churned on trivial state changes
  (13 renames on a dry run, 28 more on apply).
- The strip-then-reapply regex could not round-trip cleanly, so it rewrote names to the
  same value repeatedly.
- It mangled names that already read like status: a topic the human had named
  `Needs the operator` became `Needs the operator — 1 changed`.
- A topic name is **shared furniture the human chose**. In a room with other people it is
  not yours to rewrite at all.

**Rule: the rollup card carries the state; the topic name does not.** Delete the rename
code rather than config-flagging it, or a future session will re-enable it. If it is ever
genuinely wanted, it needs an explicit ask, a rate ceiling, and idempotent round-tripping.

When reverting: enumerate the polluted names via `GetForumTopicsRequest`, restore each
with `editForumTopic`, then **re-verify the count is zero** rather than trusting the loop.

---

## 4.5 Never roll up a LIVE agent's interim output

The second rejection of the accepted build. 30 of the first 50 cards were families like
`terminal — 12×`, `⏩ Steered into current run — 10×`, `⏳ Queued for the next turn — 31×`,
`✍️ Writing … — 10×`.

> "On the other one where you're rolling up the terminal messages, what this is doing is
> you are **interfering with an active agent that is doing incremental job progress**.
> That's already cleaned up, by the way, by how we clean up interim messages. That's not
> useful at all."

Two independent reasons this is wrong, and both generalise:

1. **It is already someone else's job.** The interim-message cleanup owns this class. This
   is the _same_ mistake as the first rejected build (§1) arriving through a different
   door — the first one deleted ephemera directly, this one aggregated it. Checking "does
   something already handle this class" has to be re-asked for every message class the
   tool touches, not once at the start.
2. **A live turn's progress is not a recurring fault.** `terminal — 12×` describes an agent
   doing its job right now. Aggregating it tells the owner nothing and buries the fact
   that real work was in flight.

Exclude at the **read layer**, before fingerprinting, so it can never reach a card:

```python
INTERIM = re.compile(
    r"^\s*[\U0001F4BB\U0001F40D\U0001F527\u270D\u270F\U0001F4DD\u2699\U0001F4BE"
    r"\u23F3\u23E9\U0001F50D\U0001F4D6\U0001F310]"
    r"|^\s*(?:terminal|Running code|Writing|Editing|Reading|Searching)\b"
    r"|Steered into current run|Queued for the next turn",
    re.IGNORECASE,
)
```

**Rollup applies to completed, recurring, machine-emitted OUTCOMES** — cron results,
monitor verdicts, guard failures. Not to the narration of an in-flight turn.

When cleaning up cards that should never have existed, delete them via each room's own bot
token, `NULL` the `card_id` in state so the next sweep does not think they still exist, and
re-count the survivors rather than trusting the loop's own tally.

---

## 5. Fingerprinting: find the stable identity in the payload

The clustering rule is the mechanism everything depends on, and a plausible one was
wrong in a way that its own evidence table exposed.

Naive `re.sub(r'\d','#', text.lower())` reported these as two families:

```
Grinder position monitor   38×
GRINDER position monitor   36×
```

Same job. The prose drifted; digit-masking destroyed the `job_id` that would have merged
them. **Corrected: extract the stable identifier first, fall back to normalized prose.**

```python
JOB_ID = re.compile(r"job_id:\s*([0-9a-f]{6,})", re.I)
def fingerprint(text):
    m = JOB_ID.search(text or "")
    if m:
        return "job:" + m.group(1).lower()
    s = re.sub(r"\s+", " ", (text or "").lower()).strip()
    s = re.sub(r"\d+", "#", s)
    s = re.sub(r"[0-9a-f]{8,}", "#", s)
    return "txt:" + hashlib.sha256(s[:180].encode()).hexdigest()[:24]
```

Re-measured, the true top family was **191×, not 54×**.

**General rule:** before shipping a fingerprint, find two messages you _know_ are the same
event and assert they merge, plus two you know are different and assert they do not. A
count that looks plausible is not evidence the grouping is right.

---

## 6. Tune the threshold from data — the cards can become the flood

One card per family sounds harmless until you count the families.

| Min count | Cards   | Messages covered |
| --------- | ------- | ---------------- |
| **N=3**   | **208** | 1,945            |
| N=5       | 114     | 1,627            |
| **N=8**   | **50**  | 1,258            |
| N=10      | 45      | 1,217            |

At N=3, 94 families of only 3–4 messages produced 45% of the cards while covering 16% of
the volume. **208 new pinned cards is a worse flood than the one being fixed.** N=8 keeps
nearly all the coverage at a quarter of the cards.

Always print this distribution and pick the knee. Do not pick a threshold by taste.

---

## 7. Flood control is per-chat and it WILL bite

Measured on one card in one chat:

| Test                         | Result                                          |
| ---------------------------- | ----------------------------------------------- |
| 45 unpaced `editMessageText` | **429 after 35**, `retry_after: 37` — 10 failed |
| 30 edits paced at 1.1s       | **30/30 clean**                                 |

Flood control is keyed on `chat_id`, and **every forum topic in a room shares one
budget** — 40 topics do not get 40 budgets. Unpaced, a multi-family sweep locks the whole
room out for ~37 seconds.

- Global token bucket per `chat_id`, ~1 edit/sec, shared across topics.
- On 429, honour `retry_after` and requeue.
- **Never fall back to `sendMessage` on a 429** — that recreates the exact flood the tool
  exists to remove.
- Coalesce: one edit per card per sweep, never one per occurrence.

---

## 8. The industry model: dedup ≠ grouping

Every mature tool converged on the same shape, and none of them delete:

- **Sentry** — events are fingerprinted into an _issue_ carrying count, first-seen,
  last-seen. Individual events live _inside_ it.
- **PagerDuty / Opsgenie / Rootly** — source-level **dedup** collapses the same monitor
  re-firing; **grouping** joins _different_ monitors on one incident into a single page.
  "The first matching alert pages on-call; subsequent matching alerts join silently."
- **LangChain Agent Inbox** — human-in-the-loop items as outcomes with accept / edit /
  respond / ignore.

Common core: **one durable object per recurring thing, carrying a count and a state,
updated in place.**

Building only the dedup half is the easy mistake: three alert families firing in the same
window are usually one incident wearing three templates, and the owner gets three cards
instead of one storm signal.

---

## 9. Notification state machine — write it as a table, not prose

"Edited in place so it never notifies" and "critical pages immediately at night" are
contradictory as prose, because **edits do not push**. Specify transitions:

| Transition                           | Action                                                   |
| ------------------------------------ | -------------------------------------------------------- |
| New family appears                   | ONE notifying send                                       |
| Repeat occurrence                    | silent edit (`disable_notification=True`)                |
| Unacked + crosses re-escalation tier | ONE fresh notifying "still waiting", then silent         |
| Acked                                | edit card, set reaction, unpin                           |
| Quiet hours                          | non-critical holds; critical-unacked pages on transition |

---

## 10. Multiplayer rules — the room is not single-player

A review lens roleplaying the other humans in the rooms returned: _"You have designed a
single-player IT ticketing system and dropped it into multiplayer spaces."_ Each of these
is a defect, not a nicety:

- **Never LLM-digest human-authored text.** Sweeping a person's own words into "X and the
  agents discussed weekend plans" is that person losing their own conversation.
- **Never digest structured data** — code blocks, ledgers, trade payloads bypass any
  summarizer and stay raw. Exact timestamps and amounts are the reason they exist.
- **Quiet hours resolve to the ROOM's timezone**, never the operator's. A hardcoded
  21:00 Austin window silences a Seattle user's assistant at 19:00 local.
- **Check quiet hours against each agent's real working window.** One agent legitimately
  works 01:00–08:00 local — _entirely inside_ a normal quiet window. Blanket quiet hours
  would have muted the busiest agent during its actual job. Disable per-room where the
  window collides.
- **Attribute every action**: `👍 Acked by <name>`, never a silent state flip. Otherwise
  one person clears their own screen and the owner never learns the subsystem threw errors.
- **Authorize the button now, not later** — check `callback_query.from.id` against a
  per-room allowlist and answer an unauthorized tap _visibly_. Silently eating it reads as
  a broken bot. It is a no-op in single-owner rooms, but retrofitting permissions onto
  shipped button semantics diverges behavior.
- **Ack must be reversible.** Mute has a recovery path; ack needs one too.
- **The bot pins only what it authored**, one pin per topic, and never touches a human's pin.
- **The bot never reads human-applied reactions** — state that as its own invariant so
  reacting normally in the room is always safe.
- **Plain language, not PagerDuty**: `Dismiss`, not `Ack`, in any room with a
  non-technical occupant.

---

## 11. Report honest numbers

A committed target of "4,344 → ~800/week" was challenged and did not survive: only the
rollup segment had been computed; the rest was asserted, and three of five rooms had no
baseline at all.

Split committed numbers by basis — **measured** vs **not yet built** — and refuse to state
a fleet-wide figure until the unbuilt part has run on real traffic.

---

## Checklist

- [ ] Confirmed no existing tool already handles this class before building.
- [ ] Re-asked that question for EVERY message class the tool touches, not just once.
- [ ] Live-agent interim/progress output excluded at the read layer, before fingerprinting.
- [ ] Deliverable states the count; it does not just remove messages.
- [ ] At least one button ACTS (fix/explain); only ONE dismissal affordance, and it is reversible.
- [ ] Fingerprint asserted in both directions on real known-same/known-different pairs.
- [ ] Threshold picked from a printed distribution, not taste.
- [ ] Card renders under 4096 chars with worst-case occurrence count.
- [ ] Edits paced ≥1.1s per chat; 429 honoured; never falls back to send.
- [ ] Notification transitions written as a table.
- [ ] No forum-topic renaming.
- [ ] Per-room timezone; quiet hours checked against each agent's real working window.
- [ ] Actions attributed and authorized; ack reversible.
- [ ] Numbers reported split by measured vs asserted.
