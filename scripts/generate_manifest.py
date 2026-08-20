#!/usr/bin/env python3
"""Generate skills/MANIFEST.yaml from the SKILL.md files on disk.

Why this exists: the README's skill table is written for humans, and it has drifted
twice already. An agent asked to "set this up" should not have to open nineteen
SKILL.md files and infer which ones will work on this machine. The manifest is the
machine-readable answer to three questions an installing agent actually has:

  1. What is this skill for?          -> `summary` + `use_when`
  2. Will it work for THIS user?      -> `scope` (solo / fleet) and `requires`
  3. What breaks if I install it?     -> `requires` lists env vars, CLIs, services

It is GENERATED, never hand-edited: `python scripts/generate_manifest.py`. CI runs
`--check` and fails if the committed file disagrees with disk, so it cannot rot the
way the README table did.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships with the repo's dev deps
    sys.exit("PyYAML is required: pip install pyyaml")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
MANIFEST = SKILLS / "MANIFEST.yaml"
CATALOG = SKILLS / "CATALOG.md"

# Requirements are DECLARED, not inferred.
#
# An earlier version of this script guessed dependencies by pattern-matching skill
# bodies. It was wrong in both directions: it flagged `mob-check` as needing the `gh`
# CLI (it lists GitHub as one of several optional sources) and missed `mini-app`'s hard
# Caddy/PM2 requirement because that skill's prerequisites live under a heading named
# "First-time install on this machine". Heading conventions vary too much across skills
# for inference to be trustworthy, and a wrong `requires` is worse than none — it scares
# an agent off a skill that would have worked.
#
# So the source of truth is `metadata.hermes.requires` in each SKILL.md. Skills without
# the key are treated as dependency-free, and `--check` in CI keeps this file honest
# against whatever the skills actually declare.

# Skills that assume a multi-agent / multi-host deployment rather than one laptop.
# This is a judgement call, so it lives here explicitly instead of being guessed.
FLEET_SCOPED = {
    "mini-app",
    "pr-review-sweep",
    "report",
}

# Skills that only make sense while migrating off OpenClaw.
MIGRATION_SCOPED: set[str] = set()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body)."""
    match = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    return data, text[match.end() :]


def first_sentence(description: str) -> str:
    """Condense a multi-line description to one scannable sentence."""
    flat = " ".join(description.split())
    match = re.match(r"(.+?[.!?])(?:\s|$)", flat)
    return (match.group(1) if match else flat).strip()


def use_when(description: str) -> str:
    """Pull the trigger conditions out of a description.

    Skill descriptions in this repo follow a 'Use when X, or when Y' convention. That
    clause is the single most useful thing for an agent deciding whether to install a
    skill, so it is promoted to its own field rather than buried mid-paragraph.
    """
    flat = " ".join(description.split())
    match = re.search(r"\bUse (?:when|this when|for)\b(.+)", flat, re.I)
    if not match:
        return ""
    clause = match.group(1).strip()
    if len(clause) <= 300:
        return clause
    # Truncate on a sentence boundary, never mid-word. An agent reads this field to
    # decide whether to install a skill; a clause cut off mid-sentence ("…is th…")
    # is the worst possible input for that decision.
    window = clause[:300]
    cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
    if cut > 80:
        return window[: cut + 1]
    cut = window.rfind(" ")
    return window[:cut].rstrip(" ,;") + "…"


def requirements_for(frontmatter: dict) -> list[str]:
    """Read a skill's declared external dependencies from its frontmatter."""
    meta = (frontmatter.get("metadata") or {}).get("hermes") or {}
    declared = meta.get("requires") or []
    if isinstance(declared, str):
        declared = [declared]
    return [str(item) for item in declared]


def compatibility_for(frontmatter: dict) -> str:
    """Read the skill's runtime compatibility claim from standard frontmatter."""
    return str(frontmatter.get("compatibility", "Agent Skills standard")).strip()


