#!/usr/bin/env python3
"""Contract tests for the LAMMPS explain mode (Phase I)."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "references" / "lammps_validation_rules.json"
EXPLAIN_SCRIPT = ROOT / "scripts" / "explain_lammps.py"

KNOWN_FINDING_CODES = frozenset({
    "LAMMPS_NO_UNITS",
    "LAMMPS_NO_ATOM_STYLE",
    "LAMMPS_NO_BOUNDARY",
    "LAMMPS_TIMESTEP_INVALID",
    "LAMMPS_NO_SYSTEM",
    "LAMMPS_NO_PAIR_STYLE",
    "LAMMPS_COEFF_BEFORE_STYLE",
    "LAMMPS_NO_RUN",
    "LAMMPS_NEB_NO_FIX",
    "LAMMPS_PLACEHOLDER_UNRESOLVED",
    "LAMMPS_VELOCITY_ZERO_TEMP",
    "LAMMPS_PAIR_COEFF_MISSING",
    "LAMMPS_EAM_PAIRCOEFF_ARGS",
    "LAMMPS_NVT_NVE_CONFLICT",
    "LAMMPS_NPT_NONPERIODIC_DIM",
    "LAMMPS_NO_SHAKE",
    "LAMMPS_TIMESTEP_HIGH",
    "LAMMPS_NO_VELOCITY",
    "LAMMPS_NO_DUMP",
    "LAMMPS_NO_THERMO",
    "LAMMPS_ELECTRODE_KSPACE",
    "LAMMPS_REAXC_REMOVED",
    "LAMMPS_MLFF_NO_MODEL",
    "LAMMPS_DATA_UNREADABLE",
})


class TestValidationRulesRegistry(unittest.TestCase):
    def test_registry_covers_all_known_finding_codes(self):
        self.assertTrue(RULES.exists(), f"missing registry: {RULES}")
        registry = json.loads(RULES.read_text(encoding="utf-8"))

        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual(registry["code"], "lammps")
        rules = registry["rules"]

        missing = KNOWN_FINDING_CODES - set(rules.keys())
        self.assertFalse(missing, f"registry missing finding codes: {sorted(missing)}")

        extra = set(rules.keys()) - KNOWN_FINDING_CODES
        self.assertFalse(extra, f"registry has unknown finding codes: {sorted(extra)}")

        for code, rule in rules.items():
            self.assertIn("rule_id", rule)
            self.assertIn(rule["severity"], {"ERROR", "WARN", "INFO"})
            self.assertEqual(rule["affected_evidence_level"], "L1")
            self.assertTrue(rule["severity_meaning"])
            self.assertTrue(rule["rationale"])
            self.assertTrue(rule["source_reference"])
            self.assertTrue(rule["trigger_condition"])


class ExplainTestBase(unittest.TestCase):
    """Shared loader helpers for explain mode tests."""

    def setUp(self):
        from explain_lammps_support import write_explain_case

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = write_explain_case(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def load_explain(self):
        self.assertTrue(EXPLAIN_SCRIPT.exists(), f"missing module: {EXPLAIN_SCRIPT}")
        spec = importlib.util.spec_from_file_location("explain_lammps", EXPLAIN_SCRIPT)
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

    def load_explain_with_evidence(self):
        explain = self.load_explain()
        evidence_script = ROOT / "scripts" / "lammps_evidence.py"
        if "lammps_evidence" not in sys.modules:
            ev_spec = importlib.util.spec_from_file_location(
                "lammps_evidence", evidence_script
            )
            ev_module = importlib.util.module_from_spec(ev_spec)
            sys.modules[ev_spec.name] = ev_module
            ev_spec.loader.exec_module(ev_module)
        return explain

    def build_report(self, explain, **overrides):
        paths = dict(self.paths)
        paths.update(overrides)
        return explain.build_explain_report(
            spec_path=paths.get("spec"),
            input_path=paths.get("input"),
            render_trace_path=paths.get("render_trace"),
            examples_index_path=paths.get("examples_index"),
            validation_report_path=paths.get("validation_report"),
            static_validation_path=paths.get("static_validation"),
        )


class TestExplainCompleteJoin(ExplainTestBase):
    def test_complete_join_produces_all_sections(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        self.assertEqual(report.status, "COMPLETE")
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(len(report.missing_inputs), 0)
        self.assertGreater(len(report.commands), 0)
        self.assertEqual(len(report.unexplained_findings), 0)
        self.assertIsNotNone(report.evidence)
        self.assertEqual(report.evidence.highest_level, "L1_STATIC_PASS")


class TestCommandProvenance(ExplainTestBase):
    def test_commands_are_ordered_by_index(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        indices = [cmd.index for cmd in report.commands]
        self.assertEqual(indices, sorted(indices))

    def test_fix_command_has_id_and_anchor(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        fix_cmd = next(cmd for cmd in report.commands if cmd.command == "fix")
        self.assertEqual(fix_cmd.assigned_id, 1)
        self.assertEqual(fix_cmd.id_type, "fix")
        self.assertEqual(fix_cmd.anchor, "after_pair_definition")
        self.assertIsNotNone(fix_cmd.ordering_rationale)

    def test_source_text_matches_span(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        units_cmd = report.commands[0]
        self.assertEqual(units_cmd.source_span, (1, 1))
        self.assertIn("units", units_cmd.source_text or "")

    def test_missing_render_trace_produces_empty_commands_and_partial(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, render_trace=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertEqual(report.exit_code, 1)
        self.assertIn("render_trace", report.missing_inputs)
        self.assertEqual(len(report.commands), 0)


class TestFindingExplanation(ExplainTestBase):
    def test_known_finding_gets_rule_rationale(self):
        explain = self.load_explain_with_evidence()
        sv = json.loads(self.paths["static_validation"].read_text(encoding="utf-8"))
        sv["findings"] = [
            {"level": "ERROR", "code": "LAMMPS_PAIR_COEFF_MISSING",
             "message": "pair_style present but no pair_coeff anywhere"},
        ]
        self.paths["static_validation"].write_text(
            json.dumps(sv, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.build_report(explain)
        self.assertEqual(len(report.findings), 1)
        finding = report.findings[0]
        self.assertTrue(finding.explained)
        self.assertIsNotNone(finding.rule)
        self.assertEqual(finding.rule.affected_evidence_level, "L1")
        self.assertEqual(len(report.unexplained_findings), 0)

    def test_unknown_finding_remains_visible_and_partial(self):
        explain = self.load_explain_with_evidence()
        sv = json.loads(self.paths["static_validation"].read_text(encoding="utf-8"))
        sv["findings"] = [
            {"level": "ERROR", "code": "LAMMPS_FUTURE_UNKNOWN_CODE",
             "message": "a finding code from a future validator version"},
        ]
        self.paths["static_validation"].write_text(
            json.dumps(sv, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.build_report(explain)
        self.assertEqual(report.status, "PARTIAL")
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(len(report.findings), 1)
        finding = report.findings[0]
        self.assertFalse(finding.explained)
        self.assertIsNone(finding.rule)
        self.assertIn("LAMMPS_FUTURE_UNKNOWN_CODE", report.unexplained_findings)

    def test_missing_static_validation_produces_empty_findings_and_partial(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, static_validation=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertIn("static_validation", report.missing_inputs)
        self.assertEqual(len(report.findings), 0)


class TestEvidenceReporting(ExplainTestBase):
    def test_evidence_levels_copied_not_recomputed(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        self.assertIsNotNone(report.evidence)
        self.assertEqual(report.evidence.highest_level, "L1_STATIC_PASS")
        self.assertEqual(report.evidence.target_satisfied, True)
        levels = {lv.level: lv for lv in report.evidence.levels}
        self.assertEqual(levels["L0"].status, "PASS")
        self.assertEqual(levels["L1"].status, "PASS")
        self.assertEqual(levels["L2"].status, "NOT_EVALUATED")

    def test_stop_reason_for_not_evaluated_l2(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        self.assertIn("L2 is NOT_EVALUATED", report.evidence.stop_reason)

    def test_stop_reason_for_l1_fail(self):
        explain = self.load_explain_with_evidence()
        vr = json.loads(self.paths["validation_report"].read_text(encoding="utf-8"))
        vr["highest_level"] = "NONE"
        vr["target_satisfied"] = False
        vr["levels"]["L0"]["status"] = "PASS"
        vr["levels"]["L1"]["status"] = "FAIL"
        self.paths["validation_report"].write_text(
            json.dumps(vr, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.build_report(explain)
        self.assertEqual(report.evidence.highest_level, "NONE")
        self.assertIn("L1 is FAIL", report.evidence.stop_reason)

    def test_missing_validation_report_produces_null_evidence_and_partial(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, validation_report=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertIn("validation_report", report.missing_inputs)
        self.assertIsNone(report.evidence)

    def test_evidence_levels_never_raised(self):
        explain = self.load_explain_with_evidence()
        vr = json.loads(self.paths["validation_report"].read_text(encoding="utf-8"))
        vr["highest_level"] = "NONE"
        vr["levels"]["L0"]["status"] = "INCOMPLETE"
        vr["levels"]["L1"]["status"] = "BLOCKED"
        self.paths["validation_report"].write_text(
            json.dumps(vr, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.build_report(explain)
        self.assertEqual(report.evidence.highest_level, "NONE")
        levels = {lv.level: lv for lv in report.evidence.levels}
        self.assertEqual(levels["L0"].status, "INCOMPLETE")
        self.assertEqual(levels["L1"].status, "BLOCKED")


class TestPartialReportSemantics(ExplainTestBase):
    def test_missing_examples_index_produces_partial(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, examples_index=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertEqual(report.exit_code, 1)
        self.assertIn("examples_index", report.missing_inputs)

    def test_missing_spec_produces_partial_and_empty_unresolved(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, spec=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertIn("spec", report.missing_inputs)
        self.assertEqual(len(report.unresolved), 0)

    def test_missing_input_produces_partial_and_null_source_text(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain, input=None)
        self.assertEqual(report.status, "PARTIAL")
        self.assertIn("input", report.missing_inputs)
        for cmd in report.commands:
            self.assertIsNone(cmd.source_text)

    def test_all_optional_missing_produces_partial_with_all_missing(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(
            explain,
            spec=None,
            input=None,
            render_trace=None,
            examples_index=None,
            validation_report=None,
            static_validation=None,
        )
        self.assertEqual(report.status, "PARTIAL")
        self.assertEqual(report.exit_code, 1)
        expected_missing = {
            "spec", "input", "render_trace",
            "examples_index", "validation_report", "static_validation",
        }
        self.assertEqual(set(report.missing_inputs), expected_missing)

    def test_complete_inputs_produce_complete_report(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        self.assertEqual(report.status, "COMPLETE")
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(len(report.missing_inputs), 0)

    def test_inputs_tuple_preserves_fixed_order(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        names = [name for name, _ in report.inputs]
        self.assertEqual(
            names,
            ["spec", "input", "render_trace",
             "examples_index", "validation_report", "static_validation"],
        )


class TestSerialization(ExplainTestBase):
    def test_json_bytes_are_deterministic(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        json1 = explain.report_json(report)
        json2 = explain.report_json(report)
        self.assertEqual(json1, json2)
        self.assertTrue(json1.endswith("\n"))

    def test_markdown_bytes_are_deterministic(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        md1 = explain.report_markdown(report)
        md2 = explain.report_markdown(report)
        self.assertEqual(md1, md2)
        self.assertTrue(md1.endswith("\n"))

    def test_markdown_contains_required_sections(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        md = explain.report_markdown(report)
        self.assertIn("# LAMMPS Input Explanation", md)
        self.assertIn("## Inputs", md)
        self.assertIn("## Missing inputs", md)
        self.assertIn("## Command provenance", md)
        self.assertIn("## ID allocations", md)
        self.assertIn("## Validator findings", md)
        self.assertIn("## Unexplained findings", md)
        self.assertIn("## Evidence levels", md)
        self.assertIn("## Unresolved assumptions", md)

    def test_markdown_status_and_exit_code_present(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        md = explain.report_markdown(report)
        self.assertIn("Status: `COMPLETE`", md)
        self.assertIn("Exit code: `0`", md)

    def test_json_has_fixed_top_level_keys(self):
        explain = self.load_explain_with_evidence()
        report = self.build_report(explain)
        data = json.loads(explain.report_json(report))
        expected_keys = {
            "schema_version", "code", "status", "exit_code", "exit_reason",
            "inputs", "missing_inputs", "commands", "id_allocations",
            "findings", "unexplained_findings", "evidence", "unresolved",
        }
        self.assertEqual(set(data.keys()), expected_keys)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["code"], "lammps")


class TestExplainCLI(ExplainTestBase):
    def setUp(self):
        super().setUp()
        self.output_dir = self.root / "output"

    def _run_cli(self, *extra_args):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "explain_lammps.py"),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _run_complete(self):
        return self._run_cli(
            "--spec", str(self.paths["spec"]),
            "--input", str(self.paths["input"]),
            "--render-trace", str(self.paths["render_trace"]),
            "--examples-index", str(self.paths["examples_index"]),
            "--validation-report", str(self.paths["validation_report"]),
            "--static-validation", str(self.paths["static_validation"]),
            "--output-dir", str(self.output_dir),
        )

    def test_complete_inputs_exit_zero(self):
        proc = self._run_complete()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.output_dir / "explain_report.json").exists())
        self.assertTrue((self.output_dir / "explain_report.md").exists())
        data = json.loads(
            (self.output_dir / "explain_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["status"], "COMPLETE")
        self.assertEqual(data["exit_code"], 0)

    def test_missing_optional_inputs_exit_one(self):
        proc = self._run_cli(
            "--spec", str(self.paths["spec"]),
            "--input", str(self.paths["input"]),
            "--output-dir", str(self.output_dir),
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue((self.output_dir / "explain_report.json").exists())
        self.assertTrue((self.output_dir / "explain_report.md").exists())
        data = json.loads(
            (self.output_dir / "explain_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["status"], "PARTIAL")
        self.assertEqual(data["exit_code"], 1)
        self.assertIn("render_trace", data["missing_inputs"])

    def test_missing_required_args_exit_two(self):
        proc = self._run_cli("--output-dir", str(self.output_dir))
        self.assertEqual(proc.returncode, 2)

    def test_readonly_no_input_files_modified(self):
        spec_before = self.paths["spec"].read_bytes()
        input_before = self.paths["input"].read_bytes()
        trace_before = self.paths["render_trace"].read_bytes()
        proc = self._run_complete()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.paths["spec"].read_bytes(), spec_before)
        self.assertEqual(self.paths["input"].read_bytes(), input_before)
        self.assertEqual(self.paths["render_trace"].read_bytes(), trace_before)

    def test_unknown_finding_exit_one(self):
        self.load_explain_with_evidence()
        sv = json.loads(self.paths["static_validation"].read_text(encoding="utf-8"))
        sv["findings"] = [
            {"level": "ERROR", "code": "LAMMPS_FUTURE_UNKNOWN_CODE",
             "message": "a finding code from a future validator version"},
        ]
        self.paths["static_validation"].write_text(
            json.dumps(sv, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        proc = self._run_complete()
        self.assertEqual(proc.returncode, 1, proc.stderr)
        data = json.loads(
            (self.output_dir / "explain_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["status"], "PARTIAL")
        self.assertIn("LAMMPS_FUTURE_UNKNOWN_CODE", data["unexplained_findings"])


if __name__ == "__main__":
    unittest.main()
