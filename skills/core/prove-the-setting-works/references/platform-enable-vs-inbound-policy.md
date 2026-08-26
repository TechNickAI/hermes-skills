# Platform enablement is not inbound authorization

## Trigger

Use this when credentials are needed for outbound delivery but the same platform must not answer unsolicited inbound messages. Proven on BlueBubbles/iMessage after an agent sent pairing codes to four of the owner's real contacts.

## The two independent controls

- `platforms.<platform>.enabled` controls whether the platform is configured. `tools/send_message_tool.py` refuses outbound sends when `not pconfig.enabled`.
- `unauthorized_dm_behavior` controls what happens when an unknown sender sends a DM. `pair` sends a pairing code; `ignore` silently drops it.

Do not disable the platform to suppress pairing. That also disables outbound sending.

## Correct BlueBubbles configuration

```yaml
gateway:
  platforms:
    bluebubbles:
      enabled: true
      extra:
        unauthorized_dm_behavior: ignore
```

A `BLUEBUBBLES_ALLOWED_USERS` allowlist independently makes unknown senders resolve to `ignore`; keep it as defence in depth, not as the only control.

## 🔴 Probe at the layer the product actually uses

The most misleading result in this investigation came from probing the wrong
loader. Two harnesses disagreed about the SAME config, and both were "correct"
at different layers.

`gateway/config.py` (v2026.8.19) has two entry points:

| entry point                               | flat per-platform `unauthorized_dm_behavior`         |
| ----------------------------------------- | ---------------------------------------------------- |
| `GatewayConfig.from_dict(raw["gateway"])` | **dropped** — never reaches `PlatformConfig.extra`   |
| `load_gateway_config()`                   | **bridged into `extra`** at `gateway/config.py:1607` |

`PlatformConfig.from_dict` only lifts a hardcoded set of keys
(`gateway_restart_notification`, `typing_indicator`, `typing_status_text`) from
top level into `extra`. Everything else at that depth is discarded. The full
`load_gateway_config()` path runs a separate bridging loop that DOES handle
`unauthorized_dm_behavior` and `notice_delivery`.

Consequence: a probe built on `from_dict` reports the flat key as a silent
no-op, while the running gateway honors it. Neither result is a bug — they are
different layers, and only the second is what the gateway executes.

**Rule: probe through the highest-level loader the product calls at startup.**
For a Hermes gateway that is:

```python
import hermes_cli.config as hcfg
for k, v in (hcfg.load_env() or {}).items():   # profile .env -> os.environ
    os.environ.setdefault(k, v)
cfg = gcfg.load_gateway_config()               # NOT GatewayConfig.from_dict
```

`load_gateway_config()` does not itself parse `.env`. `get_hermes_home()` honors
`HERMES_HOME`, but credentials only arrive if you run the product's own
`load_env()` first. Skipping it makes credentials look absent and every
capability check read `False` — which looks exactly like a config bug.

Reload the modules between cases (`importlib.reload`) so module-level
memoization from a previous sandbox cannot leak into the next result.

Still write the config under `extra:` regardless. It is honored by both layers,
so it cannot be broken by a refactor of the bridging loop, and it states intent
explicitly.

## Upstream behavior to remember

On vanilla v2026.8.19, BlueBubbles credentials force `enabled = True` during environment override even when config says `enabled: false`. Do not patch that assignment to suppress pairing: with the patch, `enabled:false` sticks and outbound sending fails silently — the send tool's guard is `not pconfig.enabled`, so the capability disappears with no error and the symptom that prompted the patch is gone, which hides the regression.

Upstream already applies an inbox-shaped carve-out to email: arbitrary unread human messages should not trigger pairing codes. iMessage has the same safety shape; a framework default change should extend that carve-out to BlueBubbles rather than coupling inbound policy to platform enablement.

## Required probe

Test on an isolated local `HERMES_HOME`, never the affected owner's machine first. Exercise the product's own paths:

1. `hermes_cli.config.load_env()`
2. `gateway.config.load_gateway_config()`
3. `GatewayAuthorizationMixin._get_unauthorized_dm_behavior(Platform.BLUEBUBBLES)`
4. The outbound gate: `pconfig and pconfig.enabled` plus resolved server/password.

Report a TUPLE per case — `(pairs_with_strangers, can_send)`. A single boolean hides the capability regression that started the whole incident.

Include both controls:

- **Positive control**: credentials only must reproduce `pair`. If it does not, the harness is broken and every "fix" it blesses is meaningless.
- **Negative nesting control**: a deliberately wrong location. Interpret its result against the loader you used (see the table above) rather than assuming it must fail.

Pass condition: unknown inbound DM resolves to `ignore` while outbound remains configured.

## Rehearse the edit on a copy of the real file

Before editing a live owner's config, fetch a copy and apply the exact edit locally, then `diff`. The expected result is one line:

```diff
-      enabled: false
+      enabled: true
```

Anchor the edit on the platform block by regex and assert the replacement count, so a stray `enabled:` elsewhere in an 800-line config cannot be hit. Then verify on the target host by re-running the probe against the REAL config before restarting anything.

## Verifying the live result

After restart, re-run the probe on the box and require both properties:

```text
STRANGER GETS PAIRING CODE?    : False
OUTBOUND SEND CONFIGURED?      : True
```

`OUTBOUND SEND CONFIGURED` is a configuration proof, not a delivery proof. Do not claim outbound works until a message has actually been delivered — and never send a test message to a real human without the owner naming the recipient.

## Check the whole fleet for the same default

The incident box is rarely the only one. Any host holding credentials for the
platform and lacking an explicit policy sits on the open-gateway default. Sweep
every profile with the same probe and report which ones resolve to `pair`;
finding a second exposed box is the normal outcome, not a surprise.
