#!/usr/bin/env python3
"""
Audit-driven regression tests for the 2026-07 validator hardening
(scripts/validate_input.py). One test class per new rule:

  VASP   (a) IBRION=5/6 requires NSW >= 1              (audit P0-02)
         (b) RANDOM_SEED arity (VASP 6.x: 3 integers)  (audit P1-VASP-01)
         (c) DFT+U zero-U placeholder -> ERROR          (audit P1-VASP-07)
         (d) elf task requires LELF=.TRUE.              (SKILL.md rules table)
         (e) LANGEVIN_GAMMA count vs POSCAR species     (audit P1-VASP-02)
  LAMMPS (f) velocity ... create 0.0 -> ERROR           (audit P0-01)
         (g) pair_style without pair_coeff -> ERROR     (audit P1-LAMMPS-04)
         (h) fix nvt + fix nve on one group -> ERROR    (audit P1-LAMMPS-04)
         (i) barostat on a non-periodic dim -> ERROR    (audit P1-LAMMPS-03)
         (j) pair_style reax/c removed -> ERROR         (audit P1-LAMMPS-02)
         (k) active-line '>>> USER' placeholder -> ERROR (audit 10.3)
  CP2K   (l) &OT with &KPOINTS -> ERROR                 (audit P0-06)
         (m) &LINRES/&DFPT with &KPOINTS -> ERROR       (audit P0-06)
         (n) WAVEFUNCTIONS REAL on general mesh -> ERROR (audit P0-07)
         (o) POISSON_SOLVER vs cell periodicity          (audit P0-05)
         (p) unit tokens / Fortran D exponents parsing  (audit P1-CP2K-05)
  Runner (q) VASP example missing POSCAR -> INCOMPLETE  (audit 10.2)
         (r) K-series KPOINTS/README consistency        (audit 10.1)
  LAMMPS (s) EAM pair_coeff arity vs file format        (pair_eam.cpp,
             runtime-verified: funcfl `pair_style eam` takes exactly 3 args,
             setfl eam/alloy / eam/fs require element symbol(s))
         (t) bond/angle/pair coeff before the matching style -> ERROR
             (runtime-caught 2026-10-21: input.cpp:1395)

Run from the skill directory:
    python -m unittest discover -s tests -p "test_audit_validator.py" -v
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CEO2 = """\
CeO2 fluorite
1.0
5.411 0.0 0.0
0.0 5.411 0.0
0.0 0.0 5.411
Ce O
4 8
Direct
0.00 0.00 0.00
0.00 0.50 0.50
0.50 0.00 0.50
0.50 0.50 0.00
0.25 0.25 0.25
0.25 0.75 0.75
0.75 0.25 0.75
0.75 0.75 0.25
0.75 0.75 0.75
0.75 0.25 0.25
0.25 0.75 0.25
0.25 0.25 0.75
"""

AL_BULK = """\
Al FCC conventional
1.0
4.0495 0.0 0.0
0.0 4.0495 0.0
0.0 0.0 4.0495
Al
4
Direct
0.0 0.0 0.0
0.5 0.5 0.0
0.5 0.0 0.5
0.0 0.5 0.5
"""

H2O_XYZ = """\
3
water
O 0.0 0.0 0.0
H 0.76 0.58 0.0
H -0.76 0.58 0.0
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

CP2K_KPTS_MP = """    &KPOINTS
      SCHEME MONKHORST-PACK 4 4 4
      SYMMETRY OFF
      WAVEFUNCTIONS COMPLEX
    &END KPOINTS
"""


def cp2k_with_kpoints(base, kpoints):
    """Insert a &KPOINTS block into &DFT (before &POISSON)."""
    return base.replace("    &POISSON", kpoints + "    &POISSON")


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

    def incar(self, mapping):
        lines = [f"{k} = {v}" for k, v in mapping.items()]
        return self.write("INCAR", "\n".join(lines) + "\n")

    def vasp(self, mapping, poscar=None, task=None):
        """validate() on an INCAR mapping; optional POSCAR content and task."""
        params = vi.parse_incar(self.incar(mapping))
        structure = vi.parse_poscar(self.write("POSCAR", poscar)) if poscar else None
        return vi.validate(params, structure, task_override=task)

    def codes(self, findings):
        return {x.code for x in findings}

    def errors(self, findings):
        return [x for x in findings if x.level == vi.ERROR]

    def lammps(self, text):
        return vi.validate_lammps_one(self.write("in.test", text))

    def cp2k(self, text=CP2K_BASE, xyz=None, task=None):
        path = self.write("test.inp", text)
        xyz_path = self.write("coord.xyz", xyz) if xyz else None
        return vi.validate_cp2k_one(path, xyz_path, task)


# ---------------------------------------------------------------------------
# (a) IBRION=5/6 requires NSW >= 1 (audit P0-02)
# ---------------------------------------------------------------------------

class TestFreqNsw(Case):
    def test_ibrion5_without_nsw_is_error(self):
        findings = self.vasp({"IBRION": "5", "ENCUT": "400"})
        self.assertIn("FREQ_MISSING_NSW", self.codes(findings))

    def test_ibrion6_with_nsw0_is_error(self):
        findings = self.vasp({"IBRION": "6", "NSW": "0", "ENCUT": "400"})
        self.assertIn("FREQ_MISSING_NSW", self.codes(findings))

    def test_ibrion5_with_nsw1_clean(self):
        findings = self.vasp({"IBRION": "5", "NSW": "1", "ENCUT": "400"})
        self.assertNotIn("FREQ_MISSING_NSW", self.codes(findings))

    def test_relax_without_nsw_unaffected(self):
        findings = self.vasp({"IBRION": "2", "NSW": "100", "ENCUT": "400"})
        self.assertNotIn("FREQ_MISSING_NSW", self.codes(findings))


