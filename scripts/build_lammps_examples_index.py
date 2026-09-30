#!/usr/bin/env python3
"""Build and validate the LAMMPS official examples index.

A stdlib-only provenance scanner: reads ``in.*`` inputs from a user-supplied
local LAMMPS checkout, extracts commands/styles/packages/tags, hashes each
file, and writes a deterministic ``references/lammps_examples_index.json``.
The index records source-traceability metadata only; it never copies
parameters into templates, never selects force fields, never renders inputs,
never executes LAMMPS, and never raises an evidence level.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Final

from lammps_examples_index_validate import (
    ALLOWED_REPOSITORIES,
    validate_index,
)


# Token index (0-based) of the style argument for style-bearing commands.
# LAMMPS syntax is "<cmd> ID group-ID style ..." for fix/compute/dump, so the
# style sits at index 3; pair/bond/angle/dihedral/improper/kspace/atom_style
# take the style as the first argument (index 1).
STYLE_TOKEN_INDEX: Final[dict[str, int]] = {
    "pair_style": 1, "bond_style": 1, "angle_style": 1,
    "dihedral_style": 1, "improper_style": 1, "kspace_style": 1,
    "atom_style": 1,
    "fix": 3, "compute": 3, "dump": 3,
}

# Closed mapping: do not extend without checking
# https://docs.lammps.org/Packages.html against the pinned version.
# Unconfirmed mappings must be absent, never guessed.
STYLE_PACKAGE_MAP: Final[dict[str, str]] = {
    "mace": "ML-MACE",
    "electrode/conp": "ELECTRODE", "electrode/conq": "ELECTRODE",
    "electrode/thermo": "ELECTRODE",
    "pppm/electrode": "ELECTRODE", "ewald/electrode": "ELECTRODE",
    "plumed": "PLUMED", "reaxff": "REAXFF",
}

STYLE_TAG_MAP: Final[dict[str, str]] = {
    "mace": "mlff", "deepmd": "mlff", "pace": "mlff", "snap": "mlff",
    "pod": "mlff", "quip": "mlff", "rann": "mlff",
    "electrode/conp": "conp", "electrode/conq": "conp", "electrode/thermo": "conp",
    "pppm/electrode": "conp", "ewald/electrode": "conp",
    "plumed": "plumed", "reaxff": "reaxff", "shake": "rigid_water",
    "lj/cut": "lj", "eam": "eam", "eam/alloy": "eam", "eam/fs": "eam",
    "tersoff": "tersoff", "sw": "sw", "rebo": "rebo",
    "nve": "nve", "nvt": "nvt", "npt": "npt", "nph": "nph",
    "efield": "efield",
}

COMMAND_TAG_MAP: Final[dict[str, str]] = {
    "neb": "neb", "minimize": "minimize", "min_style": "minimize",
}


class BuildError(Exception):
    """Raised for builder-level failures (missing source, bad args, traversal).

    Not a dataclass: it must accept a free-form message string, which a
    frozen/slots dataclass with no fields cannot.
    """


def extract_commands_styles(text: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Return (commands, styles) from LAMMPS input text.

    commands: sorted unique lowercased command tokens.
    styles: command -> sorted unique lowercased style tokens.
    Continuation lines ending with '&' are joined; trailing '#' comments
    are stripped. This is a lightweight provenance scanner, not the Phase C
    parser; quoted '#' inside args is not handled.
    """
    commands: set[str] = set()
    styles: dict[str, set[str]] = {}
    logical: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if logical and logical[-1].endswith("&"):
            logical[-1] = logical[-1][:-1] + " " + line
        else:
            logical.append(line)
    for line in logical:
        if line.endswith("&"):
            line = line[:-1].strip()
            if not line:
                continue
        tokens = line.split()
        cmd = tokens[0].lower()
        commands.add(cmd)
        idx = STYLE_TOKEN_INDEX.get(cmd)
        if idx is not None and len(tokens) > idx:
            styles.setdefault(cmd, set()).add(tokens[idx].lower())
    return (
        tuple(sorted(commands)),
        {k: tuple(sorted(v)) for k, v in sorted(styles.items())},
    )


