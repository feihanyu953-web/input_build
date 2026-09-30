import importlib.util
import json
import sys
import unittest
from pathlib import Path

from profile_support import VALID_CONP_SPEC, make_commands

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "profiles" / "lammps" / "constant_potential"


def load_rules(self):
    rules_path = PROFILE_DIR / "rules.py"
    self.assertTrue(rules_path.exists(), f"missing rules: {rules_path}")
    module_spec = importlib.util.spec_from_file_location("conp_rules", rules_path)
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


class TestConpProfileContract(unittest.TestCase):
    def test_profile_json_exists_and_valid(self):
        json_path = PROFILE_DIR / "profile.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["profile_id"], "constant_potential")
        self.assertFalse(data["trigger"]["auto_infer"])
        self.assertTrue(data["l4_acceptance"]["fail_closed"])


class TestConpStaticRules(unittest.TestCase):
    load_rules = load_rules

    def test_valid_spec_no_errors(self):
        rules = self.load_rules()
        cmds = make_commands([("units","real"),("atom_style","full"),("boundary","p p p"),
            ("read_data","system.data"),("pair_style","lj/cut/coul/long 12.0"),("pair_coeff","* * params.dat O H C N Na Au"),
            ("kspace_style","pppm/electrode 1.0e-7"),("group","bot type 6"),("group","top type 7"),
            ("group","electrolyte subtract all bot top"),
            ("fix","conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes etypes on"),
            ("fix_modify","conp energy yes"),("compute","qbot bot reduce sum v_q"),("compute","qtop top reduce sum v_q"),
            ("timestep","1.0"),("run","100000")])
        findings = rules.check_static(dict(VALID_CONP_SPEC), cmds, "")
        errors = [f for f in findings if f[0] == "ERROR"]
        self.assertEqual(errors, [], f"unexpected ERRORs: {errors}")

    def test_plain_pppm_is_error(self):
        rules = self.load_rules()
        cmds = make_commands([("kspace_style","pppm 1.0e-4"),("fix","conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes")])
        self.assertIn("CONP_KSPACE_ELECTRODE", [f[1] for f in rules.check_static(dict(VALID_CONP_SPEC), cmds, "")])

    def test_missing_electrode_groups_is_error(self):
        rules = self.load_rules()
        cmds = make_commands([("kspace_style","pppm/electrode 1.0e-7"),("fix","conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes")])
        self.assertIn("CONP_ELECTRODE_GROUPS_DEFINED", [f[1] for f in rules.check_static(dict(VALID_CONP_SPEC), cmds, ">>> USER: define groups")])

    def test_atom_style_not_full_is_error(self):
        rules = self.load_rules()
        spec = json.loads(json.dumps(VALID_CONP_SPEC))
        spec["system"]["atom_style"] = "atomic"
        cmds = make_commands([("atom_style","atomic")])
        self.assertIn("CONP_ATOM_STYLE_FULL", [f[1] for f in rules.check_static(spec, cmds, "")])

    def test_missing_charge_output_is_warn(self):
        rules = self.load_rules()
        cmds = make_commands([("kspace_style","pppm/electrode 1.0e-7"),("group","bot type 6"),("group","top type 7"),
            ("group","electrolyte subtract all bot top"),("fix","conp bot electrode/conp -1.0 1.805 couple top 1.0 symm on ffield yes")])
        self.assertIn("CONP_CHARGE_OUTPUT", [f[1] for f in rules.check_static(dict(VALID_CONP_SPEC), cmds, "")])


class TestConpL4Acceptance(unittest.TestCase):
    load_rules = load_rules

    def test_l4_blocked_when_l3_not_pass(self):
        self.assertEqual(self.load_rules().assess_l4("FAIL", {})[0], "BLOCKED")

    def test_l4_incomplete_without_zero_V_evidence(self):
        status, missing = self.load_rules().assess_l4("PASS", {})
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("zero_V_equilibration_evidence", missing)

    def test_l4_incomplete_without_target_potential_stability(self):
        ctx = {"zero_V_equilibration_evidence": {"charges_stable": True, "steps": 1000}}
        status, missing = self.load_rules().assess_l4("PASS", ctx)
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("target_potential_charge_stability", missing)

    def test_l4_pass_with_all_evidence(self):
        ctx = {"zero_V_equilibration_evidence": {"charges_stable": True, "steps": 1000},
               "target_potential_charge_stability": {"charges_stable": True, "potential_V": 2.0, "steps": 5000}}
        self.assertEqual(self.load_rules().assess_l4("PASS", ctx), ("PASS", ()))
