from __future__ import annotations

L4_REQUIRED_KEYS = ("density_comparison_plan", "rdf_comparison_plan", "water_integrity_evidence")
MLFF_FAMILIES = ("mace", "deepmd", "pace", "nequip", "allegro")


def check_static(spec, commands, raw_text="", context=None):
    findings = []
    ctx = context or {}
    system = spec.get("system", {})
    potential = spec.get("potential", {})
    type_map = system.get("type_map", {})

    has_o = any(v == "O" for v in type_map.values())
    has_h = any(v == "H" for v in type_map.values())
    if not (has_o and has_h):
        findings.append(("ERROR", "WATER_HO_MAPPING_EXPLICIT",
            "type_map must contain O and H for interface_water profile"))
    elif "water_o_type" not in ctx or "water_h_type" not in ctx:
        findings.append(("ERROR", "WATER_HO_MAPPING_EXPLICIT",
            "water O and H type IDs must be explicitly declared in profile_context"))

    if "water_model" not in ctx:
        findings.append(("ERROR", "WATER_MODEL_DECLARED",
            "water model must be explicitly declared"))
    if "water_flexibility" not in ctx:
        findings.append(("ERROR", "WATER_FLEXIBILITY_DECLARED",
            "water flexibility (rigid or flexible) must be explicitly declared"))

    flexibility = ctx.get("water_flexibility", "")
    family = potential.get("family", "").lower()
    is_mlff = family in MLFF_FAMILIES
    has_shake = any(cmd == "fix" and len(args) >= 3 and str(args[2]).lower() == "shake" for cmd, args in commands)

    if has_shake and is_mlff and flexibility == "flexible":
        findings.append(("ERROR", "WATER_NO_SHAKE_MLFF_FLEXIBLE",
            "fix shake must not appear with MLFF flexible water; SHAKE changes the model sampling space"))

    if has_shake and flexibility == "rigid":
        if "Bonds" not in raw_text and "bonds" not in raw_text.lower():
            findings.append(("ERROR", "WATER_SHAKE_RIGID_TOPOLOGY",
                "fix shake requires bond and angle topology in the data file; only for user-confirmed rigid classical water"))

    periodicity = system.get("periodicity", [])
    if len(periodicity) == 3:
        non_p = [i for i, b in enumerate(periodicity) if b != "p"]
        if non_p:
            axis_names = ["x", "y", "z"]
            bad = set()
            for cmd, args in commands:
                if cmd == "fix" and len(args) >= 3 and str(args[2]).lower() in ("npt", "nph"):
                    fix_args = " ".join(args).lower()
                    for i in non_p:
                        if axis_names[i] in fix_args:
                            bad.add(axis_names[i])
            if bad:
                findings.append(("ERROR", "WATER_SLAB_BAROSTAT",
                    f"fix npt or nph barostats non-periodic axis {sorted(bad)}; barostat must not couple to vacuum"))

    has_rdf = any(cmd == "compute" and "rdf" in args for cmd, args in commands)
    has_run = any(cmd == "run" for cmd, args in commands)
    if has_run and not has_rdf:
        findings.append(("WARN", "WATER_ANALYSIS_OUTPUTS",
            "RDF, z-density and water-count outputs should be declared for interface water production"))
    return findings


def assess_l4(l3_status, context):
    if l3_status != "PASS":
        return ("BLOCKED", ())
    missing = tuple(k for k in L4_REQUIRED_KEYS if k not in context)
    if missing:
        return ("INCOMPLETE", missing)
    integrity = context.get("water_integrity_evidence", {})
    if isinstance(integrity, dict) and integrity.get("count_conserved") is False:
        return ("FAIL", ())
    return ("PASS", ())
