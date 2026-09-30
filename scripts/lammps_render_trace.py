"""render_trace.json serialization for the LAMMPS deterministic renderer.

Byte-stable JSON: UTF-8, LF, trailing newline, two-space indent,
``ensure_ascii=False`` and ``sort_keys=True``. Every command carries its
output span, provenance source, anchor, ordering edges and ID namespace so the
trace is consumable by an explain mode without re-parsing the rendered input.
"""

from __future__ import annotations

import json
from typing import Any

from lammps_anchors import ORDERING_EDGES, fix_style_anchor
from lammps_render_conflicts import cmd_namespace

_EXPLICIT_FIX_STYLES = frozenset({
    "efield", "wall/", "electrode/", "shake", "rigid", "box/relax",
    "nve", "nvt", "npt", "nph", "langevin", "neb", "plumed",
    "recenter", "momentum", "ave/time", "ave/chunk", "ave/atom",
})


def build_trace(req, input_text, output_sha256, anchors, cmd_spans,
                id_allocations, conflicts, validator_findings,
                validator_tiers) -> str:
    payload = {
        "schema_version": 1,
        "code": "lammps",
        "spec_file": req.spec.input_declared_path,
        "output_file": req.spec.input_declared_path,
        "output_sha256": output_sha256,
        "base_template": req.base_template,
        "modifiers": list(req.modifiers),
        "profiles": list(req.profiles),
        "examples_index": "absent" if req.examples_index_path is None else "present",
        "anchors": anchors,
        "commands": [
            _command_entry(req, anchor, name, args, source, span)
            for anchor, name, args, source, span in cmd_spans
        ],
        "id_allocations": [
            {"namespace": a.namespace, "id": a.id, "source": a.source,
             "allocated": a.allocated, "replacement": a.replacement}
            for a in id_allocations
        ],
        "conflicts": [
            {"conflict_type": c.conflict_type, "namespace": c.namespace,
             "id": c.id, "decision": c.decision, "detail": c.detail,
             "before": c.before, "after": c.after}
            for c in conflicts
        ],
        "unresolved": [
            {"key": u.key,
             "blocks_level": u.blocks_level.value
             if hasattr(u.blocks_level, "value") else str(u.blocks_level),
             "reason": u.reason}
            for u in req.spec.unresolved
        ],
        "validator_findings": [
            {"level": f.level, "code": f.code, "message": f.message}
            for f in validator_findings
        ],
        "validator_tiers": [[k, v] for k, v in validator_tiers],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False,
                      sort_keys=True) + "\n"


def _command_entry(req, anchor, name, args, source, span) -> dict[str, Any]:
    ns = cmd_namespace(name)
    return {
        "command": name,
        "id": args[0] if ns is not None and args else None,
        "namespace": ns,
        "anchor": anchor,
        "output_span": [span[0], span[1]],
        "source": _trace_source(source),
        "official_examples": _official_examples(req, name),
        "ordering_edges": _ordering_edges(anchor),
        "anchor_inferred": _anchor_inferred(name, args),
        "conflict_refs": [],
    }


def _trace_source(source: str) -> dict[str, str]:
    if source.startswith("base_template:"):
        return {"type": "base_template", "name": source.split(":", 1)[1]}
    if source.startswith("modifier:"):
        return {"type": "modifier", "name": source.split(":", 1)[1]}
    return {"type": "spec", "name": source}


def _ordering_edges(anchor: str) -> list[str]:
    result = []
    for before, after in ORDERING_EDGES:
        if before == anchor:
            result.append(after)
        elif after == anchor:
            result.append(before)
    return result


def _anchor_inferred(name: str, args: list[str]) -> bool:
    if name != "fix" or len(args) < 3:
        return False
    style = args[2].lower()
    known = any(style == p or style.startswith(p) for p in _EXPLICIT_FIX_STYLES)
    return fix_style_anchor(style) == "integration" and not known


def _official_examples(req, name: str) -> list[str]:
    if req.examples_index_path is None:
        return []
    try:
        index = json.loads(
            req.examples_index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = index.get("entries", []) if isinstance(index, dict) else []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        covered = entry.get("commands")
        if not isinstance(covered, list) or name not in covered:
            continue
        path = entry.get("upstream_path")
        if isinstance(path, str):
            result.append(path)
    return result
