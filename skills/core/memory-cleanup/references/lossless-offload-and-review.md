# Lossless Offload and Review Hardening

Use this reference when a cleanup moves a large share of always-loaded memory into Cortex or other long-tail storage.

## 1. Make two independent recovery layers

Before rewriting **either** live file (`MEMORY.md` and `USER.md`):

1. Freeze verbatim source copies for both files. Record absolute source/archive paths, character counts, entry counts, mtimes, and SHA-256 payload hashes in a manifest.
2. Create timestamped filesystem backups and verify each backup payload hash matches its source. Do not call a backup "checksum-verified" unless the manifest contains the expected and observed hashes plus the verified path.
3. Write **verbatim full snapshots** to the active memory provider, preserving separators, commands, IDs, paths, negative constraints, and known-good values. A Markdown provider page may have frontmatter/preamble, so hash and verify the embedded source payload separately rather than comparing the whole page hash to the source hash.
4. Keep topical offloads as separate pages when they improve retrieval; the full snapshots are lossless backstops, not the preferred day-to-day result.
5. Verify retrieval of both topical pages and representative details from both full snapshots before removing anything from core.

A backup proves recoverability on disk. A provider snapshot proves the removed detail remains discoverable. Neither substitutes for the other. Archiving only `MEMORY.md` while compressing `USER.md` is not a lossless cleanup.

### Snapshot-isolation gate

Record source hashes before inventorying. Recheck them immediately before synthesis and again before apply. If either live file changes during review:

- stop comparing the moving live file to frozen proposals;
- continue the audit only against the named frozen snapshot, clearly labeled with its hash/time;
- report live drift separately; and
- regenerate the inventory/proposals before apply.

Never blend entries from two source versions into one "52/52 accounted for" claim.

## 2. Test retrieval, not merely file existence

For every destination:

- Confirm the page/file exists.
- Search using several distinctive terms from the original entry.
- Require the intended page in the returned results.
- Include exact IDs, paths, and unusual phrases among the probes.
- Record the query and returned destination in the cleanup artifact.

A pointer is valid only when the named destination exists **and contains the claimed detail**. Do not attach unrelated facts to a nearby pointer just because the destination is broadly topical.

## 3. Cortex FTS5 recovery

Cortex uses an external-content FTS5 index. A desynchronized index may produce empty searches or errors such as `fts5: missing row ... from content table 'pages'`, even when the Markdown page and `pages` row exist.

Recovery pattern:

1. Back up `.plugin.db` if practical.
2. Open the Cortex SQLite database.
3. Rebuild the FTS index with:
   `INSERT INTO pages_fts(pages_fts) VALUES('rebuild');`
4. Commit.
5. Repeat the exact retrieval probes that previously failed.

Do not conclude an offload is safe from a successful write receipt alone. The gate is successful search readback after any index repair.

## 4. Always-on behavior test

Before moving a correction out of core, ask:

- Is this merely a procedure used when a named skill is loaded?
- Or is it a cross-cutting behavior needed before the agent knows which skill to load?

Keep a compact always-on form when the rule governs general communication, completion claims, prompt parsing, approval visibility, factual humility, represented-party boundaries, or safe rule-writing. A detailed procedure can still live in a skill, but a skill-only copy is insufficient if the behavior must fire globally.

Examples of rules that often need an always-on compressed form:

- Specific status messages instead of empty acknowledgments.
- Sequential handling of explicitly gated prompts.
- Treating a completion caveat that means "may not work" as an unfinished bug.
- Surfacing real approval decisions in run output rather than burying them in state files.
- Identifying which party the user represents before assigning obligations.
- Writing positive behavioral rules without priming the forbidden wording.

## 5. Review hardening

Run independent reviewers, then verify their findings against source files before editing:

- Map every finding to the actual entry ID; reviewers can misnumber entries.
- Re-open the original source around the cited entry.
- Verify claims of hallucinated IDs, broken pointers, or missing coverage directly.
- Treat rendered redaction as a display boundary, not authoritative file content. When an exact private value must remain, copy the original entry from source to destination without round-tripping through reviewer prose or a redacted tool display.
- After fixes, run a targeted re-review naming the resolved findings and require a clean verdict.

The parent owns synthesis. A reviewer finding is evidence to investigate, not permission to mutate blindly.

## 6. Final proof

Before reporting completion, verify:

- Proposed and live files have matching hashes after apply.
- Before/after character and entry counts are recorded.
- Backup exists and retains the original character count.
- Active provider status is healthy.
- Representative searches return every routed category.
- The final review has no open Critical, High, or Medium findings.
- A final report records the highest-risk compression choice and its mitigation.
