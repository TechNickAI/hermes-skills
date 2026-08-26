# Deletion safety in message pipelines

For any change that DELETES, edits, or suppresses user-visible messages —
progress-bubble cleanup, chat pruning, retention jobs, "tidy up the thread"
features. The failure mode is not a crash. It is a user losing content, silently,
in an edge case the happy-path tests never reach.

Source session: 2026-08-14, patching Hermes `cleanup_progress` so interim
assistant commentary is deleted after the final answer lands.

## The catch, and why it matters that self-review found it

The first version of the patch was small, tested, falsified, and **wrong in a way
that could blank a user's turn.**

`_send_commentary` sends interim commentary. The patch registered every
commentary bubble's `message_id` for post-delivery deletion. Correct in the
common case — that chatter is throwaway.

But reading `run.py` further up the call chain:

```python
# run.py — has_delivered_text() consults _delivered_commentary_texts
if not _is_empty_sentinel and not _transformed and (_streamed or _content_delivered):
    response["already_sent"] = True      # normal final send SUPPRESSED
```

The interim path can deliver the turn's **actual final answer**. When it does,
`has_delivered_text()` matches it, `run.py` sets `already_sent=True` and skips
the normal final send — making that commentary bubble the **only copy the user
has**. Deleting it afterwards leaves an empty turn.

Three independent reviewers were mid-flight. This was found by continuing to read
the surrounding code while waiting for them, not by the panel. **Do not treat a
dispatched review as permission to stop thinking.**

## The fix shape: hold, then release against the final text

Do not register an id for deletion at send time. Hold `(visible_text, message_id)`
and release only once the turn's real final response is known:

```python
def release_transient_ids(self, final_text: str) -> None:
    """Release held ids for deletion, minus any bubble carrying the answer."""
    held, self._transient_candidates = self._transient_candidates, []
    target = self._clean_for_display(final_text or "").strip()
    for text, message_id in held:
        if not message_id:
            continue
        if target and text == target:
            continue          # this bubble IS the answer — keep it
        self._notify_transient_message(message_id)
```

Properties worth copying:

- **Fails closed.** A turn that dies before release deletes nothing, so
  interrupted runs keep their breadcrumbs.
- **Idempotent.** The held list is cleared on first use; a double call cannot
  double-delete.
- **Compare normalized visible text**, the same form the user saw, not the raw
  payload.
- **Falsy ids ignored** — an adapter reporting success without a usable id is
  simply untrackable, not an error.

## Generalized rule

> Before deleting any message the system itself sent, ask: **can this message
> ever BE the deliverable?** If a suppression/dedup path anywhere treats it as
> the final content, deleting it is data loss.

Trace the id's whole lifetime, both directions:

1. Where is it created, and what else records it?
2. Does any code path treat that record as proof the answer was delivered?
3. What happens if the turn is cancelled, fails, or is superseded mid-flight?
4. Is the deletion gated on success, and does the failure path leave evidence?

## Tests must include the data-loss case explicitly

Name it so nobody deletes it later as redundant:

- `test_commentary_carrying_final_answer_is_never_deleted` — the guard
- `test_mixed_turn_deletes_chatter_keeps_answer` — chatter goes, answer stays
- `test_release_is_idempotent` — double-delete safety
- `test_never_released_means_never_deleted` — fails closed
- `test_callback_exception_never_breaks_delivery` — bookkeeping must never
  break the user-visible message

**Falsify each guard separately.** Removing the tracking call must fail the
tracking test; removing the final-answer guard must fail _both_ data-loss tests.
Two guards need two falsification runs — proving one says nothing about the other.

```bash
# revert just the guard clause, run, confirm the RIGHT tests fail, restore
```

### The falsification that actually matters: revert the WIRING, not just the helper

A panel review of this exact patch produced a finding worth more than the bug it
was looking for:

> _"Reverting `run.py:5005-5012` leaves all 9 tests green. The tests pin the
> plumbing, not the defect."_

Both true. Every test constructed the consumer **directly**, passing the callback
by hand, so they proved the helper worked while proving nothing about whether the
gateway ever _passes_ it. The one-line wiring — the only line that makes the fix
reach a real user — was untested.

**Falsify each layer separately:**

| revert this                                                | a test must fail      |
| ---------------------------------------------------------- | --------------------- |
| the helper / notify call                                   | unit test             |
| the **wiring** that passes the callback in production code | end-to-end test       |
| the data-loss guard clause                                 | the named guard tests |

If reverting the wiring leaves everything green, you have unit-tested a component
and shipped an unverified feature. Write at least one test that drives the REAL
entry point (here, `_run_agent` with a fake agent emitting commentary through
`interim_assistant_callback`) so the production call path is load-bearing in CI.

### Sibling call paths of the same bug class

Fixing the site you found is half the job. Search the same function for other
producers of the same message class — a maintainer reads "fixed one site, left
its sibling in the same function" as an incomplete fix.

Here the consumer-path fix left a fallback at `run.py:5043` (fires when the
stream consumer could not be constructed) still sending unregistered commentary.
The callback could not cover it — the callback lives _on_ the consumer, which
does not exist on that path — so the ids had to be held on the turn context
instead and released through the same guard.

Distinguish a real sibling from a false one: a second construction site in the
proxy path looked like the same bug, but it can never emit interim commentary and
has no cleanup machinery at all. Correct to skip — but say so in a comment, or the
next reader re-opens the question.

### Naming a callback for what it actually fires on

The first name, `on_transient_message`, promised more than it delivered: it fires
from exactly ONE site (commentary) and never for tool/heartbeat/status bubbles,
which the gateway registers inline. An over-broad name invites a future
contributor to wire it at an already-tracked site — producing double deletes.
Name the hook after its actual trigger (`on_commentary_sent`), and check whether
the codebase already has vocabulary for that event before inventing new terms.

**When you rename, grep every consumer** — including your own verification
tooling. A rename here left the fleet verifier grepping the old symbol, so it
reported the patch ABSENT on a correctly patched host. A checker that fails on
healthy code trains people to ignore it.

## Reporting shape

Give the user the rollback trigger in plain language and make it cheap to invoke:

> If a turn ever comes back **empty**, that is the data-loss path — say so
> immediately and I'll roll back to `<stock-sha>` in seconds.

Also state what remains unverified. Static analysis of a deletion path is not the
same as watching a live turn; say which one you have.

## Checklist

- [ ] Every message class the change can delete is enumerated
- [ ] Asked whether each class can ever carry the final deliverable
- [ ] Suppression/dedup paths (`already_sent`, "already delivered") traced
- [ ] Deletion gated on turn success; failed runs keep breadcrumbs
- [ ] Release mechanism fails closed and is idempotent
- [ ] Data-loss guard has its own named test, falsified independently
- [ ] **Reverting the production WIRING fails a test** — not just reverting the
      helper. If everything stays green, the feature is unverified
- [ ] Sibling call paths of the same bug class searched in the same function;
      genuine non-siblings documented with a comment rather than left silent
- [ ] Callback/hook named for its actual trigger, and every consumer of a renamed
      symbol re-grepped — including verification tooling
- [ ] Rollback trigger stated to the user in observable terms
