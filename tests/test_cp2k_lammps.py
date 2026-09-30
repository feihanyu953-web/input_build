#!/usr/bin/env python3
"""
Tests for the CP2K and LAMMPS validators in scripts/validate_input.py.

Includes the P0 regression guards:
  - &BAND_STRUCTURE under &MOTION must fail (it belongs in FORCE_EVAL/DFT/PRINT)
  - CP2K DFT+U without PLUS_U_METHOD must fail

Run:
    python -m unittest discover -s tests -v          # from the skill directory
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")


CP2K_BASE = """\
&GLOBAL
  PROJECT test
  RUN_TYPE ENERGY_FORCE
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
    &KIND O
      BASIS_SET DZVP-MOLOPT-SR-GTH
      POTENTIAL GTH-PBE
    &END KIND
  &END SUBSYS
&END FORCE_EVAL
"""

H2O_XYZ = """\
3
water
O 0.0 0.0 0.0
H 0.76 0.58 0.0
H -0.76 0.58 0.0
"""

LAMMPS_OK = """\
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
        p.write_text(content, encoding="utf-8")
        return str(p)

    def codes(self, findings):
        return {x.code for x in findings}

    def cp2k(self, text=CP2K_BASE, xyz=None, task=None):
        path = self.write("test.inp", text)
        xyz_path = self.write("coord.xyz", xyz) if xyz else None
        return vi.validate_cp2k_one(path, xyz_path, task)


# ---------------------------------------------------------------------------
# CP2K
# ---------------------------------------------------------------------------

