# Multi-source project brief checklist

Use for a concise owner-facing handoff assembled from multiple local sources.

## Evidence table before drafting

| Field          | What to capture                                                   |
| -------------- | ----------------------------------------------------------------- |
| Current state  | Latest confirmed fact, date, source                               |
| Intended move  | Plan and target date, explicitly not yet completed                |
| Decisions      | Decision, date, rationale, whether superseded                     |
| People         | Role, authority, and next responsibility                          |
| Money          | Viable paths, requirements, tradeoffs, unverified assumptions     |
| External party | Latest seller, vendor, lender, or counterparty signal             |
| Risks          | Confirmed finding vs observation vs theory; test that resolves it |
| Planned work   | Must-do, optional, sequence, dependencies, portability            |
| Actions        | Owner, trigger, deadline or phase, completion evidence            |
| Conflicts      | Older claim, newer claim, chosen current truth                    |

## Recommended brief order

1. Title, audience, and "current through" date
2. Bottom line
3. Current external-party or offer state
4. Decisions already made
5. People and roles
6. Financing or other major paths
7. Risks and diligence
8. Planned work and sequencing
9. Concrete next actions grouped by phase
10. Conflicts, stale claims, and attribution caveats

## Claim language

- Confirmed: "The approval letter was received on August 7."
- Reported but not independently verified: "The August 7 conversation reports that the approval letter was received."
- Intent: "The plan was to submit Monday or Tuesday; the corpus does not confirm submission."
- Theory: "Roof replacement was discussed as a possibility, not an inspection finding."
- Estimate: "The model estimates $X using an assumed rate; this is not a quote."
- Conflict: "The older model assumes a co-signer, but the later lender review says one should not be needed."

When transcript labels are unreliable, prefer "the conversation discussed" or "the group agreed" over naming a speaker. Name a speaker only when identity is independently clear from context or a direct user-authored turn.

## Reconciliation rules

1. Newest direct, firsthand evidence generally beats an older summary.
2. A dated decision log beats a stale proposed-task row.
3. A signed or executed artifact beats conversation intent.
4. A specialist finding beats a lay observation, which beats a theory.
5. A quote beats a model, but only for the quoted scope and date.
6. Do not average contradictions. Choose the current claim or keep the fork explicit.

## Concurrent-corpus safety

- Inventory recursively at start and again before sign-off.
- If the file count changes, inspect the new files before declaring full coverage.
- Read an existing output before replacing it.
- Treat any sibling-edit warning as a merge gate.
- Verify the merged artifact after resolving a collision.

## Deterministic final checks

- Exact output path exists.
- Every requested topic has a heading or explicit treatment.
- Dates use one clear format and the "as of" date is stated.
- Status and intent are not conflated.
- Estimates, quotes, observations, and theories are labeled.
- No credentials, personal identifiers, account numbers, private thread IDs, or unnecessary URLs.
- Forbidden style characters or formats are absent.
- No transcript attribution exceeds the evidence.
- Action list names owners and phase or trigger.
- Latest recursive file count matches the corpus actually reviewed.
