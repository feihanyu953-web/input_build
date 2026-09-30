#!/usr/bin/env python3
"""
KPOINTS Helper for input-build skill
Exact KPOINTS generation using seekpath for space-group-aware band paths.

Usage:
    python kpoints_helper.py --poscar POSCAR --spacing 0.18 --scheme MP
    python kpoints_helper.py --poscar POSCAR --band-structure
    python kpoints_helper.py --poscar POSCAR --band-structure --symprec 1e-4
    python kpoints_helper.py --bootstrap-deps        # explicit dependency install

Dependencies (NEVER auto-installed on import — audit P1-KPOINTS-04):
    ase, spglib, seekpath (>= 2.0 for get_path_orig_cell)
    If any dependency is missing the script exits with an error and prints
    install instructions. Installing happens ONLY via the explicit
    `--bootstrap-deps` command below, which installs pinned, tested versions.
    There is no fallback to built-in path tables — wrong k-points are worse
    than none (fail closed).
"""

import argparse
import math
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path


# ------------------------------------------------------------------------------
# Dependency handling: report-only on import; explicit bootstrap to install
# ------------------------------------------------------------------------------
_REQUIRED_DEPS = ["ase", "spglib", "seekpath"]

# Pinned, tested versions (this skill was validated against these).
# seekpath >= 2.0 is required for get_path_orig_cell (original-cell basis).
_PINNED_DEPS = ["ase==3.29.0", "spglib==2.7.0", "seekpath==2.2.1"]


class KpointsHelperError(RuntimeError):
    """Fatal, user-actionable error. main() catches it and exits non-zero."""


class PoscarScalingError(ValueError):
    """POSCAR line-2 (scaling factor) does not follow the VASP specification."""


def _find_missing_deps():
    """Return the list of required packages that cannot be imported."""
    missing = []
    for pkg in _REQUIRED_DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def _check_deps_or_die():
    """Report missing dependencies and exit. NEVER installs anything.

    Importing or running this module must not touch the network or modify the
    Python environment (audit P1-KPOINTS-04).
    """
    missing = _find_missing_deps()
    if not missing:
        return
    print(f"[ERROR] Missing Python dependencies: {', '.join(missing)}")
    print("[ERROR] kpoints_helper.py requires: ase, spglib, seekpath (>= 2.0)")
    print("[ERROR] This script does NOT auto-install on import. Install with:")
    print("    python scripts/kpoints_helper.py --bootstrap-deps   # pinned, tested versions")
    print("    # or choose versions yourself:")
    print("    uv pip install ase spglib seekpath")
    print("    pip install ase spglib seekpath")
    sys.exit(1)


def _bootstrap_deps():
    """Explicitly install pinned dependency versions (opt-in, user-invoked).

    Only reached via `python kpoints_helper.py --bootstrap-deps`. Output is
    intentionally visible (not suppressed) so the user can audit what happens.
    """
    missing = _find_missing_deps()
    if not missing:
        print("[OK] All dependencies already importable "
              f"({', '.join(_REQUIRED_DEPS)}) — nothing to install.")
        return

    pinned = {spec.split("==")[0]: spec for spec in _PINNED_DEPS}
    targets = [pinned[name] for name in missing]
    print(f"[INFO] Missing dependencies: {', '.join(missing)}")
    print(f"[INFO] Installing pinned, tested versions: {', '.join(targets)}")

    # Try uv first (user preference), fallback to pip
    cmds = [
        [sys.executable, "-m", "uv", "pip", "install"] + targets,
        [sys.executable, "-m", "pip", "install"] + targets,
    ]

    installed = False
    for cmd in cmds:
        try:
            subprocess.check_call(cmd)
            installed = True
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not installed:
        print("[ERROR] Failed to install dependencies.")
        print("[ERROR] Please run manually:")
        print("    uv pip install " + " ".join(targets))
        print("    # or: pip install " + " ".join(targets))
        sys.exit(1)

    still_missing = _find_missing_deps()
    if still_missing:
        print(f"[ERROR] Installed but import still fails: {', '.join(still_missing)}.")
        print("[ERROR] Restart the script or check your Python environment.")
        sys.exit(1)

    print("[OK] Dependencies installed successfully.")


