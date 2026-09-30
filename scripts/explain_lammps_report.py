"""Deterministic JSON/Markdown serialization for the LAMMPS explain mode."""

from __future__ import annotations

import json
from typing import Any

from explain_lammps_models import (
    CommandExplanation,
    EvidenceSummary,
    ExplainReport,
    FindingExplanation,
    IdAllocation,
)


def _command_payload(cmd: CommandExplanation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": cmd.index,
        "command": cmd.command,
        "args": list(cmd.args),
        "source_text": cmd.source_text,
        "assigned_id": cmd.assigned_id,
        "id_type": cmd.id_type,
        "anchor": cmd.anchor,
        "ordering_rationale": cmd.ordering_rationale,
        "profile_contribution": cmd.profile_contribution,
    }
    if cmd.source_span is None:
        payload["source_span"] = None
    else:
        payload["source_span"] = {
            "start_line": cmd.source_span[0],
            "end_line": cmd.source_span[1],
        }
    if cmd.provenance is None:
        payload["provenance"] = None
    else:
        payload["provenance"] = {
            "origin": cmd.provenance.origin,
            "name": cmd.provenance.name,
            "section": cmd.provenance.section,
        }
    if cmd.official_example is None:
        payload["official_example"] = None
    else:
        payload["official_example"] = {
            "path": cmd.official_example.path,
            "lammps_version": cmd.official_example.lammps_version,
            "source_url": cmd.official_example.source_url,
            "resolved": cmd.official_example.resolved,
        }
    return payload


def _id_payload(alloc: IdAllocation) -> dict[str, Any]:
    return {
        "id_type": alloc.id_type,
        "id": alloc.id,
        "command_index": alloc.command_index,
        "rationale": alloc.rationale,
    }


def _finding_payload(finding: FindingExplanation) -> dict[str, Any]:
    rule = finding.rule
    return {
        "code": finding.code,
        "level": finding.level,
        "message": finding.message,
        "rule": None if rule is None else {
            "rule_id": rule.rule_id,
            "severity": rule.severity,
            "affected_evidence_level": rule.affected_evidence_level,
            "severity_meaning": rule.severity_meaning,
            "rationale": rule.rationale,
            "source_reference": rule.source_reference,
            "trigger_condition": rule.trigger_condition,
        },
        "explained": finding.explained,
    }


def _evidence_payload(evidence: EvidenceSummary | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "highest_level": evidence.highest_level,
        "target_level": evidence.target_level,
        "target_satisfied": evidence.target_satisfied,
        "stop_reason": evidence.stop_reason,
        "levels": [
            {"level": summary.level, "name": summary.name, "status": summary.status}
            for summary in evidence.levels
        ],
    }


def report_json(report: ExplainReport) -> str:
    """Return canonical pretty JSON with one trailing newline."""
    payload = {
        "schema_version": 1,
        "code": "lammps",
        "status": report.status,
        "exit_code": report.exit_code,
        "exit_reason": report.exit_reason,
        "inputs": {name: path for name, path in report.inputs},
        "missing_inputs": list(report.missing_inputs),
        "commands": [_command_payload(cmd) for cmd in report.commands],
        "id_allocations": [_id_payload(alloc) for alloc in report.id_allocations],
        "findings": [_finding_payload(finding) for finding in report.findings],
        "unexplained_findings": list(report.unexplained_findings),
        "evidence": _evidence_payload(report.evidence),
        "unresolved": [
            {"key": item.key, "blocks_level": item.blocks_level, "reason": item.reason}
            for item in report.unresolved
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _cell(value: str | None) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|")


def report_markdown(report: ExplainReport) -> str:
    """Return a deterministic human-readable explanation with one trailing newline."""
    lines = [
        "# LAMMPS Input Explanation",
        "",
        f"Status: `{report.status}`",
        f"Exit code: `{report.exit_code}`",
        f"Exit reason: {report.exit_reason}",
        "",
        "## Inputs",
        "",
        "| Input | Path |",
        "|---|---|",
    ]
    for name, path in report.inputs:
        lines.append(f"| {name} | {_cell(path)} |")

    lines.extend(["", "## Missing inputs", ""])
    if report.missing_inputs:
        for name in report.missing_inputs:
            lines.append(f"- {name}")
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            "## Command provenance",
            "",
            "| Index | Command | Span | Origin | Source | Assigned ID | Anchor | Ordering rationale |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    if report.commands:
        for cmd in report.commands:
            span = (
                f"{cmd.source_span[0]}-{cmd.source_span[1]}"
                if cmd.source_span
                else "-"
            )
            aid = (
                f"{cmd.id_type} {cmd.assigned_id}"
                if cmd.assigned_id is not None
                else "-"
            )
            origin = cmd.provenance.origin if cmd.provenance else "-"
            source = cmd.provenance.name if cmd.provenance else "-"
            full_cmd = " ".join([cmd.command, *cmd.args])
            lines.append(
                f"| {cmd.index} | {_cell(full_cmd)} | {span} | {origin} | {source} | {aid} | {_cell(cmd.anchor)} | {_cell(cmd.ordering_rationale)} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## ID allocations",
            "",
            "| Type | ID | Command index | Rationale |",
            "|---|---|---|---|",
        ]
    )
    if report.id_allocations:
        for alloc in report.id_allocations:
            lines.append(
                f"| {alloc.id_type} | {alloc.id} | {alloc.command_index} | {_cell(alloc.rationale)} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.extend(
        [
            "",
            "## Validator findings",
            "",
            "| Code | Level | Explained | Rule ID | Affected level |",
            "|---|---|---|---|---|",
        ]
    )
    if report.findings:
        for finding in report.findings:
            rule_id = finding.rule.rule_id if finding.rule else "-"
            affected = (
                finding.rule.affected_evidence_level if finding.rule else "-"
            )
            explained = "yes" if finding.explained else "no"
            lines.append(
                f"| {finding.code} | {finding.level} | {explained} | {rule_id} | {affected} |"
            )
    else:
        lines.append("| - | - | - | - | - |")

    lines.extend(["", "## Unexplained findings", ""])
    if report.unexplained_findings:
        for code in report.unexplained_findings:
            lines.append(f"- {code}")
    else:
        lines.append("(none)")

    lines.extend(["", "## Evidence levels", ""])
    if report.evidence:
        lines.append(f"Highest level: `{report.evidence.highest_level}`")
        lines.append(f"Stop reason: {report.evidence.stop_reason}")
        lines.append("")
        lines.extend(["| Level | Name | Status |", "|---|---|---|"])
        for summary in report.evidence.levels:
            lines.append(f"| {summary.level} | {summary.name} | {summary.status} |")
    else:
        lines.append("(validation report missing)")

    lines.extend(
        [
            "",
            "## Unresolved assumptions",
            "",
            "| Key | Blocks level | Reason |",
            "|---|---|---|",
        ]
    )
    if report.unresolved:
        for item in report.unresolved:
            reason = item.reason.replace("|", "\\|")
            lines.append(f"| {item.key} | {item.blocks_level} | {reason} |")
    else:
        lines.append("| - | - | - |")

    return "\n".join(lines) + "\n"
