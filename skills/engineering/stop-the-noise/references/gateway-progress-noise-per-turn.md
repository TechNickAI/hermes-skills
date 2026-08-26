# Gateway per-turn progress noise (the "wall of text" class)

A SECOND, distinct noise class from the cron/webhook floods in SKILL.md. Here a
**single agent turn** emits many chat messages: tool-progress bubbles, "still working"
heartbeats, status callbacks, and interim assistant commentary. The user gets useful
live progress and then is left staring at a transcript of it forever.

Symptom phrasing to recognize: "wall of text", "I only want to see the last message",
"roll up / summarize / clean up the incremental progress", "it's too much".

`[SILENT]` and cron prompt contracts are IRRELEVANT here. This is the gateway display
layer, not a prompt surface. Do not reach for the SKILL.md diagnostic order.

## The message classes in a turn

**Line numbers below are from upstream `main` @ `d6a5cb9725` (one occasion).** They move
constantly — `gateway/run.py` is ~29.7k lines and churns daily. Re-grep rather than
trusting any number here:

```bash
grep -n "_cleanup_msg_ids.append" gateway/run.py
grep -n "async def _send_commentary" gateway/stream_consumer.py
```

| Class                            | Emitted at                        | Tracked for cleanup? |
| -------------------------------- | --------------------------------- | -------------------- |
| tool-progress bubbles            | `gateway/run.py:4548, 4717, 4739` | yes                  |
| native task-card fallback        | `gateway/run.py:4353`             | yes                  |
| "⏳ Working — N min" heartbeat   | `gateway/run.py:27622`            | yes                  |
| status-callback bubbles          | `gateway/run.py:5004`             | yes                  |
| **interim assistant commentary** | `gateway/stream_consumer.py:1833` | **NO**               |

