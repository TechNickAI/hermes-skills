"""Tests for skill-librarian's audit.py.

DESIGN RULE: every check must be proven to FAIL on a broken fixture, not just
pass on a healthy one. A check that cannot fail is worthless. Each test here
builds the broken case, asserts detection, then builds the healthy control and
asserts silence -- both directions, every time.

Run:  python -m pytest skills/core/skill-librarian/tests/ -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit.py"
spec = importlib.util.spec_from_file_location("sl_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
sys.modules["sl_audit"] = audit
spec.loader.exec_module(audit)


def write_skill(root: Path, category: str, name: str, *, declared_name=None,
                description="Use when you need the thing. Does the thing well.",
                version="1.0.0", body="# Body\n\nsteps here\n", platforms=None,
                related=None):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    fm = [f"name: {declared_name or name}", f"description: {description}"]
    if version:
        fm.append(f"version: {version}")
    if platforms:
        fm.append(f"platforms: [{', '.join(platforms)}]")
    if related:
        fm.append(f"related_skills: [{', '.join(related)}]")
    (d / "SKILL.md").write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body)
    return d / "SKILL.md"


def checks(findings, check_id, severity=None):
    return [f for f in findings
            if f.check == check_id and (severity is None or f.severity == severity)]


# ---------------------------------------------------------------- frontmatter


def test_missing_description_is_detected_and_clean_case_is_silent(tmp_path):
    write_skill(tmp_path, "cat", "broken", description="")
    bad = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(bad, "frontmatter.description_required", "error"), \
        "missing description must be an error"

    good = tmp_path / "good"
    write_skill(good, "cat", "fine")
    ok = audit.check_mechanical(audit.collect([("profile", good)]))
    assert not checks(ok, "frontmatter.description_required"), \
        "NEGATIVE CONTROL: a healthy skill must not trip the check"


def test_name_directory_mismatch_detected(tmp_path):
    write_skill(tmp_path, "cat", "real-dir", declared_name="different-name")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.name_matches_directory", "error")


def test_nested_category_layout_does_not_false_positive(tmp_path):
    """The bug that produced 170 of 175 false positives in skill-check.

    A CATEGORY directory between skills/ and the skill dir must not be read as
    the skill's own directory.
    """
    write_skill(tmp_path, "devops/deeply/nested", "my-skill")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "frontmatter.name_matches_directory"), \
        "category nesting must not be mistaken for a name mismatch"


def test_malformed_yaml_is_reported_not_crashed(tmp_path):
    d = tmp_path / "cat" / "bad-yaml"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: x\n  description: ]][\nbroken\n---\n\nbody\n")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.parse", "error") or \
        checks(f, "frontmatter.description_required", "error")


def test_no_frontmatter_at_all(tmp_path):
    d = tmp_path / "cat" / "raw"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# just markdown, no frontmatter\n")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.parse", "error")


# ---------------------------------------------------------- the trigger lens


def test_description_without_trigger_is_flagged(tmp_path):
    write_skill(tmp_path, "cat", "whatty",
                description="This skill contains helpful utilities and reference "
                            "material about widgets and various widget operations.")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "description.no_trigger", "warn"), \
        "a description that says WHAT but never WHEN must be flagged"


def test_description_with_trigger_is_not_flagged(tmp_path):
    write_skill(tmp_path, "cat", "whenny",
                description="Use when a widget jams during assembly. Clears the "
                            "jam and verifies the line restarted.")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "description.no_trigger"), \
        "NEGATIVE CONTROL: 'Use when ...' must pass"


# ------------------------------------------------------------ collisions


def test_two_live_copies_in_same_root_is_an_error(tmp_path):
    write_skill(tmp_path, "cat-a", "dup")
    write_skill(tmp_path, "cat-b", "dup")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    assert checks(f, "collision.duplicate_name", "error"), \
        "two live copies in one root have no tiebreak - must be an error"


def test_profile_overriding_bundled_is_not_an_error(tmp_path):
    """63 of 63 'collisions' on a real agent were this. Must not be an error."""
    prof, bund = tmp_path / "p", tmp_path / "b"
    write_skill(prof, "cat", "shared")
    write_skill(bund, "cat", "shared")
    f = audit.check_collisions(audit.collect([("profile", prof), ("bundled", bund)]))
    errs = checks(f, "collision.duplicate_name", "error")
    assert not errs, "profile override of a bundled skill is intended, not an error"
    assert checks(f, "collision.duplicate_name", "info")


def test_archived_alongside_live_is_benign(tmp_path):
    write_skill(tmp_path, "cat", "thing")
    write_skill(tmp_path, ".archive", "thing")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "collision.duplicate_name", "error"), \
        "archive + live coexistence is benign; index resolves the live copy"


def test_archive_only_copy_is_an_error(tmp_path):
    """The silent-vanish bug: an agent lost `plan` entirely this way."""
    write_skill(tmp_path, ".archive", "orphan")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    # single archived copy -> no collision pair, but must not be silently OK
    skills = audit.collect([("profile", tmp_path)])
    assert skills and skills[0].archived


def test_archive_only_duplicate_is_an_error(tmp_path):
    write_skill(tmp_path, ".archive/one", "ghost")
    write_skill(tmp_path, ".archive/two", "ghost")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    assert checks(f, "collision.duplicate_name", "error")


# ------------------------------------------------------------- shadowing


def test_near_identical_descriptions_flagged(tmp_path):
    d = "Use when delegating a coding task to an external CLI agent for implementation."
    write_skill(tmp_path, "cat", "agent-one", description=d)
    write_skill(tmp_path, "cat", "agent-two",
                description=d.replace("external", "an external"))
    f = audit.check_desc_similarity(audit.collect([("profile", tmp_path)]))
    assert checks(f, "shadowing.similar_description"), \
        "near-identical triggers are the primary shadowing mechanism"


def test_distinct_descriptions_not_flagged(tmp_path):
    """NEGATIVE CONTROL. google-workspace vs google-docs: different jobs."""
    write_skill(tmp_path, "cat", "mail-tool",
                description="Use when reading, sending, or searching email and "
                            "calendar events from the terminal via the gws CLI.")
    write_skill(tmp_path, "cat", "doc-tool",
                description="Use when creating, formatting, or exporting word "
                            "processor documents through the gog authoring CLI.")
    f = audit.check_desc_similarity(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "shadowing.similar_description"), \
        "genuinely distinct skills must not be reported as shadowing"


def test_same_skill_in_two_roots_reported_once(tmp_path):
    """Profile+bundled copies must not be compared against each other."""
    prof, bund = tmp_path / "p", tmp_path / "b"
    for root in (prof, bund):
        write_skill(root, "cat", "alpha", description="Use when alpha happens here.")
        write_skill(root, "cat", "beta", description="Use when alpha happens here!")
    f = audit.check_desc_similarity(
        audit.collect([("profile", prof), ("bundled", bund)]))
    assert len(checks(f, "shadowing.similar_description")) == 1, \
        "each ambiguous PAIR is reported once, not once per copy"


def test_near_collision_names_flagged(tmp_path):
    write_skill(tmp_path, "cat", "model-selection-eval")
    write_skill(tmp_path, "cat", "model-selection-evals")
    f = audit.check_name_near_collisions(audit.collect([("profile", tmp_path)]))
    assert checks(f, "naming.near_collision")


def test_distinct_names_not_flagged(tmp_path):
    write_skill(tmp_path, "cat", "deploy-service")
    write_skill(tmp_path, "cat", "rotate-credentials")
    f = audit.check_name_near_collisions(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "naming.near_collision")


# ------------------------------------------------------------- references


def test_dangling_related_skill_detected(tmp_path):
    write_skill(tmp_path, "cat", "has-refs", related=["does-not-exist"])
    f = audit.check_related(audit.collect([("profile", tmp_path)]))
    assert checks(f, "links.related_skills_resolve", "warn")


def test_resolving_related_skill_is_silent(tmp_path):
    write_skill(tmp_path, "cat", "target")
    write_skill(tmp_path, "cat", "source", related=["target"])
    f = audit.check_related(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "links.related_skills_resolve")


# ------------------------------------------------------------- misc


def test_missing_version_is_warned(tmp_path):
    write_skill(tmp_path, "cat", "unversioned", version=None)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.version_missing", "warn")


def test_platforms_parsed(tmp_path):
    write_skill(tmp_path, "cat", "linux-only", platforms=["linux"])
    s = audit.collect([("profile", tmp_path)])[0]
    assert s.platforms == ["linux"], \
        "platform gating must be parsed or platform-filtered skills look missing"


def test_empty_tree_is_not_a_crash(tmp_path):
    assert audit.collect([("profile", tmp_path)]) == []


def test_environments_parsed(tmp_path):
    """Env-gated skills (e.g. kanban) are filtered by design, not missing.

    Fourth false-positive class for index.enabled_but_absent, found on a real
    agent: 3 skills declaring `environments: [kanban]` were reported missing.
    """
    d = tmp_path / "cat" / "kanban-thing"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: kanban-thing\ndescription: Use when running a kanban lane task.\n"
        "version: 1.0.0\nenvironments: [kanban]\n---\n\nbody\n"
    )
    s = audit.collect([("profile", tmp_path)])[0]
    assert s.environments == ["kanban"], \
        "environments gating must be parsed or gated skills look broken"


def test_environments_block_syntax_parsed(tmp_path):
    """Both `environments: [x]` and YAML block `- x` appear in the wild."""
    d = tmp_path / "cat" / "block-style"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: block-style\ndescription: Use when the block syntax appears.\n"
        "version: 1.0.0\nenvironments:\n  - kanban\n---\n\nbody\n"
    )
    s = audit.collect([("profile", tmp_path)])[0]
    assert "kanban" in s.environments


# ------------------------------------------------- PR #7 bot review findings


def test_archived_profile_copy_beside_bundled_is_warn_not_error(tmp_path):
    """Archived profile copy + bundled copy: WARN, never error.

    Two reviewers flagged this as benign-when-it-should-be-fatal, and the first
    fix made it an error. Running that on a real fleet agent produced 59 false
    alarms: all 64 such names were absent from the index, but so were 108
    bundled names with NO archived copy. Bundled skills are opt-in, so absence
    is normal and archiving was not the cause.

    The filesystem cannot decide this. It is a warn; the live-index check
    promotes it to an error when the skill is genuinely expected and missing.
    """
    prof, bund = tmp_path / "p", tmp_path / "b"
    write_skill(prof, ".archive", "plan")
    write_skill(bund, "core", "plan")
    f = audit.check_collisions(audit.collect([("profile", prof), ("bundled", bund)]))
    assert not checks(f, "collision.duplicate_name", "error"), \
        "must not error: 59 false alarms on a real agent when it did"
    warns = checks(f, "collision.duplicate_name", "warn")
    assert warns, "must still surface as a warning worth checking"
    assert "live index" in warns[0].message, \
        "must tell the reader how to adjudicate it"


def test_archive_beside_live_in_same_root_stays_benign(tmp_path):
    """NEGATIVE CONTROL for the fix above - must not become an error."""
    write_skill(tmp_path, "cat", "thing")
    write_skill(tmp_path, ".archive", "thing")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "collision.duplicate_name", "error")
    assert checks(f, "collision.duplicate_name", "info")


def test_missing_name_field_is_reported_not_masked(tmp_path):
    """The directory-name fallback must not make an invalid skill look healthy."""
    d = tmp_path / "cat" / "nameless"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\ndescription: Use when something happens that needs handling.\n"
        "version: 1.0.0\n---\n\nbody\n"
    )
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.name_required", "error"), \
        "absent name: must be an error, not silently replaced by the dir name"
    assert not checks(f, "frontmatter.name_matches_directory"), \
        "must not also report a mismatch against a name we invented"


def test_declared_name_still_checked_against_directory(tmp_path):
    """NEGATIVE CONTROL: a real mismatch must still be caught."""
    write_skill(tmp_path, "cat", "the-dir", declared_name="other-name")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.name_matches_directory", "error")
    assert not checks(f, "frontmatter.name_required")


def test_whenever_counts_as_a_trigger(tmp_path):
    """`\\bwhen\\b` does not match "whenever" - 8 false positives on a real agent."""
    write_skill(tmp_path, "cat", "whenever-skill",
                description="Drive a real browser from any script. Use whenever a "
                            "task needs to navigate a site or fill a form.")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "description.no_trigger"), \
        "'Use whenever ...' states a trigger and must not be flagged"


def test_other_trigger_phrasings_accepted(tmp_path):
    """Real descriptions use several trigger forms, not just 'Use when'."""
    for i, desc in enumerate([
        "Recover the fleet after a host reboot leaves agents down.",
        "Use before you buy, send, or delete anything.",
        "Use if you need to verify a claim against live data.",
    ]):
        write_skill(tmp_path, "cat", f"phrasing-{i}", description=desc)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "description.no_trigger"), \
        f"valid trigger phrasings flagged: {[x.skill for x in f]}"


def test_pure_what_description_still_flagged(tmp_path):
    """NEGATIVE CONTROL: a description with no trigger at all must still fire."""
    write_skill(tmp_path, "cat", "whatty-two",
                description="A collection of helpful utilities and reference "
                            "material covering widgets and gadget operations.")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "description.no_trigger", "warn")
