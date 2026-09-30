#!/usr/bin/env python3
"""Schema, extraction, build-CLI, and determinism tests for the LAMMPS
official examples index builder."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from lammps_examples_index_support import (
    BUILDER,
    COMMIT,
    FIXTURE,
    ROOT,
    SCHEMA,
    run_build,
)


class TestExamplesIndexSchema(unittest.TestCase):
    def test_schema_declares_phase_b_required_fields(self):
        self.assertTrue(SCHEMA.exists(), f"missing schema: {SCHEMA}")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(schema["properties"]["code"]["const"], "lammps")
        self.assertEqual(schema["properties"]["kind"]["const"], "official_examples_index")
        self.assertEqual(
            set(schema["$defs"]["allowedRepository"]["enum"]),
            {"https://github.com/lammps/lammps"},
        )
        self.assertEqual(
            set(schema["required"]),
            {"schema_version", "code", "kind", "generated_from", "entries"},
        )
        entry_required = set(schema["$defs"]["entry"]["required"])
        self.assertEqual(entry_required, {
            "id", "upstream_repository", "upstream_commit", "upstream_release",
            "upstream_path", "canonical_source_url", "retrieval_date", "sha256",
            "commands", "styles", "packages", "tags", "local_example",
        })
        self.assertRegex(
            schema["$defs"]["entry"]["properties"]["id"]["pattern"],
            r"\^lammps_examples_\[a-z0-9_\]\+\$",
        )


class BuilderTestCase(unittest.TestCase):
    """Base class that imports the builder module fresh for each test."""

    def load_builder(self) -> ModuleType:
        self.assertTrue(BUILDER.exists(), f"missing module: {BUILDER}")
        scripts_dir = str(BUILDER.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec = importlib.util.spec_from_file_location(
            "build_lammps_examples_index", BUILDER
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(spec.name, None)
            raise
        return module


class TestExamplesIndexExtraction(BuilderTestCase):
    def test_extract_crack_commands_and_styles(self):
        b = self.load_builder()
        text = (FIXTURE / "crack" / "in.crack").read_text(encoding="utf-8")
        commands, styles = b.extract_commands_styles(text)
        self.assertIn("fix", commands)
        self.assertIn("pair_style", commands)
        self.assertEqual(styles["pair_style"], ("lj/cut",))
        self.assertEqual(styles["fix"], ("nve",))
        self.assertEqual(styles["atom_style"], ("atomic",))

    def test_extract_handles_continuation_and_comments(self):
        b = self.load_builder()
        text = "units lj &\n  # comment\n  real\natom_style atomic\nrun 10\n"
        commands, styles = b.extract_commands_styles(text)
        self.assertEqual(commands, ("atom_style", "run", "units"))
        self.assertEqual(styles["atom_style"], ("atomic",))

    def test_id_derivation_is_stable_and_lowercased(self):
        b = self.load_builder()
        self.assertEqual(
            b.derive_entry_id("crack/in.crack"),
            "lammps_examples_crack_in_crack",
        )
        self.assertEqual(
            b.derive_entry_id("PACKAGES/electrode/in.conp"),
            "lammps_examples_packages_electrode_in_conp",
        )

    def test_packages_and_tags_for_electrode_fixture(self):
        b = self.load_builder()
        text = (FIXTURE / "PACKAGES" / "electrode" / "in.conp").read_text(
            encoding="utf-8"
        )
        commands, styles = b.extract_commands_styles(text)
        self.assertEqual(b.derive_packages(styles), ("ELECTRODE",))
        tags = b.derive_tags("PACKAGES/electrode/in.conp", commands, styles)
        self.assertIn("conp", tags)
        self.assertIn("electrode", tags)


class TestExamplesIndexBuildCli(unittest.TestCase):
    def test_build_from_fixture_writes_valid_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_build(Path(tmp))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], 1)
            self.assertEqual(index["code"], "lammps")
            self.assertEqual(index["kind"], "official_examples_index")
            self.assertEqual(index["generated_from"]["commit"], COMMIT)
            self.assertEqual(index["generated_from"]["release"], None)
            ids = [e["id"] for e in index["entries"]]
            self.assertEqual(ids, sorted(ids))
            self.assertIn("lammps_examples_crack_in_crack", ids)
            self.assertIn("lammps_examples_packages_electrode_in_conp", ids)
            crack = next(e for e in index["entries"]
                         if e["id"] == "lammps_examples_crack_in_crack")
            self.assertTrue(crack["sha256"].startswith("sha256:"))
            self.assertEqual(crack["upstream_path"], "examples/crack/in.crack")
            self.assertEqual(crack["canonical_source_url"],
                             "https://github.com/lammps/lammps/blob/"
                             "abc123def456789012345678901234567890abcd/"
                             "examples/crack/in.crack")
            self.assertEqual(crack["local_example"], None)
            self.assertEqual(crack["packages"], [])
            expected = "sha256:" + hashlib.sha256(
                (FIXTURE / "crack" / "in.crack").read_bytes()
            ).hexdigest()
            self.assertEqual(crack["sha256"], expected)

    def test_local_map_populates_local_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "examples" / "fake_local").mkdir(parents=True)
            map_path = root / "local_map.json"
            map_path.write_text(json.dumps({"melt/in.melt": "examples/fake_local"}),
                                encoding="utf-8")
            proc = run_build(root, skill_root=root,
                             extra=("--local-map", str(map_path)))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            index = json.loads((root / "index.json").read_text(encoding="utf-8"))
            melt = next(e for e in index["entries"]
                        if e["id"] == "lammps_examples_melt_in_melt")
            self.assertEqual(melt["local_example"], "examples/fake_local")


class TestExamplesIndexDeterminism(unittest.TestCase):
    def test_rebuild_is_byte_identical(self):
        outputs = []
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(2):
                out = Path(tmp) / f"index_{i}.json"
                proc = subprocess.run(
                    [sys.executable, str(BUILDER), "build",
                     "--source-root", str(FIXTURE),
                     "--repository", "https://github.com/lammps/lammps",
                     "--commit", COMMIT,
                     "--retrieval-date", "2026-08-09",
                     "--skill-root", str(ROOT),
                     "--output", str(out)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                outputs.append(out.read_bytes())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
