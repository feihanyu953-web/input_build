import importlib.util
import json
import sys
import unittest
from pathlib import Path

from profile_support import VALID_WATER_SPEC, make_commands

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "profiles" / "lammps" / "interface_water"


def load_rules(self):
    rules_path = PROFILE_DIR / "rules.py"
    self.assertTrue(rules_path.exists(), f"missing rules: {rules_path}")
    module_spec = importlib.util.spec_from_file_location("water_rules", rules_path)
    self.assertIsNotNone(module_spec)
    self.assertIsNotNone(module_spec.loader)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    try:
        module_spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_spec.name, None)
        raise
    return module


class TestWaterProfileContract(unittest.TestCase):
    def test_profile_json_exists_and_valid(self):
        json_path = PROFILE_DIR / "profile.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["profile_id"], "interface_water")
        self.assertFalse(data["trigger"]["auto_infer"])
        self.assertTrue(data["l4_acceptance"]["fail_closed"])


class TestWaterStaticRules(unittest.TestCase):
    load_rules = load_rules

    def test_valid_spec_no_errors(self):
        rules = self.load_rules()
        ctx = {"water_o_type": 2, "water_h_type": 3, "water_model": "SPC/E", "water_flexibility": "rigid"}
        cmds = make_commands([("units","real"),("atom_style","full"),("boundary","p p f"),
            ("read_data","system.data"),("pair_style","lj/cut/coul/long 10.0"),("pair_coeff","* * params.dat Pt O H N Na"),
            ("kspace_style","pppm 1.0e-5"),("kspace_modify","slab 3.0"),
            ("fix","sh water shake 1.0e-4 20 10 b 1 a 1"),("fix","nvt all nvt temp 300.0 300.0 100.0"),
            ("compute","rdf1 all rdf 200 2 2 2 3 3 3"),("fix","frdf all ave/time 100 10 1000 c_rdf1[*] file rdf.dat mode vector"),
            ("timestep","2.0"),("run","100000")])
        raw = "Bonds\n1 1 1 2\n"
        findings = rules.check_static(dict(VALID_WATER_SPEC), cmds, raw, ctx)
        errors = [f for f in findings if f[0] == "ERROR"]
        self.assertEqual(errors, [], f"unexpected ERRORs: {errors}")

    def test_missing_ho_mapping_is_error(self):
        rules = self.load_rules()
        cmds = make_commands([("pair_style","lj/cut/coul/long 10.0")])
        self.assertIn("WATER_HO_MAPPING_EXPLICIT", [f[1] for f in rules.check_static(dict(VALID_WATER_SPEC), cmds, "", {})])

    def test_missing_water_model_is_error(self):
        rules = self.load_rules()
        ctx = {"water_o_type": 2, "water_h_type": 3}
        cmds = make_commands([("pair_style","lj/cut/coul/long 10.0")])
        self.assertIn("WATER_MODEL_DECLARED", [f[1] for f in rules.check_static(dict(VALID_WATER_SPEC), cmds, "", ctx)])

    def test_missing_flexibility_is_error(self):
        rules = self.load_rules()
        ctx = {"water_o_type": 2, "water_h_type": 3, "water_model": "SPC/E"}
        cmds = make_commands([("pair_style","lj/cut/coul/long 10.0")])
        self.assertIn("WATER_FLEXIBILITY_DECLARED", [f[1] for f in rules.check_static(dict(VALID_WATER_SPEC), cmds, "", ctx)])

    def test_mlff_flexible_with_shake_is_error(self):
        rules = self.load_rules()
        spec = json.loads(json.dumps(VALID_WATER_SPEC))
        spec["potential"]["family"] = "mace"
        spec["potential"]["pair_style"] = "mace"
        ctx = {"water_o_type": 2, "water_h_type": 3, "water_model": "flexible", "water_flexibility": "flexible"}
        cmds = make_commands([("pair_style","mace"),("pair_coeff","* * model.pt Pt O H N Na"),("fix","sh water shake 1.0e-4 20 10 b 1 a 1")])
        self.assertIn("WATER_NO_SHAKE_MLFF_FLEXIBLE", [f[1] for f in rules.check_static(spec, cmds, "", ctx)])

    def test_barostat_vacuum_axis_is_error(self):
        rules = self.load_rules()
        ctx = {"water_o_type": 2, "water_h_type": 3, "water_model": "SPC/E", "water_flexibility": "rigid"}
        cmds = make_commands([("boundary","p p f"),("fix","npt all npt temp 300.0 300.0 100.0 x 1.0 1.0 y 1.0 1.0 z 1.0 1.0")])
        self.assertIn("WATER_SLAB_BAROSTAT", [f[1] for f in rules.check_static(dict(VALID_WATER_SPEC), cmds, "", ctx)])

    def test_missing_analysis_outputs_is_warn(self):
        rules = self.load_rules()
        ctx = {"water_o_type": 2, "water_h_type": 3, "water_model": "SPC/E", "water_flexibility": "rigid"}
        cmds = make_commands([("pair_style","lj/cut/coul/long 10.0"),("fix","nvt all nvt temp 300.0 300.0 100.0"),("run","100000")])
        self.assertIn("WATER_ANALYSIS_OUTPUTS", [f[1] for f in rules.check_static(dict(VALID_WATER_SPEC), cmds, "", ctx)])


class TestWaterL4Acceptance(unittest.TestCase):
    load_rules = load_rules

    def test_l4_blocked_when_l3_not_pass(self):
        self.assertEqual(self.load_rules().assess_l4("INCOMPLETE", {})[0], "BLOCKED")

    def test_l4_incomplete_without_comparison_plan(self):
        status, missing = self.load_rules().assess_l4("PASS", {})
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("density_comparison_plan", missing)

    def test_l4_pass_with_all_evidence(self):
        ctx = {"density_comparison_plan": "compare z-density vs AIMD at 300K", "rdf_comparison_plan": "compare O-O RDF vs experiment", "water_integrity_evidence": {"count_conserved": True, "steps": 10000}}
        self.assertEqual(self.load_rules().assess_l4("PASS", ctx), ("PASS", ()))