class TestCp2k(Case):
    def test_clean_base_passes(self):
        self.assertEqual(self.cp2k(xyz=H2O_XYZ), [])

    def test_kind_missing_is_error(self):
        findings = self.cp2k(xyz="3\nx\nO 0 0 0\nH 0 0 1\nC 0 1 0\n")
        self.assertIn("CP2K_KIND_MISSING", self.codes(findings))
        self.assertTrue(any("C" in x.message for x in findings))

    def test_periodic_mismatch_is_error(self):
        text = CP2K_BASE.replace("      PERIODIC XYZ\n    &END POISSON",
                                 "      PERIODIC NONE\n    &END POISSON")
        findings = self.cp2k(text)
        self.assertIn("CP2K_PERIODIC_MISMATCH", self.codes(findings))

    def test_slab_xy_xyz_is_warn_not_error(self):
        text = CP2K_BASE.replace("      PERIODIC XYZ\n    &END POISSON",
                                 "      PERIODIC XY\n    &END POISSON")
        findings = self.cp2k(text)
        self.assertIn("CP2K_PERIODIC_SLAB", self.codes(findings))
        self.assertNotIn("CP2K_PERIODIC_MISMATCH", self.codes(findings))

    def test_poisson_on_molecule_is_error(self):
        text = CP2K_BASE.replace("      PERIODIC XYZ\n    &END CELL",
                                 "      PERIODIC NONE\n    &END CELL")
        findings = self.cp2k(text)
        self.assertIn("CP2K_POISSON_ON_MOLECULE", self.codes(findings))

    def test_cutoff_low_warns(self):
        findings = self.cp2k(CP2K_BASE.replace("CUTOFF 400", "CUTOFF 200"))
        self.assertIn("CP2K_CUTOFF_LOW", self.codes(findings))

    def test_md_timestep_cap(self):
        md = "\n&MOTION\n  &MD\n    ENSEMBLE NVT\n    TIMESTEP 2.0\n    STEPS 100\n  &END MD\n&END MOTION\n"
        findings = self.cp2k(CP2K_BASE + md, xyz=H2O_XYZ, task="md")
        self.assertIn("CP2K_MD_TIMESTEP", self.codes(findings))

    def test_band_under_motion_is_error(self):
        """P0 regression: &BAND_STRUCTURE must not live under &MOTION."""
        bad = CP2K_BASE + "\n&MOTION\n  &BAND_STRUCTURE\n  &END BAND_STRUCTURE\n&END MOTION\n"
        findings = self.cp2k(bad, task="band")
        self.assertIn("CP2K_BAND_HIERARCHY", self.codes(findings))

    def test_band_under_print_passes(self):
        good = CP2K_BASE.replace(
            "    &POISSON",
            "    &PRINT\n      &BAND_STRUCTURE\n      &END BAND_STRUCTURE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(good, task="band")
        self.assertNotIn("CP2K_BAND_HIERARCHY", self.codes(findings))
        self.assertNotIn("CP2K_BAND_MISSING", self.codes(findings))

    def test_dftu_requires_plus_u_method(self):
        dftu = CP2K_BASE.replace(
            "    &END KIND\n  &END SUBSYS",
            "      &DFT_PLUS_U\n        L 2\n        U_MINUS_J [eV] 4.0\n      &END DFT_PLUS_U\n    &END KIND\n  &END SUBSYS", 1)
        findings = self.cp2k(dftu)
        self.assertIn("CP2K_DFTU_INCOMPLETE", self.codes(findings))

    def test_workfunction_requires_hartree_output(self):
        # Neither &V_HARTREE_CUBE (2026.1-safe) nor &PLANAR_AVERAGED_V_HARTREE
        # (2026.2-dev+) present -> ERROR; see test_audit_phase4b.py for the
        # relaxed either/or acceptance and the 2026.2+ version WARN.
        findings = self.cp2k(task="workfunction")
        self.assertIn("CP2K_WF_MISSING", self.codes(findings))

    def test_workfunction_without_surface_dipole_warns(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertIn("CP2K_WF_NO_DIPOLE", self.codes(findings))
        self.assertEqual(
            next(x.level for x in findings if x.code == "CP2K_WF_NO_DIPOLE"),
            vi.WARN)

    def test_workfunction_active_surface_dipole_is_clean(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION .TRUE.\n"
            "    SURF_DIP_DIR Z\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertNotIn("CP2K_WF_NO_DIPOLE", self.codes(findings))
        self.assertNotIn("CP2K_WF_DIPOLE_DIR_INVALID", self.codes(findings))

    def test_workfunction_explicit_false_surface_dipole_still_warns(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION .FALSE.\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertIn("CP2K_WF_NO_DIPOLE", self.codes(findings))

    def test_workfunction_invalid_surface_dipole_direction_is_error(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION .TRUE.\n"
            "    SURF_DIP_DIR XY\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertIn("CP2K_WF_DIPOLE_DIR_INVALID", self.codes(findings))
        self.assertEqual(
            next(x.level for x in findings
                 if x.code == "CP2K_WF_DIPOLE_DIR_INVALID"), vi.ERROR)

    def test_workfunction_surface_dipole_allows_inline_bang_comment(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION .TRUE. ! asymmetric slab\n"
            "    SURF_DIP_DIR Z ! surface normal\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertNotIn("CP2K_WF_DIPOLE_VALUE_INVALID", self.codes(findings))
        self.assertNotIn("CP2K_WF_DIPOLE_DIR_INVALID", self.codes(findings))
        self.assertNotIn("CP2K_WF_NO_DIPOLE", self.codes(findings))

    def test_workfunction_surface_dipole_variable_is_unresolved_warn(self):
        text = CP2K_BASE.replace(
            "&GLOBAL",
            "@SET DIPOLE TRUE\n&GLOBAL").replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION ${DIPOLE}\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertIn("CP2K_WF_DIPOLE_UNRESOLVED", self.codes(findings))
        self.assertEqual(
            next(x.level for x in findings
                 if x.code == "CP2K_WF_DIPOLE_UNRESOLVED"), vi.WARN)
        self.assertNotIn("CP2K_WF_DIPOLE_VALUE_INVALID", self.codes(findings))

    def test_workfunction_surface_dipole_direction_variable_is_unresolved_warn(self):
        text = CP2K_BASE.replace(
            "&GLOBAL",
            "@SET DIPOLE_DIR Z\n&GLOBAL").replace(
            "    &POISSON",
            "    SURFACE_DIPOLE_CORRECTION .TRUE.\n"
            "    SURF_DIP_DIR ${DIPOLE_DIR}\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertIn("CP2K_WF_DIPOLE_DIR_UNRESOLVED", self.codes(findings))
        self.assertEqual(
            next(x.level for x in findings
                 if x.code == "CP2K_WF_DIPOLE_DIR_UNRESOLVED"), vi.WARN)
        self.assertNotIn("CP2K_WF_DIPOLE_DIR_INVALID", self.codes(findings))

    def test_workfunction_lone_alias_uses_default_z_direction(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    SURF_DIP\n"
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        findings = self.cp2k(text, task="workfunction")
        self.assertNotIn("CP2K_WF_NO_DIPOLE", self.codes(findings))
        self.assertNotIn("CP2K_WF_DIPOLE_DIR_INVALID", self.codes(findings))

    def test_workfunction_filename_infers_task_for_dipole_check(self):
        text = CP2K_BASE.replace(
            "    &POISSON",
            "    &PRINT\n      &V_HARTREE_CUBE ON\n"
            "      &END V_HARTREE_CUBE\n    &END PRINT\n    &POISSON")
        path = self.write("cp2k_workfunction.inp", text)
        findings = vi.validate_cp2k_one(path)
        self.assertIn("CP2K_WF_NO_DIPOLE", self.codes(findings))

    def test_phonon_requires_forces(self):
        findings = self.cp2k(task="phonon")
        self.assertIn("CP2K_PHONON_MISSING", self.codes(findings))

    def test_parse_error_on_unclosed_section(self):
        findings = vi.validate_cp2k_one(self.write("bad.inp", "&GLOBAL\n  PROJECT x\n"))
        self.assertIn("CP2K_PARSE", self.codes(findings))

    def test_sccs_without_dielectric_warns(self):
        sccs = CP2K_BASE.replace(
            "    &POISSON",
            "    &SCCS\n      METHOD ANDREUSSI\n      EPS_SCCS 1.0E-7\n    &END SCCS\n    &POISSON")
        findings = self.cp2k(sccs)
        self.assertIn("CP2K_SCCS_NO_DIELECTRIC", self.codes(findings))

    def test_sccs_loose_eps_warns(self):
        sccs = CP2K_BASE.replace(
            "    &POISSON",
            "    &SCCS\n      METHOD ANDREUSSI\n      DIELECTRIC_CONSTANT 78.36\n"
            "      EPS_SCCS 1.0E-4\n    &END SCCS\n    &POISSON")
        findings = self.cp2k(sccs)
        self.assertIn("CP2K_SCCS_LOOSE", self.codes(findings))

    def test_sccs_clean(self):
        sccs = CP2K_BASE.replace(
            "    &POISSON",
            "    &SCCS\n      METHOD ANDREUSSI\n      DIELECTRIC_CONSTANT 78.36\n"
            "      EPS_SCCS 1.0E-7\n    &END SCCS\n    &POISSON")
        findings = self.cp2k(sccs)
        for code in ("CP2K_SCCS_NO_DIELECTRIC", "CP2K_SCCS_LOOSE", "CP2K_SCCS_EPS_RANGE"):
            self.assertNotIn(code, self.codes(findings))


COLVAR_BLOCK = ("    &COLVAR\n      &DISTANCE\n        ATOMS 1 4\n"
                "      &END DISTANCE\n    &END COLVAR\n")

METADYN_BLOCK = """\
&MOTION
  &MD
    ENSEMBLE NVT
    TIMESTEP 0.5
    STEPS 100
  &END MD
  &FREE_ENERGY
    &METADYN
      DO_HILLS .TRUE.
      NT_HILLS 100
      WW [kcalmol] 1.5
      &METAVAR
        SCALE 0.5
        COLVAR 1
      &END METAVAR
      WELL_TEMPERED .TRUE.
      WTGAMMA 20
      &PRINT
        &COLVAR
          COMMON_ITERATION_LEVELS 3
          &EACH
            MD 10
          &END EACH
        &END COLVAR
        &HILLS
          COMMON_ITERATION_LEVELS 3
          &EACH
            MD 10
          &END EACH
        &END HILLS
      &END PRINT
    &END METADYN
  &END FREE_ENERGY
&END MOTION
"""


class TestCp2kMetadyn(Case):
    def with_colvar(self, text=CP2K_BASE):
        return text.replace("  &END SUBSYS", COLVAR_BLOCK + "  &END SUBSYS")

    def test_metadyn_missing_is_error(self):
        findings = self.cp2k(task="metadyn")
        self.assertIn("CP2K_METADYN_MISSING", self.codes(findings))
        self.assertIn("CP2K_METADYN_NO_COLVAR", self.codes(findings))

    def test_metadyn_no_metavar_is_error(self):
        no_var = METADYN_BLOCK.replace(
            "      &METAVAR\n        SCALE 0.5\n        COLVAR 1\n      &END METAVAR\n", "")
        findings = self.cp2k(self.with_colvar() + "\n" + no_var, task="metadyn")
        self.assertIn("CP2K_METADYN_NO_METAVAR", self.codes(findings))

    def test_metadyn_no_colvar_is_error(self):
        findings = self.cp2k(CP2K_BASE + "\n" + METADYN_BLOCK, task="metadyn")
        self.assertIn("CP2K_METADYN_NO_COLVAR", self.codes(findings))

    def test_metadyn_no_hills_print_warns(self):
        no_hills = METADYN_BLOCK.replace(
            "        &HILLS\n          COMMON_ITERATION_LEVELS 3\n"
            "          &EACH\n            MD 10\n          &END EACH\n        &END HILLS\n", "")
        findings = self.cp2k(self.with_colvar() + "\n" + no_hills, task="metadyn")
        self.assertIn("CP2K_METADYN_NO_HILLS_PRINT", self.codes(findings))
        self.assertEqual([x for x in findings if x.level == vi.ERROR], [])

    def test_metadyn_complete_passes(self):
        findings = self.cp2k(self.with_colvar() + "\n" + METADYN_BLOCK, task="metadyn")
        for code in ("CP2K_METADYN_MISSING", "CP2K_METADYN_NO_METAVAR",
                     "CP2K_METADYN_NO_COLVAR", "CP2K_METADYN_NO_HILLS_PRINT"):
            self.assertNotIn(code, self.codes(findings))


class TestCp2kMetaggaCutoff(Case):
    R2SCAN_XC = ("    &XC\n      &XC_FUNCTIONAL\n        &LIBXC\n"
                 "          FUNCTIONAL MGGA_X_R2SCAN\n        &END LIBXC\n"
                 "      &END XC_FUNCTIONAL\n    &END XC\n")

    def test_r2scan_low_cutoff_warns(self):
        text = CP2K_BASE.replace("    &SCF", self.R2SCAN_XC + "    &SCF")
        findings = self.cp2k(text)  # CUTOFF 400 < 600
        self.assertIn("CP2K_CUTOFF_METAGGA", self.codes(findings))

    def test_r2scan_high_cutoff_clean(self):
        text = CP2K_BASE.replace("    &SCF", self.R2SCAN_XC + "    &SCF")
        text = text.replace("CUTOFF 400", "CUTOFF 600")
        findings = self.cp2k(text)
        self.assertNotIn("CP2K_CUTOFF_METAGGA", self.codes(findings))
        self.assertNotIn("CP2K_CUTOFF_LOW", self.codes(findings))


# ---------------------------------------------------------------------------
# LAMMPS
# ---------------------------------------------------------------------------

class TestLammps(Case):
    def test_clean_md_passes(self):
        findings = vi.validate_lammps_one(self.write("in.md", LAMMPS_OK))
        self.assertEqual(findings, [])

    def test_missing_pair_style_is_error(self):
        text = LAMMPS_OK.replace("pair_style eam/alloy\n", "")
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertIn("LAMMPS_NO_PAIR_STYLE", self.codes(findings))

    def test_user_marker_satisfies_potential_rule(self):
        text = LAMMPS_OK.replace("pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
                                 "# >>> USER: insert pair_style/pair_coeff here <<<\n")
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertNotIn("LAMMPS_NO_PAIR_STYLE", self.codes(findings))

    def test_missing_units_atom_style_boundary(self):
        findings = vi.validate_lammps_one(self.write("in.md", "read_data x.data\nrun 1\n"))
        for code in ("LAMMPS_NO_UNITS", "LAMMPS_NO_ATOM_STYLE", "LAMMPS_NO_BOUNDARY"):
            self.assertIn(code, self.codes(findings))

    def test_missing_run_is_error(self):
        text = LAMMPS_OK.replace("run 1000\n", "")
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertIn("LAMMPS_NO_RUN", self.codes(findings))

    def test_minimize_only_needs_no_run(self):
        text = ("units metal\natom_style atomic\nboundary p p p\n"
                "read_data x.data\npair_style eam/alloy\nminimize 1e-4 1e-6 100 1000\n")
        findings = vi.validate_lammps_one(self.write("in.min", text))
        self.assertNotIn("LAMMPS_NO_RUN", self.codes(findings))

    def test_timestep_high_warns(self):
        text = LAMMPS_OK.replace("timestep 0.0005", "timestep 0.002")  # 2 fs in metal units
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_md_without_velocity_warns(self):
        text = LAMMPS_OK.replace("velocity all create 300.0 12345\n", "")
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertIn("LAMMPS_NO_VELOCITY", self.codes(findings))

    def test_electrode_fix_without_electrode_kspace_is_error(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_style lj/cut/coul/long 12.0\npair_coeff * *\nkspace_style pppm 1.0e-5\n"
            "fix conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes\n")
        findings = vi.validate_lammps_one(self.write("in.conp", text))
        self.assertIn("LAMMPS_ELECTRODE_KSPACE", self.codes(findings))

    def test_electrode_fix_with_electrode_kspace_passes(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_style lj/cut/coul/long 12.0\npair_coeff * *\n"
            "kspace_style pppm/electrode 1.0e-7\n"
            "fix conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes\n")
        findings = vi.validate_lammps_one(self.write("in.conp", text))
        self.assertNotIn("LAMMPS_ELECTRODE_KSPACE", self.codes(findings))

    def test_mlff_without_model_warns(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_style mace\npair_coeff * *\n")
        findings = vi.validate_lammps_one(self.write("in.mlff", text))
        self.assertIn("LAMMPS_MLFF_NO_MODEL", self.codes(findings))

    def test_mlff_with_model_clean(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_style mace\npair_coeff * * mace.model H O Pt\n")
        findings = vi.validate_lammps_one(self.write("in.mlff", text))
        self.assertNotIn("LAMMPS_MLFF_NO_MODEL", self.codes(findings))


NEB_OK = """\
units metal
atom_style atomic
boundary p p p
atom_modify map array
read_data initial.data
pair_style eam/alloy
pair_coeff * * Al.eam Al
neighbor 2.0 bin
timestep 0.005
min_style quickmin
fix 1 all neb 1.0
thermo 100
neb 1.0e-3 1.0e-5 1000 1000 100 final coords.final
"""


class TestLammpsShakeNeb(Case):
    def test_non_finite_timestep_is_error(self):
        text = LAMMPS_OK.replace("timestep 0.0005", "timestep nan")
        findings = vi.validate_lammps_one(self.write("in.nan", text))
        self.assertIn("LAMMPS_TIMESTEP_INVALID", self.codes(findings))

    def test_large_timestep_without_shake_warns(self):
        text = LAMMPS_OK.replace("timestep 0.0005", "timestep 0.002")  # 2 fs, metal
        findings = vi.validate_lammps_one(self.write("in.md", text))
        self.assertIn("LAMMPS_NO_SHAKE", self.codes(findings))

    def test_shake_or_small_timestep_no_warn(self):
        findings = vi.validate_lammps_one(self.write("in.md", LAMMPS_OK))  # 0.5 fs
        self.assertNotIn("LAMMPS_NO_SHAKE", self.codes(findings))
        text = LAMMPS_OK.replace(
            "timestep 0.0005", "timestep 0.002").replace(
            "fix 1 all nvt temp 300.0 300.0 0.05\n",
            "fix 1 all nvt temp 300.0 300.0 0.05\nfix 2 water shake 1.0e-4 20 10 b 1 a 1\n")
        findings = vi.validate_lammps_one(self.write("in.shake", text))
        self.assertNotIn("LAMMPS_NO_SHAKE", self.codes(findings))

    def test_shake_words_in_comment_do_not_suppress_warns(self):
        text = (LAMMPS_OK.replace("timestep 0.0005", "timestep 0.002")
                + "# add fix shake or rigid later\n")
        findings = vi.validate_lammps_one(self.write("in.comment", text))
        self.assertIn("LAMMPS_NO_SHAKE", self.codes(findings))
        self.assertIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_unfix_after_run_does_not_hide_unconstrained_md(self):
        text = (LAMMPS_OK.replace("timestep 0.0005", "timestep 0.002")
                .replace("run 1000", "run 1000\nunfix 1"))
        findings = vi.validate_lammps_one(self.write("in.unfix-after", text))
        self.assertIn("LAMMPS_NO_SHAKE", self.codes(findings))
        self.assertIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_neb_command_without_neb_fix_is_error(self):
        text = NEB_OK.replace("fix 1 all neb 1.0\n", "")
        findings = vi.validate_lammps_one(self.write("in.neb", text))
        self.assertIn("LAMMPS_NEB_NO_FIX", self.codes(findings))

    def test_neb_with_fix_passes(self):
        findings = vi.validate_lammps_one(self.write("in.neb", NEB_OK))
        self.assertNotIn("LAMMPS_NEB_NO_FIX", self.codes(findings))
        self.assertNotIn("LAMMPS_NO_RUN", self.codes(findings))
        self.assertNotIn("LAMMPS_NO_SHAKE", self.codes(findings))
        self.assertNotIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))
        self.assertEqual([x for x in findings if x.level == vi.ERROR], [])


# ---------------------------------------------------------------------------
# Golden test: all shipped CP2K/LAMMPS examples must be ERROR-free
# ---------------------------------------------------------------------------

class TestGoldenCp2kLammps(unittest.TestCase):
    def test_examples_have_no_errors(self):
        results = vi.run_examples_dir(str(ROOT / "examples"))
        cp2k_lammps = {name: fs for name, fs in results.items()
                       if name.endswith((".inp",)) or "/in" in name or "input" in name}
        self.assertTrue(cp2k_lammps, "expected CP2K/LAMMPS examples to be discovered")
        bad = {name: [str(x) for x in fs if x.level == vi.ERROR]
               for name, fs in cp2k_lammps.items()}
        bad = {k: v for k, v in bad.items() if v}
        self.assertEqual(bad, {}, msg=f"CP2K/LAMMPS examples with ERROR:\n{bad}")


if __name__ == "__main__":
    unittest.main()