# Handle the explicit bootstrap command BEFORE the import-time dependency
# check. `--bootstrap-deps` installs pinned versions and exits; it is the ONLY
# code path in this module that may run an installer.
if "--bootstrap-deps" in sys.argv[1:]:
    _bootstrap_deps()
    sys.exit(0)

_check_deps_or_die()

# Now safe to import
import ase.io
import seekpath
import spglib


# ------------------------------------------------------------------------------
# POSCAR parsing (VASP wiki: POSCAR — scaling factor rules)
# ------------------------------------------------------------------------------

def parse_scaling_line(line):
    """Parse POSCAR line 2 (scaling factor) per the VASP specification.

    Returns (mode, values):
      - ("uniform", (sx, sy, sz)): one positive value s (applied uniformly)
        or three positive values scaling the Cartesian x/y/z components.
      - ("volume", target): one negative value s; |s| is the TARGET TOTAL
        VOLUME of the cell, so every lattice vector must be scaled by
        (|s| / V_current)^(1/3) — NOT multiplied by s directly.

    Raises PoscarScalingError with a precise message for anything else
    (non-numeric, zero, two values, negative values inside a 3-factor form).
    """
    tokens = line.split()
    try:
        values = [float(t) for t in tokens]
    except ValueError:
        raise PoscarScalingError(
            f"POSCAR line 2 (scaling factor) is not numeric: {line.strip()!r}. "
            "Expected one number, or three numbers scaling Cartesian x/y/z."
        )
    if any(not math.isfinite(v) for v in values):
        raise PoscarScalingError(
            f"POSCAR line 2 scaling factors must be finite, got {values}."
        )

    if len(values) == 1:
        s = values[0]
        if s > 0:
            return ("uniform", (s, s, s))
        if s < 0:
            return ("volume", abs(s))
        raise PoscarScalingError(
            "POSCAR line 2: scaling factor 0 is invalid. Use a positive value "
            "(cartesian scaling) or a negative value (target total volume)."
        )

    if len(values) == 3:
        if any(v <= 0 for v in values):
            raise PoscarScalingError(
                f"POSCAR line 2: three scaling factors must all be positive, "
                f"got {values}. The negative target-volume form only allows a "
                "single value."
            )
        return ("uniform", tuple(values))

    raise PoscarScalingError(
        f"POSCAR line 2: expected 1 or 3 scaling factors, got {len(values)} "
        f"({line.strip()!r})."
    )


def read_poscar_lattice(poscar_path: str):
    """Read lattice vectors from POSCAR, applying the line-2 scaling factor.

    Handles all VASP-legal scaling forms (see parse_scaling_line):
    single positive, single negative (target volume), three positive factors.
    Raises PoscarScalingError on malformed input (fail closed).
    """
    with open(poscar_path, 'r') as f:
        lines = f.readlines()

    if len(lines) < 5:
        raise PoscarScalingError(
            f"POSCAR too short: expected at least 5 lines (comment, scaling, "
            f"3 lattice vectors), got {len(lines)}."
        )

    mode, values = parse_scaling_line(lines[1])

    # Lines 3-5: lattice vectors (Angstrom, before scaling)
    raw = []
    for i in (2, 3, 4):
        parts = lines[i].split()
        if len(parts) < 3:
            raise PoscarScalingError(
                f"POSCAR line {i + 1}: expected 3 components of a lattice "
                f"vector, got {len(parts)} ({lines[i].strip()!r})."
            )
        try:
            raw.append([float(x) for x in parts[:3]])
        except ValueError:
            raise PoscarScalingError(
                f"POSCAR line {i + 1}: lattice vector is not numeric: "
                f"{lines[i].strip()!r}."
            )

    if mode == "volume":
        volume = abs(dot(raw[0], cross(raw[1], raw[2])))
        if volume < 1e-12:
            raise PoscarScalingError(
                "POSCAR lattice vectors have ~zero volume; cannot apply the "
                "negative target-volume scaling factor."
            )
        factor = (values / volume) ** (1.0 / 3.0)
        factors = (factor, factor, factor)
    else:
        factors = values

    # In the three-value POSCAR form the factors apply to Cartesian x/y/z
    # components (matrix columns), not to the lattice vectors a/b/c (rows).
    a, b, c = ([x * factors[j] for j, x in enumerate(vec)] for vec in raw)
    return a, b, c