# Runtime compatibility is DECLARED, not inferred from prose.
#
# An earlier version of this repo carried compatibility only as sentences inside
# install guides, and it drifted one skill at a time: `recall` was caught by hand as
# Hermes-only while `memory-cleanup` (27 references to MEMORY.md, 27 to USER.md, 8 to
# SOUL.md — none of which exist in Claude) was still recommended to Claude users with
# "Setup: none". A structured field makes the whole class of bug impossible.
#
#   native      works fully in that runtime
#   degraded    runs, but loses its differentiator — must be disclosed, never sold as full
#   unsupported depends on runtime features that do not exist there; never recommend
# Every skill must appear here. A missing entry is a hard error rather than a silent
# default: declaring prerequisites says nothing about runtime portability, so an
# absent skill would otherwise publish as `native` and CI would happily regenerate
# the same wrong answer.
CLAUDE_COMPAT = {
    # Hermes-only runtime state: session stores, memory files, agent health, MoA, routing.
    "recall": ("unsupported", "Reads Hermes session and memory stores, which Claude does not have."),
    "memory-cleanup": (
        "unsupported",
        "Cleans Hermes MEMORY.md / USER.md / SOUL.md files, which do not exist in Claude.",
    ),
    "moa-solve": ("unsupported", "Requires the native Hermes MoA fan-out runtime."),
    "report": ("unsupported", "Uses Hermes reporting and routing tools."),
    "robustify-doctor": ("unsupported", "Inspects a Hermes runtime and HERMES_HOME layout."),
    "mini-app": ("unsupported", "Operates Hermes-config mini-app host services."),
    "pr-review-sweep": ("unsupported", "Depends on the Hermes delegation toolset."),
    "email-steward": ("unsupported", "Depends on Hermes cron and delegation toolsets."),
    "project-steward": ("unsupported", "Drives a Hermes living board and cron cadence."),
    "skill-librarian": ("degraded", "Audits Hermes skill layout; the method transfers, the paths do not."),
    # Portable method, Hermes-specific mechanism for its headline feature.
    "multi-review": (
        "degraded",
        "The review method transfers, but cross-model-family diversity needs Hermes; "
        "in Claude it becomes Claude reviewing Claude.",
    ),
    "grok-search": ("native", "Works in Claude once XAI_API_KEY is available."),
    "data-verification": (
        "native",
        "Stdlib-only check library and eval harness; the protocol needs no Hermes runtime.",
    ),
    "keep-going": ("native", "Works in Claude with no additional setup."),
    "mob-check": ("native", "Works in Claude with no additional setup."),
    "trust-framework": ("native", "Portable governance rules; no runtime dependency."),
    "address-pr-comments": ("native", "Works in Claude Code with an authenticated gh CLI."),
    "diagram-rendering": ("native", "Works in Claude once its render prerequisites exist."),
    "google-docs": ("native", "Works in Claude once the gog CLI is authorized."),
    "google-sheets": ("native", "Works in Claude once the gog CLI is authorized."),
    "google-slides": ("native", "Works in Claude once the gog CLI is authorized."),
    "imessage-bluebubbles": ("native", "Works in Claude on macOS once BlueBubbles is set up."),
    "vapi-calls": ("native", "Works in Claude once VAPI_API_KEY is available."),
    "deep-dive": (
        "degraded",
        "Full method in Claude Code using its own web, file, and subagent tools; "
        "prior-session search and cross-family synthesis are unavailable.",
    ),
}


def claude_compat_for(name: str) -> tuple[str, str]:
    """Return (status, note) describing how the skill behaves inside Claude."""
    try:
        return CLAUDE_COMPAT[name]
    except KeyError:
        raise SystemExit(
            f"MISSING Claude compatibility for '{name}'.\n"
            "Add it to CLAUDE_COMPAT in scripts/generate_manifest.py as one of:\n"
            "  native      works fully in Claude\n"
            "  degraded    runs, but loses its differentiator (say what it loses)\n"
            "  unsupported depends on runtime features Claude does not have\n"
            "Compatibility is declared, never inferred from prerequisites."
        ) from None


