#!/usr/bin/env python3
"""Boundary tests for typed LAMMPS GenerationSpec assessment."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final, TypeAlias

import lammps_evidence_support as support


ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_SCRIPT: Final = ROOT / "scripts" / "lammps_evidence.py"
SPEC_SCRIPT: Final = ROOT / "scripts" / "lammps_spec.py"
SPEC_PRIVATE_MODULES: Final = (
    "lammps_spec_models",
    "lammps_spec_fields",
    "lammps_spec_protocol",
    "lammps_spec_metadata",
    "lammps_spec_parser",
)
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class TestGenerationSpecAssessment(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.path = support.write_complete_case(self.root)
        self.spec_module: ModuleType | None = None

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def restore_module(self, name: str, previous: ModuleType | None) -> None:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous

    def load_module(self, name: str, path: Path) -> ModuleType:
        previous = sys.modules.get(name)
        module_spec = importlib.util.spec_from_file_location(name, path)
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        self.addCleanup(self.restore_module, name, previous)
        module_spec.loader.exec_module(module)
        return module

    def load_spec(self) -> ModuleType:
        if self.spec_module is not None:
            return self.spec_module
        self.assertTrue(SPEC_SCRIPT.exists(), f"missing module: {SPEC_SCRIPT}")
        previous_private = {
            name: sys.modules.get(name) for name in SPEC_PRIVATE_MODULES
        }
        self.load_module("lammps_evidence", EVIDENCE_SCRIPT)
        self.spec_module = self.load_module("lammps_spec", SPEC_SCRIPT)
        for name, previous in previous_private.items():
            self.addCleanup(self.restore_module, name, previous)
        return self.spec_module

    def raw(self) -> JsonObject:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, raw: JsonObject) -> None:
        self.path.write_text(json.dumps(raw), encoding="utf-8")

    def assess(self):
        return self.load_spec().assess_generation_spec(self.path)

    def assert_issue(self, assessment, status: str, code: str, path: str) -> None:
        self.assertEqual(assessment.level.status, status)
        self.assertIn((code, path), {(issue.code, issue.path) for issue in assessment.issues})

    def test_complete_case_is_typed_and_passes_with_ordered_manifest(self) -> None:
        raw = self.raw()
        for name in ("first.eam", "second.table"):
            data = name.encode()
            (self.root / name).write_bytes(data)
            raw["potential"]["artifacts"].append(
                {"path": name, "sha256": f"sha256:{hashlib.sha256(data).hexdigest()}"}
            )
        self.save(raw)

        assessment = self.assess()

        self.assertEqual(assessment.level.status, "PASS")
        self.assertIsInstance(assessment.spec, self.load_spec().GenerationSpec)
        self.assertEqual(assessment.spec.type_map, ((1, "Al"),))
        self.assertEqual(assessment.level.evidence, (self.path.name, "generation_manifest.json"))
        self.assertEqual(
            [(entry.role, entry.path) for entry in assessment.manifest],
            [("spec", self.path.name), ("input", "in.lammps"), ("data", "system.data"),
             ("potential_artifact", "first.eam"), ("potential_artifact", "second.table")],
        )

    def test_malformed_json_fails(self) -> None:
        self.path.write_text("{", encoding="utf-8")
        self.assert_issue(self.assess(), "FAIL", "SPEC_JSON_INVALID", "$")

    def test_missing_input_key_fails_at_field_path(self) -> None:
        raw = self.raw()
        del raw["input_file"]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_REQUIRED_FIELD", "$.input_file")

    def test_unknown_top_level_key_fails(self) -> None:
        raw = self.raw()
        raw["surprise"] = True
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_UNKNOWN_FIELD", "$.surprise")

    def test_boolean_schema_version_is_a_type_error(self) -> None:
        raw = self.raw()
        raw["schema_version"] = True
        self.save(raw)
        assessment = self.assess()
        self.assertEqual(assessment.level.status, "FAIL")
        self.assertEqual(
            [issue.code for issue in assessment.issues if issue.path == "$.schema_version"],
            ["SPEC_VALUE_TYPE"],
        )

    def test_nan_json_constant_fails_at_root(self) -> None:
        self.path.write_text('{"schema_version": NaN}', encoding="utf-8")
        self.assert_issue(self.assess(), "FAIL", "SPEC_JSON_INVALID", "$")

    def test_infinity_json_constant_fails_at_root(self) -> None:
        self.path.write_text('{"schema_version": Infinity}', encoding="utf-8")
        self.assert_issue(self.assess(), "FAIL", "SPEC_JSON_INVALID", "$")

    def test_missing_data_file_is_incomplete(self) -> None:
        (self.root / "system.data").unlink()
        assessment = self.assess()
        self.assertEqual(assessment.level.status, "INCOMPLETE")
        self.assertIn("system.data_file", assessment.level.missing)

    def test_data_hash_mismatch_fails(self) -> None:
        raw = self.raw()
        raw["system"]["data_sha256"] = "sha256:" + "0" * 64
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_HASH_MISMATCH", "$.system.data_sha256")

    def test_duplicate_artifact_declared_path_fails_at_second_path(self) -> None:
        raw = self.raw()
        artifact = {"path": "same.eam", "sha256": "sha256:" + "0" * 64}
        raw["potential"]["artifacts"] = [artifact, dict(artifact)]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_DUPLICATE_VALUE", "$.potential.artifacts[1].path")

    def test_type_map_keys_must_cover_atom_types(self) -> None:
        raw = self.raw()
        raw["system"]["atom_types"] = 2
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_TYPE_MAP_MISMATCH", "$.system.type_map")

    def test_arabic_indic_type_map_key_is_invalid(self) -> None:
        raw = self.raw()
        raw["system"]["type_map"] = {"١": "Al"}
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_VALUE_INVALID", "$.system.type_map.١")

    def test_superscript_type_map_key_is_invalid_without_conversion(self) -> None:
        raw = self.raw()
        raw["system"]["type_map"] = {"²": "Al"}
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_VALUE_INVALID", "$.system.type_map.²")

    def test_type_elements_must_follow_numeric_type_order(self) -> None:
        raw = self.raw()
        raw["potential"]["type_elements"] = ["H"]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_TYPE_ELEMENTS_MISMATCH", "$.potential.type_elements")

    def test_has_h_must_match_exact_h_element(self) -> None:
        raw = self.raw()
        raw["system"]["type_map"] = {"1": "H"}
        raw["potential"]["type_elements"] = ["H"]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_HAS_H_MISMATCH", "$.system.has_h")

    def test_l0_unresolved_is_incomplete(self) -> None:
        self.path = support.write_complete_case(self.root, unresolved=[{"key": "x", "blocks_level": "L0", "reason": "x"}])
        self.assert_issue(self.assess(), "INCOMPLETE", "SPEC_UNRESOLVED_L0", "$.unresolved[0]")

    def test_l4_unresolved_does_not_block_l0(self) -> None:
        self.path = support.write_complete_case(self.root, unresolved=[{"key": "x", "blocks_level": "L4", "reason": "x"}])
        self.assertEqual(self.assess().level.status, "PASS")

    def test_duplicate_unresolved_key_fails_at_second_key(self) -> None:
        unresolved = [
            {"key": "same", "blocks_level": "L4", "reason": "first"},
            {"key": "same", "blocks_level": "L4", "reason": "second"},
        ]
        self.path = support.write_complete_case(self.root, unresolved=unresolved)
        self.assert_issue(self.assess(), "FAIL", "SPEC_DUPLICATE_VALUE", "$.unresolved[1].key")

    def test_relative_paths_resolve_from_spec_directory(self) -> None:
        previous = Path.cwd()
        try:
            os.chdir(previous.parent)
            assessment = self.assess()
        finally:
            os.chdir(previous)
        self.assertEqual(assessment.spec.data_file, (self.root / "system.data").resolve())

    def test_ai_inferred_potential_provenance_fails(self) -> None:
        raw = self.raw()
        raw["provenance"]["potential"] = "ai-inferred"
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_PROVENANCE_FORBIDDEN", "$.provenance.potential")

    def test_ai_inferred_required_provenance_is_incomplete(self) -> None:
        raw = self.raw()
        raw["provenance"]["structure"] = "ai-inferred"
        self.save(raw)
        self.assert_issue(self.assess(), "INCOMPLETE", "SPEC_PROVENANCE_UNCONFIRMED", "$.provenance.structure")

    def test_invalid_protocol_units_fail(self) -> None:
        raw = self.raw()
        raw["protocol"]["units"] = "si"
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_PROTOCOL_INVALID", "$.protocol.units")

    def test_unknown_stage_kind_fails(self) -> None:
        raw = self.raw()
        raw["protocol"]["stages"][0]["kind"] = "quench"
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_STAGE_UNKNOWN_KIND", "$.protocol.stages[0].kind")

    def test_duplicate_stage_id_fails(self) -> None:
        raw = self.raw()
        raw["protocol"]["stages"].append(dict(raw["protocol"]["stages"][0]))
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_STAGE_DUPLICATE_ID", "$.protocol.stages[1].stage_id")

    def test_nve_rejects_non_null_damping(self) -> None:
        raw = self.raw()
        raw["protocol"]["stages"][0]["damping_fs"] = 10.0
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_STAGE_NULL_FORBIDDEN", "$.protocol.stages[0].damping_fs")

    def test_nvt_rejects_null_damping(self) -> None:
        raw = self.raw()
        raw["protocol"]["stages"][0]["ensemble"] = "nvt"
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_STAGE_NULL_FORBIDDEN", "$.protocol.stages[0].damping_fs")

    def test_unknown_modifier_name_fails(self) -> None:
        raw = self.raw()
        raw["modifiers"] = [{"name": "unknown_mod", "stage_id": None}]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_MODIFIER_UNKNOWN_NAME", "$.modifiers[0].name")

    def test_modifier_stage_reference_must_exist(self) -> None:
        raw = self.raw()
        raw["modifiers"] = [{"name": "dump_full", "stage_id": "missing"}]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_MODIFIER_STAGE_REF", "$.modifiers[0].stage_id")

    def test_missing_input_file_is_incomplete(self) -> None:
        (self.root / "in.lammps").unlink()
        assessment = self.assess()
        self.assertEqual(assessment.level.status, "INCOMPLETE")
        self.assertIn("input_file", assessment.level.missing)

    def test_exact_modifier_pair_duplicate_fails_but_distinct_stage_pair_is_allowed(self) -> None:
        raw = self.raw()
        second = dict(raw["protocol"]["stages"][0])
        second["stage_id"] = "run2"
        raw["protocol"]["stages"].append(second)
        raw["modifiers"] = [
            {"name": "dump_full", "stage_id": "run"},
            {"name": "dump_full", "stage_id": "run2"},
            {"name": "dump_full", "stage_id": "run"},
        ]
        self.save(raw)
        self.assert_issue(self.assess(), "FAIL", "SPEC_MODIFIER_DUPLICATE", "$.modifiers[2]")

if __name__ == "__main__":
    unittest.main()
