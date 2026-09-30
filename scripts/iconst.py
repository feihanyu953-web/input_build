#!/usr/bin/env python3
"""
ICONST file model for VASP constrained MD / slow-growth (SG-AIMD).

Owns the ICONST syntax tables, the parsed line/file model, the controlled-
parameter count and geometry evaluation of collective variables. Stdlib only.

Official semantics this module encodes (vasp.at/wiki ICONST, INCREM):
  * one coordinate per line: `flag item(1) ... item(N) status`
  * complex coordinates (S/C/D/IS/IZ) come AFTER every primitive and take one
    coefficient per preceding primitive
  * once a complex coordinate exists, the status of every primitive is IGNORED
    (primitives are only the basis) -> this drives n_controlled()
  * INCREM needs exactly one value per controlled (STATUS=0) parameter

Consumers: scripts/validate_input.py (via lazy import) and
scripts/iconst_helper.py. Issues are plain dicts, not Finding objects, so this
module stays independent of the validator.
"""

import math
import os

# --- flag tables ----------------------------------------------------------
# Primitive flags -> total item count (excluding the trailing status).
PRIMITIVE_FLAGS = {
    "R": 2,    # interatomic distance
    "A": 3,    # angle, item(2) is the apex
    "T": 4,    # torsional angle
    "M": 3,    # atom to bond-centre distance
    "B": 4,    # bond-centre to bond-centre distance
    "P": 4,    # ratio of two bond lengths
    "W": 5,    # switching function: 2 atoms + c + M + N
    "X": 1, "Y": 1, "Z": 1,          # fractional coordinate
    "cX": 1, "cY": 1, "cZ": 1,       # cartesian coordinate
    "LR": 1,   # lattice vector length
    "LA": 2,   # angle between lattice vectors
    "LV": 0,   # cell volume
}

# Number of LEADING items that are atom indices (index-range checking).
ATOM_INDEX_ARITY = {
    "R": 2, "A": 3, "T": 4, "M": 3, "B": 4, "P": 4, "W": 2,
    "X": 1, "Y": 1, "Z": 1, "cX": 1, "cY": 1, "cZ": 1,
}

COMPLEX_FLAGS = frozenset({"S", "C", "D", "IS", "IZ"})

# v1 coverage: deep checks (arity + geometry) are implemented for these only.
V1_FLAGS = frozenset({"R", "A", "T", "S", "D"})
V1_STATUS = frozenset({0, 7})
# 0 constrained, 3 HESSEMAT harmonic forcefield, 4 Fermi step, 5 metadynamics,
# 7 monitored, 8 harmonic potential (SPRING_R0/SPRING_K).
KNOWN_STATUS = frozenset({0, 3, 4, 5, 7, 8})

# Initial-value tolerances per basis kind. A single Angstrom threshold would be
# a unit error for angles (degrees) and coordination numbers (dimensionless).
TOLERANCE = {
    "distance": (0.1, "A"),
    "angle": (2.0, "deg"),
    "torsion": (2.0, "deg"),
    "dimensionless": (0.05, ""),
}

_D_EXP_LOW = 9
_D_EXP_HIGH = 14


class IconstLine:
    def __init__(self, flag, items, status, lineno, raw):
        self.flag = flag
        self.items = items
        self.status = status
        self.lineno = lineno
        self.raw = raw

    @property
    def is_complex(self):
        return self.flag in COMPLEX_FLAGS

    def __repr__(self):
        return f"IconstLine({self.flag} {self.items} status={self.status})"


class IconstFile:
    def __init__(self, lines, issues, path):
        self.lines = lines
        self.issues = issues
        self.path = path

    @property
    def primitives(self):
        return [l for l in self.lines if not l.is_complex]

    @property
    def complexes(self):
        return [l for l in self.lines if l.is_complex]

    def n_controlled(self):
        """Number of parameters INCREM must supply a value for.

        Official rule: when complex coordinates exist the primitives' status is
        ignored, so only status=0 COMPLEX rows count. Otherwise status=0
        primitive rows count.
        """
        pool = self.complexes if self.complexes else self.primitives
        return sum(1 for l in pool if l.status == 0)