# ---------------------------------------------------------------------------
# (b) RANDOM_SEED arity (audit P1-VASP-01)
# ---------------------------------------------------------------------------

class TestRandomSeed(Case):
    def test_single_integer_warns_vasp6_needs_three(self):
        findings = self.vasp({"IBRION": "0", "NSW": "10", "POTIM": "1.0",
                              "ISYM": "0", "RANDOM_SEED": "12345", "ENCUT": "400"})
        hits = [x for x in findings if x.code == "RANDOM_SEED_COUNT"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.WARN)
        self.assertIn("three integers", hits[0].message)

    def test_two_integers_warns_generic(self):
        findings = self.vasp({"IBRION": "0", "NSW": "10", "POTIM": "1.0",
                              "ISYM": "0", "RANDOM_SEED": "12345 0", "ENCUT": "400"})
        self.assertIn("RANDOM_SEED_COUNT", self.codes(findings))

    def test_three_integers_clean(self):
        findings = self.vasp({"IBRION": "0", "NSW": "10", "POTIM": "1.0",
                              "ISYM": "0", "RANDOM_SEED": "248489752 0 0",
                              "ENCUT": "400"})
        self.assertNotIn("RANDOM_SEED_COUNT", self.codes(findings))


# ---------------------------------------------------------------------------
# (c) DFT+U zero-U placeholder (audit P1-VASP-07)
# ---------------------------------------------------------------------------

class TestDftuZeroU(Case):
    BASE = {"LDAU": ".TRUE.", "LDAUTYPE": "2", "LMAXMIX": "4", "NELM": "100",
            "IBRION": "2", "NSW": "50", "ENCUT": "400"}

    def test_all_ldaul_minus1_is_error(self):
        findings = self.vasp(dict(self.BASE, LDAUL="-1 -1",
                                  LDAUU="0.0 0.0", LDAUJ="0.0 0.0"))
        self.assertIn("DFTU_ZERO_U", self.codes(findings))

    def test_all_zero_ueff_is_error(self):
        findings = self.vasp(dict(self.BASE, LDAUL="2 -1",
                                  LDAUU="0.0 0.0", LDAUJ="0.0 0.0"))
        self.assertIn("DFTU_ZERO_U", self.codes(findings))

    def test_u_equal_j_is_zero_ueff_error(self):
        findings = self.vasp(dict(self.BASE, LDAUL="2 -1",
                                  LDAUU="4.0 0.0", LDAUJ="4.0 0.0"))
        self.assertIn("DFTU_ZERO_U", self.codes(findings))

    def test_real_u_clean(self):
        findings = self.vasp(dict(self.BASE, LDAUL="2 -1",
                                  LDAUU="5.0 0.0", LDAUJ="0.0 0.0"))
        self.assertNotIn("DFTU_ZERO_U", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_dftu_control_task_exempts(self):
        _, findings = vi.validate_one(
            self.incar(dict(self.BASE, LDAUL="-1 -1", LDAUU="0.0 0.0",
                            LDAUJ="0.0 0.0")),
            task="dftu-control")
        self.assertNotIn("DFTU_ZERO_U", self.codes(findings))

    def test_control_comment_exempts(self):
        path = self.write("INCAR",
                          "# control calculation: zero-U reference for a delta-U scan\n"
                          "LDAU = .TRUE.\nLDAUTYPE = 2\nLMAXMIX = 4\nLDAUL = -1 -1\n"
                          "LDAUU = 0.0 0.0\nLDAUJ = 0.0 0.0\nNELM = 100\nENCUT = 400\n")
        _, findings = vi.validate_one(path)
        self.assertNotIn("DFTU_ZERO_U", self.codes(findings))

    def test_zero_u_without_control_marker_still_errors_via_file(self):
        path = self.write("INCAR",
                          "LDAU = .TRUE.\nLDAUTYPE = 2\nLMAXMIX = 4\nLDAUL = -1 -1\n"
                          "LDAUU = 0.0 0.0\nLDAUJ = 0.0 0.0\nNELM = 100\nENCUT = 400\n")
        _, findings = vi.validate_one(path)
        self.assertIn("DFTU_ZERO_U", self.codes(findings))


# ---------------------------------------------------------------------------
# (d) elf task requires LELF=.TRUE. (SKILL.md rules table)
# ---------------------------------------------------------------------------

class TestElfTask(Case):
    def test_elf_task_without_lelf_is_error(self):
        findings = self.vasp({"IBRION": "-1", "NSW": "0", "ENCUT": "400"}, task="elf")
        self.assertIn("ELF_MISSING_LELF", self.codes(findings))

    def test_elf_task_with_lelf_clean(self):
        findings = self.vasp({"IBRION": "-1", "NSW": "0", "ENCUT": "400",
                              "LELF": ".TRUE.", "NPAR": "1"}, task="elf")
        self.assertNotIn("ELF_MISSING_LELF", self.codes(findings))


# ---------------------------------------------------------------------------
# (e) LANGEVIN_GAMMA count vs POSCAR species (audit P1-VASP-02)
# ---------------------------------------------------------------------------

class TestLangevinGamma(Case):
    MD = {"IBRION": "0", "NSW": "10", "POTIM": "1.0", "ISYM": "0", "ENCUT": "400"}

    def test_count_mismatch_warns(self):
        findings = self.vasp(dict(self.MD, LANGEVIN_GAMMA="10.0"), poscar=CEO2)
        self.assertIn("LANGEVIN_GAMMA_COUNT", self.codes(findings))

    def test_count_match_clean(self):
        findings = self.vasp(dict(self.MD, LANGEVIN_GAMMA="10.0 5.0"), poscar=CEO2)
        self.assertNotIn("LANGEVIN_GAMMA_COUNT", self.codes(findings))

    def test_no_poscar_skips_check(self):
        findings = self.vasp(dict(self.MD, LANGEVIN_GAMMA="10.0"))
        self.assertNotIn("LANGEVIN_GAMMA_COUNT", self.codes(findings))


# ---------------------------------------------------------------------------
# (f) velocity ... create 0.0 (audit P0-01)
# ---------------------------------------------------------------------------

class TestLammpsVelocityZero(Case):
    def test_zero_temperature_is_error(self):
        text = LAMMPS_BASE.replace("velocity all create 300.0 12345",
                                   "velocity all create 0.0 12345")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_VELOCITY_ZERO_TEMP", self.codes(findings))

    def test_nonzero_temperature_clean(self):
        findings = self.lammps(LAMMPS_BASE)
        self.assertNotIn("LAMMPS_VELOCITY_ZERO_TEMP", self.codes(findings))
        self.assertEqual(self.errors(findings), [])


# ---------------------------------------------------------------------------
# (g) pair_style without pair_coeff (audit P1-LAMMPS-04)
# ---------------------------------------------------------------------------

class TestPairCoeff(Case):
    def test_pair_style_without_pair_coeff_is_error(self):
        text = LAMMPS_BASE.replace("pair_coeff * * Al.eam Al\n", "")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_PAIR_COEFF_MISSING", self.codes(findings))

    def test_pair_style_with_pair_coeff_clean(self):
        findings = self.lammps(LAMMPS_BASE)
        self.assertNotIn("LAMMPS_PAIR_COEFF_MISSING", self.codes(findings))


# ---------------------------------------------------------------------------
# (t) coeff commands require the matching style declared earlier
#     (runtime-caught 2026-10-21: bond_coeff before bond_style aborts with
#     "Bond_coeff command before bond_style is defined", input.cpp:1395)
# ---------------------------------------------------------------------------

BONDED_BASE = LAMMPS_BASE.replace(
    "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
    "pair_style lj/cut/coul/long 10.0\n"
    "pair_coeff 1 1 0.15535 3.166\n"
    "bond_style harmonic\n"
    "angle_style harmonic\n"
    "bond_coeff 1 450.0 0.957\n"
    "angle_coeff 1 55.0 104.52\n")


class TestCoeffBeforeStyle(Case):
    def test_bonded_input_clean(self):
        findings = self.lammps(BONDED_BASE)
        self.assertNotIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))

    def test_bond_coeff_without_bond_style_is_error(self):
        findings = self.lammps(BONDED_BASE.replace("bond_style harmonic\n", ""))
        self.assertIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))

    def test_angle_coeff_without_angle_style_is_error(self):
        findings = self.lammps(BONDED_BASE.replace("angle_style harmonic\n", ""))
        self.assertIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))

    def test_pair_coeff_before_pair_style_is_error(self):
        text = LAMMPS_BASE.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_coeff * * Al.eam Al\npair_style eam/alloy\n")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))

    def test_style_from_earlier_include_satisfies_rule(self):
        self.write("ff.inc", "bond_style harmonic\nangle_style harmonic\n")
        text = BONDED_BASE.replace(
            "bond_style harmonic\nangle_style harmonic\n", "include ff.inc\n")
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))

    def test_read_restart_skips_rule(self):
        # restart files restore force-field styles; coeff without an explicit
        # style declaration is legal after read_restart
        text = (
            "units metal\n"
            "atom_style full\n"
            "boundary p p p\n"
            "read_restart restart.bin\n"
            "bond_coeff 1 450.0 0.957\n"
            "run 1000\n")
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_COEFF_BEFORE_STYLE", self.codes(findings))


