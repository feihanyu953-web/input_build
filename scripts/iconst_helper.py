#!/usr/bin/env python3
"""
ICONST / SG-AIMD helper for input_build.

Two subcommands:

  candidates  List candidate atoms with their real distances to an acceptor
              atom, so the user can pick the reacting atom on evidence.
              Read-only.

  render      Verify a declared collective variable against POSCAR geometry,
              compute INCREM, write ICONST and (with --emit-incar) derive both
              stage INCARs from base_templates/vasp_slowgrowth.incar.

Division of labour: this script never invents atom indices, CV definitions or
growth rates. The user supplies the chemistry; the script does the arithmetic,
the index bookkeeping and the file rendering. Stdlib only.

Distances use the minimum-image convention, which is how a periodic MD code
sees a bond that straddles the cell boundary.
"""

import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import iconst as ic                      # noqa: E402
import validate_input as vi              # noqa: E402

# Candidates closer than this to the acceptor are bonded to it (X-H covalent
# bonds max out around 1.1 A even PBE-relaxed; H-bonds and hydrides start
# around 1.5 A), so they are the acceptor's own atoms, not transferring ones.
_BONDING_THRESHOLD_A = 1.2


def _fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _load_structure(path):
    if not os.path.exists(path):
        _fail(f"POSCAR not found: {path}")
    try:
        structure = vi.parse_poscar(path)
    except (ValueError, IndexError) as exc:
        _fail(f"could not parse {path}: {exc}")
    if structure.elements is None:
        _fail(f"{path}: POSCAR has no element-symbols line (VASP4 style); "
              "the helper needs element names to resolve species and indices")
    return structure


def _element_of(structure, index1):
    """Element symbol of a 1-based atom index, from the POSCAR element blocks."""
    seen = 0
    for element, count in zip(structure.elements, structure.counts):
        if index1 <= seen + count:
            return element
        seen += count
    return "?"


def _indices_of_species(structure, species):
    out = []
    seen = 0
    for element, count in zip(structure.elements, structure.counts):
        if element == species:
            out.extend(range(seen + 1, seen + count + 1))
        seen += count
    return out


def cmd_candidates(args):
    structure = _load_structure(args.poscar)
    natoms = structure.natoms

    if args.indices:
        indices = list(args.indices)
    elif args.species:
        indices = _indices_of_species(structure, args.species)
        if not indices:
            _fail(f"no atoms of species {args.species!r} in {args.poscar}; "
                  f"POSCAR declares {list(structure.elements)}")
    else:
        _fail("give --species or --indices to select candidate atoms")

    for i in indices:
        if i < 1 or i > natoms:
            _fail(f"atom index {i} is outside 1..{natoms}")
    if args.acceptor is not None and not (1 <= args.acceptor <= natoms):
        _fail(f"--acceptor {args.acceptor} is outside 1..{natoms}")

    print(f"POSCAR: {args.poscar}   ({natoms} atoms, "
          f"elements {' '.join(structure.elements)})")
    if args.acceptor is not None:
        print(f"Acceptor: atom {args.acceptor} "
              f"({_element_of(structure, args.acceptor)})")
    print()
    header = f"{'index':>6}  {'elem':>4}  {'x':>9} {'y':>9} {'z':>9}"
    if args.acceptor is not None:
        header += f"  {'d(acceptor)':>12}"
    print(header)
    print("-" * len(header))

    rows = []
    for i in indices:
        cart = ic._cart(structure, i)
        line = (f"{i:>6}  {_element_of(structure, i):>4}  "
                f"{cart[0]:>9.3f} {cart[1]:>9.3f} {cart[2]:>9.3f}")
        dist = None
        if args.acceptor is not None:
            dist = ic._norm(ic._min_image_vector(structure, i, args.acceptor))
            line += f"  {dist:>12.3f}"
        rows.append((i, dist))
        print(line)

    print()
    if args.acceptor is not None:
        ranked = sorted((d, i) for i, d in rows if d is not None)
        if ranked:
            bonded = [(d, i) for d, i in ranked if d < _BONDING_THRESHOLD_A]
            free = [(d, i) for d, i in ranked if d >= _BONDING_THRESHOLD_A]
            for d, i in bonded:
                print(f"NOTE: atom {i} excluded from the ranking: bonded to "
                      f"the acceptor ({d:.3f} A < {_BONDING_THRESHOLD_A:g} A). "
                      "If the proton has already transferred, this atom is "
                      "the reverse-direction donor.")
            if free:
                best_d, best_i = free[0]
                print(f"SUGGESTION: atom {best_i} is closest to the acceptor "
                      f"({best_d:.3f} A) among non-bonded candidates.")
                if best_d > 2.5:
                    print("  WARNING: even the closest non-bonded candidate is "
                          "> 2.5 A from the acceptor. The structure is probably "
                          "not pre-oriented for this reaction - re-orient and "
                          "re-equilibrate before starting slow growth instead of "
                          "picking a least-bad atom.")
            else:
                print("SUGGESTION: none - every candidate is bonded to the "
                      "acceptor. The proton transfer may already be complete; "
                      "for a reverse-direction scan pick the donor side "
                      "instead.")
            print("  This is a geometric ranking only. Confirm the chemistry "
                  "yourself before it goes into ICONST: a wrong atom index "
                  "produces a valid run of the wrong reaction, with no error.")
    else:
        print("No --acceptor given: distances were not computed. "
              "Pass --acceptor <index> to rank candidates.")
    return 0


