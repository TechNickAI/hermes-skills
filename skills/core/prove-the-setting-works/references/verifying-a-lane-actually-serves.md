# Verifying a Lane Actually Serves (Not Just That It Appears)

Config-lever probing proves a row/option **appears**. It does not prove the
option **works**. These are different failures and both ship silently.

A menu entry that fails on tap is worse than an ugly label: the user hits it,
gets a confusing error, and loses trust in the whole surface. Always probe real
execution before shipping a newly exposed or renamed option.

## Trap 1 — relabeling a built-in can BREAK its credentials

Some UI rows are emitted by a built-in registry and ignore a same-named user
config block, so the only way to rename them is:

> exclude the built-in slug + add a user block pointing at the same endpoint

**That trick silently breaks auth when the credential does not live in the env
var your new block names.**

Live case: renaming the `Anthropic` row to `Claude (direct)`
required a `providers.claude` block with `key_env: ANTHROPIC_API_KEY`. But that
env var was commented out — the real credential lived in the Hermes auth store
as `auth_type: oauth`. The result was a perfect-looking row that was a **dead
button**. Reverted; the plainer built-in label was kept as the honest cost of a
working lane.

**Check the credential source before renaming any built-in row:**

```bash
HERMES_HOME=<profile> <app-interpreter> -c "
from hermes_cli.auth import _load_auth_store
s=_load_auth_store() or {}
for k,v in (s.get('credential_pool') or {}).items():
    for e in v: print(k, e.get('auth_type'), e.get('source'))"
```

| what you see                             | verdict                              |
| ---------------------------------------- | ------------------------------------ |
| `source: env:FOO`                        | safe to re-block with `key_env: FOO` |
| `auth_type: oauth`, no populated env var | **leave the built-in row alone**     |

Generalization: a user-defined block can only carry credentials it can _reach_.
Registry/OAuth-backed rows own auth the block cannot see.

## Trap 2 — HTTP 429 does not mean "rate limited"

Providers overload 429 for unrelated conditions. The status code alone is not a
diagnosis, and guessing produces confidently wrong answers.

**Disambiguate with two signals: the `code` field and the rate-limit headers.**

```python
# On the error response:
#   rl = {k:v for k,v in e.headers.items() if "ratelimit" in k.lower()}
#   err = json.loads(body)["error"]  -> err["type"], err["code"]
```

| signal                                                                                   | meaning                                     | retry helps?  |
| ---------------------------------------------------------------------------------------- | ------------------------------------------- | ------------- |
| `code: rate_limit_exceeded` + `x-ratelimit-*` headers present                            | genuine throttle                            | yes, back off |
| `code: credit_balance_exhausted` / `type: insufficient_quota`, **no** rate-limit headers | prepaid balance is $0 — a **billing state** | never         |

**The absence of `x-ratelimit-*` headers on a 429 is the tell.** A real throttle
always reports its ceiling, remaining, and reset. No headers → nothing was
throttled.

### Separate the auth question from the quota question

Run a **GET that consumes no tokens** first (e.g. `/v1/models`). It isolates
three states that otherwise look alike:

- GET fails auth → bad/expired key
- GET 200, tiny completion 429 → key valid, **quota/billing** problem
- both succeed → lane is genuinely healthy

Probe with `max_tokens: 1` on the cheapest model so the check costs ~nothing.

## Trap 3 — one vendor, two meters

A subscription and a pay-as-you-go API from the same vendor are **separately
billed products that do not fund each other**. A healthy usage dashboard for one
says nothing about the other.

| lane                                                         | billing                            | typical auth     |
| ------------------------------------------------------------ | ---------------------------------- | ---------------- |
| consumer subscription (ChatGPT/Codex, Claude Max, SuperGrok) | flat monthly, session/weekly quota | OAuth            |
| platform API                                                 | prepaid credits / metered          | `sk-...` API key |

Live case: a dashboard showed "68% of weekly limit remaining" while API calls
returned `credit_balance_exhausted`. Both readings were correct — the dashboard
was the **subscription** meter; the failing calls used the **API key** meter,
whose prepaid balance was zero.

Before explaining a quota symptom, establish **which meter the failing call
actually billed**, then answer about that one. Ask: which credential did this
request use, and which product does that credential belong to?

## Trap 4 — the label can outlive the truth

After collapsing or renaming lanes, re-read the label as a stranger would. A row
labeled for a _subscription_ product that actually bills a _metered API_ is
actively misleading — worse than the raw slug it replaced, because it invites
the wrong click.

When a lane is known-dead, prefer (in order): remove the row, fix the
credential, or relabel to state the condition (`OpenAI API (needs credits)`).
Never leave a confident label on a broken lane.

## Checklist

- [ ] Credential source checked before renaming any built-in row
- [ ] Newly exposed/renamed lane exercised with a real (1-token) request
- [ ] 429s classified by `code` + presence of rate-limit headers, not status alone
- [ ] Token-free GET used to separate auth failure from quota failure
- [ ] Correct billing meter identified before explaining a quota symptom
- [ ] Pre-existing breakage distinguished from breakage this change introduced
- [ ] Known-dead lanes removed or honestly labeled, never left confidently named