# ---------------------------------------------------------------------------
# (h) fix nvt + fix nve on one group (audit P1-LAMMPS-04)
# ---------------------------------------------------------------------------

class TestNvtNveConflict(Case):
    def test_nvt_plus_nve_same_group_is_error(self):
        findings = self.lammps(LAMMPS_BASE + "fix 2 all nve\n")
        self.assertIn("LAMMPS_NVT_NVE_CONFLICT", self.codes(findings))

    def test_unfix_separates_the_pair(self):
        text = LAMMPS_BASE.replace("run 1000", "unfix 1\nfix 2 all nve\nrun 1000")
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_NVT_NVE_CONFLICT", self.codes(findings))

    def test_different_groups_clean(self):
        findings = self.lammps(LAMMPS_BASE + "fix 2 substrate nve\n")
        self.assertNotIn("LAMMPS_NVT_NVE_CONFLICT", self.codes(findings))

    def test_npt_plus_nve_same_group_is_error(self):
        text = LAMMPS_BASE.replace(
            "fix 1 all nvt temp 300.0 300.0 0.05",
            "fix 1 all npt temp 300.0 300.0 0.05 iso 1.0 1.0 1.0\n"
            "fix 2 all nve")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_NVT_NVE_CONFLICT", self.codes(findings))

    def test_nph_plus_nve_same_group_is_error(self):
        text = LAMMPS_BASE.replace(
            "fix 1 all nvt temp 300.0 300.0 0.05",
            "fix 1 all nph iso 1.0 1.0 1.0\nfix 2 all nve")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_NVT_NVE_CONFLICT", self.codes(findings))


# ---------------------------------------------------------------------------
# (i) barostat on a non-periodic dimension (audit P1-LAMMPS-03)
# ---------------------------------------------------------------------------

