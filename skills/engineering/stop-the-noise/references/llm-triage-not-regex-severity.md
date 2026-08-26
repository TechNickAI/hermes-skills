# Severity is a JUDGEMENT — use the model, not a regex

Governs: **anything that decides what a human SEES**. Severity, priority, "does this
matter", "is this the same issue", "should I interrupt them". If the answer depends on
what the text _means_, a pattern cannot produce it.

Derived from the 2026-08-23 session, after three escalating corrections ending in:

> "You are doing too much with python, and not THINKING enough."
> "I don't want you in these channels just making more work for me."
> The owner's correction was emphatic: stop string-matching and use the model.

The rollup tool was already built, tested, and live. The classifier underneath it was a
regex. It had never read a single message.

---

## 1. What regex severity actually produced

Measured on live channels, all four wrong in a way no test caught because the tests
asserted the regex did what the regex said:

| Family                        | Regex verdict           | What the text actually said                                                  |
| ----------------------------- | ----------------------- | ---------------------------------------------------------------------------- |
| a trading agent Sentinel, 61× | 🔥 CRITICAL, **pinned** | `"SEV-2 resolved — no money loss or excess exposure"` — good news            |
| Position monitor, 126×        | 🔥 CRITICAL             | `cash $1047.89 \| 14 positions \| realized -$18.34` — routine balance report |
| Protect job, 86×              | "warning"               | Genuinely failing, **one position left unprotected**                         |
| 288 source messages           | reacted 🔥/⚡           | Wrong on every one                                                           |

The pattern matched scary **words**. It fired on `CRITICAL` inside `"SEV-2 resolved"` and
missed a real outage whose text never used an alarm word. It cannot distinguish an
incident from its own resolution notice, because those two things differ only in meaning.

The tell that this had gone wrong was not a failing test. It was the owner opening the
channel and seeing a fire emoji pinned to good news.

**Sibling task:** this file is about a TOOL that grades messages as it delivers them.
When the owner instead asks _you_ to go read what was already delivered and adjudicate
it on their behalf, see
`references/auditing-delivered-alerts-as-the-operator.md` — same judgement standard,
applied retrospectively through the owner's own account, with read watermarks as the
alarm-fatigue evidence.

---

## 2. Grade by reading, and act on the grade

Four grades, because "severity 1-5" invites the model to hedge into the middle:

| Grade      | Means                                      | Channel behavior                  |
| ---------- | ------------------------------------------ | --------------------------------- |
| `act`      | Broken or losing money, will NOT self-heal | Card + 🔥 reaction + pin          |
| `watch`    | Degraded/intermittent, not urgent          | Card + ⚡ reaction, no pin        |
| `fyi`      | Routine reports, balances, heartbeats      | **No card, no reaction, nothing** |
| `resolved` | The message says it was already handled    | **Card deleted**                  |

`fyi` and `resolved` producing _nothing_ is the whole point. A tool that renders every
family is a flood with better typography.

System prompt that worked, kept short and rule-shaped:

```
Judge what the text MEANS, not which scary words it contains.
"SEV-2 resolved, no money loss" is `resolved`, never `act`.
A recurring balance/position report is `fyi` even at 200 repeats.
Repetition is not severity: a routine report repeating 200 times is still
routine; a FAILURE repeating 200 times means it never self-healed.
Be strict about `act` — it must be worth interrupting a person for.

Reply with STRICT JSON only:
{"grade":"act|watch|fyi|resolved",
 "headline":"<= 12 words, what is actually happening",
 "why":"one sentence of evidence from the text",
 "action":"<= 15 words: concrete next step, or null"}
```

Feed it 4 recent samples per family. Re-grade on first sight and when the family has grown
~50% since the last read — a stable family does not need re-reading every sweep.

**Cost is not the constraint.** ~25 families re-graded on change came to a few cents a day.
Any argument for regex on cost grounds is answering a question nobody asked.

---

## 3. The card must LEAD with the reading

Before — a count, and an implicit demand that the owner go do the triage:

```
🔥 Position Manager — Favorite Grinder entry — 204× in 8d
   unacknowledged
```

After — the headline is the news, the count is supporting evidence:

```
🔥 Trading position entry job has failed every run for 8 days
   Position Manager — Favorite Grinder entry · 204× · needs you
   Exits code 3 on trading.<internal-domain>; never self-healed since Aug 15.
   Next: Check the position-manager entry script on trading
```

**Related and non-negotiable: kill the re-escalation ping.** A message saying
`"still unacknowledged — 204×, 8d"` adds zero information and demands the owner read 204
messages. The answer was in the text the whole time. If the tool has read the family, it
must say what it found; if it has not, it has no business pinging.

