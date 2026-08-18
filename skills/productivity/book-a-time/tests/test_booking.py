from __future__ import annotations

import http.client
import sys
import tempfile
import threading
import unittest
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from booking_core import (  # noqa: E402
    BookingError,
    BookingStore,
    CalendarConflict,
    DeliveryUncertain,
    GogClient,
    Settings,
    candidate_recurring_slots,
    candidate_slots,
    confirmation_signature,
    proposal_occurrences,
    render_email,
    render_ics,
    weekly_rrule,
)
from booking import deliver_proposal  # noqa: E402
from booking_server import build_server  # noqa: E402


UTC = timezone.utc


def settings_for(root: Path) -> Settings:
    return Settings(
        state_dir=root,
        public_base_url="https://booking.example.com/book",
        signing_key=b"s" * 48,
        gog_bin="gog",
        gog_keyring_password="keyring-test-password",
        account="assistant@example.com",
        calendar_id="owner@example.com",
        busy_calendar_ids=("owner@example.com",),
        owner_name="Calendar owner",
        owner_email="owner@example.com",
        owner_timezone="America/Denver",
        workday_start=time(9, 0),
        workday_end=time(17, 0),
        workdays=frozenset({0, 1, 2, 3, 4}),
        slot_increment_minutes=30,
        buffer_minutes=15,
        minimum_lead_hours=0,
        proposal_ttl_hours=168,
        with_meet=True,
        listen_host="127.0.0.1",
        listen_port=0,
    )


def create_sent_proposal(store: BookingStore) -> tuple[str, str, list[dict[str, str]]]:
    token = "A" * 48
    proposal_id, options = store.create_proposal(
        dedupe_key="test-sent-proposal",
        token=token,
        guest_name="Alex",
        guest_email="alex@example.com",
        title="Project conversation",
        note="A short introduction.",
        guest_timezone="America/New_York",
        duration_minutes=30,
        expires_at=datetime.now(UTC) + timedelta(days=3),
        slots=[
            (
                datetime(2027, 1, 11, 17, 0, tzinfo=UTC),
                datetime(2027, 1, 11, 17, 30, tzinfo=UTC),
            ),
            (
                datetime(2027, 1, 12, 18, 0, tzinfo=UTC),
                datetime(2027, 1, 12, 18, 30, tzinfo=UTC),
            ),
        ],
    )
    store.mark_prepared(proposal_id, draft_id="draft-1")
    store.mark_sending(proposal_id)
    store.record_send_receipt(proposal_id, "message-1")
    store.mark_sent(proposal_id, "message-1")
    return token, proposal_id, options


class FakeCalendar:
    def __init__(self, *, conflict: bool = False):
        self.conflict = conflict
        self.create_calls = 0

    def create_event(self, proposal):
        self.create_calls += 1
        if self.conflict:
            raise CalendarConflict("That time was just taken. Please choose another option.")
        return {
            "id": "event-1",
            "htmlLink": "https://calendar.example/event-1",
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
        }

    def find_event(self, _proposal_id, _start, _end):
        return None


class FakeGmail:
    def __init__(self, *, send_error: BookingError | None = None, draft_exists: bool = True):
        self.send_error = send_error
        self.draft_still_exists = draft_exists
        self.create_calls = 0
        self.send_calls = 0
        self.verify_calls = 0

    def create_email_draft(self, **_kwargs):
        self.create_calls += 1
        return {"draft_id": "draft-1"}

    def send_draft(self, _draft_id):
        self.send_calls += 1
        if self.send_error:
            raise self.send_error
        return {"messageId": "message-1"}

    def draft_exists(self, _draft_id):
        return self.draft_still_exists

    def find_sent_reference(self, _reference):
        return ""

    def verify_sent(self, _message_id, **_kwargs):
        self.verify_calls += 1

    @staticmethod
    def _message_id(payload):
        return payload.get("messageId", "")

    def delete_draft(self, _draft_id):
        pass