def cross(u, v):
    """Cross product of two 3-vectors."""
    return [
        u[1]*v[2] - u[2]*v[1],
        u[2]*v[0] - u[0]*v[2],
        u[0]*v[1] - u[1]*v[0]
    ]


def dot(u, v):
    """Dot product of two 3-vectors."""
    return sum(ui * vi for ui, vi in zip(u, v))


def norm(v):
    """Euclidean norm of a 3-vector."""
    return math.sqrt(sum(x**2 for x in v))


def reciprocal_vectors(a, b, c):
    """Compute reciprocal lattice vectors b1, b2, b3 (units: 1/Angstrom)."""
    volume = dot(a, cross(b, c))
    b1 = [2 * math.pi * x / volume for x in cross(b, c)]
    b2 = [2 * math.pi * x / volume for x in cross(c, a)]
    b3 = [2 * math.pi * x / volume for x in cross(a, b)]
    return b1, b2, b3


def classify_lattice(a, b, c, tol=1e-3):
    """Classify Bravais lattice from lattice vectors."""
    na, nb, nc = norm(a), norm(b), norm(c)

    # Angles
    alpha = math.acos(dot(b, c) / (nb * nc)) * 180 / math.pi
    beta  = math.acos(dot(a, c) / (na * nc)) * 180 / math.pi
    gamma = math.acos(dot(a, b) / (na * nb)) * 180 / math.pi

    def close(x, y, t=tol):
        return abs(x - y) < t

    # Check equalities
    eq_ab = close(na, nb)
    eq_bc = close(nb, nc)
    eq_ac = close(na, nc)
    all_eq = eq_ab and eq_bc

    right_angles = close(alpha, 90) and close(beta, 90) and close(gamma, 90)
    hex_gamma = close(gamma, 120) and close(alpha, 90) and close(beta, 90)
    rhombo_angles = (close(alpha, beta) and close(beta, gamma)
                     and not right_angles)

    if all_eq and right_angles:
        return "cubic", na, nb, nc, alpha, beta, gamma
    elif all_eq and rhombo_angles:
        return "rhombohedral", na, nb, nc, alpha, beta, gamma
    elif eq_ab and close(alpha, 90) and close(beta, 90) and hex_gamma:
        return "hexagonal", na, nb, nc, alpha, beta, gamma
    elif eq_ab and right_angles:
        return "tetragonal", na, nb, nc, alpha, beta, gamma
    elif right_angles:
        return "orthorhombic", na, nb, nc, alpha, beta, gamma
    elif close(alpha, 90) and close(gamma, 90) and not close(beta, 90):
        return "monoclinic", na, nb, nc, alpha, beta, gamma
    else:
        return "triclinic", na, nb, nc, alpha, beta, gamma


# ------------------------------------------------------------------------------
# Lattice-family declaration vs. identification (audit P0-03)
# ------------------------------------------------------------------------------

# Crystal families a user may declare via --lattice or the POSCAR comment line.
# NOTE: "trigonal" is deliberately NOT a keyword — the trigonal crystal system
# maps to either hP (hexagonal) or hR (rhombohedral) Bravais lattices, so a
# "trigonal" declaration would be ambiguous.
_LATTICE_KEYWORDS = (
    "cubic", "hexagonal", "tetragonal", "orthorhombic",
    "monoclinic", "rhombohedral", "triclinic",
)
_LATTICE_CHOICES = list(_LATTICE_KEYWORDS)
_LATTICE_RE = re.compile(
    r"\b(" + "|".join(_LATTICE_KEYWORDS) + r")\b", re.IGNORECASE
)


def parse_declared_lattice(comment: str):
    """Extract a crystal-family declaration from free text (POSCAR line 1).

    Returns the normalized family name (lowercase) or None when no
    unambiguous keyword is present.
    """
    if not comment:
        return None
    m = _LATTICE_RE.search(comment)
    return m.group(1).lower() if m else None


