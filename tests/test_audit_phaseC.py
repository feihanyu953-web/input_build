#!/usr/bin/env python3
"""
Phase-C validator architecture tests (scripts/validate_input.py):

  LAMMPS (a) --data real implementation: parse_lammps_data (Masses section,
             atoms / atom-types counts) and the H-aware LAMMPS_NO_SHAKE rule —
             data-confirmed H keeps the WARN with an explicit data-check note,
             data-confirmed no-H suppresses the heuristic WARN
         (b) --data missing / unparseable -> WARN LAMMPS_DATA_UNREADABLE
  VASP   (c) --kpoints standalone validation: automatic-mesh / line-mode /
             explicit-list syntax, line-mode points > 0, explicit coordinate
             count vs line 2, mesh-dimension and Gamma-only density heuristics
  CLI    (d) --verified KEY=VALUE (audit P2-04): a user-declared convergence
             value downgrades the mapped heuristic WARN to INFO tagged
             user-verified; a mismatching value (or a value the file does not
             set) leaves the WARN standing; ERROR findings never downgrade

Run from the skill directory:
    python -m unittest discover -s tests -p "test_audit_phaseC.py" -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory
SCRIPT = ROOT / "scripts" / "validate_input.py"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")

FIXTURES = Path(__file__).resolve().parent / "fixtures"

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

FE_BCC = """\
Fe bcc
1.0
2.8665 0.0 0.0
0.0 2.8665 0.0
0.0 0.0 2.8665
Fe
2
Direct
0.0 0.0 0.0
0.5 0.5 0.5
"""

H2O_POSCAR = """\
water in a box
1.0
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
O H
1 2
Direct
0.500 0.500 0.500
0.576 0.558 0.500
0.424 0.558 0.500
"""

# 2 fs (units metal) without fix shake/rigid -> shake + timestep WARNs
LAMMPS_2FS = """\
units metal
atom_style atomic
boundary p p p
read_data system.data
pair_style eam/alloy
pair_coeff * * Al.eam Al
velocity all create 300.0 12345
neighbor 2.0 bin
timestep 0.002
fix 1 all nvt temp 300.0 300.0 0.05
thermo 100
dump 1 all custom 100 traj.lammpstrj id type x y z
run 1000
"""

LAMMPS_DATA_H2O = """\
LAMMPS data file (water)

3 atoms
2 atom types

0.0 20.0 xlo xhi
0.0 20.0 ylo yhi
0.0 20.0 zlo zhi

Masses

1 15.9994
2 1.008

Atoms # atomic

1 2 10.0 10.0 10.30
2 1 10.0 10.76 9.70
3 1 9.24 10.76 9.70
"""

LAMMPS_DATA_AL = """\
LAMMPS data file (fcc Al)

4 atoms
1 atom types

0.0 4.0495 xlo xhi
0.0 4.0495 ylo yhi
0.0 4.0495 zlo zhi

Masses

1 26.9815

Atoms # atomic

1 1 0.0 0.0 0.0
2 1 2.02475 2.02475 0.0
3 1 2.02475 0.0 2.02475
4 1 0.0 2.02475 2.02475
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

    def codes(self, findings):
        return {x.code for x in findings}

    def errors(self, findings):
        return [x for x in findings if x.level == vi.ERROR]

    def level(self, findings, code):
        hits = [x for x in findings if x.code == code]
        self.assertTrue(hits, f"{code} not found in {findings}")
        return hits[0].level

    def run_cli(self, *cli_args):
        # the validator emits UTF-8 (em-dashes etc.); the Windows default locale
        # codec (GBK) would choke on them, so decode explicitly
        return subprocess.run(
            [sys.executable, str(SCRIPT), *cli_args],
            capture_output=True, encoding="utf-8", errors="replace",
            cwd=str(self.dir), timeout=60)


# ---------------------------------------------------------------------------
# (a/b) LAMMPS data-file parsing
# ---------------------------------------------------------------------------

