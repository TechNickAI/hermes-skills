# 2026-06-12 sender addendum

New confirmed security pattern from backlog processing:

- `appleid@id.apple.com` (Apple ID) password-reset notifications (`Your Apple ID password has been reset.`) should be treated as account-security events and flagged/left visible rather than archived or deleted, even when discovered in older backlog mail.

Reason:

- During backlog cleanup, multiple unprocessed Apple ID password-reset notices surfaced. They fit the same durable category as login alerts, MFA changes, and account-recovery notifications: security-relevant account events with no reliable expiry from an inbox-triage perspective.
