#!/usr/bin/env python3
"""Stable public facade and L0 assessment for LAMMPS GenerationSpec JSON."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from typing import Final

from lammps_evidence import LevelEvidence, LevelName, LevelStatus


_PRIVATE_MODULES: Final = (
    "lammps_spec_models",
    "lammps_spec_fields",
    "lammps_spec_protocol",
    "lammps_spec_metadata",
    "lammps_spec_parser",
)


def _restore_module(name: str, previous: ModuleType | None) -> None:
    if previous is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


def _load_private_modules() -> None:
    scripts = Path(__file__).parent
    with ExitStack() as rollback:
        for name in _PRIVATE_MODULES:
            module_spec = importlib.util.spec_from_file_location(
                name, scripts / f"{name}.py"
            )
            assert module_spec is not None and module_spec.loader is not None
            previous = sys.modules.get(name)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[name] = module
            rollback.callback(_restore_module, name, previous)
            module_spec.loader.exec_module(module)
        rollback.pop_all()


def _load_public_api() -> None:
    global HASH_RE, MODIFIERS, SOURCES, ArtifactSpec, Ensemble, GenerationSpec
    global JsonValue, LammpsUnits, ManifestEntry, MdStage, MinimizeStage
    global ModifierSelection, ProtocolSpec, ProvenanceSpec, SpecAssessment, SpecIssue
    global ToolEntry, _Parser

    _load_private_modules()
    from lammps_spec_models import (
        HASH_RE,
        MODIFIERS,
        SOURCES,
        ArtifactSpec,
        Ensemble,
        GenerationSpec,
        JsonValue,
        LammpsUnits,
        ManifestEntry,
        MdStage,
        MinimizeStage,
        ModifierSelection,
        ProtocolSpec,
        ProvenanceSpec,
        SpecAssessment,
        SpecIssue,
        ToolEntry,
    )
    from lammps_spec_parser import _Parser


_load_public_api()

__all__ = [
    "ArtifactSpec",
    "Ensemble",
    "GenerationSpec",
    "HASH_RE",
    "JsonValue",
    "LammpsUnits",
    "ManifestEntry",
    "MdStage",
    "MinimizeStage",
    "MODIFIERS",
    "ModifierSelection",
    "ProtocolSpec",
    "ProvenanceSpec",
    "SpecAssessment",
    "SpecIssue",
    "SOURCES",
    "ToolEntry",
    "assess_generation_spec",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _manifest(
    role: str,
    declared: str,
    resolved: Path,
    expected: str | None,
) -> ManifestEntry:
    try:
        exists = resolved.is_file()
        actual = _sha256(resolved) if exists else None
    except OSError:
        exists = False
        actual = None
    matches_expected = (
        actual == expected if actual is not None and expected is not None else None
    )
    return ManifestEntry(
        role=role,
        path=declared,
        exists=exists,
        sha256=actual,
        expected_sha256=expected,
        matches_expected=matches_expected,
    )


def _invalid_constant(constant: str) -> int:
    return int(constant)


def _failed_assessment(
    path: Path,
    parser: _Parser,
    manifest: tuple[ManifestEntry, ...],
) -> SpecAssessment:
    issues = tuple(
        sorted(parser.issues, key=lambda item: (item.path, item.code, item.message))
    )
    level = LevelEvidence(
        level=LevelName.L0,
        status=LevelStatus.FAIL,
        evidence=(path.name, "generation_manifest.json"),
    )
    return SpecAssessment(spec=None, level=level, issues=issues, manifest=manifest)


def _file_evidence(
    manifest: list[ManifestEntry],
) -> tuple[list[SpecIssue], list[str]]:
    issues: list[SpecIssue] = []
    missing: list[str] = []
    for index, entry in enumerate(manifest[1:]):
        if index == 0:
            field = "input_file"
            missing_path = "$.input_file"
            hash_path = missing_path
        elif index == 1:
            field = "system.data_file"
            missing_path = "$.system.data_file"
            hash_path = "$.system.data_sha256"
        else:
            artifact_index = index - 2
            field = f"potential.artifacts[{artifact_index}].path"
            missing_path = f"$.potential.artifacts[{artifact_index}].path"
            hash_path = f"$.potential.artifacts[{artifact_index}].sha256"
        if not entry.exists:
            missing.append(field)
            issues.append(
                SpecIssue(
                    path=missing_path,
                    code="SPEC_FILE_MISSING",
                    message="declared file missing",
                )
            )
        elif entry.matches_expected is False:
            issues.append(
                SpecIssue(
                    path=hash_path,
                    code="SPEC_HASH_MISMATCH",
                    message="hash mismatch",
                )
            )
    return issues, missing


def assess_generation_spec(path: Path) -> SpecAssessment:
    """Parse one UTF-8 JSON spec and return deterministic L0 evidence."""
    parser = _Parser(path)
    try:
        raw: JsonValue = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as error:
        parser.issue("$", "SPEC_JSON_INVALID", str(error))
        raw = None
    spec = parser.parse(raw) if not parser.issues else None
    manifest = [_manifest("spec", path.name, path.resolve(), None)]
    if parser.issues or spec is None:
        return _failed_assessment(path, parser, tuple(manifest))

    manifest.extend(
        (
            _manifest("input", spec.input_declared_path, spec.input_file, None),
            _manifest(
                "data", spec.data_declared_path, spec.data_file, spec.data_sha256
            ),
        )
    )
    manifest.extend(
        _manifest(
            "potential_artifact",
            artifact.declared_path,
            artifact.resolved_path,
            artifact.expected_sha256,
        )
        for artifact in spec.artifacts
    )
    evidence_issues, missing = _file_evidence(manifest)
    if spec.provenance.potential not in {"user-provided", "user-confirmed"}:
        evidence_issues.append(
            SpecIssue(
                path="$.provenance.potential",
                code="SPEC_PROVENANCE_FORBIDDEN",
                message="potential provenance forbidden",
            )
        )
    for key in ("structure", "type_map", "protocol"):
        if getattr(spec.provenance, key) == "ai-inferred":
            evidence_issues.append(
                SpecIssue(
                    path=f"$.provenance.{key}",
                    code="SPEC_PROVENANCE_UNCONFIRMED",
                    message="provenance unconfirmed",
                )
            )
    for index, item in enumerate(spec.unresolved):
        if item.blocks_level == LevelName.L0:
            evidence_issues.append(
                SpecIssue(
                    path=f"$.unresolved[{index}]",
                    code="SPEC_UNRESOLVED_L0",
                    message="unresolved L0 item",
                )
            )
    fail_codes = {"SPEC_HASH_MISMATCH", "SPEC_PROVENANCE_FORBIDDEN"}
    if any(issue.code in fail_codes for issue in evidence_issues):
        status = LevelStatus.FAIL
    elif evidence_issues:
        status = LevelStatus.INCOMPLETE
    else:
        status = LevelStatus.PASS
    issues = tuple(
        sorted(evidence_issues, key=lambda item: (item.path, item.code, item.message))
    )
    level = LevelEvidence(
        level=LevelName.L0,
        status=status,
        evidence=(path.name, "generation_manifest.json"),
        missing=tuple(missing),
    )
    return SpecAssessment(
        spec=spec,
        level=level,
        issues=issues,
        manifest=tuple(manifest),
    )
