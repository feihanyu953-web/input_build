from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VALID_RENDER_TRACE: dict[str, Any] = {
    "schema_version": 1,
    "rendered_file": "in.lammps",
    "spec_file": "generation_spec.json",
    "template": "lammps_md",
    "modifiers_applied": [],
    "profiles_active": [],
    "commands": [
        {
            "index": 0,
            "command": "units",
            "args": ["metal"],
            "source_span": {"start_line": 1, "end_line": 1},
            "provenance": {
                "origin": "template",
                "name": "lammps_md",
                "section": "global",
            },
            "official_example_ref": None,
            "assigned_id": None,
            "id_type": None,
            "anchor": None,
            "ordering_rationale": "units must be the first command in any LAMMPS input",
            "profile_contribution": None,
        },
        {
            "index": 6,
            "command": "fix",
            "args": ["1", "all", "nve"],
            "source_span": {"start_line": 8, "end_line": 8},
            "provenance": {
                "origin": "template",
                "name": "lammps_md",
                "section": "integration",
            },
            "official_example_ref": None,
            "assigned_id": 1,
            "id_type": "fix",
            "anchor": "after_pair_definition",
            "ordering_rationale": "integrator fix must come after pair_style/pair_coeff and before run",
            "profile_contribution": None,
        },
    ],
    "id_allocations": [
        {
            "id_type": "fix",
            "id": 1,
            "command_index": 6,
            "rationale": "first force-adding fix, sequential allocation",
        },
    ],
    "anchor_decisions": [
        {
            "anchor": "after_pair_definition",
            "inserted_command_indices": [6],
            "rationale": "all force-adding fixes must be placed after pair definition and before SHAKE",
        },
    ],
    "conflict_checks": [
        {
            "check": "duplicate_integrator",
            "result": "pass",
            "details": None,
        },
    ],
}

VALID_EXAMPLES_INDEX: dict[str, Any] = {
    "schema_version": 1,
    "entries": [
        {
            "path": "examples/PACKAGES/rigid/in.rigid",
            "lammps_version": "22Jul2025",
            "commands": ["fix", "shake"],
            "styles": ["rigid"],
            "packages": ["RIGID"],
            "source_url": "https://github.com/lammps/lammps/blob/22Jul2025/examples/PACKAGES/rigid/in.rigid",
            "local_cache": "references/lammps_example_cache/PACKAGES/rigid/in.rigid",
            "provenance": {
                "repo_commit": "abc123def456",
                "download_date": "2026-08-09",
                "original_path": "examples/PACKAGES/rigid/in.rigid",
            },
        },
    ],
}

VALID_VALIDATION_REPORT: dict[str, Any] = {
    "schema_version": 1,
    "code": "lammps",
    "target_level": "L1_STATIC_PASS",
    "target_satisfied": True,
    "highest_level": "L1_STATIC_PASS",
    "spec_file": "generation_spec.json",
    "manifest_file": "generation_manifest.json",
    "levels": {
        "L0": {
            "name": "SPEC_COMPLETE",
            "status": "PASS",
            "evidence": ["generation_spec.json", "generation_manifest.json"],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
        "L1": {
            "name": "STATIC_PASS",
            "status": "PASS",
            "evidence": ["static_validation.json"],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
        "L2": {
            "name": "BUILD_COMPATIBLE",
            "status": "NOT_EVALUATED",
            "evidence": [],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
        "L3": {
            "name": "SMOKE_PASS",
            "status": "NOT_EVALUATED",
            "evidence": [],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
        "L4": {
            "name": "TASK_READY",
            "status": "NOT_EVALUATED",
            "evidence": [],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
        "L5": {
            "name": "PRODUCTION_EVIDENCE",
            "status": "NOT_EVALUATED",
            "evidence": [],
            "missing": [],
            "warnings": [],
            "findings": [],
        },
    },
    "unresolved": [],
}

VALID_STATIC_VALIDATION: dict[str, Any] = {
    "file": "in.lammps",
    "status": "EVALUATED",
    "validation": {
        "overall": "STATIC_PASS",
        "syntax": "PASS",
        "combination": "PASS",
        "physics": "NOT_EVALUATED",
    },
    "findings": [],
}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_explain_case(root: Path) -> dict[str, Path]:
    """Build a complete explain-mode fixture directory.

    Returns a dict mapping input names to their file paths:
    spec, input, render_trace, examples_index, validation_report, static_validation.
    """
    from lammps_evidence_support import write_complete_case

    spec_path = write_complete_case(root)
    input_path = root / "in.lammps"
    render_trace_path = root / "render_trace.json"
    examples_index_path = root / "lammps_examples_index.json"
    validation_report_path = root / "validation_report.json"
    static_validation_path = root / "static_validation.json"

    _write_json(render_trace_path, VALID_RENDER_TRACE)
    _write_json(examples_index_path, VALID_EXAMPLES_INDEX)
    _write_json(validation_report_path, VALID_VALIDATION_REPORT)
    _write_json(static_validation_path, VALID_STATIC_VALIDATION)

    return {
        "spec": spec_path,
        "input": input_path,
        "render_trace": render_trace_path,
        "examples_index": examples_index_path,
        "validation_report": validation_report_path,
        "static_validation": static_validation_path,
    }
