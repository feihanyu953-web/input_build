#!/usr/bin/env python3
"""
validate_input.py — deterministic validator for input-build generated inputs.

Implements the rules from SKILL.md's "Validation Rules" table as executable
checks, so a violation fails loudly instead of silently producing a bad
calculation. Covers VASP (INCAR + POSCAR + POTCAR + KPOINTS), CP2K (.inp
section tree + XYZ/PDB/inline coordinates), and LAMMPS (input scripts).

Usage:
    python validate_input.py --incar INCAR [--poscar POSCAR] [--potcar POTCAR]
                             [--kpoints KPOINTS] [--task TASK]
                             [--verified ENCUT=520,...] [--json]
    python validate_input.py --cp2k input.inp [--xyz coord.xyz] [--task TASK]
    python validate_input.py --lammps input.md [--data system.data] [--task TASK]
    python validate_input.py --kpoints KPOINTS        # standalone KPOINTS check
    python validate_input.py --examples-dir path/to/examples [--json]

Exit code: 1 if any ERROR-level finding, else 0. Text/JSON output separates
syntax, cross-parameter combination, and physics-convergence tiers. The static
validator always reports physics=NOT_EVALUATED; INFO-level findings (e.g.
user-verified downgrades, audit P2-04) never affect the exit code.
Stdlib only — no third-party dependencies.
"""

import argparse
import json
import math
import os
import re
import sys

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"

# Elements that strongly suggest spin polarization (SKILL.md auto-detection)
MAGNETIC_ELEMENTS = {"Fe", "Co", "Ni", "Mn", "Cr", "Ce", "U", "La"}

TASK_KEYWORDS = {
    "workfunction": "workfunction",
    "dielectric": "dielectric",
    "optics": "optics",
    "elf": "elf",
    "freq": "freq",
    "phonon": "phonon",
    "hirshfeld": "hirshfeld",
    "metadyn": "metadyn",
    "neb": "neb",
    "band": "band",
    "dos": "dos",
    "slowgrowth": "slowgrowth",
    "aimd": "md",
    "md": "md",
    "scf": "static",
    "_opt": "geo_opt",
    "min": "minimize",
    "relax": "relax",
    "dftu": "relax",
}


class Finding:
    def __init__(self, level, code, message):
        self.level = level
        self.code = code
        self.message = message

    def as_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message}

    def __str__(self):
        return f"[{self.level}] {self.code}: {self.message}"


SYNTAX_FAILURE_CODES = {
    "CP2K_BAND_HIERARCHY",
    "CP2K_MISPLACED_SECTION",
    "CP2K_PARSE",
    "CP2K_WF_DIPOLE_DIR_INVALID",
    "CP2K_WF_DIPOLE_VALUE_INVALID",
    "KPOINTS_COUNT_MISMATCH",
    "KPOINTS_MALFORMED",
    "LAMMPS_TIMESTEP_INVALID",
    "POSCAR_PARSE",
    "PDB_PARSE",
    "VASP_VALUE_UNPARSEABLE",
    "XYZ_PARSE",
}

SYNTAX_NOT_EVALUATED_CODES = {
    "KPOINTS_MISSING",
}


def validation_tiers(findings, incomplete=False):
    """Return the three validation layers without claiming runtime physics.

    The validator reads input files only. It can establish that supported
    syntax parsed and that deterministic cross-parameter rules passed, but it
    cannot establish that VASP/CP2K/LAMMPS ran or that a physical convergence
    study succeeded. That final tier therefore remains NOT_EVALUATED here and
    is reserved for runtime smoke/output checks outside this static validator.
    """
    codes = {x.code for x in findings}
    n_err = sum(1 for x in findings if x.level == ERROR)
    n_warn = sum(1 for x in findings if x.level == WARN)

    if codes & SYNTAX_FAILURE_CODES:
        syntax = "FAIL"
    elif codes & SYNTAX_NOT_EVALUATED_CODES:
        syntax = "NOT_EVALUATED"
    else:
        syntax = "PASS"

    if syntax != "PASS":
        combination = "BLOCKED"
    elif n_err:
        combination = "FAIL"
    elif incomplete:
        combination = "INCOMPLETE"
    elif n_warn:
        combination = "PASS_WITH_WARNINGS"
    else:
        combination = "PASS"

    if n_err:
        overall = "FAIL"
    elif incomplete:
        overall = "INCOMPLETE"
    else:
        overall = "STATIC_PASS"

    return {
        "overall": overall,
        "syntax": syntax,
        "combination": combination,
        "physics": "NOT_EVALUATED",
    }


# ---------------------------------------------------------------------------
# INCAR parsing
# ---------------------------------------------------------------------------

def parse_incar(path):
    """Parse INCAR into {KEY: [tokens]}. Strips ! and # comments."""
    params = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(("#", "!")):
                continue
            for mark in ("!", "#"):
                idx = line.find(mark)
                if idx != -1:
                    line = line[:idx]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().upper()
            if key:
                params[key] = value.split()
    return params


def _num(token):
    try:
        value = float(token.replace("D", "e").replace("d", "e"))
    except (ValueError, AttributeError):
        return None
    return value if math.isfinite(value) else None


def get_float(params, key, default=None):
    toks = params.get(key)
    if not toks:
        return default
    v = _num(toks[0])
    return default if v is None else v


def get_int(params, key, default=None):
    v = get_float(params, key, None)
    return default if v is None else int(round(v))


def get_bool(params, key, default=False):
    toks = params.get(key)
    if not toks:
        return default
    t = toks[0].strip().upper().strip(".")
    if t in ("TRUE", "T"):
        return True
    if t in ("FALSE", "F"):
        return False
    return default


def get_num_list(params, key):
    out = []
    for tok in params.get(key, []):
        v = _num(tok)
        if v is not None:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# POSCAR parsing
# ---------------------------------------------------------------------------

class Structure:
    def __init__(self, lattice, elements, counts, frac):
        self.lattice = lattice          # 3x3, Angstrom
        self.elements = elements        # list[str] or None (VASP4)
        self.counts = counts
        self.frac = frac                # fractional coords

    @property
    def natoms(self):
        return sum(self.counts)

    @property
    def has_h(self):
        return bool(self.elements) and "H" in self.elements

    @property
    def magnetic_present(self):
        return bool(self.elements) and bool(set(self.elements) & MAGNETIC_ELEMENTS)

    @property
    def has_oxygen(self):
        return bool(self.elements) and "O" in self.elements

    def vacuum_axes(self, min_vacuum=5.0):
        """Axes ('a'/'b'/'c') along which a vacuum gap >= min_vacuum exists.

        Fractional coordinates are periodic, so the vacuum is the largest gap
        between adjacent sorted coordinates, including the wrap-around gap.
        Valid for slabs whose normal aligns with a lattice vector.
        """
        axes = []
        if not self.frac:
            return axes
        for i, name in enumerate(("a", "b", "c")):
            col = sorted(p[i] % 1.0 for p in self.frac)
            gaps = [col[j + 1] - col[j] for j in range(len(col) - 1)]
            gaps.append(col[0] + 1.0 - col[-1])
            vac = max(gaps) * _norm(self.lattice[i])
            if vac >= min_vacuum:
                axes.append(name)
        return axes

    def vacuum_gaps(self):
        """Largest periodic gap per axis in Angstrom: {'a': 14.2, 'c': 0.3, ...}."""
        out = {}
        if not self.frac:
            return out
        for i, name in enumerate(("a", "b", "c")):
            col = sorted(p[i] % 1.0 for p in self.frac)
            gaps = [col[j + 1] - col[j] for j in range(len(col) - 1)]
            gaps.append(col[0] + 1.0 - col[-1])
            out[name] = max(gaps) * _norm(self.lattice[i])
        return out


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _cross(u, v):
    return [u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0]]


def _cart_to_frac(coords, lattice):
    # r = f . L  =>  f_i = r . (a_j x a_k) / V   (reciprocal-lattice identity)
    a, b, c = lattice
    vol = _det3(lattice)
    bxc, cxa, axb = _cross(b, c), _cross(c, a), _cross(a, b)
    out = []
    for r in coords:
        out.append([
            sum(r[j] * bxc[j] for j in range(3)) / vol,
            sum(r[j] * cxa[j] for j in range(3)) / vol,
            sum(r[j] * axb[j] for j in range(3)) / vol,
        ])
    return out


