#!/usr/bin/env python3
"""Shared fixtures and helpers for the LAMMPS examples index tests."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "lammps_examples_index.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "lammps_official_source" / "examples"
BUILDER = ROOT / "scripts" / "build_lammps_examples_index.py"

REPOSITORY = "https://github.com/lammps/lammps"
COMMIT = "abc123def456789012345678901234567890abcd"
RETRIEVAL_DATE = "2026-08-09"


def run_build(tmp: Path, skill_root: Path | None = None, extra: tuple[str, ...] = ()):
    """Run the builder over the fixture tree; return the CompletedProcess."""
    output = tmp / "index.json"
    args = [
        sys.executable, str(BUILDER), "build",
        "--source-root", str(FIXTURE),
        "--repository", REPOSITORY,
        "--commit", COMMIT,
        "--retrieval-date", RETRIEVAL_DATE,
        "--skill-root", str(skill_root or ROOT),
        "--output", str(output),
    ] + list(extra)
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