class BookingCoreTests(unittest.TestCase):
    def test_settings_include_writable_and_additional_busy_calendars(self):
        settings = Settings.from_env(
            {
                "BOOKING_CALENDAR_ID": "owner@example.com",
                "BOOKING_BUSY_CALENDAR_IDS": (
                    "owner@example.com,other@example.com, other@example.com"
                ),
            },
            require_secrets=False,
        )
        self.assertEqual(
            settings.busy_calendar_ids,
            ("owner@example.com", "other@example.com"),
        )

    def test_gog_receives_file_keyring_password_without_systemd_environment_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            completed = __import__("subprocess").CompletedProcess(
                args=[], returncode=0, stdout='{"messages": []}', stderr=""
            )
            with patch("booking_core.subprocess.run", return_value=completed) as run:
                GogClient(settings).gmail_ready()

            environment = run.call_args.kwargs["env"]
            self.assertEqual(environment["GOG_KEYRING_PASSWORD"], "keyring-test-password")
            self.assertEqual(environment["GOG_ACCOUNT"], "assistant@example.com")
            self.assertNotIn("keyring-test-password", repr(settings))

    def test_freebusy_merges_every_configured_calendar(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = replace(
                settings_for(Path(temporary)),
                busy_calendar_ids=("owner@example.com", "other@example.com"),
            )
            client = GogClient(settings)
            response = {
                "calendars": {
                    "owner@example.com": {
                        "busy": [
                            {
                                "start": "2027-01-11T16:00:00Z",
                                "end": "2027-01-11T17:00:00Z",
                            }
                        ]
                    },
                    "other@example.com": {
                        "busy": [
                            {
                                "start": "2027-01-11T19:00:00Z",
                                "end": "2027-01-11T20:00:00Z",
                            }
                        ]
                    },
                }
            }
            with patch.object(client, "run", return_value=response) as run:
                periods = client.busy_periods(
                    datetime(2027, 1, 11, 15, 0, tzinfo=UTC),
                    datetime(2027, 1, 12, 0, 0, tzinfo=UTC),
                )

            self.assertEqual(len(periods), 2)
            self.assertEqual(
                run.call_args.args[0][2],
                "owner@example.com,other@example.com",
            )

    def test_freebusy_fails_closed_when_any_calendar_is_unreadable(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = replace(
                settings_for(Path(temporary)),
                busy_calendar_ids=("owner@example.com", "other@example.com"),
            )
            client = GogClient(settings)
            response = {
                "calendars": {
                    "owner@example.com": {"busy": []},
                    "other@example.com": {"errors": [{"reason": "notFound"}]},
                }
            }
            with patch.object(client, "run", return_value=response):
                with self.assertRaisesRegex(BookingError, "could not be checked"):
                    client.busy_periods(
                        datetime(2027, 1, 11, 15, 0, tzinfo=UTC),
                        datetime(2027, 1, 12, 0, 0, tzinfo=UTC),
                    )

    def test_store_migrates_existing_database_for_recurring_proposals(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "bookings.sqlite3"
            store = BookingStore(database)
            with store.connect() as connection:
                connection.execute("ALTER TABLE proposals DROP COLUMN recurrence_rule")
                connection.execute("ALTER TABLE proposals DROP COLUMN recurrence_until")

            migrated = BookingStore(database)
            with migrated.connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(proposals)")
                }
            self.assertIn("recurrence_rule", columns)
            self.assertIn("recurrence_until", columns)

    def test_candidate_slots_respect_buffer_and_spread_across_days(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            busy = [
                (
                    datetime(2027, 1, 11, 16, 0, tzinfo=UTC),
                    datetime(2027, 1, 11, 17, 0, tzinfo=UTC),
                )
            ]
            slots = candidate_slots(
                settings,
                range_start=date(2027, 1, 11),
                range_end=date(2027, 1, 13),
                duration_minutes=30,
                busy_periods=busy,
                maximum=3,
                now=datetime(2027, 1, 10, tzinfo=UTC),
            )
            local_dates = [slot[0].astimezone().date() for slot in slots]
            self.assertEqual(len(slots), 3)
            self.assertEqual(len(set(local_dates)), 3)
            self.assertGreaterEqual(slots[0][0], datetime(2027, 1, 11, 17, 15, tzinfo=UTC))

    def test_recurring_slots_reject_a_time_when_any_occurrence_conflicts(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            busy = [
                (
                    datetime(2027, 1, 13, 16, 0, tzinfo=UTC),
                    datetime(2027, 1, 13, 16, 30, tzinfo=UTC),
                )
            ]
            slots = candidate_recurring_slots(
                settings,
                range_start=date(2027, 1, 6),
                recurrence_until=date(2027, 1, 27),
                weekday=2,
                duration_minutes=30,
                busy_periods=busy,
                maximum=3,
                now=datetime(2027, 1, 1, tzinfo=UTC),
            )

            self.assertEqual(len(slots), 3)
            for start, end in slots:
                occurrences = proposal_occurrences(
                    {
                        "starts_at": start.isoformat(),
                        "ends_at": end.isoformat(),
                        "recurrence_rule": weekly_rrule(date(2027, 1, 27)),
                        "recurrence_until": "2027-01-27",
                    },
                    settings.owner_timezone,
                )
                self.assertFalse(
                    any(
                        occurrence_start
                        < busy[0][1] + timedelta(minutes=settings.buffer_minutes)
                        and occurrence_end
                        > busy[0][0] - timedelta(minutes=settings.buffer_minutes)
                        for occurrence_start, occurrence_end in occurrences
                    )
                )

    def test_recurring_email_has_buttons_and_full_series_description(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            store = BookingStore(settings.database_path)
            token = "R" * 48
            proposal_id, options = store.create_proposal(
                dedupe_key="weekly-email",
                token=token,
                guest_name="Alex",
                guest_email="alex@example.com",
                title="Weekly sales conversation",
                note="",
                guest_timezone="America/Denver",
                duration_minutes=45,
                expires_at=datetime.now(UTC) + timedelta(days=3),
                slots=[
                    (
                        datetime(2027, 1, 6, 17, 0, tzinfo=UTC),
                        datetime(2027, 1, 6, 17, 45, tzinfo=UTC),
                    ),
                    (
                        datetime(2027, 1, 6, 20, 0, tzinfo=UTC),
                        datetime(2027, 1, 6, 20, 45, tzinfo=UTC),
                    ),
                ],
                recurrence_rule=weekly_rrule(date(2027, 3, 31)),
                recurrence_until="2027-03-31",
            )
            proposal = store.get_by_id(proposal_id)
            assert proposal is not None

            plain, email_html = render_email(settings, token=token, proposal=proposal)
            self.assertIn("Every Wednesday", plain)
            self.assertIn("through March 31, 2027", plain)
            self.assertEqual(email_html.count(">Choose</a>"), 2)
            for option in options:
                self.assertIn(option["id"], email_html)
            calendar_file = render_ics(settings, proposal, options[0])
            self.assertIn(b"RRULE:FREQ=WEEKLY;UNTIL=20270331T235959Z", calendar_file)

    def test_create_event_rechecks_whole_series_and_passes_rrule(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            proposal = {
                "id": "proposal-1",
                "guest_name": "Alex",
                "guest_email": "alex@example.com",
                "title": "Weekly conversation",
                "note": "",
                "starts_at": "2027-01-06T17:00:00Z",
                "ends_at": "2027-01-06T17:45:00Z",
                "recurrence_rule": weekly_rrule(date(2027, 1, 27)),
                "recurrence_until": "2027-01-27",
            }
            client = GogClient(settings)
            responses = [
                {"events": []},
                {"calendars": {settings.calendar_id: {"busy": []}}},
                {"event": {"id": "event-1"}},
            ]
            with patch.object(client, "run", side_effect=responses) as run:
                event = client.create_event(proposal)

            self.assertEqual(event["id"], "event-1")
            create_arguments = run.call_args_list[-1].args[0]
            self.assertIn("--rrule", create_arguments)
            self.assertIn(proposal["recurrence_rule"], create_arguments)
            freebusy_arguments = run.call_args_list[1].args[0]
            self.assertIn("2027-01-27", " ".join(freebusy_arguments))

    def test_create_event_blocks_when_later_recurrence_is_busy(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            proposal = {
                "id": "proposal-2",
                "guest_name": "Alex",
                "guest_email": "alex@example.com",
                "title": "Weekly conversation",
                "note": "",
                "starts_at": "2027-01-06T17:00:00Z",
                "ends_at": "2027-01-06T17:45:00Z",
                "recurrence_rule": weekly_rrule(date(2027, 1, 27)),
                "recurrence_until": "2027-01-27",
            }
            client = GogClient(settings)
            responses = [
                {"events": []},
                {
                    "calendars": {
                        settings.calendar_id: {
                            "busy": [
                                {
                                    "start": "2027-01-20T17:15:00Z",
                                    "end": "2027-01-20T18:00:00Z",
                                }
                            ]
                        }
                    }
                },
            ]
            with patch.object(client, "run", side_effect=responses) as run:
                with self.assertRaisesRegex(CalendarConflict, "recurring"):
                    client.create_event(proposal)

            self.assertEqual(run.call_count, 2)

    def test_store_hashes_bearer_token_and_blocks_competing_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = BookingStore(Path(temporary) / "bookings.sqlite3")
            token, proposal_id, options = create_sent_proposal(store)
            raw_database = store.path.read_bytes()
            self.assertNotIn(token.encode("ascii"), raw_database)

            first = store.claim(token, options[0]["id"])
            self.assertEqual(first["id"], proposal_id)
            with self.assertRaisesRegex(BookingError, "another time"):
                store.claim(token, options[1]["id"])

    def test_email_escapes_untrusted_fields_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            store = BookingStore(settings.database_path)
            token, proposal_id, _options = create_sent_proposal(store)
            proposal = store.get_by_id(proposal_id)
            assert proposal is not None
            proposal["guest_name"] = '<script>alert("x")</script>'
            plain, email_html = render_email(settings, token=token, proposal=proposal)
            self.assertNotIn("<script>", email_html)
            self.assertIn("&lt;script&gt;", email_html)
            self.assertIn("Nothing is booked until you confirm", plain)
            self.assertIn("https://booking.example.com/book/", email_html)

    def test_delivery_persists_gmail_receipt_before_claiming_sent(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            store = BookingStore(settings.database_path)
            proposal_id, _options = store.create_proposal(
                dedupe_key="delivery-proof",
                token="B" * 48,
                guest_name="Alex",
                guest_email="alex@example.com",
                title="Project conversation",
                note="",
                guest_timezone="America/New_York",
                duration_minutes=30,
                expires_at=datetime.now(UTC) + timedelta(days=3),
                slots=[
                    (
                        datetime(2027, 1, 11, 17, 0, tzinfo=UTC),
                        datetime(2027, 1, 11, 17, 30, tzinfo=UTC),
                    )
                ],
            )
            proposal = store.get_by_id(proposal_id)
            assert proposal is not None
            gmail = FakeGmail()

            result = deliver_proposal(
                client=gmail,
                store=store,
                proposal=proposal,
                plain_body="plain",
                html_body="<p>html</p>",
                subject="A few times with the calendar owner",
                state_dir=settings.state_dir,
            )

            self.assertEqual(result["status"], "sent")
            persisted = store.get_by_id(proposal_id)
            assert persisted is not None
            self.assertEqual(persisted["delivery_status"], "verified")
            self.assertEqual(persisted["gmail_draft_id"], "draft-1")
            self.assertEqual(persisted["gmail_message_id"], "message-1")
            self.assertEqual(gmail.create_calls, 1)
            self.assertEqual(gmail.send_calls, 1)
            self.assertEqual(gmail.verify_calls, 1)

    def test_uncertain_send_is_preserved_and_not_automatically_duplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = settings_for(Path(temporary))
            store = BookingStore(settings.database_path)
            proposal_id, _options = store.create_proposal(
                dedupe_key="delivery-uncertain",
                token="C" * 48,
                guest_name="Alex",
                guest_email="alex@example.com",
                title="Project conversation",
                note="",
                guest_timezone="America/New_York",
                duration_minutes=30,
                expires_at=datetime.now(UTC) + timedelta(days=3),
                slots=[
                    (
                        datetime(2027, 1, 11, 17, 0, tzinfo=UTC),
                        datetime(2027, 1, 11, 17, 30, tzinfo=UTC),
                    )
                ],
            )
            proposal = store.get_by_id(proposal_id)
            assert proposal is not None
            gmail = FakeGmail(
                send_error=BookingError("connection dropped"),
                draft_exists=False,
            )

            with self.assertRaises(DeliveryUncertain):
                deliver_proposal(
                    client=gmail,
                    store=store,
                    proposal=proposal,
                    plain_body="plain",
                    html_body="<p>html</p>",
                    subject="A few times with the calendar owner",
                    state_dir=settings.state_dir,
                )

            persisted = store.get_by_id(proposal_id)
            assert persisted is not None
            self.assertEqual(persisted["status"], "draft")
            self.assertEqual(persisted["delivery_status"], "sending")
            self.assertTrue(persisted["last_error"])


class BookingServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = settings_for(Path(self.temporary.name))
        self.store = BookingStore(self.settings.database_path)
        self.token, self.proposal_id, self.options = create_sent_proposal(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def start_server(self, calendar: FakeCalendar):
        server = build_server(replace(self.settings, listen_port=0))
        server.RequestHandlerClass.calendar = calendar
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def request(self, server, method: str, path: str, body: str = ""):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {}
        if body:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Content-Length"] = str(len(body.encode("utf-8")))
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, payload

    def test_get_is_safe_and_post_books_once(self):
        calendar = FakeCalendar()
        server, thread = self.start_server(calendar)
        option_id = self.options[0]["id"]
        try:
            status, _headers, payload = self.request(
                server, "GET", f"/book/{self.token}/{option_id}"
            )
            self.assertEqual(status, 200)
            self.assertIn(b"Yes, book this time", payload)
            self.assertEqual(calendar.create_calls, 0)

            signature = confirmation_signature(self.settings, self.token, option_id)
            form = urllib.parse.urlencode({"confirmation": signature})
            status, headers, _payload = self.request(
                server,
                "POST",
                f"/book/{self.token}/{option_id}/confirm",
                form,
            )
            self.assertEqual(status, 303)
            self.assertEqual(headers["Location"], f"{self.settings.public_base_url}/{self.token}")
            self.assertEqual(calendar.create_calls, 1)
            proposal = self.store.get_by_id(self.proposal_id)
            assert proposal is not None
            self.assertEqual(proposal["status"], "booked")

            status, _headers, payload = self.request(
                server, "GET", f"/book/{self.token}"
            )
            self.assertEqual(status, 200)
            self.assertIn(b"You are on the calendar", payload)
            self.assertNotIn(b"alex@example.com", payload)

            status, _headers, payload = self.request(
                server, "GET", f"/book/{self.token}/{option_id}.ics"
            )
            self.assertEqual(status, 200)
            self.assertIn(b"BEGIN:VCALENDAR", payload)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_conflict_releases_claim_for_another_choice(self):
        calendar = FakeCalendar(conflict=True)
        server, thread = self.start_server(calendar)
        option_id = self.options[0]["id"]
        try:
            signature = confirmation_signature(self.settings, self.token, option_id)
            form = urllib.parse.urlencode({"confirmation": signature})
            status, _headers, payload = self.request(
                server,
                "POST",
                f"/book/{self.token}/{option_id}/confirm",
                form,
            )
            self.assertEqual(status, 409)
            self.assertIn(b"just taken", payload)
            proposal = self.store.get_by_id(self.proposal_id)
            assert proposal is not None
            self.assertEqual(proposal["status"], "sent")
            self.assertIsNone(proposal["booked_option_id"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
