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
    return clause[:300].rstrip(" ,;") + ("…" if len(clause) > 300 else "")


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
    ]
    for entry in manifest["skills"]:
        requirements = ", ".join(entry["requires"]) or "None"
        use_when_text = entry["use_when"] or entry["summary"]
        lines.extend(
            [
                f"## {entry['name']}",
                "",
                f"- **Pack:** {entry['pack']}",
                f"- **Scope:** {entry['scope']}",
                f"- **What it does:** {entry['summary']}",
                f"- **Use when:** {use_when_text}",
                f"- **Prerequisites:** {requirements}",
                f"- **Works without setup:** {'Yes' if entry['works_out_of_the_box'] else 'No'}",
                f"- **Compatibility:** {entry['compatibility']}",
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