class TestLammpsDataParsing(Case):
    def test_parses_masses_and_header_counts(self):
        data = vi.parse_lammps_data(self.write("h2o.data", LAMMPS_DATA_H2O))
        self.assertEqual(data.natoms, 3)
        self.assertEqual(data.ntypes, 2)
        self.assertEqual(data.masses, {1: 15.9994, 2: 1.008})
        self.assertTrue(data.has_h)

    def test_no_h_masses(self):
        data = vi.parse_lammps_data(self.write("al.data", LAMMPS_DATA_AL))
        self.assertEqual(data.natoms, 4)
        self.assertEqual(data.ntypes, 1)
        self.assertFalse(data.has_h)

    def test_data_without_masses_section_still_parses(self):
        # shipped fixture: minimal ASE-written data file without a Masses section
        data = vi.parse_lammps_data(str(FIXTURES / "system_Al.data"))
        self.assertEqual(data.natoms, 4)
        self.assertEqual(data.ntypes, 1)
        self.assertIsNone(data.masses)
        self.assertIsNone(data.has_h)  # H status unresolved, not a parse failure

    def test_h_mass_threshold_excludes_heavier_types(self):
        text = LAMMPS_DATA_H2O.replace("2 1.008", "2 2.014")  # deuterium-like
        data = vi.parse_lammps_data(self.write("d2o.data", text))
        self.assertFalse(data.has_h)  # 2.014 > 1.008 * 1.10

    def test_garbage_file_raises(self):
        with self.assertRaises(ValueError):
            vi.parse_lammps_data(self.write("junk.data", "hello world\nnot a data file\n"))

    def test_malformed_masses_line_raises(self):
        with self.assertRaises(ValueError):
            vi.parse_lammps_data(self.write(
                "bad.data", "bad\n3 atoms\n1 atom types\n\nMasses\n\n1 not_a_mass\n"))


# ---------------------------------------------------------------------------
# (a/b) --data-aware LAMMPS_NO_SHAKE + unreadable-data WARN
# ---------------------------------------------------------------------------

class TestDataShakeRule(Case):
    def lammps(self, text=LAMMPS_2FS, data_path=None):
        return vi.validate_lammps_one(self.write("in.test", text),
                                      data_path=data_path)

    def test_no_data_heuristic_warn_unchanged(self):
        findings = self.lammps()
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)
        msg = next(x for x in findings if x.code == "LAMMPS_NO_SHAKE").message
        self.assertIn("H-containing systems need bond constraints", msg)
        self.assertNotIn("data-file check", msg)

    def test_data_confirms_h_warns_with_data_note(self):
        findings = self.lammps(data_path=self.write("h2o.data", LAMMPS_DATA_H2O))
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)
        msg = next(x for x in findings if x.code == "LAMMPS_NO_SHAKE").message
        self.assertIn("Masses confirm H", msg)      # data 实检 note, still WARN
        self.assertIn("data-file check", msg)

    def test_data_without_h_suppresses_shake_warn(self):
        findings = self.lammps(data_path=self.write("al.data", LAMMPS_DATA_AL))
        self.assertNotIn("LAMMPS_NO_SHAKE", self.codes(findings))
        self.assertNotIn("LAMMPS_TIMESTEP_HIGH", self.codes(findings))

    def test_constraint_on_unrelated_group_does_not_suppress_h_warnings(self):
        text = LAMMPS_2FS.replace(
            "fix 1 all nvt temp 300.0 300.0 0.05\n",
            "fix 1 all nvt temp 300.0 300.0 0.05\n"
            "group spectator type 1\n"
            "fix 2 spectator shake 1.0e-4 20 10 b 1 a 1\n")
        findings = self.lammps(
            text, data_path=self.write("h2o.data", LAMMPS_DATA_H2O))
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)
        self.assertEqual(self.level(findings, "LAMMPS_TIMESTEP_HIGH"), vi.WARN)

    def test_later_large_timestep_run_is_not_hidden_by_first_timestep(self):
        text = (LAMMPS_2FS.replace("timestep 0.002", "timestep 0.0005")
                .replace("run 1000", "run 10\ntimestep 0.002\nrun 10"))
        findings = self.lammps(
            text, data_path=self.write("h2o.data", LAMMPS_DATA_H2O))
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)
        self.assertEqual(self.level(findings, "LAMMPS_TIMESTEP_HIGH"), vi.WARN)

    def test_data_without_masses_falls_back_to_heuristic(self):
        findings = self.lammps(data_path=str(FIXTURES / "system_Al.data"))
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)
        self.assertNotIn("LAMMPS_DATA_UNREADABLE", self.codes(findings))

    def test_missing_data_file_warns_and_heuristic_still_applies(self):
        findings = self.lammps(data_path=str(self.dir / "no_such.data"))
        self.assertEqual(self.level(findings, "LAMMPS_DATA_UNREADABLE"), vi.WARN)
        # data unavailable -> the shake reminder falls back to the heuristic
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)

    def test_unparseable_data_file_warns(self):
        findings = self.lammps(data_path=self.write("junk.data", "garbage\n"))
        self.assertEqual(self.level(findings, "LAMMPS_DATA_UNREADABLE"), vi.WARN)