def _issue(level, code, message, lineno=None):
    return {"level": level, "code": code, "message": message, "lineno": lineno}


def _as_int(token):
    try:
        return int(token)
    except (TypeError, ValueError):
        return None


def _as_float(token):
    try:
        v = float(token)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_iconst(path):
    """Parse an ICONST file. Never raises on content problems: every problem is
    an entry in .issues so callers can map them onto their own finding types."""
    lines, issues = [], []
    if not os.path.exists(path):
        return IconstFile([], [_issue("ERROR", "ICONST_UNREADABLE",
                                      f"ICONST not found: {path}")], path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        # Environment failure (e.g. a directory path passes os.path.exists on
        # Windows as PermissionError) - still a finding, never a raise.
        return IconstFile([], [_issue("ERROR", "ICONST_UNREADABLE",
                                      f"{path}: {exc}")], path)

    seen_complex = False
    for lineno, raw in enumerate(raw_lines, start=1):
        text = raw.strip()
        if not text:
            continue
        if text[0] in "#!":
            # The official ICONST documentation defines no comment syntax; VASP
            # may fail to parse such a line. Report instead of silently eating.
            issues.append(_issue(
                "WARN", "ICONST_COMMENT_UNSUPPORTED",
                f"line {lineno}: ICONST has no documented comment syntax; "
                f"VASP may fail to parse {text[:40]!r}", lineno))
            continue

        tokens = text.split()
        flag = tokens[0]
        if flag not in PRIMITIVE_FLAGS and flag not in COMPLEX_FLAGS:
            issues.append(_issue("ERROR", "ICONST_FLAG_UNKNOWN",
                                 f"line {lineno}: unknown ICONST flag {flag!r}",
                                 lineno))
            continue
        if len(tokens) < 2:
            issues.append(_issue("ERROR", "ICONST_STATUS_INVALID",
                                 f"line {lineno}: missing status field", lineno))
            continue

        status = _as_int(tokens[-1])
        if status is None:
            issues.append(_issue(
                "ERROR", "ICONST_STATUS_INVALID",
                f"line {lineno}: status must be an integer, got "
                f"{tokens[-1]!r}", lineno))
            continue
        if status not in KNOWN_STATUS:
            issues.append(_issue(
                "ERROR", "ICONST_STATUS_INVALID",
                f"line {lineno}: status={status} is not a documented ICONST "
                f"status {sorted(KNOWN_STATUS)}", lineno))
            continue
        if status not in V1_STATUS:
            issues.append(_issue(
                "WARN", "ICONST_STATUS_COVERAGE",
                f"line {lineno}: status={status} is metadynamics/harmonic-"
                "potential territory (3=HESSEMAT, 4=Fermi step, 5=metadyn, "
                "8=spring), outside slow-growth v1 coverage {0,7}", lineno))

        raw_items = tokens[1:-1]
        is_complex = flag in COMPLEX_FLAGS
        if is_complex:
            seen_complex = True
            items = [_as_float(t) for t in raw_items]
        else:
            if seen_complex:
                issues.append(_issue(
                    "ERROR", "ICONST_ORDER",
                    f"line {lineno}: primitive coordinate {flag!r} appears "
                    "after a complex coordinate; every primitive must precede "
                    "all complex coordinates", lineno))
            n_idx = ATOM_INDEX_ARITY.get(flag, 0)
            items = [(_as_int(t) if i < n_idx else _as_float(t))
                     for i, t in enumerate(raw_items)]

        if any(v is None for v in items):
            issues.append(_issue(
                "ERROR", "ICONST_ARITY",
                f"line {lineno}: unparseable item in {text!r}", lineno))
            continue

        line = IconstLine(flag, items, status, lineno, text)
        issues.extend(_check_arity(line, lines))
        lines.append(line)

    if not lines and not any(x["level"] == "ERROR" for x in issues):
        issues.append(_issue("ERROR", "ICONST_EMPTY",
                             f"{path}: no coordinate lines found"))
    return IconstFile(lines, issues, path)


def _check_arity(line, previous):
    """Arity rules. Complex coordinates take one coefficient per PRECEDING
    primitive (this is why D is not fixed at two references)."""
    out = []
    if line.flag not in V1_FLAGS:
        out.append(_issue(
            "WARN", "ICONST_FLAG_COVERAGE",
            f"line {line.lineno}: flag {line.flag!r} parses but is outside "
            "slow-growth v1 deep coverage {R,A,T,S,D}; arity and geometry "
            "checks are skipped", line.lineno))
        return out

    if line.is_complex:
        n_prim = sum(1 for l in previous if not l.is_complex)
        if n_prim == 0:
            out.append(_issue(
                "ERROR", "ICONST_ARITY",
                f"line {line.lineno}: complex coordinate {line.flag!r} needs at "
                "least one preceding primitive coordinate", line.lineno))
        elif len(line.items) != n_prim:
            out.append(_issue(
                "ERROR", "ICONST_ARITY",
                f"line {line.lineno}: {line.flag!r} needs one coefficient per "
                f"preceding primitive ({n_prim}), got {len(line.items)}",
                line.lineno))
        if line.flag == "D":
            for c in line.items:
                if c is not None and c <= 0:
                    out.append(_issue(
                        "ERROR", "ICONST_ARITY",
                        f"line {line.lineno}: D coefficients are reference "
                        f"distances and must be positive, got {c:g}",
                        line.lineno))
                    break
        return out

    want = PRIMITIVE_FLAGS[line.flag]
    if len(line.items) != want:
        out.append(_issue(
            "ERROR", "ICONST_ARITY",
            f"line {line.lineno}: {line.flag!r} takes {want} item(s), got "
            f"{len(line.items)}", line.lineno))
    return out


# --- geometry evaluation --------------------------------------------------
# structure is a validate_input.Structure: .lattice (3x3 rows), .frac (list of
# [f1,f2,f3]), .natoms. Distances use the minimum-image convention, matching
# how a periodic MD code sees a bond that straddles the cell boundary.

def _cart(structure, index1):
    """Cartesian coordinate of a 1-based atom index."""
    f = structure.frac[index1 - 1]
    lat = structure.lattice
    return [sum(f[k] * lat[k][j] for k in range(3)) for j in range(3)]


def _min_image_vector(structure, i, j):
    """Vector from atom i to atom j under the minimum-image convention.

    The per-component fractional wrap is exact only for near-orthogonal cells;
    for triclinic/hexagonal cells (e.g. the gamma=120 deg fcc(111) slab) the
    true minimum image can sit in a neighbouring lattice translation, so the
    wrapped delta is refined against the 27 surrounding images.
    """
    fi = structure.frac[i - 1]
    fj = structure.frac[j - 1]
    df = []
    for k in range(3):
        d = fj[k] - fi[k]
        d -= round(d)          # wrap into (-0.5, 0.5] (banker's rounding)
        df.append(d)
    lat = structure.lattice
    best_vec = best_norm = None
    for n1 in (-1, 0, 1):
        for n2 in (-1, 0, 1):
            for n3 in (-1, 0, 1):
                t = [df[0] + n1, df[1] + n2, df[2] + n3]
                cart = [sum(t[m] * lat[m][c] for m in range(3)) for c in range(3)]
                norm = math.sqrt(sum(v * v for v in cart))
                if best_norm is None or norm < best_norm:
                    best_vec, best_norm = cart, norm
    return best_vec


def _norm(v):
    return math.sqrt(sum(c * c for c in v))


def _angle_deg(v1, v2):
    n1, n2 = _norm(v1), _norm(v2)
    if n1 == 0 or n2 == 0:
        raise ValueError("degenerate angle: coincident atoms")
    cos = sum(a * b for a, b in zip(v1, v2)) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def evaluate_primitive(line, structure):
    """Current value of a primitive coordinate: R in Angstrom, A/T in degrees."""
    if structure is None:
        raise ValueError("structure required to evaluate a primitive coordinate")
    idx = line.items[:ATOM_INDEX_ARITY.get(line.flag, 0)]
    for i in idx:
        if not isinstance(i, int) or i < 1 or i > structure.natoms:
            raise ValueError(
                f"atom index {i} out of range 1..{structure.natoms}")

    if line.flag == "R":
        return _norm(_min_image_vector(structure, idx[0], idx[1]))
    if line.flag == "A":
        a, apex, c = idx
        return _angle_deg(_min_image_vector(structure, apex, a),
                          _min_image_vector(structure, apex, c))
    if line.flag == "T":
        # Torsion i-j-k-l via the standard b1/b2/b3 cross-product form.
        i, j, k, l = idx
        b1 = _min_image_vector(structure, i, j)
        b2 = _min_image_vector(structure, j, k)
        b3 = _min_image_vector(structure, k, l)
        n1 = _cross(b1, b2)
        n2 = _cross(b2, b3)
        m = _cross(_unit(b2), n1)
        x = sum(a * b for a, b in zip(n1, n2))
        y = sum(a * b for a, b in zip(m, n2))
        if x == 0.0 and y == 0.0:
            raise ValueError("degenerate torsion: collinear or coincident atoms")
        return math.degrees(math.atan2(y, x))
    raise ValueError(f"primitive flag {line.flag!r} is outside v1 geometry support")


def _cross(u, v):
    return [u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0]]


