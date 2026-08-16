# Autonomous cleanup artifact synchronization and verification

Use this for a scheduled cleanup that is explicitly authorized to apply without an interactive approval gate. It supplements the backup and post-apply review requirements in `SKILL.md`.

## Canonical-source rule

The current live memory file is the only source to inventory. Prior cleanup artifacts may explain history, but never reuse their counts or accounting as if they describe the current file. Freeze the current original once, then derive the backup, inventory, proposal, and diff from that exact text.

## Apply and artifact-sync sequence

1. Read the current live file and count Unicode characters.
2. Write the full dry-run artifact set outside the live memory directory.
3. Back up the frozen original, read it back, and verify byte equality or SHA-256 equality before applying.
4. Apply the proposal and verify live equals `proposed-MEMORY.md` byte-for-byte.
5. If any correction is made after apply but before review, update live and proposed identically, then regenerate every derived artifact that changed:
   - `memory.diff`, always from the untouched backup/original to the latest proposal;
   - proposed char counts in `inventory.md` and summary metadata;
   - the affected inventory row's proposed text and rationale;
   - the declared highest-risk decision when scope changed.
6. Recheck live equals proposed before dispatching reviewers. Reviewers must inspect the final synchronized artifacts, not a superseded proposal.

## Deterministic acceptance probes

Run mechanical checks before accepting reviewer verdicts:

- live file equals proposed file byte-for-byte;
- backup hash equals the original hash recorded in summary metadata;
- inventory row count equals the number of original entries;
- final character count is at or under the scheduled ceiling or the safe shortfall is reported;
- every unchanged original entry remains byte-identical in the live file;
- a required-token checklist for each changed entry still finds every load-bearing negative constraint, command, path, ID, port, URL, known-good value, and named pointer;
- every named skill pointer resolves with `skill_view`/`skills_list` or to a verified path;
- `review-checklist.md` has no unchecked apply/review gates at completion.

Mechanical checks do not replace semantic review. They prevent an LLM panel from passing a stale artifact set or overlooking a missing literal.

## Cortex/provider gate

A configured provider label is not proof that provider offload works. Check `hermes memory status` and distinguish:

- provider selected;
- plugin installed and operational;
- retrieval from the exact destination verified.

If the plugin is unavailable, do not claim a provider offload. A local Cortex markdown tree is a separate manual destination: use it only after loading the `cortex` skill, verifying the active root/schema, writing the detail, and successfully retrieving it from that exact store. Otherwise keep the detail in core memory or safely compress it.

## Review and rollback

Use multiple independent reviewer lenses or model families when available, then reproduce every acceptance-unlocking claim mechanically. If review finds material loss, restore the verified backup and confirm the restored hash. Otherwise report: `post-apply review found no required rollback`.
