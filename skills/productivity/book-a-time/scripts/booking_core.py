#!/usr/bin/env python3
"""Deterministic storage, calendar, email, and rendering for book-a-time."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,80}$")
OPTION_RE = re.compile(r"^[a-f0-9]{16}$")
GMAIL_THREAD_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
RRULE_RE = re.compile(r"^RRULE:FREQ=WEEKLY;UNTIL=\d{8}T235959Z$")
ACTIVE_STATUSES = {"draft", "sent", "booking"}
WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class BookingError(RuntimeError):
    """A safe, expected booking failure."""


class CalendarConflict(BookingError):
    """The selected time is no longer available."""


class DeliveryUncertain(BookingError):
    """Gmail may have accepted a message, so an automatic resend is unsafe."""


class GogCommandError(BookingError):
    """A gog command failed with a sanitized diagnostic."""

    def __init__(self, detail: str):
        super().__init__(f"Google Workspace operation failed: {detail}")
        self.detail = detail


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BookingError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def require_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise BookingError(f"unknown IANA timezone: {value}") from error


def validate_email(value: str) -> str:
    normalized = value.strip().lower()
    if not EMAIL_RE.fullmatch(normalized) or len(normalized) > 254:
        raise BookingError("provide a valid guest email address")
    return normalized


def clean_text(value: str, *, label: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise BookingError(f"{label} must be between 1 and {maximum} characters")
    return normalized


def normalize_email_subject(value: str) -> str:
    subject = " ".join(value.split())
    while True:
        stripped = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", subject, count=1, flags=re.I)
        if stripped == subject:
            return subject.casefold()
        subject = stripped


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise BookingError(f"invalid boolean value: {value}")


def parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise BookingError(f"invalid clock time: {value}") from error


def _env_int(env: dict[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(key, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise BookingError(f"{key} must be an integer") from error
    if value < minimum or value > maximum:
        raise BookingError(f"{key} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    public_base_url: str
    signing_key: bytes
    gog_bin: str
    gog_keyring_password: str = field(repr=False)
    account: str
    calendar_id: str
    busy_calendar_ids: tuple[str, ...]
    owner_name: str
    owner_email: str
    owner_timezone: str
    workday_start: time
    workday_end: time
    workdays: frozenset[int]
    slot_increment_minutes: int
    buffer_minutes: int
    minimum_lead_hours: int
    proposal_ttl_hours: int
    with_meet: bool
    listen_host: str
    listen_port: int

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        require_secrets: bool = True,
    ) -> "Settings":
        if env is None:
            hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
            values = read_dotenv(hermes_home / ".env")
            values.update(os.environ)
        else:
            values = dict(env)
        state_dir = Path(
            values.get("BOOKING_STATE_DIR", "~/.hermes/book-a-time")
        ).expanduser()
        base = values.get(
            "BOOKING_PUBLIC_BASE_URL", "https://booking.example.com/book"
        ).strip().rstrip("/")
        parsed_base = urllib.parse.urlparse(base)
        if parsed_base.scheme != "https" or not parsed_base.netloc:
            raise BookingError("BOOKING_PUBLIC_BASE_URL must be an https URL")

        signing = values.get("BOOKING_SIGNING_KEY", "").strip()
        if require_secrets and len(signing) < 32:
            raise BookingError("BOOKING_SIGNING_KEY must contain at least 32 characters")

        account = values.get("BOOKING_GOOGLE_ACCOUNT", values.get("EMAIL_ADDRESS", "")).strip()
        calendar_id = values.get("BOOKING_CALENDAR_ID", "").strip()
        raw_busy_calendar_ids = values.get("BOOKING_BUSY_CALENDAR_IDS", "")
        busy_calendar_ids: list[str] = []
        for candidate in (calendar_id, *raw_busy_calendar_ids.split(",")):
            calendar = candidate.strip()
            if not calendar or calendar in busy_calendar_ids:
                continue
            if len(calendar) > 1024 or any(character.isspace() for character in calendar):
                raise BookingError("BOOKING_BUSY_CALENDAR_IDS contains an invalid calendar ID")
            busy_calendar_ids.append(calendar)
        owner_email = values.get("BOOKING_OWNER_EMAIL", "").strip().lower()
        if require_secrets:
            if not account:
                raise BookingError("BOOKING_GOOGLE_ACCOUNT or EMAIL_ADDRESS is required")
            if not calendar_id:
                raise BookingError("BOOKING_CALENDAR_ID is required")
            validate_email(owner_email)

        owner_timezone = values.get("BOOKING_TIMEZONE", "America/Denver").strip()
        require_timezone(owner_timezone)
        workday_start = parse_clock(values.get("BOOKING_WORKDAY_START", "09:00"))
        workday_end = parse_clock(values.get("BOOKING_WORKDAY_END", "17:00"))
        if workday_start >= workday_end:
            raise BookingError("BOOKING_WORKDAY_START must be before BOOKING_WORKDAY_END")

        raw_workdays = values.get("BOOKING_WORKDAYS", "0,1,2,3,4")
        try:
            workdays = frozenset(int(part.strip()) for part in raw_workdays.split(","))
        except ValueError as error:
            raise BookingError("BOOKING_WORKDAYS must be comma-separated integers 0-6") from error
        if not workdays or any(day < 0 or day > 6 for day in workdays):
            raise BookingError("BOOKING_WORKDAYS must contain weekdays 0-6")

        return cls(
            state_dir=state_dir,
            public_base_url=base,
            signing_key=signing.encode("utf-8"),
            gog_bin=values.get("BOOKING_GOG_BIN", "gog").strip() or "gog",
            gog_keyring_password=values.get("GOG_KEYRING_PASSWORD", ""),
            account=account,
            calendar_id=calendar_id,
            busy_calendar_ids=tuple(busy_calendar_ids),
            owner_name=clean_text(
                values.get("BOOKING_OWNER_NAME", "Calendar owner"),
                label="BOOKING_OWNER_NAME",
                maximum=80,
            ),
            owner_email=owner_email,
            owner_timezone=owner_timezone,
            workday_start=workday_start,
            workday_end=workday_end,
            workdays=workdays,
            slot_increment_minutes=_env_int(
                values, "BOOKING_SLOT_INCREMENT_MINUTES", 30, 5, 120
            ),
            buffer_minutes=_env_int(values, "BOOKING_BUFFER_MINUTES", 15, 0, 120),
            minimum_lead_hours=_env_int(
                values, "BOOKING_MINIMUM_LEAD_HOURS", 24, 0, 720
            ),
            proposal_ttl_hours=_env_int(
                values, "BOOKING_PROPOSAL_TTL_HOURS", 168, 1, 720
            ),
            with_meet=parse_bool(values.get("BOOKING_WITH_MEET"), True),
            listen_host=values.get("BOOKING_LISTEN_HOST", "127.0.0.1").strip(),
            listen_port=_env_int(values, "BOOKING_LISTEN_PORT", 8766, 1024, 65535),
        )

    @property
    def database_path(self) -> Path:
        return self.state_dir / "bookings.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT,
    token_hash TEXT NOT NULL UNIQUE,
    guest_name TEXT NOT NULL,
    guest_email TEXT NOT NULL,
    title TEXT NOT NULL,
    note TEXT NOT NULL,
    guest_timezone TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    recurrence_rule TEXT NOT NULL DEFAULT '',
    recurrence_until TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','sent','booking','booked','expired','cancelled')),
    delivery_status TEXT NOT NULL DEFAULT 'creating',
    gmail_draft_id TEXT,
    gmail_message_id TEXT,
    gmail_thread_id TEXT NOT NULL DEFAULT '',
    reply_subject TEXT NOT NULL DEFAULT '',
    sent_at TEXT,
    last_error TEXT,
    booked_option_id TEXT,
    calendar_event_id TEXT,
    calendar_event_url TEXT,
    meet_url TEXT,
    booked_at TEXT
);
CREATE TABLE IF NOT EXISTS options (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    UNIQUE(proposal_id, starts_at, ends_at)
);
CREATE INDEX IF NOT EXISTS options_proposal_idx ON options(proposal_id);
"""

