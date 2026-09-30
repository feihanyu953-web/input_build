#!/usr/bin/env python3
"""
Audit-regression tests for the CP2K template group (cp2k_tpl).

Covers audit items from the 2026-07-19 internal skill audit:
  - P1-CP2K-02: `&ADDED_MOS` (section syntax) must not appear anywhere;
    ADDED_MOS is a keyword of &SCF, not a section.
  - P0-07: cp2k_band.inp general k-mesh must use WAVEFUNCTIONS COMPLEX.
  - P0-04: cp2k_cell_opt.inp TYPE DIRECT_CELL_OPT must carry a CP2K 2026.2
    version-gate comment.
  - P0-05: C2 molecule example must pair PERIODIC NONE with a compatible
    POISSON_SOLVER.
  - P0-06: C11 optics example must be a Gamma-only OT workflow (no k-mesh,
    no OT+kpoints+LINRES mix).
  - P1-CP2K-01: cp2k_dftu.inp / C10 must enable UKS and use two Fe kinds
    with opposite MAGNETIZATION initial guesses.
  - P1-CP2K-03: DFT+U Gamma-only statement must be version-gated (2026.2).
  - P1-CP2K-04: cp2k_workfunction.inp must offer SURFACE_DIPOLE_CORRECTION
    + SURF_DIP_DIR.
  - Placeholder hygiene: no ACTIVE (non-comment) line in the CP2K templates
    or C1-C15 examples may contain the '>>> USER' marker.

2026.1 runtime-evidence follow-ups (FORCES/TRAJECTORY section placement,
workfunction &V_HARTREE_CUBE vs &PLANAR_AVERAGED_V_HARTREE version gate,
NEB SUBSYS coordinate source, PDOS-vs-KPOINTS mutual exclusion) are covered
in tests/test_audit_phase4b.py (template + example level, incl. validator
positive/negative cases).

Run from the skill directory:
    python -m unittest discover -s tests -p "test_audit_cp2k_tpl.py" -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "base_templates"
EXAMPLES = ROOT / "examples"
REFERENCES = ROOT / "references"

CP2K_TEMPLATES = sorted(TEMPLATES.glob("cp2k_*.inp"))
C_EXAMPLE_INPUTS = sorted(
    p
    for d in EXAMPLES.iterdir()
    if d.is_dir() and re.fullmatch(r"C\d+_.*", d.name)
    for p in d.glob("*.inp")
)

# The 8 templates that previously carried the wrong `&ADDED_MOS` form
ADDED_MOS_TEMPLATES = [
    "cp2k_cell_opt.inp",
    "cp2k_dftu.inp",
    "cp2k_elf.inp",
    "cp2k_geo_opt.inp",
    "cp2k_hirshfeld.inp",
    "cp2k_optics.inp",
    "cp2k_scf.inp",
    "cp2k_workfunction.inp",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def active_lines(text: str):
    """Yield lines that are not full-line comments (CP2K '#' comments)."""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("!"):
            continue
        yield line


class TestAddedMosKeywordForm(unittest.TestCase):
    """P1-CP2K-02: ADDED_MOS is a keyword, never a section."""

    def test_templates_have_no_added_mos_section_syntax(self):
        for name in ADDED_MOS_TEMPLATES:
            text = read(TEMPLATES / name)
            self.assertNotIn(
                "&ADDED_MOS", text,
                f"{name} still contains '&ADDED_MOS' (section syntax)",
            )

    def test_reference_has_no_added_mos_section_syntax(self):
        text = read(REFERENCES / "cp2k.md")
        self.assertNotIn("&ADDED_MOS", text)

    def test_no_added_mos_section_anywhere_in_cp2k_templates(self):
        for path in CP2K_TEMPLATES:
            self.assertNotIn("&ADDED_MOS", read(path), path.name)


class TestBandWavefunctions(unittest.TestCase):
    """P0-07: general 4x4x4 MP mesh requires COMPLEX wavefunctions."""

    def test_band_template_uses_complex(self):
        text = read(TEMPLATES / "cp2k_band.inp")
        active = "\n".join(active_lines(text))
        self.assertIn("WAVEFUNCTIONS COMPLEX", active)
        self.assertNotRegex(active, r"WAVEFUNCTIONS\s+REAL")


class TestCellOptVersionGate(unittest.TestCase):
    """P0-04: TYPE DIRECT_CELL_OPT removed in CP2K 2026.2 -> gate comment."""

    def test_template_cell_opt_type_is_version_gated(self):
        text = read(TEMPLATES / "cp2k_cell_opt.inp")
        self.assertIn("TYPE         DIRECT_CELL_OPT", text)
        self.assertIn("2026.2", text)

    def test_c5_example_type_is_version_gated(self):
        text = read(EXAMPLES / "C5_CP2K_Al_cell_opt" / "cp2k_cell_opt.inp")
        self.assertIn("TYPE         DIRECT_CELL_OPT", text)
        self.assertIn("2026.2", text)


class TestPoissonSolverPairing(unittest.TestCase):
    """P0-05: PERIODIC NONE/XY must come with a compatible POISSON_SOLVER."""

    def test_c2_molecule_has_compatible_solver(self):
        text = read(EXAMPLES / "C2_CP2K_H2O_opt" / "cp2k_geo_opt.inp")
        m = re.search(r"&POISSON(.*?)&END POISSON", text, re.S)
        self.assertIsNotNone(m, "C2 example has no &POISSON section")
        block = m.group(1)
        self.assertIn("PERIODIC NONE", block)
        self.assertRegex(
            block, r"POISSON_SOLVER\s+(ANALYTIC|MT|WAVELET)",
            "C2 PERIODIC NONE lacks a 0D-compatible POISSON_SOLVER",
        )

    def test_geo_opt_template_documents_atomic_block(self):
        text = read(TEMPLATES / "cp2k_geo_opt.inp")
        self.assertIn("POISSON_SOLVER", text)
        self.assertIn("ANALYTIC", text)

    def test_reference_documents_atomic_block(self):
        text = read(REFERENCES / "cp2k.md")
        self.assertIn("POISSON_SOLVER", text)
        self.assertIn("ANALYTIC", text)


class TestOpticsGammaOnly(unittest.TestCase):
    """P0-06: optics example must not mix OT + k-mesh + LINRES."""

    def test_c11_has_no_kpoint_mesh(self):
        text = read(EXAMPLES / "C11_CP2K_Si_optics" / "Si_optics.inp")
        active = "\n".join(active_lines(text))
        self.assertNotIn("&KPOINTS", active)
        self.assertNotIn("MONKHORST-PACK", active)

    def test_c11_keeps_ot_and_linres(self):
        text = read(EXAMPLES / "C11_CP2K_Si_optics" / "Si_optics.inp")
        active = "\n".join(active_lines(text))
        self.assertIn("&OT", active)
        self.assertIn("&LINRES", active)

    def test_c11_documents_mutually_exclusive_routes(self):
        text = read(EXAMPLES / "C11_CP2K_Si_optics" / "Si_optics.inp")
        self.assertIn("mutually exclusive", text)

    def test_optics_template_warns_about_incompatibility(self):
        text = read(TEMPLATES / "cp2k_optics.inp")
        self.assertIn("mutually exclusive", text)
        active = "\n".join(active_lines(text))
        self.assertNotIn("MONKHORST-PACK", active)


class TestDftuMagnetism(unittest.TestCase):
    """P1-CP2K-01: DFT+U needs UKS + AFM initial guess; P1-CP2K-03 gate."""

    def test_dftu_template_uks_and_afm_kinds(self):
        text = read(TEMPLATES / "cp2k_dftu.inp")
        self.assertIn("UKS .TRUE.", text)
        self.assertIn("&KIND Fe1", text)
        self.assertIn("&KIND Fe2", text)
        self.assertRegex(text, r"MAGNETIZATION\s+4\.0")
        self.assertRegex(text, r"MAGNETIZATION\s+-4\.0")

    def test_dftu_template_gamma_only_is_version_gated(self):
        text = read(TEMPLATES / "cp2k_dftu.inp")
        self.assertIn("2026.2", text)
        self.assertNotIn("does NOT support k-points: use GAMMA only", text)

    def test_c10_uks_and_afm_kinds(self):
        text = read(EXAMPLES / "C10_CP2K_FeO_dftu" / "FeO_dftu.inp")
        self.assertIn("UKS .TRUE.", text)
        self.assertIn("&KIND Fe1", text)
        self.assertIn("&KIND Fe2", text)
        self.assertRegex(text, r"MAGNETIZATION\s+4\.0")
        self.assertRegex(text, r"MAGNETIZATION\s+-4\.0")

    def test_c10_xyz_labels_match_kinds(self):
        text = read(EXAMPLES / "C10_CP2K_FeO_dftu" / "FeO.xyz")
        self.assertIn("Fe1", text)
        self.assertIn("Fe2", text)

    def test_c10_gamma_only_is_version_gated(self):
        text = read(EXAMPLES / "C10_CP2K_FeO_dftu" / "FeO_dftu.inp")
        self.assertIn("2026.2", text)


class TestWorkfunctionDipoleCorrection(unittest.TestCase):
    """P1-CP2K-04: optional surface dipole correction block."""

    def test_workfunction_template_offers_dipole_correction(self):
        text = read(TEMPLATES / "cp2k_workfunction.inp")
        self.assertIn("SURFACE_DIPOLE_CORRECTION", text)
        self.assertIn("SURF_DIP_DIR", text)
        # Must remain opt-in (commented out) — symmetric slabs are the default
        active = "\n".join(active_lines(text))
        self.assertNotRegex(active, r"SURFACE_DIPOLE_CORRECTION\s+\.TRUE\.")


class TestPlaceholderHygiene(unittest.TestCase):
    """No ACTIVE line in CP2K templates or C1-C15 examples may carry the
    '>>> USER' placeholder marker (commented guidance is allowed)."""

    def test_no_active_user_marker_in_templates(self):
        for path in CP2K_TEMPLATES:
            for line in active_lines(read(path)):
                self.assertNotIn(">>> USER", line, f"{path.name}: {line!r}")

    def test_no_active_user_marker_in_c_examples(self):
        self.assertTrue(C_EXAMPLE_INPUTS, "no C1-C15 example inputs found")
        for path in C_EXAMPLE_INPUTS:
            for line in active_lines(read(path)):
                self.assertNotIn(">>> USER", line, f"{path}: {line!r}")


if __name__ == "__main__":
    unittest.main()
