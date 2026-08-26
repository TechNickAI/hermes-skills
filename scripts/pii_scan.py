#!/usr/bin/env python3
"""Scan skill content for material that must not land in a PUBLIC repo.

hermes-config is public. Fleet member names, host names, Tailscale IPs, private
domains, and absolute home paths identify real people and machines. This gates
promotion: anything flagged goes to private agent-skills, or gets sanitized.

Exit 1 if any BLOCKER is found so a pipeline can gate on it.
"""
import pathlib
import re
import sys

PEOPLE = r"\bjulianna\b|\bthomasowen\b|\bcathy\b|\bkenny\b|\bnick sullivan\b"
HOSTS = (r"\b[a-z]+s-mac-mini\b|\b[a-z]+s-imac\b|\bmac-studio\b|hex\.technick"
         r"|\bkenbot\b|\bshantima\b|\bbobsteel\b|(?<![a-z-])roxy\b")
# Agent / persona names. These are fleet identifiers just like hostnames, and a
# public skill that names them leaks the roster even when no host or IP appears.
# Matched case-insensitively at compile time.
#
# Boundaries exclude a neighbouring letter or quote, which kills the two
# false positives that fire on prose about this very problem:
#   "interface" / "replace"   -> ace as a substring
#   f'ace'timemessagestored   -> quote-spliced inside a code comment
# A hyphen and a slash are NOT excluded, because `hermes-argus` and
# `/hermes-ace/` are real leaks. The regex-literal case `/hermes|ace/` is
# excluded specifically via the alternation pipe.
AGENTS = (r"(?<![a-z'\"|])bosun\b|(?<![a-z'\"|])argus\b|(?<![a-z'\"|])cora\b"
          r"|(?<![a-z'\"|])sterling\b|(?<![a-z'\"|])drishti\b"
          r"|(?<![a-z'\"|])ace(?![a-z'\"])\b")
# Private/LAN addressing only. Loopback and documentation ranges are not PII.
NETWORK = r"\b100\.(?:6[4-9]|[7-9]\d|1[0-1]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"
# Real chat/group identifiers. A Telegram supergroup id is -100 followed by 10
# digits and names a specific private room, but it is not a name, a host, or an
# IP -- so every other rule here misses it. The documentation range -100123456789x
# is allowed so examples can still be concrete.
CHAT_IDS = r"-100(?!1234567890|0000000000)\d{10}\b"
# Commit SHAs and build identifiers. These correlate a public artifact with a
# private repository's history even when every name has been scrubbed.
BUILD_IDS = r"\breleases/standalone-[0-9a-f]{7,}\b|\b[0-9a-f]{40}\b"
# Exact incident dates. CONTRIBUTING's substitution table already bans these
# ("an exact incident date tied to a real outage" -> "on one occasion", or drop
# it), but nothing enforced it and 299 shipped. A date is a JOIN KEY: alone it
# identifies nobody, but against a public commit timeline it narrows an anecdote
# to one outage on one estate on one day.
#
# Applies to BUNDLED CODE too (.py/.sh/.cjs), not just prose -- those files are
# published with the skill and leak identically.
#
# NOT flagged: an ISO timestamp with a time component, or a date followed by a
# clock time. Those are format examples and typed literals; rewriting them
# breaks the command (an awk filter matches nothing, a SQL cutoff sorts after
# every real row and deletes the table). Use a neutral placeholder date there
# instead of prose.
INCIDENT_DATES = r"\b20(?:2[4-9]|3\d)-\d{2}-\d{2}\b(?!T\d|\d|\s\d{2}:\d{2})"
DOMAINS = r"technick\.ai|carmenta\.ai|sullivanflock\.com"
PATHS = r"/Users/(?!<user>|you\b)[a-z]+/|/home/(?!<user>|ubuntu/?$)[a-z]+/"
# Real key shapes: require enough entropy-ish length and exclude hyphenated words.
SECRETS = r"\b(?:sk-[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"

RULES = [
    ("SECRET", SECRETS, "BLOCKER"),
    ("network", NETWORK, "BLOCKER"),
    ("incident-date", INCIDENT_DATES, "warn"),
    ("chat-id", CHAT_IDS, "BLOCKER"),
    ("build-id", BUILD_IDS, "BLOCKER"),
    ("private-domain", DOMAINS, "BLOCKER"),
    ("fleet-host", HOSTS, "BLOCKER"),
    ("agent-name", AGENTS, "BLOCKER"),
    ("person", PEOPLE, "BLOCKER"),
    ("home-path", PATHS, "warn"),
]
COMPILED = [(n, re.compile(p, re.I), sev) for n, p, sev in RULES]


def scan(path: pathlib.Path):
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx, sev in COMPILED:
            m = rx.search(line)
            if m:
                out.append((sev, name, i, line.strip()[:100], m.group(0)))
    return out


def main(argv):
    targets = [pathlib.Path(a) for a in argv[1:]]
    if not targets:
        print("usage: pii_scan.py <dir-or-file>...")
        return 2

    blockers = warns = 0
    for t in targets:
        files = [t] if t.is_file() else [f for f in t.rglob("*") if f.is_file()]
        hits = {}
        for f in files:
            if any(s in str(f) for s in ("/.archive/", "/.hub/", "/.git/")):
                continue
            for sev, name, ln, txt, match in scan(f):
                hits.setdefault(f, []).append((sev, name, ln, txt, match))

        label = t.name
        nb = sum(1 for v in hits.values() for h in v if h[0] == "BLOCKER")
        nw = sum(1 for v in hits.values() for h in v if h[0] == "warn")
        blockers += nb
        warns += nw
        status = "BLOCKED " if nb else ("warn    " if nw else "clean   ")
        print(f"{status} {label:28} blockers={nb:4} warns={nw:4}")
        for f, v in sorted(hits.items()):
            shown = [h for h in v if h[0] == "BLOCKER"][:4]
            for sev, name, ln, txt, match in shown:
                rel = f.name if f == t else f.relative_to(t)
                print(f"      {name:15} {rel}:{ln}  {match!r}")

    print(f"\nTOTAL blockers={blockers} warns={warns}")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
