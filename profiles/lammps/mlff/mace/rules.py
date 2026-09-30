from __future__ import annotations

L4_REQUIRED_KEYS = ("independent_dft_validation", "nve_energy_drift", "structure_coverage")


def check_static(spec, commands, raw_text=""):
    findings = []
    potential = spec.get("potential", {})
    system = spec.get("system", {})
    type_map = system.get("type_map", {})
    type_elements = potential.get("type_elements", [])

    map_values = [type_map[str(i)] for i in range(1, len(type_map) + 1) if str(i) in type_map] if type_map else []
    if type_elements and map_values and list(type_elements) != map_values:
        findings.append(("ERROR", "MACE_TYPE_ELEMENT_ORDER",
            f"type_elements {list(type_elements)} does not match type_map order {map_values}"))

    for cmd, args in commands:
        if cmd == "kspace_style":
            findings.append(("ERROR", "MACE_NO_KSPACE",
                "kspace_style must not appear with MACE (local MLFF, no long-range electrostatics)"))
            break

    atom_style = system.get("atom_style", "")
    if atom_style and atom_style != "atomic":
        findings.append(("ERROR", "MACE_ATOM_STYLE_ATOMIC",
            f"atom_style is '{atom_style}' but MACE requires 'atomic' (no bond topology)"))

    artifacts = potential.get("artifacts", [])
    if artifacts:
        sha = artifacts[0].get("sha256", "")
        if not sha or not sha.startswith("sha256:"):
            findings.append(("ERROR", "MACE_MODEL_HASH_PRESENT",
                "potential.artifacts[0].sha256 is missing or malformed; model hash must be recorded"))
    else:
        findings.append(("ERROR", "MACE_MODEL_HASH_PRESENT",
            "potential.artifacts is empty; MACE model file with sha256 is required"))

    for cmd, args in commands:
        if cmd == "fix" and len(args) >= 3 and str(args[2]).lower() == "efield":
            findings.append(("ERROR", "MACE_NO_EFIELD",
                "fix efield must not appear with MACE; MLFF does not expose per-atom charges"))
            break

    findings.append(("WARN", "MACE_TRAINING_DOMAIN_UNCLAIMED",
        "profile does not claim model training-domain applicability; L4 requires independent DFT validation evidence"))
    return findings


def assess_l4(l3_status, context):
    if l3_status != "PASS":
        return ("BLOCKED", ())
    missing = tuple(k for k in L4_REQUIRED_KEYS if k not in context)
    if missing:
        return ("INCOMPLETE", missing)
    for key in L4_REQUIRED_KEYS:
        val = context[key]
        if isinstance(val, dict) and val.get("passed") is False:
            return ("FAIL", ())
    return ("PASS", ())