> "I don't want you in these channels just making more work for me."

---

## 4. Reading surfaces problems the regex buried

Once graded by meaning, five real faults came out of the same pile the regex had flattened
into undifferentiated noise:

- Risk guard cron broken 2 days — **positions unmonitored**
- Agent session database corrupted, scheduled jobs failing
- Trading cron running from a **retired code tree**
- Held positions repeatedly lacking stop protection
- Auto-sell erroring nonstop for two days

This is the actual argument for LLM triage. Not that it is tidier — that a pattern-matcher
**hides real outages** by scoring them the same as balance reports.

---

## 5. Do not eat your own output

77 rows in the state DB turned out to be the tool's **own cards**, re-ingested as agent
messages on the next sweep, forming families like `🔥 fleet-smart-watchdog — 14× in 6d`.

Exclude the bot's own card message ids at the read layer. Any tool that writes into the
surface it scans needs this check on day one, or it slowly builds a hall of mirrors.

---

## 6. Reactions on SOURCE messages — the transcript is what gets scrolled

A card says a family repeated 192 times. It does not help while scrolling 200
near-identical lines looking for the one that matters. React on the **original messages**:
🔥 on `act`, ⚡ on `watch`, nothing on `fyi`.

Two properties, both probed live:

- **Reactions have NO 48-hour limit** (deletes do). The entire backlog can be marked.
- **A bot may react to any message in a room it belongs to** — including messages it did
  not author, **including a human's**.

That second one is a boundary to close, not a feature to keep. Record `author` on every
observed message and filter `author = that room's bot id`. Fail closed when the bot id is
unknown. Verified: 0 non-bot messages marked.

When a family is re-graded down to `fyi`/`resolved`, **strip the reactions you already
applied** (`reaction=[]`) and delete the card. A verdict that changes must un-do its own
prior output, or the channel keeps the fire emoji forever.

---

## 7. Silent-pass failures — the recurring shape

Three separate bugs this session, all the same shape: **a pass reports success while
processing almost nothing.**

1. **Cursor-gated work.** Grading (and later source-marking) lived inside the
   per-message loop, which only runs for topics with NEW messages. Settled families were
   never read — **2 of 25 graded**, `errors: []`. Anything that must cover _all_ records
   belongs in its **own pass**, not inside the incremental loop.
2. **Budget starvation.** Ordering candidates by `count DESC` let big families consume the
   per-sweep budget on re-grades, so 4 families were **never graded at all** and showed
   blank headlines indefinitely. Order **never-processed first**:
   `ORDER BY (grade IS NOT NULL), count DESC`.
3. **Truncated model reply.** One `why` field overran `max_tokens`; the partial JSON failed
   to parse and triage returned `None` **silently**, stranding a family for 3 sweeps. Raise
   the ceiling AND salvage partial replies with per-field regex before giving up.

**The detection rule: when a pass reports success but its output count is implausibly low
against what should have been processed, the pass is broken.** `graded: 2` on 25 families
is a bug, not a quiet day. Print the denominator.

Same class as the dry-run leak: `--dry-run` wrote real reactions and recorded them done, so
the real apply found nothing left. A dry run must count what it _would_ do and touch no
state.

---

## 8. Locking must live where every entry point passes

A shell-wrapper lock guarded manual runs against each other, but the **cron job invokes the
script directly** and bypassed it — two clients opened the shared telethon session and hit
`database is locked` mid-connect.

Put the lock **inside the script** (atomic `mkdir` + stale takeover; macOS has no
`flock(1)`), so the scheduler, the wrapper, and a human all serialize on the same gate.

---

## Checklist

- [ ] Severity/priority decided by a model that READ the text, not a pattern.
- [ ] `fyi` and `resolved` produce NOTHING — no card, no reaction, no ping.
- [ ] Card leads with the headline; raw title and count demoted to a subline.
- [ ] No "still unacknowledged, N×" pings — say what was found or say nothing.
- [ ] Re-grade un-does prior output (card deleted, reactions stripped).
- [ ] The tool's own messages excluded from its own scan.
- [ ] Reactions filtered to `author = room's bot id`; fails closed; verified 0 human marks.
- [ ] Every full-coverage pass is its OWN pass, not inside the cursor-gated loop.
- [ ] Never-processed records ordered FIRST so a budget cannot starve them forever.
- [ ] Model-reply parse failures salvage partial output instead of silently returning None.
- [ ] Dry run counts without writing state.
- [ ] Output count checked against the denominator; an implausibly low count is a bug.
- [ ] Lock lives inside the script so cron and wrapper share one gate.
