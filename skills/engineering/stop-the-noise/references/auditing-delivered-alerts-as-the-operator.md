# Auditing Delivered Alerts As The Operator

The task class: the owner says some version of _"I keep looking at these cron
messages and telling you fix this or silence this. I've done it fifty times in
five days. You do that work instead."_

This is **not** the same as measuring noise volume
(`measuring-noise-before-fixing-it`, which counts and classifies) and not the
same as building a suppression contract (the main SKILL.md). It is
**adjudication**: read what was actually delivered to a human, one card at a
time, and answer two questions per card.

1. Did this deserve to interrupt them at all?
2. If yes, was the **urgency label** right?

Question 2 is the one that carries consequences. An owner who is told something
is CRITICAL and disagrees does not just discount that card — they discount the
channel. Getting urgency wrong is more expensive than getting volume wrong.

---

## 1. Confirm whose eyes you are using, and say so

Before any analysis, prove the session is the **operator's own account**, not a
bot that happens to be in the same rooms. A bot sees a different subset of a
forum, cannot read the human's per-topic read watermarks, and will silently
produce an audit of the wrong thing.

```python
me = client.get_me()
# assert: is_bot is False, and the id/username is the OWNER's
print(me.first_name, me.username, me.id, "is_bot:", me.bot)
```

Report the identity in the answer. The owner asked to know that you are seeing
what they see; a claim of "I checked Telegram" without an identity line is
unverifiable and invites exactly the doubt the audit exists to remove.

Also print the dialog list. If the account cannot see a room the fleet posts
into, the audit has a hole and the hole must be named.

---

## 2. Capture per TOPIC, not per group

Agent rooms are forum supergroups. `iter_messages(group)` returns every topic
interleaved, and a message's topic is only recoverable from
`reply_to.reply_to_top_id` / `reply_to_msg_id`.

A first-pass probe that counts messages per _group_ can report `87 messages in
Ken[Bot] & the operator` while being **unable to say whether any of them were cron
cards or ordinary conversation**. That number feels like evidence and is not.

```python
r = client(functions.messages.GetForumTopicsRequest(
    peer=entity, offset_date=None, offset_id=0, offset_topic=0, limit=100))
topics = {t.id: {"title": t.title, "read_upto": t.read_inbox_max_id}
          for t in r.topics}
```

`GetForumTopicsRequest` takes `peer=` and lives under `functions.messages`.
Requires telethon >= 1.44; 1.43 aborts mid-iteration on some topics.

**Capture full bodies, not counts.** The entire deliverable is a judgement about
content. A count cannot tell you whether a card earned its severity.

Bot API rich messages keep their text in `rich_message.blocks[]` rather than
`.message`, and the affected subset is biased toward conclusions — exactly the
messages the audit cares about. Extract both or the audit under-samples the
important cards.

---

## 3. Identify automated traffic STRUCTURALLY

Do not grep for alarm words to find cron cards — that is the same regex-severity
error the parent skill warns about, applied one layer earlier.

Scheduled deliveries carry a scheduler envelope. Match on that:

```python
CRON_MARKERS = ("cronjob response", "job_id:", "cron '",
                "to stop or manage this job", "script exited with code")

def is_cron(m):
    return m["is_bot"] and any(k in m["text"].lower() for k in CRON_MARKERS)
```

Measured on one fleet: **230 cron cards inside 2,469 total messages over 5
days**. Auditing all 2,469 would have buried the signal in conversation.

---

## 4. Group by CONDITION so each recurring card is judged once

Normalize away volatile detail, then group. Regex is legitimate here: it is
extracting known-shape tokens, not deciding meaning.

```python
def condition_key(t):
    t = re.sub(r"\d{4}-\d{2}-\d{2}[T ]?[\d:.]*Z?", "<ts>", t)
    t = re.sub(r"\$-?[\d,]+(\.\d+)?", "<money>", t)
    t = re.sub(r"\b\d+(\.\d+)?\s*(s|ms|m|h)\b", "<dur>", t)
    t = re.sub(r"\b[0-9a-f]{6,40}\b", "<hash>", t)
    t = re.sub(r"\d+", "<n>", t)
    return re.sub(r"\s+", " ", t).strip()[:220]
```

Then sort by repeat count. The top of that list _is_ the owner's complaint.

---

## 5. The read watermark is the muting evidence

