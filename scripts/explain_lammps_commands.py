"""Command-level joins for the LAMMPS explain mode (Phase I)."""

from __future__ import annotations

from typing import Any

from explain_lammps_models import (
    CommandExplanation,
    IdAllocation,
    OfficialExampleRef,
    ProvenanceExplanation,
)


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _source_text(lines: list[str] | None, span: tuple[int, int] | None) -> str | None:
    if lines is None or span is None:
        return None
    start, end = span
    if start < 1 or end < start or end > len(lines):
        return None
    return "\n".join(lines[start - 1 : end])


def _examples_by_path(
    examples_index: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if examples_index is None:
        return {}
    entries = examples_index.get("entries")
    if not isinstance(entries, list):
        return {}
    return {
        str(entry["path"]): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }


def _command_explanation(
    entry: dict[str, Any],
    lines: list[str] | None,
    examples: dict[str, dict[str, Any]],
) -> CommandExplanation:
    span = entry.get("source_span")
    span_tuple = None
    if isinstance(span, dict) and isinstance(span.get("start_line"), int):
        start = int(span["start_line"])
        end = span.get("end_line")
        if isinstance(end, int):
            span_tuple = (start, end)

    provenance = entry.get("provenance")
    prov = None
    if isinstance(provenance, dict):
        prov = ProvenanceExplanation(
            origin=str(provenance.get("origin", "")),
            name=str(provenance.get("name", "")),
            section=(
                str(provenance["section"])
                if provenance.get("section") is not None
                else None
            ),
        )

    ref = entry.get("official_example_ref")
    example = None
    if isinstance(ref, str):
        found = examples.get(ref)
        if found is not None:
            example = OfficialExampleRef(
                path=ref,
                lammps_version=_optional_str(found.get("lammps_version")),
                source_url=_optional_str(found.get("source_url")),
                resolved=True,
            )
        else:
            example = OfficialExampleRef(
                path=ref, lammps_version=None, source_url=None, resolved=False
            )

    return CommandExplanation(
        index=int(entry.get("index", 0)),
        command=str(entry.get("command", "")),
        args=tuple(str(arg) for arg in entry.get("args", ()) or ()),
        source_span=span_tuple,
        source_text=_source_text(lines, span_tuple),
        provenance=prov,
        official_example=example,
        assigned_id=(
            int(entry["assigned_id"]) if entry.get("assigned_id") is not None else None
        ),
        id_type=(
            str(entry["id_type"]) if entry.get("id_type") is not None else None
        ),
        anchor=(
            str(entry["anchor"]) if entry.get("anchor") is not None else None
        ),
        ordering_rationale=(
            str(entry["ordering_rationale"])
            if entry.get("ordering_rationale") is not None
            else None
        ),
        profile_contribution=(
            str(entry["profile_contribution"])
            if entry.get("profile_contribution") is not None
            else None
        ),
    )


def build_command_explanations(
    trace: dict[str, Any] | None,
    input_text: str | None,
    examples_index: dict[str, Any] | None,
) -> tuple[CommandExplanation, ...]:
    """Build command explanations from the render trace and input text."""
    if trace is None:
        return ()
    entries = trace.get("commands")
    if not isinstance(entries, list):
        return ()
    examples = _examples_by_path(examples_index)
    lines = input_text.splitlines() if input_text is not None else None
    commands: list[CommandExplanation] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        commands.append(_command_explanation(entry, lines, examples))
    commands.sort(key=lambda cmd: cmd.index)
    return tuple(commands)


def build_id_allocations(
    trace: dict[str, Any] | None,
) -> tuple[IdAllocation, ...]:
    """Build ID allocations from the render trace, sorted by type then id."""
    if trace is None:
        return ()
    entries = trace.get("id_allocations")
    if not isinstance(entries, list):
        return ()
    allocations = [
        IdAllocation(
            id_type=str(entry["id_type"]),
            id=int(entry["id"]),
            command_index=int(entry["command_index"]),
            rationale=str(entry.get("rationale", "")),
        )
        for entry in entries
        if isinstance(entry, dict)
        and "id_type" in entry
        and "id" in entry
        and "command_index" in entry
    ]
    allocations.sort(key=lambda alloc: (alloc.id_type, alloc.id))
    return tuple(allocations)