class TestBarostatBoundary(Case):
    NPT_ISO = "fix 1 all npt temp 300.0 300.0 0.05 iso 1.0 1.0 0.5"
    NPT_XY = "fix 1 all npt temp 300.0 300.0 0.05 x 1.0 1.0 0.5 y 1.0 1.0 0.5"

    def _slab(self, fix_line):
        return (LAMMPS_BASE
                .replace("boundary p p p", "boundary p p f")
                .replace("fix 1 all nvt temp 300.0 300.0 0.05", fix_line))

    def test_iso_barostat_on_nonperiodic_z_is_error(self):
        findings = self.lammps(self._slab(self.NPT_ISO))
        self.assertIn("LAMMPS_NPT_NONPERIODIC_DIM", self.codes(findings))

    def test_z_barostat_on_nonperiodic_z_is_error(self):
        fix = "fix 1 all npt temp 300.0 300.0 0.05 z 1.0 1.0 0.5"
        findings = self.lammps(self._slab(fix))
        self.assertIn("LAMMPS_NPT_NONPERIODIC_DIM", self.codes(findings))

    def test_xy_only_barostat_on_slab_clean(self):
        findings = self.lammps(self._slab(self.NPT_XY))
        self.assertNotIn("LAMMPS_NPT_NONPERIODIC_DIM", self.codes(findings))

    def test_couple_value_is_not_misread_as_pressure_keyword(self):
        fix = self.NPT_XY.replace(" y 1.0 1.0 0.5", "") + " couple xy"
        findings = self.lammps(self._slab(fix))  # only x barostatted, x is periodic
        self.assertNotIn("LAMMPS_NPT_NONPERIODIC_DIM", self.codes(findings))

    def test_iso_barostat_fully_periodic_clean(self):
        text = LAMMPS_BASE.replace("fix 1 all nvt temp 300.0 300.0 0.05", self.NPT_ISO)
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_NPT_NONPERIODIC_DIM", self.codes(findings))


# ---------------------------------------------------------------------------
# (j) pair_style reax/c removed (audit P1-LAMMPS-02)
# ---------------------------------------------------------------------------

class TestReaxcRemoved(Case):
    def _with_style(self, style_line):
        return (LAMMPS_BASE
                .replace("pair_style eam/alloy", style_line)
                .replace("pair_coeff * * Al.eam Al", "pair_coeff * * ffield.reax C H O")
                .replace("units metal", "units real"))

    def test_reaxc_is_error(self):
        findings = self.lammps(self._with_style("pair_style reax/c"))
        self.assertIn("LAMMPS_REAXC_REMOVED", self.codes(findings))

    def test_reaxc_omp_suffix_is_error(self):
        findings = self.lammps(self._with_style("pair_style reax/c/omp"))
        self.assertIn("LAMMPS_REAXC_REMOVED", self.codes(findings))

    def test_reaxff_clean(self):
        findings = self.lammps(self._with_style("pair_style reaxff"))
        self.assertNotIn("LAMMPS_REAXC_REMOVED", self.codes(findings))


# ---------------------------------------------------------------------------
# (k) active-line '>>> USER' placeholder (audit 10.3)
# ---------------------------------------------------------------------------

class TestPlaceholder(Case):
    def test_active_placeholder_is_error(self):
        text = LAMMPS_BASE.replace("pair_coeff * * Al.eam Al",
                                   "pair_coeff * * >>> USER: your potential <<<")
        findings = self.lammps(text)
        self.assertIn("LAMMPS_PLACEHOLDER_UNRESOLVED", self.codes(findings))

    def test_comment_only_marker_clean(self):
        text = LAMMPS_BASE + "# >>> USER: guidance may stay in comments <<<\n"
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_PLACEHOLDER_UNRESOLVED", self.codes(findings))

    def test_trailing_comment_marker_clean(self):
        text = LAMMPS_BASE.replace(
            "read_data system.data",
            "read_data system.data  # >>> USER: your data file <<<")
        findings = self.lammps(text)
        self.assertNotIn("LAMMPS_PLACEHOLDER_UNRESOLVED", self.codes(findings))


# ---------------------------------------------------------------------------
# (l) &OT with &KPOINTS (audit P0-06)
# ---------------------------------------------------------------------------

class TestCp2kOtKpoints(Case):
    def test_ot_with_kpoints_is_error(self):
        text = CP2K_BASE.replace(
            "      &DIAGONALIZATION\n      &END DIAGONALIZATION",
            "      &OT\n        PRECONDITIONER FULL_ALL\n      &END OT")
        findings = self.cp2k(cp2k_with_kpoints(text, CP2K_KPTS_MP))
        self.assertIn("CP2K_OT_KPOINTS", self.codes(findings))

    def test_diagonalization_with_kpoints_clean(self):
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, CP2K_KPTS_MP))
        self.assertNotIn("CP2K_OT_KPOINTS", self.codes(findings))

    def test_ot_gamma_only_clean(self):
        text = CP2K_BASE.replace(
            "      &DIAGONALIZATION\n      &END DIAGONALIZATION",
            "      &OT\n        PRECONDITIONER FULL_ALL\n      &END OT")
        findings = self.cp2k(text)  # no &KPOINTS at all
        self.assertNotIn("CP2K_OT_KPOINTS", self.codes(findings))


# ---------------------------------------------------------------------------
# (m) &LINRES / &DFPT with &KPOINTS (audit P0-06)
# ---------------------------------------------------------------------------

