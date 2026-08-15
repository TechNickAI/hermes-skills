# jbudding@gmail.com — Hard-rule targeted sweeps

Use this when a jbudding Email Steward run processes bounded backlog batches but hard-rule attention senders may be buried deeper than the current default page.

## Why

The default unprocessed inbox scan returns only the current Gmail page. In deep legacy backlog runs, important hard-rule items can sit behind many pages and never surface before the run budget is exhausted. A targeted hard-rule query can safely expose those items without attempting a full multi-year cleanup.

## Required sweep: Google security alerts

Google account security alerts from `no-reply@accounts.google.com` are hard-rule `flag` items regardless of age. After normal bounded backlog batches, run a targeted search for unprocessed Google security alerts before final verification/reporting:

- Query: `in:inbox from:no-reply@accounts.google.com "Security alert" -label:Agent-Starred -label:Agent-Reviewed -label:Agent-Archived -label:Agent-Deleted -label:Agent-Unsubscribe`
- Parse the `threads` key and filter by returned `labels` just like the default scan.
- Build the plan from the scan JSON with exact ID preflight.
- Apply `Agent-Starred` only; keep `INBOX`.
- Verify by rerunning the same targeted query and requiring `genuinely_unprocessed == 0` before claiming the hard-rule sweep is clean.

## Reporting

Group multiple legacy Google security threads in the final report, e.g. "Google <no-reply@accounts.google.com> — N related Security alert threads — Google account security alerts are hard-rule security items." Do not list every duplicate unless subjects differ materially.
