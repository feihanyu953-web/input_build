#!/usr/bin/env python3
"""Semantic validator for the LAMMPS official examples index.

Sibling module of ``build_lammps_examples_index.py`` (kept separate so the
builder stays under the 250 pure-LOC ceiling). ``validate_index`` applies the
closed rejection rules from the Phase B contract and returns deterministic
``IndexIssue`` records sorted by (path, code).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


ALLOWED_REPOSITORIES: Final[frozenset[str]] = frozenset({
    "https://github.com/lammps/lammps",
})


@dataclass(frozen=True, slots=True)
class IndexIssue:
    path: str
    code: str
    message: str


def validate_index(index, skill_root):
    issues = []

    def add(path, code, message=""):
        issues.append(IndexIssue(path, code, message))

    gf = index.get("generated_from") if isinstance(index, dict) else None
    if not isinstance(gf, dict):
        add("$.generated_from", "INDEX_REQUIRED_FIELD")
        gf = {}
    commit = gf.get("commit")
    release = gf.get("release")
    if bool(commit) == bool(release):
        add("$.generated_from", "INDEX_UNPINNED",
            "exactly one of commit/release must be non-empty")
    repo = gf.get("repository")
    if repo not in ALLOWED_REPOSITORIES:
        add("$.generated_from.repository", "INDEX_REPO_UNSUPPORTED", repr(repo))
    gf_pin = commit or release

    entries = index.get("entries", []) if isinstance(index, dict) else []
    if not isinstance(entries, list):
        add("$.entries", "INDEX_VALUE_INVALID", "entries must be an array")
        entries = []

    seen = set()
    prev_id = None
    for i, entry in enumerate(entries):
        base = f"$.entries[{i}]"
        if not isinstance(entry, dict):
            add(base, "INDEX_VALUE_INVALID", "entry must be an object")
            continue
        eid = entry.get("id")
        if not isinstance(eid, str) or not re.match(r"^lammps_examples_[a-z0-9_]+$", eid):
            add(f"{base}.id", "INDEX_ID_MALFORMED", repr(eid))
            eid = f"!malformed:{i}"
        if eid in seen:
            add(f"{base}.id", "INDEX_DUPLICATE_ID", eid)
        seen.add(eid)
        if prev_id is not None and eid < prev_id:
            add(f"{base}.id", "INDEX_NOT_SORTED", f"{eid} < {prev_id}")
        prev_id = eid

        e_commit = entry.get("upstream_commit")
        e_release = entry.get("upstream_release")
        if bool(e_commit) == bool(e_release):
            add(base, "INDEX_ENTRY_UNPINNED", "exactly one of commit/release required")
        e_pin = e_commit or e_release
        if gf_pin and e_pin and e_pin != gf_pin:
            add(base, "INDEX_ENTRY_PIN_MISMATCH", f"{e_pin!r} != {gf_pin!r}")
        if entry.get("upstream_repository") != repo:
            add(f"{base}.upstream_repository", "INDEX_REPO_MISMATCH", "")

        up = entry.get("upstream_path", "")
        if not isinstance(up, str) or ".." in up.split("/") or up != up.lstrip("/"):
            add(f"{base}.upstream_path", "INDEX_PATH_TRAVERSAL", repr(up))

        if repo and e_pin and isinstance(up, str) and up:
            expected_url = f"{repo}/blob/{e_pin}/{up}"
            if entry.get("canonical_source_url") != expected_url:
                add(f"{base}.canonical_source_url", "INDEX_URL_MALFORMED",
                    f"expected {expected_url!r}")

        sha = entry.get("sha256", "")
        if not re.match(r"^sha256:[0-9a-f]{64}$", str(sha)):
            add(f"{base}.sha256", "INDEX_HASH_MALFORMED", repr(sha))

        for field in ("commands", "packages", "tags"):
            vals = entry.get(field, [])
            if vals != sorted(set(vals)):
                add(f"{base}.{field}", "INDEX_LIST_NOT_SORTED", repr(vals))

        st = entry.get("styles", {})
        if not isinstance(st, dict):
            add(f"{base}.styles", "INDEX_STYLES_MALFORMED", "not an object")
        else:
            if list(st.keys()) != sorted(st.keys()):
                add(f"{base}.styles", "INDEX_STYLES_MALFORMED", "keys not sorted")
            for k, v in st.items():
                if v != sorted(set(v)):
                    add(f"{base}.styles.{k}", "INDEX_STYLES_MALFORMED", repr(v))

        local = entry.get("local_example")
        if local is not None:
            resolved = (skill_root / local).resolve()
            ok = (resolved.is_relative_to((skill_root / "examples").resolve())
                  and resolved.is_dir())
            if not ok:
                add(f"{base}.local_example", "INDEX_LOCAL_EXAMPLE_INVALID", repr(local))

    return tuple(sorted(issues, key=lambda x: (x.path, x.code)))
