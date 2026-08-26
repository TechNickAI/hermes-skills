# Lossless Apply and Always-On Safety Audit

Use this reference for a large cleanup that will be applied in the same run, especially an unattended scheduled health check with explicit pre-authorization.

## Core distinction: archival losslessness is not behavioral losslessness

An exact provider snapshot proves the old text still exists. It does **not** prove the next session will obey rules that are no longer injected. Before moving anything out of core, identify standing guardrails that must remain always-on:

- external-send/share authorization
- channel allowlists and silent-drop boundaries
- account and scheduling boundaries
- privacy and consent constraints
- destructive-action or document-integrity gates
- frequently corrected interaction rules
- exact negative language whose absence has repeatedly caused mistakes

Keep these rules directly in core, compressed but semantically explicit. Do not rely on a provider search to recover them after a mistake is already underway.

## Apply authorization in unattended runs

The ordinary mode is dry-run and human approval. An invocation may explicitly pre-authorize application, for example a scheduled job that says to clean autonomously and not ask questions. Treat that as approval for the stated file/scope only.

Even with pre-authorization:

1. honor the exact scope (for example, MEMORY.md only; do not opportunistically edit USER.md or SOUL.md),
2. complete independent review before writing,
3. create and verify a rollback backup,
4. write relocation targets before removing source text,
5. verify the final live file after replacement.

If the invocation forbids restarting/resetting, do not restart merely to refresh the injected snapshot. Report that the new memory will load naturally in the next session.

## Recommended artifact set

Alongside the normal inventory and proposed files, create:

- `targeted-absence-audit.md` — critical always-on rules probed in the proposal
- `apply-verification.json` — machine-readable before/after sizes, hashes, paths, and post-write checks
- independent reviewer outputs (kept private in scratch space)

## Exact local offload verification

For a verbatim local provider snapshot:

1. Put clear begin/end markers around the exact source body.
2. Compare the extracted body with the live source using direct string equality.
3. Record a SHA-256 hash of the source body.
4. Write the provider destination first.
5. Read it back from the final destination, re-extract the body, and confirm equality plus hash.
6. Only then replace the core file.

A whole-file hash may differ because the offload page has frontmatter and retrieval notes. Hash and compare the marked source body, not the wrapper.

## Targeted absence audit

A numbered inventory proves accounting, but generic classification rows can still hide a bad compression. Add a separate probe matrix for high-risk rules:

```text
critical rule                    required semantic text in proposed core
external-send authorization      explicit same-exchange authorization
channel boundary                 all unlisted groups silently dropped
schedule boundary                live calendar + allowed booking window
source integrity                 verbal notes are not formal terms
voice correction                 exact banned phrase/word remains banned
```

Check all of the following:

- inventory IDs are unique, contiguous, and sum to the original entry count,
- the verbatim offload body equals the complete original,
- every critical rule has a direct semantic equivalent in proposed core,
- every named pointer exists before application,
- every procedure pointer names the exact skill/reference that was inspected,
- no workflow correction conflicts with a still-loaded skill reference.

Do not overfit this to literal case-sensitive substring matching. A failed probe can be a capitalization or punctuation difference; inspect it before declaring a gap.

## Review panel pattern

For a high-stakes memory change, use independent lenses:

1. **Data-safety/semantic reviewer:** missing hard rules, dangerous reversals, broken pointers.
2. **Prompt-quality reviewer:** clarity, redundancy, preference fidelity, overly detailed core entries.
3. **Meta-reviewer:** asks what the first reviews failed to test, especially absence and post-apply verification.

Reviewers may incorrectly call an unprefetched pointer "probably broken." Verify pointer existence locally before accepting that finding. Conversely, a reviewer PASS does not replace entry accounting or the targeted absence audit.

If model-family diversity cannot be verified, label the review degraded rather than claiming multi-model review.

## Safe apply order

1. Confirm the live source still matches the reviewed baseline; abort if it changed.
2. Confirm the timestamped backup exists and exactly matches the live source.
3. Atomically write the relocation target; read it back and verify retrieval/equality.
4. Atomically replace core memory from the reviewed proposal.
5. Read the live file back and verify:
   - exact equality to the proposal,
   - character count and target,
   - critical semantic probes,
   - provider pointer and provider availability,
   - rollback backup still matches the original.
6. Save a private machine-readable verification report.
7. Do not reset/restart if the invocation forbids it.

## Reporting

For a scheduled health report, keep the owner-facing result short:

- current size and whether cleanup ran,
- before/after characters and reduction,
- what was compressed/offloaded/routed to skills,
- backup path,
- single highest-risk decision and mitigation.

Do not expose sensitive offloaded details in the report.
