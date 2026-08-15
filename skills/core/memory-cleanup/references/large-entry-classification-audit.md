# Large-entry classification audits

Use this workflow when a core-memory cleanup contains dozens of numbered entries and the user wants a lossless, row-by-row routing report.

## 1. Freeze the task contract first

Write down four fields before inspecting content:

- **Scope:** exact entry range and source files.
- **Mode:** report-only or apply.
- **Target:** measured character ceiling.
- **Preservation floor:** constraints, commands, identifiers, paths, ports, URLs, and known-good values that must survive somewhere.

A current `do not edit files` instruction overrides older or contextual authorization to apply. In report-only mode, do not create scratch artifacts unless the user asked for files; return the ledger in the response.

## 2. Build the ledger before deep duplicate searches

Create one row per entry with these columns:

| ID  | Class | Proposed MEMORY text or exact destination | Evidence | Risk |
| --- | ----- | ----------------------------------------- | -------- | ---- |

Allowed classes should match the user's requested taxonomy, for example:

- keep/compress in core memory;
- offload verbatim to the external memory provider;
- convert to an existing named skill/reference;
- drop only as stale or exact duplicate.

Populate every row provisionally from the source-entry files first. Then verify destinations. This prevents exhaustive searches from consuming the run before the deliverable exists.

## 3. Verify destinations with an evidence hierarchy

Use the smallest sufficient proof:

1. Read the named skill/reference or Cortex page when the likely destination is known.
2. Search an exact distinctive phrase, command, identifier, or value when duplication is uncertain.
3. Use broad thematic searches only to discover a destination, not as proof that the complete entry is duplicated.

A destination is an exact duplicate only if it preserves every decision-relevant clause and every required exact string. A paraphrase that omits a negative constraint, command flag, identifier, path, port, URL, or known-good value is not lossless duplication.

If the destination does not yet exist, label it `CREATE: <exact path>` rather than pretending a pointer exists.

## 4. Reconcile stale, tentative, and conflicting facts

Do not flatten different truth statuses:

- **Current/locked:** retain in core or canonical skill/reference as appropriate.
- **Tentative/working:** archive verbatim with an `UNCONFIRMED as of YYYY-MM-DD` marker.
- **Superseded:** archive the old value with provenance; keep only the current value or source-of-truth pointer in core.
- **Stale operational identifier:** check live configuration. Preserve the historical identifier in an archive if exact-value preservation was requested, but do not leave it in core as if active.
- **Time-sensitive legal/tax fact:** destination must include `VERIFY LIVE BEFORE USE` and the as-of date.

When several entries describe successive naming or product-ladder decisions, reconcile them together before routing any one entry. The newest explicit lock wins in core; older locks remain searchable as superseded history.

## 5. Preserve enforcement chains

If an entry mixes a reusable procedure with a hard safety rule:

- keep a compact safety rule in core memory;
- move the full procedure to the named skill/reference;
- ensure the skill repeats or points back to the safety gate.

Do not split them in a way that leaves the procedure executable without its approval, privacy, or verification constraint.

Sensitive exact values may be redacted in the user-facing report, but the row must name the exact existing or proposed private destination where the full value remains. Never copy secrets into a new general-purpose skill.

## 6. Control investigation budget

For large inventories:

1. Batch-read all source-entry files.
2. Draft all rows provisionally.
3. Batch-read known canonical destinations.
4. Run targeted searches only for unresolved/high-risk rows.
5. Finalize the table.
6. Run review only after the complete artifact exists.

Reserve enough interaction/tool budget to produce the answer. If approaching a runtime limit, stop optional searches and return the fully accounted provisional ledger with unresolved rows clearly marked. A complete honest ledger is more valuable than exhaustive research with no deliverable.

## 7. Verify accounting and size

Before returning:

- Regex-count the source IDs and confirm every integer in the requested range appears exactly once.
- Count table rows and ensure it matches the source count.
- Confirm every `drop` row names its duplicate/staleness evidence.
- Confirm every offload/skill row names an exact path, skill, or `CREATE:` destination.
- Estimate the proposed MEMORY size from the actual compact text, not intuition.
- Measure Unicode characters with Python `len(Path(...).read_text())` or equivalent, not bytes and not a tool's truncated display count.
- List the highest-risk decisions separately.

## Output discipline

For a compact one-row-per-ID request, keep each row terse. Put shared explanations, notation, and risk discussion outside the table. Do not replace the requested classification table with a narrative progress report.
