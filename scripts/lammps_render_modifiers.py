"""Modifier application for the LAMMPS deterministic renderer.

Each modifier snippet is parsed with the Phase C parser and inserted into its
declared target anchor. ``replace_integrator`` and ``replace_dump`` swap out the
existing integrator/dump fix so force-adding fixes always precede SHAKE/rigid
and definitions precede their consumers.
"""

from __future__ import annotations

from lammps_anchors import AnchorError, validate_modifier_anchor
from lammps_render_conflicts import ConflictDecision, cmd_namespace

_INTEGRATOR_STYLES = frozenset({"nve", "nvt", "npt", "nph", "langevin"})

_MODIFIER_FILES: dict[str, str] = {
    "efield_lammps": "fix_efield.snip",
    "shake_lammps": "fix_shake.snip",
    "wall_slab": "fix_wall_slab.snip",
    "ensemble_langevin": "ensemble_langevin.snip",
    "temp_ramp": "temp_ramp.snip",
    "dump_full": "dump_full.snip",
    "analysis_rdf_msd": "analysis_rdf_msd.snip",
    "analysis_hbond": "analysis_hbond.snip",
}


def _modifier_filename(modifier_name: str) -> str:
    return _MODIFIER_FILES.get(modifier_name, f"{modifier_name}.snip")


def apply_modifiers(req, commands_by_anchor, conflicts) -> None:
    for mod_name in req.modifiers:
        try:
            target = validate_modifier_anchor(mod_name)
        except AnchorError as exc:
            conflicts.append(ConflictDecision(
                conflict_type="UNKNOWN_MODIFIER", namespace=None, id=None,
                decision="BLOCKED", detail=str(exc), before=None, after=None))
            continue
        snip_path = req.modifiers_dir / _modifier_filename(mod_name)
        from parse_lammps import parse_lammps_file
        snip_cmds = parse_lammps_file(snip_path).commands
        new_entries = [(cmd.name, list(cmd.args), f"modifier:{mod_name}")
                       for cmd in snip_cmds]
        if target.insert == "replace_dump":
            _replace_in_anchor(
                commands_by_anchor, "output", "dump", new_entries, mod_name,
                conflicts)
        elif target.insert == "replace_integrator":
            _replace_in_anchor(
                commands_by_anchor, "integration", "fix", new_entries,
                mod_name, conflicts, style_filter=_INTEGRATOR_STYLES)
        else:
            bucket = commands_by_anchor.setdefault(target.anchor, [])
            bucket.extend(new_entries)


def _replace_in_anchor(commands_by_anchor, anchor, cmd_name,
                       new_entries, mod_name, conflicts, style_filter=None):
    bucket = commands_by_anchor.setdefault(anchor, [])
    replaced = False
    result = []
    for name, args, source in bucket:
        if name == cmd_name and not replaced:
            if style_filter is None or (
                len(args) >= 3 and args[2].lower() in style_filter):
                replaced = True
                result.extend(new_entries)
                conflicts.append(ConflictDecision(
                    conflict_type="MODIFIER_REPLACES_INTEGRATOR"
                    if style_filter else "DUPLICATE_OUTPUT",
                    namespace=cmd_namespace(cmd_name),
                    id=args[0] if args else None,
                    decision="REPAIRED",
                    detail=f"{mod_name} replaced existing {cmd_name}",
                    before=" ".join([name, *args]),
                    after=" ".join([new_entries[0][0], *new_entries[0][1]]),
                ))
                continue
        result.append((name, args, source))
    if not replaced:
        result.extend(new_entries)
    commands_by_anchor[anchor] = result
