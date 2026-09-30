#!/usr/bin/env python3
"""
Phase-4b validator regression tests (scripts/validate_input.py) — 2026.1 /
6.5.1 / 22Jul2025 runtime-evidence batch:

  CP2K   (a) CP2K_MISPLACED_SECTION: &FORCES under FORCE_EVAL/DFT/PRINT ->
             ERROR (2026.1 aborts "unknown subsection FORCES of section
             PRINT"); correct home is FORCE_EVAL/PRINT. &TRAJECTORY under
             MOTION/CELL_OPT/PRINT -> ERROR; correct home is MOTION/PRINT.
         (b) CP2K workfunction version gate: &PLANAR_AVERAGED_V_HARTREE is a
             2026.2-dev trunk addition (2026.1 aborts); the task accepts
             &V_HARTREE_CUBE OR &PLANAR_AVERAGED_V_HARTREE, with a WARN on the
             latter (CP2K_WF_PLANAR_VERSION_GATE); neither -> CP2K_WF_MISSING.
         (c) CP2K_PDOS_KPOINTS: &PDOS + &KPOINTS -> WARN (2026.1 writes no
             PDOS files: "pDOS is not implemented for k points").
  LAMMPS (d) LAMMPS_TIMESTEP_HIGH shares the LAMMPS_NO_SHAKE exemption:
             fix shake / rigid makes a ~2 fs timestep legitimate (SPC/E water,
             runtime-verified).
  Shipped (e) templates/examples: no misplaced sections; workfunction
             template + C9 use active &V_HARTREE_CUBE (PLANAR commented out);
             NEB template + C6 SUBSYS carry a coordinate source.

Run from the skill directory:
    python -m unittest discover -s tests -p "test_audit_phase4b.py" -v
"""

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory
TEMPLATES = ROOT / "base_templates"
EXAMPLES = ROOT / "examples"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")

