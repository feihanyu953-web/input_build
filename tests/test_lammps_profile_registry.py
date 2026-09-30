import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "lammps_profile.schema.json"
PROFILE_ROOT = ROOT / "profiles" / "lammps"


class TestProfileSchema(unittest.TestCase):
    def test_schema_declares_closed_contract_fields(self):
        self.assertTrue(SCHEMA.exists(), f"missing schema: {SCHEMA}")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["profile_version"]["const"], 1)
        self.assertEqual(schema["properties"]["trigger"]["properties"]["auto_infer"]["const"], False)
        self.assertEqual(schema["properties"]["l4_acceptance"]["properties"]["fail_closed"]["const"], True)
        self.assertEqual(
            set(schema["required"]),
            {"profile_id", "profile_version", "trigger", "required_spec_fields",
             "renderer_extensions", "static_rules", "capability_requirements",
             "smoke_protocol", "l4_acceptance", "unresolved_behavior",
             "official_refs", "post_run_handoff"},
        )
        self.assertFalse(schema.get("additionalProperties", True))


class TestProfileRegistry(unittest.TestCase):
    def load_registry(self):
        registry_path = ROOT / "profiles" / "lammps" / "registry.py"
        self.assertTrue(registry_path.exists(), f"missing registry: {registry_path}")
        module_spec = importlib.util.spec_from_file_location("lammps_profile_registry", registry_path)
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

    def test_discover_finds_three_profiles(self):
        reg = self.load_registry()
        profiles = reg.discover_profiles()
        self.assertEqual(set(profiles.keys()), {"mlff/mace", "constant_potential", "interface_water"})

    def test_activate_rejects_unknown_id(self):
        reg = self.load_registry()
        available = reg.discover_profiles()
        composed = reg.activate_profiles(["mlff/mace", "nonexistent"], available)
        self.assertTrue(composed.has_conflict)
        self.assertIn("PROFILE_UNKNOWN_ID", [c.conflict_code for c in composed.conflicts])

    def test_activate_single_profile_no_conflict(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["mlff/mace"])
        self.assertFalse(composed.has_conflict)
        self.assertEqual(composed.active_ids, ("mlff/mace",))

    def test_activate_water_plus_conp_compatible(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["interface_water", "constant_potential"])
        self.assertFalse(composed.has_conflict)

    def test_activate_mace_plus_conp_conflict(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["mlff/mace", "constant_potential"])
        self.assertTrue(composed.has_conflict)
        self.assertIn("PROFILE_CONFLICT_MLFF_CONP", [c.conflict_code for c in composed.conflicts])

    def test_mace_plus_water_compatible(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["mlff/mace", "interface_water"])
        self.assertFalse(composed.has_conflict)
        self.assertEqual(set(composed.active_ids), {"mlff/mace", "interface_water"})

    def test_priority_order_mace_before_water(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["interface_water", "mlff/mace"])
        self.assertEqual(composed.active_ids, ("mlff/mace", "interface_water"))

    def test_merged_capability_requirements_union(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["mlff/mace", "constant_potential"])
        cap_values = [c.value for c in composed.merged_capability_requirements]
        self.assertIn("ML-MACE", cap_values)
        self.assertIn("ELECTRODE", cap_values)

    def test_merged_static_rule_codes_no_dedup(self):
        reg = self.load_registry()
        composed = reg.activate_profiles(["mlff/mace", "interface_water"])
        codes = composed.merged_static_rule_codes
        self.assertIn("MACE_TYPE_ELEMENT_ORDER", codes)
        self.assertIn("WATER_HO_MAPPING_EXPLICIT", codes)

    def test_run_static_rules_through_registry(self):
        reg = self.load_registry()
        contract = reg.discover_profiles()["mlff/mace"]
        from profile_support import VALID_MACE_SPEC, make_commands
        cmds = make_commands([("pair_style","mace"),("pair_coeff","* * mace.model C H O N"),("kspace_style","pppm 1.0e-4")])
        findings = reg.run_profile_static_rules(contract, VALID_MACE_SPEC, cmds, "")
        self.assertIn("MACE_NO_KSPACE", [f[1] for f in findings])

    def test_assess_l4_through_registry(self):
        reg = self.load_registry()
        contract = reg.discover_profiles()["mlff/mace"]
        status, missing = reg.assess_profile_l4(contract, "PASS", {})
        self.assertEqual(status, "INCOMPLETE")
        self.assertIn("independent_dft_validation", missing)