def _unit(v):
    n = _norm(v)
    if n == 0:
        raise ValueError("zero-length vector")
    return [c / n for c in v]


def evaluate_complex(line, primitive_values):
    """Value of a complex coordinate given its primitives' current values."""
    coeffs = line.items
    if len(coeffs) != len(primitive_values):
        raise ValueError(
            f"{line.flag}: {len(coeffs)} coefficients vs "
            f"{len(primitive_values)} primitive values")
    if line.flag == "S":
        return sum(c * q for c, q in zip(coeffs, primitive_values))
    if line.flag == "C":
        return math.sqrt(sum((c * q) ** 2 for c, q in zip(coeffs, primitive_values)))
    if line.flag == "D":
        total = 0.0
        for c, q in zip(coeffs, primitive_values):
            if c <= 0:
                raise ValueError(
                    "D reference distance must be positive; resolve the "
                    "file's ICONST_ARITY issues first")
            ratio = q / c
            if abs(ratio - 1.0) < 1e-9:
                # Removable 0/0 singularity; limit of (1-r^9)/(1-r^14) is 9/14.
                total += _D_EXP_LOW / _D_EXP_HIGH
            else:
                total += ((1.0 - ratio ** _D_EXP_LOW) /
                          (1.0 - ratio ** _D_EXP_HIGH))
        return total
    raise ValueError(f"complex flag {line.flag!r} is outside v1 geometry support")


