"""Tests for skill-librarian's audit.py.

DESIGN RULE: every check must be proven to FAIL on a broken fixture, not just
pass on a healthy one. A check that cannot fail is worthless. Each test here
builds the broken case, asserts detection, then builds the healthy control and
asserts silence -- both directions, every time.

Run:  python -m pytest skills/core/skill-librarian/tests/ -v
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
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


def test_archive_only_duplicate_is_info_not_error(tmp_path):
    """Archive-only copies are the normal end state of deliberate archiving.

    Verified on a real fleet: `omnirouter` appeared as an archive-only orphan
    on 7 agents and every one was a deliberate role-fit archive, not a loss.
    Reporting deliberate curation as an error trains the reader to ignore the
    check. The live-index check catches the case that actually matters.
    """
    write_skill(tmp_path, ".archive/one", "ghost")
    write_skill(tmp_path, ".archive/two", "ghost")
    f = audit.check_collisions(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "collision.duplicate_name", "error"), \
        "deliberate archiving must not be an error"
    assert checks(f, "collision.duplicate_name", "info")


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


def test_archived_copy_exempt_from_name_dir_check(tmp_path):
    """Archiving renames the DIRECTORY but not the frontmatter name.

    An archived skill lands in e.g. `.archive/plan-merged-20260816-114638/`
    while still declaring `name: plan`, so it would report a mismatch forever.
    Verified on a real fleet: 3 of 4 non-obvious mismatches were archive or
    backup directories.
    """
    write_skill(tmp_path, ".archive", "my-skill-merged-20260816-114638",
                declared_name="my-skill")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "frontmatter.name_matches_directory"), \
        "archived copies keep their original name by design"


def test_live_copy_still_checked_for_name_dir(tmp_path):
    """NEGATIVE CONTROL: exempting archives must not disable the check."""
    write_skill(tmp_path, "cat", "actual-dir", declared_name="declared-name")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "frontmatter.name_matches_directory", "error")


# ------------------------------------------------------------ runtime budgets
#
# These checks exist because the collector was blind to the two limits the
# runtime actually enforces: the 100k write cap (patches refused) and the
# ~60-char prompt truncation (description ignored past that point). Both
# failures are SILENT in normal operation, so each test below builds the
# broken case, asserts detection, then asserts the healthy control is silent.


def _pad_to(root, category, name, target_chars, **kw):
    """Write a skill whose whole SKILL.md is ~target_chars long."""
    p = write_skill(root, category, name, body="# Body\n\nx\n", **kw)
    base = len(p.read_text())
    if target_chars > base:
        p.write_text(p.read_text() + ("filler line for size\n" * ((target_chars - base) // 20 + 1)))
    return p


def _set_exact_size(path: Path, target_chars: int) -> None:
    text = path.read_text()
    assert len(text) <= target_chars
    path.write_text(text + ("x" * (target_chars - len(text))))


def test_skill_exactly_at_write_cap_is_valid(tmp_path):
    p = write_skill(tmp_path, "cat", "exactly-at-cap")
    _set_exact_size(p, audit.WRITE_CAP_CHARS)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "budget.write_cap_exceeded"), \
        "the runtime rejects only content strictly greater than 100k chars"


def test_skill_over_write_cap_is_an_error_but_shrink_is_valid(tmp_path):
    p = write_skill(tmp_path, "cat", "fat")
    _set_exact_size(p, audit.WRITE_CAP_CHARS + 1)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    hits = checks(f, "budget.write_cap_exceeded", "error")
    assert hits and hits[0].evidence["over_by"] == 1
    assert "every patch" not in hits[0].message.lower(), \
        "over-cap content can still be replaced by a shrink-to-under patch"

    p.write_text(p.read_text()[: audit.WRITE_CAP_CHARS - 1])
    repaired = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(repaired, "budget.write_cap_exceeded")


def test_skill_below_cap_is_silent(tmp_path):
    _pad_to(tmp_path, "cat", "lean", 5_000)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "budget.write_cap_exceeded"), \
        "NEGATIVE CONTROL: a normal-sized skill must not be reported frozen"
    assert not checks(f, "budget.write_cap_approaching")


def test_skill_approaching_cap_warns_before_it_freezes(tmp_path):
    _pad_to(tmp_path, "cat", "nearly", int(audit.WRITE_CAP_CHARS * 0.95))
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert checks(f, "budget.write_cap_approaching", "warn"), \
        "the band below the cap is the whole point - a library piles up THERE"
    assert not checks(f, "budget.write_cap_exceeded"), \
        "under the cap is not yet frozen"


def test_archived_oversize_skill_is_not_reported(tmp_path):
    """An archived copy accepts no writes by design; freezing it is meaningless."""
    _pad_to(tmp_path, ".archive/20260101", "old-fat", audit.WRITE_CAP_CHARS + 500)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "budget.write_cap_exceeded"), \
        "archived skills must be exempt - they are not meant to grow"


def test_description_past_prompt_limit_is_flagged_with_the_lost_text(tmp_path):
    tail = "THIS TAIL IS NEVER SEEN BY THE MODEL DURING SELECTION"
    write_skill(tmp_path, "cat", "verbose",
                description="Use when the widget jams. " + tail)
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    hits = checks(f, "description.exceeds_prompt_limit", "warn")
    assert hits, "a description longer than the prompt limit must be flagged"
    # The finding has to show WHICH text is being discarded, otherwise the
    # reader cannot tell whether anything load-bearing was lost.
    assert hits[0].evidence["lost_text"], "must report the text that never reaches selection"
    assert len(hits[0].evidence["visible_text"]) == audit.PROMPT_DESC_CHARS - 3


def test_short_description_within_prompt_limit_is_silent(tmp_path):
    write_skill(tmp_path, "cat", "terse", description="Use when a widget jams. Clears it.")
    f = audit.check_mechanical(audit.collect([("profile", tmp_path)]))
    assert not checks(f, "description.exceeds_prompt_limit"), \
        "NEGATIVE CONTROL: a description inside the limit must not be flagged"


def test_prompt_limit_is_not_a_second_hardcoded_copy():
    """The defect this whole layer exists to prevent.

    The collector previously carried DESC_MAX=1024 while the runtime truncated
    at 60, so every over-long description passed clean. Whatever the runtime
    says must be what we measure.
    """
    assert audit.PROMPT_DESC_CHARS <= 200, \
        "a description ceiling in the hundreds means we are not reading the runtime limit"
    assert audit.WRITE_WARN_CHARS < audit.WRITE_CAP_CHARS


# ------------------------------------------------------------- index budget


class StubAdapter:
    def __init__(self, live, err=None):
        self._live = set(live)
        self._err = err

    def live_index(self):
        return self._live, self._err


def test_index_budget_counts_actual_resolved_enabled_selection(tmp_path):
    write_skill(tmp_path, "cat", "enabled")
    write_skill(tmp_path, "cat", "disabled-or-filtered")
    write_skill(tmp_path, "cat", "shadowed-file-row")
    skills = audit.collect([("profile", tmp_path)])
    f, skipped = audit.check_index_budget(skills, StubAdapter({"enabled"}))
    assert not skipped
    assert f[0].evidence["live_skills"] == 1
    assert f[0].evidence["names"] == ["enabled"]


def test_index_budget_degrades_when_runtime_selection_unavailable(tmp_path):
    write_skill(tmp_path, "cat", "maybe-live")
    f, skipped = audit.check_index_budget(
        audit.collect([("profile", tmp_path)]), StubAdapter(set(), "probe failed"))
    assert f == []
    assert skipped == ["selection-index budget: probe failed"]


def test_index_budget_is_measurement_not_arbitrary_health_ceiling(tmp_path):
    long_desc = "Use when the widget jams. " + ("padding text " * 30)
    for i in range(400):
        write_skill(tmp_path, "cat", f"skill-{i}", description=long_desc)
    live = {f"skill-{i}" for i in range(400)}
    f, _ = audit.check_index_budget(audit.collect([("profile", tmp_path)]), StubAdapter(live))
    assert f[0].severity == "info"
    assert "budget_chars" not in f[0].evidence
    assert f[0].evidence["rendered_chars"] > 20_000


def test_index_budget_counts_truncated_not_authored_length(tmp_path):
    """Descriptions are truncated before entering the prompt."""

    # Reporting the authored total as per-turn cost invents a saving that does
    # not exist. The rendered figure must not scale with the authored one.
    long_desc = "Use when the widget jams. " + ("padding text " * 200)
    for i in range(5):
        write_skill(tmp_path, "cat", f"skill-{i}", description=long_desc)
    skills = audit.collect([("profile", tmp_path)])
    f, skipped = audit.check_index_budget(skills, StubAdapter({f"skill-{i}" for i in range(5)}))
    assert not skipped
    assert f, "the index budget must always be reported"
    e = f[0].evidence
    assert e["authored_desc_chars"] > 10_000, "fixture should have long authored descriptions"
    assert e["rendered_chars"] < e["authored_desc_chars"] / 5, \
        "rendered cost must reflect truncation, not authored length"
    assert e["descriptions_truncated"] == 5


def test_index_budget_reports_small_selection_without_warning(tmp_path):
    write_skill(tmp_path, "cat", "only-one")
    f, _ = audit.check_index_budget(
        audit.collect([("profile", tmp_path)]), StubAdapter({"only-one"}))
    assert f and f[0].severity == "info"


def test_index_budget_uses_resolved_selection_not_archives(tmp_path):
    write_skill(tmp_path, ".archive/20260101", "gone")
    write_skill(tmp_path, "cat", "here")
    f, _ = audit.check_index_budget(
        audit.collect([("profile", tmp_path)]), StubAdapter({"here"}))
    assert f[0].evidence["live_skills"] == 1


# ----------------------------------------------------------- growth snapshot


def test_unchanged_large_skill_is_not_claimed_to_have_refused_writes(tmp_path):
    _pad_to(tmp_path, "cat", "stable", int(audit.WRITE_CAP_CHARS * 0.95))
    snap = tmp_path / "snap.json"
    skills = audit.collect([("profile", tmp_path)])
    first, state, degraded = audit.check_growth(skills, str(snap))
    assert not first and not degraded
    audit.write_snapshot(str(snap), state)

    second, _, degraded = audit.check_growth(
        audit.collect([("profile", tmp_path)]), str(snap))
    assert not checks(second, "budget.stuck_at_cap")
    assert not degraded


def test_corrupt_json_snapshot_is_explicitly_degraded(tmp_path):
    _pad_to(tmp_path, "cat", "any", 3_000)
    snap = tmp_path / "snap.json"
    snap.write_text("{ this is not json")
    f, state, degraded = audit.check_growth(
        audit.collect([("profile", tmp_path)]), str(snap))
    assert f == [] and "skills" in state
    assert degraded and "snapshot read failed" in degraded[0]


def test_sqlite_snapshot_round_trip(tmp_path):
    _pad_to(tmp_path, "cat", "any", 3_000)
    snap = tmp_path / "snap.sqlite"
    skills = audit.collect([("profile", tmp_path)])
    _, state, degraded = audit.check_growth(skills, str(snap))
    assert not degraded
    assert audit.write_snapshot(str(snap), state) is None
    _, _, degraded = audit.check_growth(skills, str(snap))
    assert not degraded
    with sqlite3.connect(snap) as db:
        assert db.execute("select count(*) from skill_sizes").fetchone()[0] == 1


def test_corrupt_sqlite_snapshot_is_explicitly_degraded(tmp_path):
    _pad_to(tmp_path, "cat", "any", 3_000)
    snap = tmp_path / "snap.sqlite"
    snap.write_bytes(b"not a sqlite database")
    _, _, degraded = audit.check_growth(
        audit.collect([("profile", tmp_path)]), str(snap))
    assert degraded and "snapshot read failed" in degraded[0]


def test_missing_snapshot_is_a_clean_first_run(tmp_path):
    _pad_to(tmp_path, "cat", "any", 3_000)
    f, state, degraded = audit.check_growth(
        audit.collect([("profile", tmp_path)]), str(tmp_path / "does-not-exist.json"))
    assert f == [] and state["skills"] and not degraded


def test_live_index_probe_uses_absolute_runtime_path(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    runtime = tmp_path / ".hermes" / "hermes-agent"
    py = runtime / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    monkeypatch.setattr(audit.Path, "home", classmethod(lambda cls: tmp_path))
    captured = {}

    def fake_run(argv, **kwargs):
        captured["code"] = argv[2]
        return type("Result", (), {"returncode": 0, "stdout": "cat\n", "stderr": ""})()

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    live, err = audit.HermesAdapter(profile).live_index()
    assert live == {"cat"} and err is None
    assert str(runtime) in captured["code"]
    assert "expanduser('~/.hermes" not in captured["code"]


# ------------------------------------------------ supporting files and links


def _supporting_findings(root):
    return audit.check_supporting_files(audit.collect([("profile", root)]))


def test_supporting_file_exactly_at_both_limits_is_valid(tmp_path):
    skill = write_skill(tmp_path, "cat", "bounded")
    support = skill.parent / "references" / "large.md"
    support.parent.mkdir()
    support.write_text("é" * audit.SUPPORTING_MAX_CHARS)
    assert len(support.read_bytes()) <= audit.SUPPORTING_MAX_BYTES
    assert not checks(_supporting_findings(tmp_path), "budget.supporting_file_exceeded")


def test_supporting_file_over_character_cap_is_error(tmp_path):
    skill = write_skill(tmp_path, "cat", "too-many-chars")
    support = skill.parent / "references" / "large.md"
    support.parent.mkdir()
    support.write_text("x" * (audit.SUPPORTING_MAX_CHARS + 1))
    hits = checks(_supporting_findings(tmp_path), "budget.supporting_file_exceeded", "error")
    assert hits and hits[0].evidence["chars"] == audit.SUPPORTING_MAX_CHARS + 1


def test_supporting_file_over_byte_cap_is_error(tmp_path):
    skill = write_skill(tmp_path, "cat", "too-many-bytes")
    support = skill.parent / "references" / "large.md"
    support.parent.mkdir()
    support.write_text("🙂" * 270_000)
    hits = checks(_supporting_findings(tmp_path), "budget.supporting_file_exceeded", "error")
    assert hits and hits[0].evidence["bytes"] > audit.SUPPORTING_MAX_BYTES


def test_markdown_links_ignore_code_fences_but_check_prose(tmp_path):
    skill = write_skill(
        tmp_path, "cat", "links", body=(
            "# Body\n\n[missing](references/nope.md)\n\n"
            "```markdown\n[example](references/example-only.md)\n```\n"))
    findings = audit.check_markdown_links(audit.collect([("profile", tmp_path)]))
    hits = checks(findings, "links.markdown_target_resolves", "warn")
    assert [h.evidence["target"] for h in hits] == ["references/nope.md"]
    (skill.parent / "references").mkdir()
    (skill.parent / "references" / "nope.md").write_text("ok")
    assert not checks(
        audit.check_markdown_links(audit.collect([("profile", tmp_path)])),
        "links.markdown_target_resolves")
