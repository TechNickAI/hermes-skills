#!/usr/bin/env python3
"""Create, inspect, and diagnose email-first booking proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time as time_module
from datetime import date, datetime, time, timedelta
from pathlib import Path

from booking_core import (
    BookingError,
    BookingStore,
    DeliveryUncertain,
    GogClient,
    Settings,
    candidate_recurring_slots,
    candidate_slots,
    clean_text,
    first_weekday_on_or_after,
    iso_utc,
    render_email,
    require_timezone,
    utc_now,
    validate_email,
    weekly_rrule,
)


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from error


def parse_weekday(value: str) -> int:
    weekday = WEEKDAYS.get(value.strip().lower())
    if weekday is None:
        raise argparse.ArgumentTypeError("use a weekday name such as Wednesday")
    return weekday


def default_window() -> tuple[date, date]:
    start = (utc_now() + timedelta(days=1)).date()
    return start, start + timedelta(days=13)


def dedupe_key(
    *,
    guest_email: str,
    title: str,
    duration: int,
    range_start: date,
    range_end: date,
    guest_timezone: str,
    recurrence_rule: str = "",
    recurrence_until: str = "",
) -> str:
    payload = "\0".join(
        (
            guest_email,
            title.casefold(),
            str(duration),
            range_start.isoformat(),
            range_end.isoformat(),
            guest_timezone,
            recurrence_rule,
            recurrence_until,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def public_result(proposal: dict[str, object]) -> dict[str, object]:
    return {
        "status": proposal["status"],
        "delivery_status": proposal.get("delivery_status", ""),
        "proposal_id": proposal["id"],
        "recipient": proposal["guest_email"],
        "message_id": proposal.get("gmail_message_id", ""),
        "expires_at": proposal["expires_at"],
        "options": proposal.get("options", []),
        "recurrence_rule": proposal.get("recurrence_rule", ""),
        "recurrence_until": proposal.get("recurrence_until", ""),
    }


def proposal_subject(settings: Settings, proposal: dict[str, object]) -> str:
    if proposal.get("recurrence_rule"):
        return f"Recurring times with {settings.owner_name}"
    return f"A few times with {settings.owner_name}"


def verify_and_finish(
    *,
    client: GogClient,
    store: BookingStore,
    proposal: dict[str, object],
    message_id: str,
    subject: str,
) -> dict[str, object]:
    last_error: BookingError | None = None
    for attempt in range(3):
        try:
            client.verify_sent(
                message_id,
                recipient=str(proposal["guest_email"]),
                subject=subject,
            )
            last_error = None
            break
        except BookingError as error:
            last_error = error
            if attempt < 2:
                time_module.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    store.mark_sent(str(proposal["id"]), message_id)
    updated = store.get_by_id(str(proposal["id"]))
    if updated is None:
        raise BookingError("sent proposal disappeared from storage")
    return public_result(updated)


def deliver_proposal(
    *,
    client: GogClient,
    store: BookingStore,
    proposal: dict[str, object],
    plain_body: str,
    html_body: str,
    subject: str,
    state_dir,
) -> dict[str, object]:
    proposal_id = str(proposal["id"])
    delivery_status = str(proposal.get("delivery_status", "creating"))
    message_id = str(proposal.get("gmail_message_id") or "")
    draft_id = str(proposal.get("gmail_draft_id") or "")

    if proposal["status"] == "sent" and message_id:
        client.verify_sent(
            message_id,
            recipient=str(proposal["guest_email"]),
            subject=subject,
        )
        return public_result(proposal)
    if delivery_status == "sending":
        if message_id:
            return verify_and_finish(
                client=client,
                store=store,
                proposal=proposal,
                message_id=message_id,
                subject=subject,
            )
        recovered_id = client.find_sent_reference(f"BK-{proposal_id}")
        if recovered_id:
            store.record_send_receipt(proposal_id, recovered_id)
            return verify_and_finish(
                client=client,
                store=store,
                proposal=proposal,
                message_id=recovered_id,
                subject=subject,
            )
        raise DeliveryUncertain(
            "delivery is still unresolved; no Sent copy was found and automatic resend is blocked"
        )

    if delivery_status == "creating":
        try:
            draft = client.create_email_draft(
                recipient=str(proposal["guest_email"]),
                subject=subject,
                plain_body=plain_body,
                html_body=html_body,
                state_dir=state_dir,
            )
        except BookingError:
            store.delete_draft(proposal_id)
            raise
        draft_id = str(draft["draft_id"])
        try:
            store.mark_prepared(proposal_id, draft_id=draft_id)
        except Exception:
            try:
                client.delete_draft(draft_id)
            except BookingError:
                pass
            raise

    store.mark_sending(proposal_id)
    try:
        response = client.send_draft(draft_id)
    except BookingError as error:
        try:
            still_exists = client.draft_exists(draft_id)
        except BookingError:
            store.mark_uncertain(proposal_id, str(error))
            raise DeliveryUncertain(
                "delivery is uncertain because Gmail could not confirm whether the draft was sent"
            ) from error
        if still_exists:
            store.mark_retryable(proposal_id, str(error))
            raise
        recovered_id = client.find_sent_reference(f"BK-{proposal_id}")
        if not recovered_id:
            store.mark_uncertain(proposal_id, str(error))
            raise DeliveryUncertain(
                "delivery is uncertain; the draft disappeared without a send receipt"
            ) from error
        response = {"messageId": recovered_id}

    message_id = client._message_id(response)
    if not message_id:
        store.mark_uncertain(proposal_id, "Gmail returned no message ID after sending")
        raise DeliveryUncertain("Gmail sent the draft but returned no stable message ID")
    store.record_send_receipt(proposal_id, message_id)
    try:
        return verify_and_finish(
            client=client,
            store=store,
            proposal=proposal,
            message_id=message_id,
            subject=subject,
        )
    except BookingError as error:
        store.mark_uncertain(proposal_id, str(error))
        raise DeliveryUncertain(
            "Gmail accepted the message, but its Sent copy could not be verified yet"
        ) from error


def propose(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings.from_env()
    guest_email = validate_email(args.guest_email)
    guest_name = clean_text(args.guest_name, label="guest name", maximum=100)
    title = clean_text(args.title, label="title", maximum=160)
    note = ""
    if args.note:
        note = clean_text(args.note, label="note", maximum=500)
    require_timezone(args.guest_timezone)

    range_start, range_end = default_window()
    if args.from_date:
        range_start = args.from_date
    if args.to_date:
        range_end = args.to_date

    recurrence_rule = ""
    recurrence_until = ""
    recurring_first_date: date | None = None
    if args.weekly:
        if args.weekday is None or args.repeat_until is None:
            raise BookingError("weekly proposals require --weekday and --repeat-until")
        recurring_first_date = first_weekday_on_or_after(range_start, args.weekday)
        if recurring_first_date > range_end and args.to_date:
            raise BookingError("requested weekday is outside the proposed start window")
        if args.repeat_until < recurring_first_date:
            raise BookingError("repeat-until date is before the first requested weekday")
        recurrence_rule = weekly_rrule(args.repeat_until)
        recurrence_until = args.repeat_until.isoformat()
    elif args.weekday is not None or args.repeat_until is not None:
        raise BookingError("--weekday and --repeat-until require --weekly")

    client = GogClient(settings)
    store: BookingStore | None = None
    existing: dict[str, object] | None = None
    idempotency_key = ""
    if not args.preview:
        if args.idempotency_key:
            idempotency_key = hashlib.sha256(
                f"caller\0{args.idempotency_key}".encode("utf-8")
            ).hexdigest()
        else:
            idempotency_key = dedupe_key(
                guest_email=guest_email,
                title=title,
                duration=args.duration,
                range_start=range_start,
                range_end=range_end,
                guest_timezone=args.guest_timezone,
                recurrence_rule=recurrence_rule,
                recurrence_until=recurrence_until,
            )
        store = BookingStore(settings.database_path)
        existing = store.get_by_dedupe_key(idempotency_key)
        if existing is not None:
            if str(existing.get("delivery_status")) == "creating":
                raise BookingError(
                    f"proposal {existing['id']} is already being prepared; do not duplicate it"
                )
            if existing["status"] == "sent" and existing.get("gmail_message_id"):
                subject = proposal_subject(settings, existing)
                client.verify_sent(
                    str(existing["gmail_message_id"]),
                    recipient=guest_email,
                    subject=subject,
                )
                return public_result(existing)
            return deliver_proposal(
                client=client,
                store=store,
                proposal=existing,
                plain_body="",
                html_body="",
                subject=proposal_subject(settings, existing),
                state_dir=settings.state_dir,
            )
    owner_tz = require_timezone(settings.owner_timezone)
    if args.weekly:
        assert recurring_first_date is not None
        start_instant = datetime.combine(
            recurring_first_date, settings.workday_start, owner_tz
        )
        end_instant = datetime.combine(
            args.repeat_until + timedelta(days=1), time.min, owner_tz
        )
    else:
        start_instant = datetime.combine(range_start, settings.workday_start, owner_tz)
        end_instant = datetime.combine(range_end + timedelta(days=1), time.min, owner_tz)
    busy = client.busy_periods(start_instant, end_instant)
    if args.weekly:
        slots = candidate_recurring_slots(
            settings,
            range_start=range_start,
            recurrence_until=args.repeat_until,
            weekday=args.weekday,
            duration_minutes=args.duration,
            busy_periods=busy,
            maximum=args.options,
        )
    else:
        slots = candidate_slots(
            settings,
            range_start=range_start,
            range_end=range_end,
            duration_minutes=args.duration,
            busy_periods=busy,
            maximum=args.options,
        )
    if not slots:
        if args.weekly:
            raise BookingError(
                "no recurring time is conflict-free across every occurrence in that window"
            )
        raise BookingError("no available times matched the requested window")

    if args.preview:
        proposal = {
            "id": f"preview-{secrets.token_hex(8)}",
            "guest_name": guest_name,
            "guest_email": guest_email,
            "title": title,
            "note": note,
            "guest_timezone": args.guest_timezone,
            "duration_minutes": args.duration,
            "recurrence_rule": recurrence_rule,
            "recurrence_until": recurrence_until,
            "created_at": iso_utc(utc_now()),
            "expires_at": iso_utc(utc_now() + timedelta(hours=settings.proposal_ttl_hours)),
            "status": "draft",
            "options": [
                {
                    "id": secrets.token_hex(8),
                    "starts_at": iso_utc(start),
                    "ends_at": iso_utc(end),
                }
                for start, end in slots
            ],
        }
        preview_token = secrets.token_urlsafe(36)
        plain_body, html_body = render_email(
            settings, token=preview_token, proposal=proposal
        )
        preview_dir = settings.state_dir / "previews"
        preview_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        html_path = preview_dir / f"{proposal['id']}.html"
        text_path = preview_dir / f"{proposal['id']}.txt"
        html_path.write_text(html_body, encoding="utf-8")
        text_path.write_text(plain_body, encoding="utf-8")
        html_path.chmod(0o600)
        text_path.chmod(0o600)
        return {
            "status": "preview",
            "proposal_id": proposal["id"],
            "html_preview": str(html_path),
            "text_preview": str(text_path),
            "expires_at": proposal["expires_at"],
            "options": proposal["options"],
        }

    assert store is not None
    if existing is None:
        token = secrets.token_urlsafe(36)
        expires_at = utc_now() + timedelta(hours=settings.proposal_ttl_hours)
        try:
            proposal_id, options = store.create_proposal(
                dedupe_key=idempotency_key,
                token=token,
                guest_name=guest_name,
                guest_email=guest_email,
                title=title,
                note=note,
                guest_timezone=args.guest_timezone,
                duration_minutes=args.duration,
                expires_at=expires_at,
                slots=slots,
                recurrence_rule=recurrence_rule,
                recurrence_until=recurrence_until,
            )
            proposal = store.get_by_id(proposal_id)
        except sqlite3.IntegrityError:
            existing = store.get_by_dedupe_key(idempotency_key)
            proposal = existing
        if proposal is None:
            raise BookingError("proposal was not persisted")
    else:
        proposal = existing

    if existing is not None:
        if str(proposal.get("delivery_status")) == "creating":
            raise BookingError(
                f"proposal {proposal['id']} is already being prepared; do not duplicate it"
            )
        if proposal["status"] == "sent" and proposal.get("gmail_message_id"):
            subject = proposal_subject(settings, proposal)
            client.verify_sent(
                str(proposal["gmail_message_id"]),
                recipient=guest_email,
                subject=subject,
            )
            return public_result(proposal)
        return deliver_proposal(
            client=client,
            store=store,
            proposal=proposal,
            plain_body="",
            html_body="",
            subject=proposal_subject(settings, proposal),
            state_dir=settings.state_dir,
        )

    plain_body, html_body = render_email(settings, token=token, proposal=proposal)

    return deliver_proposal(
        client=client,
        store=store,
        proposal=proposal,
        plain_body=plain_body,
        html_body=html_body,
        subject=proposal_subject(settings, proposal),
        state_dir=settings.state_dir,
    )


def recover(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings.from_env()
    store = BookingStore(settings.database_path)
    proposal = store.get_by_id(args.proposal_id)
    if proposal is None:
        raise BookingError("proposal not found")
    if proposal["status"] == "sent":
        return public_result(proposal)
    if proposal["status"] != "draft":
        raise BookingError(f"proposal is {proposal['status']}, not awaiting delivery")
    if str(proposal.get("delivery_status")) != "sending":
        raise BookingError("only an uncertain sending proposal can be recovered")
    client = GogClient(settings)
    client.verify_cli_capabilities()
    message_id = str(proposal.get("gmail_message_id") or "")
    if not message_id:
        message_id = client.find_sent_reference(f"BK-{proposal['id']}")
        if message_id:
            store.record_send_receipt(str(proposal["id"]), message_id)
    if not message_id:
        raise DeliveryUncertain("no matching Gmail Sent message was found; do not resend blindly")
    return verify_and_finish(
        client=client,
        store=store,
        proposal=proposal,
        message_id=message_id,
        subject=proposal_subject(settings, proposal),
    )


def status(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings.from_env()
    proposal = BookingStore(settings.database_path).get_by_id(args.proposal_id)
    if proposal is None:
        raise BookingError("proposal not found")
    proposal.pop("token_hash", None)
    return proposal


def doctor(_args: argparse.Namespace) -> dict[str, object]:
    settings = Settings.from_env()
    binary = shutil.which(settings.gog_bin)
    if binary is None:
        raise BookingError(f"gog executable not found: {settings.gog_bin}")
    client = GogClient(settings)
    client.verify_cli_capabilities()
    now = utc_now()
    client.busy_periods(now, now + timedelta(hours=1))
    client.gmail_ready()
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.state_dir) as temporary:
        BookingStore(Path(temporary) / "doctor.sqlite3")
    return {
        "status": "ok",
        "gog": binary,
        "account": settings.account,
        "calendar_id": settings.calendar_id,
        "busy_calendar_ids": list(settings.busy_calendar_ids),
        "public_base_url": settings.public_base_url,
        "database": str(settings.database_path),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("propose", help="find openings and send a booking email")
    create.add_argument("--guest-name", required=True)
    create.add_argument("--guest-email", required=True)
    create.add_argument("--title", default="Conversation")
    create.add_argument("--note", default="")
    create.add_argument("--duration", type=int, default=30)
    create.add_argument("--options", type=int, default=3)
    create.add_argument("--from-date", type=parse_date)
    create.add_argument("--to-date", type=parse_date)
    create.add_argument(
        "--weekly",
        action="store_true",
        help="offer times for a weekly recurring series",
    )
    create.add_argument("--weekday", type=parse_weekday)
    create.add_argument("--repeat-until", type=parse_date)
    create.add_argument("--guest-timezone", default="America/Denver")
    create.add_argument(
        "--idempotency-key",
        help="stable caller-supplied key; identical requests otherwise deduplicate automatically",
    )
    create.add_argument(
        "--preview",
        action="store_true",
        help="render local preview files without sending email",
    )
    create.set_defaults(handler=propose)

    inspect = subparsers.add_parser("status", help="show proposal status without its token")
    inspect.add_argument("proposal_id")
    inspect.set_defaults(handler=status)

    recovery = subparsers.add_parser(
        "recover", help="verify an uncertain Gmail delivery without sending again"
    )
    recovery.add_argument("proposal_id")
    recovery.set_defaults(handler=recover)

    diagnostics = subparsers.add_parser("doctor", help="prove config, storage, and calendar access")
    diagnostics.set_defaults(handler=doctor)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.handler(args)
    except (BookingError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
