#!/usr/bin/env python3
"""Regression tests for scripts/smoke/run_smoke.py."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "smoke" / "run_smoke.py"
CASES = ROOT / "scripts" / "smoke" / "cases.yaml"


def _load():
    spec = importlib.util.spec_from_file_location("run_smoke", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke = _load()


def minimal_case(**overrides):
    case = {
        "name": "demo",
        "code": "vasp",
        "files": {"INCAR": "ENCUT = 400\n"},
        "run": "{{vasp_std}}",
        "asserts": [{"type": "file_exists", "path": "OUTCAR"}],
    }
    case.update(overrides)
    return case


class TestCaseSchema(unittest.TestCase):
    def test_asserts_are_required(self):
        errs = smoke.validate_case(minimal_case(asserts=[]))
        self.assertTrue(any("asserts" in e for e in errs), errs)

    def test_assert_type_required_fields(self):
        cases = [
            ({"type": "file_exists"}, "path"),
            ({"type": "grep", "path": "OUTCAR"}, "pattern"),
            ({"type": "not_grep", "pattern": "ERROR"}, "path"),
            ({"type": "regex_number", "path": "OUTCAR"}, "pattern"),
            ({"type": "xyz_angle", "path": "traj.xyz", "atoms": [1, 2]}, "atoms"),
        ]
        for assertion, expected in cases:
            with self.subTest(assertion=assertion):
                errs = smoke.validate_case(minimal_case(asserts=[assertion]))
                self.assertTrue(any(expected in e for e in errs), errs)

    def test_regex_number_schema_checks_capture_and_bounds(self):
        bad = [
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=\d+"},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "occurrence": "middle"},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "divide_by": 0},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "divide_by": "nan"},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "abs_min": -1},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "abs_min": "inf"},
            {"type": "regex_number", "path": "OUTCAR", "pattern": r"value=(\d+)",
             "min": 2, "max": 1},
        ]
        for assertion in bad:
            with self.subTest(assertion=assertion):
                self.assertTrue(smoke.validate_case(minimal_case(asserts=[assertion])))

    def test_context_closure_reports_missing_variables(self):
        errs = smoke.validate_case(minimal_case(), ctx={})
        self.assertTrue(any("vasp_std" in e for e in errs), errs)

    def test_context_closure_checks_file_contents(self):
        case = minimal_case(files={"INCAR": "MODEL = {{model_path}}\n"}, run="true")
        errs = smoke.validate_case(case, ctx={})
        self.assertTrue(any("model_path" in e for e in errs), errs)

    def test_context_closure_checks_implicit_potcar_root(self):
        case = minimal_case(potcar=["H"])
        errs = smoke.validate_case(case, ctx={"vasp_std": "vasp_std"})
        self.assertTrue(any("vasp_potcars" in e for e in errs), errs)


class TestAbsMinimum(unittest.TestCase):
    def test_regex_number_abs_min_rejects_zero_and_accepts_nonzero_last_value(self):
        case = minimal_case(asserts=[{
            "type": "regex_number",
            "path": "OUTCAR",
            "pattern": r"Ediel_sol\s*=\s*([-+0-9.Ee]+)",
            "occurrence": "last",
            "abs_min": 1.0e-8,
        }])
        with tempfile.TemporaryDirectory() as tmp:
            outcar = Path(tmp) / "OUTCAR"
            outcar.write_text("Ediel_sol = 1.0\nEdiel_sol = 0.0\n", encoding="utf-8")
            failures = smoke.check_asserts(case, tmp)
            self.assertTrue(any("绝对值" in x or "abs" in x.lower() for x in failures),
                            failures)
            outcar.write_text("Ediel_sol = 0.0\nEdiel_sol = -0.25\n", encoding="utf-8")
            self.assertEqual(smoke.check_asserts(case, tmp), [])

    def test_regex_number_rejects_non_finite_captured_value(self):
        case = minimal_case(asserts=[{
            "type": "regex_number", "path": "OUTCAR",
            "pattern": r"value=(\S+)", "min": 0, "max": 10,
        }])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "OUTCAR").write_text("value=nan\n", encoding="utf-8")
            failures = smoke.check_asserts(case, tmp)
        self.assertTrue(any("有限" in x or "finite" in x.lower() for x in failures),
                        failures)


class TestCliList(unittest.TestCase):
    def _write_json(self, directory, name, obj):
        path = Path(directory) / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def test_list_uses_selected_env_and_fails_cleanly_on_missing_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = self._write_json(tmp, "env.json", {
                "default": "local",
                "environments": {"local": {"codes": {}, "data": {}}},
            })
            cases_file = self._write_json(tmp, "cases.json", [minimal_case()])
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--list",
                 "--env-file", str(env_file), "--cases-file", str(cases_file)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, smoke.EXIT_FAIL, proc.stdout + proc.stderr)
        self.assertIn("vasp_std", proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)

    def test_list_survives_gbk_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = self._write_json(tmp, "env.json", {
                "default": "local",
                "environments": {"local": {"codes": {"vasp_std": "vasp"},
                                             "data": {}}},
            })
            cases_file = self._write_json(tmp, "cases.json", [minimal_case(
                description="中文 Å ✓")])
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "gbk"
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--list",
                 "--env-file", str(env_file), "--cases-file", str(cases_file)],
                capture_output=True, text=True, encoding="gbk", errors="replace", env=env)
        self.assertEqual(proc.returncode, smoke.EXIT_OK, proc.stdout + proc.stderr)
        self.assertIn("[OK]", proc.stdout)
        self.assertNotIn("UnicodeEncodeError", proc.stderr)


class TestShippedVaspsolAssertions(unittest.TestCase):
    def test_vaspsol_cases_require_nonzero_energy_and_xml_parameters(self):
        cases = smoke.load_structured(str(CASES))
        by_name = {case["name"]: case for case in cases}
        for name in ("vaspsol_h2", "vasp_efield_h2o"):
            with self.subTest(name=name):
                assertions = by_name[name]["asserts"]
                numeric = [a for a in assertions
                           if a.get("type") == "regex_number"
                           and "Ediel_sol" in a.get("pattern", "")]
                self.assertEqual(len(numeric), 1)
                self.assertEqual(float(numeric[0]["abs_min"]), 1.0e-8)
                xml_patterns = [a.get("pattern") for a in assertions
                                if a.get("type") == "grep"
                                and a.get("path") == "vasprun.xml"]
                self.assertTrue(any("LSOL" in p for p in xml_patterns), xml_patterns)
                self.assertTrue(any("EB_K" in p for p in xml_patterns), xml_patterns)


if __name__ == "__main__":
    unittest.main()
