#!/usr/bin/env python3
"""Sync the input_build skill from a local checkout into this release repo.

This repository is the publishable form of the ``input_build`` skill. The
development copy lives elsewhere (typically a private workspace); this script
copies it in, skipping machine-specific artifacts, then runs a leak gate over
the whole repository so nothing private can ship.

Usage
-----
    # sync from your local skill checkout, then run the leak gate
    python tools/make_release.py --src /path/to/input_build

    # only run the leak gate over the current repository state
    python tools/make_release.py --check-only

Exit code 0 means the tree is clean; 1 means leaks or missing required files.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- what never leaves the development checkout ------------------------------
EXCLUDE_DIR_NAMES = {"__pycache__"}
EXCLUDE_FILE_GLOBS = ("*.pyc",)
# Excluded relative paths (posix style): historical run artifacts carry
# machine-local paths, and the real smoke_env.yaml is the maintainer's own
# environment config — users generate theirs from smoke_env.example.yaml.
EXCLUDE_RELPATHS = {
    "scripts/smoke/runs",
    "scripts/smoke/smoke_env.yaml",
}

# Files that live only in the release repo and are never overwritten by sync.
RELEASE_ONLY = {
    "README.md",
    "LICENSE",
    ".gitignore",
    "tools/make_release.py",
    "scripts/smoke/smoke_env.example.yaml",
}

# Files that must exist for the release to be considered complete.
REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "LICENSE",
    ".gitignore",
    "base_templates/INDEX.json",
    "scripts/validate_input.py",
    "scripts/smoke/run_smoke.py",
    "scripts/smoke/smoke_env.example.yaml",
)

# --- leak gate ----------------------------------------------------------------
# Any case-insensitive substring hit fails the release. The tools/ directory is
# excluded from the content scan because this script's own pattern list
# necessarily contains the strings.
LEAK_PATTERNS = (
    "yufeihan",          # personal username
    "hpc-169",           # private cluster alias
    "env-compute.sh",    # personal environment script
    "computer_kb",       # private knowledge base
    "codex",             # private workspace root (covers e:\codex, /mnt/e/codex)
    "c:\\users",         # windows user dirs
    "c:/users",
    "/home/",            # unix home paths
)


def iter_source_files(src: Path):
    """Yield (abs_path, rel_posix) for every file that should be released."""
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        kept = []
        for d in dirs:
            rel_dir = (rel_root / d).as_posix()
            if d in EXCLUDE_DIR_NAMES or rel_dir in EXCLUDE_RELPATHS:
                continue
            kept.append(d)
        dirs[:] = kept
        for name in sorted(files):
            rel = (rel_root / name).as_posix()
            if any(fnmatch.fnmatch(name, g) for g in EXCLUDE_FILE_GLOBS):
                continue
            if rel in EXCLUDE_RELPATHS:
                continue
            yield Path(root) / name, rel


def sync(src: Path) -> int:
    if not (src / "SKILL.md").is_file():
        print(f"ERROR: --src does not look like the input_build skill dir: {src}", file=sys.stderr)
        return 1
    copied = 0
    for abs_path, rel in iter_source_files(src):
        dst = REPO_ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(abs_path, dst)
        copied += 1
    print(f"synced {copied} file(s) from {src}")

    # Report destination-only files: expected release-only files vs stale leftovers.
    dest_files = {
        p.relative_to(REPO_ROOT).as_posix()
        for p in REPO_ROOT.rglob("*")
        if p.is_file() and not ({"tools", ".git"} & set(p.relative_to(REPO_ROOT).parts))
    }
    stale = sorted(dest_files - set(RELEASE_ONLY) - {rel for _, rel in iter_source_files(src)})
    if stale:
        print("WARNING: files present in the release repo but not in the source tree")
        for rel in stale:
            print(f"  stale: {rel}")
    return 0


def leak_gate() -> int:
    problems: list[str] = []

    for rel in REQUIRED_FILES:
        if not (REPO_ROOT / rel).is_file():
            problems.append(f"missing required file: {rel}")

    for rel in EXCLUDE_RELPATHS:
        if (REPO_ROOT / rel).exists():
            problems.append(f"excluded path present in release: {rel}")

    for cache in sorted(REPO_ROOT.rglob("__pycache__")):
        if ".git" not in cache.parts:
            problems.append(f"excluded dir present in release: {cache.relative_to(REPO_ROOT).as_posix()}")
    for pyc in sorted(REPO_ROOT.rglob("*.pyc")):
        problems.append(f"excluded file present in release: {pyc.relative_to(REPO_ROOT).as_posix()}")

    hits: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(REPO_ROOT).parts)
        if rel_parts & {".git", "tools"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            problems.append(f"unreadable file: {path.relative_to(REPO_ROOT).as_posix()} ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            for pat in LEAK_PATTERNS:
                if pat in low:
                    hits.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: "
                        f"[{pat}] {line.strip()[:120]}"
                    )
    if hits:
        print(f"\nLEAK GATE: {len(hits)} hit(s)")
        for h in hits[:80]:
            print(f"  {h}")
        if len(hits) > 80:
            print(f"  ... and {len(hits) - 80} more")
        return 1

    print("LEAK GATE: clean "
          f"({len(LEAK_PATTERNS)} patterns x all tracked text files; tools/ excluded)")
    if problems:
        print(f"\nSTRUCTURAL PROBLEMS: {len(problems)}")
        for p in problems:
            print(f"  {p}")
        return 1
    print("STRUCTURE: all required files present, no excluded artifacts")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=None,
                    help="path to the development copy of the input_build skill")
    ap.add_argument("--check-only", action="store_true",
                    help="skip syncing; only run the leak gate on this repository")
    args = ap.parse_args(argv)

    if args.check_only:
        return leak_gate()
    if args.src is None:
        ap.error("--src is required unless --check-only is given")
    rc = sync(args.src.resolve())
    if rc != 0:
        return rc
    return leak_gate()


if __name__ == "__main__":
    sys.exit(main())