CP2K_TEMPLATES = sorted(TEMPLATES.glob("cp2k_*.inp"))
# ALL shipped example .inp files (C-series)
EXAMPLE_INPUTS = sorted(
    p
    for d in EXAMPLES.iterdir()
    if d.is_dir() and not d.name.startswith("_")
    for p in d.glob("*.inp")
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CP2K_BASE = """\
&GLOBAL
  PROJECT test
  RUN_TYPE ENERGY
&END GLOBAL
&FORCE_EVAL
  METHOD Quickstep
  &DFT
    &MGRID
      CUTOFF 400
      REL_CUTOFF 50
    &END MGRID
    &SCF
      EPS_SCF 1.0E-6
      &DIAGONALIZATION
      &END DIAGONALIZATION
    &END SCF
    &POISSON
      PERIODIC XYZ
    &END POISSON
  &END DFT
  &SUBSYS
    &CELL
      ABC 10.0 10.0 10.0
      PERIODIC XYZ
    &END CELL
    &KIND H
      BASIS_SET DZVP-MOLOPT-SR-GTH
      POTENTIAL GTH-PBE
    &END KIND
  &END SUBSYS
&END FORCE_EVAL
"""

LAMMPS_BASE = """\
units metal
atom_style atomic
boundary p p p
read_data system.data
pair_style eam/alloy
pair_coeff * * Al.eam Al
velocity all create 300.0 12345
neighbor 2.0 bin
timestep 0.0005
fix 1 all nvt temp 300.0 300.0 0.05
thermo 100
dump 1 all custom 100 traj.lammpstrj id type x y z
run 1000
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return str(p)

    def codes(self, findings):
        return {x.code for x in findings}

    def errors(self, findings):
        return [x for x in findings if x.level == vi.ERROR]

    def cp2k(self, text=CP2K_BASE, task=None):
        return vi.validate_cp2k_one(self.write("test.inp", text), task=task)

    def lammps(self, text):
        return vi.validate_lammps_one(self.write("in.test", text))


# ---------------------------------------------------------------------------
# (a) CP2K_MISPLACED_SECTION — &FORCES / &TRAJECTORY placement (2026.1 aborts)
# ---------------------------------------------------------------------------

class TestCp2kMisplacedSection(Case):
    FORCES_DFT_PRINT = CP2K_BASE.replace(
        "    &POISSON",
        "    &PRINT\n      &FORCES ON\n      &END FORCES\n    &END PRINT\n    &POISSON")
    FORCES_FE_PRINT = CP2K_BASE.replace(
        "&END FORCE_EVAL",
        "  &PRINT\n    &FORCES ON\n    &END FORCES\n  &END PRINT\n&END FORCE_EVAL")

    def test_forces_under_dft_print_is_error(self):
        findings = self.cp2k(self.FORCES_DFT_PRINT)
        hits = [x for x in findings if x.code == "CP2K_MISPLACED_SECTION"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.ERROR)
        self.assertIn("FORCE_EVAL/PRINT", hits[0].message)

    def test_forces_under_force_eval_print_clean(self):
        findings = self.cp2k(self.FORCES_FE_PRINT)
        self.assertNotIn("CP2K_MISPLACED_SECTION", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_trajectory_under_cell_opt_print_is_error(self):
        motion = ("\n&MOTION\n  &CELL_OPT\n    OPTIMIZER BFGS\n"
                  "    &PRINT\n      &TRAJECTORY\n        FORMAT XYZ\n"
                  "      &END TRAJECTORY\n    &END PRINT\n"
                  "  &END CELL_OPT\n&END MOTION\n")
        findings = self.cp2k(CP2K_BASE + motion)
        hits = [x for x in findings if x.code == "CP2K_MISPLACED_SECTION"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.ERROR)
        self.assertIn("MOTION/PRINT", hits[0].message)

    def test_trajectory_under_motion_print_clean(self):
        motion = ("\n&MOTION\n  &CELL_OPT\n    OPTIMIZER BFGS\n  &END CELL_OPT\n"
                  "  &PRINT\n    &TRAJECTORY\n      FORMAT XYZ\n"
                  "    &END TRAJECTORY\n  &END PRINT\n&END MOTION\n")
        findings = self.cp2k(CP2K_BASE + motion)
        self.assertNotIn("CP2K_MISPLACED_SECTION", self.codes(findings))

    def test_md_trajectory_under_motion_print_clean(self):
        motion = ("\n&MOTION\n  &MD\n    ENSEMBLE NVT\n    TIMESTEP 0.5\n"
                  "    STEPS 10\n  &END MD\n"
                  "  &PRINT\n    &TRAJECTORY\n      FORMAT XYZ\n"
                  "    &END TRAJECTORY\n  &END PRINT\n&END MOTION\n")
        findings = self.cp2k(CP2K_BASE + motion)
        self.assertNotIn("CP2K_MISPLACED_SECTION", self.codes(findings))


# ---------------------------------------------------------------------------
# (b) workfunction version gate: V_HARTREE_CUBE (2026.1) vs
#     PLANAR_AVERAGED_V_HARTREE (2026.2-dev+)
# ---------------------------------------------------------------------------

class TestCp2kWorkfunctionGate(Case):
    PLANAR = ("    &PLANAR_AVERAGED_V_HARTREE\n      SECTION_PARAMETERS ON\n"
              "      PARALLEL_PLANE XY\n    &END PLANAR_AVERAGED_V_HARTREE\n")
    CUBE_PRINT = ("    &PRINT\n      &V_HARTREE_CUBE ON\n      &END V_HARTREE_CUBE\n"
                  "    &END PRINT\n")

    def _insert_in_dft(self, base, block):
        return base.replace("    &POISSON", block + "    &POISSON")

    def test_neither_section_is_error(self):
        findings = self.cp2k(task="workfunction")
        self.assertIn("CP2K_WF_MISSING", self.codes(findings))

    def test_v_hartree_cube_clean(self):
        findings = self.cp2k(self._insert_in_dft(CP2K_BASE, self.CUBE_PRINT),
                             task="workfunction")
        self.assertNotIn("CP2K_WF_MISSING", self.codes(findings))
        self.assertNotIn("CP2K_WF_PLANAR_VERSION_GATE", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_planar_alone_warns_version_gate_no_error(self):
        findings = self.cp2k(self._insert_in_dft(CP2K_BASE, self.PLANAR),
                             task="workfunction")
        hits = [x for x in findings if x.code == "CP2K_WF_PLANAR_VERSION_GATE"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.WARN)
        self.assertIn("2026.2", hits[0].message)
        self.assertNotIn("CP2K_WF_MISSING", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_planar_plus_cube_still_warns_but_no_error(self):
        findings = self.cp2k(
            self._insert_in_dft(CP2K_BASE, self.PLANAR + self.CUBE_PRINT),
            task="workfunction")
        self.assertIn("CP2K_WF_PLANAR_VERSION_GATE", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_v_hartree_cube_off_does_not_satisfy(self):
        off = self.CUBE_PRINT.replace("V_HARTREE_CUBE ON", "V_HARTREE_CUBE OFF")
        findings = self.cp2k(self._insert_in_dft(CP2K_BASE, off),
                             task="workfunction")
        self.assertIn("CP2K_WF_MISSING", self.codes(findings))


# ---------------------------------------------------------------------------
# (c) CP2K_PDOS_KPOINTS — &PDOS + &KPOINTS writes no PDOS files on 2026.1
# ---------------------------------------------------------------------------

class TestCp2kPdosKpoints(Case):
    PDOS_PRINT = ("    &PRINT\n      &PDOS\n        NLUMO -1\n      &END PDOS\n"
                  "    &END PRINT\n")
    KPOINTS = ("    &KPOINTS\n      SCHEME MONKHORST-PACK 4 4 4\n"
               "    &END KPOINTS\n")

    def _insert_in_dft(self, base, block):
        return base.replace("    &POISSON", block + "    &POISSON")

    def test_pdos_with_kpoints_warns(self):
        findings = self.cp2k(
            self._insert_in_dft(CP2K_BASE, self.KPOINTS + self.PDOS_PRINT))
        hits = [x for x in findings if x.code == "CP2K_PDOS_KPOINTS"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.WARN)
        self.assertIn("pDOS is not implemented for k points", hits[0].message)

    def test_pdos_gamma_only_clean(self):
        findings = self.cp2k(self._insert_in_dft(CP2K_BASE, self.PDOS_PRINT),
                             task="dos")
        self.assertNotIn("CP2K_PDOS_KPOINTS", self.codes(findings))

    def test_kpoints_without_pdos_clean(self):
        findings = self.cp2k(self._insert_in_dft(CP2K_BASE, self.KPOINTS))
        self.assertNotIn("CP2K_PDOS_KPOINTS", self.codes(findings))


# ---------------------------------------------------------------------------
# (d) LAMMPS_TIMESTEP_HIGH — shake/rigid exemption (aligned with NO_SHAKE)
# ---------------------------------------------------------------------------

class TestLammpsTimestepShakeExempt(Case):
    SHAKE = "fix 2 water shake 1.0e-4 20 10 b 1 a 1\n"

    def _two_fs(self, text):
        return text.replace("timestep 0.0005", "timestep 0.002")  # 2 fs, metal

    def _before_run(self, text, fix_line):
        return text.replace("run 1000\n", fix_line + "run 1000\n")

    def test_two_fs_with_shake_no_timestep_warn(self):
        findings = self.lammps(
            self._before_run(self._two_fs(LAMMPS_BASE), self.SHAKE))
        self.assertNotIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_two_fs_without_shake_warns(self):
        findings = self.lammps(self._two_fs(LAMMPS_BASE))
        self.assertIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_two_fs_with_rigid_no_timestep_warn(self):
        text = self._before_run(
            self._two_fs(LAMMPS_BASE), "fix 2 water rigid/small molecule\n")
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_two_fs_units_real_with_shake_no_warn(self):
        # runtime-verified case: SPC/E water, units real, fix shake, 2 fs
        text = self._before_run(
            LAMMPS_BASE.replace("units metal", "units real")
                        .replace("timestep 0.0005", "timestep 2.0"),
            self.SHAKE)
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))


# ---------------------------------------------------------------------------
# (e) Shipped templates / C examples must satisfy the new rules
# ---------------------------------------------------------------------------

class TestShippedHierarchyClean(unittest.TestCase):
    def test_no_forces_under_dft_print_anywhere(self):
        for path in list(CP2K_TEMPLATES) + list(EXAMPLE_INPUTS):
            root = vi.parse_cp2k(str(path))
            for node in root.find_all("FORCES"):
                self.assertFalse(
                    node.path.endswith("DFT/PRINT/FORCES"),
                    f"{path.relative_to(ROOT)}: &FORCES at {node.path}")

    def test_no_trajectory_under_cell_opt_print_anywhere(self):
        for path in list(CP2K_TEMPLATES) + list(EXAMPLE_INPUTS):
            root = vi.parse_cp2k(str(path))
            for node in root.find_all("TRAJECTORY"):
                self.assertFalse(
                    node.path.endswith("CELL_OPT/PRINT/TRAJECTORY"),
                    f"{path.relative_to(ROOT)}: &TRAJECTORY at {node.path}")

    def test_workfunction_template_and_c9_use_cube_route(self):
        for path in (TEMPLATES / "cp2k_workfunction.inp",
                     EXAMPLES / "C9_CP2K_workfunction" / "cp2k_workfunction.inp"):
            root = vi.parse_cp2k(str(path))
            cubes = [n for n in root.find_all("V_HARTREE_CUBE")
                     if (n.param or "ON").upper() != "OFF"]
            self.assertTrue(cubes, f"{path.name}: no active &V_HARTREE_CUBE")
            self.assertFalse(root.find_all("PLANAR_AVERAGED_V_HARTREE"),
                             f"{path.name}: PLANAR_AVERAGED_V_HARTREE must be "
                             "commented out (2026.2-dev+ only)")
            text = path.read_text(encoding="utf-8")
            self.assertIn("2026.2", text, f"{path.name}: missing version-gate note")
            self.assertIn("PLANAR_AVERAGED_V_HARTREE", text,
                          f"{path.name}: commented 2026.2+ option must be kept")

    def test_neb_template_and_c6_subsys_have_coordinate_source(self):
        for path in (TEMPLATES / "cp2k_neb.inp",
                     EXAMPLES / "C6_CP2K_Al_NEB" / "cp2k_neb.inp"):
            root = vi.parse_cp2k(str(path))
            subsys_list = root.find_all("SUBSYS")
            self.assertTrue(subsys_list, f"{path.name}: no &SUBSYS")
            subsys = subsys_list[0]
            has_coords = bool(subsys.find_all("TOPOLOGY") or subsys.find_all("COORD"))
            self.assertTrue(has_coords,
                            f"{path.name}: NEB &SUBSYS lacks a coordinate source "
                            "(2026.1 aborts in topology.F without one)")

    def test_dos_template_and_c7_pdos_have_no_active_kpoints(self):
        for path in (TEMPLATES / "cp2k_dos.inp",
                     EXAMPLES / "C7_CP2K_dos" / "cp2k_dos.inp"):
            root = vi.parse_cp2k(str(path))
            self.assertTrue(root.find_all("PDOS"), f"{path.name}: no &PDOS")
            self.assertFalse(root.find_all("KPOINTS"),
                             f"{path.name}: &PDOS example must not carry an "
                             "active &KPOINTS (2026.1 writes no PDOS files)")


if __name__ == "__main__":
    unittest.main()
