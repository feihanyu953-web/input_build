"""Closed anchor vocabulary and ordering graph for the LAMMPS renderer.

The anchor vocabulary is a closed enumeration: unknown, missing or duplicate
anchors fail closed with an ``AnchorError`` so the renderer never silently
misplaces a command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping


class AnchorError(Exception):
    """Raised when anchor validation fails closed."""


ANCHOR_NAMES: Final[tuple[str, ...]] = (
    "initialization", "system", "force_field", "minimization",
    "velocity_init", "external_force_fixes", "constraints",
    "integration", "analysis", "output", "run", "cleanup",
)

_ANCHOR_SET: Final[frozenset[str]] = frozenset(ANCHOR_NAMES)

ORDERING_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("initialization", "system"),
    ("system", "force_field"),
    ("force_field", "minimization"),
    ("force_field", "velocity_init"),
    ("minimization", "velocity_init"),
    ("velocity_init", "external_force_fixes"),
    ("external_force_fixes", "constraints"),
    ("constraints", "integration"),
    ("integration", "analysis"),
    ("analysis", "output"),
    ("output", "run"),
    ("run", "cleanup"),
)


def topological_order() -> tuple[str, ...]:
    """Return the deterministic linear order implied by ORDERING_EDGES."""
    indeg: dict[str, int] = {a: 0 for a in ANCHOR_NAMES}
    adj: dict[str, list[str]] = {a: [] for a in ANCHOR_NAMES}
    for before, after in ORDERING_EDGES:
        adj[before].append(after)
        indeg[after] += 1
    queue = [a for a in ANCHOR_NAMES if indeg[a] == 0]
    result: list[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(result) != len(ANCHOR_NAMES):
        raise AnchorError("CYCLE_IN_ORDERING_GRAPH")
    return tuple(result)


_COVERED_TEMPLATES: Final[frozenset[str]] = frozenset({
    "lammps_md.in", "lammps_mlff.in",
})

TEMPLATE_ANCHORS: Final[Mapping[str, tuple[str, ...]]] = {
    "lammps_md.in": (
        "initialization", "system", "force_field", "minimization",
        "velocity_init", "integration", "output", "run", "cleanup",
    ),
    "lammps_mlff.in": (
        "initialization", "system", "force_field", "minimization",
        "velocity_init", "integration", "output", "run", "cleanup",
    ),
    "lammps_nve.in": (
        "initialization", "system", "force_field", "velocity_init",
        "integration", "output", "run", "cleanup",
    ),
    "lammps_minimize.in": (
        "initialization", "system", "force_field", "minimization",
        "output", "run", "cleanup",
    ),
    "lammps_conp.in": (
        "initialization", "system", "force_field", "velocity_init",
        "external_force_fixes", "constraints", "integration",
        "output", "run", "cleanup",
    ),
    "lammps_plumed.in": (
        "initialization", "system", "force_field", "velocity_init",
        "integration", "output", "run", "cleanup",
    ),
    "lammps_neb.in": (
        "initialization", "system", "force_field", "integration",
        "run", "cleanup",
    ),
}


def validate_template_anchors(
    template_name: str, observed: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate that observed anchors match the declared sequence.

    Returns the canonical order on success. Raises AnchorError on any
    mismatch. Templates not in _COVERED_TEMPLATES raise TEMPLATE_NOT_COVERED
    but still have their declared sequence validated if present.
    """
    declared = TEMPLATE_ANCHORS.get(template_name)
    if declared is None:
        raise AnchorError(f"UNKNOWN_TEMPLATE:{template_name}")
    if template_name not in _COVERED_TEMPLATES:
        raise AnchorError(f"TEMPLATE_NOT_COVERED:{template_name}")
    expected_set = set(declared)
    observed_set = set(observed)
    for missing in expected_set - observed_set:
        raise AnchorError(f"MISSING_ANCHOR:{missing}")
    seen: set[str] = set()
    for anchor in observed:
        if anchor not in _ANCHOR_SET:
            raise AnchorError(f"UNKNOWN_ANCHOR:{anchor}")
        if anchor in seen:
            raise AnchorError(f"DUPLICATE_ANCHOR:{anchor}")
        seen.add(anchor)
    return declared


@dataclass(frozen=True, slots=True)
class ModifierAnchorTarget:
    anchor: str
    insert: str  # append / before_constraints / replace_integrator / replace_dump


MODIFIER_ANCHORS: Final[Mapping[str, ModifierAnchorTarget]] = {
    "efield_lammps":     ModifierAnchorTarget("external_force_fixes", "append"),
    "shake_lammps":      ModifierAnchorTarget("constraints", "append"),
    "wall_slab":         ModifierAnchorTarget("external_force_fixes", "before_constraints"),
    "ensemble_langevin": ModifierAnchorTarget("integration", "replace_integrator"),
    "temp_ramp":         ModifierAnchorTarget("integration", "replace_integrator"),
    "dump_full":         ModifierAnchorTarget("output", "replace_dump"),
    "analysis_rdf_msd":  ModifierAnchorTarget("analysis", "append"),
    "analysis_hbond":    ModifierAnchorTarget("analysis", "append"),
}


def validate_modifier_anchor(modifier_name: str) -> ModifierAnchorTarget:
    target = MODIFIER_ANCHORS.get(modifier_name)
    if target is None:
        raise AnchorError(f"UNKNOWN_MODIFIER:{modifier_name}")
    if target.anchor not in _ANCHOR_SET:
        raise AnchorError(f"UNKNOWN_MODIFIER_ANCHOR:{target.anchor}")
    return target


_FIX_STYLE_ANCHORS: Final[tuple[tuple[str, str], ...]] = (
    ("efield", "external_force_fixes"),
    ("wall/", "external_force_fixes"),
    ("electrode/", "external_force_fixes"),
    ("shake", "constraints"),
    ("rigid", "constraints"),
    ("box/relax", "constraints"),
    ("nve", "integration"),
    ("nvt", "integration"),
    ("npt", "integration"),
    ("nph", "integration"),
    ("langevin", "integration"),
    ("neb", "integration"),
    ("plumed", "integration"),
    ("recenter", "integration"),
    ("momentum", "integration"),
    ("ave/time", "analysis"),
    ("ave/chunk", "analysis"),
    ("ave/atom", "analysis"),
)


def fix_style_anchor(style: str) -> str:
    """Map a fix style to its anchor. Returns 'integration' as conservative
    default for unrecognized styles, with anchor_inferred=True at call site."""
    lowered = style.lower()
    for prefix, anchor in _FIX_STYLE_ANCHORS:
        if lowered == prefix or lowered.startswith(prefix):
            return anchor
    return "integration"


def anchor_ordinal(anchor: str) -> int:
    """Return the position of an anchor in the canonical order."""
    return topological_order().index(anchor)