class TestCp2kLinresKpoints(Case):
    LINRES = "&PROPERTIES\n  &LINRES\n  &END LINRES\n&END PROPERTIES\n"
    DFPT = "&PROPERTIES\n  &DFPT\n  &END DFPT\n&END PROPERTIES\n"

    def test_linres_with_kpoints_is_error(self):
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, CP2K_KPTS_MP) + self.LINRES)
        self.assertIn("CP2K_LINRES_KPOINTS", self.codes(findings))

    def test_dfpt_with_kpoints_is_error(self):
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, CP2K_KPTS_MP) + self.DFPT)
        self.assertIn("CP2K_LINRES_KPOINTS", self.codes(findings))

    def test_linres_gamma_only_clean(self):
        findings = self.cp2k(CP2K_BASE + self.LINRES)  # no &KPOINTS
        self.assertNotIn("CP2K_LINRES_KPOINTS", self.codes(findings))


# ---------------------------------------------------------------------------
# (n) WAVEFUNCTIONS REAL on a general k-mesh (audit P0-07)
# ---------------------------------------------------------------------------

class TestCp2kRealWfn(Case):
    def test_real_wfn_on_mp_mesh_is_error(self):
        kpts = CP2K_KPTS_MP.replace("WAVEFUNCTIONS COMPLEX", "WAVEFUNCTIONS REAL")
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, kpts))
        self.assertIn("CP2K_KPOINTS_REAL_WFN", self.codes(findings))

    def test_complex_wfn_on_mp_mesh_clean(self):
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, CP2K_KPTS_MP))
        self.assertNotIn("CP2K_KPOINTS_REAL_WFN", self.codes(findings))

    def test_real_wfn_gamma_only_clean(self):
        kpts = ("    &KPOINTS\n      SCHEME GAMMA\n"
                "      WAVEFUNCTIONS REAL\n    &END KPOINTS\n")
        findings = self.cp2k(cp2k_with_kpoints(CP2K_BASE, kpts))
        self.assertNotIn("CP2K_KPOINTS_REAL_WFN", self.codes(findings))


# ---------------------------------------------------------------------------
# (o) POISSON_SOLVER vs cell periodicity (audit P0-05)
# ---------------------------------------------------------------------------

class TestCp2kPoissonSolver(Case):
    def _nonperiodic(self, poisson_lines, cell_periodic="NONE"):
        text = CP2K_BASE.replace("      PERIODIC XYZ\n    &END POISSON",
                                 poisson_lines + "\n    &END POISSON")
        return text.replace("      PERIODIC XYZ\n    &END CELL",
                            f"      PERIODIC {cell_periodic}\n    &END CELL")

    def test_periodic_none_default_solver_is_error(self):
        findings = self.cp2k(self._nonperiodic("      PERIODIC NONE"))
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_periodic_none_with_mt_clean(self):
        findings = self.cp2k(self._nonperiodic(
            "      PERIODIC NONE\n      POISSON_SOLVER MT"))
        self.assertNotIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_poisson_periodic_default_is_xyz_for_solver_check(self):
        findings = self.cp2k(self._nonperiodic(
            "      POISSON_SOLVER MT", cell_periodic="NONE"))
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_periodic_xy_with_wavelet_clean(self):
        findings = self.cp2k(self._nonperiodic(
            "      PERIODIC XY\n      POISSON_SOLVER WAVELET", cell_periodic="XY"))
        self.assertNotIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_multipole_on_2d_is_error(self):
        # MULTIPOLE is documented for cluster (0D) systems only
        findings = self.cp2k(self._nonperiodic(
            "      PERIODIC XY\n      POISSON_SOLVER MULTIPOLE", cell_periodic="XY"))
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_unknown_solver_is_error(self):
        findings = self.cp2k(self._nonperiodic(
            "      PERIODIC NONE\n      POISSON_SOLVER BOGUS"))
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_periodic_xyz_default_solver_clean(self):
        findings = self.cp2k(CP2K_BASE)
        self.assertNotIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_periodic_xyz_unknown_explicit_solver_is_error(self):
        text = CP2K_BASE.replace(
            "      PERIODIC XYZ\n    &END POISSON",
            "      PERIODIC XYZ\n      POISSON_SOLVER BOGUS\n    &END POISSON")
        findings = self.cp2k(text)
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_unknown_solver_is_checked_even_without_cell_section(self):
        text = CP2K_BASE.replace(
            "    &CELL\n      ABC 10.0 10.0 10.0\n      PERIODIC XYZ\n    &END CELL\n", "")
        text = text.replace(
            "      PERIODIC XYZ\n    &END POISSON",
            "      PERIODIC XYZ\n      POISSON_SOLVER BOGUS\n    &END POISSON")
        findings = self.cp2k(text)
        self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_xyz_cell_with_xy_poisson_uses_poisson_dimension(self):
        findings = self.cp2k(self._nonperiodic(
            "      PERIODIC XY\n      POISSON_SOLVER ANALYTIC",
            cell_periodic="XYZ"))
        self.assertNotIn("CP2K_POISSON_SOLVER_INCOMPATIBLE", self.codes(findings))

    def test_xyz_cell_with_xy_poisson_rejects_3d_solver(self):
        for solver in ("PERIODIC", "MULTIPOLE", "BOGUS"):
            with self.subTest(solver=solver):
                findings = self.cp2k(self._nonperiodic(
                    f"      PERIODIC XY\n      POISSON_SOLVER {solver}",
                    cell_periodic="XYZ"))
                self.assertIn("CP2K_POISSON_SOLVER_INCOMPATIBLE",
                              self.codes(findings))


# ---------------------------------------------------------------------------
# (p) unit tokens / Fortran D exponents (audit P1-CP2K-05)
# ---------------------------------------------------------------------------

