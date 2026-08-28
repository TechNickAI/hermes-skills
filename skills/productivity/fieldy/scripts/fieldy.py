#!/usr/bin/env python3
"""fieldy.py — CLI for the Fieldy Public API (v2).

Auth: FIELDY_API_KEY environment variable, or --env-file PATH.
Base: https://api.fieldy.ai/api/public/v2
Stdlib only. Prints JSON, or readable text with --text.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.fieldy.ai/api/public/v2"
API_HOST = urllib.parse.urlsplit(BASE).netloc

# A page cap so a server that pins its cursor cannot spin forever even if the
# repeat-detector is somehow defeated by a rotating-but-cycling cursor.
MAX_PAGES = 500

SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{4,}")


def redact(text):
    """Never let an API key reach stdout, stderr, or a log."""
    return SECRET_RE.sub("sk-***REDACTED***", str(text))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects outright.

    urllib replays request headers on redirect, and `Authorization` is stored in
    `headers` rather than `unredirected_hdrs`, so a 302 to another host hands
    that host a long-lived bearer token for the user's entire recorded history.
    Verified: a cross-host HTTPS->HTTP redirect received the header intact.
    The Fieldy API never legitimately redirects, so refusing is strictly correct.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(
            f"refusing redirect to {newurl!r}: the Authorization header would "
            "be replayed to another host"
        )


_OPENER = urllib.request.build_opener(NoRedirect)


def load_env_file(path):
    """Read FIELDY_API_KEY from a dotenv-style file. Explicit paths only."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if line.startswith("FIELDY_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError as e:
        sys.exit(f"Cannot read --env-file {path!r}: {e}")
    return None


def find_key(env_file=None):
    """Resolve the API key. Environment first; a file only when asked for.

    Deliberately does NOT scan sibling profiles or config directories. An
    implicit scan can hand the caller a different account's credential, and
    silently reading someone else's private conversations is worse than a
    missing-key error.
    """
    if env_file:
        key = load_env_file(env_file)
        if key:
            return key
        sys.exit(f"No FIELDY_API_KEY line in {env_file!r}.")
    key = os.environ.get("FIELDY_API_KEY")
    if key and key.strip():
        return key.strip()
    sys.exit(
        "No FIELDY_API_KEY found.\n"
        "  export FIELDY_API_KEY=sk-fieldy-...   (Fieldy app > Settings > "
        "Developer Settings)\n"
        "  or pass --env-file /path/to/.env"
    )


def call(method, path, key, params=None, body=None, retries=3, verbose=False):
    method = method.upper()
    # The path is an API endpoint, never a URL and never a place to smuggle a
    # query string. Rejecting `?` here is what makes the "errors never echo the
    # query string" guarantee true: `raw '/x?token=secret'` would otherwise be
    # reproduced verbatim in the error message.
    if not path.startswith("/") or path.startswith("//"):
        sys.exit(f"path must be a single API path beginning with '/': {path!r}")
    for bad in ("?", "#", "://"):
        if bad in path:
            # Do NOT echo the path: it is being rejected precisely because it
            # may carry a secret in a query string.
            sys.exit(f"path may not contain {bad!r} (offending value withheld). "
                     "Pass query values with --param instead.")
    url = BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    safe_url = BASE + path  # never echo the query string; it may hold secrets
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")

    # Only GET is retried. A retried POST/PATCH/DELETE that actually succeeded
    # before the connection broke duplicates the side effect -- for POST
    # /sharables that means minting several public links to a private
    # conversation. An unsafe method fails once and says the outcome is unknown.
    idempotent = method == "GET"
    attempts = retries if idempotent else 1

    for attempt in range(attempts):
        try:
            with _OPENER.open(req, timeout=60) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 429 and idempotent and attempt < attempts - 1:
                time.sleep(20 * (attempt + 1))
                continue
            if e.code >= 500 and idempotent and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            msg = f"HTTP {e.code} on {method} {safe_url}"
            if not idempotent and e.code >= 500:
                msg += ("\nOutcome UNKNOWN: the request may have taken effect. "
                        "Check state before retrying.")
            if verbose:
                msg += "\n" + redact(detail[:500])
            else:
                msg += f"\n{redact(detail[:200])}"
            sys.exit(msg)
        except urllib.error.URLError as e:
            if idempotent and attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
            msg = f"Network error on {method} {safe_url}: {redact(e)}"
            if not idempotent:
                msg += ("\nOutcome UNKNOWN: the request may have taken effect. "
                        "Check state before retrying.")
            sys.exit(msg)


