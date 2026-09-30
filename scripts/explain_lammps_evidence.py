"""Evidence-level summary join for the LAMMPS explain mode (Phase I)."""

from __future__ import annotations

from typing import Any

from explain_lammps_models import EvidenceSummary, LevelSummary

_LEVEL_ORDER: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4", "L5")

_STOP_REASON_BY_L0: dict[str, str] = {
    "FAIL": "L0 is FAIL; spec completeness checks found deterministic contradictions",
    "INCOMPLETE": "L0 is INCOMPLETE; required spec fields or declared files are missing",
    "NOT_EVALUATED": "L0 is NOT_EVALUATED; spec completeness was not assessed",
    "BLOCKED": "L0 is BLOCKED; a prerequisite blocked spec assessment",
}

_STOP_REASON_BY_L1: dict[str, str] = {
    "FAIL": "L1 is FAIL; static validation found ERROR-level findings",
    "INCOMPLETE": (
        "L1 is INCOMPLETE; static validation context is missing or an unresolved item blocks L1"
    ),
    "NOT_EVALUATED": "L1 is NOT_EVALUATED; static validation was not assessed",
    "BLOCKED": "L1 is BLOCKED; L0 did not pass, so static validation was not executed",
}

_STOP_REASON_RUNTIME: dict[str, str] = {
    "L2": "L2 is {status}; build compatibility is not assessed by the static evidence pipeline",
    "L3": "L3 is {status}; smoke execution is not assessed by the static evidence pipeline",
    "L4": "L4 is {status}; task readiness is not assessed by the static evidence pipeline",
    "L5": "L5 is {status}; production evidence is not assessed by the static evidence pipeline",
}

_MISSING_REASON: str = (
    "validation report missing or incomplete; stop reason cannot be derived"
)


def _derive_stop_reason(levels: tuple[LevelSummary, ...]) -> str:
    if len(levels) != len(_LEVEL_ORDER):
        return _MISSING_REASON
    for summary in levels:
        if summary.status == "PASS":
            continue
        if summary.level == "L0":
            return _STOP_REASON_BY_L0.get(summary.status, _MISSING_REASON)
        if summary.level == "L1":
            return _STOP_REASON_BY_L1.get(summary.status, _MISSING_REASON)
        template = _STOP_REASON_RUNTIME.get(summary.level)
        if template is None:
            return _MISSING_REASON
        return template.format(status=summary.status)
    return "All evaluated levels passed; highest_level is L5_PRODUCTION_EVIDENCE"


def build_evidence_summary(
    validation_report: dict[str, Any] | None,
) -> EvidenceSummary | None:
    """Copy evidence levels from the validation report without recomputation."""
    if validation_report is None:
        return None
    levels_data = validation_report.get("levels")
    if not isinstance(levels_data, dict):
        return EvidenceSummary(
            highest_level=str(validation_report.get("highest_level", "NONE")),
            target_level=str(validation_report.get("target_level", "NONE")),
            target_satisfied=bool(validation_report.get("target_satisfied", False)),
            stop_reason=_MISSING_REASON,
            levels=(),
        )
    summaries: list[LevelSummary] = []
    for level in _LEVEL_ORDER:
        entry = levels_data.get(level)
        if not isinstance(entry, dict) or "status" not in entry:
            break
        summaries.append(
            LevelSummary(
                level=level,
                name=str(entry.get("name", "")),
                status=str(entry["status"]),
            )
        )
    return EvidenceSummary(
        highest_level=str(validation_report.get("highest_level", "NONE")),
        target_level=str(validation_report.get("target_level", "NONE")),
        target_satisfied=bool(validation_report.get("target_satisfied", False)),
        stop_reason=_derive_stop_reason(tuple(summaries)),
        levels=tuple(summaries),
    )
