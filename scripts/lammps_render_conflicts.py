"""Conflict detection for the LAMMPS deterministic renderer.

Mechanical conflicts (duplicate IDs, duplicate output, anchor ordering) are
repaired deterministically; scientific conflicts (multiple integrators,
incompatible ensemble, unresolved placeholders) are recorded as BLOCKED /
UNRESOLVED and never papered over by re-tuning parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

from lammps_anchors import topological_order

_INTEGRATOR_STYLES = frozenset({"nve", "nvt", "npt", "nph", "langevin"})
_PLACEHOLDER_GROUPS = frozenset({"water", "electrolyte"})


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    conflict_type: str
    namespace: str | None
    id: str | None
    decision: str
    detail: str
    before: str | None
    after: str | None


def cmd_namespace(cmd_name: str) -> str | None:
    """Return the LAMMPS ID namespace for a command, or None."""
    if cmd_name == "fix":
        return "fix"
    if cmd_name == "compute":
        return "compute"
    if cmd_name == "dump":
        return "dump"
    return None


def detect_conflicts(req, commands_by_anchor) -> list[ConflictDecision]:
    conflicts: list[ConflictDecision] = []
    all_cmds = []
    for anchor in topological_order():
        for name, args, source in commands_by_anchor.get(anchor, []):
            all_cmds.append((anchor, name, args, source))
    _check_multiple_integrators(all_cmds, conflicts)
    _check_lifecycle(all_cmds, conflicts)
    _check_unresolved_placeholders(all_cmds, conflicts)
    _check_ensemble_compat(req, all_cmds, conflicts)
    _check_duplicate_output(all_cmds, conflicts)
    return conflicts


def _check_multiple_integrators(all_cmds, conflicts):
    active_integrators: dict[str, list[str]] = {}
    reported = set()
    for anchor, name, args, source in all_cmds:
        if name == "fix" and len(args) >= 3:
            style = args[2].lower()
            if style in _INTEGRATOR_STYLES or style.startswith("rigid"):
                group = args[1] if len(args) >= 2 else "unknown"
                fix_id = args[0]
                active_integrators.setdefault(group, []).append(fix_id)
        elif name == "unfix" and args:
            active_integrators.pop(args[0], None)
        elif name == "run":
            for group, ids in active_integrators.items():
                if len(ids) > 1 and (group, tuple(sorted(ids))) not in reported:
                    reported.add((group, tuple(sorted(ids))))
                    conflicts.append(ConflictDecision(
                        conflict_type="MULTIPLE_INTEGRATORS",
                        namespace="fix", id=None, decision="BLOCKED",
                        detail=f"group '{group}' has {len(ids)} active "
                               f"integrators: {', '.join(ids)}",
                        before=None, after=None))


def _check_lifecycle(all_cmds, conflicts):
    active_fixes: set[str] = set()
    active_computes: set[str] = set()
    active_dumps: set[str] = set()
    for anchor, name, args, source in all_cmds:
        if name == "fix" and args:
            active_fixes.add(args[0])
        elif name == "unfix" and args:
            if args[0] not in active_fixes:
                conflicts.append(ConflictDecision(
                    conflict_type="LIFECYCLE_VIOLATION",
                    namespace="fix", id=args[0], decision="BLOCKED",
                    detail=f"unfix {args[0]} references a fix that was "
                           "never created or already released",
                    before=None, after=None))
            active_fixes.discard(args[0])
        elif name == "compute" and args:
            active_computes.add(args[0])
        elif name == "uncompute" and args:
            if args[0] not in active_computes:
                conflicts.append(ConflictDecision(
                    conflict_type="LIFECYCLE_VIOLATION",
                    namespace="compute", id=args[0], decision="BLOCKED",
                    detail=f"uncompute {args[0]} references a compute that "
                           "was never created or already released",
                    before=None, after=None))
            active_computes.discard(args[0])
        elif name == "dump" and args:
            active_dumps.add(args[0])
        elif name == "undump" and args:
            if args[0] not in active_dumps:
                conflicts.append(ConflictDecision(
                    conflict_type="LIFECYCLE_VIOLATION",
                    namespace="dump", id=args[0], decision="BLOCKED",
                    detail=f"undump {args[0]} references a dump that was "
                           "never created or already released",
                    before=None, after=None))
            active_dumps.discard(args[0])


def _check_unresolved_placeholders(all_cmds, conflicts):
    declared_groups: set[str] = set()
    for anchor, name, args, source in all_cmds:
        if name == "group" and len(args) >= 2:
            declared_groups.add(args[0])
    for anchor, name, args, source in all_cmds:
        if "modifier:" not in source:
            continue
        for arg in args:
            if ">>>" in arg:
                conflicts.append(ConflictDecision(
                    conflict_type="UNRESOLVED_PLACEHOLDER",
                    namespace=None, id=None, decision="UNRESOLVED",
                    detail=f"command '{name}' from {source} has unresolved "
                           "placeholder marker",
                    before=None, after=None))
                break
        if name == "fix" and len(args) >= 2 and args[1] in _PLACEHOLDER_GROUPS:
            if args[1] not in declared_groups:
                conflicts.append(ConflictDecision(
                    conflict_type="UNRESOLVED_PLACEHOLDER",
                    namespace="fix", id=args[0] if args else None,
                    decision="UNRESOLVED",
                    detail=f"fix references group '{args[1]}' which is a "
                           "modifier placeholder not declared in the input",
                    before=None, after=None))


def _check_ensemble_compat(req, all_cmds, conflicts):
    periodicity = req.spec.periodicity
    for anchor, name, args, source in all_cmds:
        if name == "fix" and len(args) >= 3 and args[2].lower() in ("npt", "nph"):
            dims = _barostat_dims(args[3:])
            for i, p in enumerate(periodicity):
                if i in dims and p != "p":
                    conflicts.append(ConflictDecision(
                        conflict_type="INCOMPATIBLE_ENSEMBLE",
                        namespace="fix", id=args[0], decision="BLOCKED",
                        detail=f"fix {args[2]} barostats dimension {i} "
                               "but boundary is non-periodic there",
                        before=None, after=None))


def _barostat_dims(tokens):
    PRESSURE_KWS = {"iso": (0, 1, 2), "aniso": (0, 1, 2), "tri": (0, 1, 2),
                    "x": (0,), "y": (1,), "z": (2,),
                    "xy": (0, 1), "yz": (1, 2), "xz": (0, 2)}
    dims = set()
    skip = False
    for t in tokens:
        tl = t.lower()
        if skip:
            skip = False
            continue
        if tl == "couple":
            skip = True
            continue
        if tl in PRESSURE_KWS:
            dims.update(PRESSURE_KWS[tl])
    return dims if dims else {0, 1, 2}


def _check_duplicate_output(all_cmds, conflicts):
    seen_files: dict[str, str] = {}
    for anchor, name, args, source in all_cmds:
        if name == "dump" and len(args) >= 5:
            filepath = args[4]
            if filepath in seen_files:
                conflicts.append(ConflictDecision(
                    conflict_type="DUPLICATE_OUTPUT",
                    namespace="dump", id=args[0], decision="REPAIRED",
                    detail=f"dump writes to '{filepath}' already used by "
                           f"dump {seen_files[filepath]}",
                    before=filepath, after=None))
            else:
                seen_files[filepath] = args[0]
