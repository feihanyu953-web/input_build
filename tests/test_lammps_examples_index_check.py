#!/usr/bin/env python3
"""Offline check rejections and source-mutation guards for the LAMMPS
official examples index builder."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lammps_examples_index_support import (
    BUILDER,
    COMMIT,
    FIXTURE,
    REPOSITORY,
    ROOT,
    run_build,
)


class TestExamplesIndexRejections(unittest.TestCase):
    def build_valid(self, tmp: Path) -> dict:
        proc = run_build(tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads((tmp / "index.json").read_text(encoding="utf-8"))

    def run_check(self, index: dict, tmp: Path):
        path = tmp / "mutated.json"
        path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(BUILDER), "check", "--index", str(path),
             "--skill-root", str(ROOT)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def assert_rejected(self, mutate, code: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = self.build_valid(root)
            mutate(index)
            proc = self.run_check(index, root)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn(code, proc.stderr)

    def test_local_example_escape_is_rejected(self):
        def mutate(index):
            index["entries"][0]["local_example"] = "../../etc"
        self.assert_rejected(mutate, "INDEX_LOCAL_EXAMPLE_INVALID")

    def test_unpinned_generated_from_is_rejected(self):
        def mutate(index):
            index["generated_from"]["commit"] = None
            index["generated_from"]["release"] = None
        self.assert_rejected(mutate, "INDEX_UNPINNED")

    def test_unsupported_repository_is_rejected(self):
        def mutate(index):
            index["generated_from"]["repository"] = "https://example.com/lammps"
        self.assert_rejected(mutate, "INDEX_REPO_UNSUPPORTED")

    def test_duplicate_entry_id_is_rejected(self):
        def mutate(index):
            index["entries"].insert(1, dict(index["entries"][0]))
        self.assert_rejected(mutate, "INDEX_DUPLICATE_ID")

    def test_unsorted_entry_ids_are_rejected(self):
        def mutate(index):
            index["entries"][0], index["entries"][1] = (
                index["entries"][1], index["entries"][0])
        self.assert_rejected(mutate, "INDEX_NOT_SORTED")

    def test_uppercase_sha256_is_rejected(self):
        def mutate(index):
            index["entries"][0]["sha256"] = index["entries"][0]["sha256"].upper()
        self.assert_rejected(mutate, "INDEX_HASH_MALFORMED")

    def test_foreign_canonical_url_is_rejected(self):
        def mutate(index):
            index["entries"][0]["canonical_source_url"] = "https://example.com/x"
        self.assert_rejected(mutate, "INDEX_URL_MALFORMED")

    def test_path_traversal_is_rejected(self):
        def mutate(index):
            index["entries"][0]["upstream_path"] = "../escape/in.x"
        self.assert_rejected(mutate, "INDEX_PATH_TRAVERSAL")

    def test_unsorted_commands_are_rejected(self):
        def mutate(index):
            index["entries"][0]["commands"] = ["zeta", "alpha"]
        self.assert_rejected(mutate, "INDEX_LIST_NOT_SORTED")

    def test_entry_pin_mismatch_is_rejected(self):
        def mutate(index):
            index["entries"][0]["upstream_commit"] = (
                "dddddddddddddddddddddddddddddddddddddddd")
        self.assert_rejected(mutate, "INDEX_ENTRY_PIN_MISMATCH")

    def test_entry_repo_mismatch_is_rejected(self):
        def mutate(index):
            index["entries"][0]["upstream_repository"] = "https://example.com/other"
        self.assert_rejected(mutate, "INDEX_REPO_MISMATCH")


class TestExamplesIndexSourceMutation(unittest.TestCase):
    def copy_fixture(self, tmp: Path) -> Path:
        tree = tmp / "source"
        shutil.copytree(FIXTURE, tree)
        return tree

    def build_tree(self, tree: Path, output: Path):
        return subprocess.run(
            [sys.executable, str(BUILDER), "build",
             "--source-root", str(tree),
             "--repository", REPOSITORY,
             "--commit", COMMIT,
             "--retrieval-date", "2026-08-09",
             "--skill-root", str(ROOT),
             "--output", str(output)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def test_build_rejects_colliding_derived_ids(self):
        # A second file whose name normalizes to the same derived id as
        # crack/in.crack must make the build fail with INDEX_DUPLICATE_ID.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self.copy_fixture(root)
            shutil.copyfile(tree / "crack" / "in.crack",
                            tree / "crack" / "in..crack")
            output = root / "index.json"
            proc = self.build_tree(tree, output)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("INDEX_DUPLICATE_ID", proc.stderr)
            self.assertFalse(output.exists())

    def test_build_reflects_source_without_guessing(self):
        # Removing a command from the source must remove it from the index;
        # the builder never completes or guesses missing commands.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self.copy_fixture(root)
            crack = tree / "crack" / "in.crack"
            text = crack.read_text(encoding="utf-8")
            crack.write_text("\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("pair_style")
            ) + "\n", encoding="utf-8")
            output = root / "index.json"
            proc = self.build_tree(tree, output)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            index = json.loads(output.read_text(encoding="utf-8"))
            crack_entry = next(e for e in index["entries"]
                               if e["id"] == "lammps_examples_crack_in_crack")
            self.assertNotIn("pair_style", crack_entry["commands"])
            self.assertNotIn("pair_style", crack_entry["styles"])


if __name__ == "__main__":
    unittest.main()
