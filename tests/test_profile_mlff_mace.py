import importlib.util
import json
import sys
import unittest
from pathlib import Path

from profile_support import VALID_MACE_SPEC, make_commands

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "profiles" / "lammps" / "mlff" / "mace"


def load_rules(self):
    rules_path = PROFILE_DIR / "rules.py"
    self.assertTrue(rules_path.exists(), f"missing rules: {rules_path}")
    module_spec = importlib.util.spec_from_file_location("mace_rules", rules_path)
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


class TestMaceProfileContract(unittest.TestCase):
    def test_profile_json_exists_and_valid(self):
        json_path = PROFILE_DIR / "profile.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["profile_id"], "mlff/mace")
        self.assertEqual(data["profile_version"], 1)
        self.assertFalse(data["trigger"]["auto_infer"])
        self.assertTrue(data["l4_acceptance"]["fail_closed"])


class TestMaceStaticRules(unittest.TestCase):
    load_rules = load_rules

    def test_valid_spec_no_errors(self):
        rules = self.load_rules()
        cmds = make_commands([("units","metal"),("atom_style","atomic"),("boundary","p p p"),
            ("read_data","system.data"),("pair_style","mace"),("pair_coeff","* * mace.model C H O N"),
            ("timestep","0.0005"),("fix","nvt all nvt temp 300.0 300.0 0.05"),("run","200000")])
        findings = rules.check_static(dict(VALID_MACE_SPEC), cmds, "")
        errors = [f for f in findings if f[0] == "ERROR"]
        self.assertEqual(errors, [], f"unexpected ERRORs: {errors}")

    def test_type_element_order_mismatch(self):
        rules = self.load_rules()
        spec = json.loads(json.dumps(VALID_MACE_SPEC))
        spec["potential"]["type_elements"] = ["H", "C", "O", "N"]
        cmds = make_commands([("pair_style","mace"),("pair_coeff","* * mace.model C H O N")])
        self.assertIn("MACE_TYPE_ELEMENT_ORDER", [f[1] for f in rules.check_static(spec, cmds, "")])

    def test_kspace_present_is_error(self):
        rules = self.load_rules()
        cmds = make_commands([("pair_style","mace"),("pair_coeff","* * mace.model C H O N"),("kspace_style","pppm 1.0e-4")])
        self.assertIn("MACE_NO_KSPACE", [f[1] for f in rules.check_static(dict(VALID_MACE_SPEC), cmds, "")])

    def test_atom_style_not_atomic_is_error(self):
        rules = self.load_rules()
        spec = json.loads(json.dumps(VALID_MACE_SPEC))
        spec["system"]["atom_style"] = "full"
        cmds = make_commands([("atom_style","full"),("pair_style","mace")])
        self.assertIn("MACE_ATOM_STYLE_ATOMIC", [f[1] for f in rules.check_static(spec, cmds, "")])

    def test_missing_model_hash_is_error(self):
        rules = self.load_rules()
        spec = json.loads(json.dumps(VALID_MACE_SPEC))
        spec["potential"]["artifacts"] = [{"path": "mace.model", "sha256": ""}]
        cmds = make_commands([("pair_style","mace")])
        self.assertIn("MACE_MODEL_HASH_PRESENT", [f[1] for f in rules.check_static(spec, cmds, "")])

    def test_efield_is_error(self):
        rules = self.load_rules()
        cmds = make_commands([("pair_style","mace"),("pair_coeff","* * mace.model C H O N"),("fix","fld all efield 0.0 0.0 0.1")])
        self.assertIn("MACE_NO_EFIELD", [f[1] for f in rules.check_static(dict(VALID_MACE_SPEC), cmds, "")])


class TestMaceL4Acceptance(unittest.TestCase):
    load_rules = load_rules

    def test_l4_blocked_when_l3_not_pass(self):
        self.assertEqual(self.load_rules().assess_l4("NOT_EVALUATED", {})[0], "BLOCKED")

    def test_l4_incomplete_without_validation_set(self):
        status, missing = self.load_rules().assess_l4("PASS", {})
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("independent_dft_validation", missing)

    def test_l4_incomplete_without_nve_drift(self):
        ctx = {"independent_dft_validation": {"energy_rmse": 0.01, "force_rmse": 0.05}}
        status, missing = self.load_rules().assess_l4("PASS", ctx)
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("nve_energy_drift", missing)

    def test_l4_pass_with_all_evidence(self):
        ctx = {"independent_dft_validation": {"energy_rmse": 0.01}, "nve_energy_drift": {"drift_eV_per_atom_per_ps": 0.003},
               "structure_coverage": "covers C-H-O-N"}
        self.assertEqual(self.load_rules().assess_l4("PASS", ctx), ("PASS", ()))