class TestCp2kNumericParsing(Case):
    def test_helper_parses_unit_token_and_d_exponent(self):
        self.assertEqual(vi._cp2k_number("[Ry] 200"), 200.0)
        self.assertEqual(vi._cp2k_number("1.0D-4"), 1.0e-4)
        self.assertEqual(vi._cp2k_number("[fs] 0.5"), 0.5)
        self.assertIsNone(vi._cp2k_number("${CUTOFF}"))
        self.assertIsNone(vi._cp2k_number(None))
        self.assertIsNone(vi._cp2k_number("not_a_number"))
        self.assertIsNone(vi._cp2k_number("nan"))
        self.assertIsNone(vi._cp2k_number("inf"))

    def test_non_finite_cutoff_warns_as_unparseable(self):
        findings = self.cp2k(CP2K_BASE.replace("CUTOFF 400", "CUTOFF nan"))
        self.assertIn("CP2K_VALUE_UNPARSEABLE", self.codes(findings))

    def test_cutoff_unit_token_low_still_warns(self):
        findings = self.cp2k(CP2K_BASE.replace("CUTOFF 400", "CUTOFF [Ry] 200"))
        self.assertIn("CP2K_CUTOFF_LOW", self.codes(findings))

    def test_cutoff_unit_token_high_clean(self):
        findings = self.cp2k(CP2K_BASE.replace("CUTOFF 400", "CUTOFF [Ry] 600"))
        self.assertNotIn("CP2K_CUTOFF_LOW", self.codes(findings))

    def test_eps_scf_fortran_d_loose_warns(self):
        findings = self.cp2k(CP2K_BASE.replace("EPS_SCF 1.0E-6", "EPS_SCF 1.0D-4"))
        self.assertIn("CP2K_EPS_SCF_LOOSE", self.codes(findings))

    def test_eps_scf_fortran_d_tight_clean(self):
        findings = self.cp2k(CP2K_BASE.replace("EPS_SCF 1.0E-6", "EPS_SCF 1.0D-7"))
        self.assertNotIn("CP2K_EPS_SCF_LOOSE", self.codes(findings))

    def test_md_timestep_unit_token_cap_fires(self):
        md = ("\n&MOTION\n  &MD\n    ENSEMBLE NVT\n    TIMESTEP [fs] 2.0\n"
              "    STEPS 100\n  &END MD\n&END MOTION\n")
        findings = self.cp2k(CP2K_BASE + md, xyz=H2O_XYZ, task="md")
        self.assertIn("CP2K_MD_TIMESTEP", self.codes(findings))

    def test_unparseable_cutoff_warns_instead_of_silent_pass(self):
        findings = self.cp2k(CP2K_BASE.replace("CUTOFF 400", "CUTOFF ${CUTOFF}"))
        self.assertIn("CP2K_VALUE_UNPARSEABLE", self.codes(findings))
        # the numeric checks are explicitly skipped, not silently bypassed
        self.assertNotIn("CP2K_CUTOFF_LOW", self.codes(findings))


# ---------------------------------------------------------------------------
# (q) runner: missing POSCAR -> INCOMPLETE (audit 10.2)
# ---------------------------------------------------------------------------