def read_poscar_comment_lattice(poscar_path: str):
    """Read the POSCAR comment line (line 1) and extract a lattice declaration."""
    try:
        with open(poscar_path, 'r') as f:
            comment = f.readline()
    except OSError:
        return None
    return parse_declared_lattice(comment)


def bravais_family(bravais_lattice: str):
    """Map a seekpath Bravais-lattice symbol (e.g. 'mC', 'hP', 'cF') to a
    crystal family name matching classify_lattice / --lattice choices."""
    if not bravais_lattice:
        return None
    if bravais_lattice == "hP":
        return "hexagonal"
    if bravais_lattice == "hR":
        return "rhombohedral"
    return {
        "c": "cubic",
        "t": "tetragonal",
        "o": "orthorhombic",
        "m": "monoclinic",
        "a": "triclinic",
    }.get(bravais_lattice[0].lower())


def check_declared_lattice(declared, identified, identified_desc, source_desc):
    """Fail closed when a user-declared crystal family conflicts with the
    identified one (audit P0-03). identified_desc/source_desc make the error
    message self-explanatory."""
    if not declared or not identified:
        return
    if declared != identified:
        raise KpointsHelperError(
            f"Declared lattice '{declared}' ({source_desc}) conflicts with the\n"
            f"        identified Bravais lattice: {identified_desc} "
            f"(family '{identified}').\n"
            f"        The structure may be slightly distorted — try adjusting "
            f"--symprec,\n        or fix the POSCAR. No KPOINTS file was written."
        )


def compute_kmesh(b1, b2, b3, spacing_angstrom):
    """Compute Monkhorst-Pack or Gamma-centered mesh from reciprocal vectors."""
    # spacing in Angstrom^-1
    # k_i = ceil(2*pi / (spacing * |b_i|))
    # But actually: number of points = ceil(|b_i| / spacing)
    k1 = max(1, math.ceil(norm(b1) / spacing_angstrom))
    k2 = max(1, math.ceil(norm(b2) / spacing_angstrom))
    k3 = max(1, math.ceil(norm(b3) / spacing_angstrom))
    return k1, k2, k3


def bravais_centering(poscar_path, symprec=1e-5):
    """Return Bravais centering letter ('P','I','F','A','B','C','R') via spglib.

    Used for k-mesh scheme selection: VASP recommends Gamma-centered meshes
    for fcc, hexagonal, and fcc-orthorhombic lattices (VASP wiki: KPOINTS),
    which cannot be distinguished from lattice lengths/angles alone.
    Returns None if symmetry analysis fails.
    """
    try:
        atoms = ase.io.read(poscar_path)
        dataset = spglib.get_symmetry_dataset(
            (atoms.cell, atoms.get_scaled_positions(), atoms.numbers),
            symprec=symprec,
        )
        # spglib >= 2.0 returns a SpglibDataset; use the attribute interface
        # (dict access is deprecated). 'international' is the Hermann-Mauguin
        # symbol, e.g. 'Fm-3m' -> centering 'F'
        symbol = getattr(dataset, "international", None)
        if symbol is None:
            symbol = dataset["international"]  # spglib 1.x fallback
        return symbol[0] if symbol else None
    except Exception:
        return None


def recommend_scheme(lattice_type, has_vacuum=False, centering=None):
    """Recommend k-point scheme based on lattice type, vacuum, and centering.

    VASP wiki (KPOINTS): use Gamma-centered meshes for fcc, hexagonal, and
    fcc-orthorhombic lattices so the mesh preserves the point-group symmetry
    of the reciprocal lattice. Centering 'F' covers both cubic-F (fcc) and
    orthorhombic-F.
    """
    if has_vacuum or lattice_type == "hexagonal" or centering == "F":
        return "Gamma"
    return "MP"


def write_kpoints_auto(k1, k2, k3, scheme, output_path="KPOINTS"):
    """Write automatic mesh KPOINTS file."""
    with open(output_path, 'w') as f:
        f.write("Automatic mesh\n")
        f.write("0\n")  # Auto-mesh flag
        if scheme.upper() == "GAMMA":
            f.write("Gamma\n")
        else:
            f.write("Monkhorst-Pack\n")
        f.write(f"{k1} {k2} {k3}\n")
        f.write("0.0 0.0 0.0\n")
    print(f"[OK] Wrote {scheme}-centered {k1}x{k2}x{k3} mesh to {output_path}")


