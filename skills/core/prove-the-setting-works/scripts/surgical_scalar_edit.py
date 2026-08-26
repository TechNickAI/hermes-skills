#!/usr/bin/env python3
"""Surgical single-scalar YAML edit for fleet config.yaml files.

Backs up, edits one leaf under one parent mapping (e.g. ``agent.max_turns``),
guards ruamel against sequence-indent reflow and folded-scalar unfolding via a
diff-gate, and falls back to a text-surgical line replacement when ruamel would
churn the file. Verifies the value landed by re-parsing. Idempotent and
restore-on-failure.

Exit codes: 0 ok (changed or already-target), 2 missing, 3 parse error,
4 bad shape / unsupported key, 5 backup exists, 6 write/verify failed (restored).

Usage:
    python surgical_scalar_edit.py --path /path/config.yaml \
        --key agent.max_turns --value 500 --label the operations agent
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def loader() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.allow_duplicate_keys = False
    return y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--key", required=True, help="dotted leaf under one parent, e.g. agent.max_turns")
    ap.add_argument("--value", required=True)
    ap.add_argument("--timestamp", default="")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    parts = a.key.split(".")
    if len(parts) != 2:
        print(json.dumps({"ok": False, "error": "only parent.leaf supported"}))
        return 4
    parent_key, leaf = parts
    new_val = int(a.value) if re.fullmatch(r"[+-]?\d+", a.value) else a.value

    path = Path(a.path).expanduser()
    rec = {"label": a.label or path.parent.name or "root", "path": str(path),
           "key": a.key, "target": new_val}
    if not path.is_file():
        rec.update(ok=False, error="config missing")
        print(json.dumps(rec, sort_keys=True))
        return 2

    y = loader()
    try:
        with path.open("r", encoding="utf-8") as f:
            doc = y.load(f) or {}
    except DuplicateKeyError as e:
        rec.update(ok=False, error_type="DuplicateKeyError", error=str(e))
        print(json.dumps(rec, sort_keys=True))
        return 3
    except Exception as e:
        rec.update(ok=False, error_type=type(e).__name__, error=str(e))
        print(json.dumps(rec, sort_keys=True))
        return 3

    if not isinstance(doc, dict) or parent_key not in doc or not isinstance(doc[parent_key], dict):
        rec.update(ok=False, error=f"parent '{parent_key}' missing or not a mapping")
        print(json.dumps(rec, sort_keys=True))
        return 4
    parent = doc[parent_key]
    present = leaf in parent
    before = parent.get(leaf) if present else None
    rec["before"] = before
    rec["before_present"] = present
    if before == new_val:
        rec.update(ok=True, classification="already target", after=new_val, backup=None, changed=False)
        print(json.dumps(rec, sort_keys=True))
        return 0

    stamp = a.timestamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    if backup.exists():
        rec.update(ok=False, error=f"backup exists: {backup}")
        print(json.dumps(rec, sort_keys=True))
        return 5
    shutil.copy2(path, backup)
    rec["backup"] = str(backup)
    source_text = backup.read_text(encoding="utf-8")
    before_hash = sha256(path)

    try:
        y2 = loader()
        if any(line.startswith("  - ") for line in source_text.splitlines()):
            y2.indent(mapping=2, sequence=4, offset=2)
        else:
            y2.indent(mapping=2, sequence=2, offset=0)
        y2.fold_pos = 4096
        parent[leaf] = new_val
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        with tmp.open("w", encoding="utf-8") as f:
            y2.dump(doc, f)
        os.chmod(tmp, path.stat().st_mode)

        # Diff-gate: a single-scalar change must be exactly one - / one + line.
        old_lines = source_text.splitlines(keepends=True)
        new_lines = tmp.read_text(encoding="utf-8").splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=str(backup), tofile=str(path)))
        removed = [l for l in diff if l.startswith("-") and not l.startswith("---")]
        added = [l for l in diff if l.startswith("+") and not l.startswith("+++")]
        if present:
            valid = len(removed) == 1 and len(added) == 1 and leaf in removed[0] and leaf in added[0]
        else:
            valid = len(removed) == 0 and len(added) == 1 and leaf in added[0]
        if not valid:
            # Fall back to text-surgical on the ORIGINAL source.
            tmp.unlink(missing_ok=True)
            lines = source_text.splitlines(keepends=True)
            pidx = None
            matches = []
            for i, line in enumerate(lines):
                if re.match(rf"^{re.escape(parent_key)}:\s*(?:#.*)?(?:\r?\n)?$", line):
                    pidx = i
                    continue
                if pidx is not None and re.match(r"^[^ \t#][^:]*:", line):
                    pidx = None
                if pidx is not None and re.match(rf"^  {re.escape(leaf)}:\s*", line):
                    matches.append(i)
            if len(matches) != 1:
                raise RuntimeError(f"expected exactly one {parent_key}.{leaf} scalar; found {len(matches)}")
            idx = matches[0]
            eol = "\r\n" if lines[idx].endswith("\r\n") else "\n" if lines[idx].endswith("\n") else ""
            body = lines[idx].rstrip("\r\n")
            comment = body[body.index(" #"):] if " #" in body else ""
            lines[idx] = f"  {leaf}: {new_val}{comment}{eol}"
            tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
            tmp.write_text("".join(lines), encoding="utf-8")
            os.chmod(tmp, path.stat().st_mode)

        # Final parse/readback from the candidate.
        vfy = loader()
        with tmp.open("r", encoding="utf-8") as f:
            parsed = vfy.load(f) or {}
        pg = parsed.get(parent_key)
        after = pg.get(leaf) if isinstance(pg, dict) else None
        if after != new_val:
            raise RuntimeError(f"readback mismatch: {after!r}")
        os.replace(tmp, path)
        rec.update(
            ok=True,
            changed=True,
            classification=(f"changed {before} -> {new_val}" if present else "key absent, added"),
            after=after,
            before_sha256=before_hash,
            after_sha256=sha256(path),
        )
        print(json.dumps(rec, sort_keys=True))
        return 0
    except Exception as e:
        try:
            if "tmp" in locals() and tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        try:
            shutil.copy2(backup, path)
            restored = sha256(path) == before_hash
        except Exception as re_:
            restored = False
            rec["restore_error"] = str(re_)
        rec.update(ok=False, error_type=type(e).__name__, error=str(e), restored=restored)
        print(json.dumps(rec, sort_keys=True))
        return 6


if __name__ == "__main__":
    sys.exit(main())
