# Web-only historical X evidence audits

Use this procedure when a user asks for historical X posts but restricts evidence gathering to `web_search` and `web_extract`.

## Evidence ladder

1. Verify the underlying event from an official company, regulator, or issuer announcement. Extract the page and record its displayed date and URL.
2. Search each `(account, subject)` pair independently with targeted `site:x.com/<handle>/status` queries and subject variants such as ticker, company name, and asset name.
3. Accept a candidate post only when its URL is returned by search, supplied by the user, or cited by a source you can inspect. Never invent a status ID or alter another account's status URL.
4. Verify authorship, text, and date from indexed search metadata or another public page quoting/linking the post. If `web_extract` returns empty content or errors, that extraction provides no positive evidence.
5. A Snowflake decoder may derive an exact UTC timestamp from a known status ID. Use it only as timestamp corroboration after provenance is established, never to infer author or content.
6. Compute calendar-day lead as `announcement_date - call_date` only after both dates are verified. If dates match, record `0`; classify as post-hoc only if timestamps or another source prove the announcement came first.
7. Use `NOT FOUND` when no qualifying pre-announcement call is verifiable. State that this means not found through public web indexing, not proof the post never existed.

## Deal-identity guard

If the requested ticker/deal premise does not match the sourced event, preserve the requested pair but mark it incomplete. Record the actually verified event date/source and explain the mismatch, including predecessor ticker, private target, rebrand, or transaction-year issues. Do not silently force a near match into a confirmed deal.

## Output discipline

For every `(account, deal)` pair preserve the same schema, even when evidence is missing. URLs and dates must be literal sourced values or `NOT FOUND`. Notes should separate facts from search limitations and disclose any same-day ordering uncertainty.