def parse_poscar(path):
    """Parse POSCAR/CONTCAR. Returns Structure. Raises ValueError on malformed input."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [l.rstrip() for l in f if l.strip()]
    if len(lines) < 8:
        raise ValueError(f"POSCAR too short: {path}")

    try:
        scales = [float(x) for x in lines[1].split()]
    except ValueError as exc:
        raise ValueError(
            f"POSCAR line 2 scaling factor is not numeric in {path}") from exc
    if any(not math.isfinite(x) for x in scales):
        raise ValueError("POSCAR scaling factors must be finite")
    if len(scales) not in (1, 3):
        raise ValueError(
            f"POSCAR line 2 must contain 1 or 3 scaling factors, got {len(scales)}")
    if len(scales) == 3 and any(x <= 0 for x in scales):
        raise ValueError("POSCAR three scaling factors must all be positive")
    if len(scales) == 1 and scales[0] == 0:
        raise ValueError("POSCAR scaling factor must not be zero")
    raw = [[float(x) for x in lines[i].split()[:3]] for i in (2, 3, 4)]
    if len(scales) == 1 and scales[0] < 0:  # negative scale = target volume
        v0 = abs(_det3(raw))
        if v0 == 0:
            raise ValueError(f"Zero-volume cell in {path}")
        factor = (-scales[0] / v0) ** (1.0 / 3.0)
        factors = (factor, factor, factor)
    elif len(scales) == 1:
        factors = (scales[0], scales[0], scales[0])
    else:
        factors = tuple(scales)
    lattice = [[x * factors[j] for j, x in enumerate(vec)] for vec in raw]

    idx = 5
    tokens = lines[idx].split()
    if all(re.fullmatch(r"-?\d+", t) for t in tokens):  # VASP4: counts only
        elements, counts = None, [int(t) for t in tokens]
        idx += 1
    else:  # VASP5: elements then counts
        elements = tokens
        idx += 1
        counts = [int(t) for t in lines[idx].split()]
        idx += 1

    if lines[idx].strip().lower().startswith("s"):  # Selective dynamics
        idx += 1
    cartesian = lines[idx].strip().lower().startswith(("c", "k"))
    idx += 1

    natoms = sum(counts)
    coords = []
    for i in range(idx, idx + natoms):
        coords.append([float(x) for x in lines[i].split()[:3]])
    if cartesian:
        coords = [[c * factors[j] for j, c in enumerate(p)] for p in coords]
        frac = _cart_to_frac(coords, lattice)
    else:
        frac = coords
    return Structure(lattice, elements, counts, frac)


# ---------------------------------------------------------------------------
# POTCAR / KPOINTS parsing
# ---------------------------------------------------------------------------

def parse_potcar_max_enmax(path):
    """Return max ENMAX across all species in a (possibly concatenated) POTCAR."""
    vals = [float(m.group(1))
            for m in re.finditer(r"ENMAX\s*=\s*([0-9.]+)", open(path, encoding="utf-8", errors="replace").read())]
    return max(vals) if vals else None


def is_linemode_kpoints(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [l.strip() for l in f if l.strip()]
    return len(lines) >= 3 and lines[2].lower().startswith("li")


def parse_kpoints_mesh_declaration(value):
    """Return a canonical automatic-mesh tuple from ``NxNxN``/``N N N``.

    ``None`` means the declaration is not a positive three-integer mesh.
    """
    parts = re.sub(r"[xX,]", " ", str(value)).split()
    if len(parts) != 3 or not all(re.fullmatch(r"\d+", x) for x in parts):
        return None
    mesh = tuple(int(x) for x in parts)
    return mesh if all(x > 0 for x in mesh) else None


def read_automatic_kpoints_mesh(path):
    """Return ``(nx, ny, nz)`` for a well-formed automatic KPOINTS file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]
        if len(lines) < 4 or int(lines[1].split()[0]) != 0:
            return None
        return parse_kpoints_mesh_declaration(" ".join(lines[3].split()[:3]))
    except (OSError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Task inference
# ---------------------------------------------------------------------------

def infer_task(params):
    if get_bool(params, "LOPTICS"):
        return "optics"
    if get_bool(params, "LEPSILON"):
        return "dielectric"
    if get_bool(params, "LELF"):
        return "elf"
    # Slow growth before the generic MD branch: an SG INCAR carries INCREM
    # and/or LBLUEOUT on top of IBRION=0, and must not be treated as plain MD
    # (that would silently disable every SG rule when --iconst is forgotten).
    if "INCREM" in params or "LBLUEOUT" in params:
        return "slowgrowth"
    if get_int(params, "IBRION", -1) == 0:
        return "md"
    if get_int(params, "IBRION", -1) in (5, 6, 7, 8):
        return "freq"
    if get_int(params, "IMAGES", 0) > 0:
        return "neb"
    if get_int(params, "NSW", 0) == 0 or get_int(params, "IBRION", -1) == -1:
        return "static"
    return "relax"


# ---------------------------------------------------------------------------
# Validation rules (mirror of SKILL.md "Validation Rules" table)
# ---------------------------------------------------------------------------

def validate(params, structure=None, max_enmax=None, linemode=False, task_override=None,
             dftu_control=False, iconst=None, iconst_requested=False):
    # dftu_control=True exempts the zero-U placeholder guard (audit P1-VASP-07);
    # set via --task dftu-control or a '# control calculation' comment in INCAR.
    # iconst: parsed iconst.IconstFile or None (context absent).
    # iconst_requested: True when the caller explicitly asked for the
    # slowgrowth task (--task slowgrowth), which turns a missing ICONST from
    # INCOMPLETE context into a hard ERROR. See Task 4.
    f = []
    add = lambda level, code, msg: f.append(Finding(level, code, msg))

    task = task_override or infer_task(params)
    elements = structure.elements if structure else None
    has_h = structure.has_h if structure else False
    vacuum = structure.vacuum_axes() if structure else []

    # Scalar values used by the rules must be finite. Rejecting NaN/Inf here
    # prevents comparisons from silently evaluating false and avoids crashes in
    # integer task-inference paths.
    scalar_keys = (
        "EDIFF", "ENCUT", "POTIM", "IBRION", "ICHARG", "IDIPOL", "IMAGES",
        "ISMEAR", "ISPIN", "ISYM", "IVDW", "LMAXMIX", "NELM", "NELMIN",
        "NPAR", "NSW",
    )
    for key in scalar_keys:
        tokens = params.get(key)
        if tokens and _num(tokens[0]) is None:
            add(ERROR, "VASP_VALUE_UNPARSEABLE",
                f"{key} value {tokens[0]!r} is not a finite scalar number")

    # --- Dipole logic ---
    has_idipol = "IDIPOL" in params
    if structure:
        if bool(vacuum) != has_idipol:
            if vacuum and not has_idipol:
                if set(vacuum) == {"a", "b", "c"}:
                    add(WARN, "DIPOLE_MISSING",
                        "Three-direction vacuum suggests an isolated molecule, but "
                        "no IDIPOL/LDIPOL dipole correction is set. Use IDIPOL=4 "
                        "when the total dipole is non-negligible; omit it only with "
                        "evidence that the net total dipole is negligible")
                else:
                    add(WARN, "DIPOLE_MISSING",
                        f"Vacuum gap detected along {vacuum} but no IDIPOL/LDIPOL "
                        "dipole correction. Asymmetric/polar slabs require it; omit "
                        "it only with evidence that the two surfaces are symmetric "
                        "and the net dipole along the surface normal is negligible")
            elif has_idipol and not vacuum:
                add(WARN, "DIPOLE_WITHOUT_VACUUM",
                    "IDIPOL set but no vacuum gap > 5 A detected in POSCAR")
    if has_idipol and not get_bool(params, "LDIPOL"):
        add(ERROR, "DIPOLE_WITHOUT_LDIPOL",
            "IDIPOL is set but LDIPOL=.TRUE. is missing (dipole correction inactive)")
    idipol = get_int(params, "IDIPOL", 3) if has_idipol else None
    if has_idipol and idipol == 4 and task == "workfunction":
        add(WARN, "IDIPOL4_NONMOLECULAR",
            "IDIPOL=4 applies the full three-direction correction and is "
            "intended for isolated molecules; a workfunction task is slab-specific. "
            "Use IDIPOL=1/2/3 along the surface-normal lattice vector")
    elif has_idipol and structure and vacuum:
        idipol_axis = {1: "a", 2: "b", 3: "c"}.get(idipol)
        if idipol == 4 and set(vacuum) != {"a", "b", "c"}:
            add(WARN, "IDIPOL4_NONMOLECULAR",
                f"IDIPOL=4 applies the full three-direction correction and is "
                f"intended for isolated molecules; this input is slab/wire-like "
                f"(vacuum axes {vacuum}, task={task}). Use IDIPOL=1/2/3 along "
                "the surface-normal lattice vector")
        elif idipol_axis and idipol_axis not in vacuum:
            add(WARN, "DIPOLE_AXIS_MISMATCH",
                f"IDIPOL={idipol} corrects along lattice vector "
                f"'{idipol_axis}' but the vacuum gap is along {vacuum}; set IDIPOL to "
                "the surface-normal vector (1=a, 2=b, 3=c; 4=all directions)")

    # --- Magnetic consistency ---
    if structure and structure.magnetic_present and get_int(params, "ISPIN", 1) != 2:
        mag = sorted(set(elements) & MAGNETIC_ELEMENTS)
        add(WARN, "MAGNETIC_ELEMENTS_ISP1",
            f"{mag} present but ISPIN != 2; confirm spin treatment with the user")

    # --- ENCUT coverage ---
    encut = get_float(params, "ENCUT")
    if max_enmax is not None and encut is not None:
        if encut < 1.3 * max_enmax:
            add(WARN, "ENCUT_BELOW_1P3_ENMAX",
                f"ENCUT={encut:g} < 1.3 x max ENMAX ({max_enmax:g}); "
                f"use >= {math.ceil(1.3 * max_enmax)} for final energies")
    elif encut is not None:
        add(WARN, "ENCUT_NOT_VERIFIED",
            "No POTCAR provided; ENCUT coverage vs ENMAX unresolved (pass --potcar to verify)")
    if structure and structure.has_oxygen and task in ("relax", "md", "slowgrowth"):
        if encut is not None and encut < 450:
            add(WARN, "OXIDE_ENCUT_LOW",
                f"O-containing system with ENCUT={encut:g} < 450; 520+ recommended for final energies")

    # --- Smearing (task-aware; see SKILL.md red flags) ---
    ismear = get_int(params, "ISMEAR")
    if ismear == -5:
        if linemode:
            add(ERROR, "TETRA_ON_LINEMODE",
                "ISMEAR=-5 (tetrahedron) on line-mode KPOINTS; tetrahedron needs an automatic mesh")
        if task in ("relax", "md"):
            add(WARN, "TETRA_ON_RELAX",
                "ISMEAR=-5 during relax/MD can cause trouble (no entropy term, bad with ISIF=3); "
                "use ISMEAR=0 with small SIGMA")

    # --- KPOINTS mode vs task --------------------------------------------
    # Observed 2026-10 on 6.4.2: VASP aborts a frequency run fed line-mode
    # KPOINTS with "requires a uniform k mesh ... I REFUSE TO CONTINUE WITH
    # THIS SICK JOB"; finite-difference displacements need a uniform BZ mesh.
    # A line-mode path is legitimate ONLY for the band non-self-consistent
    # step (ICHARG=11); on any other task it is almost always band KPOINTS
    # left in the wrong folder.
    if linemode:
        if task == "freq":
            add(ERROR, "FREQ_ON_LINEMODE",
                "IBRION=5/6/7/8 frequency calculation on line-mode KPOINTS; "
                "finite-difference displacements require a uniform mesh spanning "
                "the entire BZ (VASP aborts: 'I REFUSE TO CONTINUE'). Use a "
                "Gamma-centered uniform mesh")
        elif task in ("static", "relax") and get_int(params, "ICHARG", 2) != 11:
            add(WARN, "STATIC_ON_LINEMODE",
                "line-mode KPOINTS on a plain static/relax task (ICHARG != 11); "
                "this is usually band-path KPOINTS left in the wrong folder. A "
                "non-self-consistent band run must set ICHARG=11; plain SCF on "
                "a k-path is rarely intended")

    # --- Band non-SCF memory budget ---------------------------------------
    # Observed 2026-10 on 6.4.2 (Janus MoSSe 4x4, 30 A vacuum box): four
    # consecutive OOM kills on 125 GB nodes. ICHARG=11 runs allocate the
    # full-FFT-grid wavefunction projection buffer of ALL bands REPLICATED on
    # EVERY MPI rank -- per-rank RSS ~= NPLWV x NBANDS x 16 bytes (measured
    # 870912 x 280 x 16 = 3.87 GB/rank). The total does NOT shrink with rank
    # count, so reducing ranks never fixes it; cut NBANDS/ISPIN/grid instead.
    if get_int(params, "ICHARG", 2) == 11 and structure:
        encut = get_int(params, "ENCUT", 400) or 400
        # VASP default FFT grid: N_i ~= L_i * sqrt(ENCUT) / 4 (calibrated on
        # 6.4.2: 13 A @ 500 eV -> 72, 30 A @ 500 eV -> 168; both within ~2%)
        nplwv = 1
        for v in structure.lattice:
            nplwv *= max(int(_norm(v) * (encut ** 0.5) / 4.0), 1)
        ispin = get_int(params, "ISPIN", 1)
        nbands_est = get_int(params, "NBANDS", 0) or int(
            structure.natoms * (5.7 if ispin == 2 else 5.2))
        mb = nplwv * nbands_est * 16 / (1024 * 1024)
        if mb > 2000:
            add(WARN, "BAND_MEMORY_HEAVY",
                f"ICHARG=11 band run estimated at ~{mb:.0f} MB per MPI rank "
                f"(NPLWV~{nplwv} x NBANDS~{nbands_est} x 16 B), and this buffer "
                f"is REPLICATED on every rank (total ~ranks x {mb:.0f} MB; "
                f"28 ranks ~{28 * mb / 1024:.0f} GB) -- OOM risk. Remedies: "
                "ISPIN=1 for non-magnetic systems, NBANDS = occupied + 30-40 "
                "(a band plot needs few conduction bands), no ADDGRID, and a "
                "modest rank count")
        if get_bool(params, "ADDGRID"):
            add(WARN, "ADDGRID_ON_BAND",
                "ADDGRID on a band run adds a large support-grid memory "
                "footprint with no eigenvalue benefit (it exists for force "
                "accuracy); eigenvalues are unchanged without it")

    # --- Slow-growth AIMD (SG-AIMD) -------------------------------------
    # Official semantics: ICONST defines the collective variable (STATUS=0 =
    # constrained), INCREM grows each controlled parameter every MD step and
    # requires MDALGO=1|2, LBLUEOUT=.TRUE. writes the free-energy gradient to
    # REPORT, per the VASP manual (the detailed design spec lives outside this skill).
    if task == "slowgrowth":
        # get_num_list already drops unparseable tokens, so every element is a
        # finite number here.
        increm = get_num_list(params, "INCREM")
        has_increm_tag = "INCREM" in params
        n_tokens = len(params.get("INCREM", []))
        # get_num_list silently drops unparseable tokens; fail loudly instead,
        # because INCREM drives both the stage diagnosis and the arity rule.
        unparseable = has_increm_tag and len(increm) != n_tokens
        if unparseable:
            add(ERROR, "SG_INCREM_UNPARSEABLE",
                f"INCREM has {n_tokens} token(s) but only {len(increm)} "
                f"parsed as finite numbers: {params.get('INCREM')}. Check for "
                "stray commas (use spaces: INCREM = v1 v2 ...) or typos")
        # Growth stage = at least one non-zero increment. INCREM defaults to 0,
        # so an absent/zero tag is the equilibration stage (constrained MD).
        growing = (not unparseable) and any(v != 0.0 for v in increm)

        if iconst is None:
            if iconst_requested:
                add(ERROR, "SG_ICONST_MISSING",
                    "task=slowgrowth was requested but no readable ICONST "
                    "context is available (--iconst missing or unreadable): "
                    "the collective variable cannot be checked. Slow growth "
                    "is meaningless without ICONST")
            else:
                add(WARN, "SG_ICONST_CONTEXT_MISSING",
                    "INCREM/LBLUEOUT indicate slow growth but no ICONST "
                    "context was provided (--iconst): CV, INCREM arity and "
                    "atom-index checks are skipped")
        else:
            # Surface parser issues under SG_* codes.
            for issue in iconst.issues:
                code = issue["code"]
                if code in ("ICONST_FLAG_COVERAGE", "ICONST_STATUS_COVERAGE"):
                    add(WARN, "SG_" + code, issue["message"])
                elif code == "ICONST_COMMENT_UNSUPPORTED":
                    add(WARN, "SG_ICONST_COMMENT", issue["message"])
                elif code in ("ICONST_ARITY", "ICONST_ORDER",
                              "ICONST_STATUS_INVALID", "ICONST_FLAG_UNKNOWN",
                              "ICONST_EMPTY", "ICONST_UNREADABLE"):
                    add(ERROR, "SG_ICONST_ARITY", issue["message"])
                else:
                    add(issue["level"], "SG_" + code, issue["message"])

            if get_int(params, "IBRION", -1) != 0:
                add(ERROR, "SG_IBRION_NOT_MD",
                    "ICONST is only read for molecular dynamics (IBRION=0); "
                    f"IBRION={get_int(params, 'IBRION', -1)} means the "
                    "constraints are silently ignored")

            # Atom-index range needs the structure; without POSCAR it is skipped.
            if structure:
                mod = _load_iconst_module()
                for line in iconst.lines:
                    n_idx = mod.ATOM_INDEX_ARITY.get(line.flag, 0)
                    for idx in line.items[:n_idx]:
                        if (not isinstance(idx, int) or idx < 1
                                or idx > structure.natoms):
                            add(ERROR, "SG_ICONST_INDEX_RANGE",
                                f"ICONST line {line.lineno}: atom index {idx} "
                                f"is outside 1..{structure.natoms} "
                                "(POSCAR atom count)")

            n_controlled = iconst.n_controlled()
            if growing and n_controlled == 0:
                add(ERROR, "SG_NO_CONTROLLED_COORD",
                    "a non-zero INCREM was given but ICONST defines no "
                    "STATUS=0 coordinate: the increment has nothing to act on "
                    "and the run produces a plain MD trajectory")
            if has_increm_tag and increm and n_controlled and len(increm) != n_controlled:
                add(ERROR, "SG_INCREM_ARITY",
                    f"INCREM has {len(increm)} value(s) but ICONST defines "
                    f"{n_controlled} controlled parameter(s). One value is "
                    "required per STATUS=0 parameter. Note: when a complex "
                    "coordinate (S/C/D) is present the status of every "
                    "preceding primitive is ignored, so only the complex "
                    "coordinates count")

        # These three do not need the ICONST context.
        mdalgo = get_int(params, "MDALGO")
        if mdalgo is None:
            add(WARN, "SG_MDALGO_UNSET",
                "MDALGO unset for a slow-growth run: INCREM is only honoured "
                "for MDALGO=1 (Andersen) or 2 (Nose-Hoover), and the "
                "deprecated default also wraps coordinates into the cell")
        elif mdalgo not in (1, 2):
            hint = (" MDALGO=3 is the Langevin thermostat, which the "
                    "slow-growth route does not support"
                    if mdalgo == 3 else "")
            add(ERROR, "SG_MDALGO_UNSUPPORTED",
                f"MDALGO={mdalgo} cannot drive slow growth: INCREM is only "
                f"honoured for MDALGO=1 (Andersen) or 2 (Nose-Hoover).{hint}")

        if growing:
            if not get_bool(params, "LBLUEOUT"):
                add(ERROR, "SG_LBLUEOUT_MISSING",
                    "growth stage (non-zero INCREM) without LBLUEOUT=.TRUE.: "
                    "REPORT will not carry the free-energy gradient, so the "
                    "thermodynamic integration cannot be done afterwards")
        elif has_increm_tag and not unparseable:
            # Only an explicit INCREM=0 declares an equilibration stage. A
            # template whose INCREM is still a commented placeholder must not
            # collect either finding, or the standalone template check in
            # test_template_index.py starts reporting noise.
            add(WARN, "SG_INCREM_ALL_ZERO",
                "every INCREM component is zero: this is a constrained-MD "
                "equilibration run, not slow growth (INCREM defaults to 0). "
                "Intended for the equilibration stage; set a non-zero "
                "INCREM for the growth stage")
            if get_bool(params, "LBLUEOUT"):
                add(INFO, "SG_LBLUEOUT_EQUIL",
                    "LBLUEOUT=.TRUE. on an equilibration stage (zero INCREM) is "
                    "harmless but writes gradient data that will not be "
                    "integrated; it can be switched off")

    # --- MD timestep ---
    # slowgrowth is an MD run with a growing constraint: the whole interface-
    # AIMD rule family (timestep, ISYM, ISIF, NCORE, vacuum sloshing, mixing
    # trio, NBANDS drift) applies unchanged.
    if task in ("md", "slowgrowth"):
        potim = get_float(params, "POTIM")
        cap = 1.0 if has_h else 2.0
        if potim is not None and potim > cap:
            add(ERROR, "MD_TIMESTEP_CAP",
                f"POTIM={potim:g} fs exceeds the {cap:g} fs cap "
                f"({'H present' if has_h else 'no H'}); reduce the MD timestep")
        if get_int(params, "ISYM", 2) not in (0,):
            add(WARN, "MD_ISYM",
                "ISYM should be 0 for MD (symmetry is meaningless at finite temperature)")

        # ISIF=2 computes a full stress tensor every MD step; NVT MD needs none
        # (VASP defaults to ISIF=0 when IBRION=0). Observed 2026-09: template
        # value ISIF=2 carried from relax semantics wasted 10-20% per step.
        if get_int(params, "ISIF", 0) == 2:
            add(WARN, "MD_ISIF_STRESS",
                "ISIF=2 computes the stress tensor at every MD step; fixed-cell "
                "NVT MD needs none (VASP defaults to ISIF=0 for IBRION=0). "
                "Remove ISIF unless monitoring pressure is intended")

        # NCORE unset defaults to 1 — grossly inefficient on multi-core nodes
        # (measured 2026-09: 410 s/step vs 10-16 s/step with NCORE=8 on 64 cores)
        if "NCORE" not in params and "NPAR" not in params:
            add(WARN, "MD_NCORE_UNSET",
                "NCORE/NPAR unset: VASP defaults to NCORE=1, which is grossly "
                "inefficient on modern nodes (VASP itself warns in OUTCAR). "
                "Set NCORE=4-8 (tested on 56-64 core nodes)")

        # Long vacuum + slab AIMD: charge sloshing. Measured 2026-09 on
        # Pt(100)/water: total periodic vacuum gap 25 A -> SCF never converges
        # (200+ iters/step); 15-17 A -> 9-11 iters/step. Long-wavelength
        # density modes mix slowly. NOTE: the gap is periodic — top and bottom
        # vacuum combine into one continuous region across the cell boundary.
        if structure:
            gaps = structure.vacuum_gaps()
            long_vac = {ax: g for ax, g in gaps.items() if g > 18.0}
            if long_vac and get_bool(params, "LDIPOL"):
                vac_desc = ", ".join("{}={:.1f}".format(ax, g)
                                     for ax, g in sorted(long_vac.items()))
                add(WARN, "MD_VACUUM_SLOSHING",
                    "AIMD/slow-growth on a slab with total periodic vacuum > 18 A ({}; top+"
                    "bottom vacuum combine across the cell boundary): long "
                    "vacuum breeds charge sloshing — SCF can stall at 100-200 "
                    "iterations/step. Locally verified converging range is "
                    "15-17 A total; consider trimming the vacuum".format(vac_desc))

        # Metal slab + explicit solvent (O and H present + vacuum) with default
        # mixing AMIX=0.4 diverges. Locally verified trio: AMIX=0.02 BMIX=1.0
        # AMIN=0.01. Do not swap in BMIX=0.01 (static two-step SCF prescription).
        if (structure and vacuum and structure.has_oxygen and has_h
                and "AMIX" not in params):
            add(WARN, "MD_MIXING_METAL_WATER",
                "Metal slab + explicit water/ions detected with default charge "
                "mixing (AMIX=0.4): this combination charge-sloshes and diverges. "
                "Add the verified trio AMIX=0.02, BMIX=1.0, AMIN=0.01 "
                "(BMIX=0.01 belongs to static two-step SCF, not AIMD)")

        # NBANDS auto value drifts with VASP version/binary/PAW variant;
        # slab AIMD should pin it (Pt ZVAL=10 vs Pt_pv 16 shifts occupied
        # bands by ~100). Vasp_gam additionally rounds NBANDS up for band groups.
        if structure and vacuum and "NBANDS" not in params:
            add(WARN, "MD_NBANDS_DRIFT",
                "NBANDS unset for a slab AIMD/slow-growth run: the auto value drifts with "
                "VASP version, binary (std vs gam) and PAW variant (e.g. Pt "
                "ZVAL=10 vs Pt_pv 16 changes occupied bands by ~100). Pin "
                "NBANDS ~= 1.2-1.4 x occupied bands after checking POTCAR ZVAL")

    # --- CG POTIM for adsorbates on slabs ---
    if (task == "relax" and get_int(params, "IBRION") == 2 and structure
            and has_h and vacuum):
        potim = get_float(params, "POTIM")
        if potim is not None and potim > 0.3:
            add(WARN, "CG_POTIM_ADSORBATE",
                f"H-containing slab with IBRION=2 and POTIM={potim:g} > 0.3; "
                "reduce to <= 0.3 (0.2 for complex oxides)")

    # --- Finite-difference frequencies need NSW >= 1 (audit P0-02) ---
    if get_int(params, "IBRION") in (5, 6) and get_int(params, "NSW", 0) < 1:
        add(ERROR, "FREQ_MISSING_NSW",
            f"IBRION={get_int(params, 'IBRION')} (finite-difference phonons/frequencies) "
            "requires NSW >= 1 (typically NSW = 1); without it VASP runs only a static SCF "
            "and never enters the displacement/Hessian loop "
            "(vasp.at/wiki/Phonons_from_finite_differences)")

    # --- RANDOM_SEED arity (audit P1-VASP-01): VASP 6.x takes three integers ---
    if "RANDOM_SEED" in params:
        seeds = params["RANDOM_SEED"]
        if len(seeds) == 1:
            add(WARN, "RANDOM_SEED_COUNT",
                "RANDOM_SEED with a single integer is the pre-6.0 form; VASP 6.x requires "
                "three integers, e.g. RANDOM_SEED = 248489752 0 0 "
                "(vasp.at/wiki/RANDOM_SEED)")
        elif len(seeds) != 3:
            add(WARN, "RANDOM_SEED_COUNT",
                f"RANDOM_SEED has {len(seeds)} value(s); VASP 6.x expects exactly 3 "
                "integers (vasp.at/wiki/RANDOM_SEED)")

    # --- LANGEVIN_GAMMA must give one friction coefficient per species (P1-VASP-02) ---
    if "LANGEVIN_GAMMA" in params and structure and structure.elements:
        gammas = get_num_list(params, "LANGEVIN_GAMMA")
        if gammas and len(gammas) != len(structure.elements):
            add(WARN, "LANGEVIN_GAMMA_COUNT",
                f"LANGEVIN_GAMMA has {len(gammas)} value(s) but POSCAR has "
                f"{len(structure.elements)} species ({', '.join(structure.elements)}); "
                "VASP expects one friction coefficient per NTYP species "
                "(vasp.at/wiki/LANGEVIN_GAMMA)")

    # --- DFT+U completeness and LMAXMIX ---
    if get_bool(params, "LDAU"):
        fixed_density = get_int(params, "ICHARG", 2) == 11
        missing = [k for k in ("LDAUTYPE", "LDAUL", "LDAUU", "LDAUJ") if k not in params]
        if missing:
            add(ERROR, "DFTU_INCOMPLETE",
                f"LDAU=.TRUE. but missing: {', '.join(missing)}")
        if "LMAXMIX" not in params:
            level = ERROR if fixed_density else WARN
            context = ("required for the ICHARG=11 fixed-density CHGCAR path"
                       if fixed_density else
                       "recommended so CHGCAR restart/post-processing preserves the "
                       "on-site occupancy matrix")
            add(level, "DFTU_MISSING_LMAXMIX",
                "LDAU=.TRUE. has no LMAXMIX (use 4 for d-electrons, 6 for "
                f"f-electrons); it is {context} (VASP wiki: LMAXMIX)")
        else:
            lmaxmix = get_int(params, "LMAXMIX", 2)
            ldaul = get_num_list(params, "LDAUL")
            if 3 in ldaul and lmaxmix != 6:
                add(ERROR if fixed_density else WARN, "LMAXMIX_F_MISMATCH",
                    f"LDAUL contains 3 (f-electrons) but LMAXMIX={lmaxmix}; "
                    "use 6" + (" for ICHARG=11" if fixed_density else ""))
            elif 2 in ldaul and lmaxmix < 4:
                add(ERROR if fixed_density else WARN, "LMAXMIX_D_MISMATCH",
                    f"LDAUL contains 2 (d-electrons) but LMAXMIX={lmaxmix}; "
                    "use >= 4" + (" for ICHARG=11" if fixed_density else ""))
        if elements:
            for k in ("LDAUL", "LDAUU", "LDAUJ"):
                vals = get_num_list(params, k)
                if vals and len(vals) != len(elements):
                    add(ERROR, "DFTU_COUNT_MISMATCH",
                        f"{k} has {len(vals)} values but POSCAR has {len(elements)} element types "
                        f"({', '.join(elements)}); values must be per-element in POSCAR order")
        # Zero-U placeholder guard (audit P1-VASP-07 / 10.3): LDAU=.TRUE. with no
        # orbital actually corrected is a pseudo-configuration, not a DFT+U input.
        if not dftu_control:
            ldaul_vals = get_num_list(params, "LDAUL")
            ldauu_vals = get_num_list(params, "LDAUU")
            ldauj_vals = get_num_list(params, "LDAUJ")
            if ldaul_vals and all(v == -1 for v in ldaul_vals):
                add(ERROR, "DFTU_ZERO_U",
                    "LDAU=.TRUE. but every LDAUL = -1: no orbital receives a U correction, "
                    "so this INCAR is not a DFT+U calculation. Set per-species "
                    "LDAUL/LDAUU/LDAUJ, or explicitly declare a control calculation "
                    "('# control calculation' comment in INCAR, or --task dftu-control)")
            elif ldauu_vals:
                ueff = [u - (ldauj_vals[i] if i < len(ldauj_vals) else 0.0)
                        for i, u in enumerate(ldauu_vals)]
                if all(abs(x) < 1.0e-8 for x in ueff):
                    add(ERROR, "DFTU_ZERO_U",
                        "LDAU=.TRUE. but every effective U (LDAUU - LDAUJ) is 0 eV: the U "
                        "correction is a no-op placeholder. Set real U values, or "
                        "explicitly declare a control calculation ('# control calculation' "
                        "comment in INCAR, or --task dftu-control)")
        nelm = get_int(params, "NELM")
        if nelm is not None and nelm < 80:
            add(WARN, "DFTU_NELM_LOW",
                f"DFT+U with NELM={nelm} < 80; U-corrected SCF often needs more iterations")

    # --- Dispersion sanity (regression guard: D3BJ is IVDW=12, not 11) ---
    ivdw = get_int(params, "IVDW")
    if ivdw == 11:
        add(WARN, "IVDW_ZERO_DAMPING",
            "IVDW=11 is DFT-D3 with ZERO damping; if you intended D3(BJ), use IVDW=12")

    # --- ELF ---
    if get_bool(params, "LELF") and get_int(params, "NPAR", 1) != 1:
        add(ERROR, "ELF_NPAR",
            "LELF=.TRUE. requires NPAR=1 (ELF is wrong with band parallelization)")
    if task == "elf" and not get_bool(params, "LELF"):
        add(ERROR, "ELF_MISSING_LELF",
            "elf task requires LELF=.TRUE. to compute and write ELFCAR "
            "(SKILL.md validation rules; vasp.at/wiki/LELF)")

    # --- Work function ---
    if task == "workfunction":
        if not (get_bool(params, "LVHAR") or get_bool(params, "LVTOT")):
            add(ERROR, "WF_NO_OUTPUT",
                "workfunction task requires LVHAR=.TRUE. (VASP 6+) or LVTOT=.TRUE. to write LOCPOT")
    # Decoupled from the task name: any INCAR writing LOCPOT for WF extraction on a
    # slab should carry a dipole correction — fires even without a task/filename hint.
    if (get_bool(params, "LVHAR") or get_bool(params, "LVTOT")) and vacuum and not has_idipol:
        add(WARN, "WF_NO_DIPOLE",
            "slab work function (LVHAR/LVTOT set) without dipole correction; "
            "IDIPOL/LDIPOL recommended")

    # --- Optics / dielectric ---
    if get_bool(params, "LEPSILON") and get_bool(params, "LOPTICS"):
        add(ERROR, "LEPSILON_LOPTICS_CONFLICT",
            "LEPSILON and LOPTICS must not be combined in one INCAR (VASP wiki: LEPSILON)")
    if get_bool(params, "LOPTICS") and "NBANDS" not in params:
        add(WARN, "OPTICS_NBANDS",
            "LOPTICS without explicit NBANDS; boost empty bands (~2-3x default)")
    if task == "dielectric" and not get_bool(params, "LEPSILON"):
        add(ERROR, "DIELECTRIC_NO_LEPSILON",
            "dielectric task requires LEPSILON=.TRUE.")

    # --- Spin-orbit coupling ---
    if get_bool(params, "LSORBIT") and "NBANDS" not in params:
        add(WARN, "SOC_NBANDS",
            "LSORBIT=.TRUE. (non-collinear) roughly doubles the number of bands; "
            "set NBANDS explicitly (~2x the scalar-relativistic value)")

    # --- meta-GGA (r2SCAN/SCAN) ---
    if "METAGGA" in params:
        if not get_bool(params, "LASPH"):
            add(ERROR, "METAGGA_NO_LASPH",
                "meta-GGA (METAGGA) requires LASPH=.TRUE. — non-spherical PAW "
                "contributions are essential (VASP wiki: METAGGA)")
        if "ADDGRID" not in params:
            add(WARN, "METAGGA_NO_ADDGRID",
                "meta-GGA without ADDGRID; set ADDGRID=.TRUE. for accurate forces")

    # --- Phonon (phonopy single-point forces) ---
    if task == "phonon":
        ediff = get_float(params, "EDIFF")
        if ediff is not None and ediff > 1e-7:
            add(WARN, "PHONON_EDIFF_LOOSE",
                f"phonon task with EDIFF={ediff:g} > 1E-7; forces for phonopy "
                "finite displacements need EDIFF <= 1E-7 (1E-8 recommended)")

    # --- Implicit solvation (VASPsol) ---
    if get_bool(params, "LSOL"):
        add(WARN, "VASPSOL_BINARY_UNVERIFIED",
            "LSOL=.TRUE. requires a VASPsol-patched VASP binary; on stock VASP the tags "
            "are silently ignored. Verify ACTUAL coupling after the first run: the "
            "last-step 'Solvation Ediel_sol' in OUTCAR must be NON-ZERO (a constant "
            "0.00000000 means LSOL never coupled — the inert symptom observed on a "
            "real 6.5.1 build), or confirm vasprun.xml carries the LSOL/EB_K "
            "solvent parameter block")
        prec = str(params.get("PREC", [""])[0]).lower()
        if prec and not prec.startswith("acc"):
            add(WARN, "VASPSOL_PREC_LOW",
                "VASPsol cavitation energy needs PREC=Accurate (and ENCUT >= 1.3x vacuum)")

    # --- Applied electric field / charged slab ---
    if "EFIELD" in params and not (has_idipol and get_bool(params, "LDIPOL")):
        add(ERROR, "EFIELD_WITHOUT_DIPOLE",
            "EFIELD requires IDIPOL + LDIPOL=.TRUE.; without the dipole correction "
            "the sawtooth field is not applied (VASP wiki: EFIELD)")
    if "NELECT" in params and vacuum and not has_idipol:
        add(WARN, "NELECT_SLAB_NO_DIPOLE",
            "charged slab (NELECT set) without dipole correction; IDIPOL/LDIPOL "
            "recommended for a well-defined electrostatic reference")

    # --- LREAL on small cells ---
    if (structure and structure.natoms < 20
            and str(params.get("LREAL", [""])[0]).lower().startswith("auto")):
        add(WARN, "LREAL_AUTO_SMALL",
            f"LREAL=Auto on a {structure.natoms}-atom cell; use LREAL=.FALSE. for small cells/accurate statics")

    # --- NELMIN for metals ---
    if structure and elements:
        TRANSITION = {"Fe", "Co", "Ni", "Cu", "Mn", "Cr", "Pt", "Pd", "Au", "Ag",
                      "Ti", "V", "Zn", "Zr", "Nb", "Mo", "Ru", "Rh", "Hf", "Ta", "W", "Ir"}
        if set(elements) & TRANSITION:
            nelmin = get_int(params, "NELMIN", 2)
            if nelmin < 4:
                add(WARN, "NELMIN_LOW",
                    f"Metal system with NELMIN={nelmin} < 4 (default 2); "
                    "set NELMIN >= 4 to avoid premature SCF exit")

    return f


# ---------------------------------------------------------------------------
# CP2K parsing (&SECTION ... &END tree)
# ---------------------------------------------------------------------------

class Cp2kNode:
    def __init__(self, name, param="", path=""):
        self.name = name
        self.param = param
        self.path = path
        self.keywords = {}   # KEY -> [values]
        self.children = []

    def add_kw(self, key, val):
        self.keywords.setdefault(key, []).append(val)

    def get(self, key, default=None):
        vals = self.keywords.get(key.upper())
        return vals[0] if vals else default

    def find_all(self, name):
        name = name.upper()
        out = [c for c in self.children if c.name == name]
        for c in self.children:
            out.extend(c.find_all(name))
        return out


def parse_cp2k(path):
    """Parse a CP2K input into a section tree. Raises ValueError on malformed input."""
    root = Cp2kNode("ROOT")
    stack = [root]
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw
            for comment_mark in ("#", "!"):
                line = line.split(comment_mark, 1)[0]
            line = line.strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("&END"):
                if len(stack) == 1:
                    raise ValueError("&END without an open section")
                end_name = upper[4:].strip()
                if end_name and end_name != stack[-1].name:
                    raise ValueError(
                        f"&END {end_name} closes &{stack[-1].name} "
                        f"(mismatched or a keyword was written as &SECTION)")
                stack.pop()
            elif line.startswith("&"):
                body = line[1:]
                name, _, param = body.partition(" ")
                name = name.strip().upper()
                node = Cp2kNode(name, param.strip(),
                                "/".join([n.name for n in stack[1:]] + [name]))
                stack[-1].children.append(node)
                stack.append(node)
            else:
                key, _, val = line.partition(" ")
                stack[-1].add_kw(key, val.strip())
    if len(stack) != 1:
        raise ValueError(f"unclosed section &{stack[-1].name}")
    return root


def parse_xyz_elements(path):
    """Return the element list of an XYZ coordinate file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    try:
        n = int(lines[0].strip())
    except (IndexError, ValueError):
        raise ValueError(f"not an XYZ file: {path}")
    out = []
    for line in lines[2:2 + n]:
        tok = line.split()
        if tok:
            out.append(tok[0])
    return out


def parse_pdb_kinds(path, use_element_as_kind=False):
    """Return CP2K KIND labels from standard PDB ATOM/HETATM records.

    CP2K defaults ``TOPOLOGY/USE_ELEMENT_AS_KIND`` to false, so the PDB atom
    name (columns 13-16) is the KIND unless the input explicitly enables the
    element-column route (columns 77-78).
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if use_element_as_kind:
            kind = line[76:78].strip() if len(line) >= 78 else ""
            if kind:
                kind = kind[0].upper() + kind[1:].lower()
            field = "element field in columns 77-78"
        else:
            kind = line[12:16].strip() if len(line) >= 16 else ""
            field = "atom-name field in columns 13-16"
        if not kind:
            raise ValueError(f"PDB atom record has no {field}: {line!r}")
        out.append(kind)
    if not out:
        raise ValueError(f"no ATOM/HETATM records found: {path}")
    return out


def _cp2k_number(value):
    """Parse a CP2K numeric keyword value.

    Handles a leading unit token (`[Ry] 200` -> 200.0) and Fortran D exponents
    (`1.0D-4` -> 1.0e-4). Returns None when the value is not a plain number
    (e.g. a `${VAR}` reference), so callers can flag it instead of silently
    falling back to 0 / a default and bypassing the checks (audit P1-CP2K-05).
    """
    if value is None:
        return None
    toks = value.split()
    if not toks:
        return None
    if toks[0].startswith("["):
        toks = toks[1:]
    if not toks:
        return None
    tok = toks[0]
    if tok.startswith("$"):
        return None
    try:
        number = float(re.sub(r"[dD]", "e", tok))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _cp2k_logical(value):
    """Parse a CP2K logical value; a lone keyword is true."""
    if value is None:
        return None
    token = str(value).strip().upper().strip(".")
    if token == "":
        return True
    if token in {"T", "TRUE", "ON", "YES", "1"}:
        return True
    if token in {"F", "FALSE", "OFF", "NO", "0"}:
        return False
    return None


def cp2k_pdb_kind_mode(root):
    """Return (use_element_as_kind, unresolved_reason) for PDB coordinates."""
    topologies = root.find_all("TOPOLOGY")
    raw = topologies[0].get("USE_ELEMENT_AS_KIND") if topologies else None
    if raw is None:
        return False, None  # documented CP2K default
    if str(raw).strip().startswith("$"):
        return (None, "TOPOLOGY/USE_ELEMENT_AS_KIND uses an unresolved CP2K "
                f"preprocessor value {raw!r}; PDB KIND coverage is incomplete")
    value = _cp2k_logical(raw)
    if value is None:
        return (None, "TOPOLOGY/USE_ELEMENT_AS_KIND has an unrecognized logical "
                f"value {raw!r}; PDB KIND coverage is incomplete")
    return value, None


def parse_cp2k_inline_coord_elements(root):
    """Extract KIND labels from ordinary ``&COORD`` atom rows.

    Literal coordinates are unnecessary for KIND/H coverage: preprocessor
    values such as ``O ${OX} 0 0`` still expose the atom label. Directives such
    as ``@INCLUDE`` remain unresolved and are handled by the coverage router.
    """
    elements = []
    for coord in root.find_all("COORD"):
        for label, rows in coord.keywords.items():
            if label.startswith("@"):
                continue
            for row in rows:
                toks = row.split()
                if len(toks) >= 3:
                    elements.append(label)
    return elements or None


def validate_cp2k(root, elements=None, task=None):
    """CP2K rules (mirror of SKILL.md CP2K validation rows + red flags)."""
    f = []
    add = lambda level, code, msg: f.append(Finding(level, code, msg))

    def first(name):
        nodes = root.find_all(name)
        return nodes[0] if nodes else None

    global_ = first("GLOBAL")
    run_type = (global_.get("RUN_TYPE", "") if global_ else "").upper()

    # --- &KIND covers every element ---
    kinds = {c.param.upper() for c in root.find_all("KIND")}
    if elements:
        missing = sorted({e.upper() for e in elements} - kinds)
        if missing:
            add(ERROR, "CP2K_KIND_MISSING",
                f"elements without a &KIND block: {', '.join(missing)} (CP2K crashes without it)")
    for kind in root.find_all("KIND"):
        for req in ("BASIS_SET", "POTENTIAL"):
            if kind.get(req) is None:
                add(WARN, "CP2K_KIND_INCOMPLETE",
                    f"&KIND {kind.param} lacks {req}")

    # --- &POISSON vs &CELL periodicity ---
    poisson, cell = first("POISSON"), first("CELL")
    if poisson is not None and cell is not None:
        p_per = (poisson.get("PERIODIC", "XYZ") or "XYZ").upper()
        c_per = (cell.get("PERIODIC", "XYZ") or "XYZ").upper()
        if p_per != c_per:
            if {p_per, c_per} == {"XY", "XYZ"}:
                add(WARN, "CP2K_PERIODIC_SLAB",
                    f"&POISSON PERIODIC {p_per} with &CELL PERIODIC {c_per}; "
                    "acceptable for 2D slabs — make sure this is intentional")
            else:
                add(ERROR, "CP2K_PERIODIC_MISMATCH",
                    f"&POISSON PERIODIC {p_per} vs &CELL PERIODIC {c_per}; "
                    "mismatch gives wrong electrostatics")
        if c_per == "NONE" and p_per != "NONE":
            add(ERROR, "CP2K_POISSON_ON_MOLECULE",
                "isolated molecule (&CELL PERIODIC NONE) must use &POISSON PERIODIC NONE")

    # --- POISSON_SOLVER must support the cell dimensionality (audit P0-05) ---
    # Compatibility per CP2K manual FORCE_EVAL/DFT/POISSON (POISSON_SOLVER):
    #   PERIODIC  -> XYZ only (default; 3D-periodic systems only)
    #   ANALYTIC  -> 0D / 1D / 2D      MT -> 0D / 2D      MULTIPOLE -> 0D only
    #   WAVELET   -> 0D / 2D / 3D      IMPLICIT -> 0D / 1D / 2D / 3D
    POISSON_SOLVER_DIMS = {
        "PERIODIC": {"XYZ"},
        "ANALYTIC": {"NONE", "X", "Y", "Z", "XY", "XZ", "YZ"},
        "MT": {"NONE", "XY", "XZ", "YZ"},
        "MULTIPOLE": {"NONE"},
        "WAVELET": {"NONE", "XY", "XZ", "YZ", "XYZ"},
        "IMPLICIT": {"NONE", "X", "Y", "Z", "XY", "XZ", "YZ", "XYZ"},
    }
    c_periodic = ((cell.get("PERIODIC", "XYZ") or "XYZ").upper()
                  if cell is not None else None)
    if poisson is None:
        if c_periodic is not None and c_periodic != "XYZ":
            compatible = sorted(
                s for s, dims in POISSON_SOLVER_DIMS.items()
                if c_periodic in dims)
            add(WARN, "CP2K_POISSON_SOLVER_UNVERIFIED",
                f"&CELL PERIODIC {c_periodic} but no &POISSON section; the default "
                "PERIODIC solver only supports fully 3D-periodic systems — add an "
                f"explicit &POISSON with PERIODIC {c_periodic} and a compatible "
                f"POISSON_SOLVER ({', '.join(compatible)})")
    else:
        # Every explicit solver is independently checkable even when &CELL is
        # absent. Compatibility follows the electrostatic boundary declared by
        # &POISSON, which can intentionally differ from &CELL for slabs.
        p_periodic = (poisson.get("PERIODIC", "XYZ") or "XYZ").upper()
        solver_raw = poisson.get("POISSON_SOLVER")
        solver = (solver_raw or "PERIODIC").upper()
        compatible = sorted(
            s for s, dims in POISSON_SOLVER_DIMS.items()
            if p_periodic in dims)
        if solver not in POISSON_SOLVER_DIMS:
            add(ERROR, "CP2K_POISSON_SOLVER_INCOMPATIBLE",
                f"unknown POISSON_SOLVER {solver_raw!r}; valid values: "
                f"{', '.join(sorted(POISSON_SOLVER_DIMS))} "
                "(CP2K manual FORCE_EVAL/DFT/POISSON)")
        elif p_periodic not in POISSON_SOLVER_DIMS[solver]:
            src = "" if solver_raw else " (default — no POISSON_SOLVER set)"
            add(ERROR, "CP2K_POISSON_SOLVER_INCOMPATIBLE",
                f"POISSON_SOLVER {solver}{src} is incompatible with &POISSON "
                f"PERIODIC {p_periodic}; compatible solvers: {', '.join(compatible)} "
                "(CP2K manual FORCE_EVAL/DFT/POISSON: the PERIODIC solver is only "
                "available for fully 3D-periodic systems)")

    # --- CUTOFF sanity ---
    mgrid = first("MGRID")
    if mgrid is not None:
        cutoff_raw = mgrid.get("CUTOFF")
        cutoff = _cp2k_number(cutoff_raw)
        if cutoff_raw is not None and cutoff is None:
            add(WARN, "CP2K_VALUE_UNPARSEABLE",
                f"MGRID CUTOFF value `{cutoff_raw}` is not a plain number (leading unit "
                "tokens like [Ry] and Fortran D exponents ARE supported); cutoff checks "
                "skipped — verify the value manually")
        if cutoff_raw is None:
            cutoff = 0.0
        hybrid = any("PBE0" in (xc.param or "").upper() or "HSE" in (xc.param or "").upper()
                     or "B3LYP" in (xc.param or "").upper()
                     for xc in root.find_all("XC_FUNCTIONAL")) or root.find_all("HF")
        # meta-GGA (SCAN / r2SCAN) via &XC_FUNCTIONAL param or &LIBXC FUNCTIONAL
        metagga = False
        for xc in root.find_all("XC_FUNCTIONAL"):
            texts = [xc.param or ""]
            for lib in xc.find_all("LIBXC"):
                texts.append(lib.get("FUNCTIONAL", "") or "")
            if any("SCAN" in t.upper() for t in texts):
                metagga = True
        if cutoff is not None:
            if hybrid and cutoff < 600:
                add(WARN, "CP2K_CUTOFF_HYBRID",
                    f"CUTOFF={cutoff:g} Ry with hybrid functional; >= 600 Ry recommended")
            elif metagga and cutoff < 600:
                add(WARN, "CP2K_CUTOFF_METAGGA",
                    f"CUTOFF={cutoff:g} Ry with meta-GGA (SCAN/r2SCAN); >= 600 Ry recommended")
            elif not hybrid and not metagga and 0 < cutoff < 300:
                add(WARN, "CP2K_CUTOFF_LOW",
                    f"CUTOFF={cutoff:g} Ry < 300 Ry for DFT; check convergence")

    # --- SCF tightness ---
    scf = first("SCF")
    if scf is not None:
        eps_raw = scf.get("EPS_SCF")
        eps = _cp2k_number(eps_raw)
        if eps_raw is not None and eps is None:
            add(WARN, "CP2K_VALUE_UNPARSEABLE",
                f"EPS_SCF value `{eps_raw}` could not be parsed; SCF-tightness checks "
                "skipped — verify the value manually")
        if eps_raw is None:
            eps = 1.0e-6
        is_md = (task == "md") or run_type == "MD"
        if eps is not None:
            if is_md and eps > 1.0e-5:
                add(WARN, "CP2K_EPS_SCF_LOOSE_MD",
                    f"EPS_SCF={eps:g} > 1.0E-5 for MD; energy drift will be severe")
            if not is_md and eps > 1.0e-6:
                add(WARN, "CP2K_EPS_SCF_LOOSE",
                    f"EPS_SCF={eps:g} > 1.0E-6 for static/opt; tighten for accurate forces")

    # --- MD timestep ---
    md = first("MD")
    if md is not None:
        ts_raw = md.get("TIMESTEP")
        ts = _cp2k_number(ts_raw)
        if ts_raw is not None and ts is None:
            add(WARN, "CP2K_VALUE_UNPARSEABLE",
                f"MD TIMESTEP value `{ts_raw}` could not be parsed; timestep cap check "
                "skipped — verify the value manually")
        elif ts is not None:
            has_h = bool(elements) and "H" in elements
            cap = 0.5 if has_h else 1.0
            if ts > cap:
                add(ERROR, "CP2K_MD_TIMESTEP",
                    f"TIMESTEP={ts:g} fs exceeds the {cap:g} fs cap "
                    f"({'H present' if has_h else 'no H detected'})")

    # --- BAND_STRUCTURE hierarchy (P0 regression guard) ---
    for bs in root.find_all("BAND_STRUCTURE"):
        if bs.path != "FORCE_EVAL/DFT/PRINT/BAND_STRUCTURE":
            add(ERROR, "CP2K_BAND_HIERARCHY",
                f"&BAND_STRUCTURE is at {bs.path}; it belongs under "
                "FORCE_EVAL/DFT/PRINT, NOT &MOTION")
    if task == "band" and not root.find_all("BAND_STRUCTURE"):
        add(ERROR, "CP2K_BAND_MISSING", "band task requires &BAND_STRUCTURE under FORCE_EVAL/DFT/PRINT")

    # --- Section placement guards (2026.1 runtime-verified aborts) ---
    # &FORCES under FORCE_EVAL/DFT/PRINT -> CP2K 2026.1 aborts with
    # "unknown subsection FORCES of section PRINT"; it belongs under
    # FORCE_EVAL/PRINT. &TRAJECTORY under MOTION/CELL_OPT/PRINT is likewise
    # not a valid 2026.1 subsection; it belongs under MOTION/PRINT.
    for forces in root.find_all("FORCES"):
        if forces.path.endswith("DFT/PRINT/FORCES"):
            add(ERROR, "CP2K_MISPLACED_SECTION",
                f"&FORCES is at {forces.path}; it belongs under FORCE_EVAL/PRINT — "
                "under DFT/PRINT CP2K 2026.1 aborts with 'unknown subsection "
                "FORCES of section PRINT' (runtime-verified)")
    for traj in root.find_all("TRAJECTORY"):
        if traj.path.endswith("CELL_OPT/PRINT/TRAJECTORY"):
            add(ERROR, "CP2K_MISPLACED_SECTION",
                f"&TRAJECTORY is at {traj.path}; it belongs under MOTION/PRINT — "
                "&CELL_OPT/&PRINT/&TRAJECTORY is not a valid subsection on "
                "CP2K 2026.1 (runtime-verified)")

    # --- DFT+U ---
    if root.find_all("DFT_PLUS_U"):
        dft = first("DFT")
        if dft is None or dft.get("PLUS_U_METHOD") is None:
            add(ERROR, "CP2K_DFTU_INCOMPLETE",
                "&DFT_PLUS_U present but PLUS_U_METHOD missing in &DFT")
        kp = first("KPOINTS")
        if kp is not None:
            # 2026.1 runtime-verified: ANY &KPOINTS (even SCHEME GAMMA)
            # activates the k-point code path, and Mulliken DFT+U aborts with
            # "Method not implemented for k-points". Pre-2026.2 the correct
            # form is no &KPOINTS block at all (Gamma is the default).
            add(WARN, "CP2K_DFTU_KPOINTS",
                "DFT+U with a &KPOINTS block: on CP2K < 2026.2 ANY &KPOINTS "
                "(including SCHEME GAMMA) aborts with 'Method not implemented "
                "for k-points' — omit &KPOINTS entirely (omitting it = Gamma "
                "point); >= 2026.2 Mulliken DFT+U supports k-points")

    # --- k-points compatibility matrix (audit P0-06 / P0-07) ---
    # CP2K FAQ (cp2k.org/faq:kpoints) + manual methods/dft/k-points: with
    # &KPOINTS only DIAGONALIZATION works; OT, linear-response/DFPT are unsupported.
    kpoints_nodes = root.find_all("KPOINTS")
    if kpoints_nodes:
        if root.find_all("OT"):
            add(ERROR, "CP2K_OT_KPOINTS",
                "&OT cannot be used with &KPOINTS: MO derivatives are not implemented "
                "for k-points, so k-point SCF requires &DIAGONALIZATION (CP2K FAQ: "
                "k-points; manual methods/dft/k-points)")
        if root.find_all("LINRES") or root.find_all("DFPT"):
            add(ERROR, "CP2K_LINRES_KPOINTS",
                "linear-response/DFPT (&LINRES/&DFPT) cannot be combined with &KPOINTS: "
                "CP2K linear response is a Gamma-point localized-orbital implementation "
                "and k-point support covers DFT/RI-HFX/GW only (CP2K manual "
                "methods/dft/k-points)")
        for kp in kpoints_nodes:
            scheme = (kp.get("SCHEME", "") or "").upper()
            gamma_only = (not scheme) or ("GAMMA" in scheme) or ("NONE" in scheme)
            wfn = (kp.get("WAVEFUNCTIONS", "") or "").upper()
            if not gamma_only and wfn.startswith("REAL"):
                add(ERROR, "CP2K_KPOINTS_REAL_WFN",
                    f"WAVEFUNCTIONS REAL with SCHEME {scheme.split()[0]}: real "
                    "wavefunctions can only represent Gamma (or special real-Bloch-phase) "
                    "k-points; use WAVEFUNCTIONS COMPLEX for a general k-mesh (CP2K "
                    "manual FORCE_EVAL/DFT/KPOINTS: WAVEFUNCTIONS)")

    # --- &PDOS vs &KPOINTS (2026.1 runtime-verified) ---
    # With a &KPOINTS block CP2K 2026.1 only prints the warning "pDOS is not
    # implemented for k points" and writes NO PDOS files — easy to miss.
    if kpoints_nodes and root.find_all("PDOS"):
        add(WARN, "CP2K_PDOS_KPOINTS",
            "&PDOS together with &KPOINTS: on CP2K 2026.1 pDOS is not "
            "implemented for k points, so no PDOS files are written (only a "
            "warning in the output). Remove &KPOINTS (Gamma-only) to get PDOS "
            "output, or run the k-mesh SCF separately without &PDOS")

    # --- SCCS implicit solvent ---
    sccs = first("SCCS")
    if sccs is not None:
        dielectric_raw = sccs.get("DIELECTRIC_CONSTANT")
        eps_d = _cp2k_number(dielectric_raw)
        if dielectric_raw is not None and eps_d is None:
            add(WARN, "CP2K_VALUE_UNPARSEABLE",
                f"SCCS DIELECTRIC_CONSTANT value `{dielectric_raw}` could not be parsed; "
                "verify the value manually")
        elif eps_d is None:
            add(WARN, "CP2K_SCCS_NO_DIELECTRIC",
                "&SCCS without DIELECTRIC_CONSTANT; set it explicitly (78.36 for water)")
        elif not 1.0 <= eps_d <= 90.0:
            add(WARN, "CP2K_SCCS_EPS_RANGE",
                f"DIELECTRIC_CONSTANT={eps_d:g} outside the usual 1-90 range")
        eps_sccs_raw = sccs.get("EPS_SCCS")
        eps_sccs = _cp2k_number(eps_sccs_raw)
        if eps_sccs_raw is not None and eps_sccs is None:
            add(WARN, "CP2K_VALUE_UNPARSEABLE",
                f"SCCS EPS_SCCS value `{eps_sccs_raw}` could not be parsed; verify the "
                "value manually")
        elif eps_sccs is not None and eps_sccs > 1.0e-6:
            add(WARN, "CP2K_SCCS_LOOSE",
                f"EPS_SCCS={eps_sccs:g} > 1.0E-6; tighten to 1.0E-7/1.0E-8 — loose "
                "values can silently return zero polarization energy")

    # --- Task-specific required sections ---
    task_checks = {
        "elf": ("ELF_CUBE", "CP2K_ELF_MISSING", "elf task requires &ELF_CUBE"),
        "hirshfeld": ("HIRSHFELD", "CP2K_HIRSHFELD_MISSING", "hirshfeld task requires &HIRSHFELD"),
        "dos": ("PDOS", "CP2K_DOS_MISSING", "dos task requires &PRINT/&PDOS"),
        "phonon": ("FORCES", "CP2K_PHONON_MISSING",
                   "phonon task requires RUN_TYPE ENERGY_FORCE with &PRINT/&FORCES ON"),
    }
    if task in task_checks:
        section, code, msg = task_checks[task]
        if not root.find_all(section):
            add(ERROR, code, msg)

    # --- Work function output (version-gated, 2026.1 runtime-verified) ---
    # &PLANAR_AVERAGED_V_HARTREE is a 2026.2-dev trunk addition; CP2K 2026.1
    # aborts on it ("unknown subsection ... of section DFT"). The 2026.1-safe
    # route is &DFT/&PRINT/&V_HARTREE_CUBE (cube + external planar averaging).
    # Either section satisfies the workfunction task; using the 2026.2+ one
    # earns a version WARN instead of an ERROR.
    if task == "workfunction":
        planar = root.find_all("PLANAR_AVERAGED_V_HARTREE")
        vh_cube = [n for n in root.find_all("V_HARTREE_CUBE")
                   if (n.param or "ON").upper() not in ("OFF", "F", "FALSE", ".FALSE.")]
        if not planar and not vh_cube:
            add(ERROR, "CP2K_WF_MISSING",
                "workfunction task requires &V_HARTREE_CUBE (under "
                "FORCE_EVAL/DFT/PRINT; 2026.1-safe) or "
                "&PLANAR_AVERAGED_V_HARTREE (CP2K >= 2026.2 only)")
        elif planar:
            add(WARN, "CP2K_WF_PLANAR_VERSION_GATE",
                "&PLANAR_AVERAGED_V_HARTREE requires CP2K >= 2026.2 (2026.2-dev "
                "trunk); CP2K 2026.1 aborts with 'unknown subsection "
                "PLANAR_AVERAGED_V_HARTREE of section DFT' — on 2026.1 use "
                "&DFT/&PRINT/&V_HARTREE_CUBE plus external planar averaging")

        # CP2K documents the surface correction specifically for asymmetric
        # slabs. Static .inp/.xyz validation cannot reliably determine whether
        # the two slab faces are symmetry-equivalent, so absence is a WARN, not
        # an ERROR. If correction is enabled, validate the Cartesian direction;
        # SURF_DIP_DIR defaults to Z in CP2K when omitted.
        dft = first("DFT")
        dipole_raw = None
        dipole_present = False
        if dft is not None:
            for key in ("SURFACE_DIPOLE_CORRECTION", "SURFACE_DIPOLE", "SURF_DIP"):
                if key in dft.keywords:
                    dipole_present = True
                    dipole_raw = dft.get(key)
                    break
        dipole_variable = (dipole_present
                           and str(dipole_raw).strip().startswith("$"))
        dipole_active = _cp2k_logical(dipole_raw) if dipole_present else False
        if dipole_variable:
            add(WARN, "CP2K_WF_DIPOLE_UNRESOLVED",
                f"surface dipole correction uses preprocessor value {dipole_raw!r}; "
                "static validation cannot determine whether it expands to true — "
                "verify the @SET/@INCLUDE path or rendered input")
        elif dipole_present and dipole_active is None:
            add(ERROR, "CP2K_WF_DIPOLE_VALUE_INVALID",
                f"surface dipole correction has invalid logical value {dipole_raw!r}; "
                "use .TRUE./.FALSE. (or the lone SURF_DIP alias)")
        elif not dipole_active:
            add(WARN, "CP2K_WF_NO_DIPOLE",
                "workfunction input has no active SURFACE_DIPOLE_CORRECTION. "
                "CP2K requires it for asymmetric/polar slabs; keep it off only "
                "when the two slab faces are demonstrably symmetric. Static input "
                "validation cannot infer that symmetry, so this remains a review WARN")
        else:
            direction_raw = dft.get("SURF_DIP_DIR", "Z") or "Z"
            direction = direction_raw.split()[0].upper()
            if direction.startswith("$"):
                add(WARN, "CP2K_WF_DIPOLE_DIR_UNRESOLVED",
                    f"SURF_DIP_DIR uses preprocessor value {direction_raw!r}; "
                    "static validation cannot determine whether it expands to "
                    "X, Y, or Z — verify the @SET/@INCLUDE path or rendered input")
            elif direction not in {"X", "Y", "Z"}:
                add(ERROR, "CP2K_WF_DIPOLE_DIR_INVALID",
                    f"SURF_DIP_DIR={direction!r}; CP2K accepts only X, Y, or Z "
                    "for the Cartesian surface normal")
    if task == "phonon" and run_type and run_type != "ENERGY_FORCE":
        add(ERROR, "CP2K_PHONON_RUN_TYPE",
            f"phonon task needs RUN_TYPE ENERGY_FORCE, got {run_type}")
    if task == "optics":
        if run_type != "LINEAR_RESPONSE" or not (root.find_all("LINRES") and root.find_all("POLAR")):
            add(ERROR, "CP2K_OPTICS_MISSING",
                "optics task requires RUN_TYPE LINEAR_RESPONSE with &PROPERTIES/&LINRES/&POLAR")

    # --- Metadynamics ---
    if task == "metadyn":
        metadyn = first("METADYN")
        if metadyn is None:
            add(ERROR, "CP2K_METADYN_MISSING",
                "metadyn task requires &MOTION/&FREE_ENERGY/&METADYN")
        else:
            if not metadyn.find_all("METAVAR"):
                add(ERROR, "CP2K_METADYN_NO_METAVAR",
                    "&METADYN without &METAVAR; link at least one collective variable")
            if not root.find_all("HILLS"):
                add(WARN, "CP2K_METADYN_NO_HILLS_PRINT",
                    "no &METADYN/&PRINT/&HILLS section; the hills trajectory will not "
                    "be written (needed for FES reconstruction)")
        if not [c for c in root.find_all("COLVAR")
                if c.path.startswith("FORCE_EVAL/SUBSYS")]:
            add(ERROR, "CP2K_METADYN_NO_COLVAR",
                "metadyn task requires &COLVAR under FORCE_EVAL/SUBSYS")

    return f


# ---------------------------------------------------------------------------
# LAMMPS parsing
# ---------------------------------------------------------------------------

_LAMMPS_PARSER = None


def _load_lammps_parser():
    global _LAMMPS_PARSER
    if _LAMMPS_PARSER is None:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import parse_lammps as _mod
        _LAMMPS_PARSER = _mod
    return _LAMMPS_PARSER


def parse_lammps(path):
    """Return (commands, raw_text). commands = [(cmd, [args])] in file order.

    Compatibility wrapper delegating to the structural LAMMPS parser in
    parse_lammps.py. Preserves the legacy return shape for simple inputs.
    """
    parser = _load_lammps_parser()
    result = parser.parse_lammps_file(path)
    return parser.to_legacy_commands(result), result.raw_text


_ICONST_MODULE = None


def _load_iconst_module():
    """Lazy import of the ICONST model, mirroring _load_lammps_parser."""
    global _ICONST_MODULE
    if _ICONST_MODULE is None:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import iconst as _mod
        _ICONST_MODULE = _mod
    return _ICONST_MODULE


def parse_iconst(path):
    """Parse an ICONST file via the dedicated model module."""
    return _load_iconst_module().parse_iconst(path)


# Hydrogen mass ceiling for data-file Masses checks: 1.008 u + 10% tolerance.
H_MASS_CAP = 1.008 * 1.10


class LammpsData:
    """Parsed LAMMPS data file: header counts + Masses section."""

    def __init__(self, natoms, ntypes, masses):
        self.natoms = natoms    # int or None
        self.ntypes = ntypes    # int or None
        self.masses = masses    # {type_id(int): mass(float)} or None (no Masses)

    @property
    def has_h(self):
        """True/False when Masses are known; None when the file has no Masses
        section (e.g. minimal ASE-written data files) — H status unresolved."""
        if not self.masses:
            return None
        return any(m <= H_MASS_CAP for m in self.masses.values())


def parse_lammps_data(path):
    """Parse a LAMMPS data file: `N atoms`, `N atom types`, and the Masses
    section. Returns LammpsData. Raises ValueError when nothing data-file-like
    is found, so callers can WARN instead of silently skipping data-aware
    checks (Phase C --data implementation)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    natoms = ntypes = None
    masses = None
    i = 0
    while i < len(lines):
        line = lines[i].split("#", 1)[0].strip()
        m = re.fullmatch(r"(\d+)\s+atoms", line)
        if m:
            natoms = int(m.group(1))
            i += 1
            continue
        m = re.fullmatch(r"(\d+)\s+atom\s+types", line)
        if m:
            ntypes = int(m.group(1))
            i += 1
            continue
        if line.split()[:1] == ["Masses"]:
            masses = {}
            i += 1
            while i < len(lines):
                body = lines[i].split("#", 1)[0].strip()
                if not body:
                    i += 1
                    if masses:
                        break      # blank line after the entries: section over
                    continue       # blank line(s) between header and entries
                toks = body.split()
                if not re.fullmatch(r"\d+", toks[0]):
                    break          # next section header (Atoms, Velocities, ...)
                if len(toks) < 2 or _num(toks[1]) is None:
                    raise ValueError(
                        f"malformed Masses line {i + 1}: {lines[i].strip()!r}")
                masses[int(toks[0])] = _num(toks[1])
                i += 1
            continue
        i += 1
    if natoms is None and ntypes is None and masses is None:
        raise ValueError("no 'N atoms', 'N atom types' or Masses section found — "
                         "not a recognizable LAMMPS data file")
    return LammpsData(natoms, ntypes, masses)


_LAMMPS_INTEGRATOR_STYLES = {"nve", "nvt", "npt", "nph"}


def _lammps_is_integrator(style):
    return (style in _LAMMPS_INTEGRATOR_STYLES or style == "rigid"
            or style.startswith("rigid/"))


def _lammps_is_constraint(style):
    return style == "shake" or style == "rigid" or style.startswith("rigid/")


def _lammps_timestep_fs(state):
    raw = state.get("timestep")
    value = _num(raw) if raw is not None else None
    if value is None:
        return None
    units = state.get("units")
    return value * 1000.0 if units == "metal" else value if units == "real" else None


def _lammps_state_analysis(cmds, data=None):
    """Return ``(md_states, fix_states, unsafe_states)`` for run history.

    ``unsafe_states`` contains ``(state, timestep_fs)`` pairs whose executed MD
    segment exceeds 1 fs and lacks a constraint that can cover the H-bearing
    atoms.  Both validation warnings and ``--verified TIMESTEP`` use this one
    analysis so a safe segment cannot verify a different unsafe segment.
    """
    active_fixes = {}
    group_types = {}
    current_timestep = None
    current_units = None
    run_states = []
    for cmd, args in cmds:
        if cmd == "fix" and len(args) >= 3:
            active_fixes[args[0]] = (args[1], args[2].lower())
        elif cmd == "unfix" and args:
            active_fixes.pop(args[0], None)
        elif cmd == "group" and len(args) >= 2:
            group_id, group_style = args[0], args[1].lower()
            if group_style == "delete":
                group_types.pop(group_id, None)
            elif group_style == "type" and len(args) >= 3:
                parsed_types = set()
                for token in args[2:]:
                    if not re.fullmatch(r"\d+", token):
                        parsed_types = None
                        break
                    parsed_types.add(int(token))
                group_types[group_id] = parsed_types
            else:
                group_types[group_id] = None
        elif cmd == "timestep" and args:
            current_timestep = args[0]
        elif cmd == "units" and args:
            current_units = args[0].lower()
        elif cmd == "run":
            run_states.append({
                "fixes": dict(active_fixes),
                "group_types": dict(group_types),
                "timestep": current_timestep,
                "units": current_units,
            })

    final_state = {
        "fixes": dict(active_fixes),
        "group_types": dict(group_types),
        "timestep": current_timestep,
        "units": current_units,
    }
    execution_states = run_states or [final_state]
    fix_states = [state["fixes"] for state in run_states] + [final_state["fixes"]]
    md_states = [
        state for state in execution_states
        if any(_lammps_is_integrator(style)
               for _group, style in state["fixes"].values())
    ]

    h_type_ids = ({type_id for type_id, mass in data.masses.items()
                   if mass <= H_MASS_CAP}
                  if data is not None and data.masses else None)

    def constraints_cover_h(state):
        constraint_groups = {
            group for group, style in state["fixes"].values()
            if _lammps_is_constraint(style)
        }
        if not constraint_groups:
            return False
        if h_type_ids is None:
            return True
        covered_types = set()
        for group in constraint_groups:
            if group == "all":
                return True
            types = state["group_types"].get(group)
            if types is None:
                return True
            covered_types.update(types & h_type_ids)
        return h_type_ids <= covered_types

    unsafe_states = []
    for state in md_states:
        fs = _lammps_timestep_fs(state)
        if fs is not None and fs > 1.0 and not constraints_cover_h(state):
            unsafe_states.append((state, fs))
    return md_states, fix_states, unsafe_states


def validate_lammps(cmds, raw_text, task=None, data=None):
    """LAMMPS rules (mirror of SKILL.md LAMMPS validation rows + red flags).

    `data` is an optional parsed LammpsData (from --data); when its Masses
    section is present it replaces heuristic guesses about H content with a
    real check of the data file.
    """
    f = []
    add = lambda level, code, msg: f.append(Finding(level, code, msg))

    have = {}
    for cmd, args in cmds:
        have.setdefault(cmd, args)
    md_states, fix_states, unsafe_states = _lammps_state_analysis(cmds, data)
    has_md_fix = bool(md_states)
    has_minimize = "minimize" in have

    for required, code in (("units", "LAMMPS_NO_UNITS"),
                           ("atom_style", "LAMMPS_NO_ATOM_STYLE"),
                           ("boundary", "LAMMPS_NO_BOUNDARY")):
        if required not in have:
            add(ERROR, code, f"missing `{required}` command")

    for cmd, args in cmds:
        if cmd == "timestep":
            value = _num(args[0]) if args else None
            if value is None or value <= 0:
                shown = args[0] if args else "<missing>"
                add(ERROR, "LAMMPS_TIMESTEP_INVALID",
                    f"timestep value {shown!r} must be a finite positive number")

    if not any(k in have for k in ("read_data", "read_restart", "create_atoms")):
        add(ERROR, "LAMMPS_NO_SYSTEM",
            "no system source (read_data / read_restart / create_atoms)")

    if "pair_style" not in have and ">>> USER" not in raw_text:
        add(ERROR, "LAMMPS_NO_PAIR_STYLE",
            "no pair_style and no '>>> USER: insert' marker; "
            "the potential must come from the user, never invent one")

    if "run" not in have and not has_minimize and "neb" not in have:
        add(ERROR, "LAMMPS_NO_RUN", "neither `run` nor `minimize` nor `neb` present")

    # --- NEB: the `neb` command requires fix neb ---
    has_neb_fix = any(cmd == "fix" and len(args) >= 3 and args[2] == "neb"
                      for cmd, args in cmds)
    if "neb" in have and not has_neb_fix:
        add(ERROR, "LAMMPS_NEB_NO_FIX",
            "`neb` command without `fix ID group neb Kspring`; NEB requires the neb fix")

    # --- Unresolved placeholders on active lines (audit 10.3 / shared convention) ---
    for raw in raw_text.splitlines():
        active = raw.split("#", 1)[0]
        if ">>> USER" in active:
            snippet = " ".join(active.split())[:70]
            add(ERROR, "LAMMPS_PLACEHOLDER_UNRESOLVED",
                f"active line still contains an unresolved '>>> USER' placeholder: "
                f"`{snippet}`; replace it with a concrete value (guidance may stay "
                "in comments)")

    # --- velocity create 0.0 silently zeroes velocities (audit P0-01, runtime-verified) ---
    for cmd, args in cmds:
        if cmd == "velocity" and len(args) >= 3 and args[1].lower() == "create":
            try:
                temp0 = float(args[2])
            except ValueError:
                continue
            if temp0 == 0.0:
                add(ERROR, "LAMMPS_VELOCITY_ZERO_TEMP",
                    "velocity ... create 0.0 tries to build a 0 K velocity "
                    "distribution; in multi-atom systems LAMMPS does NOT abort — "
                    "the rescale factor is 0, so all velocities are silently zeroed "
                    "and the MD runs at 0 K (only single-atom systems abort with "
                    "'Attempting to rescale a 0.0 temperature'). Use the target "
                    "temperature or a non-zero preheat value "
                    "(docs.lammps.org/velocity.html)")

    # --- pair_style without any pair_coeff (audit P1-LAMMPS-04) ---
    if "pair_style" in have and "pair_coeff" not in have:
        add(ERROR, "LAMMPS_PAIR_COEFF_MISSING",
            "pair_style is set but no pair_coeff appears anywhere; LAMMPS needs "
            "pair_coeff to assign the potential parameters "
            "(docs.lammps.org/pair_coeff.html)")

    # --- EAM pair_coeff arity vs file format (runtime-verified: pair_eam.cpp) ---
    # funcfl single-element files (plain `pair_style eam`) take exactly 3 args
    # (`pair_coeff * * file`, NO element symbol) — a 4th arg aborts with
    # "Incorrect args for pair coefficients". The element-symbol form belongs
    # to the setfl styles eam/alloy and eam/fs, which REQUIRE it.
    ps0 = have.get("pair_style", [])
    if ps0:
        eam_style = str(ps0[0]).lower()
        for suffix in ("/omp", "/kk", "/intel", "/gpu"):
            if eam_style.endswith(suffix):
                eam_style = eam_style[: -len(suffix)]
        if eam_style in ("eam", "eam/alloy", "eam/fs"):
            for cmd, args in cmds:
                if cmd != "pair_coeff" or any(">>>" in tok for tok in args):
                    continue
                line = "pair_coeff " + " ".join(args)
                if eam_style == "eam" and len(args) != 3:
                    add(ERROR, "LAMMPS_EAM_PAIRCOEFF_ARGS",
                        f"`{line}` with plain pair_style eam (funcfl single-element "
                        "format): pair_coeff takes exactly 3 arguments "
                        "(`pair_coeff * * <file>`) with NO element symbol — real "
                        "LAMMPS aborts with 'Incorrect args for pair coefficients' "
                        "(pair_eam.cpp enforces narg == 3). The element-symbol form "
                        "belongs to eam/alloy / eam/fs (setfl files)")
                elif eam_style in ("eam/alloy", "eam/fs") and len(args) < 4:
                    add(ERROR, "LAMMPS_EAM_PAIRCOEFF_ARGS",
                        f"`{line}` with pair_style {eam_style} (setfl format) is "
                        "missing the element symbol(s) after the potential file "
                        "(`pair_coeff * * <file> Al`); real LAMMPS aborts with "
                        "'Incorrect args for pair coefficients'")

    # --- two time-integration fixes on the same group, no unfix in between ---
    reported_conflicts = set()
    for state in fix_states:
        integrators_by_group = {}
        for fix_id, (group, style) in state.items():
            if _lammps_is_integrator(style):
                integrators_by_group.setdefault(group, {})[fix_id] = style
        for group, fixes in integrators_by_group.items():
            signature = (group, tuple(sorted(fixes.items())))
            if len(fixes) > 1 and signature not in reported_conflicts:
                reported_conflicts.add(signature)
                detail = ", ".join(
                    f"{fix_id}:{style}" for fix_id, style in sorted(fixes.items()))
                add(ERROR, "LAMMPS_NVT_NVE_CONFLICT",
                    f"group '{group}' carries multiple active time-integration fixes "
                    f"({detail}); two "
                    "time-integration fixes on the same atoms double-integrate the "
                    "equations of motion — unfix one before adding the other "
                    "(docs.lammps.org/fix.html)")

    # --- barostat along a non-periodic dimension is rejected by LAMMPS (P1-LAMMPS-03) ---
    boundary_args = [b.lower() for b in have.get("boundary", [])][:3]
    if len(boundary_args) == 3:
        periodic = [b == "p" for b in boundary_args]
        PRESSURE_KWS = {"iso": (0, 1, 2), "aniso": (0, 1, 2), "tri": (0, 1, 2),
                        "x": (0,), "y": (1,), "z": (2,),
                        "xy": (0, 1), "yz": (1, 2), "xz": (0, 2)}
        axes = "xyz"
        for cmd, args in cmds:
            if cmd == "fix" and len(args) >= 3 and args[2].lower() in ("npt", "nph"):
                dims, skip_next = set(), False
                for tok in args[3:]:
                    t = tok.lower()
                    if skip_next:            # value of 'couple' (none/xyz/xy/yz/xz)
                        skip_next = False
                        continue
                    if t == "couple":
                        skip_next = True
                        continue
                    if t in PRESSURE_KWS:
                        dims.update(PRESSURE_KWS[t])
                if not dims:
                    dims = {0, 1, 2}         # no pressure keyword parsed -> assume iso
                bad = [axes[i] for i in sorted(dims) if not periodic[i]]
                if bad:
                    add(ERROR, "LAMMPS_NPT_NONPERIODIC_DIM",
                        f"fix {args[2]} barostats dimension(s) {', '.join(bad)} but "
                        f"`boundary {' '.join(boundary_args)}` is non-periodic there; "
                        "LAMMPS rejects pressure coupling along non-periodic dimensions "
                        "— barostat only the periodic axes (never the slab vacuum "
                        "direction) (docs.lammps.org/fix_nh.html)")

    # --- Large timestep without bond constraints (SHAKE/rigid reminder) ---
    # Evaluate each executed MD segment with the timestep/fixes that were active
    # at that run. A later command must not erase an earlier unsafe segment.
    no_h_confirmed = data is not None and data.has_h is False

    metal_unsafe = [(state, fs) for state, fs in unsafe_states
                    if state.get("units") == "metal"]
    if metal_unsafe and not no_h_confirmed:
        ts_fs = max(fs for _state, fs in metal_unsafe)
        coverage = "without fix shake/rigid that can cover the H-bearing atoms"
        if data is not None and data.has_h is True:
            add(WARN, "LAMMPS_NO_SHAKE",
                f"timestep {ts_fs:g} fs (units metal) > 1 fs {coverage}; the "
                f"--data Masses confirm H is present (mass <= {H_MASS_CAP:.4f} u "
                "— real data-file check, not a heuristic), so H bonds genuinely "
                "need constraints at this step size")
        else:
            add(WARN, "LAMMPS_NO_SHAKE",
                f"timestep {ts_fs:g} fs (units metal) > 1 fs {coverage}; "
                "H-containing systems need bond constraints at this step size")

    # Rigid-bond constraints covering the H-bearing atoms make a
    # ~2 fs timestep legitimate (runtime-verified for SPC/E water). When group
    # coverage cannot be proven, retain the conservative reminder.
    if unsafe_states and not no_h_confirmed:
        max_fs = max(fs for _state, fs in unsafe_states)
        add(WARN, "LAMMPS_TIMESTEP_HIGH",
            f"an MD run uses timestep {max_fs:g} fs > 1.0 fs without fix "
            "shake/rigid that can cover the H-bearing atoms; H-containing systems "
            "should use <= 0.5 fs (or constrain the H-bearing group)")
    if has_md_fix and "velocity" not in have:
        add(WARN, "LAMMPS_NO_VELOCITY",
            "MD fix present but no `velocity create`; atoms start at rest")
    if has_md_fix and "dump" not in have:
        add(WARN, "LAMMPS_NO_DUMP", "MD run without any dump (no trajectory output)")
    if "thermo" not in have and ("run" in have or has_minimize):
        add(WARN, "LAMMPS_NO_THERMO", "no thermo output frequency set (LAMMPS default may be silent)")

    # --- Constant-potential electrodes need an /electrode kspace style ---
    has_electrode_fix = any(cmd == "fix" and len(args) >= 3
                            and str(args[2]).startswith("electrode/")
                            for cmd, args in cmds)
    if has_electrode_fix:
        ks = " ".join(have.get("kspace_style", [""]))
        if "/electrode" not in ks:
            add(ERROR, "LAMMPS_ELECTRODE_KSPACE",
                "fix electrode/* requires kspace_style pppm/electrode, "
                "pppm/electrode/intel or ewald/electrode (plain pppm crashes)")

    # --- MLFF pair styles: the model file must be present or left to the user ---
    ps = have.get("pair_style", [])

    # --- pair_style reax/c was removed from current LAMMPS (audit P1-LAMMPS-02) ---
    if ps:
        style0 = str(ps[0]).lower()
        for suffix in ("/omp", "/kk", "/intel", "/gpu"):
            if style0.endswith(suffix):
                style0 = style0[: -len(suffix)]
        if style0 == "reax/c":
            add(ERROR, "LAMMPS_REAXC_REMOVED",
                "pair_style reax/c was removed from current LAMMPS (the REAX-C package "
                "was superseded; LAMMPS >= 22Jul2025 ships only pair_style reaxff). Use "
                "`pair_style reaxff` plus `fix qeq/reaxff` for charge equilibration "
                "(docs.lammps.org/pair_reaxff.html)")

    MLFF_STYLES = {"mace", "deepmd", "pace", "nequip", "allegro"}
    if ps and str(ps[0]).lower() in MLFF_STYLES:
        pc_line = " ".join(have.get("pair_coeff", []))
        has_model = re.search(r"\.(model|pb|pt|pth|yace|ace|pot)\b", pc_line, re.I)
        if not has_model and ">>> USER" not in raw_text:
            add(WARN, "LAMMPS_MLFF_NO_MODEL",
                f"pair_style {ps[0]} without a model file in pair_coeff; "
                "the model path must come from the user, never invent one")

    return f


def _is_lammps_input(fname):
    fl = fname.lower()
    # ``input.inp`` is a conventional CP2K name. Do not run the LAMMPS parser
    # over a file already recognized as CP2K and overwrite its findings.
    if fl.endswith(".inp"):
        return False
    return fl.startswith(("in.", "input")) or fl.endswith(".in")


def cp2k_coordinate_context(inp_path, explicit_xyz=None):
    """Resolve CP2K coordinates for static element/H-aware checks.

    Returns ``(path_or_none, format_or_none, incomplete_reason_or_none)``.
    Inline ``&COORD`` needs no external file when its atom labels are visible.
    A referenced coordinate file is resolved relative to the CP2K input path.
    """
    if explicit_xyz:
        if os.path.exists(explicit_xyz):
            return explicit_xyz, "XYZ", None
        return (explicit_xyz, "XYZ",
                f"coordinate context file not found: {explicit_xyz}")
    try:
        root = parse_cp2k(inp_path)
    except (OSError, ValueError):
        return None, None, None  # validate_cp2k_one owns the parse failure
    coords = root.find_all("COORD")
    if coords:
        unresolved = any(
            key.startswith("@")
            for coord in coords for key in coord.keywords)
        elements = parse_cp2k_inline_coord_elements(root)
        if unresolved:
            return (None, "INLINE",
                    "inline &COORD uses an unresolved preprocessor directive "
                    "such as @INCLUDE; element/H-aware checks are incomplete")
        if not elements:
            return (None, "INLINE",
                    "inline &COORD contains no statically identifiable atom rows; "
                    "element/H-aware checks are incomplete")
        return None, "INLINE", None
    topologies = root.find_all("TOPOLOGY")
    coord_name = topologies[0].get("COORD_FILE_NAME") if topologies else None
    if coord_name:
        token = coord_name.split()[0].strip("'\"")
        format_raw = topologies[0].get("COORD_FILE_FORMAT")
        coord_format = (format_raw.split()[0].upper() if format_raw else
                        "PDB" if token.lower().endswith(".pdb") else
                        "XYZ" if token.lower().endswith(".xyz") else None)
        candidate = (token if os.path.isabs(token)
                     else os.path.join(os.path.dirname(inp_path), token))
        if not os.path.exists(candidate):
            return (candidate, coord_format,
                    f"referenced CP2K coordinate file not found: {token}")
        if coord_format not in {"XYZ", "PDB"}:
            shown = coord_format or "unspecified/unknown"
            return (candidate, coord_format,
                    f"CP2K COORD_FILE_FORMAT={shown} is not supported by the "
                    "static element parser; element/H-aware checks are incomplete")
        if coord_format == "PDB":
            _use_element, mode_reason = cp2k_pdb_kind_mode(root)
            if mode_reason:
                return candidate, coord_format, mode_reason
        return candidate, coord_format, None
    return (None, None, "no --xyz, inline &COORD, or resolvable "
            "&TOPOLOGY/COORD_FILE_NAME; element/H-aware checks skipped")


def lammps_data_context(in_path, explicit_data=None):
    """Resolve a LAMMPS read_data companion and coverage status."""
    if explicit_data:
        if os.path.exists(explicit_data):
            try:
                parse_lammps_data(explicit_data)
            except (OSError, ValueError) as exc:
                return (explicit_data,
                        f"LAMMPS data context could not be parsed: {exc}")
            return explicit_data, None
        return explicit_data, f"LAMMPS data context file not found: {explicit_data}"
    try:
        cmds, _ = parse_lammps(in_path)
    except OSError:
        return None, None
    for cmd, args in cmds:
        if cmd == "read_data" and args:
            token = args[0].strip("'\"")
            candidate = (token if os.path.isabs(token)
                         else os.path.join(os.path.dirname(in_path), token))
            if os.path.exists(candidate):
                try:
                    parse_lammps_data(candidate)
                except (OSError, ValueError) as exc:
                    return (candidate,
                            f"referenced LAMMPS data file could not be parsed: {exc}")
                return candidate, None
            return candidate, f"referenced LAMMPS data file not found: {token}"
        if cmd == "read_restart":
            return None, ("read_restart input has no parseable --data context; "
                          "Masses/H-aware checks skipped")
    return None, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def task_hint_from_name(name):
    lname = name.lower()
    for kw, task in TASK_KEYWORDS.items():
        if kw in lname:
            return task
    return None


_CONTROL_COMMENT_RE = re.compile(r"[!#][^\n]*\bcontrol\b", re.IGNORECASE)


def _declares_control_calculation(path):
    """True when an INCAR comment declares a control calculation, e.g.
    '# control calculation: zero-U reference' (exempts the DFTU_ZERO_U guard)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return bool(_CONTROL_COMMENT_RE.search(f.read()))
    except OSError:
        return False


def validate_one(incar_path, poscar_path=None, potcar_path=None,
                 kpoints_path=None, task=None, verified=None,
                 iconst_path=None):
    params = parse_incar(incar_path)
    structure = None
    if poscar_path and os.path.exists(poscar_path):
        try:
            structure = parse_poscar(poscar_path)
        except (ValueError, IndexError) as exc:
            return None, [Finding(ERROR, "POSCAR_PARSE", f"{poscar_path}: {exc}")]
    max_enmax = None
    if potcar_path and os.path.exists(potcar_path):
        max_enmax = parse_potcar_max_enmax(potcar_path)
    linemode = bool(kpoints_path and os.path.exists(kpoints_path)
                    and is_linemode_kpoints(kpoints_path))
    dftu_control = (task == "dftu-control") or _declares_control_calculation(incar_path)
    iconst_file = None
    if iconst_path and os.path.exists(iconst_path):
        iconst_file = parse_iconst(iconst_path)
    findings = validate(params, structure, max_enmax, linemode, task,
                        dftu_control=dftu_control, iconst=iconst_file,
                        iconst_requested=(task == "slowgrowth"))
    if iconst_path and iconst_file is None:
        findings.append(Finding(
            WARN, "SG_ICONST_UNREADABLE_PATH",
            f"--iconst path not found: {iconst_path}; the collective "
            "variable, INCREM arity and atom-index checks are skipped"))
    if verified:
        file_values = {k: get_float(params, k)
                       for k in ("ENCUT", "EDIFF", "POTIM", "NELMIN", "NELM")}
        findings = apply_verified(findings, verified, file_values)
    return params, findings


def validate_cp2k_one(inp_path, xyz_path=None, task=None, verified=None,
                      coord_format=None):
    try:
        root = parse_cp2k(inp_path)
    except ValueError as exc:
        return [Finding(ERROR, "CP2K_PARSE", f"{inp_path}: {exc}")]
    elements = parse_cp2k_inline_coord_elements(root)
    if xyz_path and os.path.exists(xyz_path):
        effective_format = (coord_format or
                            ("PDB" if xyz_path.lower().endswith(".pdb") else "XYZ"))
        try:
            if effective_format == "PDB":
                use_element, _mode_reason = cp2k_pdb_kind_mode(root)
                if use_element is not None:
                    elements = parse_pdb_kinds(
                        xyz_path, use_element_as_kind=use_element)
            elif effective_format == "XYZ":
                elements = parse_xyz_elements(xyz_path)
        except ValueError as exc:
            code = "PDB_PARSE" if effective_format == "PDB" else "XYZ_PARSE"
            return [Finding(ERROR, code, f"{xyz_path}: {exc}")]
    effective_task = task or task_hint_from_name(os.path.basename(inp_path))
    findings = validate_cp2k(root, elements, effective_task)
    if verified:
        mgrid = root.find_all("MGRID")
        scf = root.find_all("SCF")
        file_values = {
            "CUTOFF": (_cp2k_number(mgrid[0].get("CUTOFF")) if mgrid else None),
            "EPS_SCF": (_cp2k_number(scf[0].get("EPS_SCF")) if scf else None),
        }
        findings = apply_verified(findings, verified, file_values)
    return findings


def validate_lammps_one(in_path, task=None, data_path=None, verified=None):
    cmds, raw_text = parse_lammps(in_path)
    findings = []
    data = None
    if data_path:
        if not os.path.exists(data_path):
            findings.append(Finding(WARN, "LAMMPS_DATA_UNREADABLE",
                f"--data file not found: {data_path}; data-aware checks "
                "(Masses/H detection) skipped"))
        else:
            try:
                data = parse_lammps_data(data_path)
            except (OSError, ValueError) as exc:
                findings.append(Finding(WARN, "LAMMPS_DATA_UNREADABLE",
                    f"--data {data_path} could not be parsed as a LAMMPS data "
                    f"file ({exc}); data-aware checks (Masses/H detection) "
                    "skipped"))
    findings.extend(validate_lammps(cmds, raw_text, task, data=data))
    if verified:
        _md_states, _fix_states, unsafe_states = _lammps_state_analysis(cmds, data)
        ts_fs = (max(fs for _state, fs in unsafe_states)
                 if unsafe_states else None)
        findings = apply_verified(findings, verified, {"TIMESTEP": ts_fs})
    return findings


def run_examples_dir(examples_dir):
    """Validate every example input file (VASP/CP2K/LAMMPS/KPOINTS).

    Backward-compatible wrapper returning {label: findings}; use
    run_examples_dir_full() for the INCOMPLETE / skip metadata (audit 10.1/10.2).
    """
    results, _meta = run_examples_dir_full(examples_dir)
    return results


def run_examples_dir_full(examples_dir):
    """Full examples runner. Returns (results, meta).

    results: {label: [Finding, ...]}
    meta:    {"incomplete": [label, ...],
              "incomplete_reasons": {label: reason},
              "notes": [str, ...]}         # checks that were skipped or are limited
    """
    results = {}
    meta = {"incomplete": [], "incomplete_reasons": {}, "notes": []}

    def mark_incomplete(label, reason):
        if label not in meta["incomplete"]:
            meta["incomplete"].append(label)
        meta["incomplete_reasons"][label] = reason
    for name in sorted(os.listdir(examples_dir)):
        d = os.path.join(examples_dir, name)
        if not os.path.isdir(d) or name.startswith("_") or "test_venv" in name:
            continue
        hint = task_hint_from_name(name)
        files = sorted(os.listdir(d))
        matched = False

        # Slow-growth examples ship two stage files (INCAR_equil, INCAR_growth)
        # instead of a single INCAR. Both must be validated: matching only the
        # literal name "INCAR" left them unchecked, and because such a dir also
        # ships KPOINTS it fell through to the KPOINTS-only branch and reported
        # a pass with zero INCAR coverage.
        incar_files = [fn for fn in files
                       if fn == "INCAR" or fn.startswith("INCAR_")]
        for incar_name in incar_files:
            matched = True
            poscar = os.path.join(d, "POSCAR")
            iconst = os.path.join(d, "ICONST")
            _, findings = validate_one(
                os.path.join(d, incar_name),
                poscar_path=poscar,
                potcar_path=os.path.join(d, "POTCAR"),
                kpoints_path=os.path.join(d, "KPOINTS"),
                task=hint,
                iconst_path=iconst if os.path.exists(iconst) else None,
            )
            label = f"{name}/{incar_name}"
            if not os.path.exists(poscar):
                mark_incomplete(
                    label, "missing POSCAR; structure-aware checks skipped")
            results[label] = findings

        inp = next((fn for fn in files if fn.lower().endswith(".inp")), None)
        if inp:
            matched = True
            inp_path = os.path.join(d, inp)
            xyz = next((fn for fn in files if fn.lower().endswith(".xyz")), None)
            xyz_path, coord_format, incomplete_reason = cp2k_coordinate_context(
                inp_path, os.path.join(d, xyz) if xyz else None)
            findings = validate_cp2k_one(
                inp_path,
                xyz_path,
                task=hint,
                coord_format=coord_format,
            )
            label = f"{name}/{inp}"
            if incomplete_reason:
                findings.append(Finding(
                    WARN, "CP2K_COORD_CONTEXT_MISSING", incomplete_reason))
                mark_incomplete(label, incomplete_reason)
            results[label] = findings

        lam = next((fn for fn in files if _is_lammps_input(fn)), None)
        if lam:
            matched = True
            in_path = os.path.join(d, lam)
            data_path, incomplete_reason = lammps_data_context(in_path)
            findings = validate_lammps_one(
                in_path, task=hint, data_path=data_path)
            label = f"{name}/{lam}"
            if incomplete_reason:
                mark_incomplete(label, incomplete_reason)
            results[label] = findings

        if not matched:
            # K-series: standalone KPOINTS examples (audit 10.1 — must not be invisible)
            if os.path.exists(os.path.join(d, "KPOINTS")):
                findings, notes = validate_kpoints_example(d)
                results[f"{name}/KPOINTS"] = findings
                meta["notes"].extend(f"{name}: {n}" for n in notes)
            elif re.match(r"^K\d", name):
                results[f"{name}/KPOINTS"] = [Finding(
                    ERROR, "KPOINTS_MISSING",
                    f"{name} looks like a KPOINTS example but ships no KPOINTS file")]

    return results, meta


def validate_kpoints_example(d):
    """Validate a standalone KPOINTS example dir: KPOINTS well-formedness plus
    consistency with the scheme its README declares (audit 10.1).

    Returns (findings, notes). Symmetry-label correctness of line-mode paths
    needs seekpath/spglib and is reported as a skipped note, not a PASS.
    """
    findings = []
    notes = []
    kp_path = os.path.join(d, "KPOINTS")
    name = os.path.basename(d)
    with open(kp_path, encoding="utf-8", errors="replace") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if len(lines) < 4:
        findings.append(Finding(
            ERROR, "KPOINTS_MALFORMED",
            f"{kp_path}: KPOINTS needs at least 4 non-blank lines "
            "(comment / number / mode / mesh-or-coordinate)"))
        return findings, notes
    try:
        npts = int(lines[1].split()[0])
    except (ValueError, IndexError):
        findings.append(Finding(
            ERROR, "KPOINTS_MALFORMED",
            f"{kp_path}: line 2 must be an integer (0 = automatic mesh, "
            f"N>0 = explicit/line-mode), got {lines[1].strip()!r}"))
        return findings, notes

    mode = lines[2].strip().lower()
    scheme = None
    if npts == 0:
        if mode.startswith("m"):
            scheme = "monkhorst-pack"
        elif mode.startswith("g"):
            scheme = "gamma"
        else:
            findings.append(Finding(
                ERROR, "KPOINTS_MALFORMED",
                f"{kp_path}: automatic mesh (0) requires Monkhorst-Pack or Gamma on "
                f"line 3, got {lines[2].strip()!r}"))
        mesh = lines[3].split()
        if scheme and (len(mesh) < 3
                       or not all(re.fullmatch(r"\d+", t) for t in mesh[:3])):
            findings.append(Finding(
                ERROR, "KPOINTS_MALFORMED",
                f"{kp_path}: line 4 must be the integer mesh (e.g. 9 9 9), got "
                f"{lines[3].strip()!r}"))
    else:
        if mode.startswith("li"):
            scheme = "line-mode"
            if not lines[3].strip().lower().startswith(("rec", "cart")):
                findings.append(Finding(
                    ERROR, "KPOINTS_MALFORMED",
                    f"{kp_path}: line-mode KPOINTS needs 'reciprocal' or 'cartesian' "
                    f"on line 4, got {lines[3].strip()!r}"))
            else:
                notes.append("line-mode band path: high-symmetry-label correctness is "
                             "NOT verifiable without seekpath/spglib — check skipped "
                             "(see the K5 README for the symprec sensitivity issue)")
        elif mode.startswith(("c", "k", "r")):
            scheme = "explicit"
        else:
            findings.append(Finding(
                ERROR, "KPOINTS_MALFORMED",
                f"{kp_path}: with N>0, line 3 must be Line-mode, Cartesian or "
                f"Reciprocal, got {lines[2].strip()!r}"))

    readme = os.path.join(d, "README.md")
    if os.path.exists(readme):
        with open(readme, encoding="utf-8", errors="replace") as f:
            text = f.read().lower()
        claims = set()
        if "monkhorst" in text:
            claims.add("monkhorst-pack")
        if re.search(r"gamma[- ]?cent", text):
            claims.add("gamma")
        if "line-mode" in text or "band structure" in text or "band path" in text:
            claims.add("line-mode")
        if scheme and claims and scheme not in claims:
            findings.append(Finding(
                ERROR, "KPOINTS_README_MISMATCH",
                f"{name}: README declares scheme(s) {sorted(claims)} but KPOINTS "
                f"line 3 is {lines[2].strip()!r} ({scheme}); a KPOINTS example must "
                "match its README claim"))
        elif not claims:
            notes.append("no k-scheme claim found in README; README-consistency "
                         "check skipped")
    else:
        notes.append("no README.md; README-consistency check skipped")
    return findings, notes


# ---------------------------------------------------------------------------
# Standalone KPOINTS validation (Phase C) + user-verified downgrades (P2-04)
# ---------------------------------------------------------------------------

def _floats3(line):
    """True when the first 3 tokens of a KPOINTS coordinate line are floats
    (a 4th token — weight or symmetry label — is allowed and unchecked)."""
    toks = line.split()
    return len(toks) >= 3 and all(_num(t) is not None for t in toks[:3])


def validate_kpoints_file(path):
    """Standalone KPOINTS validation for `--kpoints` without an INCAR.

    Checks syntax for all three modes plus coarse density heuristics (no POSCAR
    is available, so the density rules stay deliberately shallow):
      - >= 4 non-blank lines; line 2 an integer N >= 0
      - N == 0 (automatic mesh): Monkhorst-Pack/Gamma on line 3, an integer
        mesh on line 4 with every dimension >= 1; 1x1x1 -> KPOINTS_GAMMA_ONLY
        (WARN: Gamma-only sampling is fine for molecules, not for periodic
        bulk/slabs)
      - N > 0 line-mode: 'reciprocal'/'cartesian' on line 4 and an even
        number >= 2 of segment-endpoint lines, each with 3 floats
      - N > 0 explicit list: exactly N coordinate lines, each with 3 floats
      - line-mode with N == 0 is contradictory (points per segment must be > 0)
    """
    findings = []
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if len(lines) < 4:
        return [Finding(ERROR, "KPOINTS_MALFORMED",
            f"{path}: KPOINTS needs at least 4 non-blank lines "
            "(comment / number / mode / mesh-or-coordinate)")]
    try:
        npts = int(lines[1].split()[0])
    except (ValueError, IndexError):
        return [Finding(ERROR, "KPOINTS_MALFORMED",
            f"{path}: line 2 must be an integer (0 = automatic mesh, "
            f"N>0 = explicit/line-mode), got {lines[1].strip()!r}")]
    if npts < 0:
        return [Finding(ERROR, "KPOINTS_MALFORMED",
            f"{path}: line 2 must be >= 0, got {npts}")]

    mode = lines[2].strip().lower()
    if npts == 0:
        if mode.startswith("li"):
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: line 2 = 0 selects an automatic mesh but line 3 says "
                "Line-mode; a line-mode band path needs N > 0 points per segment"))
            return findings
        if not mode.startswith(("m", "g")):
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: automatic mesh (0) requires Monkhorst-Pack or Gamma on "
                f"line 3, got {lines[2].strip()!r}"))
            return findings
        toks = lines[3].split()
        if len(toks) < 3 or not all(re.fullmatch(r"-?\d+", t) for t in toks[:3]):
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: line 4 must be the integer mesh (e.g. 9 9 9), got "
                f"{lines[3].strip()!r}"))
            return findings
        dims = [int(t) for t in toks[:3]]
        if any(d <= 0 for d in dims):
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: mesh dimensions must be >= 1, got {' '.join(toks[:3])}"))
        elif all(d == 1 for d in dims):
            findings.append(Finding(WARN, "KPOINTS_GAMMA_ONLY",
                f"{path}: 1x1x1 mesh samples the Gamma point only; fine for an "
                "isolated molecule in a large box, but insufficient for periodic "
                "bulk/slabs — if this mesh was convergence-tested, declare it "
                "via --verified KPOINTS=<mesh>"))
        return findings

    # N > 0: line-mode or explicit list
    if mode.startswith("li"):
        if not lines[3].strip().lower().startswith(("rec", "cart")):
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: line-mode KPOINTS needs 'reciprocal' or 'cartesian' "
                f"on line 4, got {lines[3].strip()!r}"))
            return findings
        endpoints = lines[4:]
        if len(endpoints) < 2 or len(endpoints) % 2:
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: line-mode paths are written as segment endpoint pairs; "
                f"found {len(endpoints)} coordinate line(s) after line 4 — "
                "expected an even number >= 2"))
            return findings
        bad = [ln.strip() for ln in endpoints if not _floats3(ln)]
        if bad:
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: line-mode endpoint lines need 3 floats (+ optional "
                f"symmetry label); bad line: {bad[0]!r}"))
        else:
            findings.append(Finding(INFO, "KPOINTS_LINEMODE_PATH_UNVERIFIED",
                f"{path}: line-mode syntax OK ({npts} points/segment, "
                f"{len(endpoints) // 2} segment(s)); high-symmetry-label "
                "correctness is NOT verifiable without seekpath/spglib"))
        return findings

    if mode.startswith(("c", "k", "r")):
        coords = lines[3:]
        if len(coords) != npts:
            findings.append(Finding(ERROR, "KPOINTS_COUNT_MISMATCH",
                f"{path}: line 2 declares {npts} k-point(s) but "
                f"{len(coords)} coordinate line(s) follow; explicit-list mode "
                "must list exactly N coordinates"))
            return findings
        bad = [ln.strip() for ln in coords if not _floats3(ln)]
        if bad:
            findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
                f"{path}: explicit-list coordinate lines need 3 floats "
                f"(+ optional weight); bad line: {bad[0]!r}"))
        return findings

    findings.append(Finding(ERROR, "KPOINTS_MALFORMED",
        f"{path}: with N>0, line 3 must be Line-mode, Cartesian or "
        f"Reciprocal, got {lines[2].strip()!r}"))
    return findings


