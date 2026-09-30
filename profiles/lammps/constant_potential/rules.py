from __future__ import annotations

L4_REQUIRED_KEYS = ("zero_V_equilibration_evidence", "target_potential_charge_stability")


def check_static(spec, commands, raw_text=""):
    findings = []
    system = spec.get("system", {})

    atom_style = system.get("atom_style", "")
    if atom_style and atom_style != "full":
        findings.append(("ERROR", "CONP_ATOM_STYLE_FULL",
            f"atom_style is '{atom_style}' but constant_potential requires 'full' (charges and bonds)"))

    has_electrode_fix = False
    kspace_style = ""
    group_defs = []
    has_charge_compute = False
    for cmd, args in commands:
        if cmd == "fix" and len(args) >= 3 and str(args[2]).startswith("electrode/"):
            has_electrode_fix = True
        if cmd == "kspace_style" and args:
            kspace_style = " ".join(args)
        if cmd == "group" and len(args) >= 2:
            group_defs.append(args)
        if cmd == "compute" and "reduce" in args and "sum" in args and "q" in args:
            has_charge_compute = True

    if has_electrode_fix:
        if kspace_style and "/electrode" not in kspace_style:
            findings.append(("ERROR", "CONP_KSPACE_ELECTRODE",
                f"fix electrode/* requires /electrode kspace variant; got '{kspace_style}'"))
        elif not kspace_style:
            findings.append(("ERROR", "CONP_KSPACE_ELECTRODE",
                "fix electrode/* present but kspace_style not set; /electrode variant is mandatory"))

        active_lines = [line.split("#", 1)[0] for line in raw_text.splitlines()]
        if any(">>> USER" in line and "group" in line for line in active_lines) or not group_defs:
            findings.append(("ERROR", "CONP_ELECTRODE_GROUPS_DEFINED",
                "electrode groups must be explicitly defined; no >>> USER placeholder on active group lines"))
        if any(">>> USER" in line and "electrode" in line for line in active_lines):
            findings.append(("ERROR", "CONP_POTENTIAL_EXPLICIT",
                "electrode potentials must be explicit values, not >>> USER markers"))

        boundary = system.get("periodicity", [])
        if len(boundary) == 3 and all(b == "p" for b in boundary):
            ffield_present = any(
                cmd == "fix" and "ffield" in " ".join(args) and "yes" in " ".join(args)
                for cmd, args in commands)
            if not ffield_present:
                findings.append(("ERROR", "CONP_BOUNDARY_FFIELD",
                    "boundary p p p requires ffield yes in fix electrode; finite-field mode is mandatory"))

        if not has_charge_compute:
            dump_has_q = any(cmd == "dump" and "q" in " ".join(args) for cmd, args in commands)
            if not dump_has_q:
                findings.append(("WARN", "CONP_CHARGE_OUTPUT",
                    "electrode charge monitoring should be present for CONP diagnostics"))
    return findings


def assess_l4(l3_status, context):
    if l3_status != "PASS":
        return ("BLOCKED", ())
    missing = tuple(k for k in L4_REQUIRED_KEYS if k not in context)
    if missing:
        return ("INCOMPLETE", missing)
    for key in L4_REQUIRED_KEYS:
        val = context[key]
        if isinstance(val, dict) and val.get("charges_stable") is False:
            return ("FAIL", ())
    return ("PASS", ())
