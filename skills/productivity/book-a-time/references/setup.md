# Book-a-time setup

## Identity boundary

Authenticate `gog` with a dedicated assistant account. Do not authenticate as the
calendar owner. Share the writable calendar with `assistant@example.com` using **Make
changes to events**, and set its ID as `BOOKING_CALENDAR_ID`. The assistant then acts
through its own OAuth identity on an explicitly delegated calendar.

Share calendars that should block availability, but never receive created events, with
the same account using **See only free/busy**. Put their IDs in the comma-separated
`BOOKING_BUSY_CALENDAR_IDS` value. The writable calendar is always checked too.

The account needs Gmail send and Calendar scopes:

```bash
gog auth add assistant@example.com --services gmail,calendar --remote
```

Do not put OAuth tokens, application credentials, or generated signing keys in a
repository.

## Private environment

Add these values to `~/.hermes/.env` and set the file mode to `600`:

```dotenv
BOOKING_SIGNING_KEY=<output-of-openssl-rand-hex-32>
BOOKING_GOOGLE_ACCOUNT=assistant@example.com
BOOKING_CALENDAR_ID=<delegated-calendar-id>
BOOKING_BUSY_CALENDAR_IDS=<additional-free-busy-calendar-ids>
BOOKING_OWNER_NAME=<calendar-owner-display-name>
BOOKING_OWNER_EMAIL=<calendar-owner-email>
BOOKING_TIMEZONE=America/Denver
BOOKING_PUBLIC_BASE_URL=https://booking.example.com/book
```

Create a signing key without printing it into shell history:

```bash
umask 077
printf 'BOOKING_SIGNING_KEY=%s\n' "$(openssl rand -hex 32)" >> ~/.hermes/.env
```

Optional values include `BOOKING_WORKDAY_START`, `BOOKING_WORKDAY_END`,
`BOOKING_WORKDAYS`, `BOOKING_BUFFER_MINUTES`, `BOOKING_MINIMUM_LEAD_HOURS`,
`BOOKING_PROPOSAL_TTL_HOURS`, and `BOOKING_WITH_MEET`.

## Service boundary

Run `scripts/booking_server.py` under the host's service manager. It binds to
`127.0.0.1:8766` by default. Expose only `/book/*` through an HTTPS reverse proxy. The
route must be public because recipients may be outside the private network, but each
proposal has a random bearer URL and a separate signed confirmation POST. A GET never
books a meeting.

Example local start:

```bash
python3 ~/.hermes/skills/book-a-time/scripts/booking_server.py
```

Verify both boundaries and the dependencies:

```bash
curl -fsS http://127.0.0.1:8766/book/health
curl -fsS https://booking.example.com/book/health
python3 ~/.hermes/skills/book-a-time/scripts/booking.py doctor
```

Use a real proposal addressed to a test mailbox for the first end-to-end test. Confirm
the received message in a private browser, verify exactly one calendar event and one
invitation, then delete the test event.