# A commented INCREM assignment (the growth-stage placeholder) and a live
# LBLUEOUT assignment. Anchored so explanatory comments cannot match.
_INCREM_PLACEHOLDER_RE = re.compile(r"^#\s*INCREM\s*=", re.IGNORECASE)
_LBLUEOUT_ASSIGN_RE = re.compile(r"^LBLUEOUT\s*=", re.IGNORECASE)


def _parse_cv_spec(specs):
    """Turn --cv "R 5 7" strings into IconstLine objects with status=0."""
    lines = []
    for lineno, spec in enumerate(specs, start=1):
        tokens = spec.split()
        if not tokens:
            _fail("empty --cv specification")
        flag = tokens[0]
        if flag not in ic.PRIMITIVE_FLAGS and flag not in ic.COMPLEX_FLAGS:
            _fail(f"--cv {spec!r}: unknown ICONST flag {flag!r}")
        is_complex = flag in ic.COMPLEX_FLAGS
        n_idx = 0 if is_complex else ic.ATOM_INDEX_ARITY.get(flag, 0)
        items = []
        for i, tok in enumerate(tokens[1:]):
            try:
                items.append(int(tok) if i < n_idx else float(tok))
            except ValueError:
                _fail(f"--cv {spec!r}: cannot parse item {tok!r}")
        lines.append(ic.IconstLine(flag, items, 0, lineno, spec))
    return lines


def _render_iconst_text(lines):
    out = []
    for line in lines:
        items = " ".join(
            (f"{v:g}" if isinstance(v, float) else str(v)) for v in line.items)
        out.append(f"{line.flag} {items} {line.status}".replace("  ", " "))
    return "\n".join(out) + "\n"


def _emit_stage_incars(template_path, growth_path, equil_path, increm_values):
    """Derive both stage INCARs from ONE template read.

    Growth: activate INCREM with the computed value, LBLUEOUT=.TRUE.
    Equil:  keep INCREM commented (= 0), LBLUEOUT=.FALSE.
    Only these two lines differ, so the stages cannot drift apart.
    """
    if not os.path.exists(template_path):
        _fail(f"--template not found: {template_path}")
    with open(template_path, encoding="utf-8") as fh:
        template = fh.read().splitlines()

    # Scientific notation: a slow-growth increment is ~1e-4, and %g would render
    # it as 0.000333333, which is hard to eyeball and unlike VASP's own style.
    increm_text = " ".join(f"{v:.5E}" for v in increm_values)
    growth, equil = [], []
    seen_increm = seen_lblueout = False
    for raw in template:
        stripped = raw.strip()
        # Match ONLY a commented INCREM assignment. A loose "INCREM" substring
        # test would hit the explanatory comments first (they contain both
        # "INCREM" and "=", e.g. "STATUS=0" and "INCREM commented out (= 0)")
        # and inject the tag into the comment block.
        if not seen_increm and _INCREM_PLACEHOLDER_RE.match(stripped):
            seen_increm = True
            growth.append(f"INCREM   = {increm_text}")
            equil.append(raw)
            continue
        if _LBLUEOUT_ASSIGN_RE.match(stripped):
            seen_lblueout = True
            growth.append("LBLUEOUT = .TRUE.")
            equil.append("LBLUEOUT = .FALSE.")
            continue
        growth.append(raw)
        equil.append(raw)

    if not seen_increm:
        _fail(f"{template_path}: no commented INCREM placeholder found; the "
              "template must carry a '# INCREM = ...' line for the growth stage")
    if not seen_lblueout:
        _fail(f"{template_path}: no LBLUEOUT line found")

    for path, body in ((growth_path, growth), (equil_path, equil)):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(body).rstrip("\n") + "\n")
    return increm_text