PROPOSAL_MIGRATIONS = {
    "dedupe_key": "ALTER TABLE proposals ADD COLUMN dedupe_key TEXT",
    "delivery_status": (
        "ALTER TABLE proposals ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'creating'"
    ),
    "gmail_draft_id": "ALTER TABLE proposals ADD COLUMN gmail_draft_id TEXT",
    "gmail_message_id": "ALTER TABLE proposals ADD COLUMN gmail_message_id TEXT",
    "gmail_thread_id": (
        "ALTER TABLE proposals ADD COLUMN gmail_thread_id TEXT NOT NULL DEFAULT ''"
    ),
    "reply_subject": (
        "ALTER TABLE proposals ADD COLUMN reply_subject TEXT NOT NULL DEFAULT ''"
    ),
    "sent_at": "ALTER TABLE proposals ADD COLUMN sent_at TEXT",
    "last_error": "ALTER TABLE proposals ADD COLUMN last_error TEXT",
    "recurrence_rule": (
        "ALTER TABLE proposals ADD COLUMN recurrence_rule TEXT NOT NULL DEFAULT ''"
    ),
    "recurrence_until": (
        "ALTER TABLE proposals ADD COLUMN recurrence_until TEXT NOT NULL DEFAULT ''"
    ),
}


class BookingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(proposals)")
            }
            for name, migration in PROPOSAL_MIGRATIONS.items():
                if name not in columns:
                    connection.execute(migration)
            connection.execute(
                "UPDATE proposals SET dedupe_key = 'legacy:' || id WHERE dedupe_key IS NULL"
            )
            connection.execute(
                """
                UPDATE proposals SET delivery_status = 'verified'
                WHERE status IN ('sent','booking','booked') AND delivery_status = 'creating'
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS proposals_dedupe_idx ON proposals(dedupe_key)"
            )
        os.chmod(self.path, 0o600)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 20000")
        return connection

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create_proposal(
        self,
        *,
        dedupe_key: str,
        token: str,
        guest_name: str,
        guest_email: str,
        title: str,
        note: str,
        guest_timezone: str,
        duration_minutes: int,
        expires_at: datetime,
        slots: Sequence[tuple[datetime, datetime]],
        recurrence_rule: str = "",
        recurrence_until: str = "",
        gmail_thread_id: str = "",
        reply_subject: str = "",
    ) -> tuple[str, list[dict[str, str]]]:
        if recurrence_rule and not RRULE_RE.fullmatch(recurrence_rule):
            raise BookingError("unsupported recurrence rule")
        if bool(recurrence_rule) != bool(recurrence_until):
            raise BookingError("recurrence rule and end date must be provided together")
        if recurrence_until:
            try:
                until = date.fromisoformat(recurrence_until)
            except ValueError as error:
                raise BookingError("invalid recurrence end date") from error
            if recurrence_rule != weekly_rrule(until):
                raise BookingError("recurrence rule does not match its end date")
        proposal_id = secrets.token_hex(12)
        created_at = utc_now()
        options: list[dict[str, str]] = []
        for start, end in slots:
            options.append(
                {
                    "id": secrets.token_hex(8),
                    "starts_at": iso_utc(start),
                    "ends_at": iso_utc(end),
                }
            )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO proposals (
                    id, dedupe_key, token_hash, guest_name, guest_email, title, note,
                    guest_timezone, duration_minutes, recurrence_rule, recurrence_until,
                    gmail_thread_id, reply_subject, created_at, expires_at, status,
                    delivery_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 'creating')
                """,
                (
                    proposal_id,
                    dedupe_key,
                    self.token_hash(token),
                    guest_name,
                    guest_email,
                    title,
                    note,
                    guest_timezone,
                    duration_minutes,
                    recurrence_rule,
                    recurrence_until,
                    gmail_thread_id,
                    reply_subject,
                    iso_utc(created_at),
                    iso_utc(expires_at),
                ),
            )
            connection.executemany(
                "INSERT INTO options (id, proposal_id, starts_at, ends_at) VALUES (?, ?, ?, ?)",
                [
                    (option["id"], proposal_id, option["starts_at"], option["ends_at"])
                    for option in options
                ],
            )
        return proposal_id, options

    def delete_draft(self, proposal_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                "DELETE FROM proposals WHERE id = ? AND status = 'draft'", (proposal_id,)
            ).rowcount
        if changed != 1:
            raise BookingError("proposal draft could not be removed")

    def mark_prepared(self, proposal_id: str, *, draft_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE proposals
                SET delivery_status = 'prepared', gmail_draft_id = ?, last_error = NULL
                WHERE id = ? AND status = 'draft' AND delivery_status = 'creating'
                """,
                (draft_id, proposal_id),
            ).rowcount
        if changed != 1:
            raise BookingError("proposal could not be prepared for delivery")

    def mark_sending(self, proposal_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE proposals SET delivery_status = 'sending', last_error = NULL
                WHERE id = ? AND status = 'draft'
                  AND delivery_status = 'prepared'
                """,
                (proposal_id,),
            ).rowcount
        if changed != 1:
            raise BookingError("proposal is not ready to send")

    def record_send_receipt(self, proposal_id: str, message_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE proposals SET gmail_message_id = ?
                WHERE id = ? AND status = 'draft' AND delivery_status = 'sending'
                """,
                (message_id, proposal_id),
            ).rowcount
        if changed != 1:
            existing = self.get_by_id(proposal_id)
            if (
                existing is not None
                and existing["status"] == "sent"
                and existing.get("gmail_message_id") == message_id
            ):
                return
            raise BookingError("proposal could not record the Gmail receipt")

    def mark_retryable(self, proposal_id: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE proposals SET delivery_status = 'prepared', last_error = ?
                WHERE id = ? AND status = 'draft' AND delivery_status = 'sending'
                  AND gmail_message_id IS NULL
                """,
                (error[:500], proposal_id),
            )

    def mark_uncertain(self, proposal_id: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE proposals SET delivery_status = 'sending', last_error = ?
                WHERE id = ? AND status = 'draft' AND delivery_status = 'sending'
                """,
                (error[:500], proposal_id),
            )

    def mark_sent(self, proposal_id: str, message_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE proposals
                SET status = 'sent', delivery_status = 'verified', gmail_message_id = ?,
                    sent_at = ?, last_error = NULL
                WHERE id = ? AND status = 'draft' AND delivery_status = 'sending'
                """,
                (message_id, iso_utc(utc_now()), proposal_id),
            ).rowcount
        if changed != 1:
            existing = self.get_by_id(proposal_id)
            if (
                existing is not None
                and existing["status"] == "sent"
                and existing.get("gmail_message_id") == message_id
            ):
                return
            raise BookingError("proposal could not be marked sent")

    def get_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM proposals WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
        return self.get_by_id(row["id"]) if row is not None else None

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        if not TOKEN_RE.fullmatch(token):
            return None
        with self.connect() as connection:
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE token_hash = ?",
                (self.token_hash(token),),
            ).fetchone()
            if proposal is None:
                return None
            options = connection.execute(
                "SELECT * FROM options WHERE proposal_id = ? ORDER BY starts_at",
                (proposal["id"],),
            ).fetchall()
        result = dict(proposal)
        result["options"] = [dict(option) for option in options]
        if result["status"] in ACTIVE_STATUSES and parse_instant(result["expires_at"]) <= utc_now():
            self.expire(result["id"])
            result["status"] = "expired"
        return result

    def expire(self, proposal_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE proposals SET status = 'expired'
                WHERE id = ? AND status IN ('draft','sent','booking')
                """,
                (proposal_id,),
            )

    def claim(self, token: str, option_id: str) -> dict[str, Any]:
        if not OPTION_RE.fullmatch(option_id):
            raise BookingError("invalid option")
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE token_hash = ?",
                (self.token_hash(token),),
            ).fetchone()
            if proposal is None:
                raise BookingError("booking link not found")
            if parse_instant(proposal["expires_at"]) <= utc_now():
                connection.execute(
                    "UPDATE proposals SET status = 'expired' WHERE id = ?", (proposal["id"],)
                )
                connection.commit()
                raise BookingError("booking link expired")
            if proposal["status"] == "booked":
                connection.commit()
                result = dict(proposal)
                result["already_booked"] = True
                return result
            if proposal["status"] == "booking" and proposal["booked_option_id"] != option_id:
                raise BookingError("another time is already being confirmed")
            if proposal["status"] not in {"sent", "booking"}:
                raise BookingError("booking link is not active")
            option = connection.execute(
                "SELECT * FROM options WHERE id = ? AND proposal_id = ?",
                (option_id, proposal["id"]),
            ).fetchone()
            if option is None:
                raise BookingError("time option not found")
            connection.execute(
                "UPDATE proposals SET status = 'booking', booked_option_id = ? WHERE id = ?",
                (option_id, proposal["id"]),
            )
            connection.commit()
            result = dict(proposal)
            result["option_id"] = option["id"]
            result["starts_at"] = option["starts_at"]
            result["ends_at"] = option["ends_at"]
            result["already_booked"] = False
            return result
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def release_claim(self, proposal_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE proposals
                SET status = 'sent', booked_option_id = NULL
                WHERE id = ? AND status = 'booking'
                """,
                (proposal_id,),
            )

    def complete(
        self,
        proposal_id: str,
        option_id: str,
        *,
        event_id: str,
        event_url: str,
        meet_url: str,
    ) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE proposals
                SET status = 'booked', booked_option_id = ?, calendar_event_id = ?,
                    calendar_event_url = ?, meet_url = ?, booked_at = ?
                WHERE id = ? AND status = 'booking'
                """,
                (
                    option_id,
                    event_id,
                    event_url,
                    meet_url,
                    iso_utc(utc_now()),
                    proposal_id,
                ),
            ).rowcount
        if changed != 1:
            raise BookingError("booking state changed before completion")

    def get_by_id(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                return None
            options = connection.execute(
                "SELECT * FROM options WHERE proposal_id = ? ORDER BY starts_at",
                (proposal_id,),
            ).fetchall()
        result = dict(proposal)
        result["options"] = [dict(option) for option in options]
        return result


class GogClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, arguments: Sequence[str]) -> dict[str, Any]:
        command = [
            self.settings.gog_bin,
            "--account",
            self.settings.account,
            "--json",
            "--no-input",
            *arguments,
        ]
        environment = os.environ.copy()
        environment["GOG_ACCOUNT"] = self.settings.account
        environment["GOG_TIMEZONE"] = self.settings.owner_timezone
        if self.settings.gog_keyring_password:
            environment["GOG_KEYRING_PASSWORD"] = self.settings.gog_keyring_password
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            env=environment,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            safe_detail = detail[-1][:300] if detail else "unknown gog failure"
            raise GogCommandError(safe_detail)
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise BookingError("Google Workspace returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise BookingError("Google Workspace returned an unexpected response")
        return parsed

    @staticmethod
    def _message_id(payload: dict[str, Any]) -> str:
        direct = payload.get("messageId") or payload.get("message_id")
        if isinstance(direct, str):
            return direct.strip()
        message = payload.get("message")
        if isinstance(message, dict):
            value = message.get("id") or message.get("messageId")
            if isinstance(value, str):
                return value.strip()
        value = payload.get("id")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _draft_id(payload: dict[str, Any]) -> str:
        value = payload.get("draftId") or payload.get("draft_id")
        if isinstance(value, str):
            return value.strip()
        draft = payload.get("draft")
        if isinstance(draft, dict) and isinstance(draft.get("id"), str):
            return draft["id"].strip()
        return ""

    @staticmethod
    def _message_headers(message: dict[str, Any]) -> dict[str, str]:
        payload = message.get("payload", {})
        raw_headers = payload.get("headers", []) if isinstance(payload, dict) else []
        if not isinstance(raw_headers, list):
            return {}
        return {
            str(item.get("name", "")).casefold(): str(item.get("value", ""))
            for item in raw_headers
            if isinstance(item, dict) and item.get("name")
        }

    def validate_reply_thread(
        self,
        thread_id: str,
        *,
        guest_email: str,
        expected_subject: str = "",
    ) -> dict[str, str]:
        if not GMAIL_THREAD_RE.fullmatch(thread_id):
            raise BookingError("invalid Gmail thread ID")
        payload = self.run(["gmail", "thread", "get", thread_id])
        thread = payload.get("thread", payload)
        if not isinstance(thread, dict):
            raise BookingError("Gmail returned no matching thread")
        actual_id = str(thread.get("id", ""))
        if actual_id != thread_id:
            raise BookingError("Gmail returned a different thread than requested")
        messages = thread.get("messages", [])
        if not isinstance(messages, list) or not messages:
            raise BookingError("Gmail thread has no messages")

        participants: set[str] = set()
        latest_subject = ""
        for message in messages:
            if not isinstance(message, dict):
                continue
            headers = self._message_headers(message)
            latest_subject = headers.get("subject", latest_subject)
            participants.update(
                address.casefold()
                for _name, address in getaddresses(
                    [headers.get("from", ""), headers.get("to", ""), headers.get("cc", "")]
                )
                if address
            )

        required = {
            guest_email.casefold(),
            self.settings.account.casefold(),
            self.settings.owner_email.casefold(),
        }
        if not required.issubset(participants):
            raise BookingError(
                "the Gmail thread must include the guest, assistant, and calendar owner"
            )
        if not latest_subject:
            raise BookingError("Gmail thread has no subject")
        if expected_subject and normalize_email_subject(latest_subject) != normalize_email_subject(
            expected_subject
        ):
            raise BookingError("Gmail thread subject changed before delivery")
        return {"thread_id": thread_id, "subject": latest_subject}

    def find_reply_thread(self, *, subject: str, guest_email: str) -> dict[str, str]:
        normalized_subject = normalize_email_subject(subject)
        if not normalized_subject:
            raise BookingError("provide the source email subject for a thread reply")
        query = (
            f"in:anywhere newer_than:365d "
            f"{{from:{guest_email} to:{guest_email} cc:{guest_email}}}"
        )
        payload = self.run(["gmail", "search", query, "--max", "20"])
        threads = payload.get("threads", [])
        if not isinstance(threads, list):
            raise BookingError("Gmail search returned no thread list")

        matches: list[dict[str, str]] = []
        seen: set[str] = set()
        for candidate in threads:
            if not isinstance(candidate, dict):
                continue
            thread_id = str(candidate.get("id", ""))
            candidate_subject = str(candidate.get("subject", ""))
            if thread_id in seen or normalize_email_subject(candidate_subject) != normalized_subject:
                continue
            seen.add(thread_id)
            try:
                matches.append(
                    self.validate_reply_thread(
                        thread_id,
                        guest_email=guest_email,
                        expected_subject=subject,
                    )
                )
            except BookingError:
                continue
        if not matches:
            raise BookingError(
                "no eligible Gmail thread matched that subject and guest; no email was sent"
            )
        if len(matches) != 1:
            raise BookingError(
                "multiple eligible Gmail threads matched; provide --reply-thread-id"
            )
        return matches[0]

    def busy_periods(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        calendar_ids = self.settings.busy_calendar_ids or (self.settings.calendar_id,)
        payload = self.run(
            [
                "calendar",
                "freebusy",
                ",".join(calendar_ids),
                "--from",
                iso_utc(start),
                "--to",
                iso_utc(end),
            ]
        )
        calendars = payload.get("calendars", {})
        if not isinstance(calendars, dict):
            raise BookingError("free/busy response did not include configured calendars")
        periods: list[tuple[datetime, datetime]] = []
        for calendar_id in calendar_ids:
            calendar = calendars.get(calendar_id)
            if calendar is None and len(calendar_ids) == 1 and len(calendars) == 1:
                calendar = next(iter(calendars.values()))
            if not isinstance(calendar, dict):
                raise BookingError("free/busy response omitted a configured calendar")
            if calendar.get("errors"):
                raise BookingError("a configured calendar could not be checked for conflicts")
            for period in calendar.get("busy", []):
                if not isinstance(period, dict) or "start" not in period or "end" not in period:
                    continue
                periods.append((parse_instant(period["start"]), parse_instant(period["end"])))
        return periods

    def is_free(self, start: datetime, end: datetime) -> bool:
        buffer = timedelta(minutes=self.settings.buffer_minutes)
        return not overlaps_any(start, end, self.busy_periods(start - buffer, end + buffer), buffer)

    def find_event(self, proposal_id: str, start: datetime, end: datetime) -> dict[str, Any] | None:
        payload = self.run(
            [
                "calendar",
                "events",
                self.settings.calendar_id,
                "--from",
                iso_utc(start - timedelta(days=1)),
                "--to",
                iso_utc(end + timedelta(days=1)),
                "--private-prop-filter",
                f"bookingProposal={proposal_id}",
                "--max",
                "5",
            ]
        )
        events = payload.get("events", payload.get("items", []))
        if isinstance(events, list) and events:
            return events[0] if isinstance(events[0], dict) else None
        return None

    def create_event(self, proposal: dict[str, Any]) -> dict[str, Any]:
        start = parse_instant(proposal["starts_at"])
        end = parse_instant(proposal["ends_at"])
        existing = self.find_event(proposal["id"], start, end)
        if existing is not None:
            return existing
        occurrences = proposal_occurrences(proposal, self.settings.owner_timezone)
        buffer = timedelta(minutes=self.settings.buffer_minutes)
        busy = self.busy_periods(
            occurrences[0][0] - buffer,
            occurrences[-1][1] + buffer,
        )
        if any(
            overlaps_any(occurrence_start, occurrence_end, busy, buffer)
            for occurrence_start, occurrence_end in occurrences
        ):
            if proposal.get("recurrence_rule"):
                raise CalendarConflict(
                    "One of those recurring times was just taken. Please choose another option."
                )
            raise CalendarConflict("That time was just taken. Please choose another option.")

        description = (
            f"Scheduled through the booking assistant for {self.settings.owner_name}.\n\n"
            f"Guest: {proposal['guest_name']} <{proposal['guest_email']}>"
        )
        if proposal.get("note"):
            description += f"\n\nContext: {proposal['note']}"
        arguments = [
            "calendar",
            "create",
            self.settings.calendar_id,
            "--summary",
            proposal["title"],
            "--from",
            iso_utc(start),
            "--to",
            iso_utc(end),
            "--timezone",
            self.settings.owner_timezone,
            "--description",
            description,
            "--attendees",
            proposal["guest_email"],
            "--send-updates",
            "all",
            "--guests-can-modify=false",
            "--guests-can-invite=false",
            "--private-prop",
            f"bookingProposal={proposal['id']}",
        ]
        if proposal.get("recurrence_rule"):
            arguments.extend(["--rrule", proposal["recurrence_rule"]])
        if self.settings.with_meet:
            arguments.append("--with-meet")
        payload = self.run(arguments)
        event = payload.get("event", payload)
        if not isinstance(event, dict) or not event.get("id"):
            raise BookingError("calendar event creation returned no event id")
        return event

    def create_email_draft(
        self,
        *,
        recipient: str,
        subject: str,
        plain_body: str,
        html_body: str,
        state_dir: Path,
        reply_thread_id: str = "",
    ) -> dict[str, Any]:
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", dir=state_dir, delete=False
        ) as plain_file:
            plain_file.write(plain_body)
            plain_path = Path(plain_file.name)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".html", dir=state_dir, delete=False
        ) as html_file:
            html_file.write(html_body)
            html_path = Path(html_file.name)
        os.chmod(plain_path, 0o600)
        os.chmod(html_path, 0o600)
        try:
            arguments = ["gmail", "drafts", "create"]
            if reply_thread_id:
                self.validate_reply_thread(
                    reply_thread_id,
                    guest_email=recipient,
                    expected_subject=subject,
                )
                arguments.extend(["--thread-id", reply_thread_id, "--reply-all"])
            else:
                arguments.extend(["--to", recipient])
            arguments.extend(
                [
                    "--subject",
                    subject,
                    "--body-file",
                    str(plain_path),
                    "--body-html-file",
                    str(html_path),
                ]
            )
            response = self.run(arguments)
            draft_id = self._draft_id(response)
            if not draft_id:
                raise BookingError("Gmail created no durable draft ID")
            return {"draft_id": draft_id, "response": response}
        finally:
            plain_path.unlink(missing_ok=True)
            html_path.unlink(missing_ok=True)

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        return self.run(["gmail", "drafts", "send", draft_id])

    def delete_draft(self, draft_id: str) -> None:
        self.run(["gmail", "drafts", "delete", draft_id, "--force"])

    def draft_exists(self, draft_id: str) -> bool:
        try:
            self.run(["gmail", "drafts", "get", draft_id])
            return True
        except GogCommandError as error:
            if re.search(r"\b(404|not found|does not exist)\b", error.detail, re.IGNORECASE):
                return False
            raise

    def verify_sent(
        self,
        message_id: str,
        *,
        recipient: str,
        subject: str,
        expected_thread_id: str = "",
    ) -> None:
        payload = self.run(
            [
                "gmail",
                "get",
                message_id,
                "--format",
                "metadata",
                "--headers",
                "To,Cc,Subject",
            ]
        )
        message = payload.get("message", payload)
        if not isinstance(message, dict):
            raise BookingError("Gmail delivery verification returned no message")
        labels = message.get("labelIds", message.get("label_ids", []))
        if not isinstance(labels, list) or "SENT" not in labels:
            raise BookingError("Gmail message is not visible in Sent")
        headers = payload.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        actual_subject = headers.get("subject", "")
        actual_to = headers.get("to", "")
        actual_cc = headers.get("cc", "")
        if not actual_subject or (not actual_to and not actual_cc):
            raw_headers = message.get("payload", {}).get("headers", [])
            if isinstance(raw_headers, list):
                flattened = {
                    str(item.get("name", "")).lower(): str(item.get("value", ""))
                    for item in raw_headers
                    if isinstance(item, dict)
                }
                actual_subject = actual_subject or flattened.get("subject", "")
                actual_to = actual_to or flattened.get("to", "")
                actual_cc = actual_cc or flattened.get("cc", "")
        recipients = {
            address.casefold()
            for _name, address in getaddresses([str(actual_to), str(actual_cc)])
        }
        if recipient.casefold() not in recipients or str(actual_subject) != subject:
            raise BookingError("Gmail Sent copy does not match the intended recipient and subject")
        if expected_thread_id:
            actual_thread_id = str(
                message.get("threadId", message.get("thread_id", payload.get("threadId", "")))
            )
            if actual_thread_id != expected_thread_id:
                raise BookingError("Gmail Sent copy was not delivered in the intended thread")
            if self.settings.owner_email.casefold() not in recipients:
                raise BookingError("Gmail thread reply did not keep the calendar owner copied")

    def gmail_ready(self) -> None:
        self.run(["gmail", "search", "in:sent newer_than:1d", "--max", "1"])

    def verify_cli_capabilities(self) -> None:
        commands = (
            ["gmail", "drafts", "create", "--help"],
            ["gmail", "drafts", "send", "--help"],
            ["gmail", "get", "--help"],
            ["calendar", "create", "--help"],
        )
        for arguments in commands:
            result = subprocess.run(
                [self.settings.gog_bin, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                raise BookingError(f"gog does not support {' '.join(arguments[:-1])}")
            if arguments[:3] == ["gmail", "drafts", "create"] and "--body-html-file" not in output:
                raise BookingError("gog Gmail drafts create lacks --body-html-file support")
            if arguments[:2] == ["calendar", "create"] and "--rrule" not in output:
                raise BookingError("gog calendar create lacks recurring-event support")

    def find_sent_reference(self, reference: str) -> str:
        payload = self.run(
            [
                "gmail",
                "messages",
                "search",
                f'in:sent "{reference}"',
                "--max",
                "2",
            ]
        )
        messages = payload.get("messages", [])
        if not isinstance(messages, list) or len(messages) != 1:
            return ""
        message = messages[0]
        if not isinstance(message, dict):
            return ""
        value = message.get("id") or message.get("messageId")
        return value.strip() if isinstance(value, str) else ""


def overlaps_any(
    start: datetime,
    end: datetime,
    busy_periods: Iterable[tuple[datetime, datetime]],
    buffer: timedelta,
) -> bool:
    for busy_start, busy_end in busy_periods:
        if start < busy_end + buffer and end > busy_start - buffer:
            return True
    return False


def candidate_slots(
    settings: Settings,
    *,
    range_start: date,
    range_end: date,
    duration_minutes: int,
    busy_periods: Sequence[tuple[datetime, datetime]],
    maximum: int,
    now: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    if range_end < range_start:
        raise BookingError("end date must not be before start date")
    if (range_end - range_start).days > 31:
        raise BookingError("booking window cannot exceed 31 days")
    if duration_minutes < 15 or duration_minutes > 240 or duration_minutes % 5:
        raise BookingError("duration must be 15-240 minutes in five-minute increments")
    if maximum < 1 or maximum > 8:
        raise BookingError("option count must be between 1 and 8")

    owner_tz = require_timezone(settings.owner_timezone)
    earliest = (now or utc_now()) + timedelta(hours=settings.minimum_lead_hours)
    duration = timedelta(minutes=duration_minutes)
    increment = timedelta(minutes=settings.slot_increment_minutes)
    buffer = timedelta(minutes=settings.buffer_minutes)
    by_day: list[list[tuple[datetime, datetime]]] = []

    day = range_start
    while day <= range_end:
        choices: list[tuple[datetime, datetime]] = []
        if day.weekday() in settings.workdays:
            local_cursor = datetime.combine(day, settings.workday_start, owner_tz)
            local_close = datetime.combine(day, settings.workday_end, owner_tz)
            while local_cursor + duration <= local_close:
                start = local_cursor.astimezone(UTC)
                end = (local_cursor + duration).astimezone(UTC)
                if start >= earliest and not overlaps_any(start, end, busy_periods, buffer):
                    choices.append((start, end))
                local_cursor += increment
        if choices:
            by_day.append(choices)
        day += timedelta(days=1)

    selected: list[tuple[datetime, datetime]] = []
    for choices in by_day:
        selected.append(choices[0])
        if len(selected) == maximum:
            return selected
    for choices in by_day:
        for choice in choices[1:]:
            selected.append(choice)
            if len(selected) == maximum:
                return sorted(selected)
    return sorted(selected)


def first_weekday_on_or_after(value: date, weekday: int) -> date:
    if weekday < 0 or weekday > 6:
        raise BookingError("weekday must be between Monday and Sunday")
    return value + timedelta(days=(weekday - value.weekday()) % 7)


def weekly_rrule(recurrence_until: date) -> str:
    return f"RRULE:FREQ=WEEKLY;UNTIL={recurrence_until.strftime('%Y%m%d')}T235959Z"


def recurring_occurrences(
    start: datetime,
    end: datetime,
    *,
    recurrence_until: date,
    timezone_name: str,
) -> list[tuple[datetime, datetime]]:
    zone = require_timezone(timezone_name)
    local_start = start.astimezone(zone)
    local_end = end.astimezone(zone)
    if recurrence_until < local_start.date():
        raise BookingError("recurrence end date must not be before the first meeting")
    if (recurrence_until - local_start.date()).days > 366:
        raise BookingError("recurring booking window cannot exceed 366 days")

    occurrences: list[tuple[datetime, datetime]] = []
    while local_start.date() <= recurrence_until:
        occurrences.append((local_start.astimezone(UTC), local_end.astimezone(UTC)))
        local_start += timedelta(days=7)
        local_end += timedelta(days=7)
    return occurrences


def proposal_occurrences(
    proposal: dict[str, Any], timezone_name: str
) -> list[tuple[datetime, datetime]]:
    start = parse_instant(proposal["starts_at"])
    end = parse_instant(proposal["ends_at"])
    recurrence_rule = str(proposal.get("recurrence_rule") or "")
    recurrence_until = str(proposal.get("recurrence_until") or "")
    if not recurrence_rule:
        return [(start, end)]
    if not RRULE_RE.fullmatch(recurrence_rule):
        raise BookingError("proposal contains an unsupported recurrence rule")
    try:
        until = date.fromisoformat(recurrence_until)
    except ValueError as error:
        raise BookingError("proposal contains an invalid recurrence end date") from error
    return recurring_occurrences(
        start,
        end,
        recurrence_until=until,
        timezone_name=timezone_name,
    )


def _spread_choices(
    choices: Sequence[tuple[datetime, datetime]], maximum: int
) -> list[tuple[datetime, datetime]]:
    if len(choices) <= maximum:
        return list(choices)
    if maximum == 1:
        return [choices[len(choices) // 2]]
    indices = [round(index * (len(choices) - 1) / (maximum - 1)) for index in range(maximum)]
    return [choices[index] for index in indices]


def candidate_recurring_slots(
    settings: Settings,
    *,
    range_start: date,
    recurrence_until: date,
    weekday: int,
    duration_minutes: int,
    busy_periods: Sequence[tuple[datetime, datetime]],
    maximum: int,
    now: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    if duration_minutes < 15 or duration_minutes > 240 or duration_minutes % 5:
        raise BookingError("duration must be 15-240 minutes in five-minute increments")
    if maximum < 1 or maximum > 8:
        raise BookingError("option count must be between 1 and 8")
    if weekday < 0 or weekday > 6:
        raise BookingError("weekday must be between Monday and Sunday")
    if weekday not in settings.workdays:
        raise BookingError(f"{WEEKDAY_NAMES[weekday]} is outside configured working days")

    owner_tz = require_timezone(settings.owner_timezone)
    first_date = first_weekday_on_or_after(range_start, weekday)
    if recurrence_until < first_date:
        raise BookingError("recurrence end date is before the first requested weekday")
    if (recurrence_until - first_date).days > 366:
        raise BookingError("recurring booking window cannot exceed 366 days")

    earliest = (now or utc_now()) + timedelta(hours=settings.minimum_lead_hours)
    duration = timedelta(minutes=duration_minutes)
    increment = timedelta(minutes=settings.slot_increment_minutes)
    buffer = timedelta(minutes=settings.buffer_minutes)
    local_cursor = datetime.combine(first_date, settings.workday_start, owner_tz)
    local_close = datetime.combine(first_date, settings.workday_end, owner_tz)
    choices: list[tuple[datetime, datetime]] = []

    while local_cursor + duration <= local_close:
        start = local_cursor.astimezone(UTC)
        end = (local_cursor + duration).astimezone(UTC)
        occurrences = recurring_occurrences(
            start,
            end,
            recurrence_until=recurrence_until,
            timezone_name=settings.owner_timezone,
        )
        if start >= earliest and all(
            not overlaps_any(
                occurrence_start,
                occurrence_end,
                busy_periods,
                buffer,
            )
            for occurrence_start, occurrence_end in occurrences
        ):
            choices.append((start, end))
        local_cursor += increment

    return _spread_choices(choices, maximum)


def display_slot(start_value: str, end_value: str, timezone_name: str) -> tuple[str, str]:
    zone = require_timezone(timezone_name)
    start = parse_instant(start_value).astimezone(zone)
    end = parse_instant(end_value).astimezone(zone)
    date_label = start.strftime("%A, %B %-d")
    time_label = f"{start.strftime('%-I:%M %p')}–{end.strftime('%-I:%M %p %Z')}"
    return date_label, time_label


def display_option(
    settings: Settings,
    proposal: dict[str, Any],
    option: dict[str, Any],
) -> tuple[str, str, str]:
    date_label, time_label = display_slot(
        option["starts_at"], option["ends_at"], proposal["guest_timezone"]
    )
    if not proposal.get("recurrence_rule"):
        return date_label, time_label, ""

    occurrence_proposal = dict(proposal)
    occurrence_proposal.update(
        starts_at=option["starts_at"],
        ends_at=option["ends_at"],
    )
    occurrences = proposal_occurrences(occurrence_proposal, settings.owner_timezone)
    guest_zone = require_timezone(proposal["guest_timezone"])
    first = occurrences[0][0].astimezone(guest_zone)
    last = occurrences[-1][0].astimezone(guest_zone)
    date_label = f"Every {first.strftime('%A')}"
    range_label = f"{first.strftime('%B %-d')} through {last.strftime('%B %-d, %Y')}"
    return date_label, time_label, range_label


def option_url(settings: Settings, token: str, option_id: str) -> str:
    return f"{settings.public_base_url}/{token}/{option_id}"


def render_email(
    settings: Settings,
    *,
    token: str,
    proposal: dict[str, Any],
) -> tuple[str, str]:
    guest_name = html.escape(proposal["guest_name"])
    owner_name = html.escape(settings.owner_name)
    title = html.escape(proposal["title"])
    timezone_name = proposal["guest_timezone"]
    rows: list[str] = []
    plain_options: list[str] = []
    for option in proposal["options"]:
        date_label, time_label, range_label = display_option(settings, proposal, option)
        url = option_url(settings, token, option["id"])
        range_html = ""
        if range_label:
            range_html = (
                '<div style="font-size:13px;color:#7b8481;line-height:19px">'
                + html.escape(range_label)
                + "</div>"
            )
        rows.append(
            """
            <tr><td style="padding:0 0 12px 0">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                     style="border:1px solid #d9dedb;border-radius:6px;background:#ffffff">
                <tr>
                  <td style="padding:16px 18px;color:#202524">
                    <div style="font-size:15px;font-weight:700;line-height:21px">{date}</div>
                    <div style="font-size:14px;color:#59625f;line-height:20px">{time}</div>
                    {date_range}
                  </td>
                  <td align="right" style="padding:12px 14px">
                    <a href="{url}" style="display:inline-block;background:#147d64;color:#ffffff;
                       text-decoration:none;font-size:14px;font-weight:700;padding:11px 16px;
                       border-radius:5px">Choose</a>
                  </td>
                </tr>
              </table>
            </td></tr>
            """.format(
                date=html.escape(date_label),
                time=html.escape(time_label),
                date_range=range_html,
                url=html.escape(url),
            )
        )
        plain_label = f"{date_label}, {time_label}"
        if range_label:
            plain_label += f" ({range_label})"
        plain_options.append(f"- {plain_label}: {url}")

    expires = parse_instant(proposal["expires_at"]).astimezone(
        require_timezone(timezone_name)
    ).strftime("%B %-d at %-I:%M %p %Z")
    note_html = ""
    if proposal.get("note"):
        note_html = (
            '<p style="margin:0 0 22px;color:#59625f;font-size:14px;line-height:21px">'
            + html.escape(proposal["note"])
            + "</p>"
        )

    meeting_kind = "recurring weekly time" if proposal.get("recurrence_rule") else "time"
    html_body = f"""<!doctype html>