# WARN codes a user can silence by declaring the underlying quantity
# convergence-verified (--verified KEY=VALUE). Only value-like convergence
# heuristics are mapped: completeness WARNs (e.g. "set NBANDS explicitly")
# are not convergence questions and stay WARN. ERROR findings never downgrade.
VERIFIED_KEY_CODES = {
    "ENCUT": {"ENCUT_BELOW_1P3_ENMAX", "OXIDE_ENCUT_LOW"},
    "EDIFF": {"PHONON_EDIFF_LOOSE"},
    "POTIM": {"CG_POTIM_ADSORBATE"},
    "NELMIN": {"NELMIN_LOW"},
    "NELM": {"DFTU_NELM_LOW"},
    "CUTOFF": {"CP2K_CUTOFF_LOW", "CP2K_CUTOFF_HYBRID", "CP2K_CUTOFF_METAGGA"},
    "EPS_SCF": {"CP2K_EPS_SCF_LOOSE", "CP2K_EPS_SCF_LOOSE_MD"},
    "TIMESTEP": {"LAMMPS_TIMESTEP_HIGH"},
    "KPOINTS": {"KPOINTS_GAMMA_ONLY"},
}


def parse_verified(text):
    """Parse '--verified ENCUT=520,CUTOFF=800' into {KEY: value-string}.

    Raises ValueError on entries without a KEY=VALUE shape so the CLI can
    reject them loudly instead of silently ignoring a declaration.
    """
    out = {}
    for item in str(text).split(","):
        item = item.strip()
        if not item:
            continue
        key, sep, val = item.partition("=")
        if not sep or not key.strip() or not val.strip():
            raise ValueError(
                f"malformed --verified entry {item!r}; expected KEY=VALUE")
        out[key.strip().upper()] = val.strip()
    return out


