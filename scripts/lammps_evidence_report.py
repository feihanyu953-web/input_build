#!/usr/bin/env python3
"""Deterministic construction and serialization of LAMMPS evidence reports."""

from __future__ import annotations

import json
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import TypedDict, assert_never


def _load_models_api() -> None:
    global LEVEL_ORDER, LEVEL_TITLES, HighestLevel, LevelEvidence
    global LevelName, LevelStatus, UnresolvedItem, ValidationReport
    global highest_contiguous_pass

    name = "lammps_evidence_models"
    if name not in sys.modules:
        path = Path(__file__).with_name(f"{name}.py")
        module_spec = importlib.util.spec_from_file_location(name, path)
        if module_spec is None or module_spec.loader is None:
            msg = f"unable to load evidence models module: {path}"
            raise ImportError(msg)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = module
        loaded = False
        try:
            module_spec.loader.exec_module(module)
            loaded = True
        finally:
            if not loaded:
                sys.modules.pop(name, None)

    from lammps_evidence_models import (
        LEVEL_ORDER,
        LEVEL_TITLES,
        HighestLevel,
        LevelEvidence,
        LevelName,
        LevelStatus,
        UnresolvedItem,
        ValidationReport,
        highest_contiguous_pass,
    )


_load_models_api()


class FindingPayload(TypedDict):
    level: str
    code: str
    message: str


class LevelPayload(TypedDict):
    name: str
    status: str
    evidence: list[str]
    missing: list[str]
    warnings: list[str]
    findings: list[FindingPayload]


class _UnresolvedPayload(TypedDict):
    key: str
    blocks_level: str
    reason: str


class _ReportPayload(TypedDict):
    schema_version: int
    code: str
    target_level: str
    target_satisfied: bool
    highest_level: str
    spec_file: str
    manifest_file: str
    levels: dict[str, LevelPayload]
    unresolved: list[_UnresolvedPayload]


def build_phase_a_report(
    spec_file: str,
    l0: LevelEvidence,
    l1: LevelEvidence,
    unresolved: tuple[UnresolvedItem, ...],
) -> ValidationReport:
    """Build a complete L0-L5 report whose command target is L1."""
    levels = {
        LevelName.L0: l0,
        LevelName.L1: l1,
        LevelName.L2: LevelEvidence(LevelName.L2, LevelStatus.NOT_EVALUATED),
        LevelName.L3: LevelEvidence(LevelName.L3, LevelStatus.NOT_EVALUATED),
        LevelName.L4: LevelEvidence(LevelName.L4, LevelStatus.NOT_EVALUATED),
        LevelName.L5: LevelEvidence(LevelName.L5, LevelStatus.NOT_EVALUATED),
    }
    for item in unresolved:
        match item.blocks_level:
            case LevelName.L0 | LevelName.L1:
                continue
            case LevelName.L2 | LevelName.L3 | LevelName.L4 | LevelName.L5:
                current = levels[item.blocks_level]
                levels[item.blocks_level] = replace(
                    current,
                    status=LevelStatus.INCOMPLETE,
                    missing=current.missing + (item.key,),
                )
            case unreachable:
                assert_never(unreachable)
    ordered = tuple(levels[level] for level in LEVEL_ORDER)
    statuses = {item.level: item.status for item in ordered}
    return ValidationReport(
        spec_file=spec_file,
        manifest_file="generation_manifest.json",
        target_level=HighestLevel.L1_STATIC_PASS,
        target_satisfied=(
            l0.status is LevelStatus.PASS and l1.status is LevelStatus.PASS
        ),
        highest_level=highest_contiguous_pass(statuses),
        levels=ordered,
        unresolved=unresolved,
    )


def _level_payload(item: LevelEvidence) -> LevelPayload:
    return {
        "name": LEVEL_TITLES[item.level],
        "status": item.status.value,
        "evidence": list(item.evidence),
        "missing": list(item.missing),
        "warnings": list(item.warnings),
        "findings": [
            {
                "level": finding.level,
                "code": finding.code,
                "message": finding.message,
            }
            for finding in item.findings
        ],
    }


def report_json(report: ValidationReport) -> str:
    """Return canonical pretty JSON with one trailing newline."""
    payload = _ReportPayload(
        schema_version=1,
        code="lammps",
        target_level=report.target_level.value,
        target_satisfied=report.target_satisfied,
        highest_level=report.highest_level.value,
        spec_file=report.spec_file,
        manifest_file=report.manifest_file,
        levels={item.level.value: _level_payload(item) for item in report.levels},
        unresolved=[
            {
                "key": item.key,
                "blocks_level": item.blocks_level.value,
                "reason": item.reason,
            }
            for item in report.unresolved
        ],
    )
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _escape_markdown(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "<br>").replace("\\", "\\\\").replace("|", "\\|")


def _markdown_cell(values: tuple[str, ...]) -> str:
    return ", ".join(_escape_markdown(value) for value in values) or "-"


def report_markdown(report: ValidationReport) -> str:
    """Return a deterministic human-readable summary with one trailing newline."""
    lines = [
        "# LAMMPS Validation Evidence",
        "",
        f"Highest level: `{report.highest_level.value}`",
        f"Target level: `{report.target_level.value}`",
        f"Target satisfied: `{str(report.target_satisfied).lower()}`",
        "",
        "| Level | Name | Status | Evidence | Missing |",
        "|---|---|---|---|---|",
    ]
    for item in report.levels:
        lines.append(
            f"| {item.level.value} | {LEVEL_TITLES[item.level]} | "
            f"{item.status.value} | {_markdown_cell(item.evidence)} | "
            f"{_markdown_cell(item.missing)} |"
        )
    if report.unresolved:
        lines.extend(
            [
                "",
                "## Unresolved",
                "",
                "| Key | Blocks level | Reason |",
                "|---|---|---|",
            ]
        )
        for item in report.unresolved:
            lines.append(
                f"| {_escape_markdown(item.key)} | {item.blocks_level.value} | "
                f"{_escape_markdown(item.reason)} |"
            )
    return "\n".join(lines) + "\n"