# ---------------------------------------------------------------------------
# (c) standalone --kpoints validation
# ---------------------------------------------------------------------------

class TestKpointsFile(Case):
    MP = "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0.0 0.0 0.0\n"
    GAMMA = "Automatic mesh\n0\nGamma\n8 8 8\n0.0 0.0 0.0\n"
    LINEMODE = ("Band structure\n20\nLine-mode\nrec\n"
                "0.0 0.0 0.0 GAMMA\n0.0 0.5 0.0 X\n"
                "0.0 0.5 0.0 X\n0.5 0.5 0.0 M\n")

    def kpoints(self, text):
        return vi.validate_kpoints_file(self.write("KPOINTS", text))

    def test_valid_monkhorst_mesh_clean(self):
        self.assertEqual(self.kpoints(self.MP), [])

    def test_valid_gamma_mesh_clean(self):
        self.assertEqual(self.kpoints(self.GAMMA), [])

    def test_gamma_only_mesh_warns(self):
        findings = self.kpoints(self.GAMMA.replace("8 8 8", "1 1 1"))
        self.assertEqual(self.level(findings, "KPOINTS_GAMMA_ONLY"), vi.WARN)
        self.assertEqual(self.errors(findings), [])

    def test_zero_mesh_dimension_is_error(self):
        findings = self.kpoints(self.MP.replace("9 9 9", "9 0 9"))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_noninteger_mesh_is_error(self):
        findings = self.kpoints(self.MP.replace("9 9 9", "9 x 9"))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_unknown_mode_keyword_is_error(self):
        findings = self.kpoints(self.MP.replace("Monkhorst-Pack", "Frobnicate"))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_linemode_with_zero_points_is_error(self):
        # line 2 = 0 (automatic mesh) contradicts Line-mode on line 3:
        # a line-mode path needs N > 0 points per segment
        findings = self.kpoints(self.LINEMODE.replace("20\nLine-mode", "0\nLine-mode"))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_linemode_valid_syntax_ok_with_info_note(self):
        findings = self.kpoints(self.LINEMODE)
        self.assertEqual(self.errors(findings), [])
        self.assertEqual(self.level(findings, "KPOINTS_LINEMODE_PATH_UNVERIFIED"),
                         vi.INFO)

    def test_linemode_odd_endpoint_count_is_error(self):
        text = ("Band structure\n20\nLine-mode\nrec\n"
                "0.0 0.0 0.0 GAMMA\n0.0 0.5 0.0 X\n0.5 0.5 0.0 M\n")
        findings = self.kpoints(text)
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_linemode_missing_rec_cart_is_error(self):
        findings = self.kpoints(self.LINEMODE.replace("rec\n", "foo\n"))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_linemode_bad_endpoint_line_is_error(self):
        findings = self.kpoints(
            self.LINEMODE.replace("0.0 0.5 0.0 X", "0.0 0.5 X", 1))
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_explicit_list_count_match_clean(self):
        text = ("Explicit list\n2\nReciprocal\n"
                "0.0 0.0 0.0 1.0\n0.25 0.25 0.25 1.0\n")
        self.assertEqual(self.kpoints(text), [])

    def test_explicit_list_count_mismatch_is_error(self):
        text = ("Explicit list\n3\nReciprocal\n"
                "0.0 0.0 0.0 1.0\n0.25 0.25 0.25 1.0\n")
        findings = self.kpoints(text)
        self.assertIn("KPOINTS_COUNT_MISMATCH", self.codes(findings))

    def test_explicit_list_bad_coordinate_is_error(self):
        text = "Explicit list\n1\nCartesian\n0.0 0.0 z 1.0\n"
        findings = self.kpoints(text)
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_too_few_lines_is_error(self):
        findings = self.kpoints("comment\n0\nGamma\n")
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_noninteger_line2_is_error(self):
        findings = self.kpoints("comment\nnine\nGamma\n9 9 9\n")
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))

    def test_negative_line2_is_error(self):
        findings = self.kpoints("comment\n-1\nGamma\n9 9 9\n")
        self.assertIn("KPOINTS_MALFORMED", self.codes(findings))