def apply_verified(findings, verified, file_values=None):
    """Downgrade user-verified heuristic WARNs to INFO (audit P2-04).

    verified: {KEY: value-string} from --verified. file_values maps numeric
    keys to floats and KPOINTS to a canonical ``(nx, ny, nz)`` tuple.

    Semantics:
      - a WARN whose code is mapped to a declared key is re-emitted as INFO
        with a [user-verified ...] tag;
      - declarations must be parseable (numeric for scalar keys, a positive
        three-integer mesh for KPOINTS), otherwise the WARN stands and a
        VERIFIED_VALUE_INVALID INFO explains why;
      - if the declared and file values disagree, the WARN stands and a
        VERIFIED_VALUE_MISMATCH INFO explains why;
      - if the input carries no value for a declared key, the WARN likewise stands
        (VERIFIED_NO_FILE_VALUE INFO) — you cannot "verify" a value the file
        does not set;
      - ERROR findings are never touched; unknown keys get a
        VERIFIED_KEY_UNKNOWN INFO so a typo cannot silently pass.
    """
    file_values = file_values or {}
    code_to_key = {}
    for key, codes in VERIFIED_KEY_CODES.items():
        for code in codes:
            code_to_key[code] = key
    out, extra = [], []
    for fd in findings:
        key = code_to_key.get(fd.code)
        if fd.level != WARN or key is None or key not in verified:
            out.append(fd)
            continue
        declared_raw = verified[key]
        actual = file_values.get(key)
        if key == "KPOINTS":
            declared = parse_kpoints_mesh_declaration(declared_raw)
        else:
            declared = _num(declared_raw)
            if declared is not None and not math.isfinite(declared):
                declared = None
        if declared is None:
            out.append(fd)
            expected = "a positive mesh such as 3x3x1" if key == "KPOINTS" else "a number"
            extra.append(Finding(INFO, "VERIFIED_VALUE_INVALID",
                f"--verified {key}={declared_raw} is invalid; expected {expected}; "
                "the WARN stands"))
            continue
        if (key != "KPOINTS" and actual is not None
                and not math.isfinite(actual)):
            out.append(fd)
            extra.append(Finding(INFO, "VERIFIED_VALUE_INVALID",
                f"the input value for {key} is non-finite ({actual!r}); "
                "--verified cannot match it and the WARN stands"))
            continue
        if actual is None:
            out.append(fd)
            extra.append(Finding(INFO, "VERIFIED_NO_FILE_VALUE",
                f"--verified {key}={declared_raw} cannot be matched: the input "
                f"sets no {key} value; the WARN stands"))
            continue
        if key == "KPOINTS":
            if tuple(declared) != tuple(actual):
                out.append(fd)
                actual_text = "x".join(str(x) for x in actual)
                extra.append(Finding(INFO, "VERIFIED_VALUE_MISMATCH",
                    f"--verified KPOINTS={declared_raw} does not match the mesh "
                    f"in the input ({actual_text}); the WARN stands"))
                continue
        else:
            tol = max(1.0e-9, abs(actual) * 1.0e-6)
            if abs(declared - actual) > tol:
                out.append(fd)
                extra.append(Finding(INFO, "VERIFIED_VALUE_MISMATCH",
                    f"--verified {key}={declared_raw} does not match the value "
                    f"in the input ({actual:g}); the WARN stands"))
                continue
        out.append(Finding(INFO, fd.code,
            f"{fd.message} [user-verified {key}={declared_raw}: heuristic WARN "
            "downgraded to INFO per --verified]"))
    for key in verified:
        if key not in VERIFIED_KEY_CODES:
            extra.append(Finding(INFO, "VERIFIED_KEY_UNKNOWN",
                f"--verified key {key} is not mapped to any heuristic check; "
                "it changes nothing"))
    return out + extra