_BASIS_BY_FLAG = {"R": "distance", "M": "distance", "B": "distance",
                  "A": "angle", "T": "torsion"}


def basis_kind(line, primitives):
    """Unit family of a coordinate, used to pick the comparison tolerance."""
    if line.flag == "D":
        return "dimensionless"
    if not line.is_complex:
        return _BASIS_BY_FLAG.get(line.flag, "dimensionless")
    kinds = {_BASIS_BY_FLAG.get(p.flag, "dimensionless") for p in primitives}
    if len(kinds) == 1:
        return kinds.pop()
    return "mixed"


def evaluate_cv(iconst_file, structure):
    """Return (value, basis_kind) for the single controlled coordinate.

    Raises ValueError when the file does not define exactly one controlled
    coordinate - the helper's --xi verification is only meaningful for one CV.
    """
    pool = (iconst_file.complexes if iconst_file.complexes
            else iconst_file.primitives)
    controlled = [l for l in pool if l.status == 0]
    if len(controlled) != 1:
        raise ValueError(
            f"expected exactly one controlled coordinate, found "
            f"{len(controlled)}; --xi verification needs a single CV")
    target = controlled[0]
    if target.is_complex:
        prim_values = [evaluate_primitive(p, structure)
                       for p in iconst_file.primitives]
        value = evaluate_complex(target, prim_values)
    else:
        value = evaluate_primitive(target, structure)
    return value, basis_kind(target, iconst_file.primitives)
