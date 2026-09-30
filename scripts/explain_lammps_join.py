"""Join logic for the LAMMPS explain mode (Phase I).

Loads existing artifacts and joins them into frozen value objects. This module
never parses, validates, executes, repairs or upgrades evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from explain_lammps_commands import build_command_explanations, build_id_allocations
from explain_lammps_evidence import build_evidence_summary
from explain_lammps_models import (
    ExplainReport,
    FindingExplanation,
    RuleEntry,
    UnresolvedAssumption,
)

_INPUT_ORDER: tuple[str, ...] = (
    "spec",
    "input",
    "render_trace",
    "examples_index",
    "validation_report",
    "static_validation",
)


def load_json(path: Path | None) -> dict[str, Any] | None:
    """Safely load a JSON file; return None when missing or malformed."""
    if path is None:
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_rule_registry(skill_root: Path) -> dict[str, RuleEntry]:
    """Load the LAMMPS validation rules registry."""
    registry = load_json(skill_root / "references" / "lammps_validation_rules.json")
    if registry is None:
        return {}
    rules: dict[str, RuleEntry] = {}
    for code, entry in registry.get("rules", {}).items():
        if not isinstance(entry, dict):
            continue
        rules[str(code)] = RuleEntry(
            rule_id=str(entry.get("rule_id", "")),
            severity=str(entry.get("severity", "")),
            affected_evidence_level=str(entry.get("affected_evidence_level", "")),
            severity_meaning=str(entry.get("severity_meaning", "")),
            rationale=str(entry.get("rationale", "")),
            source_reference=str(entry.get("source_reference", "")),
            trigger_condition=str(entry.get("trigger_condition", "")),
        )
    return rules


def load_input_text(path: Path | None) -> str | None:
    """Load the rendered in.lammps text; return None when missing."""
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def build_finding_explanations(
    static_validation: dict[str, Any] | None,
    rules: dict[str, RuleEntry],
) -> tuple[FindingExplanation, ...]:
    """Explain validator findings through the rule registry."""
    if static_validation is None:
        return ()
    findings = static_validation.get("findings")
    if not isinstance(findings, list):
        return ()
    explained: list[FindingExplanation] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        code = str(finding.get("code", ""))
        rule = rules.get(code)
        explained.append(
            FindingExplanation(
                code=code,
                level=str(finding.get("level", "")),
                message=str(finding.get("message", "")),
                rule=rule,
                explained=rule is not None,
            )
        )
    explained.sort(key=lambda item: item.code)
    return tuple(explained)


def build_unresolved(
    spec: dict[str, Any] | None,
) -> tuple[UnresolvedAssumption, ...]:
    """Copy unresolved assumptions from the generation spec."""
    if spec is None:
        return ()
    unresolved = spec.get("unresolved")
    if not isinstance(unresolved, list):
        return ()
    return tuple(
        UnresolvedAssumption(
            key=str(item.get("key", "")),
            blocks_level=str(item.get("blocks_level", "")),
            reason=str(item.get("reason", "")),
        )
        for item in unresolved
        if isinstance(item, dict)
    )


def _present(path: Path | None) -> bool:
    return path is not None and path.exists()


def build_explain_report(
    spec_path: Path | None,
    input_path: Path | None,
    render_trace_path: Path | None,
    examples_index_path: Path | None,
    validation_report_path: Path | None,
    static_validation_path: Path | None,
    rules: dict[str, RuleEntry] | None = None,
) -> ExplainReport:
    """Join all artifacts into a deterministic ExplainReport."""
    if rules is None:
        rules = load_rule_registry(Path(__file__).resolve().parent.parent)

    paths = {
        "spec": spec_path,
        "input": input_path,
        "render_trace": render_trace_path,
        "examples_index": examples_index_path,
        "validation_report": validation_report_path,
        "static_validation": static_validation_path,
    }
    missing = tuple(name for name in _INPUT_ORDER if not _present(paths[name]))
    inputs = tuple(
        (name, str(paths[name]) if _present(paths[name]) else None)
        for name in _INPUT_ORDER
    )

    trace = load_json(render_trace_path)
    input_text = load_input_text(input_path)
    examples_index = load_json(examples_index_path)
    static_validation = load_json(static_validation_path)
    validation_report = load_json(validation_report_path)
    spec = load_json(spec_path)

    commands = build_command_explanations(trace, input_text, examples_index)
    id_allocations = build_id_allocations(trace)
    findings = build_finding_explanations(static_validation, rules)
    unexplained = tuple(sorted({item.code for item in findings if not item.explained}))
    evidence = build_evidence_summary(validation_report)
    unresolved = build_unresolved(spec)

    complete = not missing and not unexplained
    status = "COMPLETE" if complete else "PARTIAL"
    exit_code = 0 if complete else 1
    exit_reason = (
        "all inputs present and all findings explained"
        if complete
        else "report emitted but inputs or joins incomplete"
    )

    return ExplainReport(
        status=status,
        exit_code=exit_code,
        exit_reason=exit_reason,
        inputs=inputs,
        missing_inputs=missing,
        commands=commands,
        id_allocations=id_allocations,
        findings=findings,
        unexplained_findings=unexplained,
        evidence=evidence,
        unresolved=unresolved,
    )
