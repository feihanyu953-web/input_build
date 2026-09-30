#!/usr/bin/env python3
"""Phase A collector: orchestrate L0/L1 assessment and write evidence reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace as _replace
from pathlib import Path

import validate_input
from lammps_evidence import (
    FindingRecord,
    build_phase_a_report,
    report_json,
    report_markdown,
    static_level_from_validator,
)
from lammps_spec import assess_generation_spec

SCHEMA_REL = "schemas/lammps_generation_spec.schema.json"
SPEC_PARSER_REL = "scripts/lammps_spec.py"
EVIDENCE_MODEL_REL = "scripts/lammps_evidence.py"
COLLECTOR_REL = "scripts/collect_lammps_evidence.py"
STATIC_VALIDATOR_REL = "scripts/validate_input.py"
NOT_IMPLEMENTED = ["renderer", "task_profiles"]

TOOLS = [
    ("generation_schema", SCHEMA_REL),
    ("spec_parser", SPEC_PARSER_REL),
    ("evidence_model", EVIDENCE_MODEL_REL),
    ("collector", COLLECTOR_REL),
    ("static_validator", STATIC_VALIDATOR_REL),
]

SKILL_ROOT: Path = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _serialize(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _build_manifest(assessment: object) -> dict:
    """Extend assessment manifest with fixed tool hashes and not_implemented."""
    files = [
        {
            "role": entry.role,
            "path": entry.path,
            "exists": entry.exists,
            "sha256": entry.sha256,
            "expected_sha256": entry.expected_sha256,
            "matches_expected": entry.matches_expected,
        }
        for entry in assessment.manifest
    ]
    tools = [
        {"name": name, "path": rel, "sha256": _sha256(SKILL_ROOT / rel)}
        for name, rel in TOOLS
    ]
    return {
        "schema_version": 1,
        "files": files,
        "tools": tools,
        "not_implemented": NOT_IMPLEMENTED,
    }


def _static_validation_payload(
    spec: object | None,
    tiers: dict | None,
    findings: tuple[FindingRecord, ...],
) -> dict:
    """Return one of two exact static_validation.json structures."""
    if spec is None:
        return {
            "file": None,
            "status": "BLOCKED",
            "reason_code": "L0_NOT_PASS",
            "validation": None,
            "findings": [],
        }
    return {
        "file": spec.input_declared_path,
        "status": "EVALUATED",
        "validation": tiers,
        "findings": [
            {"level": f.level, "code": f.code, "message": f.message}
            for f in findings
        ],
    }


def _run(spec_path: Path, output_dir: Path) -> int:
    """Execute the fixed collection sequence and write four report artifacts."""
    assessment = assess_generation_spec(spec_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = _build_manifest(assessment)
    (output_dir / "generation_manifest.json").write_text(
        _serialize(manifest), encoding="utf-8", newline="\n"
    )

    if assessment.level.status.value == "PASS" and assessment.spec is not None:
        spec = assessment.spec
        raw_findings = validate_input.validate_lammps_one(
            str(spec.input_file),
            task=spec.task,
            data_path=str(spec.data_file),
        )
        tiers = validate_input.validation_tiers(raw_findings, incomplete=False)
        finding_records = tuple(
            FindingRecord(level=f.level, code=f.code, message=f.message)
            for f in raw_findings
        )
    else:
        spec = None
        tiers = None
        finding_records = ()

    static_validation = _static_validation_payload(spec, tiers, finding_records)
    (output_dir / "static_validation.json").write_text(
        _serialize(static_validation), encoding="utf-8", newline="\n"
    )

    unresolved = assessment.spec.unresolved if assessment.spec else ()
    l0_findings = tuple(
        FindingRecord(level="ERROR", code=issue.code, message=issue.message)
        for issue in assessment.issues
    )
    l0 = _replace(assessment.level, findings=l0_findings)
    l1 = static_level_from_validator(l0, tiers, finding_records, unresolved)
    report = build_phase_a_report(spec_path.name, l0, l1, unresolved)

    (output_dir / "validation_report.json").write_text(
        report_json(report), encoding="utf-8", newline="\n"
    )
    (output_dir / "validation_report.md").write_text(
        report_markdown(report), encoding="utf-8", newline="\n"
    )

    print(
        f"target_level={report.target_level.value} "
        f"target_satisfied={str(report.target_satisfied).lower()} "
        f"highest_level={report.highest_level.value} "
        f"report={output_dir / 'validation_report.json'}"
    )
    return 0 if report.target_satisfied else 1


def main() -> int:
    """Parse CLI arguments and run the collector."""
    parser = argparse.ArgumentParser(
        description="Collect LAMMPS Phase A evidence"
    )
    parser.add_argument("--spec", required=True, help="path to generation_spec.json")
    parser.add_argument(
        "--output-dir", default=None, help="output directory (default: <spec-parent>/validation)"
    )
    args = parser.parse_args()

    spec_path = Path(args.spec)
    output_dir = (
        Path(args.output_dir) if args.output_dir else spec_path.parent / "validation"
    )
    return _run(spec_path, output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
