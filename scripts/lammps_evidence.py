#!/usr/bin/env python3
"""Stable public facade for LAMMPS generation evidence."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Final, assert_never


_SIBLING_MODULES: Final = (
    "lammps_evidence_models",
    "lammps_evidence_report",
)


def _restore_module(name: str, previous: ModuleType | None) -> None:
    if previous is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


def _load_public_api() -> None:
    global LEVEL_ORDER, LEVEL_TITLES, HIGHEST_BY_LEVEL
    global FindingRecord, HighestLevel, LevelEvidence, LevelName, LevelStatus
    global UnresolvedItem, ValidationReport, highest_contiguous_pass
    global build_phase_a_report, report_json, report_markdown

    previous = {name: sys.modules.get(name) for name in _SIBLING_MODULES}
    loaded = False
    try:
        for name in _SIBLING_MODULES:
            if name in sys.modules:
                continue
            path = Path(__file__).with_name(f"{name}.py")
            module_spec = importlib.util.spec_from_file_location(name, path)
            if module_spec is None or module_spec.loader is None:
                msg = f"unable to load evidence sibling module: {path}"
                raise ImportError(msg)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[name] = module
            module_spec.loader.exec_module(module)

        from lammps_evidence_models import (
            HIGHEST_BY_LEVEL,
            LEVEL_ORDER,
            LEVEL_TITLES,
            FindingRecord,
            HighestLevel,
            LevelEvidence,
            LevelName,
            LevelStatus,
            UnresolvedItem,
            ValidationReport,
            highest_contiguous_pass,
        )
        from lammps_evidence_report import (
            build_phase_a_report,
            report_json,
            report_markdown,
        )

        loaded = True
    finally:
        if not loaded:
            for name, module in previous.items():
                _restore_module(name, module)


_load_public_api()


def static_level_from_validator(
    l0: LevelEvidence,
    validation: Mapping[str, str] | None,
    findings: tuple[FindingRecord, ...],
    unresolved: tuple[UnresolvedItem, ...],
) -> LevelEvidence:
    match l0.status:
        case LevelStatus.PASS:
            pass
        case (
            LevelStatus.FAIL
            | LevelStatus.INCOMPLETE
            | LevelStatus.NOT_EVALUATED
            | LevelStatus.BLOCKED
        ):
            return LevelEvidence(level=LevelName.L1, status=LevelStatus.BLOCKED)
        case unreachable:
            assert_never(unreachable)

    missing = tuple(item.key for item in unresolved if item.blocks_level is LevelName.L1)
    mapped_findings = findings
    match None if validation is None else validation.get("overall"):
        case None | "FAIL":
            status = LevelStatus.FAIL
        case "INCOMPLETE":
            status = LevelStatus.INCOMPLETE
        case "STATIC_PASS":
            status = LevelStatus.INCOMPLETE if missing else LevelStatus.PASS
        case unknown_status:
            status = LevelStatus.FAIL
            mapped_findings += (
                FindingRecord(
                    level="ERROR",
                    code="STATIC_STATUS_UNKNOWN",
                    message=f"Unknown static validator overall status: {unknown_status}",
                ),
            )

    return LevelEvidence(
        level=LevelName.L1,
        status=status,
        evidence=("static_validation.json",),
        missing=missing,
        warnings=tuple(
            finding.code for finding in mapped_findings if finding.level == "WARN"
        ),
        findings=mapped_findings,
    )