def derive_packages(styles: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    packages: set[str] = set()
    for style_list in styles.values():
        for style in style_list:
            pkg = STYLE_PACKAGE_MAP.get(style)
            if pkg:
                packages.add(pkg)
    return tuple(sorted(packages))


def derive_tags(
    relpath: str,
    commands: tuple[str, ...],
    styles: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    tags = {Path(relpath).parent.name.lower()}
    for cmd in commands:
        if cmd in COMMAND_TAG_MAP:
            tags.add(COMMAND_TAG_MAP[cmd])
    for style_list in styles.values():
        for style in style_list:
            if style in STYLE_TAG_MAP:
                tags.add(STYLE_TAG_MAP[style])
    return tuple(sorted(tags))


def derive_entry_id(relpath: str) -> str:
    return "lammps_examples_" + re.sub(
        r"[^a-z0-9]+", "_", relpath.lower()
    ).strip("_")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def walk_sources(source_root: Path):
    for path in sorted(source_root.rglob("in.*")):
        if path.is_file():
            yield path, path.relative_to(source_root).as_posix()


def build_entry(source_root, relpath, repository, commit, release,
                source_dir, retrieval_date, local_map, skill_root):
    file_path = (source_root / relpath).resolve()
    if not file_path.is_relative_to(source_root.resolve()):
        raise BuildError(f"path traversal: {relpath}")
    text = file_path.read_text(encoding="utf-8", errors="strict")
    commands, styles = extract_commands_styles(text)
    packages = derive_packages(styles)
    tags = derive_tags(relpath, commands, styles)
    upstream_path = f"{source_dir}/{relpath}"
    pin = commit if commit else release
    url = f"{repository}/blob/{pin}/{upstream_path}"
    entry_id = derive_entry_id(relpath)
    local = local_map.get(relpath)
    if local is not None:
        examples_root = (skill_root / "examples").resolve()
        resolved = (skill_root / local).resolve()
        if not resolved.is_relative_to(examples_root):
            raise BuildError(f"local_example outside examples/: {local}")
        if not resolved.is_dir():
            raise BuildError(f"local_example not found: {local}")
    return {
        "id": entry_id,
        "upstream_repository": repository,
        "upstream_commit": commit,
        "upstream_release": release,
        "upstream_path": upstream_path,
        "canonical_source_url": url,
        "retrieval_date": retrieval_date,
        "sha256": compute_sha256(file_path),
        "commands": list(commands),
        "styles": {k: list(v) for k, v in styles.items()},
        "packages": list(packages),
        "tags": list(tags),
        "local_example": local,
    }


def serialize(index: dict) -> str:
    return json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def cmd_build(args):
    source_root = Path(args.source_root).resolve()
    if not source_root.is_dir():
        raise BuildError(f"source root not found: {source_root}")
    if args.repository not in ALLOWED_REPOSITORIES:
        raise BuildError(f"unsupported repository: {args.repository}")
    if bool(args.commit) == bool(args.release):
        raise BuildError("exactly one of --commit/--release required")
    skill_root = Path(args.skill_root).resolve()
    local_map = {}
    if args.local_map:
        local_map = json.loads(Path(args.local_map).read_text(encoding="utf-8"))
    retrieval_date = args.retrieval_date or datetime.date.today().isoformat()
    entries = []
    for _path, rel in walk_sources(source_root):
        entries.append(build_entry(
            source_root, rel, args.repository, args.commit, args.release,
            args.source_dir, retrieval_date, local_map, skill_root,
        ))
    entries.sort(key=lambda e: e["id"])
    builder_path = Path(__file__).resolve()
    schema_path = builder_path.parent.parent / "schemas" / "lammps_examples_index.schema.json"
    index = {
        "schema_version": 1,
        "code": "lammps",
        "kind": "official_examples_index",
        "generated_from": {
            "repository": args.repository,
            "commit": args.commit or None,
            "release": args.release or None,
            "source_dir": args.source_dir,
            "retrieval_date": retrieval_date,
            "builder": "scripts/build_lammps_examples_index.py",
            "builder_sha256": compute_sha256(builder_path),
            "schema": "schemas/lammps_examples_index.schema.json",
            "schema_sha256": compute_sha256(schema_path),
        },
        "entries": entries,
    }
    issues = validate_index(index, skill_root)
    if issues:
        for issue in issues:
            print(f"{issue.code}: {issue.path}: {issue.message}", file=sys.stderr)
        return 1
    Path(args.output).write_text(serialize(index), encoding="utf-8", newline="\n")
    print(f"wrote {args.output} ({len(entries)} entries)")
    return 0


def cmd_check(args):
    skill_root = Path(args.skill_root).resolve()
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    issues = validate_index(index, skill_root)
    for issue in issues:
        print(f"{issue.code}: {issue.path}: {issue.message}", file=sys.stderr)
    return 0 if not issues else 1


def main():
    parser = argparse.ArgumentParser(
        description="LAMMPS official examples index builder"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    pb = sub.add_parser("build", help="scan a local checkout and write the index")
    pb.add_argument("--source-root", required=True)
    pb.add_argument("--repository", required=True)
    pin = pb.add_mutually_exclusive_group(required=True)
    pin.add_argument("--commit")
    pin.add_argument("--release")
    pb.add_argument("--source-dir", default="examples")
    pb.add_argument("--retrieval-date")
    pb.add_argument("--local-map")
    pb.add_argument("--skill-root", default=str(Path(__file__).resolve().parent.parent))
    pb.add_argument("--output", required=True)
    pc = sub.add_parser("check", help="validate a committed index offline")
    pc.add_argument("--index", required=True)
    pc.add_argument("--skill-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    try:
        if args.command == "build":
            return cmd_build(args)
        return cmd_check(args)
    except BuildError as exc:
        print(f"BUILD_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
