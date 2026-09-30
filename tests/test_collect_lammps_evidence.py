#!/usr/bin/env python3
"""Subprocess-level E2E tests for the Phase A collector CLI."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

import lammps_evidence_support as support

ROOT: Final = Path(__file__).resolve().parent.parent
COLLECTOR: Final = ROOT / "scripts" / "collect_lammps_evidence.py"


class TestCollectLammpsEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec_path = support.write_complete_case(self.root)

    def run_collector(self, output_dir: Path | None = None) -> subprocess.CompletedProcess:
        output = str(output_dir) if output_dir else None
        args = [sys.executable, str(COLLECTOR), "--spec", str(self.spec_path)]
        if output:
            args += ["--output-dir", output]
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def read_json(self, output_dir: Path, name: str) -> dict:
        return json.loads((output_dir / name).read_text(encoding="utf-8"))

    def test_success_writes_four_reports_and_exits_zero(self) -> None:
        output_dir = self.root / "validation"
        proc = self.run_collector(output_dir)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in (
            "generation_manifest.json",
            "static_validation.json",
            "validation_report.json",
            "validation_report.md",
        ):
            self.assertTrue((output_dir / name).exists(), f"missing: {name}")

        report = self.read_json(output_dir, "validation_report.json")
        self.assertTrue(report["target_satisfied"])
        self.assertEqual(report["highest_level"], "L1_STATIC_PASS")
        for level in ("L2", "L3", "L4", "L5"):
            self.assertNotEqual(report["levels"][level]["status"], "PASS")

        manifest = self.read_json(output_dir, "generation_manifest.json")
        input_entry = next(e for e in manifest["files"] if e["role"] == "input")
        data_entry = next(e for e in manifest["files"] if e["role"] == "data")
        self.assertTrue(input_entry["sha256"].startswith("sha256:"))
        self.assertTrue(data_entry["sha256"].startswith("sha256:"))
        tool_names = [t["name"] for t in manifest["tools"]]
        self.assertEqual(
            tool_names,
            ["generation_schema", "spec_parser", "evidence_model", "collector", "static_validator"],
        )
        for tool in manifest["tools"]:
            self.assertTrue(tool["sha256"].startswith("sha256:"))
        self.assertEqual(manifest["not_implemented"], ["renderer", "task_profiles"])

        sv = self.read_json(output_dir, "static_validation.json")
        self.assertIn("validation", sv)
        self.assertIn("findings", sv)

    def test_missing_data_file_exit1_l0_incomplete_l1_blocked(self) -> None:
        (self.root / "system.data").unlink()
        output_dir = self.root / "validation"
        proc = self.run_collector(output_dir)

        self.assertEqual(proc.returncode, 1, proc.stderr)
        for name in (
            "generation_manifest.json",
            "static_validation.json",
            "validation_report.json",
            "validation_report.md",
        ):
            self.assertTrue((output_dir / name).exists(), f"missing: {name}")

        report = self.read_json(output_dir, "validation_report.json")
        self.assertEqual(report["levels"]["L0"]["status"], "INCOMPLETE")
        self.assertEqual(report["levels"]["L1"]["status"], "BLOCKED")

    def test_hash_mismatch_exit1_l0_fail_l1_blocked(self) -> None:
        (self.root / "system.data").write_text("tampered\n", encoding="utf-8")
        output_dir = self.root / "validation"
        proc = self.run_collector(output_dir)

        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = self.read_json(output_dir, "validation_report.json")
        self.assertEqual(report["levels"]["L0"]["status"], "FAIL")
        self.assertEqual(report["levels"]["L1"]["status"], "BLOCKED")
        codes = {f["code"] for f in report["levels"]["L0"]["findings"]}
        self.assertIn("SPEC_HASH_MISMATCH", codes)

    def test_missing_pair_coeff_exit1_l0_pass_l1_fail(self) -> None:
        original = (self.root / "in.lammps").read_text(encoding="utf-8")
        (self.root / "in.lammps").write_text(
            original.replace("pair_coeff * * 0.0103 2.5\n", ""),
            encoding="utf-8",
        )
        output_dir = self.root / "validation"
        proc = self.run_collector(output_dir)

        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = self.read_json(output_dir, "validation_report.json")
        self.assertEqual(report["levels"]["L0"]["status"], "PASS")
        self.assertEqual(report["levels"]["L1"]["status"], "FAIL")

        sv = self.read_json(output_dir, "static_validation.json")
        codes = {f["code"] for f in sv["findings"]}
        self.assertIn("LAMMPS_PAIR_COEFF_MISSING", codes)


if __name__ == "__main__":
    unittest.main()