# ------------------------------------------------------------------------------
# Band-structure path (seekpath), with supercell / tolerance / basis guards
# ------------------------------------------------------------------------------

_SUPERCELL_OPTIONS = (
    "        Choose one of:\n"
    "          1. Primitive-cell band: reduce the cell to the primitive cell\n"
    "             (e.g. spglib find_primitive / phonopy / VASPKIT) and re-run\n"
    "             --band-structure on the primitive cell.\n"
    "          2. Folded supercell band: construct a Gamma-anchored path for\n"
    "             the supercell Brillouin zone yourself — the supercell BZ is\n"
    "             folded, so seekpath's primitive-BZ labels do not apply.\n"
    "          3. Band-unfolding workflow: run the supercell band and unfold\n"
    "             it onto the primitive BZ (e.g. BandUP / PyProcar / VASPKIT).\n"
    "        Override only if you know what you are doing: --allow-supercell"
)


def _classification_key(path_result):
    """(space group, Bravais lattice) tuple used for stability comparison."""
    return (path_result.get("spacegroup_number"),
            path_result.get("bravais_lattice"))


def _classification_desc(path_result):
    return (f"SG {path_result.get('spacegroup_number', 'N/A')} "
            f"({path_result.get('spacegroup_international', 'N/A')}), "
            f"Bravais {path_result.get('bravais_lattice', 'N/A')}")


def _conventional_volume_ratio(structure, symprec):
    """V_input / V_standard_conventional via spglib standardization.

    Used to distinguish the two cases that both make seekpath set
    is_supercell / emit SupercellWarning:

      * ratio ~ 1  -> the input IS the standard conventional cell of a
        centered lattice (F/I/A/B/C/R, e.g. the 4-atom fcc cell). The
        orig-cell path labels are the crystal's true conventional-BZ
        high-symmetry points — physically correct and standard practice.
      * ratio >= 2 -> the input is an integer REPETITION supercell. Its
        first BZ is folded, and the seekpath labels do NOT correspond to
        the supercell-BZ high-symmetry points — must be refused.

    Returns None when standardization fails (caller then fails closed).
    """
    try:
        std = spglib.standardize_cell(structure, to_primitive=False,
                                      symprec=symprec)
    except Exception:
        return None
    if std is None:
        return None
    vol_in = abs(_det3(structure[0]))
    vol_std = abs(_det3(std[0]))
    if vol_std < 1e-12:
        return None
    return vol_in / vol_std


def _det3(m):
    """Determinant of a 3x3 matrix given as rows (lists or ndarray)."""
    a, b, c = [list(map(float, row)) for row in m]
    return dot(a, cross(b, c))


def _call_seekpath(structure, symprec, angle_tolerance):
    """Call seekpath.get_path_orig_cell, capturing warnings.

    Returns (path_result, caught_warnings). get_path_orig_cell is required:
    falling back to get_path() would write coordinates in the standardized
    PRIMITIVE basis while the user's POSCAR is a conventional cell/supercell,
    i.e. a silently wrong path — so we fail closed instead (audit
    P1-KPOINTS-03).
    """
    if not hasattr(seekpath, "get_path_orig_cell"):
        raise KpointsHelperError(
            "seekpath.get_path_orig_cell is not available (seekpath < 2.0).\n"
            "        Falling back to seekpath.get_path() would write coordinates "
            "in the\n        standardized PRIMITIVE-cell basis, which silently "
            "mismatches\n        conventional cells and supercells — refusing to "
            "write (fail closed).\n        Upgrade seekpath with:\n"
            "            python scripts/kpoints_helper.py --bootstrap-deps\n"
            "            # or: pip install -U \"seekpath>=2.0\""
        )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = seekpath.get_path_orig_cell(
            structure, symprec=symprec, angle_tolerance=angle_tolerance
        )
    return path, caught


