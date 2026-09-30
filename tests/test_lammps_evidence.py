#!/usr/bin/env python3
"""Contract tests for the LAMMPS generation evidence schema."""

import json
import hashlib
import importlib.util
import re
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Final

import lammps_evidence_support as support


ROOT: Final = Path(__file__).resolve().parent.parent
SCHEMA_PATH: Final = ROOT / "schemas" / "lammps_generation_spec.schema.json"
EVIDENCE_SCRIPT: Final = ROOT / "scripts" / "lammps_evidence.py"
EXPECTED_INPUT: Final = "units metal\natom_style atomic\nboundary p p p\nread_data system.data\npair_style lj/cut 8.5\npair_coeff * * 0.0103 2.5\ntimestep 0.001\nfix integrator all nve\nthermo 10\nrun 10\n"
EXPECTED_DATA: Final = "LAMMPS data\n\n1 atoms\n1 atom types\n\nMasses\n\n1 26.9815\n\nAtoms # atomic\n\n1 1 0.0 0.0 0.0\n"
MODIFIER_NAMES: Final = ["efield_lammps", "shake_lammps", "analysis_rdf_msd", "analysis_hbond", "ensemble_langevin", "temp_ramp", "dump_full", "wall_slab"]
PROVENANCE_SOURCES: Final = ["user-provided", "user-confirmed", "detected", "generated", "ai-inferred"]