<html><body style="margin:0;background:#f3f5f4;font-family:Arial,sans-serif;color:#202524">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f5f4">
<tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
       style="max-width:600px;background:#ffffff;border:1px solid #d9dedb;border-radius:8px">
  <tr><td style="height:7px;background:#147d64"></td></tr>
  <tr><td style="padding:30px 34px 10px">
    <div style="display:grid;place-items:center;width:48px;height:48px;border-radius:50%;margin-bottom:22px;background:#147d64;color:#fff;font-size:18px;font-weight:700">S</div>
    <div style="color:#ef6a4c;font-size:12px;font-weight:700;text-transform:uppercase">Scheduling</div>
    <h1 style="margin:8px 0 12px;font-size:27px;line-height:34px;letter-spacing:0">Pick a time with {owner_name}</h1>
    <p style="margin:0 0 12px;color:#59625f;font-size:15px;line-height:23px">Hi {guest_name},</p>
    <p style="margin:0 0 22px;color:#59625f;font-size:15px;line-height:23px">
      Here are a few open {meeting_kind}s for <strong>{title}</strong>. Choose one to review it, then confirm.
    </p>
    {note_html}
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">{''.join(rows)}</table>
    <p style="margin:12px 0 0;color:#7b8481;font-size:12px;line-height:18px">
      Times shown in {html.escape(timezone_name.replace('_', ' '))}. Links expire {html.escape(expires)}.
    </p>
  </td></tr>
  <tr><td style="padding:20px 34px 28px;color:#7b8481;font-size:12px;line-height:18px;border-top:1px solid #edf0ee">
    Sent by the scheduling assistant for {owner_name}. Nothing is booked until you confirm.
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    plain_body = "\n".join(
        [
            f"Hi {proposal['guest_name']},",
            "",
            f"Here are a few open {meeting_kind}s with {settings.owner_name} for {proposal['title']}.",
            "Choose one to review it, then confirm:",
            "",
            *plain_options,
            "",
            f"Times shown in {timezone_name}. Links expire {expires}.",
            "Nothing is booked until you confirm.",
            "",
            f"Scheduling assistant for {settings.owner_name}",
            f"Reference: BK-{proposal['id']}",
        ]
    )
    html_body = html_body.replace(
        "</body></html>",
        (
            f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
            f"BK-{html.escape(proposal['id'])}</div></body></html>"
        ),
    )
    return plain_body, html_body