def iso(dt):
    """Serialize to the API's ISO 8601 UTC form, preserving sub-second detail.

    Truncating to whole seconds broadens --start and narrows --end, which can
    pull in or drop a boundary transcript segment.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value, label):
    """Accept the ISO 8601 forms the API emits, including a trailing Z.

    A timezone-naive input is treated as UTC rather than rejected: the API speaks
    only UTC, and `--start 2026-05-01T00:00:00` is an obvious intent. Returning a
    naive datetime here would blow up on comparison with an aware one
    (`TypeError: can't compare offset-naive and offset-aware datetimes`) and,
    worse, a pair of naive inputs would silently be reinterpreted as local time
    by `astimezone()` in `iso()` — shifting the window by the UTC offset and
    quietly returning the wrong conversations.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        sys.exit(f"{label} is not ISO 8601: {value!r} "
                 "(expected e.g. 2026-05-01T00:00:00Z)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def window(args):
    """Resolve --start/--end/--days into ISO UTC strings.

    The lookback is anchored to the END of the window, not to now. Anchoring to
    now made `--end <last month> --days 7` produce start > end, which the API
    answers with zero rows -- an agent then reports "nothing was discussed"
    when the truth is the query was malformed.
    """
    now = datetime.now(timezone.utc)
    end_dt = parse_iso(args.end, "--end") if args.end else now
    if args.start:
        start_dt = parse_iso(args.start, "--start")
    else:
        days = args.days if args.days is not None else 1
        if days <= 0:
            sys.exit("--days must be a positive number of days.")
        start_dt = end_dt - timedelta(days=days)
    if start_dt >= end_dt:
        sys.exit(f"Empty time window: start {iso(start_dt)} is not before "
                 f"end {iso(end_dt)}.")
    return iso(start_dt), iso(end_dt)


def paginate(path, key, params, page_size=50, max_items=None, verbose=False,
             allow_partial=False):
    """Follow nextCursor to exhaustion, with loop and duplicate protection.

    Incomplete results EXIT NONZERO unless --allow-partial. Returning a
    truncated list with a normal-looking count is the worst failure mode here:
    an agent reads it as the complete record of a week and reports that
    something was never discussed.
    """
    items, cursor, seen = [], None, set()
    params = dict(params)
    # Do not request more per page than the caller will keep: a --limit 1 query
    # should not pull 50 conversations of private speech into an agent context.
    effective = page_size if max_items is None else min(page_size, max_items)
    params["pageSize"] = max(1, effective)
    truncated = None
    for _ in range(MAX_PAGES):
        params["cursor"] = cursor
        resp = call("GET", path, key, params=params, verbose=verbose) or {}
        items.extend(resp.get("items", []))
        if max_items is not None and len(items) >= max_items:
            break
        cursor = resp.get("nextCursor")
        # An empty page with a live cursor is a hole, not the end: following it
        # is what keeps a mid-range empty batch from discarding later pages.
        if not cursor:
            break
        if cursor in seen:
            truncated = "the API repeated a pagination cursor"
            break
        seen.add(cursor)
        time.sleep(2.0)  # documented budget is ~30 req/min
    else:
        truncated = f"hit the {MAX_PAGES}-page safety cap"

    if truncated:
        msg = (f"INCOMPLETE: {truncated} after {len(items)} items. "
               "Results are partial; narrow the time window.")
        if not allow_partial:
            sys.exit(msg + " Re-run with --allow-partial to accept them.")
        print("warning: " + msg, file=sys.stderr)
    return items[:max_items] if max_items is not None else items


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def require_started(conv, ident):
    """A conversation still being processed has no usable time range yet."""
    if not conv.get("startTime"):
        sys.exit(
            f"Conversation {ident} has no startTime yet — Fieldy is still "
            "processing it (Sending to Private Cloud -> Transcribing -> "
            "Generating Title). Retry in a few minutes."
        )
    return conv


def cmd_whoami(args, key):
    out(call("GET", "/user/me", key, verbose=args.verbose))


def cmd_conversations(args, key):
    start, end = window(args)
    items = paginate(
        "/conversations", key,
        {"startTime": start, "endTime": end, "mode": args.mode,
         "recordingSource": args.source},
        page_size=min(args.page_size, 50), max_items=args.limit,
        verbose=args.verbose, allow_partial=args.allow_partial,
    )
    if args.text:
        for c in items:
            when = c.get("startTime") or "(processing)"
            print(f"[{when}] {c.get('title') or '(untitled)'}  id={c.get('id')}")
            if c.get("summary"):
                print("  " + c["summary"].replace("\n", "\n  "))
            print()
        print(f"-- {len(items)} conversations {start} .. {end}")
    else:
        out({"count": len(items), "items": items})


def cmd_conversation(args, key):
    conv = call("GET", "/conversations/" + args.id, key, verbose=args.verbose)
    if conv is None:
        sys.exit(f"No conversation with id {args.id!r} (API returned null).")
    out(conv)


def cmd_transcript(args, key):
    """Transcript segments, by conversation id or by time window."""
    if args.conversation_id:
        conv = call("GET", "/conversations/" + args.conversation_id, key,
                    verbose=args.verbose)
        if conv is None:
            sys.exit(f"No conversation with id {args.conversation_id!r}.")
        require_started(conv, args.conversation_id)
        start = conv["startTime"]
        end = conv.get("endTime") or iso(datetime.now(timezone.utc))
        params = {"startTime": start, "endTime": end,
                  "conversationId": args.conversation_id, "order": "asc",
                  "inclusive": "true"}
    else:
        start, end = window(args)
        params = {"startTime": start, "endTime": end, "order": "asc"}
    if args.source:
        params["recordingSource"] = args.source
    items = paginate("/transcriptions", key, params,
                     page_size=min(args.page_size, 1000), max_items=args.limit,
                     verbose=args.verbose, allow_partial=args.allow_partial)
    if args.text:
        for s in items:
            print(f"{s.get('timestamp')}  {s.get('speaker') or 'Unknown'}: "
                  f"{s.get('text', '')}")
        print(f"\n-- {len(items)} segments")
    else:
        out({"count": len(items), "items": items})


def cmd_tasks(args, key):
    resp = call("GET", "/tasks", key, params={"status": args.status},
                verbose=args.verbose) or {}
    if args.text:
        for t in resp.get("items", []):
            due = f"  due {t['date']}" if t.get("date") else ""
            print(f"[{t.get('status')}] {t.get('title')}{due}  id={t.get('id')}")
        print(f"\n-- {len(resp.get('items', []))} tasks ({args.status})")
    else:
        out(resp)


def cmd_speakers(args, key):
    resp = call("GET", "/speaker-profiles", key, verbose=args.verbose) or {}
    if args.text:
        for s in resp.get("items", []):
            print(f"{s.get('name')}  id={s.get('id')}")
        print(f"\n-- {len(resp.get('items', []))} speaker profiles")
    else:
        out(resp)


def cmd_templates(args, key):
    resp = call("GET", "/memory-templates", key, verbose=args.verbose) or {}
    if args.text:
        for t in resp.get("items", []):
            print(f"{t.get('title')}  id={t.get('id')}")
            if t.get("description"):
                print(f"  {t['description']}")
        print(f"\n-- {len(resp.get('items', []))} templates")
    else:
        out(resp)


def cmd_raw(args, key):
    params = dict(p.split("=", 1) for p in args.param) if args.param else None
    body = json.loads(args.body) if args.body else None
    if args.method.upper() != "GET" and not args.yes:
        sys.exit(f"{args.method.upper()} mutates the account. Re-run with --yes "
                 "if that is genuinely intended.")
    out(call(args.method, args.path, key, params=params, body=body,
             verbose=args.verbose))


def positive_int(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or greater")
    return n


def main():
    # Flags accepted BOTH before and after the subcommand. SUPPRESS is required:
    # without it the subparser's default overwrites a value already set by the
    # main parser, silently dropping a pre-subcommand --text.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", action="store_true", default=argparse.SUPPRESS,
                        help="human-readable output")
    common.add_argument("--verbose", action="store_true",
                        default=argparse.SUPPRESS,
                        help="include full API error bodies (may contain "
                             "transcript text)")
    common.add_argument("--env-file", default=argparse.SUPPRESS,
                        help="read FIELDY_API_KEY from this dotenv file")

    paged = argparse.ArgumentParser(add_help=False)
    paged.add_argument("--limit", type=positive_int, default=argparse.SUPPRESS,
                       help="max items to return")
    paged.add_argument("--page-size", type=positive_int,
                       default=argparse.SUPPRESS, help="items per API request")
    paged.add_argument("--allow-partial", action="store_true",
                       default=argparse.SUPPRESS,
                       help="accept an incomplete result set instead of failing")

    p = argparse.ArgumentParser(description="Fieldy Public API client",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, *, parents=(), **kw):
        return sub.add_parser(name, parents=[common, *parents], **kw)

    def timeargs(sp):
        sp.add_argument("--start", help="ISO 8601 UTC start")
        sp.add_argument("--end", help="ISO 8601 UTC end (default: now)")
        sp.add_argument("--days", type=int,
                        help="lookback days from --end (default 1)")
        sp.add_argument("--source", choices=["wearable", "phone", "desktop"])

    add("whoami", help="auth probe").set_defaults(fn=cmd_whoami)

    c = add("conversations", parents=[paged], help="list conversations")
    timeargs(c)
    c.add_argument("--mode", choices=["starts-in-range", "intersects-range"],
                   default="starts-in-range")
    c.set_defaults(fn=cmd_conversations)

    g = add("conversation", help="get one conversation by id")
    g.add_argument("id")
    g.set_defaults(fn=cmd_conversation)

    t = add("transcript", parents=[paged], help="transcript segments")
    timeargs(t)
    t.add_argument("--conversation-id")
    t.set_defaults(fn=cmd_transcript)

    tk = add("tasks", help="list action items")
    tk.add_argument("--status", default="new",
                    choices=["new", "approved", "completed", "rejected",
                             "skipped", "cancelled", "expired"])
    tk.set_defaults(fn=cmd_tasks)

    add("speakers", help="list speaker profiles").set_defaults(fn=cmd_speakers)
    add("templates", help="list memory templates").set_defaults(fn=cmd_templates)

    r = add("raw", help="call any endpoint")
    r.add_argument("path", help="e.g. /sharables")
    r.add_argument("--method", default="GET")
    r.add_argument("--param", action="append", help="key=value (repeatable)")
    r.add_argument("--body", help="JSON body string")
    r.add_argument("--yes", action="store_true",
                   help="confirm a mutating method")
    r.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    # SUPPRESS leaves attributes absent; supply defaults once, centrally.
    for name, default in (("text", False), ("verbose", False),
                          ("env_file", None), ("limit", None),
                          ("page_size", 50), ("allow_partial", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    args.fn(args, find_key(args.env_file))


if __name__ == "__main__":
    main()
