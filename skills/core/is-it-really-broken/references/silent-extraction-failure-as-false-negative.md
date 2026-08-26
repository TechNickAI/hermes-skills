# Silent extraction failure reported as a factual negative

The worst integration failure mode is not a loud error. It is a decoder, parser, or
API reader that returns _something_ — technically valid, semantically empty — which
the agent then reports to a human as a fact about the world.

A crash produces a retry. A confident wrong answer produces a lost user.

## The incident (one occasion, verified end to end)

A fleet owner asked her agent whether she had any messages with her contractor about
a foundation repair and its warranty. She had explicitly pre-instructed the agent:
_"if the integrations weren't working he needed to tell me and to not return garbage
based on broken integrations."_

The agent searched, reported **"no messages found"** with full confidence, and named
the wrong contractor as having done the work.

Ground truth, measured afterward on the same machine:

| Claim                           | Reality                                           |
| ------------------------------- | ------------------------------------------------- |
| No messages with the contractor | **1,946 messages**                                |
| Nothing about the foundation    | **16 foundation-related messages**                |
| No pricing                      | Itemized quotes: leveling pier $850, skirt $1,850 |

### Root cause

macOS `chat.db` stores almost nothing in the obvious `message.text` column —
**424,887 of 428,211 rows had `text = NULL`** on this box (99.2%). The real content
lives in `message.attributedBody`, an NSKeyedArchiver binary blob.

The extraction guidance in play recommended:

```python
re.findall(rb'[\x20-\x7e]{3,}', blob) # WRONG
```

That character class is ASCII-printable only. It silently deletes every emoji, curly
quote (`'`), accented character, and "Liked..." tapback. On an emoji-heavy personal
thread the surviving bytes are the archiver's own framing characters, so the decoded
"message" comes back as a run of `+` and stray punctuation.

The agent read that as _empty messages_, and empty messages as _no messages_.

### The two-step corruption

```
tool returns garbage -> agent interprets garbage as EMPTY
                      -> agent interprets EMPTY as ABSENT
                      -> agent reports ABSENT as FACT to the user
```

Each arrow is a place a check belongs. The last one is unforgivable.

## The general rule

**A failed extraction is not evidence of absence. It is evidence of nothing at all.**

Before any "I found no X" claim that rests on parsing, decoding, or transforming
data, you owe a _coverage measurement_:

1. Count rows/records you attempted to read.
2. Count how many yielded usable content.
3. Compute the rate. Set a floor **before** you look at it.
4. Below the floor: report the TOOL as broken, in plain language, and stop. Do not
   report a finding.

Coverage is cheap. It is one extra counter in the loop you are already running.

```python
total = usable = 0
for row in rows:
    total += 1
    s = extract(row)
    if s:
        usable += 1
...
rate = 100 * usable / total if total else 0
if rate < 95:
    raise SystemExit(f"EXTRACTION BROKEN: {rate:.1f}% decoded - findings are invalid")
```

## Smell tests that catch this class before you speak

- **Suspicious uniformity.** Every record identical, every field empty, every value
  the same character. Real data is ragged. Uniform output is a parser artifact.
- **Repeated framing bytes.** `+`, `NSString`, `\x00`, `bplist`, `?????`, or the
  literal replacement char `\ufffd` in your "text" means you are reading structure,
  not content.
- **A negative that contradicts a known-active relationship.** The owner is asking
  because she _remembers the conversation_. A zero-result against lived memory is a
  measurement bug until proven otherwise — this is the same rule as "a per-unit count
  wildly out of line with its peers is a bug in the measurement."
- **Volume mismatch.** 1,946 messages exist and you found 0 relevant. Print the
  denominator. If you never counted the population you searched, you cannot claim
  absence within it.

## The correct decoder (verified 426,276 / 426,290 = 100.0%)

Read the NSKeyedArchiver length prefix rather than scraping printable bytes:

```python
def decode_attributed_body(blob):
    if not blob:
        return None
    ab = bytes(blob)
    i = ab.find(b"NSString")
    if i < 0:
        return None
    j = ab.find(b"+", i) # type marker preceding the length prefix
    if j < 0:
        return None
    k = j + 1
    b0 = ab[k]
    if b0 == 0x81: # 2-byte little-endian length
        length = int.from_bytes(ab[k + 1:k + 3], "little"); k += 3
    elif b0 == 0x82: # 4-byte little-endian length
        length = int.from_bytes(ab[k + 1:k + 5], "little"); k += 5
    else: # single-byte length
        length = b0; k += 1
    return ab[k:k + length].decode("utf-8", errors="replace")


def message_text(text, attributed_body):
    """Always read a message through this. text column first, blob as fallback."""
    return text if text else decode_attributed_body(attributed_body)
```

Open the DB read-only so you never mutate a live store:
`sqlite3.connect(f"file:{db}?mode=ro", uri=True)`.

## Fixing it is three moves, not one

1. **Ship the working extractor** as a `scripts/` file the skill invokes, not as a
   snippet in prose that the next agent will retype slightly wrong.
2. **Delete the broken guidance** from every reference that carries it. Leaving the
   old regex in place next to the new function guarantees someone picks the old one.
3. **Add the coverage gate to the skill body**, phrased as a hard rule about
   reporting, not just a technique. The technique fix prevents this bug; the
   reporting rule prevents the entire _class_.

Self-test the extractor as a `__main__` block so it can be re-run as a probe:

```
$ python3 decode_attributedbody.py
rows=426290 decoded=426276 (100.0%)
```

An extractor you have not seen report its own coverage is unverified.

## Telling the user

When this has already reached a human, the repair is owed before the explanation.

- **Concede without hedging.** "You were right, and the tool was wrong" — not "there
  may have been an issue with the decode path."
- **Name the mechanism in plain words.** "Your messages are stored in a packed format;
  the code that unpacked it only understood plain English letters, so your thread came
  back as a row of plus signs." No stack traces to a non-technical owner.
- **Show the measurement.** "426,276 of 426,290 messages decode, 100%. Nothing is
  lost." A burned user needs the receipt, and the number is the receipt.
- **Then give the answer they originally asked for**, and name the honest gap in it
  separately from the bug. In this incident the work and pricing existed in the thread
  but no warranty terms did — saying so plainly is what made the answer trustworthy
  again.
- **Fix it before reporting it.** The message that lands is "here is what broke, here
  is the fix already installed, here is your answer" — not a bug report.

## Where this generalizes

Any read path with a lossy transform between storage and the agent's eyes:

- Binary/archived blobs (NSKeyedArchiver, protobuf, msgpack) scraped as text
- HTML→text extraction where the content sits in JS-rendered nodes
- OCR/PDF text layers on scanned pages returning empty (see the extraction coverage
  warning pattern in document reads)
- API responses whose payload moved under a new key, leaving `[]` at the old one
- Encoding mismatches turning non-ASCII content into `?` or dropping it entirely

Same rule everywhere: **measure coverage, set a floor, report the tool when the floor
is missed, and never let an empty read become a factual negative.**