def cmd_render(args):
    structure = _load_structure(args.poscar)
    lines = _parse_cv_spec(args.cv)

    # 1. syntax + ordering, reusing the same arity rules the validator uses
    issues = []
    built = []
    seen_complex = False
    for line in lines:
        if line.is_complex:
            seen_complex = True
        elif seen_complex:
            _fail(f"--cv {line.raw!r}: every primitive coordinate must be "
                  "declared before any complex coordinate")
        issues.extend(ic._check_arity(line, built))
        built.append(line)
    errors = [x for x in issues if x["level"] == "ERROR"]
    if errors:
        for x in errors:
            print(f"ERROR: {x['message']}", file=sys.stderr)
        raise SystemExit(1)
    for x in issues:
        if x["level"] == "WARN":
            print(f"WARNING: {x['message']}")

    # 2. atom-index range, then the current CV value from POSCAR geometry
    for line in lines:
        n_idx = 0 if line.is_complex else ic.ATOM_INDEX_ARITY.get(line.flag, 0)
        for idx in line.items[:n_idx]:
            if idx < 1 or idx > structure.natoms:
                _fail(f"--cv {line.raw!r}: atom index {idx} is outside "
                      f"1..{structure.natoms}")

    primitives = [l for l in lines if not l.is_complex]
    complexes = [l for l in lines if l.is_complex]
    target = complexes[-1] if complexes else primitives[-1]
    try:
        prim_values = [ic.evaluate_primitive(p, structure) for p in primitives]
        current = (ic.evaluate_complex(target, prim_values) if target.is_complex
                   else ic.evaluate_primitive(target, structure))
    except ValueError as exc:
        _fail(str(exc))
    kind = ic.basis_kind(target, primitives)
    unit = ic.TOLERANCE.get(kind, (None, ""))[1]

    print(f"POSCAR: {args.poscar}   ({structure.natoms} atoms)")
    print(f"CV: {target.raw}   basis={kind}")
    for p, v in zip(primitives, prim_values):
        print(f"    {p.raw:<16} = {v:.4f} "
              f"{ic.TOLERANCE.get(ic.basis_kind(p, [p]), (None, ''))[1]}")
    print(f"CV value in POSCAR      = {current:.4f} {unit}")
    print(f"CV initial value declared = {args.xi:.4f} {unit}")

    if kind == "mixed":
        print("INFO: this S coordinate mixes bases with different units "
              "(e.g. distance and angle), so the declared initial value cannot "
              "be compared numerically. Reported for inspection only.")
    else:
        tol, _u = ic.TOLERANCE[kind]
        if abs(current - args.xi) > tol:
            print(f"WARNING: the declared initial value does not match POSCAR "
                  f"geometry: |{current:.4f} - {args.xi:.4f}| = "
                  f"{abs(current - args.xi):.4f} {unit} > {tol:g} {unit} "
                  f"tolerance. Slow growth starts from the geometry actually in "
                  f"POSCAR, so the whole free-energy profile shifts. Move the "
                  f"structure onto the intended initial value first.")

    # 3. INCREM
    if args.nsw <= 0:
        _fail("--nsw must be positive")
    increm = (args.xf - args.xi) / args.nsw
    direction = "increases" if increm > 0 else ("decreases" if increm < 0
                                                else "does not change")
    print()
    print(f"INCREM = {increm:.5E}   ({args.xi:g} -> {args.xf:g} {unit} "
          f"over NSW={args.nsw} steps; the CV {direction})")
    if args.potim:
        per_ps = increm * (1000.0 / args.potim)
        total_ps = args.nsw * args.potim / 1000.0
        print(f"         rate = {per_ps:.4g} {unit}/ps at POTIM={args.potim:g} fs; "
              f"total {total_ps:.3g} ps")
    if increm == 0:
        print("NOTE: INCREM is zero - this is a constrained-MD equilibration "
              "setup, not slow growth.")

    # 4. write ICONST
    n_controlled = len([l for l in (complexes if complexes else primitives)
                        if l.status == 0])
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_render_iconst_text(lines))
    print()
    print(f"Wrote {args.out} ({len(lines)} coordinate line(s), "
          f"{n_controlled} controlled parameter(s) -> {n_controlled} INCREM value(s))")
    if complexes:
        print("      Complex coordinate present: the status of every preceding "
              "primitive is ignored by VASP, so only the complex coordinate "
              "counts as controlled.")

    increm_values = [increm] * n_controlled

    # 5. optional two-stage INCARs
    if args.emit_incar:
        if not (args.template and args.incar_growth and args.incar_equil):
            _fail("--emit-incar requires --template, --incar-growth and "
                  "--incar-equil")
        text = _emit_stage_incars(args.template, args.incar_growth,
                                  args.incar_equil, increm_values)
        print(f"Wrote {args.incar_growth} (INCREM = {text}, LBLUEOUT = .TRUE.)")
        print(f"Wrote {args.incar_equil}  (INCREM commented out, LBLUEOUT = .FALSE.)")

    # 6. what the user still has to do
    print()
    print("NEXT STEPS")
    print("  1. Fill in system-specific parameters: ENCUT (>= 1.3 x max ENMAX), "
          "NBANDS (check POTCAR ZVAL), the AMIX/BMIX/AMIN trio for metal+water, "
          "NCORE, SMASS.")
    print("  2. Run the equilibration stage first, then restart the growth "
          "stage from its final geometry.")
    print("  3. Validate both stages:")
    validator = os.path.join(_HERE, "validate_input.py")
    growth_name = args.incar_growth or "INCAR_growth"
    equil_name = args.incar_equil or "INCAR_equil"
    for stage in (equil_name, growth_name):
        print(f"       python {validator} --incar {stage} "
              f"--poscar {args.poscar} --iconst {args.out} --task slowgrowth")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        description="ICONST / SG-AIMD helper: candidate atom tables and "
                    "ICONST + two-stage INCAR rendering.")
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("candidates",
                       help="list candidate atoms with real distances to an acceptor")
    c.add_argument("--poscar", required=True, help="POSCAR/CONTCAR to read")
    c.add_argument("--species", help="element symbol to enumerate, e.g. H")
    c.add_argument("--indices", nargs="+", type=int,
                   help="explicit 1-based atom indices instead of --species")
    c.add_argument("--acceptor", type=int,
                   help="1-based index of the acceptor atom to measure against")
    c.set_defaults(func=cmd_candidates)

    r = sub.add_parser("render",
                       help="verify the CV, compute INCREM, write ICONST and "
                            "optionally both stage INCARs")
    r.add_argument("--poscar", required=True, help="POSCAR/CONTCAR to read")
    r.add_argument("--cv", action="append", required=True, metavar="SPEC",
                   help="one coordinate per flag, e.g. --cv \"R 65 67\" "
                        "--cv \"R 69 67\" --cv \"S 1 -1\"; primitives first, "
                        "complex coordinates last")
    r.add_argument("--xi", type=float, required=True,
                   help="declared initial CV value (verified against POSCAR)")
    r.add_argument("--xf", type=float, required=True,
                   help="target final CV value")
    r.add_argument("--nsw", type=int, required=True,
                   help="number of MD steps the growth stage will run")
    r.add_argument("--potim", type=float,
                   help="MD timestep in fs; enables the per-ps rate report")
    r.add_argument("--out", default="ICONST", help="ICONST output path")
    r.add_argument("--emit-incar", action="store_true",
                   help="also derive both stage INCARs from --template")
    r.add_argument("--template", help="base_templates/vasp_slowgrowth.incar")
    r.add_argument("--incar-growth", help="growth-stage INCAR output path")
    r.add_argument("--incar-equil", help="equilibration-stage INCAR output path")
    r.set_defaults(func=cmd_render)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