**Never diagnose this from a local checkout.** A working clone can sit thousands of
commits behind `main` (this fleet's was 21,966 behind and a week stale), so every line
number and every "is it fixed yet" answer is unreliable. Pull the actual file first —
`git clone --depth 1 --filter=blob:none --sparse` then `git sparse-checkout set gateway
tools`. The GitHub contents API returns empty for files as large as `run.py`; use the
clone, not `gh api... -H "Accept: application/vnd.github.raw"`.

Verifying a "new" tracked site matters: `run.py:4353` did not exist in the older
checkout and had to be read before claiming a gap — it turned out to be a native
task-card fallback, not commentary. A new `_cleanup_msg_ids.append` site is not
automatically the missing class.

## What the built-in lever actually does

`display.platforms.<plat>.cleanup_progress: true`
(default `false`, `gateway/display_config.py:60`) collects message IDs during the turn
into `ctx._cleanup_msg_ids` and deletes them after the final answer lands, registered as
a post-delivery callback (`register_post_delivery_callback`, `gateway/run.py:20552` @
`d6a5cb9725`).

It is **already an in-process post-delivery hook**. Do not propose a cron job, an
out-of-band sweeper, or a "cleaner that runs back on each host" — that architecture is
already rejected by what ships. Deletion belongs in the turn that created the messages.

Deliberate behaviors that look like bugs but are not:

- **Failed runs skip cleanup on purpose**, so breadcrumbs survive for debugging.
- Only adapters overriding `delete_message` honor it. Confirmed present:
  telegram, slack, google_chat. Base returns `False` (no-op) for everyone else, silently.

## The gap that causes the complaint

`GatewayStreamConsumer._send_commentary` records only the delivered **text** into
`_delivered_commentary_texts` (used for dedupe against the final answer) and never
records `result.message_id`. The consumer is constructed at `gateway/run.py:5122`
(@ `d6a5cb9725`) with no cleanup hook among its parameters — its ctor takes only
`adapter, chat_id, config, metadata, on_new_message, on_before_finalize,
initial_reply_to_id, run_still_current`.

So the config combination that FEELS right produces the complaint:

```yaml
display:
  platforms:
    telegram:
      cleanup_progress: true # deletes tool bubbles + heartbeats
  interim_assistant_messages: true # commentary — permanent, never deleted
```

Every "I'll check the logs now…" survives forever. The only current lever that removes
commentary is `interim_assistant_messages: false`, which deletes the signal rather than
the residue. That is why the user perceives the setting as not working.

## Offer the options cheapest-first

When the user asks "how do we run the fixed code", rank by carrying cost and lead with
the reversible one. They may accept a partial fix today over a perfect fix next month:

| Option                              | Effort  | Ongoing carry         | Ideal UX             |
| ----------------------------------- | ------- | --------------------- | -------------------- |
| `interim_assistant_messages: false` | minutes | none                  | no — loses narration |
| Upstream PR / engage the open PR    | ~1 hr   | none                  | yes                  |
| Narrow local patch as a bridge      | ~1 hr   | ~15 lines until merge | yes                  |
| Vendor/build a plugin               | weeks   | large, fragile        | yes, badly           |

Config-only mitigation is real relief and needs no code — but note the tradeoff honestly
rather than presenting it as the fix. If the operator has frozen `config.yaml` changes,
this is still a config change: ask, even though it is a display key and not routing.

## Check both directions before diagnosing

The same complaint has an inverse. Audit the actual per-profile values; do not assume
the noisy default. A profile can be configured with `tool_progress: off`,
`interim_assistant_messages: false`, `cleanup_progress: false` but
`long_running_notifications: true` — that user sees NO useful progress and accumulating
heartbeats. Opposite fix, same-sounding complaint.

Enumerate per profile before recommending anything:

```bash
python3 -c "
import sys,yaml
c=yaml.safe_load(open(sys.argv[1])) or {}
d=c.get('display') or {}
for k in ('cleanup_progress','tool_progress','interim_assistant_messages',
          'long_running_notifications','tool_progress_grouping'):
    print(f'  {k} = {d.get(k)!r}')
print('  platforms:', d.get('platforms') or {})
" ~/.hermes/profiles/<name>/config.yaml
```

Resolution order is per-platform override → global `display.<key>` → platform tier
default → global default (`gateway/display_config.py::resolve_display_setting`). A
global `cleanup_progress: true` with an empty `platforms.telegram: {}` still resolves
true — read the resolver, not just the leaf key.

## Prior art before building

`tickernelz/hermes-progress-tail` (GitHub, ~11 stars, 277 commits, v0.2.12) implements
exactly the "one editable bubble with a rolling tail" UX: tools/todos/reasoning/subagent
progress in a single edited message, `native_gateway.suppress` to silence Hermes'
built-in progress, and its own `cleanup.auto_delete`.

**Evaluated and rejected for adoption one occasion.** Check these four things in order — the
first two are hard blockers that end the conversation before taste enters it:

1. **License.** `gh api repos/<o>/<r> --jq.license` returned `null` and there is no
   LICENSE file. Under default copyright there is **no right to copy, modify, or
   redistribute** — so vendoring it into a public MIT repo is not a decision that is ours
   to make. Fixable by asking the author to add MIT; until then every other argument is
   moot. **Check the license first on any "let's make it ours" request**, before sizing
   the code or debating repo fit.
2. **Runtime floor vs the actual fleet.** `requires-python = ">=3.12"`; measured venvs
   were 3.11.x on 5 of 6 hosts. Measure the fleet, do not assume.
3. **Size.** 16,169 lines across 86 Python files.
4. **Coupling.** 13 distinct Hermes-internal import sites (`gateway.run.GatewayRunner`,
   `gateway.platforms.base`, `tools.delegate_tool`, `tools.process_registry`,
   `agent.model_metadata`, `hermes_cli.*`, `hermes_constants`) plus 13 monkeypatch
   families across 7 modules. None of it is stable API, against a repo merging ~1,400 PRs
   per release into exactly those files.

The framing that settles it: adopting 16k lines of reverse-engineered integration to fix
a ~15-line gap is a ~1000:1 ratio of maintenance surface to problem, and "making it ours"
means _we_ get paged when a routine upgrade breaks message delivery for a non-technical
owner. Borrowing the _ideas_ is free; copying the code is a permanent liability.

Real risk to state plainly if it is ever trialed anyway: guarded monkeypatches on
`AIAgent`/`delegate_task` internals, so upstream churn can break it (it fails closed).
Trial it **unmodified via the author's own installer/update path on one non-client box**
before any ownership discussion — if the UX is not clearly better, the question dissolves.

Upstream history worth not re-deriving:

- #21186 shipped `cleanup_progress` (in v2026.5.7); #21252 closed as duplicate of it.
- #30864 made Telegram status callbacks edit one bubble per `status_key`.
- #21889 (open) — Discord never overrode `delete_message`, so `cleanup_progress` silently
  no-ops there while the docs claim support.
- **#22613 (open, `mergeable: false`/dirty since then, zero review)** already
  contains the commentary fix — its commit 2 is literally `expose commentary_message_ids
  - redirect hook`. It stalled because it bundles six concerns into +550/-20 (queue-merge,
cross-restart persistence via a new `~/.hermes/.cross_restart_cleanup.json`,
mono-formatting, approval-ack cleanup, always-on heartbeat collapsing). A live PR that
already implements your fix changes the correct action from "write a PR" to "engage the
author" — see `upstream-contribution-scoping/references/commenting-on-existing-threads.md`.
- #4882 and #47858 (both open) are the same feature family.

**Before writing this up as unfiled, search the PR queue, not just issues.** An earlier
pass of this reference declared the gap "unfiled" after searching issues alone; #22613 had
implemented it months prior. `gh pr list --repo <repo> --state open --search "<feature>"`
across a few phrasings is the check that would have caught it.

## There is no plugin seam for this — do not try to build one

Asked "could we write our own plugin instead", the structural answer is **no**, and it is
worth knowing before spending a day on it:

- The message ID exists only as a local inside `_send_commentary` and is discarded. No
  hook fires with it, no event carries it.
- `gateway/hooks.py` offers `gateway:startup`, `session:start|end|reset`,
  `agent:start|step|end`, `command:*`. **None carry platform message IDs** — hooks are for
  lifecycle notification, not message-surface manipulation.
- To reach it a plugin must patch the method or wrap the adapter's `send()` and infer
  which sends were commentary. That is precisely what the third-party plugin does with 13
  monkeypatch families.

So the options are: fix upstream, patch locally, or change config. "Write a plugin" is a
fourth option that only appears viable until you look for the extension point.

Also ruled out this session: the noise is **not** provider-specific. Commentary is emitted
from `agent/conversation_loop.py:6428` (`_emit_interim_assistant_message`) in
provider-agnostic loop code, so it is not an Anthropic-vs-OpenAI artifact. Worth checking
early — it would have changed the whole fix.

## Pitfalls

- **Do not conclude the feature is broken because the config is already on.** On this
  fleet `cleanup_progress: true` was set across four profiles and the wall of text
  persisted. The setting works; a message class escapes it. Find which class survived
  before touching config.
- **Do not propose a new config knob or a new hook first.** The correct fix threads the
  missing class into the EXISTING tracking mechanism — same contract as the other three.
  New surface area for a gap in existing plumbing is the wrong shape.
- **A client-owned agent's display config is not yours to reshape.** Changing what
  another person's agent shows them is a UX decision for their owner, even though it is
  technically reversible. Report the finding, gate the change.
- **Installing a third-party plugin on a fleet box is an approval gate**, especially one
  that monkeypatches core internals.