def measure(skill_dir: pathlib.Path) -> dict:
    """Measure real on-disk size so context cost is never a stale guess.

    The published figures for multi-review were ~47KB/~12k tokens, counting only
    SKILL.md. The directory is 131,739 B across 17 files (~33k tokens). Supporting
    files load on demand rather than every trigger, so both numbers matter: report
    the body that loads when the skill triggers, and the full footprint.

    Only git-tracked files are counted. Measuring the working tree instead made the
    manifest depend on local build artifacts (`__pycache__`), so it regenerated clean
    on a developer machine and STALE in CI.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", str(skill_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = [ROOT / rel for rel in listing.split("\0") if rel]
    total = sum(f.stat().st_size for f in files)
    body = (skill_dir / "SKILL.md").stat().st_size
    return {
        "files": len(files),
        "bytes_skill_md": body,
        "bytes_total": total,
        "approx_tokens_skill_md": round(body / 4),
        "approx_tokens_total": round(total / 4),
    }


def scope_for(name: str) -> str:
    if name in FLEET_SCOPED:
        return "fleet"
    if name in MIGRATION_SCOPED:
        return "migration"
    return "solo"


def build() -> dict:
    entries = []
    # Skills live one level deep, under a pack: skills/<pack>/<skill>/SKILL.md.
    # Walking SKILLS.iterdir() directly (the flat layout this script started
    # with) would find the pack directories and skip every real skill.
    for pack_dir in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        for skill_dir in sorted(p for p in pack_dir.iterdir() if p.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            frontmatter, _body = parse_frontmatter(skill_file.read_text())
            description = str(frontmatter.get("description", ""))
            meta = (frontmatter.get("metadata") or {}).get("hermes") or {}
            requires = requirements_for(frontmatter)
            entries.append(
                {
                    "name": skill_dir.name,
                    "pack": pack_dir.name,
                    "version": str(frontmatter.get("version", "0.0.0")),
                    "scope": scope_for(skill_dir.name),
                    "summary": first_sentence(description),
                    "use_when": use_when(description),
                    "requires": requires,
                    "works_out_of_the_box": not requires,
                    "compatibility": compatibility_for(frontmatter),
                    "claude_compat": claude_compat_for(skill_dir.name)[0],
                    "claude_note": claude_compat_for(skill_dir.name)[1],
                    "size": measure(skill_dir),
                    "tags": list(meta.get("tags") or []),
                    "path": f"skills/{pack_dir.name}/{skill_dir.name}",
                }
            )
    return {
        "_generated_by": "scripts/generate_manifest.py",
        "_do_not_edit": "Regenerate with `python scripts/generate_manifest.py`; CI checks it.",
        "count": len(entries),
        "packs": sorted({e["pack"] for e in entries}),
        "skills": entries,
    }


def render(manifest: dict) -> str:
    header = (
        "# Machine-readable index of every skill in this repo.\n"
        "#\n"
        "# GENERATED FILE — do not edit by hand.\n"
        "#   regenerate:  python scripts/generate_manifest.py\n"
        "#   verify:      python scripts/generate_manifest.py --check\n"
        "#\n"
        "# Fields an installing agent should read:\n"
        "#   scope                 solo | fleet | migration — is this relevant to this user?\n"
        "#   requires              external deps that must exist BEFORE the skill works\n"
        "#   works_out_of_the_box  true = copy it and it runs, no setup\n"
        "#   use_when              the trigger conditions, for selective installation\n"
    )
    # width=1000 keeps every scalar on one line. Prettier reflows wrapped YAML scalars,
    # which would rewrite this file after generation and leave `--check` permanently
    # failing in CI — the generator and the formatter must agree on one canonical form.
    return header + yaml.safe_dump(
        manifest, sort_keys=False, width=1000, allow_unicode=True, default_flow_style=False
    )


def render_catalog(manifest: dict) -> str:
    """Render the same source as prose designed for an LLM to read."""
    lines = [
        "# Skill catalog",
        "",
        "This file is generated from each skill's metadata. Do not edit it by hand.",
        "Use it to choose a small set of relevant skills without opening every skill file.",
        "",
        "## Start here",
        "",
        "Every installed skill's name and description sit in the system prompt on _every_",
        "turn, and its body loads whenever it triggers, so a long list costs attention on",
        "work that has nothing to do with it.",
        "Unless the person asks for something specific, propose these three and stop:",
        "",
        "- **`deep-dive`** — \"Go figure this out\" returns a recommendation instead of a",
        "  reading list. (Claude: degraded)",
        "- **`keep-going`** — It finishes the work instead of stopping to ask which option",
        "  you want. (Claude: native)",
        "- **`multi-review`** — Important drafts and decisions get reviewed from several",
        "  angles first. (Claude: degraded)",
        "",
        "Everything below is the full index, for when someone names a need these three do",
        "not cover.",
        "",
        "`Claude` values: `native` (works fully), `degraded` (runs but loses its",
        "differentiator — say so out loud), `unsupported` (never recommend it in Claude).",
        "",
    ]
    for entry in manifest["skills"]:
        requirements = ", ".join(entry["requires"]) or "None"
        use_when_text = entry["use_when"] or entry["summary"]
        size = entry["size"]
        lines.extend(
            [
                f"## {entry['name']}",
                "",
                # Lead with the disqualifier. Two live Claude Code runs recommended
                # skills whose `Claude:` line said not to, because `Prerequisites:
                # None` and `Works without setup: Yes` sit ABOVE it and read as
                # approval. An agent scanning an entry acts on the first strong
                # signal, so the veto has to come before the green lights.
                *(
                    [
                        f"> **Not for Claude.** {entry['claude_note']}",
                        "",
                    ]
                    if entry["claude_compat"] == "unsupported"
                    else []
                ),
                f"- **Pack:** {entry['pack']}",
                f"- **Scope:** {entry['scope']}",
                f"- **What it does:** {entry['summary']}",
                f"- **Use when:** {use_when_text}",
                f"- **Prerequisites:** {requirements}",
                # A degraded skill needs no setup and still is not the full thing. A live
                # Claude Code run offered all three degraded skills as "Works immediately,
                # no setup" with no caveat, because a bare Yes reads as an unqualified
                # green light and outranks a rule sitting in another file.
                (
                    f"- **Works without setup:** "
                    + ("Yes" if entry["works_out_of_the_box"] else "No")
                    + (
                        ", but read the Claude note before recommending it"
                        if entry["claude_compat"] == "degraded"
                        else (
                            " in Hermes (not available in Claude)"
                            if entry["claude_compat"] == "unsupported"
                            else ""
                        )
                    )
                ),
                f"- **Compatibility:** {entry['compatibility']}",
                f"- **Claude:** {entry['claude_compat']} — {entry['claude_note']}",
                (
                    f"- **Size:** {size['bytes_skill_md']:,} B body, loaded when the skill triggers "
                    f"(~{size['approx_tokens_skill_md']:,} tokens); "
                    f"{size['bytes_total']:,} B across {size['files']} file(s) total"
                ),
                f"- **Path:** `{entry['path']}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed manifest is stale (used by CI)",
    )
    args = parser.parse_args()

    manifest = build()
    rendered = render(manifest)
    rendered_catalog = render_catalog(manifest)

    if args.check:
        if not MANIFEST.exists():
            print(f"MISSING: {MANIFEST.relative_to(ROOT)} — run scripts/generate_manifest.py")
            return 1
        if MANIFEST.read_text() != rendered:
            print(
                f"STALE: {MANIFEST.relative_to(ROOT)} disagrees with skills/ on disk.\n"
                "Run `python scripts/generate_manifest.py` and commit the result."
            )
            return 1
        if not CATALOG.exists():
            print(f"MISSING: {CATALOG.relative_to(ROOT)} — run scripts/generate_manifest.py")
            return 1
        if CATALOG.read_text() != rendered_catalog:
            print(
                f"STALE: {CATALOG.relative_to(ROOT)} disagrees with skills/ on disk.\n"
                "Run `python scripts/generate_manifest.py` and commit the result."
            )
            return 1
        print(f"OK: {MANIFEST.relative_to(ROOT)} matches disk")
        print(f"OK: {CATALOG.relative_to(ROOT)} matches disk")
        return 0

    MANIFEST.write_text(rendered)
    CATALOG.write_text(rendered_catalog)
    print(f"wrote {MANIFEST.relative_to(ROOT)}")
    print(f"wrote {CATALOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
