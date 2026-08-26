# Phantom fields on vendor APIs

A vendor API can accept a field, persist it, and return it on a subsequent `GET`
while never consuming it. Local verification passes at every step and the feature
is still dead. This is the remote-API analogue of a normalizer silently stripping
a config key, but strictly harder to catch, because the readback _confirms your
value_.

## The case that established this (one occasion, Vapi)

Updating a voice assistant that places real outbound phone calls. The base prompt
(persona, phone-speech rules, task instructions) was written to
`model.systemPrompt`.

What the evidence said at the time:

```
[OK ] model: HTTP 200
=== READBACK ===
model: anthropic claude-sonnet-4-6 temp 0.5 maxTok 400 tools ['dtmf', 'endCall']
systemPrompt chars: 3901
prompt matches file: True
```

A `200`, an exact character count, and a byte-identical match against the source
file. By every check I had, it was applied.

It was not. `systemPrompt` is absent from every assistant schema in the live
OpenAPI. The model never received a word of it. An assistant in that state calls
a real human with no persona and no task — it would have dialed and had no idea
why.

Caught only because a cross-family reviewer checked the schema instead of the
docs. Verified independently before acting on it:

```python
import json
d = json.load(open('/tmp/vapi_openapi.json'))
s = json.dumps(d)
print(s.count('"systemPrompt"'))          # -> 0

schemas = d['components']['schemas']
for name in ['CreateAssistantDTO', 'UpdateAssistantDTO', 'Assistant',
             'AssistantOverrides']:
    props = set((schemas[name].get('properties') or {}).keys())
    print(name, 'systemPrompt:', 'systemPrompt' in props)   # -> False, all four

print(sorted(schemas['AnthropicModel']['properties']))
# ['maxTokens', 'messages', 'model', 'provider', 'temperature', 'thinking',...]
```

Zero occurrences across two million characters of schema. The real field is
`model.messages[{role: "system", content:...}]`.

Two sibling fields behave identically — `backchannelingEnabled` and
`silenceTimeoutSeconds` both round-trip on a `GET` while being absent from
`CreateAssistantDTO`. So this was not a one-off quirk of a single key; it is how
that API's write path behaves for anything it does not recognize.

## Why the wrong field was reachable at all

`systemPrompt` appears across third-party tutorials, older vendor docs, and
model training data. Every non-schema source carries a deprecated field forward
long after the service stops consuming it. Prose is a lagging indicator; the
schema is what the service validates against.

This is the specific trap for an agent: the plausible-looking field name is the
one most represented in training data, precisely _because_ it used to be right.

## Procedure

Before relying on any field of an API you have not personally exercised:

1. **Pull the machine-readable schema.** Common paths: `/api-json`,
   `/openapi.json`, `/swagger.json`, `/v3/api-docs`. Save it locally; it is
   usually large and worth grepping repeatedly.
2. **Check the WRITE DTO, not just the read model.** `CreateXDTO` / `UpdateXDTO`
   are what validate your request. A field present only on the response object
   tells you nothing about whether you may set it.
3. **Count occurrences across the whole document first.** A global zero is
   decisive and takes one line. Only narrow to per-schema checks if the count is
   non-zero.
4. **Confirm behavior on one real invocation.** The schema can lag the running
   service in either direction. The tiebreaker is always an actual call whose
   _effect_ you can observe — not whose status code you can read.
5. **Diff intent against the loaded/served state**, not against your own request
   body. Echo is not consumption.

## Auditing for damage already done

Once you know a phantom field exists, assume other resources carry it. Query the
whole collection and flag both shapes at once:

```bash
curl -sS -H "Authorization: Bearer $KEY" https://api.<vendor>/assistant \
  | jq -r '.[] | "\(.name)
     prompt_in_messages=\((.model.messages // []) | length > 0)
     legacy_systemPrompt=\(.model.systemPrompt != null)"'
```

In this case three of four assistants across the org were affected, only one of
which was the one being worked on. Finding the defect on your own resource is the
start of the audit, not the end of it.

## Generalization

- Silent-absence failure (local config): change produces no error and no effect
  → suspect it was stripped.
- **Phantom-echo failure (vendor API): change produces no error, no effect, and a
  readback that confirms your value → suspect the field is not in the schema.**

The second is more dangerous because it manufactures positive evidence. Any check
built on "did my value come back?" will pass. Only a schema check or an observed
behavioral effect can distinguish the two.

## Related traps found in the same session

Worth checking on any new vendor API, all verified against schema + live calls:

- **Response shape asserted by a review bot was wrong.** A code-review bot
  flagged `GET /call` as returning a paginated `{metadata, results}` object. The
  schema declares `{type: array, items: $ref Call}` and a live request returned a
  bare array. A `CallPaginatedResponse` schema _did_ exist — just not on that
  endpoint. Reviewer confidence is not evidence either; check the schema before
  accepting or rejecting.
- **Success status assumed.** `POST /call` returns `201`, not `200`. Code
  checking `== 200` treats success as failure — and on a non-idempotent create
  endpoint, the retry that follows places a second real phone call.
- **Defaults mistaken for absence.** `maxDurationSeconds` defaults to 600s, so a
  missing value is not "unbounded." An audit rule written without checking the
  default generates false alarms and provokes edits to working resources.
- **Mutually-exclusive fields.** `stopSpeakingPlan.voiceSeconds` applies only
  when `numWords` is `0`. Setting both looks like thorough configuration and
  leaves one silently dead.
- **Client rejected by the edge, not the API.** Python `urllib` receives
  `HTTP 403 / error code: 1010` on every endpoint of this vendor — a Cloudflare
  user-agent rule, not an auth or key problem. `curl` and `requests` work. Read
  the error body: `1010` is an edge signature, and chasing it as a credentials
  problem burns real time.