class TestProfileRendererExtensions(unittest.TestCase):
    def load_registry(self):
        registry_path = ROOT / "profiles" / "lammps" / "registry.py"
        self.assertTrue(registry_path.exists())
        module_spec = importlib.util.spec_from_file_location("lammps_profile_registry_ext", registry_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        return module

    def test_mace_renderer_extensions_declared(self):
        reg = self.load_registry()
        exts = reg.discover_profiles()["mlff/mace"].renderer_extensions
        anchors = [e.anchor for e in exts]
        self.assertIn("system_setup", anchors)
        self.assertIn("force_field", anchors)
        self.assertIn("output", anchors)

    def test_conp_renderer_extensions_declared(self):
        reg = self.load_registry()
        exts = reg.discover_profiles()["constant_potential"].renderer_extensions
        anchors = [e.anchor for e in exts]
        self.assertIn("force_field", anchors)
        self.assertIn("constraints", anchors)
        self.assertIn("output", anchors)

    def test_water_renderer_extensions_declared(self):
        reg = self.load_registry()
        exts = reg.discover_profiles()["interface_water"].renderer_extensions
        anchors = [e.anchor for e in exts]
        self.assertIn("constraints", anchors)
        self.assertIn("output", anchors)


class TestProfileCapabilityFixtureMapping(unittest.TestCase):
    def load_registry(self):
        registry_path = ROOT / "profiles" / "lammps" / "registry.py"
        self.assertTrue(registry_path.exists())
        module_spec = importlib.util.spec_from_file_location("lammps_profile_registry_caps", registry_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        return module

    def test_mace_requires_ml_mace_package(self):
        reg = self.load_registry()
        caps = reg.discover_profiles()["mlff/mace"].capability_requirements
        kinds = [(c.kind, c.value) for c in caps]
        self.assertIn(("package", "ML-MACE"), kinds)
        self.assertIn(("pair_style", "mace"), kinds)

    def test_conp_requires_electrode_package_and_kspace(self):
        reg = self.load_registry()
        caps = reg.discover_profiles()["constant_potential"].capability_requirements
        kinds = [(c.kind, c.value) for c in caps]
        self.assertIn(("package", "ELECTRODE"), kinds)
        self.assertIn(("kspace_style", "pppm/electrode"), kinds)

    def test_water_has_no_own_capability_requirements(self):
        reg = self.load_registry()
        caps = reg.discover_profiles()["interface_water"].capability_requirements
        self.assertEqual(caps, ())


class TestProfileSmokeProtocolDeclared(unittest.TestCase):
    def load_registry(self):
        registry_path = ROOT / "profiles" / "lammps" / "registry.py"
        self.assertTrue(registry_path.exists())
        module_spec = importlib.util.spec_from_file_location("lammps_profile_registry_smoke", registry_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        return module

    def test_mace_smoke_has_nve_drift_step(self):
        reg = self.load_registry()
        steps = reg.discover_profiles()["mlff/mace"].smoke_steps
        self.assertTrue(any("NVE" in s for s in steps), f"NVE drift step not found in {steps}")
        self.assertTrue(reg.discover_profiles()["mlff/mace"].smoke_thresholds)

    def test_conp_smoke_has_zero_V_step(self):
        reg = self.load_registry()
        steps = reg.discover_profiles()["constant_potential"].smoke_steps
        self.assertTrue(any("0 V" in s for s in steps), f"0 V step not found in {steps}")

    def test_water_smoke_has_integrity_check(self):
        reg = self.load_registry()
        checks = reg.discover_profiles()["interface_water"].smoke_checks
        self.assertTrue(any("integrity" in c.lower() or "count" in c.lower() for c in checks),
                        f"water integrity check not found in {checks}")
