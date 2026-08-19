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

# People. First names matter as much as full names: fleet docs say "Nick asks"
# and "Nick's framing", never "Nick Sullivan", so a full-name-only rule matched
# almost nothing in practice. Negative lookarounds keep ordinary words that
# merely CONTAIN a name (nickel, knickknack, Nicholas) from firing.
PEOPLE = (r"(?<![a-z])nick(?![a-z])|\bnick's\b|\bjulianna\b|\bthomasowen\b"
          r"|\bthomas owen\b|\bcathy\b|\bkenny\b")
# Private org / venture / product codenames. Not secrets, but they identify
# private work and have no business in a public skill library. Include slug
# forms because most leaks are repository names, paths, and filenames.
VENTURES = (r"\blendy\b|\bfiddler\b|\bcarmentacollective\b|\bantevorta\b"
            r"|\bcryptoai\b|\bhangl-dashboard\b|\bmcp-hubby\b"
            r"|\bbtc-recovery\b|\bwealth-engine\b|\bkenbot\b")
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
# Private/LAN addressing. The 100.64/10 range is real tailnet space, but the
# docs use 100.100.100.100 as an explicit placeholder, so exempt exactly that
# known-safe value. Loopback and RFC documentation ranges are not PII either.
NETWORK = (r"\b100\.(?!100\.100\.100\b)(?:6[4-9]|[7-9]\d|1[0-1]\d|12[0-7])"
           r"\.\d{1,3}\.\d{1,3}\b")
DOMAINS = r"technick\.ai|carmenta\.ai|sullivanflock\.com"
# Absolute home paths. The trailing slash was optional in practice
# (`export HOME=/Users/nick`), so requiring it let real leaks through. Word
# boundary instead, with placeholders and the generic cloud user excluded.
PATHS = (r"/Users/(?!<user>\b|<you>\b|you\b|yourname\b)[a-z][a-z0-9._-]*"
         r"|/home/(?!<user>\b|<you>\b|you\b|ubuntu\b)[a-z][a-z0-9._-]*")
# Real key shapes: require enough entropy-ish length and exclude hyphenated words.
SECRETS = r"\b(?:sk-[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"

RULES = [
    ("SECRET", SECRETS, "BLOCKER"),
    ("network", NETWORK, "BLOCKER"),
    ("private-domain", DOMAINS, "BLOCKER"),
    ("fleet-host", HOSTS, "BLOCKER"),
    ("agent-name", AGENTS, "BLOCKER"),
    ("person", PEOPLE, "BLOCKER"),
    ("venture", VENTURES, "BLOCKER"),
    # Promoted from warn: an absolute home path names a real machine and a real
    # user. As a warn it never gated CI, so 19 of them reached the public repo.
    ("home-path", PATHS, "BLOCKER"),
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
            # Skip VCS internals, caches, and build artifacts. Matching on path
            # PARTS rather than substrings: the old check looked for "/.git/",
            # which never matched when scanning "." because the relative path
            # starts with ".git/" and has no leading slash. That let commit
            # messages in .git/logs and stale .pyc files dominate the report.
            parts = set(f.parts)
            if parts & {".git", ".archive", ".hub", "__pycache__", ".pytest_cache",
                        ".ruff_cache", ".mypy_cache", "node_modules", ".venv"}:
                continue
            if f.suffix in {".pyc", ".pyo"}:
                continue
            # Scanner definitions and known-answer fixtures necessarily contain
            # the exact strings they are proving the detector catches. Structural
            # tests similarly enumerate agent-name fixtures. Exempt ONLY these
            # named test sources, never a directory wildcard. LICENSE carries the
            # public copyright holder by design, not private operational PII.
            rel_parts = f.parts[-2:]
            if rel_parts in {
                ("scripts", "pii_scan.py"),
                ("scripts", "test_pii_scan.py"),
                ("tests", "test_library_structure.py"),
            } or f.name == "LICENSE":
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
