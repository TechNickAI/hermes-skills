"""Structural guarantees for the skill library.

These enforce the properties a consumer actually depends on: the manifest is
honest, packs are meaningful, and nothing here leaks fleet identity. Content
quality is a review concern; this file guards the mechanical invariants that
silently rot.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
MANIFEST = SKILLS / "MANIFEST.yaml"

# A pack is a top-level grouping under skills/. Adding one is a deliberate act,
# so the list is explicit — a stray directory should fail, not silently become
# a pack that agents can tap.
EXPECTED_PACKS = {"core", "engineering", "productivity"}


def skill_dirs() -> list[pathlib.Path]:
    return sorted(
        d
        for pack in SKILLS.iterdir()
        if pack.is_dir()
        for d in pack.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def frontmatter_of(skill: pathlib.Path) -> dict:
    text = (skill / "SKILL.md").read_text()
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text())


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_every_pack_is_expected():
    found = {p.name for p in SKILLS.iterdir() if p.is_dir()}
    assert found == EXPECTED_PACKS, (
        f"Unexpected pack layout: {found ^ EXPECTED_PACKS}. Adding a pack is "
        "deliberate — update EXPECTED_PACKS and the README table together."
    )


def test_no_skill_sits_directly_under_skills():
    """A skill at skills/<name>/ would be invisible to a pack tap."""
    strays = [
        p.name for p in SKILLS.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    ]
    assert not strays, f"Skills outside a pack (unreachable by tap): {strays}"


def test_skill_names_are_unique_across_packs():
    """Duplicate names are ambiguous once installed — the loader sees one flat
    namespace, regardless of which pack a skill came from."""
    names = [d.name for d in skill_dirs()]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"Same skill name in more than one pack: {dupes}"


def test_skill_dir_name_matches_declared_name():
    mismatched = {
        d.name: frontmatter_of(d).get("name")
        for d in skill_dirs()
        if frontmatter_of(d).get("name") != d.name
    }
    assert not mismatched, f"Directory name disagrees with frontmatter name: {mismatched}"


# ---------------------------------------------------------------------------
# Manifest honesty
# ---------------------------------------------------------------------------


def test_manifest_is_not_stale():
    result = subprocess.run(
        [sys.executable, "scripts/generate_manifest.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_covers_every_skill():
    listed = {e["name"] for e in manifest()["skills"]}
    on_disk = {d.name for d in skill_dirs()}
    assert listed == on_disk, f"Manifest disagrees with disk: {listed ^ on_disk}"


def test_manifest_pack_matches_directory():
    by_name = {e["name"]: e["pack"] for e in manifest()["skills"]}
    for d in skill_dirs():
        assert by_name[d.name] == d.parent.name


def test_works_out_of_the_box_agrees_with_requires():
    """A skill advertising zero setup while declaring requirements sends a
    setup agent to install something that fails on first use."""
    for entry in manifest()["skills"]:
        assert entry["works_out_of_the_box"] == (not entry["requires"]), entry["name"]


# ---------------------------------------------------------------------------
# Frontmatter contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_skill_declares_version_and_description(skill: pathlib.Path):
    fm = frontmatter_of(skill)
    assert fm, f"{skill.name}: unparseable or missing frontmatter"
    assert fm.get("version"), f"{skill.name}: no version (updates cannot be detected)"
    assert re.match(r"^\d+\.\d+\.\d+$", str(fm["version"])), (
        f"{skill.name}: version {fm['version']!r} is not semver"
    )
    description = str(fm.get("description", "")).strip()
    assert description, f"{skill.name}: no description — it would never be selected"
    assert len(description) > 40, (
        f"{skill.name}: description too thin to route on: {description!r}"
    )


def test_related_skills_resolve_or_are_marked_external():
    have = {d.name for d in skill_dirs()}
    for skill in skill_dirs():
        meta = (frontmatter_of(skill).get("metadata") or {}).get("hermes") or {}
        for name in meta.get("related_skills") or []:
            assert name in have, (
                f"{skill.name} lists related skill {name!r}, which is not in this "
                "repo. Remove it, or note it in a comment as intentionally external."
            )


# ---------------------------------------------------------------------------
# Publication safety
# ---------------------------------------------------------------------------


def test_no_pii_in_any_skill():
    """The repo is public. This is the gate that keeps it publishable."""
    result = subprocess.run(
        [sys.executable, "scripts/pii_scan.py", "skills/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert "blockers=   0" in result.stdout or "TOTAL blockers=0" in result.stdout, (
        "PII scan found blockers:\n" + result.stdout
    )


# The scanner is the only thing standing between an agent's working notes and a
# public repo, so its boundaries are pinned by example. Each false-positive case
# below is one that actually fired during the migration.
PII_CASES = [
    # (text, should_be_flagged)
    ("the bosun profile owns this", True),
    ("run on cora and sterling", True),
    ("dashboard slug hermes-argus", True),
    ("Ace reboots logged out", True),
    ("APP_PASSWORD_HERMES_BOSUN", True),
    ("ssh ace 'uptime'", True),
    ("/hermes-ace/ dashboard", True),
    ("hermes-cora dashboard", True),
    ("implement the interface cleanly", False),
    ("replace the old value", False),
    ("free workspace on the host", False),
    ("trace the request path", False),
    ("a marketplace listing", False),
    ("hermes-atlas is the new slug", False),
    # Quote-spliced and regex-literal mentions, from a skill that documents
    # this exact matching problem.
    ("com.apple.f'ace'timemessagestored", False),
    ("appapl'ace'holdersyncd", False),
    ("unanchored /hermes|ace/ matched", False),
]


@pytest.mark.parametrize("text,flagged", PII_CASES, ids=lambda v: str(v)[:40])
def test_pii_scanner_boundaries(text, flagged, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import importlib

        pii = importlib.import_module("pii_scan")
        importlib.reload(pii)
    finally:
        sys.path.pop(0)
    probe = tmp_path / "probe.py"
    probe.write_text(text)
    hits = [h for h in pii.scan(probe) if h[1] == "agent-name"]
    assert bool(hits) == flagged, f"{text!r}: expected flagged={flagged}, got {hits}"