def seekpath_band(poscar_path, npoints=20, output_path="KPOINTS",
                  symprec=1e-5, angle_tolerance=-1.0,
                  declared_lattice=None, allow_supercell=False,
                  allow_tolerance_sensitive=False):
    """Use seekpath + spglib for an exact band-structure path.

    Coordinates are written in the reciprocal basis of the ORIGINAL input
    cell (seekpath.get_path_orig_cell), so the KPOINTS can be used directly
    with the user's POSCAR. seekpath.get_path() instead refers to the
    standardized PRIMITIVE cell, which silently mismatches conventional
    cells and supercells (e.g. X=(0.5,0,0.5) vs (1,0,0) for fcc).

    Guards (all fail closed — wrong k-points are worse than none):
      * repetition supercells (V >= 2x the standard conventional cell) are
        refused unless --allow-supercell (P1-KPOINTS-02); centered
        conventional cells that seekpath also flags as is_supercell are
        identified via spglib standardization and accepted;
      * a Bravais classification that changes between symprec and
        symprec x10 is refused unless --allow-tolerance-sensitive (P0-03);
      * a --lattice / POSCAR-comment declaration conflicting with the
        identified Bravais family is always refused (P0-03);
      * seekpath < 2.0 (no get_path_orig_cell) is refused (P1-KPOINTS-03).
    """
    atoms = ase.io.read(poscar_path)
    structure = (atoms.cell, atoms.get_scaled_positions(), atoms.numbers)

    path, caught = _call_seekpath(structure, symprec, angle_tolerance)

    # --- Guard 1: repetition supercell (audit P1-KPOINTS-02) ---
    # seekpath sets is_supercell / emits SupercellWarning for ANY cell larger
    # than the primitive — including the standard CONVENTIONAL cell of a
    # centered lattice (fcc 4-atom, bcc 2-atom, ...), whose orig-cell labels
    # ARE the crystal's true conventional-BZ points (standard practice, e.g.
    # the fcc Gamma-X-W-K-Gamma-L path). Only an integer repetition of the
    # standard conventional cell makes the labels meaningless (folded BZ), so
    # we distinguish via V_input / V_standard_conventional and refuse only
    # the repetition case.
    supercell_warning_cls = getattr(seekpath, "SupercellWarning", None)
    saw_supercell_warning = (
        supercell_warning_cls is not None
        and any(issubclass(w.category, supercell_warning_cls) for w in caught)
    )
    flagged_supercell = path.get("is_supercell", False) or saw_supercell_warning

    vol_ratio = _conventional_volume_ratio(structure, symprec)
    if vol_ratio is not None:
        is_repetition_supercell = vol_ratio > 1.5
    else:
        # Standardization failed: cannot distinguish conventional from
        # repetition -> fail closed when seekpath flagged a supercell.
        is_repetition_supercell = flagged_supercell

    if is_repetition_supercell:
        ratio_txt = (f"{vol_ratio:.2f}x" if vol_ratio is not None
                     else "unknown multiple of")
        if not allow_supercell:
            raise KpointsHelperError(
                "This POSCAR is a REPETITION SUPERCELL of the standard cell\n"
                f"        (volume = {ratio_txt} the standard conventional cell; "
                "SeeK-path\n        SupercellWarning / is_supercell=True).\n"
                "        The returned path would be the primitive-cell standard "
                "path\n        expressed in the supercell reciprocal basis; its "
                "labels are NOT\n        the high-symmetry points of the "
                "supercell first Brillouin zone,\n        and it is NOT a "
                "substitute for band unfolding.\n"
                "        No KPOINTS file was written.\n"
                + _SUPERCELL_OPTIONS
            )
        print("[WARN] --allow-supercell given: writing the primitive-cell standard")
        print("[WARN] path in the supercell reciprocal basis. Labels refer to the")
        print("[WARN] PRIMITIVE BZ, not the supercell BZ. Consider band unfolding.")
    elif flagged_supercell:
        print("[INFO] seekpath flags is_supercell, but the input volume matches")
        print(f"[INFO] the standard conventional cell (V/V_conv = {vol_ratio:.2f}):")
        print("[INFO] this is a centered conventional cell, and the labels are the")
        print("[INFO] crystal's true conventional-BZ high-symmetry points — the")
        print("[INFO] standard, physically correct path.")

    # --- Guard 2: tolerance-sensitive classification (audit P0-03) ---
    probe_symprec = symprec * 10.0
    probe_path = None
    probe_error = None
    try:
        probe_path, _ = _call_seekpath(structure, probe_symprec, angle_tolerance)
    except Exception as exc:  # incl. KpointsHelperError / spglib failures
        probe_error = exc

    sensitive = (probe_path is None
                 or _classification_key(probe_path) != _classification_key(path))
    if sensitive and not allow_tolerance_sensitive:
        lines = [
            "Bravais classification of this POSCAR is SENSITIVE to symprec:",
            f"          symprec {symprec:g} -> {_classification_desc(path)}",
        ]
        if probe_path is not None:
            lines.append(
                f"          symprec {probe_symprec:g} -> "
                f"{_classification_desc(probe_path)}"
            )
        else:
            lines.append(
                f"          symprec {probe_symprec:g} -> seekpath failed "
                f"({probe_error})"
            )
        lines += [
            "        The high-symmetry path depends on the space group; picking "
            "either",
            "        classification silently could give the WRONG path. No "
            "KPOINTS",
            "        file was written.",
            "        Re-run with a --symprec at which the classification is "
            "stable (this",
            "        script probes symprec x10), e.g. --symprec 1e-4 for "
            "slightly",
            "        distorted cells, or override with "
            "--allow-tolerance-sensitive if",
            "        you have checked the structure.",
        ]
        raise KpointsHelperError("\n".join(lines))
    if sensitive:
        print("[WARN] --allow-tolerance-sensitive given: classification changes "
              "with symprec:")
        print(f"[WARN]   symprec {symprec:g} -> {_classification_desc(path)}")
        if probe_path is not None:
            print(f"[WARN]   symprec {probe_symprec:g} -> "
                  f"{_classification_desc(probe_path)}")
        print("[WARN] Proceeding with the classification at the requested symprec.")

    # --- Guard 3: declared lattice vs identified Bravais family (P0-03) ---
    identified_family = bravais_family(path.get("bravais_lattice"))
    check_declared_lattice(
        declared_lattice,
        identified_family,
        _classification_desc(path),
        "--lattice / POSCAR comment",
    )

    # --- All guards passed: write the file ---
    with open(output_path, 'w') as f:
        f.write("Band structure (seekpath)\n")
        f.write(f"{npoints}\n")
        f.write("Line-mode\n")
        f.write("rec\n")

        kpoints = path["point_coords"]
        for p1_name, p2_name in path["path"]:
            p1 = kpoints[p1_name]
            p2 = kpoints[p2_name]
            f.write(f"{p1[0]:.6f} {p1[1]:.6f} {p1[2]:.6f} {p1_name}\n")
            f.write(f"{p2[0]:.6f} {p2[1]:.6f} {p2[2]:.6f} {p2_name}\n")

    print(f"[OK] Wrote seekpath KPOINTS to {output_path}")
    print(f"      Space group: {path.get('spacegroup_number', 'N/A')} "
          f"({path.get('spacegroup_international', 'N/A')})")
    print(f"      Bravais lattice: {path.get('bravais_lattice', 'N/A')}")
    print(f"      symprec: {symprec:g} (stability probed at {probe_symprec:g})")
    print(f"      Coordinate basis: reciprocal of the original input cell")