class TestKpointsCli(Case):
    def test_standalone_clean_exit0(self):
        kp = self.write("KPOINTS", "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0 0 0\n")
        proc = self.run_cli("--kpoints", kp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PASS", proc.stdout)

    def test_standalone_error_exit1(self):
        kp = self.write("KPOINTS", "Explicit\n3\nReciprocal\n0 0 0 1\n")
        proc = self.run_cli("--kpoints", kp)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("KPOINTS_COUNT_MISMATCH", proc.stdout)

    def test_standalone_missing_file_exit1(self):
        proc = self.run_cli("--kpoints", str(self.dir / "KPOINTS.absent"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("KPOINTS_MISSING", proc.stdout)

    def test_kpoints_format_checked_alongside_incar(self):
        incar = self.incar({"IBRION": "-1", "NSW": "0", "ENCUT": "400"})
        kp = self.write("KPOINTS", "Automatic mesh\n0\nGamma\n1 1 1\n")
        proc = self.run_cli("--incar", incar, "--kpoints", kp)
        self.assertIn("KPOINTS_GAMMA_ONLY", proc.stdout)


# ---------------------------------------------------------------------------
# (d2) three-tier validation semantics (audit P2-04)
# ---------------------------------------------------------------------------

class TestValidationTiers(Case):
    def test_clean_static_validation_is_not_physics_convergence(self):
        tiers = vi.validation_tiers([])
        self.assertEqual(tiers["overall"], "STATIC_PASS")
        self.assertEqual(tiers["syntax"], "PASS")
        self.assertEqual(tiers["combination"], "PASS")
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")

    def test_warning_is_combination_pass_with_warnings(self):
        tiers = vi.validation_tiers([
            vi.Finding(vi.WARN, "HEURISTIC", "review me")])
        self.assertEqual(tiers["overall"], "STATIC_PASS")
        self.assertEqual(tiers["combination"], "PASS_WITH_WARNINGS")
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")

    def test_parse_error_blocks_combination(self):
        tiers = vi.validation_tiers([
            vi.Finding(vi.ERROR, "CP2K_PARSE", "bad section")])
        self.assertEqual(tiers["overall"], "FAIL")
        self.assertEqual(tiers["syntax"], "FAIL")
        self.assertEqual(tiers["combination"], "BLOCKED")
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")

    def test_kpoints_count_mismatch_is_syntax_failure(self):
        tiers = vi.validation_tiers([
            vi.Finding(vi.ERROR, "KPOINTS_COUNT_MISMATCH", "wrong row count")])
        self.assertEqual(tiers["syntax"], "FAIL")
        self.assertEqual(tiers["combination"], "BLOCKED")

    def test_invalid_keyword_value_is_syntax_failure(self):
        for code in ("VASP_VALUE_UNPARSEABLE", "LAMMPS_TIMESTEP_INVALID",
                     "CP2K_WF_DIPOLE_VALUE_INVALID",
                     "CP2K_WF_DIPOLE_DIR_INVALID"):
            with self.subTest(code=code):
                tiers = vi.validation_tiers([
                    vi.Finding(vi.ERROR, code, "invalid literal")])
                self.assertEqual(tiers["syntax"], "FAIL")
                self.assertEqual(tiers["combination"], "BLOCKED")

    def test_cp2k_structural_placement_errors_are_syntax_failures(self):
        for code in ("CP2K_MISPLACED_SECTION", "CP2K_BAND_HIERARCHY"):
            with self.subTest(code=code):
                tiers = vi.validation_tiers([
                    vi.Finding(vi.ERROR, code, "invalid section hierarchy")])
                self.assertEqual(tiers["syntax"], "FAIL")
                self.assertEqual(tiers["combination"], "BLOCKED")

    def test_missing_context_is_incomplete_not_physics_pass(self):
        tiers = vi.validation_tiers([], incomplete=True)
        self.assertEqual(tiers["overall"], "INCOMPLETE")
        self.assertEqual(tiers["syntax"], "PASS")
        self.assertEqual(tiers["combination"], "INCOMPLETE")
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")

    def test_json_exposes_tiers(self):
        kp = self.write("KPOINTS", "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0 0 0\n")
        proc = self.run_cli("--kpoints", kp, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["validation"]["overall"], "STATIC_PASS")
        self.assertEqual(payload["validation"]["physics"], "NOT_EVALUATED")

    def test_examples_json_exposes_per_file_tiers(self):
        exdir = self.dir / "examples" / "K1_mesh"
        exdir.mkdir(parents=True)
        (exdir / "KPOINTS").write_text(
            "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0 0 0\n",
            encoding="utf-8")
        proc = self.run_cli("--examples-dir", str(exdir.parent), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload["validation"]["K1_mesh/KPOINTS"]["overall"],
            "STATIC_PASS")

    def test_single_incar_without_poscar_is_incomplete(self):
        incar = self.incar({"ENCUT": "400", "IBRION": "-1", "NSW": "0"})
        proc = self.run_cli("--incar", incar, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["validation"]["overall"], "INCOMPLETE")
        self.assertEqual(payload["validation"]["combination"], "INCOMPLETE")

    def test_single_cp2k_with_missing_xyz_is_incomplete(self):
        inp = self.write("input.inp", CP2K_BASE)
        missing = str(self.dir / "missing.xyz")
        proc = self.run_cli("--cp2k", inp, "--xyz", missing, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["validation"]["overall"], "INCOMPLETE")
        self.assertEqual(payload["validation"]["combination"], "INCOMPLETE")

    def test_single_lammps_with_missing_data_is_incomplete(self):
        inp = self.write("input.in", LAMMPS_2FS)
        missing = str(self.dir / "missing.data")
        proc = self.run_cli("--lammps", inp, "--data", missing, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["validation"]["overall"], "INCOMPLETE")
        self.assertEqual(payload["validation"]["combination"], "INCOMPLETE")

    def test_single_lammps_with_unparseable_data_is_incomplete(self):
        inp = self.write("input.in", LAMMPS_2FS)
        data = self.write("system.data", "garbage\n")
        proc = self.run_cli("--lammps", inp, "--data", data, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["validation"]["overall"], "INCOMPLETE")
        self.assertEqual(payload["validation"]["combination"], "INCOMPLETE")
        self.assertFalse(payload["coverage"]["complete"])

    def test_text_output_names_static_pass_and_physics_status(self):
        kp = self.write("KPOINTS", "Automatic mesh\n0\nMonkhorst-Pack\n9 9 9\n0 0 0\n")
        proc = self.run_cli("--kpoints", kp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("STATIC_PASS", proc.stdout)
        self.assertIn("physics=NOT_EVALUATED", proc.stdout)


# ---------------------------------------------------------------------------
# (d) --verified KEY=VALUE (audit P2-04): WARN -> INFO user-verified
# ---------------------------------------------------------------------------

class TestVerifiedParsing(Case):
    def test_parse_ok(self):
        self.assertEqual(vi.parse_verified("ENCUT=520,CUTOFF=800"),
                         {"ENCUT": "520", "CUTOFF": "800"})

    def test_parse_normalizes_key_case_and_space(self):
        self.assertEqual(vi.parse_verified(" encut = 520 "), {"ENCUT": "520"})

    def test_parse_malformed_raises(self):
        for bad in ("ENCUT", "ENCUT=", "=520"):
            with self.assertRaises(ValueError, msg=bad):
                vi.parse_verified(bad)


class TestVerifiedVasp(Case):
    OXIDE = {"IBRION": "2", "NSW": "50", "ENCUT": "400"}

    def vasp(self, mapping, poscar, verified=None):
        _, findings = vi.validate_one(self.incar(mapping),
                                      poscar_path=self.write("POSCAR", poscar),
                                      verified=verified)
        return findings

    def test_oxide_encut_warn_demoted_to_info(self):
        findings = self.vasp(self.OXIDE, CEO2, verified={"ENCUT": "400"})
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.INFO)
        msg = next(x for x in findings if x.code == "OXIDE_ENCUT_LOW").message
        self.assertIn("user-verified ENCUT=400", msg)

    def test_unverified_warn_stays_warn(self):
        findings = self.vasp(self.OXIDE, CEO2)
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.WARN)

    def test_value_mismatch_keeps_warn(self):
        # user verified ENCUT=520, but the INCAR actually sets 400
        findings = self.vasp(self.OXIDE, CEO2, verified={"ENCUT": "520"})
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_MISMATCH"), vi.INFO)

    def test_non_numeric_value_keeps_warn(self):
        findings = self.vasp(self.OXIDE, CEO2, verified={"ENCUT": "garbage"})
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_INVALID"), vi.INFO)

    def test_non_finite_value_keeps_warn(self):
        findings = self.vasp(self.OXIDE, CEO2, verified={"ENCUT": "nan"})
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_INVALID"), vi.INFO)

    def test_non_finite_file_value_cannot_be_verified(self):
        findings = vi.apply_verified(
            [vi.Finding(vi.WARN, "OXIDE_ENCUT_LOW", "low")],
            {"ENCUT": "400"}, {"ENCUT": float("nan")})
        self.assertEqual(self.level(findings, "OXIDE_ENCUT_LOW"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_INVALID"), vi.INFO)

    def test_unmapped_code_not_demoted(self):
        # ENCUT_NOT_VERIFIED (no POTCAR) is a coverage issue, not convergence —
        # it is not in the demotion map and must stay WARN
        findings = self.vasp(self.OXIDE, CEO2, verified={"ENCUT": "400"})
        self.assertEqual(self.level(findings, "ENCUT_NOT_VERIFIED"), vi.WARN)

    def test_error_never_demoted(self):
        md = {"IBRION": "0", "NSW": "10", "POTIM": "2.0", "ISYM": "0",
              "ENCUT": "400"}
        findings = self.vasp(md, H2O_POSCAR, verified={"POTIM": "2.0"})
        self.assertEqual(self.level(findings, "MD_TIMESTEP_CAP"), vi.ERROR)

    def test_no_file_value_keeps_warn(self):
        # INCAR sets no NELMIN (effective default 2 < 4); declaring NELMIN=6
        # cannot be matched against the file, so the WARN stands
        findings = self.vasp({"IBRION": "2", "NSW": "50", "ENCUT": "400"},
                             FE_BCC, verified={"NELMIN": "6"})
        self.assertEqual(self.level(findings, "NELMIN_LOW"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_NO_FILE_VALUE"), vi.INFO)

    def test_unknown_key_produces_info_note(self):
        findings = self.vasp(self.OXIDE, CEO2, verified={"FOO": "1"})
        self.assertEqual(self.level(findings, "VERIFIED_KEY_UNKNOWN"), vi.INFO)


class TestVerifiedCp2k(Case):
    def test_cutoff_demoted(self):
        findings = vi.validate_cp2k_one(
            self.write("low.inp", CP2K_BASE.replace("CUTOFF 400", "CUTOFF 200")),
            verified={"CUTOFF": "200"})
        self.assertEqual(self.level(findings, "CP2K_CUTOFF_LOW"), vi.INFO)

    def test_cutoff_mismatch_stays_warn(self):
        findings = vi.validate_cp2k_one(
            self.write("low.inp", CP2K_BASE.replace("CUTOFF 400", "CUTOFF 200")),
            verified={"CUTOFF": "800"})
        self.assertEqual(self.level(findings, "CP2K_CUTOFF_LOW"), vi.WARN)
        self.assertIn("VERIFIED_VALUE_MISMATCH", self.codes(findings))

    def test_eps_scf_demoted(self):
        findings = vi.validate_cp2k_one(
            self.write("loose.inp",
                       CP2K_BASE.replace("EPS_SCF 1.0E-6", "EPS_SCF 1.0E-5")),
            verified={"EPS_SCF": "1.0E-5"})
        self.assertEqual(self.level(findings, "CP2K_EPS_SCF_LOOSE"), vi.INFO)


class TestVerifiedLammps(Case):
    def test_timestep_demoted(self):
        findings = vi.validate_lammps_one(
            self.write("in.test", LAMMPS_2FS), verified={"TIMESTEP": "2.0"})
        self.assertEqual(self.level(findings, "LAMMPS_TIMESTEP_HIGH"), vi.INFO)

    def test_timestep_mismatch_stays_warn(self):
        findings = vi.validate_lammps_one(
            self.write("in.test", LAMMPS_2FS), verified={"TIMESTEP": "1.0"})
        self.assertEqual(self.level(findings, "LAMMPS_TIMESTEP_HIGH"), vi.WARN)

    def test_unmapped_shake_warn_not_demoted_by_timestep_key(self):
        findings = vi.validate_lammps_one(
            self.write("in.test", LAMMPS_2FS), verified={"TIMESTEP": "2.0"})
        self.assertEqual(self.level(findings, "LAMMPS_NO_SHAKE"), vi.WARN)

    def test_verified_uses_largest_executed_timestep(self):
        text = (LAMMPS_2FS.replace("timestep 0.002", "timestep 0.0005")
                .replace("run 1000", "run 10\ntimestep 0.002\nrun 10"))
        path = self.write("in.multi", text)
        wrong = vi.validate_lammps_one(path, verified={"TIMESTEP": "0.5"})
        self.assertEqual(self.level(wrong, "LAMMPS_TIMESTEP_HIGH"), vi.WARN)
        self.assertEqual(self.level(wrong, "VERIFIED_VALUE_MISMATCH"), vi.INFO)
        matched = vi.validate_lammps_one(path, verified={"TIMESTEP": "2.0"})
        self.assertEqual(self.level(matched, "LAMMPS_TIMESTEP_HIGH"), vi.INFO)

    def test_verified_matches_unsafe_not_globally_largest_timestep(self):
        text = LAMMPS_2FS.replace(
            "run 1000",
            "fix 2 all shake 1.0e-4 20 10 b 1 a 1\n"
            "run 10\nunfix 2\ntimestep 0.0015\nrun 10")
        path = self.write("in.safe-then-unsafe", text)
        wrong = vi.validate_lammps_one(path, verified={"TIMESTEP": "2.0"})
        self.assertEqual(self.level(wrong, "LAMMPS_TIMESTEP_HIGH"), vi.WARN)
        self.assertEqual(self.level(wrong, "VERIFIED_VALUE_MISMATCH"), vi.INFO)
        matched = vi.validate_lammps_one(path, verified={"TIMESTEP": "1.5"})
        self.assertEqual(self.level(matched, "LAMMPS_TIMESTEP_HIGH"), vi.INFO)


class TestVerifiedKpoints(Case):
    def test_gamma_only_demoted_by_kpoints_key(self):
        path = self.write("KPOINTS", "Automatic mesh\n0\nGamma\n1 1 1\n")
        findings = vi.validate_kpoints_file(path)
        self.assertEqual(self.level(findings, "KPOINTS_GAMMA_ONLY"), vi.WARN)
        demoted = vi.apply_verified(
            findings, {"KPOINTS": "1x1x1"}, {"KPOINTS": (1, 1, 1)})
        self.assertEqual(self.level(demoted, "KPOINTS_GAMMA_ONLY"), vi.INFO)

    def test_mismatching_mesh_keeps_warn(self):
        path = self.write("KPOINTS", "Automatic mesh\n0\nGamma\n1 1 1\n")
        findings = vi._kpoints_cli_findings(path, {"KPOINTS": "9x9x9"})
        self.assertEqual(self.level(findings, "KPOINTS_GAMMA_ONLY"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_MISMATCH"), vi.INFO)

    def test_unparseable_mesh_keeps_warn(self):
        path = self.write("KPOINTS", "Automatic mesh\n0\nGamma\n1 1 1\n")
        findings = vi._kpoints_cli_findings(path, {"KPOINTS": "not-a-mesh"})
        self.assertEqual(self.level(findings, "KPOINTS_GAMMA_ONLY"), vi.WARN)
        self.assertEqual(self.level(findings, "VERIFIED_VALUE_INVALID"), vi.INFO)


class TestVerifiedCli(Case):
    def test_incar_verified_via_cli_json(self):
        incar = self.incar({"IBRION": "2", "NSW": "50", "ENCUT": "400"})
        poscar = self.write("POSCAR", CEO2)
        proc = self.run_cli("--incar", incar, "--poscar", poscar,
                            "--verified", "ENCUT=400", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        findings = json.loads(proc.stdout)["findings"]
        hit = next(x for x in findings if x["code"] == "OXIDE_ENCUT_LOW")
        self.assertEqual(hit["level"], "INFO")
        self.assertIn("user-verified", hit["message"])

    def test_malformed_verified_rejected_by_cli(self):
        incar = self.incar({"ENCUT": "400"})
        proc = self.run_cli("--incar", incar, "--verified", "ENCUT")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("malformed --verified entry", proc.stderr)

    def test_lammps_data_flag_via_cli_json(self):
        inp = self.write("in.test", LAMMPS_2FS)
        proc = self.run_cli("--lammps", inp,
                            "--data", str(self.dir / "absent.data"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        codes = {x["code"] for x in json.loads(proc.stdout)["findings"]}
        self.assertIn("LAMMPS_DATA_UNREADABLE", codes)


if __name__ == "__main__":
    unittest.main()
