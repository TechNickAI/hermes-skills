#!/usr/bin/env python3
"""skill-librarian: deterministic evidence collector.

This script COLLECTS FACTS. It does not draw conclusions and it never edits
anything. The agent reading its output applies judgement (Layer 3).

That split is deliberate: a script can tell you two descriptions are 91%
similar; only a reader can tell you whether an agent would be unable to choose
between them. See README.md.

Layers implemented here:
  1. mechanical  -- frontmatter parse, required fields, name/dir match, sizes
  2. structural  -- cross-root name collisions, archive shadowing, dead
                    disabled entries, live-index agreement

Runtime coupling is isolated in HermesAdapter. On a non-Hermes runtime the
Hermes-only facts are reported as "skipped", never silently dropped.

Usage:
    python audit.py --profile ~/.hermes/profiles/<agent>
    python audit.py --profile ~/.hermes/profiles/<agent> --json
    python audit.py --skills-dir ./skills          # any SKILL.md tree
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path

# --------------------------------------------------------------------------
# frontmatter parsing
# --------------------------------------------------------------------------

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def parse_frontmatter(text: str) -> tuple[dict, str, str | None]:
    """Return (fields, body, error).

    Uses PyYAML when available because skill frontmatter legitimately contains
    nested metadata and folded scalars; falls back to a flat top-level parse so
    the script still runs on a bare interpreter.
    """
    m = FM_RE.match(text)
    if not m:
        return {}, text, "no YAML frontmatter (file must start with ---)"
    raw, body = m.group(1), text[m.end():]
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            return {}, body, "frontmatter is not a mapping"
        return data, body, None
    except ImportError:
        pass
    except Exception as exc:  # malformed YAML is itself a finding
        return {}, body, f"YAML parse error: {type(exc).__name__}: {exc}"

    data: dict = {}
    key = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            data[key] = val.strip().strip("\"'")
        elif key and line.strip():
            data[key] = (str(data.get(key, "")) + " " + line.strip()).strip()
    return data, body, None


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


@dataclass
class Skill:
    name: str
    dir_name: str
    path: str
    root: str          # which tree it came from
    archived: bool
    description: str
    version: str | None
    body_lines: int
    platforms: list = field(default_factory=list)
    environments: list = field(default_factory=list)
    related: list = field(default_factory=list)
    errors: list = field(default_factory=list)


@dataclass
class Finding:
    check: str
    severity: str      # error | warn | info
    message: str
    skill: str | None = None
    path: str | None = None
    evidence: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------


def collect(roots: list[tuple[str, Path]]) -> list[Skill]:
    out: list[Skill] = []
    for label, root in roots:
        if not root or not root.is_dir():
            continue
        for smd in sorted(root.rglob("SKILL.md")):
            try:
                text = smd.read_text(errors="replace")
            except OSError as exc:
                out.append(Skill(smd.parent.name, smd.parent.name, str(smd), label,
                                 ".archive" in str(smd), "", None, 0,
                                 errors=[f"unreadable: {exc}"]))
                continue
            fm, body, err = parse_frontmatter(text)
            rel = fm.get("related_skills")
            if rel is None:
                meta = fm.get("metadata")
                if isinstance(meta, dict):
                    for v in meta.values():
                        if isinstance(v, dict) and "related_skills" in v:
                            rel = v["related_skills"]
                            break
            if isinstance(rel, str):
                rel = [x.strip() for x in rel.strip("[]").split(",") if x.strip()]
            ver = fm.get("version")
            plats = fm.get("platforms")
            if isinstance(plats, str):
                plats = [x.strip() for x in plats.strip("[]").split(",") if x.strip()]
            # `environments:` gates a skill to a runtime context (e.g. kanban).
            # Accepts both inline-list and YAML-block syntax.
            envs = fm.get("environments")
            if isinstance(envs, str):
                envs = [x.strip() for x in envs.strip("[]-").split(",") if x.strip()]
            out.append(Skill(
                name=str(fm.get("name") or smd.parent.name).strip(),
                dir_name=smd.parent.name,
                path=str(smd),
                root=label,
                archived=".archive" in str(smd),
                description=str(fm.get("description") or "").strip(),
                version=str(ver) if ver is not None else None,
                body_lines=len(body.splitlines()),
                platforms=list(plats or []),
                environments=list(envs or []),
                related=list(rel or []),
                errors=[err] if err else [],
            ))
    return out


# --------------------------------------------------------------------------
# layer 1 -- mechanical
# --------------------------------------------------------------------------

DESC_MIN, DESC_MAX, BODY_MAX = 40, 1024, 500


def check_mechanical(skills: list[Skill]) -> list[Finding]:
    f: list[Finding] = []
    for s in skills:
        for e in s.errors:
            f.append(Finding("frontmatter.parse", "error", e, s.name, s.path))
        if not s.description:
            f.append(Finding("frontmatter.description_required", "error",
                             "missing description", s.name, s.path))
        else:
            n = len(s.description)
            if n < DESC_MIN:
                f.append(Finding("description.too_short", "warn",
                                 f"description {n} chars (<{DESC_MIN}) - unlikely to "
                                 "state a trigger", s.name, s.path))
            if n > DESC_MAX:
                f.append(Finding("description.too_long", "warn",
                                 f"description {n} chars (>{DESC_MAX})", s.name, s.path))
            # trigger-lens: does it say WHEN, or only WHAT?
            if not re.search(r"\buse (when|for)\b|\bwhen\b|\btrigger", s.description, re.I):
                f.append(Finding("description.no_trigger", "warn",
                                 "description does not state WHEN to invoke "
                                 "(no 'use when'/'when'/trigger phrasing)",
                                 s.name, s.path,
                                 {"description": s.description[:200]}))
        if not s.version:
            f.append(Finding("frontmatter.version_missing", "warn",
                             "no version: field - invisible to curator staleness checks",
                             s.name, s.path))
        # name vs the TRUE skill dir (not the category dir). This is the check
        # skill-check gets wrong on nested layouts: 170/175 false positives.
        if s.name != s.dir_name:
            f.append(Finding("frontmatter.name_matches_directory", "error",
                             f"frontmatter name '{s.name}' != directory '{s.dir_name}'",
                             s.name, s.path))
        if s.body_lines > BODY_MAX:
            f.append(Finding("body.too_long", "warn",
                             f"body {s.body_lines} lines (>{BODY_MAX}) - consider "
                             "splitting into references/", s.name, s.path))
    return f


def check_related(skills: list[Skill]) -> list[Finding]:
    known = {s.name for s in skills}
    out = []
    for s in skills:
        if s.archived:
            continue
        for r in s.related:
            if r and r not in known:
                out.append(Finding("links.related_skills_resolve", "warn",
                                   f"related_skills points at '{r}' which does not exist",
                                   s.name, s.path, {"missing": r}))
    return out


# --------------------------------------------------------------------------
# layer 2 -- structural
# --------------------------------------------------------------------------


def check_collisions(skills: list[Skill]) -> list[Finding]:
    """Name collisions, split by whether the runtime can still resolve a winner.

    Three cases, and conflating them produces a flood of false positives:

    OVERRIDE (info): a profile copy shadowing a BUNDLED copy of the same name.
      This is the documented, intended way to customise a shipped skill -- the
      profile wins. Measured on a real agent: 63 of 63 "collisions" were this.
      Reporting these as errors buries the two that matter.

    AMBIGUOUS (error): two live copies within the SAME root. Nothing decides a
      winner.

    ORPHANED-ARCHIVE (error): the only copies are archived. If a bundled skill
      shares the name, both can vanish from the index with no error -- the
      silent-shadowing bug this skill exists to catch.

    BENIGN (info): an archived copy alongside a live one; the index resolves the
      live path.
    """
    out = []
    by_name: dict[str, list[Skill]] = {}
    for s in skills:
        by_name.setdefault(s.name, []).append(s)

    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        live = [g for g in group if not g.archived]
        arch = [g for g in group if g.archived]
        roots = {g.root for g in live}

        if len(live) >= 2 and roots == {"profile", "bundled"}:
            sev, why = "info", ("profile copy overrides the bundled copy - intended "
                                "behaviour, profile wins")
        elif len(live) >= 2 and len(roots) == 1:
            sev, why = "error", (f"{len(live)} live copies inside root '{roots.pop()}' - "
                                 "nothing decides which wins")
        elif len(live) >= 2:
            sev, why = "warn", (f"live copies across roots {sorted(roots)} - verify which "
                                "the runtime resolves")
        elif live and arch:
            sev, why = "info", ("archived copy coexists with a live copy - benign, index "
                                "resolves the live path")
        else:
            sev, why = "error", ("only archived copies exist - if a bundled skill shares "
                                 "this name, BOTH may vanish from the index")

        out.append(Finding("collision.duplicate_name", sev, f"'{name}': {why}", name,
                           None, {"paths": [g.path for g in group]}))
    return out


def check_desc_similarity(skills: list[Skill], threshold: float = 0.80) -> list[Finding]:
    """Near-identical DESCRIPTIONS = shadowing risk, regardless of body overlap.

    This is the arXiv:2605.24050 failure mode. Two skills can share only 2% of
    their bodies and still be unselectable. Body overlap is reported alongside
    so the agent can judge, but similarity of the TRIGGER is what is flagged.
    """
    out = []
    # Dedupe by NAME first: the same skill can appear in several roots (profile
    # override of a bundled copy), and comparing every copy against every other
    # reports the same pair repeatedly. One entry per name, profile copy wins.
    best: dict[str, Skill] = {}
    for s in skills:
        if s.archived or not s.description:
            continue
        cur = best.get(s.name)
        if cur is None or (cur.root != "profile" and s.root == "profile"):
            best[s.name] = s
    live = sorted(best.values(), key=lambda s: s.name)

    for i, a in enumerate(live):
        for b in live[i + 1:]:
            r = SequenceMatcher(None, norm_text(a.description),
                                norm_text(b.description)).ratio()
            if r >= threshold:
                out.append(Finding(
                    "shadowing.similar_description",
                    "error" if r >= 0.92 else "warn",
                    f"'{a.name}' and '{b.name}' descriptions are {r:.0%} similar - "
                    "agent may be unable to choose",
                    f"{a.name} | {b.name}", None,
                    {"similarity": round(r, 3), "a": a.path, "b": b.path},
                ))
    return out


def check_name_near_collisions(skills: list[Skill]) -> list[Finding]:
    """Names differing only by a character or two (eval vs evals)."""
    out = []
    live = sorted({s.name for s in skills if not s.archived})
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if abs(len(a) - len(b)) > 3:
                continue
            r = SequenceMatcher(None, a, b).ratio()
            if r >= 0.88:
                out.append(Finding("naming.near_collision", "warn",
                                   f"'{a}' and '{b}' are {r:.0%} similar as NAMES - "
                                   "rename one to disambiguate",
                                   f"{a} | {b}", None, {"similarity": round(r, 3)}))
    return out


# --------------------------------------------------------------------------
# hermes adapter (isolated runtime coupling)
# --------------------------------------------------------------------------


class HermesAdapter:
    def __init__(self, profile: Path):
        self.profile = profile
        self.available = (profile / "config.yaml").is_file()

    def disabled(self) -> tuple[set, str | None]:
        try:
            import yaml  # type: ignore
        except ImportError:
            return set(), "PyYAML not installed"
        try:
            cfg = yaml.safe_load((self.profile / "config.yaml").read_text()) or {}
        except Exception as exc:
            return set(), f"config unreadable: {exc}"
        raw = (cfg.get("skills") or {}).get("disabled") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [x.strip() for x in raw.split(",") if x.strip()]
        return set(raw), None

    def installable_names(self) -> set:
        """Every tree the runtime could install from.

        A name in skills.disabled that is absent from the PROFILE may still be a
        deliberate deny rule for a bundled or optional skill. Verified on a real
        agent: 4 of 4 suspected "dead" entries lived in optional-skills/.
        """
        agent = Path.home() / ".hermes/hermes-agent"
        names: set = set()
        for tree in (agent / "skills", agent / "optional-skills"):
            if tree.is_dir():
                names |= {p.parent.name for p in tree.rglob("SKILL.md")}
        return names

    def live_index(self) -> tuple[set, str | None]:
        """Ask the runtime what it ACTUALLY loaded. Never infer from disk."""
        agent = Path.home() / ".hermes/hermes-agent"
        py = agent / "venv/bin/python"
        if not py.is_file():
            return set(), "hermes venv not found"
        code = (
            "import os,sys;"
            "sys.path.insert(0,os.path.expanduser('~/.hermes/hermes-agent'));"
            "from agent.skill_commands import get_skill_commands;"
            "print('\\n'.join(k.lstrip('/') for k in get_skill_commands()))"
        )
        try:
            r = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                               timeout=180,
                               env=dict(os.environ, HERMES_HOME=str(self.profile)))
        except Exception as exc:
            return set(), f"live index probe failed: {exc}"
        if r.returncode != 0:
            return set(), f"live index probe exit {r.returncode}: {r.stderr[:200]}"
        return set(r.stdout.split()), None

    def provenance(self) -> tuple[dict, str | None]:
        """Who owns each skill -> who may edit it."""
        try:
            r = subprocess.run(["hermes", "curator", "usage", "--json"],
                               capture_output=True, text=True, timeout=240,
                               env=dict(os.environ, HERMES_HOME=str(self.profile)))
            if r.returncode != 0:
                return {}, f"curator usage exit {r.returncode}"
            rows = json.loads(r.stdout)
            rows = rows if isinstance(rows, list) else rows.get("skills", [])
            return {x["name"]: {"provenance": x.get("provenance"),
                                "state": x.get("state"),
                                "use_count": x.get("use_count", 0),
                                "pinned": x.get("pinned", False)} for x in rows}, None
        except Exception as exc:
            return {}, f"curator unavailable: {exc}"


def check_runtime(skills: list[Skill], ad: HermesAdapter) -> tuple[list[Finding], list[str]]:
    findings, skipped = [], []
    # Only PROFILE skills are expected to load. Bundled skills ship with the
    # runtime and are opt-in -- their absence from the index is normal, not a
    # bug. Conflating the two produced 18 false positives on a real agent.
    profile_skills = [s for s in skills if s.root == "profile" and not s.archived]
    on_disk = {s.name for s in profile_skills}
    all_on_disk = {s.name for s in skills if not s.archived}

    this_os = {"darwin": "macos", "linux": "linux", "win32": "windows"}.get(
        sys.platform, sys.platform)

    disabled, err = ad.disabled()
    if err:
        skipped.append(f"disabled-set: {err}")
    else:
        # A disabled name absent from the profile is NOT automatically dead: it
        # may be a deliberate deny rule for a bundled/optional skill. Removing
        # it would silently re-enable that skill on the next upgrade.
        unmatched = sorted(disabled - all_on_disk - ad.installable_names())
        deny_rules = sorted((disabled - all_on_disk) & ad.installable_names())
        if deny_rules:
            findings.append(Finding(
                "config.deny_rule", "info",
                f"{len(deny_rules)} disabled entries name skills that exist in the "
                "bundled/optional trees - these are intentional deny rules, PRESERVE "
                "them", None, None, {"names": deny_rules}))
        if unmatched:
            findings.append(Finding(
                "config.disabled_entry_unmatched", "warn",
                f"{len(unmatched)} disabled entries match nothing in any installable "
                "tree - intentional reservation or rename debris? preserve by default",
                None, None, {"names": unmatched}))

    live, err = ad.live_index()
    if err:
        skipped.append(f"live-index: {err}")
    else:
        # a skill declaring platforms that exclude this OS is filtered by design
        wrong_platform = {s.name for s in profile_skills
                          if s.platforms and this_os not in s.platforms}
        # `environments:` gates a skill to a runtime context (e.g. kanban).
        # Verified on a real agent: 3 "missing" skills were kanban-gated and
        # correctly filtered. Fourth false-positive class for this check.
        env_gated = {s.name for s in profile_skills if s.environments}
        expected = on_disk - disabled - wrong_platform - env_gated
        missing = sorted(expected - live)
        if missing:
            findings.append(Finding(
                "index.enabled_but_absent", "error",
                f"{len(missing)} profile skills are on disk, not disabled, and valid for "
                f"this platform ({this_os}) yet MISSING from the live index - likely "
                "silent name collision", None, None, {"names": missing}))
        if env_gated:
            findings.append(Finding(
                "index.environment_gated", "info",
                f"{len(env_gated)} skills gated by `environments:` and absent unless "
                "that runtime context is active - expected", None, None,
                {"names": sorted(env_gated)}))
        if wrong_platform:
            findings.append(Finding(
                "index.platform_filtered", "info",
                f"{len(wrong_platform)} skills excluded by platform on {this_os} - "
                "expected", None, None, {"names": sorted(wrong_platform)}))
        leaked = sorted(n for n in (live & disabled))
        if leaked:
            findings.append(Finding(
                "index.disabled_but_live", "error",
                f"{len(leaked)} skills are disabled yet STILL in the live index",
                None, None, {"names": leaked}))

    prov, err = ad.provenance()
    if err:
        skipped.append(f"provenance: {err}")
    else:
        findings.append(Finding(
            "provenance.map", "info",
            "provenance resolved - decides which skills this agent may edit in place",
            None, None,
            {"counts": {p: sum(1 for v in prov.values() if v["provenance"] == p)
                        for p in {v["provenance"] for v in prov.values()}}}))
    return findings, skipped


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="skill-librarian evidence collector")
    ap.add_argument("--profile", help="agent profile dir (e.g. ~/.hermes/profiles/<agent>)")
    ap.add_argument("--skills-dir", action="append", default=[],
                    help="extra SKILL.md tree to scan (repeatable, runtime-agnostic)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--desc-threshold", type=float, default=0.80)
    args = ap.parse_args()

    roots: list[tuple[str, Path]] = []
    adapter = None
    if args.profile:
        p = Path(os.path.expanduser(args.profile))
        roots.append(("profile", p / "skills"))
        adapter = HermesAdapter(p)
        agent = Path.home() / ".hermes/hermes-agent"
        if (agent / "skills").is_dir():
            roots.append(("bundled", agent / "skills"))
    for d in args.skills_dir:
        roots.append(("extra", Path(os.path.expanduser(d))))
    if not roots:
        ap.error("need --profile or --skills-dir")

    skills = collect(roots)
    findings: list[Finding] = []
    findings += check_mechanical(skills)
    findings += check_related(skills)
    findings += check_collisions(skills)
    findings += check_desc_similarity(skills, args.desc_threshold)
    findings += check_name_near_collisions(skills)

    skipped: list[str] = []
    if adapter and adapter.available:
        rf, sk = check_runtime(skills, adapter)
        findings += rf
        skipped += sk
    else:
        skipped.append("runtime checks: not a Hermes profile")

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]

    if args.json:
        print(json.dumps({
            "summary": {"skills_scanned": len(skills),
                        "live": sum(1 for s in skills if not s.archived),
                        "archived": sum(1 for s in skills if s.archived),
                        "errors": len(errors), "warnings": len(warns),
                        "skipped_checks": skipped},
            "skills": [asdict(s) for s in skills],
            "findings": [asdict(f) for f in findings],
        }, indent=1))
    else:
        print(f"skill-librarian — {len(skills)} SKILL.md scanned "
              f"({sum(1 for s in skills if s.archived)} archived)")
        print(f"errors={len(errors)}  warnings={len(warns)}")
        if skipped:
            print("\ndegraded: these checks could not run")
            for s in skipped:
                print(f"   - {s}")
        for sev, group in (("ERROR", errors), ("WARN", warns)):
            if not group:
                continue
            print(f"\n{sev} ({len(group)})")
            seen: dict[str, int] = {}
            for f in group:
                seen[f.check] = seen.get(f.check, 0) + 1
            for chk, n in sorted(seen.items(), key=lambda x: -x[1]):
                print(f"   {chk:44} {n}")
        print("\nThis script collects facts only. Apply judgement per README.md.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
