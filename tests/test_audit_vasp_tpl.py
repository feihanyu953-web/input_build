#!/usr/bin/env python3
"""
Audit-fix regression tests for the VASP template group (vasp_tpl).

Covers audit items from the 2026-07-19 internal skill audit:
  P0-02      freq template/example: IBRION=5 requires an active NSW >= 1
  P1-VASP-01 RANDOM_SEED must be three integers (VASP 6.x)
  P1-VASP-02 LANGEVIN_GAMMA comment must require one value per POTCAR species
  P1-VASP-03 NEB template/example: LCLIMB flagged as VTST-only, title de-CI
  P1-VASP-04 HSE template/example: no ICHARG=11-on-k-path band workflow
  P1-VASP-05 Bader template/example: chgsum.pl + bader -ref CHGCAR_sum flow
  P1-VASP-06 magnetic.patch Ce FM nonzero MAGMOM; 07_Fe3O4 active ferrimagnetic MAGMOM
  P1-VASP-09 optics NBANDS active; DOS NELM=1+ALGO=Normal combo fixed
  P2-02      DOS EMIN/EMAX documented as absolute grid bounds

Run:
    python -m unittest discover -s tests -p "test_audit_vasp_tpl.py" -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def active_lines(text):
    """Return lines whose first non-whitespace character is not '#'."""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def active_value(text, tag):
    """Return the raw value string of the first active `TAG = value` line, or None."""
    for ln in active_lines(text):
        m = re.match(rf"^\s*{re.escape(tag)}\s*=\s*(.+)$", ln)
        if m:
            # strip trailing inline comment
            return m.group(1).split("#")[0].strip()
    return None


class TestFreqNSW(unittest.TestCase):
    """P0-02: IBRION=5/6 finite-difference frequency needs NSW > 0."""

    def test_freq_template_has_active_nsw(self):
        text = read("base_templates/vasp_freq.incar")
        self.assertEqual(active_value(text, "NSW"), "1")
        self.assertEqual(active_value(text, "IBRION"), "5")

    def test_freq_example12_has_active_nsw(self):
        text = read("examples/12_Pt100_freq/INCAR")
        self.assertEqual(active_value(text, "NSW"), "1")

    def test_freq_example12_readme_corrected(self):
        text = read("examples/12_Pt100_freq/README.md")
        self.assertNotIn("NSW` is not used", text)
        self.assertNotIn("NSW is not used", text)
        self.assertIn("NSW > 0", text)


class TestMdRandomSeedAndGamma(unittest.TestCase):
    """P1-VASP-01 / P1-VASP-02."""

    def _check_seed(self, rel):
        val = active_value(read(rel), "RANDOM_SEED")
        self.assertIsNotNone(val, f"{rel}: no active RANDOM_SEED")
        parts = val.split()
        self.assertEqual(len(parts), 3, f"{rel}: RANDOM_SEED must be three integers, got {val!r}")
        for p in parts:
            self.assertRegex(p, r"^-?\d+$", f"{rel}: non-integer seed component {p!r}")

    def test_md_template_seed_three_ints(self):
        self._check_seed("base_templates/vasp_md.incar")
        self._check_seed("base_templates/vasp_slowgrowth.incar")

    def test_example06_seed_three_ints(self):
        self._check_seed("examples/06_Pt100_aimd/INCAR")

    def test_md_template_gamma_comment_per_species(self):
        text = read("base_templates/vasp_md.incar")
        self.assertIn("one value per POTCAR species", text)
        self.assertIn("NTYP", text)

    def test_example06_gamma_is_array(self):
        val = active_value(read("examples/06_Pt100_aimd/INCAR"), "LANGEVIN_GAMMA")
        self.assertIsNotNone(val)
        self.assertEqual(len(val.split()), 5, "06 example: expect 5 gamma values (Pt O H Na N)")


class TestNebVtst(unittest.TestCase):
    """P1-VASP-03: LCLIMB is VTST-only; template title must not claim CI-NEB."""

    def test_neb_template_vtst_warning(self):
        text = read("base_templates/vasp_neb.incar")
        self.assertIn("VTST EXTENSION TAG", text)
        self.assertIn("stock VASP", text)
        # header title must not advertise CI-NEB
        header = text.splitlines()[1]
        self.assertNotIn("CI-NEB Transition", header)
        self.assertIn("NEB", header)

    def test_neb_example10_vtst_warning(self):
        text = read("examples/10_Al_NEB/INCAR")
        self.assertIn("VTST", text)
        self.assertIn("stock VASP", text)
        header = text.splitlines()[1]
        self.assertNotIn("CI-NEB Transition", header)

    def test_neb_example10_readme_vtst_note(self):
        text = read("examples/10_Al_NEB/README.md")
        self.assertIn("VTST", text)


class TestHseBandWorkflow(unittest.TestCase):
    """P1-VASP-04: hybrid bands cannot use ICHARG=11 fixed-density k-path."""

    def _check(self, rel):
        text = read(rel)
        # the old affirmative recommendation must be gone
        self.assertNotRegex(text, r"For band structures: run PBE SCF")
        self.assertIn("zero-weight", text)
        self.assertIn("KPOINTS_OPT", text)
        self.assertIn("Fock operator", text)

    def test_hse_template(self):
        self._check("base_templates/vasp_hse.incar")

    def test_hse_example09(self):
        self._check("examples/09_Al_HSE06/INCAR")


class TestBaderFlow(unittest.TestCase):
    """P1-VASP-05: standard chgsum.pl + bader -ref CHGCAR_sum flow."""

    def _check(self, rel):
        text = read(rel)
        self.assertIn("chgsum.pl AECCAR0 AECCAR2", text)
        self.assertIn("bader CHGCAR -ref CHGCAR_sum", text)
        # no suggested command of the form "$ bader AECCAR0 AECCAR2"
        self.assertNotRegex(text, r"\$\s*bader\s+AECCAR0\s+AECCAR2")
        # no suggestion to use a single AECCAR file as reference
        self.assertNotIn("-ref AECCAR0", text)
        self.assertNotIn("-ref AECCAR2", text)

    def test_bader_template(self):
        self._check("base_templates/vasp_bader.incar")

    def test_bader_example11(self):
        self._check("examples/11_Al_bader/INCAR")

    def test_bader_example11_readme(self):
        self._check("examples/11_Al_bader/README.md")


class TestMagnetic(unittest.TestCase):
    """P1-VASP-06: no all-zero 'FM' MAGMOM; 07 example uses active ferrimagnetic MAGMOM."""

    def test_magnetic_patch_no_all_zero_ce(self):
        text = read("modifiers/magnetic.patch")
        self.assertNotIn("27*0 54*0 2*0 1*0 1*0", text)
        self.assertIn("2*1.0", text)  # Ce3+ get nonzero initial moments
        self.assertIn("magnetic ordering", text)

    def test_fe3o4_active_ferrimagnetic_magmom(self):
        text = read("examples/07_Fe3O4_magnetic/INCAR")
        val = active_value(text, "MAGMOM")
        self.assertIsNotNone(val, "07_Fe3O4: MAGMOM must be an active line")
        self.assertEqual(val, "8*5.0 16*-5.0 32*0.0")
        self.assertEqual(active_value(text, "ISPIN"), "2")


class TestOpticsAndDos(unittest.TestCase):
    """P1-VASP-09 + P2-02."""

    def test_optics_template_active_nbands(self):
        text = read("base_templates/vasp_optics.incar")
        val = active_value(text, "NBANDS")
        self.assertIsNotNone(val, "vasp_optics.incar: NBANDS must be an active line")
        self.assertTrue(val.isdigit() and int(val) > 0)
        self.assertIn("2-3x", text.replace("~2-3x", "2-3x"))

    def test_optics_examples_active_nbands(self):
        for rel, expect in (
            ("examples/13_Si_optics/INCAR", "32"),
            ("examples/17_TiO2_optics/INCAR", "288"),
        ):
            with self.subTest(rel=rel):
                self.assertEqual(active_value(read(rel), "NBANDS"), expect)

    def test_dos_nelm_not_one(self):
        text = read("base_templates/vasp_dos.incar")
        val = active_value(text, "NELM")
        self.assertIsNotNone(val)
        self.assertGreater(int(val), 1, "NELM=1 + ALGO=Normal under-diagonalizes on dense k-mesh")
        self.assertIn("ALGO=None", text)  # comment documents the only sane NELM=1 combo

    def test_dos_emin_emax_absolute(self):
        text = read("base_templates/vasp_dos.incar")
        self.assertNotIn("relative to E-fermi", text)
        self.assertIn("ABSOLUTE", text)


class TestNoActiveUserPlaceholders(unittest.TestCase):
    """Shared placeholder rule: no active (non-comment) '>>> USER' lines in VASP files."""

    def test_no_active_user_marker(self):
        files = list((ROOT / "base_templates").glob("vasp_*.incar"))
        files.append(ROOT / "modifiers" / "magnetic.patch")
        for n in range(1, 21):
            for ex in (ROOT / "examples").glob(f"{n:02d}_*"):
                files.extend(ex.glob("INCAR"))
        for f in files:
            if not f.exists():
                continue
            for ln in active_lines(f.read_text(encoding="utf-8")):
                self.assertNotIn(">>> USER", ln, f"{f.relative_to(ROOT)}: active >>> USER marker")


if __name__ == "__main__":
    unittest.main()
