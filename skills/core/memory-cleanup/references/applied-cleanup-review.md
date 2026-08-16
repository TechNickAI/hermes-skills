# Applied MEMORY.md cleanup review rubric

Use this reference when Nick asks for a data-safety review of a cleanup that has already been applied. Do not redo the cleanup; audit the artifacts and live state, then return a concise pass/edit/hold verdict.

## Inputs to inspect

Typical cleanup scratch dirs contain:

- `inventory.md` — entry-by-entry accounting, classifications, destinations, and rationales.
- `memory.diff` — original vs proposed diff.
- `review-checklist.md` — creator's self-checks.
- `review-summary.json` — counts, backup path, highest-risk decision, required substring count.
- `proposed-MEMORY.md` / `proposed-USER.md` — intended result.
- Live `memories/MEMORY.md` and backup/original from the path named in the summary/checklist.

## Verification sequence

1. Establish the review snapshot: hash and character-count the live, proposed, backup, inventory, diff, and summary artifacts before judging content.
2. Confirm the live file equals the proposed file. If not, verdict is usually **hold** until the applied state is reconciled.
3. Confirm a readable backup/original exists and matches both the declared backup hash and the diff source. Strong verification: apply `memory.diff` to a temporary copy of the backup and require the reconstructed file to equal proposed byte-for-byte; a matching filename/header is not enough.
4. Check inventory accounting: every original entry should be keep/compress, relocate, merge, or explicitly drop. Verify the actual ID sequence has no gaps or duplicates rather than trusting the inventory's "all accounted for" sentence. Drops need a clear stale/duplicate/unsafe-to-keep rationale.
5. Read the diff around every full drop, merge, and high-char compression entry.
6. Preserve load-bearing details, especially:
   - exact commands, paths, skill names, script names, cron names/job IDs, DB/table names;
   - external IDs, account IDs, chat/topic IDs, UUIDs, ports, IPs, VINs, URLs/domains;
   - negative constraints (`never`, `do not`, `only`, `must`, `before delete`, `zero output`);
   - routing facts that decide which skill/tool/person/lane should be used;
   - qualifiers that change the interpretation of retained numbers or examples, such as billing period, currency, discount basis, ownership, date range, per-person vs total, or whether a count is historical/current. Token preservation alone is insufficient: `$334.22` can become materially misleading if "for two months" disappears.
7. Validate pointer names are real when possible. A stale pointer is usually an **edit**/minor issue unless it is the only route to load-bearing operational detail.
8. For any drop justified as "still discoverable," inspect the named original source directly when accessible and prove retrieval with a stable identifier or content query. Session history is secondary evidence, not a substitute for an available WhatsApp/DB/file/provider source.
9. Classify the highest-risk decision: often the densest operational compression, not necessarily the only drop. Verify its claimed destinations and live operational anchors (files, job enabled state/schedule, IDs, prohibitions) instead of reviewing prose alone.
10. Re-hash the review set immediately before the verdict. If any artifact changed during review, discard conclusions tied to the old snapshot, identify what changed, and repeat affected checks against the new stable set. One explained, stable correction can still pass/edit after re-review; unexplained or continuing mutation is **hold**.

## Verdicts

- **pass** — live equals proposed, backup exists, no load-bearing loss found, and drops/merges are defensible.
- **edit** — mostly safe, but a non-blocking correction is needed (e.g. stale skill pointer, ambiguous wording, one recoverable identifier omission).
- **hold** — possible load-bearing loss, missing backup, live/proposed mismatch, or an undefended full drop.

Return concise findings: verdict, issues, highest-risk decision, and whether files were modified during review.