def _print_findings(findings, label, incomplete=False, incomplete_reason=None):
    n_err = sum(1 for x in findings if x.level == ERROR)
    n_warn = sum(1 for x in findings if x.level == WARN)
    n_info = sum(1 for x in findings if x.level == INFO)
    tiers = validation_tiers(findings, incomplete=incomplete)
    status = tiers["overall"]
    suffix = f"; {incomplete_reason or 'required context missing'}" if incomplete else ""
    print(f"{status}  {label}  ({n_err} errors, {n_warn} warnings, "
          f"{n_info} info{suffix})")
    print("      VALIDATION_TIERS "
          f"syntax={tiers['syntax']} "
          f"combination={tiers['combination']} "
          f"physics={tiers['physics']}")
    for x in findings:
        print(f"      {x}")
    return n_err


def _kpoints_cli_findings(kpoints_path, verified=None):
    """Standalone/companion KPOINTS check for the CLI: format findings, with
    user-verified downgrades applied after comparing the declared mesh with
    the automatic mesh actually present in the file."""
    if not os.path.exists(kpoints_path):
        return [Finding(ERROR, "KPOINTS_MISSING",
                        f"{kpoints_path}: file not found")]
    findings = validate_kpoints_file(kpoints_path)
    if verified:
        findings = apply_verified(
            findings, verified,
            {"KPOINTS": read_automatic_kpoints_mesh(kpoints_path)})
    return findings


