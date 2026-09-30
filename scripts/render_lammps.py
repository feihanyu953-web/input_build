"""Deterministic LAMMPS input renderer (Phase D).

Takes a typed ``GenerationSpec`` plus explicitly selected base template,
modifiers and profiles; parses the template with the Phase C parser; injects
``pair_style``/``pair_coeff`` from the spec (never inventing a potential);
applies modifiers; detects and repairs/records conflicts; serializes a
byte-stable ``in.lammps``; runs the existing LAMMPS validator; and emits
``render_trace.json``.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from lammps_anchors import (
    TEMPLATE_ANCHORS,
    AnchorError,
    fix_style_anchor,
    topological_order,
    validate_template_anchors,
)
from lammps_evidence import FindingRecord, UnresolvedItem
from lammps_id_allocator import IdAllocator
from lammps_render_conflicts import ConflictDecision, cmd_namespace, detect_conflicts
from lammps_render_modifiers import apply_modifiers
from lammps_render_trace import build_trace


@dataclass(frozen=True, slots=True)
class RenderRequest:
    spec: Any
    base_template: str
    modifiers: tuple[str, ...]
    profiles: tuple[str, ...]
    templates_dir: Path
    modifiers_dir: Path
    examples_index_path: Path | None


@dataclass(frozen=True, slots=True)
class RenderResult:
    input_text: str
    trace_text: str
    output_sha256: str
    validator_findings: tuple[FindingRecord, ...]
    validator_tiers: tuple[tuple[str, str], ...]
    conflicts: tuple[ConflictDecision, ...]
    unresolved: tuple[UnresolvedItem, ...]


def _format_command(name: str, args: Sequence[str], comment: str = "") -> str:
    parts = " ".join([name, *args])
    if comment:
        return f"{parts} # {comment}"
    return parts


def _inject_potential(spec: Any, commands_by_anchor) -> None:
    ff = commands_by_anchor.setdefault("force_field", [])
    ff.insert(0, ("pair_style", spec.pair_style.split(), "from spec.potential"))
    ff.insert(1, ("pair_coeff", spec.pair_coeff.split(), "from spec.potential"))


def _inject_timestep(spec: Any, commands_by_anchor) -> None:
    ts_fs = spec.protocol.timestep_fs
    if ts_fs is not None:
        vi = commands_by_anchor.setdefault("velocity_init", [])
        vi.append(("timestep", [f"{ts_fs / 1000.0}"],
                   "from spec.protocol.timestep_fs"))


def render(req: RenderRequest) -> RenderResult:
    try:
        validate_template_anchors(
            req.base_template, TEMPLATE_ANCHORS.get(req.base_template, ()))
    except AnchorError as exc:
        return _empty_result(req, str(exc))

    template_path = req.templates_dir / req.base_template
    from parse_lammps import parse_lammps_file
    template_cmds = parse_lammps_file(template_path).commands

    canonical = topological_order()
    commands_by_anchor: dict[str, list[tuple[str, list[str], str]]] = {
        a: [] for a in canonical
    }
    for cmd in template_cmds:
        anchor = _cmd_anchor(cmd)
        commands_by_anchor.setdefault(anchor, []).append(
            (cmd.name, list(cmd.args), f"base_template:{req.base_template}"))

    _inject_potential(req.spec, commands_by_anchor)
    _inject_timestep(req.spec, commands_by_anchor)

    conflicts: list[ConflictDecision] = []
    apply_modifiers(req, commands_by_anchor, conflicts)
    conflicts.extend(detect_conflicts(req, commands_by_anchor))
    id_allocations = _allocate_ids(commands_by_anchor)

    lines, anchors, cmd_spans = _serialize(canonical, commands_by_anchor)
    input_text = "\n".join(lines) + "\n"
    output_sha256 = "sha256:" + hashlib.sha256(
        input_text.encode("utf-8")).hexdigest()

    validator_findings, validator_tiers = _run_validator(req, input_text)
    trace_text = build_trace(
        req, input_text, output_sha256, anchors, cmd_spans,
        id_allocations, tuple(conflicts), validator_findings, validator_tiers)

    return RenderResult(
        input_text=input_text, trace_text=trace_text,
        output_sha256=output_sha256,
        validator_findings=validator_findings,
        validator_tiers=validator_tiers,
        conflicts=tuple(conflicts),
        unresolved=req.spec.unresolved,
    )


def _cmd_anchor(cmd: Any) -> str:
    if cmd.name == "fix" and len(cmd.args) >= 3:
        return fix_style_anchor(cmd.args[2])
    if cmd.name == "unfix":
        return "integration"
    if cmd.name == "uncompute":
        return "analysis"
    if cmd.name == "undump":
        return "output"
    if cmd.name == "compute":
        return "analysis"
    _STATIC = {
        "units": "initialization", "atom_style": "initialization",
        "boundary": "initialization", "newton": "initialization",
        "atom_modify": "initialization",
        "read_data": "system", "read_restart": "system",
        "create_atoms": "system", "replicate": "system", "group": "system",
        "variable": "system",
        "pair_style": "force_field", "pair_coeff": "force_field",
        "pair_modify": "force_field", "kspace_style": "force_field",
        "kspace_modify": "force_field", "neighbor": "force_field",
        "neigh_modify": "force_field",
        "min_style": "minimization", "minimize": "minimization",
        "min_modify": "minimization",
        "velocity": "velocity_init", "timestep": "velocity_init",
        "dump": "output", "dump_modify": "output", "restart": "output",
        "thermo": "output", "thermo_style": "output",
        "thermo_modify": "output",
        "write_data": "cleanup", "write_restart": "cleanup",
        "run": "run", "neb": "run",
    }
    return _STATIC.get(cmd.name, "integration")


def _allocate_ids(commands_by_anchor) -> tuple:
    allocator = IdAllocator()
    order = 0
    for anchor in topological_order():
        for name, args, _source in commands_by_anchor.get(anchor, []):
            ns = cmd_namespace(name)
            if ns is None:
                continue
            if len(args) >= 1 and args[0] not in ("all",):
                allocator.reserve(ns, args[0], "template", order)
            order += 1
    return allocator.finalize()


def _serialize(canonical, commands_by_anchor):
    lines: list[str] = []
    anchors: list[dict[str, int]] = []
    cmd_spans: list[tuple[str, str, list[str], str, tuple[int, int]]] = []
    for anchor in canonical:
        cmds = commands_by_anchor.get(anchor, [])
        if not cmds:
            continue
        start = len(lines) + 1
        lines.append(f"# --- {anchor} ---")
        for name, args, source in cmds:
            cmd_start = len(lines) + 1
            lines.append(_format_command(name, args))
            cmd_end = len(lines)
            cmd_spans.append((anchor, name, args, source, (cmd_start, cmd_end)))
        end = len(lines)
        anchors.append({"name": anchor, "start_line": start, "end_line": end})
    return lines, anchors, cmd_spans


def _run_validator(req, input_text):
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".in", delete=False, encoding="utf-8"
    ) as f:
        f.write(input_text)
        in_path = f.name
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import validate_input
        findings_raw = validate_input.validate_lammps_one(
            in_path, task=req.spec.task, data_path=str(req.spec.data_file))
        tiers = validate_input.validation_tiers(findings_raw, incomplete=False)
        findings = tuple(
            FindingRecord(level=f.level, code=f.code, message=f.message)
            for f in findings_raw)
        return findings, tuple(sorted(tiers.items()))
    finally:
        os.unlink(in_path)


def _empty_result(req, error_msg):
    conflicts = (ConflictDecision(
        conflict_type="RENDER_ERROR", namespace=None, id=None,
        decision="BLOCKED", detail=error_msg, before=None, after=None),)
    return RenderResult(
        input_text="", trace_text="{}", output_sha256="",
        validator_findings=(), validator_tiers=(),
        conflicts=conflicts, unresolved=req.spec.unresolved)