def confirmation_signature(settings: Settings, token: str, option_id: str) -> str:
    return hmac.new(
        settings.signing_key,
        f"confirm\0{token}\0{option_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def valid_confirmation(
    settings: Settings, token: str, option_id: str, supplied: str
) -> bool:
    expected = confirmation_signature(settings, token, option_id)
    return bool(supplied) and hmac.compare_digest(expected, supplied)


def booked_option(proposal: dict[str, Any]) -> dict[str, Any] | None:
    option_id = proposal.get("booked_option_id")
    for option in proposal.get("options", []):
        if option["id"] == option_id:
            return option
    return None


def _page_shell(settings: Settings, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{html.escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f2f4f3;color:#202524;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{min-height:100vh;display:grid;place-items:center;padding:24px 16px}}
.panel{{width:min(100%,620px);background:#fff;border:1px solid #d9dedb;border-top:7px solid #147d64;border-radius:8px;padding:30px}}
.brand{{display:flex;align-items:center;gap:12px;margin-bottom:26px}} .brand-mark{{display:grid;place-items:center;width:48px;height:48px;border-radius:50%;background:#147d64;color:#fff;font-size:18px;font-weight:700}}
.brand strong{{font-size:14px}} .brand span{{display:block;color:#707976;font-size:12px;margin-top:2px}}
.eyebrow{{color:#ef6a4c;font-size:12px;font-weight:800;text-transform:uppercase}}
h1{{font-size:30px;line-height:1.15;letter-spacing:0;margin:8px 0 12px}} p{{color:#59625f;line-height:1.55;margin:0 0 20px}}
.slot{{margin:22px 0;padding:18px;border:1px solid #d9dedb;border-left:5px solid #147d64;border-radius:6px}} .slot strong{{display:block;font-size:17px}} .slot span{{display:block;color:#59625f;margin-top:4px}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}} button,.button{{appearance:none;border:0;border-radius:5px;padding:13px 18px;font:700 15px inherit;text-decoration:none;cursor:pointer}}
.primary{{background:#147d64;color:#fff}} .secondary{{background:#fff;color:#202524;border:1px solid #bfc7c3}} .primary:hover{{background:#0f6652}}
.note{{font-size:13px;color:#7b8481;margin-top:22px}} .success{{color:#147d64}} .error{{color:#b33b2e}}
@media(max-width:520px){{.panel{{padding:24px 20px}}h1{{font-size:26px}}.actions{{display:grid}}button,.button{{width:100%;text-align:center}}}}
</style></head><body><main><section class="panel">
<div class="brand"><div class="brand-mark" aria-hidden="true">S</div><div><strong>Scheduling assistant</strong><span>Scheduling for {html.escape(settings.owner_name)}</span></div></div>
{body}</section></main></body></html>"""


def render_confirmation_page(
    settings: Settings,
    token: str,
    proposal: dict[str, Any],
    option: dict[str, Any],
) -> str:
    date_label, time_label, range_label = display_option(settings, proposal, option)
    action = option_url(settings, token, option["id"]) + "/confirm"
    signature = confirmation_signature(settings, token, option["id"])
    range_html = f"<span>{html.escape(range_label)}</span>" if range_label else ""
    meeting_word = "series" if proposal.get("recurrence_rule") else "time"
    body = f"""
<div class="eyebrow">Confirm your meeting</div>
<h1>Does this {meeting_word} work?</h1>
<p>You are booking <strong>{html.escape(proposal['title'])}</strong> with {html.escape(settings.owner_name)}.</p>
<div class="slot"><strong>{html.escape(date_label)}</strong><span>{html.escape(time_label)}</span>{range_html}</div>
<form method="post" action="{html.escape(action)}">
<input type="hidden" name="confirmation" value="{signature}">
<div class="actions"><button class="primary" type="submit">Yes, book this {meeting_word}</button>
<a class="button secondary" href="{html.escape(settings.public_base_url + '/' + token)}">Choose another</a></div>
</form>
<div class="note">The calendar will be checked once more before the invitation is sent.</div>"""
    return _page_shell(settings, "Confirm meeting", body)


def render_options_page(settings: Settings, token: str, proposal: dict[str, Any]) -> str:
    if proposal["status"] == "booked":
        return render_success_page(settings, token, proposal)
    if proposal["status"] in {"expired", "cancelled", "draft"}:
        body = """
<div class="eyebrow error">Link unavailable</div><h1>This invitation is no longer active.</h1>
<p>Please reply to the email for a fresh set of times.</p>"""
        return _page_shell(settings, "Invitation unavailable", body)
    options = []
    for option in proposal["options"]:
        date_label, time_label, range_label = display_option(settings, proposal, option)
        range_html = f"<span>{html.escape(range_label)}</span>" if range_label else ""
        options.append(
            f'<div class="slot"><strong>{html.escape(date_label)}</strong><span>{html.escape(time_label)}</span>{range_html}'
            f'<div class="actions"><a class="button primary" href="{html.escape(option_url(settings, token, option["id"]))}">Review this time</a></div></div>'
        )
    body = f"""
<div class="eyebrow">Available times</div><h1>Choose what works.</h1>
<p>Pick a time for <strong>{html.escape(proposal['title'])}</strong> with {html.escape(settings.owner_name)}.</p>
{''.join(options)}<div class="note">Times shown in {html.escape(proposal['guest_timezone'].replace('_', ' '))}.</div>"""
    return _page_shell(settings, "Choose a time", body)


def _calendar_links(settings: Settings, proposal: dict[str, Any], option: dict[str, Any]) -> tuple[str, str]:
    start = parse_instant(option["starts_at"])
    end = parse_instant(option["ends_at"])
    google_query = urllib.parse.urlencode(
        {
            "action": "TEMPLATE",
            "text": proposal["title"],
            "dates": start.strftime("%Y%m%dT%H%M%SZ") + "/" + end.strftime("%Y%m%dT%H%M%SZ"),
            "details": f"Scheduled through the booking assistant for {settings.owner_name}.",
            "location": proposal.get("meet_url", ""),
        }
    )
    outlook_query = urllib.parse.urlencode(
        {
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": proposal["title"],
            "startdt": iso_utc(start),
            "enddt": iso_utc(end),
            "body": f"Scheduled through the booking assistant for {settings.owner_name}.",
            "location": proposal.get("meet_url", ""),
        }
    )
    return (
        "https://calendar.google.com/calendar/render?" + google_query,
        "https://outlook.live.com/calendar/0/deeplink/compose?" + outlook_query,
    )


def render_success_page(settings: Settings, token: str, proposal: dict[str, Any]) -> str:
    option = booked_option(proposal)
    if option is None:
        return _page_shell(
            settings,
            "Meeting booked",
            '<div class="eyebrow success">Booked</div><h1>You are all set.</h1>',
        )
    date_label, time_label, range_label = display_option(settings, proposal, option)
    ics_url = option_url(settings, token, option["id"]) + ".ics"
    meet = ""
    if proposal.get("meet_url"):
        meet = f'<a class="button primary" href="{html.escape(proposal["meet_url"])}">Open Google Meet</a>'
    range_html = f"<span>{html.escape(range_label)}</span>" if range_label else ""
    if proposal.get("recurrence_rule"):
        invitation_copy = "A recurring calendar invitation has been sent."
        calendar_actions = ""
        if proposal.get("calendar_event_url"):
            calendar_actions = (
                f'<a class="button secondary" href="{html.escape(proposal["calendar_event_url"])}">'
                "Open calendar</a>"
            )
    else:
        invitation_copy = "A calendar invitation has been sent."
        google_url, outlook_url = _calendar_links(settings, proposal, option)
        calendar_actions = (
            f'<a class="button secondary" href="{html.escape(google_url)}">Google Calendar</a>'
            f'<a class="button secondary" href="{html.escape(outlook_url)}">Outlook</a>'
        )
    body = f"""
<div class="eyebrow success">Booked</div><h1>Perfect. You are on the calendar.</h1>
<p>{invitation_copy}</p>
<div class="slot"><strong>{html.escape(date_label)}</strong><span>{html.escape(time_label)}</span>{range_html}</div>
<div class="actions">{meet}{calendar_actions}
<a class="button secondary" href="{html.escape(ics_url)}">Download .ics</a></div>
<div class="note">You may close this page.</div>"""
    return _page_shell(settings, "Meeting booked", body)


def render_error_page(settings: Settings, message: str, *, retry_url: str = "") -> str:
    action = ""
    if retry_url:
        action = f'<div class="actions"><a class="button secondary" href="{html.escape(retry_url)}">Choose another time</a></div>'
    body = f"""
<div class="eyebrow error">Unable to book</div><h1>That did not go through.</h1>
<p>{html.escape(message)}</p>{action}"""
    return _page_shell(settings, "Unable to book", body)


def render_ics(settings: Settings, proposal: dict[str, Any], option: dict[str, Any]) -> bytes:
    def escape_ics(value: str) -> str:
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    start = parse_instant(option["starts_at"])
    end = parse_instant(option["ends_at"])
    description = f"Scheduled through the booking assistant for {settings.owner_name}."
    if proposal.get("meet_url"):
        description += f" Join: {proposal['meet_url']}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Hermes Community//Book a Time//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{proposal['id']}@booking.example.com",
        f"DTSTAMP:{utc_now().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{escape_ics(proposal['title'])}",
        f"DESCRIPTION:{escape_ics(description)}",
    ]
    if proposal.get("recurrence_rule"):
        recurrence_rule = str(proposal["recurrence_rule"])
        if not RRULE_RE.fullmatch(recurrence_rule):
            raise BookingError("proposal contains an unsupported recurrence rule")
        lines.append(recurrence_rule)
    if proposal.get("meet_url"):
        lines.append(f"LOCATION:{escape_ics(proposal['meet_url'])}")
        lines.append(f"URL:{escape_ics(proposal['meet_url'])}")
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines).encode("utf-8")


def event_urls(event: dict[str, Any]) -> tuple[str, str, str]:
    event_id = str(event.get("id", ""))
    event_url = str(event.get("htmlLink", ""))
    meet_url = str(event.get("hangoutLink", ""))
    if not meet_url:
        conference = event.get("conferenceData", {})
        for entry in conference.get("entryPoints", []) if isinstance(conference, dict) else []:
            if isinstance(entry, dict) and entry.get("entryPointType") == "video":
                meet_url = str(entry.get("uri", ""))
                break
    return event_id, event_url, meet_url
