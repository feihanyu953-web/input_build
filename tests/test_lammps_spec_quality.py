#!/usr/bin/env python3
"""Hostile-input and loader-isolation tests for lammps_spec."""

import dataclasses
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final, TypeAlias
from unittest import mock

import lammps_evidence_support as support


ROOT: Final = Path(__file__).resolve().parent.parent
SCRIPTS: Final = ROOT / "scripts"
SPEC_PRIVATE_MODULES: Final = (
    "lammps_spec_models",
    "lammps_spec_fields",
    "lammps_spec_protocol",
    "lammps_spec_metadata",
    "lammps_spec_parser",
)
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class TestLammpsSpecQuality(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.path = support.write_complete_case(self.root)

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
        sys.modules[name] = module
        self.addCleanup(self.restore_module, name, previous)
        module_spec.loader.exec_module(module)
        return module

    def load_spec(self) -> ModuleType:
        previous_private = {
            name: sys.modules.get(name) for name in SPEC_PRIVATE_MODULES
        }
        self.load_module("lammps_evidence", SCRIPTS / "lammps_evidence.py")
        spec = self.load_module("lammps_spec", SCRIPTS / "lammps_spec.py")
        for name, previous in previous_private.items():
            self.addCleanup(self.restore_module, name, previous)
        return spec

    def raw(self) -> JsonObject:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, raw: JsonObject) -> None:
        self.path.write_text(json.dumps(raw), encoding="utf-8")

    def assert_issue(self, assessment, code: str, path: str) -> None:
        self.assertEqual(assessment.level.status, "FAIL")
        self.assertIn((code, path), {(issue.code, issue.path) for issue in assessment.issues})

    def test_standard_exponent_overflow_is_invalid(self) -> None:
        text = self.path.read_text(encoding="utf-8")
        updated = text.replace('"timestep_fs": 1.0', '"timestep_fs": 1e999')
        self.path.write_text(updated, encoding="utf-8")
        assessment = self.load_spec().assess_generation_spec(self.path)
        self.assert_issue(assessment, "SPEC_VALUE_INVALID", "$.protocol.timestep_fs")

    def test_huge_integer_float_conversion_is_invalid(self) -> None:
        raw = self.raw()
        raw["protocol"]["timestep_fs"] = 10**400
        self.save(raw)
        assessment = self.load_spec().assess_generation_spec(self.path)
        self.assert_issue(assessment, "SPEC_VALUE_INVALID", "$.protocol.timestep_fs")

    def test_extremely_long_ascii_type_key_is_a_mismatch(self) -> None:
        raw = self.raw()
        raw["system"]["type_map"] = {"9" * 10000: "Al"}
        self.save(raw)
        assessment = self.load_spec().assess_generation_spec(self.path)
        self.assert_issue(assessment, "SPEC_TYPE_MAP_MISMATCH", "$.system.type_map")

    def test_hash_oserror_marks_declared_file_unavailable(self) -> None:
        spec = self.load_spec()
        real_sha256 = spec._sha256

        def fail_data_hash(path: Path) -> str:
            if path.name == "system.data":
                raise OSError("unreadable")
            return real_sha256(path)

        with mock.patch.object(spec, "_sha256", side_effect=fail_data_hash):
            assessment = spec.assess_generation_spec(self.path)

        data_entry = next(entry for entry in assessment.manifest if entry.role == "data")
        self.assertEqual(assessment.level.status, "INCOMPLETE")
        self.assertFalse(data_entry.exists)
        self.assertIsNone(data_entry.sha256)
        self.assertIn("system.data_file", assessment.level.missing)

    def test_successful_dynamic_load_restores_previous_modules(self) -> None:
        previous_spec = ModuleType("previous_lammps_spec")
        previous_evidence = ModuleType("previous_lammps_evidence")
        module_names = (
            "lammps_spec",
            "lammps_evidence",
            "lammps_spec_models",
            "lammps_spec_fields",
            "lammps_spec_protocol",
            "lammps_spec_metadata",
            "lammps_spec_parser",
        )
        originals = {name: sys.modules.get(name) for name in module_names}
        sys.modules["lammps_spec"] = previous_spec
        sys.modules["lammps_evidence"] = previous_evidence
        try:
            self.load_spec()
            self.doCleanups()
            self.assertIs(sys.modules.get("lammps_spec"), previous_spec)
            self.assertIs(sys.modules.get("lammps_evidence"), previous_evidence)
            for name in module_names[2:]:
                with self.subTest(name=name):
                    self.assertIs(sys.modules.get(name), originals[name])
        finally:
            for name, previous in originals.items():
                self.restore_module(name, previous)

    def test_failed_dynamic_load_restores_previous_private_modules(self) -> None:
        originals = {name: sys.modules.get(name) for name in SPEC_PRIVATE_MODULES}
        previous = {name: ModuleType(f"previous_{name}") for name in SPEC_PRIVATE_MODULES}
        sys.modules.update(previous)
        copied_scripts = self.root / "scripts"
        copied_scripts.mkdir()
        for source in SCRIPTS.glob("lammps_spec*.py"):
            if source.name != "lammps_spec_parser.py":
                shutil.copy2(source, copied_scripts / source.name)
        try:
            self.load_module("lammps_evidence", SCRIPTS / "lammps_evidence.py")
            with self.assertRaises(FileNotFoundError):
                self.load_module("failing_lammps_spec", copied_scripts / "lammps_spec.py")
            for name in SPEC_PRIVATE_MODULES:
                with self.subTest(name=name):
                    self.assertIs(sys.modules.get(name), previous[name])
        finally:
            for name, original in originals.items():
                self.restore_module(name, original)

    def test_public_dataclass_fields_remain_exact(self) -> None:
        spec = self.load_spec()
        expected = {
            "MinimizeStage": ("stage_id", "style", "etol", "ftol", "maxiter", "maxeval"),
            "MdStage": ("stage_id", "ensemble", "steps", "temperature_start_K", "temperature_stop_K", "damping_fs", "velocity_temperature_K", "velocity_seed"),
            "ProtocolSpec": ("units", "timestep_fs", "stages"),
            "ModifierSelection": ("name", "stage_id"),
            "SpecIssue": ("path", "code", "message"),
            "ArtifactSpec": ("declared_path", "resolved_path", "expected_sha256"),
            "ProvenanceSpec": ("structure", "type_map", "potential", "protocol"),
            "GenerationSpec": (
                "source_path",
                "task",
                "input_declared_path",
                "input_file",
                "data_declared_path",
                "data_file",
                "data_sha256",
                "atom_count",
                "atom_types",
                "type_map",
                "has_h",
                "atom_style",
                "periodicity",
                "potential_family",
                "pair_style",
                "pair_coeff",
                "artifacts",
                "type_elements",
                "profiles",
                "protocol",
                "modifiers",
                "provenance",
                "unresolved",
            ),
            "ManifestEntry": ("role", "path", "exists", "sha256", "expected_sha256", "matches_expected"),
            "ToolEntry": ("name", "path", "sha256"),
            "SpecAssessment": ("spec", "level", "issues", "manifest"),
        }
        for name, field_names in expected.items():
            with self.subTest(name=name):
                self.assertEqual(tuple(field.name for field in dataclasses.fields(getattr(spec, name))), field_names)
        self.assertEqual(tuple(spec.LammpsUnits), ("metal", "real"))
        self.assertEqual(tuple(spec.Ensemble), ("nve", "nvt", "nve_langevin"))
        self.assertTrue(callable(spec.assess_generation_spec))