`ForumTopic.read_inbox_max_id` gives, per topic, the last message the owner
actually read. Comparing each card's `id` against it converts "I think this is
noisy" into a measurement.

Read through the **owner's own session**, `UserStatus` always reports Online
(that session _is_ them), so presence proves nothing. The read watermark is the
only trustworthy has-the-human-seen-it signal.

What matters is not the global unread rate but its **concentration**. Measured:

```
26 unread of 230 cron cards overall  — looks fine
  Ken[Bot]  15 unread / 69   ← the two noisiest
  an owner   9 unread / 59   ← rooms hold 24 of the 26
  the operations agent      0 unread / 28
  a monitoring agent      0 unread / 8
```

The owner had started skipping precisely the channels that shout most. That is
alarm fatigue, measured, and it is the strongest possible argument for the fix.

---

## 6. Adjudication tests that actually discriminate

### Identical internal state, hours apart

Repeated alarms are ambiguous — either a live unacknowledged fault (do NOT
suppress, see the parent skill's "Wrong #1") or a re-detected transient. The
**internal numbers** disambiguate:

```
13:56  ticks=3  stale=0.8min
13:58  ticks=3  stale=2.8min
14:56  ticks=3  stale=0.8min     ← byte-identical state, one hour later
15:56  ticks=3  stale=0.8min
```

A genuinely worsening fault has _moving_ numbers. State that resets to the same
starting values at the top of each hour is either being re-detected from
scratch or nobody has acted for hours. Both need saying; neither is served by
six identical CRITICAL pages.

### Zero decision content

Some cards contain no decision at all:

```
[lane-scan] spread: total 274s
```

A duration. Nothing to do, nothing changed, no branch the owner could take —
and it interrupted them 17 times. Apply the parent skill's gate: _does this
change what they would DO?_ Pure telemetry belongs in a ledger or a dashboard.

### Urgency inflation, counted

Count how many cards claim the top label versus how many earn it under the
four-condition CRITICAL test. Measured: **28 of 230 used CRITICAL framing; 2
were judged to have earned it.** That ratio is the headline finding — say it
plainly rather than describing cards one at a time.

### Verify the claim before repeating it

A card saying `🛑 CRITICAL — this job moves real money` may be reporting a
routine no-op. Trace the underlying run before agreeing with its own label. One
audited pair of CRITICAL money pages resolved to a single market with
insufficient depth to place a clip — correct behaviour, no order placed, next
run clean.

---

## 7. Audit your own monitor in the same pass

Include the monitoring job you just built in the scan. In one audit the new
watch job appeared in the CRITICAL-framing list on its very first run.

That is not automatically a defect — it may have correctly reported a real
problem — but it must be adjudicated by the same standard as everything else,
and stating that you checked your own output is what makes the audit credible.

**Monitor cadence must be shorter than the blast interval of what it watches.**
A 4-hour watch cannot catch two false money pages that arrive 15 minutes apart.
When the audit reveals that mismatch, surface it and propose the tighter
cadence for the money-bearing profiles rather than leaving the gap implicit.

---

## 8. Report shape

The owner has been doing this triage manually and does not want it narrated
back. Lead with the adjudication, not the methodology:

1. **Identity line** — whose account, is_bot, how many rooms.
2. **The worst live case**, quoted, with the verdict and why.
3. **The ratio** — N cards used the top label, M earned it.
4. **The muting evidence** — unread concentration by room.
5. **What you will change**, concretely, per offending job.

State honestly where automation does _not_ yet cover this. If self-repair is
shadow-only, nothing is healing itself, and claiming otherwise because the
machinery exists is the same category error as counting-without-suppressing.

---

## Checklist

- [ ] Identity proven and reported: operator's account, `is_bot: False`.
- [ ] Any room the fleet posts into that the session cannot see is named.
- [ ] Captured per topic, with full bodies, including `rich_message.blocks[]`.
- [ ] Automated traffic identified by envelope structure, never alarm words.
- [ ] Grouped by normalized condition; recurring conditions judged once each.
- [ ] Read watermarks pulled; unread reported by CONCENTRATION, not just total.
- [ ] Repeated alarms disambiguated by whether internal state MOVES.
- [ ] Top-label claims counted against the ones that earn it.
- [ ] Each severity verdict traced to the underlying run, not the card's label.
- [ ] Your own monitoring job included in the audit and its cadence checked
      against the interval of what it watches.