class TestLammpsGenerationSpecSchema(unittest.TestCase):
    def assert_field_schemas(
        self, assertions: Mapping[str, tuple[Mapping[str, str], Mapping[str, str]]]
    ) -> None:
        for field_path, (field_schema, expected) in assertions.items():
            with self.subTest(field_path=field_path):
                self.assertEqual(field_schema, expected)

    def test_schema_declares_initial_generation_contract(self) -> None:
        self.assertTrue(SCHEMA_PATH.exists(), f"missing schema: {SCHEMA_PATH}")

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        definitions = schema["$defs"]

        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema.get("$id"), "lammps_generation_spec.schema.json")
        self.assertEqual(schema["title"], "input_build LAMMPS GenerationSpec")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(schema["properties"]["code"]["const"], "lammps")
        self.assertEqual(
            set(schema["required"]),
            {
                "schema_version",
                "code",
                "task",
                "input_file",
                "system",
                "potential",
                "protocol",
                "profiles",
                "modifiers",
                "provenance",
                "unresolved",
            },
        )
        self.assertIn("runtime", schema["properties"])
        self.assertNotIn("runtime", schema["required"])
        self.assertTrue(
            {
                "nonEmptyString",
                "sha256",
                "lammpsUnits",
                "ensemble",
                "modifierName",
                "provenanceSource",
            }.issubset(definitions)
        )
        self.assertEqual(definitions["nonEmptyString"], {"minLength": 1, "type": "string"})
        self.assertEqual(
            definitions["sha256"],
            {"pattern": "^sha256:[0-9a-f]{64}$", "type": "string"},
        )
        self.assertEqual(definitions["lammpsUnits"]["enum"], ["metal", "real"])
        self.assertEqual(definitions["ensemble"]["enum"], ["nve", "nvt", "nve_langevin"])
        self.assertEqual(definitions["modifierName"]["enum"], MODIFIER_NAMES)
        self.assertEqual(definitions["provenanceSource"], {"enum": PROVENANCE_SOURCES})
        self.assert_field_schemas(
            {
                "protocol.units": (
                    definitions["protocol"]["properties"]["units"],
                    {"$ref": "#/$defs/lammpsUnits"},
                ),
                "mdStage.ensemble": (
                    definitions["mdStage"]["properties"]["ensemble"],
                    {"$ref": "#/$defs/ensemble"},
                ),
                "modifierSelection.name": (
                    definitions["modifierSelection"]["properties"]["name"],
                    {"$ref": "#/$defs/modifierName"},
                ),
            },
        )
        for definition_name, kind in (("minimizeStage", "minimize"), ("mdStage", "md")):
            with self.subTest(definition_name=definition_name):
                self.assertEqual(definitions[definition_name]["properties"]["kind"]["const"], kind)
        self.assertEqual(
            set(definitions["modifierSelection"]["required"]),
            {"name", "stage_id"},
        )
        self.assert_field_schemas(
            {
                "artifact.sha256": (
                    definitions["artifact"]["properties"]["sha256"],
                    {"$ref": "#/$defs/sha256"},
                ),
                "system.data_sha256": (
                    definitions["system"]["properties"]["data_sha256"],
                    {"$ref": "#/$defs/sha256"},
                ),
            },
        )
        self.assertEqual(
            definitions["potential"]["properties"]["pair_coeff"],
            {"$ref": "#/$defs/nonEmptyString"},
        )
        runtime = definitions["runtime"]
        self.assertFalse(runtime["additionalProperties"])
        self.assertEqual(set(runtime["properties"]), {"binary", "version", "packages", "target"})
        self.assertEqual(set(runtime["required"]), {"binary", "version", "packages", "target"})
        self.assert_field_schemas(
            {
                key: (
                    definitions["provenance"]["properties"][key],
                    {"$ref": "#/$defs/provenanceSource"},
                )
                for key in ("structure", "type_map", "potential", "protocol")
            },
        )

    def test_schema_reuses_non_empty_string_definition(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        definitions = schema["$defs"]
        non_empty_string = {"$ref": "#/$defs/nonEmptyString"}
        approved_fields = {
            "input_file": schema["properties"]["input_file"],
            "task": schema["properties"]["task"],
            "profiles.items": schema["properties"]["profiles"]["items"],
            "artifact.path": definitions["artifact"]["properties"]["path"],
            "mdStage.stage_id": definitions["mdStage"]["properties"]["stage_id"],
            "minimizeStage.stage_id": definitions["minimizeStage"]["properties"]["stage_id"],
            "minimizeStage.style": definitions["minimizeStage"]["properties"]["style"],
            "potential.family": definitions["potential"]["properties"]["family"],
            "potential.pair_style": definitions["potential"]["properties"]["pair_style"],
            "potential.pair_coeff": definitions["potential"]["properties"]["pair_coeff"],
            "potential.type_elements.items": definitions["potential"]["properties"][
                "type_elements"
            ]["items"],
            "runtime.binary": definitions["runtime"]["properties"]["binary"],
            "runtime.version": definitions["runtime"]["properties"]["version"],
            "runtime.packages.items": definitions["runtime"]["properties"]["packages"][
                "items"
            ],
            "runtime.target": definitions["runtime"]["properties"]["target"],
            "system.data_file": definitions["system"]["properties"]["data_file"],
            "system.atom_style": definitions["system"]["properties"]["atom_style"],
            "system.type_map.values": definitions["system"]["properties"]["type_map"][
                "additionalProperties"
            ],
            "unresolved.key": definitions["unresolved"]["properties"]["key"],
            "unresolved.reason": definitions["unresolved"]["properties"]["reason"],
        }

        self.assert_field_schemas(
            {
                field_path: (field_schema, non_empty_string)
                for field_path, field_schema in approved_fields.items()
            }
        )
        self.assertEqual(
            definitions["modifierSelection"]["properties"]["stage_id"],
            {"type": ["string", "null"]},
        )

    def test_complete_fixture_emits_approved_round_trip_shape(self) -> None:
        self.assertEqual(support.VALID_INPUT, EXPECTED_INPUT)
        self.assertEqual(support.VALID_DATA, EXPECTED_DATA)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec_path = support.write_complete_case(root)
            raw_spec = spec_path.read_bytes()
            generation_spec = json.loads(raw_spec)

            self.assertEqual((root / "in.lammps").read_text(encoding="utf-8"), EXPECTED_INPUT)
            data_bytes = (root / "system.data").read_bytes()
            self.assertEqual(data_bytes, EXPECTED_DATA.encode("utf-8"))
            data_sha256 = generation_spec["system"]["data_sha256"]
            self.assertIsNotNone(re.fullmatch(r"sha256:[0-9a-f]{64}", data_sha256))
            self.assertEqual(data_sha256, f"sha256:{hashlib.sha256(data_bytes).hexdigest()}")
            self.assertEqual(generation_spec["potential"]["pair_coeff"], "* * 0.0103 2.5")
            self.assertEqual(
                raw_spec,
                (
                    json.dumps(
                        generation_spec,
                        indent=2,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
            )


class TestEvidenceLevels(unittest.TestCase):
    def load_evidence(self) -> ModuleType:
        self.assertTrue(EVIDENCE_SCRIPT.exists(), f"missing module: {EVIDENCE_SCRIPT}")
        module_spec = importlib.util.spec_from_file_location(
            "lammps_evidence",
            EVIDENCE_SCRIPT,
        )
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        loaded = False
        try:
            module_spec.loader.exec_module(module)
            loaded = True
        finally:
            if not loaded:
                sys.modules.pop(module_spec.name, None)
        return module

    def test_highest_level_stops_at_first_non_pass(self) -> None:
        evidence = self.load_evidence()
        statuses = {
            evidence.LevelName.L0: evidence.LevelStatus.PASS,
            evidence.LevelName.L1: evidence.LevelStatus.PASS,
            evidence.LevelName.L2: evidence.LevelStatus.NOT_EVALUATED,
            evidence.LevelName.L3: evidence.LevelStatus.PASS,
            evidence.LevelName.L4: evidence.LevelStatus.PASS,
            evidence.LevelName.L5: evidence.LevelStatus.PASS,
        }

        self.assertEqual(
            evidence.highest_contiguous_pass(statuses),
            evidence.HighestLevel.L1_STATIC_PASS,
        )

    def test_highest_level_is_none_when_l0_is_incomplete(self) -> None:
        evidence = self.load_evidence()
        statuses = {
            level: evidence.LevelStatus.NOT_EVALUATED for level in evidence.LevelName
        }
        statuses[evidence.LevelName.L0] = evidence.LevelStatus.INCOMPLETE

        self.assertEqual(
            evidence.highest_contiguous_pass(statuses),
            evidence.HighestLevel.NONE,
        )

    def test_highest_level_reaches_l5_when_all_levels_pass(self) -> None:
        evidence = self.load_evidence()
        statuses = {level: evidence.LevelStatus.PASS for level in evidence.LevelName}

        self.assertEqual(
            evidence.highest_contiguous_pass(statuses),
            evidence.HighestLevel.L5_PRODUCTION_EVIDENCE,
        )


if __name__ == "__main__":
    unittest.main()
