# User plugins shadow package adapters — and "do it with config only" has limits

Two related traps found at the tail of the an assistant agent session (one occasion), after
the upgrade was already done. Both concern **where adapter behavior actually
lives** and **whether a requested config-only fix is even possible**.

## 1. Platform adapters may be USER PLUGINS, not package code

Searching the installed package for the Telegram adapter found nothing:

```bash
ls -d ~/.local/share/uv/tools/hermes-agent/lib/python3.11/site-packages/hermes_plugins/*telegram*
# zsh: no matches found
```

The live adapter was actually at:

```
~/.hermes/plugins/platforms/telegram/adapter.py
```

A **user plugin**, outside the package. Search BOTH roots:

```bash
find ~/.local/share/uv/tools/hermes-agent ~/.hermes/plugins \
     -maxdepth 6 -iname "adapter.py" -path "*telegram*" 2>/dev/null
```

Confirm from the logs which module namespace is live — it names the source:

```
hermes_plugins.platforms__telegram.adapter ← user plugin under ~/.hermes/plugins
hermes_plugins.slack_platform.adapter ← package-provided
```

### Why this matters more than it looks

A user plugin **survives upgrades and permanently shadows the upstream adapter.**
So a hand-patch there:

- does NOT get wiped by `uv tool install... --force` (unlike a patch in the
  package tree, and unlike a patch in a dead git checkout, which is simply inert)
- silently masks every future upstream fix to that adapter
- is invisible to `git status` — there is no VCS on it at all

This is the one place a local patch genuinely _does_ stay live, which makes it
the most dangerous place to accumulate undocumented debt. When you find a local
modification in a plugin adapter, say so explicitly and name the masking risk.

## 2. Verify a config key exists upstream before promising config-only

the operator asked to "ditch the adapter and accomplish this with config only." The knob
in play was `direct_mention_only`, added by another agent. Check before agreeing:

```bash
gh api "search/code?q=direct_mention_only+repo:NousResearch/hermes-agent" --jq '.total_count'
# 0 → the key does not exist upstream; it is a local invention
```

`0` means there is no supported setting — the "config" was custom code wearing a
config-shaped hat. The honest response is _"there is no config-only equivalent"_,
not a substitute knob that sort-of rhymes.

## 3. Read a config knob's DIRECTION before offering it as a substitute

Enumerate what the live adapter actually supports:

```bash
grep -oE 'extra\.get\(\s*"[a-z_]+"' <adapter.py> | sed 's/.*"\(.*\)"/\1/' | sort -u
```

Then read the **call site**, because names mislead. Two Telegram gating keys look
interchangeable and are not:

| Key                      | Direction          | Call-site behavior                                        |
| ------------------------ | ------------------ | --------------------------------------------------------- |
| `mention_patterns`       | **widens**         | adds extra regex wake-words; an additional way to trigger |
| `exclusive_bot_mentions` | narrow, wrong axis | only suppresses when a _different_ bot is mentioned       |

Neither can express "only wake when the mention is at the START of the message."
A widening knob cannot solve a narrowing problem. Offering one as equivalent is a
fabricated capability — exactly the failure this skill family exists to prevent.

**Rule:** before proposing a config key as a substitute for custom code, confirm
(a) it exists upstream, and (b) its call site moves the gate in the direction you
need. Grep-hit on a plausible name is not evidence of either.

## 4. When the local patch may simply be unnecessary now

The patch in question was written to stop incidental mentions ("thanks @bot")
from waking the agent — authored while the member was on a broken old version and
flood-looping. After the upgrade, the honest recommendation is: **revert to stock
and let the upgraded build prove itself first.** If the annoyance recurs on the
current release, the right path is an upstream feature request, not a permanent
local fork of the adapter.

Generalizes to: a local patch written during a known-broken period is suspect
once the underlying fault is fixed. Re-test before preserving it forever.

## Verification checklist

- [ ] Both package and `~/.hermes/plugins/` searched for the adapter
- [ ] Log module namespace read to confirm which copy is live
- [ ] Any local plugin modification named explicitly, with masking risk stated
- [ ] Proposed config key confirmed to exist upstream (`search/code` count > 0)
- [ ] Call site read to confirm the key widens vs narrows as needed
- [ ] Patches authored during a known-broken window re-evaluated after the fix