class TestRunnerIncomplete(Case):
    INCAR = "ENCUT = 400\nIBRION = -1\nNSW = 0\n"

    def make_example(self, name, with_poscar):
        d = self.dir / "examples" / name
        d.mkdir(parents=True)
        (d / "INCAR").write_text(self.INCAR, encoding="utf-8")
        if with_poscar:
            (d / "POSCAR").write_text(AL_BULK, encoding="utf-8")
        return str(self.dir / "examples")

    def test_missing_poscar_reported_incomplete(self):
        exdir = self.make_example("01_demo", with_poscar=False)
        results, meta = vi.run_examples_dir_full(exdir)
        self.assertIn("01_demo/INCAR", meta["incomplete"])
        self.assertIn("01_demo/INCAR", results)

    def test_poscar_present_not_incomplete(self):
        exdir = self.make_example("02_demo", with_poscar=True)
        _, meta = vi.run_examples_dir_full(exdir)
        self.assertNotIn("02_demo/INCAR", meta["incomplete"])

    def test_run_examples_dir_keeps_dict_shape(self):
        """Backward compatibility: run_examples_dir still returns {label: findings}."""
        exdir = self.make_example("03_demo", with_poscar=False)
        results = vi.run_examples_dir(exdir)
        self.assertIn("03_demo/INCAR", results)
        self.assertIsInstance(results["03_demo/INCAR"], list)

    def test_cp2k_missing_referenced_xyz_is_incomplete(self):
        d = self.dir / "examples" / "C1_cp2k"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME missing.xyz\n"
            "      COORD_FILE_FORMAT XYZ\n    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertIn("C1_cp2k/input.inp", meta["incomplete"])

    def test_cp2k_inline_coord_is_not_incomplete(self):
        d = self.dir / "examples" / "C2_cp2k_inline"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &COORD\n      H 0.0 0.0 0.0\n    &END COORD\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertNotIn("C2_cp2k_inline/input.inp", meta["incomplete"])

    def test_cp2k_inline_coord_drives_kind_coverage(self):
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &COORD\n      H 0.0 0.0 0.0\n"
            "      O 0.0 0.0 1.0\n    &END COORD\n  &END SUBSYS")
        findings = vi.validate_cp2k_one(self.write("inline.inp", text))
        self.assertIn("CP2K_KIND_MISSING", self.codes(findings))
        self.assertTrue(any("O" in x.message for x in findings))

    def test_cp2k_inline_variable_coord_still_drives_kind_coverage(self):
        d = self.dir / "examples" / "C3_cp2k_variable_coord"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &COORD\n      H ${HX} 0.0 0.0\n"
            "      O ${OX} 0.0 1.0\n    &END COORD\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        results, meta = vi.run_examples_dir_full(str(d.parent))
        label = "C3_cp2k_variable_coord/input.inp"
        self.assertNotIn(label, meta["incomplete"])
        self.assertIn("CP2K_KIND_MISSING", self.codes(results[label]))

    def test_cp2k_inline_include_is_incomplete(self):
        d = self.dir / "examples" / "C4_cp2k_include_coord"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &COORD\n      @INCLUDE coord.inc\n"
            "    &END COORD\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertIn("C4_cp2k_include_coord/input.inp", meta["incomplete"])

    def test_cp2k_pdb_coordinate_file_is_parsed_as_pdb(self):
        d = self.dir / "examples" / "C5_cp2k_pdb"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME coord.pdb\n"
            "      COORD_FILE_FORMAT PDB\n    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        (d / "coord.pdb").write_text(
            "ATOM      1  H   MOL A   1       0.000   0.000   0.000"
            "  1.00  0.00           H  \nEND\n",
            encoding="utf-8")
        results, meta = vi.run_examples_dir_full(str(d.parent))
        label = "C5_cp2k_pdb/input.inp"
        self.assertNotIn(label, meta["incomplete"])
        self.assertNotIn("XYZ_PARSE", self.codes(results[label]))
        self.assertNotIn("PDB_PARSE", self.codes(results[label]))

    def test_cp2k_pdb_defaults_to_atom_name_as_kind(self):
        d = self.dir / "examples" / "C5b_cp2k_pdb_atom_name"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace("&KIND H", "&KIND CA").replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME coord.pdb\n"
            "      COORD_FILE_FORMAT PDB\n    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        (d / "coord.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           C  \nEND\n",
            encoding="utf-8")
        results, meta = vi.run_examples_dir_full(str(d.parent))
        label = "C5b_cp2k_pdb_atom_name/input.inp"
        self.assertNotIn(label, meta["incomplete"])
        self.assertNotIn("CP2K_KIND_MISSING", self.codes(results[label]))

    def test_cp2k_pdb_use_element_as_kind_true_uses_element_column(self):
        d = self.dir / "examples" / "C5c_cp2k_pdb_element"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace("&KIND H", "&KIND C").replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME coord.pdb\n"
            "      COORD_FILE_FORMAT PDB\n      USE_ELEMENT_AS_KIND TRUE\n"
            "    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        (d / "coord.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           C  \nEND\n",
            encoding="utf-8")
        results, meta = vi.run_examples_dir_full(str(d.parent))
        label = "C5c_cp2k_pdb_element/input.inp"
        self.assertNotIn(label, meta["incomplete"])
        self.assertNotIn("CP2K_KIND_MISSING", self.codes(results[label]))

    def test_cp2k_pdb_use_element_as_kind_variable_is_incomplete(self):
        d = self.dir / "examples" / "C5d_cp2k_pdb_kind_variable"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME coord.pdb\n"
            "      COORD_FILE_FORMAT PDB\n"
            "      USE_ELEMENT_AS_KIND ${USE_ELEMENT}\n"
            "    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        (d / "coord.pdb").write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           C  \nEND\n",
            encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertIn("C5d_cp2k_pdb_kind_variable/input.inp", meta["incomplete"])

    def test_cp2k_unsupported_coordinate_format_is_incomplete(self):
        d = self.dir / "examples" / "C6_cp2k_cif"
        d.mkdir(parents=True)
        text = CP2K_BASE.replace(
            "  &END SUBSYS",
            "    &TOPOLOGY\n      COORD_FILE_NAME coord.cif\n"
            "      COORD_FILE_FORMAT CIF\n    &END TOPOLOGY\n  &END SUBSYS")
        (d / "input.inp").write_text(text, encoding="utf-8")
        (d / "coord.cif").write_text("data_demo\n", encoding="utf-8")
        results, meta = vi.run_examples_dir_full(str(d.parent))
        label = "C6_cp2k_cif/input.inp"
        self.assertIn(label, meta["incomplete"])
        self.assertNotIn("XYZ_PARSE", self.codes(results[label]))
        self.assertNotIn("PDB_PARSE", self.codes(results[label]))

    def test_lammps_missing_referenced_data_is_incomplete(self):
        d = self.dir / "examples" / "L1_missing_data"
        d.mkdir(parents=True)
        (d / "input.in").write_text(LAMMPS_BASE, encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertIn("L1_missing_data/input.in", meta["incomplete"])

    def test_lammps_existing_referenced_data_is_not_incomplete(self):
        d = self.dir / "examples" / "L2_with_data"
        d.mkdir(parents=True)
        (d / "input.in").write_text(LAMMPS_BASE, encoding="utf-8")
        (d / "system.data").write_text(
            "LAMMPS data\n\n1 atoms\n1 atom types\n\nMasses\n\n1 26.9815\n",
            encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertNotIn("L2_with_data/input.in", meta["incomplete"])

    def test_lammps_unparseable_referenced_data_is_incomplete(self):
        d = self.dir / "examples" / "L3_bad_data"
        d.mkdir(parents=True)
        (d / "input.in").write_text(LAMMPS_BASE, encoding="utf-8")
        (d / "system.data").write_text("garbage\n", encoding="utf-8")
        _, meta = vi.run_examples_dir_full(str(d.parent))
        self.assertIn("L3_bad_data/input.in", meta["incomplete"])


# ---------------------------------------------------------------------------
# (r) runner: K-series KPOINTS/README consistency (audit 10.1)
# ---------------------------------------------------------------------------

class TestRunnerKpoints(Case):
    MP_KPOINTS = "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0.0 0.0 0.0\n"
    GAMMA_KPOINTS = "Automatic mesh\n0\nGamma\n9 9 9\n0.0 0.0 0.0\n"
    LINEMODE_KPOINTS = ("Band structure\n20\nLine-mode\nrec\n"
                        "0.0 0.0 0.0 GAMMA\n0.0 0.5 0.0 X\n")

    def make_kdir(self, name, kpoints=None, readme=None):
        d = self.dir / "examples" / name
        d.mkdir(parents=True)
        if kpoints is not None:
            (d / "KPOINTS").write_text(kpoints, encoding="utf-8")
        if readme is not None:
            (d / "README.md").write_text(readme, encoding="utf-8")
        return str(self.dir / "examples")

    def test_consistent_mp_example_clean(self):
        exdir = self.make_kdir("K1_mp", self.MP_KPOINTS,
                               "# K1\nExplicit Monkhorst-Pack scheme.\n")
        results, _ = vi.run_examples_dir_full(exdir)
        self.assertIn("K1_mp/KPOINTS", results)
        self.assertEqual(self.errors(results["K1_mp/KPOINTS"]), [])

    def test_readme_scheme_mismatch_is_error(self):
        exdir = self.make_kdir("K2_bad", self.GAMMA_KPOINTS,
                               "# K2\nExplicit Monkhorst-Pack scheme.\n")
        results, _ = vi.run_examples_dir_full(exdir)
        self.assertIn("KPOINTS_README_MISMATCH", self.codes(results["K2_bad/KPOINTS"]))

    def test_malformed_kpoints_is_error(self):
        exdir = self.make_kdir("K3_bad", "comment\nnot_an_integer\nGamma\n9 9 9\n",
                               "# K3\nGamma-centered mesh.\n")
        results, _ = vi.run_examples_dir_full(exdir)
        self.assertIn("KPOINTS_MALFORMED", self.codes(results["K3_bad/KPOINTS"]))

    def test_k_dir_without_kpoints_is_error(self):
        exdir = self.make_kdir("K4_missing", None, "# K4\nGamma-centered mesh.\n")
        results, _ = vi.run_examples_dir_full(exdir)
        self.assertIn("KPOINTS_MISSING", self.codes(results["K4_missing/KPOINTS"]))

    def test_unverifiable_or_missing_claims_are_noted_not_passed_silently(self):
        exdir = self.make_kdir("K5_line", self.LINEMODE_KPOINTS,
                               "# K5\nBand structure line-mode path.\n")
        results, meta = vi.run_examples_dir_full(exdir)
        self.assertEqual(self.errors(results["K5_line/KPOINTS"]), [])
        self.assertTrue(any("NOT verifiable" in n for n in meta["notes"]))

    def test_readme_without_scheme_claim_noted_as_skipped(self):
        exdir = self.make_kdir("K6_note", self.GAMMA_KPOINTS, "# K6\nAuxiliary run.\n")
        results, meta = vi.run_examples_dir_full(exdir)
        self.assertEqual(self.errors(results["K6_note/KPOINTS"]), [])
        self.assertTrue(any("skipped" in n for n in meta["notes"]))

    def test_shipped_kseries_examples_are_checked_and_clean(self):
        results = vi.run_examples_dir(str(ROOT / "examples"))
        for name in ("K5_hex_band", "K6_explicit_MP", "K7_explicit_Gamma",
                     "K8_auto_install"):
            label = f"{name}/KPOINTS"
            self.assertIn(label, results)
            self.assertEqual(self.errors(results[label]), [],
                             msg=f"{label} must not gain ERROR findings")


# ---------------------------------------------------------------------------
# (s) EAM pair_coeff arity vs file format (pair_eam.cpp, runtime-verified)
# ---------------------------------------------------------------------------

class TestEamPairCoeffArgs(Case):
    def _with_eam(self, style_line, coeff_line):
        return (LAMMPS_BASE
                .replace("pair_style eam/alloy", style_line)
                .replace("pair_coeff * * Al.eam Al", coeff_line))

    def test_funcfl_eam_with_element_symbol_is_error(self):
        # 4-arg form (element symbol) on plain `pair_style eam`: pair_eam.cpp
        # enforces narg == 3 for funcfl files -> "Incorrect args" abort
        findings = self.lammps(self._with_eam(
            "pair_style eam", "pair_coeff * * Al_u3.eam Al"))
        hits = [x for x in findings if x.code == "LAMMPS_EAM_PAIRCOEFF_ARGS"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.ERROR)

    def test_funcfl_eam_three_args_clean(self):
        findings = self.lammps(self._with_eam(
            "pair_style eam", "pair_coeff * * Al_u3.eam"))
        self.assertNotIn("LAMMPS_EAM_PAIRCOEFF_ARGS", self.codes(findings))

    def test_setfl_alloy_missing_element_symbol_is_error(self):
        findings = self.lammps(self._with_eam(
            "pair_style eam/alloy", "pair_coeff * * Al99.eam.alloy"))
        hits = [x for x in findings if x.code == "LAMMPS_EAM_PAIRCOEFF_ARGS"]
        self.assertTrue(hits)
        self.assertEqual(hits[0].level, vi.ERROR)

    def test_setfl_fs_missing_element_symbol_is_error(self):
        findings = self.lammps(self._with_eam(
            "pair_style eam/fs", "pair_coeff * * Al99.eam.fs"))
        self.assertIn("LAMMPS_EAM_PAIRCOEFF_ARGS", self.codes(findings))

    def test_setfl_alloy_with_element_symbol_clean(self):
        # LAMMPS_BASE itself: eam/alloy + `pair_coeff * * Al.eam Al`
        findings = self.lammps(LAMMPS_BASE)
        self.assertNotIn("LAMMPS_EAM_PAIRCOEFF_ARGS", self.codes(findings))


if __name__ == "__main__":
    unittest.main()
