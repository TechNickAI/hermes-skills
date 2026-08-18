#!/usr/bin/env python3
"""Public confirmation server for email-first booking proposals."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from booking_core import (
    BookingError,
    BookingStore,
    CalendarConflict,
    GogClient,
    OPTION_RE,
    Settings,
    TOKEN_RE,
    booked_option,
    event_urls,
    parse_instant,
    render_confirmation_page,
    render_error_page,
    render_ics,
    render_options_page,
    valid_confirmation,
)


LOGGER = logging.getLogger("booking-service")
MAX_FORM_BYTES = 4096


class BookingHandler(BaseHTTPRequestHandler):
    server_version = "BookingService/1.0"
    settings: Settings
    store: BookingStore
    calendar: GogClient

    def log_message(self, format_string: str, *args: object) -> None:
        LOGGER.info("request from %s: %s", self.client_address[0], format_string % args)

    def security_headers(self, *, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def send_bytes(
        self,
        status: int,
        payload: bytes,
        *,
        content_type: str,
        disposition: str = "",
    ) -> None:
        self.send_response(status)
        self.security_headers(content_type=content_type, length=len(payload))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self, status: int, document: str) -> None:
        self.send_bytes(
            status,
            document.encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )

    def send_json(self, status: int, value: dict[str, Any]) -> None:
        self.send_bytes(
            status,
            (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def path_parts(self) -> list[str]:
        return [
            urllib.parse.unquote(part)
            for part in urllib.parse.urlparse(self.path).path.split("/")
            if part
        ]

    def load_proposal(self, token: str) -> dict[str, Any] | None:
        if not TOKEN_RE.fullmatch(token):
            return None
        return self.store.get_by_token(token)

    @staticmethod
    def find_option(proposal: dict[str, Any], option_id: str) -> dict[str, Any] | None:
        if not OPTION_RE.fullmatch(option_id):
            return None
        for option in proposal.get("options", []):
            if option["id"] == option_id:
                return option
        return None

    def do_GET(self) -> None:
        parts = self.path_parts()
        if parts == ["book", "health"]:
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if len(parts) not in {2, 3} or parts[0] != "book":
            self.send_html(
                HTTPStatus.NOT_FOUND,
                render_error_page(self.settings, "This booking link does not exist."),
            )
            return

        token = parts[1]
        proposal = self.load_proposal(token)
        if proposal is None:
            self.send_html(
                HTTPStatus.NOT_FOUND,
                render_error_page(self.settings, "This booking link does not exist."),
            )
            return
        if len(parts) == 2:
            self.send_html(HTTPStatus.OK, render_options_page(self.settings, token, proposal))
            return

        option_part = parts[2]
        if option_part.endswith(".ics"):
            option_id = option_part[:-4]
            option = self.find_option(proposal, option_id)
            if (
                option is None
                or proposal["status"] != "booked"
                or proposal.get("booked_option_id") != option_id
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = render_ics(self.settings, proposal, option)
            self.send_bytes(
                HTTPStatus.OK,
                payload,
                content_type="text/calendar; charset=utf-8",
                disposition='attachment; filename="meeting.ics"',
            )
            return

        option = self.find_option(proposal, option_part)
        if option is None:
            self.send_html(
                HTTPStatus.NOT_FOUND,
                render_error_page(self.settings, "That time option does not exist."),
            )
            return
        if proposal["status"] == "booked":
            self.send_html(HTTPStatus.OK, render_options_page(self.settings, token, proposal))
            return
        if proposal["status"] not in {"sent", "booking"}:
            self.send_html(HTTPStatus.GONE, render_options_page(self.settings, token, proposal))
            return
        self.send_html(
            HTTPStatus.OK,
            render_confirmation_page(self.settings, token, proposal, option),
        )

    def do_POST(self) -> None:
        parts = self.path_parts()
        if len(parts) != 4 or parts[0] != "book" or parts[3] != "confirm":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        token, option_id = parts[1], parts[2]
        if not TOKEN_RE.fullmatch(token) or not OPTION_RE.fullmatch(option_id):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        origin = self.headers.get("Origin", "")
        public_origin = urllib.parse.urlparse(self.settings.public_base_url)
        expected_origin = f"{public_origin.scheme}://{public_origin.netloc}"
        if origin and origin.rstrip("/") != expected_origin:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if length <= 0 or length > MAX_FORM_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        form = urllib.parse.parse_qs(
            self.rfile.read(length).decode("utf-8", errors="strict"),
            keep_blank_values=True,
        )
        supplied = form.get("confirmation", [""])[0]
        if not valid_confirmation(self.settings, token, option_id, supplied):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        retry_url = f"{self.settings.public_base_url}/{token}"
        try:
            claimed = self.store.claim(token, option_id)
        except BookingError as error:
            self.send_html(
                HTTPStatus.CONFLICT,
                render_error_page(self.settings, str(error), retry_url=retry_url),
            )
            return
        if claimed.get("already_booked"):
            self.redirect(retry_url)
            return

        try:
            event = self.calendar.create_event(claimed)
            event_id, event_url, meet_url = event_urls(event)
            self.store.complete(
                claimed["id"],
                option_id,
                event_id=event_id,
                event_url=event_url,
                meet_url=meet_url,
            )
        except CalendarConflict as error:
            self.store.release_claim(claimed["id"])
            self.send_html(
                HTTPStatus.CONFLICT,
                render_error_page(self.settings, str(error), retry_url=retry_url),
            )
            return
        except BookingError as error:
            recovered = self.recover_uncertain_booking(claimed, option_id)
            if recovered:
                self.redirect(retry_url)
                return
            self.send_html(
                HTTPStatus.SERVICE_UNAVAILABLE,
                render_error_page(
                    self.settings,
                    "The calendar could not be reached. Please try this same time again shortly.",
                    retry_url=f"{self.settings.public_base_url}/{token}/{option_id}",
                ),
            )
            LOGGER.warning("booking %s remains in retry state: %s", claimed["id"], error)
            return
        self.redirect(retry_url)

    def recover_uncertain_booking(self, claimed: dict[str, Any], option_id: str) -> bool:
        start = parse_instant(claimed["starts_at"])
        end = parse_instant(claimed["ends_at"])
        try:
            event = self.calendar.find_event(claimed["id"], start, end)
        except BookingError:
            return False
        if event is None:
            self.store.release_claim(claimed["id"])
            return False
        event_id, event_url, meet_url = event_urls(event)
        self.store.complete(
            claimed["id"],
            option_id,
            event_id=event_id,
            event_url=event_url,
            meet_url=meet_url,
        )
        return True


def build_server(settings: Settings | None = None) -> ThreadingHTTPServer:
    active = settings or Settings.from_env()
    handler = type(
        "ConfiguredBookingHandler",
        (BookingHandler,),
        {
            "settings": active,
            "store": BookingStore(active.database_path),
            "calendar": GogClient(active),
        },
    )
    server = ThreadingHTTPServer((active.listen_host, active.listen_port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("BOOKING_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = Settings.from_env()
    server = build_server(settings)
    LOGGER.info("booking service listening on %s:%s", settings.listen_host, settings.listen_port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