def main():
    ap = argparse.ArgumentParser(description="Validate input-build generated inputs "
                                             "(VASP/CP2K/LAMMPS) against the SKILL.md hard rules.")
    ap.add_argument("--incar", help="VASP INCAR file to validate")
    ap.add_argument("--poscar", help="POSCAR/CONTCAR for structure-aware checks")
    ap.add_argument("--potcar", help="POTCAR for ENCUT/ENMAX coverage check")
    ap.add_argument("--kpoints", help="KPOINTS file; with --incar it feeds line-mode "
                                      "detection and is also format-checked, on its own "
                                      "(no --incar) it triggers standalone KPOINTS validation")
    ap.add_argument("--iconst", help="ICONST file for slow-growth / constrained MD; "
                                     "enables collective-variable, INCREM arity and "
                                     "atom-index checks")
    ap.add_argument("--cp2k", help="CP2K .inp file to validate")
    ap.add_argument("--xyz", help="XYZ coordinate file for &KIND coverage / H detection")
    ap.add_argument("--lammps", help="LAMMPS input script to validate")
    ap.add_argument("--data", help="LAMMPS data file; enables data-aware checks "
                                   "(Masses/H detection for the shake/timestep reminders)")
    ap.add_argument("--task", help="Task override (relax/md/slowgrowth/static/geo_opt/dos/band/"
                                   "freq/phonon/neb/optics/dielectric/elf/workfunction/hirshfeld/"
                                   "minimize/dftu/metadyn/dftu-control)")
    ap.add_argument("--verified", metavar="KEY=VALUE,...",
                    help="declare convergence-verified quantities, e.g. "
                         "--verified ENCUT=520,CUTOFF=800; a heuristic WARN on a "
                         "declared quantity is downgraded to INFO and tagged "
                         "user-verified (a declared value that disagrees with the "
                         "file leaves the WARN standing; ERRORs never downgrade)")
    ap.add_argument("--examples-dir", help="Validate all example input files under a directory")
    ap.add_argument("--json", action="store_true", help="Emit JSON manifest on stdout")
    args = ap.parse_args()

    verified = None
    if args.verified:
        try:
            verified = parse_verified(args.verified)
        except ValueError as exc:
            ap.error(str(exc))

    if args.examples_dir:
        results, meta = run_examples_dir_full(args.examples_dir)
        incomplete = set(meta["incomplete"])
        if args.json:
            print(json.dumps(
                {"files": {name: [x.as_dict() for x in fs]
                           for name, fs in results.items()},
                 "validation": {
                     name: validation_tiers(fs, incomplete=name in incomplete)
                     for name, fs in results.items()
                 },
                 "incomplete": meta["incomplete"],
                 "incomplete_reasons": meta["incomplete_reasons"],
                 "notes": meta["notes"]},
                indent=2, ensure_ascii=False))
        else:
            for name, findings in results.items():
                _print_findings(
                    findings, name, incomplete=name in incomplete,
                    incomplete_reason=meta["incomplete_reasons"].get(name))
            for note in meta["notes"]:
                print(f"NOTE  {note}")
            print(f"\n{len(results)} input file(s) validated "
                  f"({len(incomplete)} incomplete: required structure/data "
                  "context missing, context-aware checks skipped).")
        total_err = sum(1 for fs in results.values() for x in fs if x.level == ERROR)
    elif args.incar:
        _, findings = validate_one(args.incar, args.poscar, args.potcar,
                                   args.kpoints, args.task, verified=verified,
                                   iconst_path=args.iconst)
        if args.kpoints:
            findings.extend(_kpoints_cli_findings(args.kpoints, verified))
        poscar_complete = bool(args.poscar and os.path.exists(args.poscar))
        reason = None if poscar_complete else (
            f"POSCAR context file not found: {args.poscar}" if args.poscar
            else "no --poscar; structure-aware checks skipped")
        _emit(args, args.incar, findings, incomplete=not poscar_complete,
              incomplete_reason=reason)
        total_err = sum(1 for x in findings if x.level == ERROR)
    elif args.cp2k:
        xyz_path, coord_format, reason = cp2k_coordinate_context(
            args.cp2k, args.xyz)
        findings = validate_cp2k_one(args.cp2k, xyz_path, args.task,
                                     verified=verified,
                                     coord_format=coord_format)
        if reason:
            findings.append(Finding(WARN, "CP2K_COORD_CONTEXT_MISSING", reason))
        _emit(args, args.cp2k, findings, incomplete=bool(reason),
              incomplete_reason=reason)
        total_err = sum(1 for x in findings if x.level == ERROR)
    elif args.lammps:
        data_path, reason = lammps_data_context(args.lammps, args.data)
        findings = validate_lammps_one(args.lammps, args.task,
                                       data_path=data_path, verified=verified)
        _emit(args, args.lammps, findings, incomplete=bool(reason),
              incomplete_reason=reason)
        total_err = sum(1 for x in findings if x.level == ERROR)
    elif args.kpoints:
        findings = _kpoints_cli_findings(args.kpoints, verified)
        _emit(args, args.kpoints, findings)
        total_err = sum(1 for x in findings if x.level == ERROR)
    else:
        ap.error("provide --incar, --cp2k, --lammps, --kpoints, or --examples-dir")

    # Exit code is driven by ERROR findings only; INCOMPLETE is reported separately
    # and never masks or produces a failure by itself.
    sys.exit(1 if total_err else 0)


def _emit(args, label, findings, incomplete=False, incomplete_reason=None):
    if args.json:
        print(json.dumps({"file": label,
                          "validation": validation_tiers(
                              findings, incomplete=incomplete),
                          "coverage": {
                              "complete": not incomplete,
                              "reason": incomplete_reason,
                          },
                          "findings": [x.as_dict() for x in findings]},
                         indent=2, ensure_ascii=False))
    else:
        _print_findings(findings, label, incomplete=incomplete,
                        incomplete_reason=incomplete_reason)


if __name__ == "__main__":
    main()