def main():
    parser = argparse.ArgumentParser(
        description="KPOINTS helper for input-build. Dependencies (ase, spglib, "
                    "seekpath>=2.0) are never auto-installed; run with "
                    "--bootstrap-deps once to install pinned versions."
    )
    parser.add_argument("--poscar", required=True, help="Path to POSCAR/CONTCAR")
    parser.add_argument("--spacing", type=float, default=0.20,
                        help="k-spacing in Angstrom^-1 (default: 0.20)")
    parser.add_argument("--scheme", choices=["MP", "Gamma", "AUTO"],
                        default="AUTO", help="k-point scheme")
    parser.add_argument("--band-structure", action="store_true",
                        help="Generate line-mode KPOINTS for band structure")
    parser.add_argument("--npoints", type=int, default=20,
                        help="Number of points per line segment (band)")
    parser.add_argument("--vacuum-axis", choices=["x", "y", "z", "none"],
                        default="none", help="Axis with vacuum (set k=1)")
    parser.add_argument("--symprec", type=float, default=1e-5,
                        help="Symmetry tolerance passed to seekpath/spglib "
                             "(default: 1e-5; try 1e-4 for slightly distorted "
                             "cells)")
    parser.add_argument("--angle-tolerance", type=float, default=-1.0,
                        help="Angle tolerance in degrees passed to "
                             "seekpath/spglib (default: -1.0 = spglib automatic)")
    parser.add_argument("--lattice", choices=_LATTICE_CHOICES, default=None,
                        help="Declare the expected crystal family; aborts if it "
                             "conflicts with the identified Bravais lattice")
    parser.add_argument("--allow-supercell", action="store_true",
                        help="Allow a band path for supercells (labels refer to "
                             "the primitive BZ — use with care)")
    parser.add_argument("--allow-tolerance-sensitive", action="store_true",
                        help="Proceed even if the Bravais classification changes "
                             "between symprec and symprec x10")
    parser.add_argument("-o", "--output", default="KPOINTS",
                        help="Output file name")
    args = parser.parse_args()

    if args.symprec <= 0:
        print(f"[ERROR] --symprec must be positive, got {args.symprec}")
        sys.exit(1)

    if not os.path.exists(args.poscar):
        print(f"[ERROR] File not found: {args.poscar}")
        sys.exit(1)

    try:
        a, b, c = read_poscar_lattice(args.poscar)
    except PoscarScalingError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    b1, b2, b3 = reciprocal_vectors(a, b, c)

    lat_type, na, nb, nc, alpha, beta, gamma = classify_lattice(a, b, c)
    print(f"[INFO] Lattice type: {lat_type}")
    print(f"       a={na:.4f}, b={nb:.4f}, c={nc:.4f} A")
    print(f"       alpha={alpha:.2f}, beta={beta:.2f}, gamma={gamma:.2f} deg")
    print(f"       |b1|={norm(b1):.4f}, |b2|={norm(b2):.4f}, |b3|={norm(b3):.4f} A^-1")

    # User-declared crystal family: --lattice wins over the POSCAR comment line
    declared = args.lattice or read_poscar_comment_lattice(args.poscar)

    if args.band_structure:
        try:
            seekpath_band(
                args.poscar, args.npoints, args.output,
                symprec=args.symprec, angle_tolerance=args.angle_tolerance,
                declared_lattice=declared,
                allow_supercell=args.allow_supercell,
                allow_tolerance_sensitive=args.allow_tolerance_sensitive,
            )
        except KpointsHelperError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        return

    # Mesh mode: a declared family must match the geometric classification
    try:
        check_declared_lattice(
            declared, lat_type,
            f"geometric classification '{lat_type}' (a={na:.3f}, b={nb:.3f}, "
            f"c={nc:.3f} A)",
            "--lattice / POSCAR comment",
        )
    except KpointsHelperError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Auto mesh generation
    k1, k2, k3 = compute_kmesh(b1, b2, b3, args.spacing)

    # Handle vacuum axis
    if args.vacuum_axis == "x":
        k1 = 1
    elif args.vacuum_axis == "y":
        k2 = 1
    elif args.vacuum_axis == "z":
        k3 = 1

    scheme = args.scheme
    if scheme == "AUTO":
        has_vacuum = args.vacuum_axis != "none"
        centering = bravais_centering(args.poscar, symprec=args.symprec)
        if centering:
            print(f"[INFO] Bravais centering (spglib): {centering}")
        scheme = recommend_scheme(lat_type, has_vacuum, centering)
        print(f"[INFO] Auto-selected scheme: {scheme}-centered")

    write_kpoints_auto(k1, k2, k3, scheme, args.output)
    print(f"       k-spacing ~ {args.spacing:.3f} A^-1 -> mesh {k1}x{k2}x{k3}")


if __name__ == "__main__":
    main()
