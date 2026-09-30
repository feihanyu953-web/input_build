#!/usr/bin/env python3
"""
Audit regression tests (group lammps_tpl) — content-based assertions on the
shipped LAMMPS base templates, references/lammps.md and examples L1-L9.

Covers:
  P0-01        : no active `velocity ... create 0.0` (LAMMPS aborts with
                 "Attempting to rescale a 0.0 temperature")
  P1-LAMMPS-01 : funcfl files (Cu_u3.eam / Al_u3.eam) pair with `pair_style eam`;
                 `eam/alloy` only with setfl files (*.eam.alloy)
  P1-LAMMPS-02 : no reax/c anywhere; reaxff example block carries
                 atom_style charge + fix qeq/reaxff
  P1-LAMMPS-03 : slab NPT guidance — x/y-only barostat for boundary p p f,
                 no z-only barostat example, no `iso` on slabs
  P2-03        : nve restart comment (fixes must be re-declared),
                 no POTIM in lammps_minimize.in, boundary examples use p p f
  placeholder  : no active (non-comment) line carries a `>>> USER` marker

Run from the skill directory:
    python -m unittest discover -s tests -p "test_audit_lammps_tpl.py" -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "base_templates"
EX = ROOT / "examples"

MD_TPL = TPL / "lammps_md.in"
NVE_TPL = TPL / "lammps_nve.in"
MIN_TPL = TPL / "lammps_minimize.in"
LAMMPS_TEMPLATES = (MD_TPL, NVE_TPL, MIN_TPL)

REF = ROOT / "references" / "lammps.md"

L1_IN = EX / "L1_Al_EAM_MD" / "input.md"
L1_README = EX / "L1_Al_EAM_MD" / "README.md"
L2_IN = EX / "L2_H2O_Pt_MLFF_min" / "input.minimize"
L3_IN = EX / "L3_Al_EAM_NPT" / "input.npt"
L3_README = EX / "L3_Al_EAM_NPT" / "README.md"
L4_IN = EX / "L4_H2O_MLFF_NVE" / "input.nve"
L5_IN = EX / "L5_electrolyte_efield" / "input.efield"
L6_IN = EX / "L6_CONP_electrode" / "input.conp"
L7_IN = EX / "L7_H2O_Pt_MLFF_md" / "input.mlff"
L8_IN = EX / "L8_lammps_plumed" / "in.plumed"
L9_IN = EX / "L9_lammps_neb" / "in.neb"

# All files owned by this group that must stay clean.
OWNED_INPUTS = (
    MD_TPL, NVE_TPL, MIN_TPL, REF,
    L1_IN, L2_IN, L3_IN, L4_IN, L5_IN, L6_IN, L7_IN, L8_IN, L9_IN,
)

ZERO_T = re.compile(r"velocity\s+\S+\s+create\s+0+(?:\.0+)?(?:\s|$)")
STYLE_LINE = re.compile(r"^\s*#?\s*pair_style\s+(\S+)")
COEFF_LINE = re.compile(r"^\s*#?\s*pair_coeff\s+\*\s+\*\s+(\S+)")


def read(path):
    return path.read_text(encoding="utf-8")


def active_lines(text):
    """Non-empty, non-comment lines (trailing comments kept on the line)."""
    return [ln for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def style_coeff_pairs(text):
    """Yield (pair_style, pair_coeff_file) for each style line and the next
    coeff line in the same example block (commented or active)."""
    lines = text.splitlines()
    pairs = []
    for i, ln in enumerate(lines):
        m = STYLE_LINE.match(ln)
        if not m:
            continue
        style = m.group(1)
        for nxt in lines[i + 1:i + 4]:
            if STYLE_LINE.match(nxt):
                break
            c = COEFF_LINE.match(nxt)
            if c:
                pairs.append((style, c.group(1)))
                break
    return pairs


class TestZeroTempVelocity(unittest.TestCase):
    """P0-01: velocity create 0.0 aborts real LAMMPS runs."""

    def test_no_active_zero_temp_velocity_create(self):
        for path in OWNED_INPUTS:
            for ln in active_lines(read(path)):
                self.assertIsNone(
                    ZERO_T.search(ln),
                    f"{path.relative_to(ROOT)}: active 0 K velocity line: {ln!r}")

    def test_md_npt_templates_keep_nonzero_velocity(self):
        for path in (MD_TPL,):
            self.assertRegex(
                read(path), r"velocity\s+all\s+create\s+[0-9]+\.0\s+\d+",
                f"{path.name}: missing target-temperature velocity create")


class TestEamPairing(unittest.TestCase):
    """P1-LAMMPS-01: funcfl -> eam, setfl -> eam/alloy."""

    FUNC_FL = ("Cu_u3.eam", "Al_u3.eam")

    def test_every_style_coeff_pair_matches_file_format(self):
        for path in OWNED_INPUTS:
            for style, coeff in style_coeff_pairs(read(path)):
                for func in self.FUNC_FL:
                    if coeff == func:
                        self.assertEqual(
                            style, "eam",
                            f"{path.relative_to(ROOT)}: funcfl {func} must use "
                            f"pair_style eam, got {style}")
                if coeff.endswith(".eam.alloy"):
                    self.assertEqual(
                        style, "eam/alloy",
                        f"{path.relative_to(ROOT)}: setfl {coeff} must use "
                        f"pair_style eam/alloy, got {style}")

    def test_eam_examples_use_canonical_files(self):
        for path in LAMMPS_TEMPLATES + (REF,):
            text = read(path)
            self.assertRegex(text, r"(?m)^#\s*pair_style\s+eam\s*$",
                             f"{path.name}: missing pair_style eam example")
            self.assertIn("Al99.eam.alloy", text,
                          f"{path.name}: setfl example should use Al99.eam.alloy")

    def test_L1_L3_active_eam_not_alloy(self):
        for path in (L1_IN, L3_IN):
            act = active_lines(read(path))
            styles = [ln for ln in act if ln.strip().startswith("pair_style")]
            self.assertTrue(any(re.fullmatch(r"pair_style\s+eam\s*(#.*)?", ln)
                                for ln in styles),
                            f"{path.relative_to(ROOT)}: active pair_style must be eam")
            self.assertFalse(any("eam/alloy" in ln.split("#")[0] for ln in act),
                             f"{path.relative_to(ROOT)}: active eam/alloy forbidden")

    def test_L1_L3_readmes_document_eam_pairing(self):
        for path in (L1_README, L3_README):
            text = read(path)
            self.assertIn("`pair_style eam`", text)
            self.assertNotIn("`pair_style eam/alloy`, `pair_coeff * * Al_u3.eam`",
                             text)


class TestReaxff(unittest.TestCase):
    """P1-LAMMPS-02: reax/c removed in LAMMPS 2024+; reaxff needs charge + QEq."""

    def test_no_reax_c_anywhere(self):
        for path in OWNED_INPUTS:
            self.assertNotIn("reax/c", read(path),
                             f"{path.relative_to(ROOT)}: reax/c reference remains")

    def test_reaxff_block_complete(self):
        for path in (MD_TPL, MIN_TPL):
            text = read(path)
            self.assertIn("REAXFF package", text,
                          f"{path.name}: reaxff block must name the REAXFF package")
            self.assertRegex(text, r"#\s*pair_style\s+reaxff\s+NULL",
                             f"{path.name}: missing pair_style reaxff example")
            self.assertRegex(text, r"#\s*fix\s+\S+\s+\S+\s+qeq/reaxff\s",
                             f"{path.name}: missing fix qeq/reaxff example")
            self.assertRegex(text, r"#\s*atom_style\s+charge",
                             f"{path.name}: reaxff needs atom_style charge")


class TestSlabNpt(unittest.TestCase):
    """P1-LAMMPS-03: barostat dims must match boundary periodicity."""

    def test_slab_xy_only_barostat_example_present(self):
        text = read(MD_TPL)
        self.assertRegex(
            text,
            r"#\s*fix\s+\S+\s+\S+\s+npt\s+temp\s+300\.0\s+300\.0\s+0\.05\s+"
            r"x\s+0\.0\s+0\.0\s+0\.5\s+y\s+0\.0\s+0\.0\s+0\.5",
            "md template must show an x/y-only slab barostat example")

    def test_no_z_barostat_example(self):
        text = read(MD_TPL)
        self.assertIsNone(
            re.search(r"fix\s+\S+\s+\S+\s+npt\s+temp\s+[\d.]+\s+[\d.]+\s+[\d.]+"
                      r"\s+z\s+[\d.]", text),
            "md template must not suggest barostatting the z (vacuum) direction")

    def test_iso_and_vacuum_warnings_present(self):
        text = read(MD_TPL)
        self.assertIn("boundary p p f", text)
        self.assertRegex(text, r"NEVER barostat the vacuum",
                         "slab guidance must forbid vacuum-direction barostat")
        self.assertRegex(text, r"never use `iso`",
                         "slab guidance must forbid iso on slabs")

    def test_boundary_examples_use_z_normal(self):
        for path in LAMMPS_TEMPLATES:
            text = read(path)
            self.assertIn("p p f", text,
                          f"{path.name}: slab boundary example must be p p f "
                          "(z = surface normal)")
            self.assertNotIn("p s p", text,
                             f"{path.name}: p s p implies y normal; use p p f")


class TestRestartAndMinimizeComments(unittest.TestCase):
    """P2-03: misleading comments fixed."""

    def test_nve_restart_comment_no_longer_claims_fixes_preserved(self):
        text = read(NVE_TPL)
        self.assertNotIn("preserves velocities, box, fixes", text)
        self.assertIn("re-declared", text,
                      "nve template must state fixes need re-declaration")

    def test_minimize_template_drops_potim(self):
        text = read(MIN_TPL)
        self.assertNotIn("POTIM", text,
                         "POTIM is a VASP parameter, not LAMMPS")
        self.assertIn("min_modify", text,
                      "minimize template should point to min_modify/minimize")


class TestPlaceholders(unittest.TestCase):
    """No active line may carry a >>> USER placeholder marker."""

    def test_no_active_user_marker(self):
        for path in OWNED_INPUTS:
            for ln in active_lines(read(path)):
                self.assertNotIn(
                    ">>> USER", ln,
                    f"{path.relative_to(ROOT)}: active line carries marker: {ln!r}")


if __name__ == "__main__":
    unittest.main()
