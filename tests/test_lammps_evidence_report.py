#!/usr/bin/env python3
"""Contract tests for deterministic L0-L5 evidence reports."""

import dataclasses
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final


ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_SCRIPT: Final = ROOT / "scripts" / "lammps_evidence.py"
MODULE_NAME: Final = "lammps_evidence_report_test"
CANONICAL_MODULES: Final = (
    "lammps_evidence",
    "lammps_evidence_models",
    "lammps_evidence_report",
)
REPORT_BUILDERS: Final = (
    "build_phase_a_report",
    "report_json",
    "report_markdown",
)


def load_evidence() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(MODULE_NAME, EVIDENCE_SCRIPT)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(EVIDENCE_SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    previous = sys.modules.get(MODULE_NAME)
    sys.modules[MODULE_NAME] = module
    try:
        module_spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous
    return module


class TestValidationReport(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = {name: sys.modules.get(name) for name in CANONICAL_MODULES}
        for name in CANONICAL_MODULES:
            sys.modules.pop(name, None)
        self.addCleanup(self.restore_modules)
        self.evidence = load_evidence()
        for attribute in REPORT_BUILDERS:
            self.assertTrue(hasattr(self.evidence, attribute), attribute)

    def restore_modules(self) -> None:
        for name, module in self.previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def level(self, name: str, status: str):
        evidence = self.evidence
        return evidence.LevelEvidence(evidence.LevelName(name), evidence.LevelStatus(status))

    def passing_phase_a_report(self):
        evidence = self.evidence
        return evidence.build_phase_a_report(
            "generation_spec.json",
            self.level("L0", "PASS"),
            self.level("L1", "PASS"),
            (),
        )

    def test_passed_phase_a_target_stops_at_l1(self) -> None:
        evidence = self.evidence

        report = self.passing_phase_a_report()

        self.assertEqual(
            tuple(field.name for field in dataclasses.fields(evidence.ValidationReport)),
            (
                "spec_file",
                "manifest_file",
                "target_level",
                "target_satisfied",
                "highest_level",
                "levels",
                "unresolved",
            ),
        )
        self.assertEqual(report.highest_level, evidence.HighestLevel.L1_STATIC_PASS)
        self.assertTrue(report.target_satisfied)
        self.assertEqual(
            tuple(level.status for level in report.levels[2:]),
            (evidence.LevelStatus.NOT_EVALUATED,) * 4,
        )

    def test_incomplete_l0_and_blocked_l1_satisfy_no_level(self) -> None:
        evidence = self.evidence

        report = evidence.build_phase_a_report(
            "generation_spec.json",
            self.level("L0", "INCOMPLETE"),
            self.level("L1", "BLOCKED"),
            (),
        )

        self.assertEqual(report.highest_level, evidence.HighestLevel.NONE)
        self.assertFalse(report.target_satisfied)

    def test_unresolved_l4_changes_only_l4_and_preserves_key_order(self) -> None:
        evidence = self.evidence
        unresolved = (
            evidence.UnresolvedItem("first|key", evidence.LevelName.L4, "first"),
            evidence.UnresolvedItem("second.key", evidence.LevelName.L4, "second"),
        )

        report = evidence.build_phase_a_report(
            "generation_spec.json",
            self.level("L0", "PASS"),
            self.level("L1", "PASS"),
            unresolved,
        )

        statuses = {level.level: level.status for level in report.levels}
        self.assertEqual(statuses[evidence.LevelName.L4], evidence.LevelStatus.INCOMPLETE)
        self.assertEqual(report.levels[4].missing, ("first|key", "second.key"))
        self.assertEqual(
            tuple(statuses[evidence.LevelName(name)] for name in ("L2", "L3", "L5")),
            (evidence.LevelStatus.NOT_EVALUATED,) * 3,
        )

    def test_json_is_canonical_repeatable_and_newline_terminated(self) -> None:
        evidence = self.evidence
        report = self.passing_phase_a_report()

        first = evidence.report_json(report)
        second = evidence.report_json(report)
        payload = json.loads(first)

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))
        self.assertEqual(
            tuple(payload),
            tuple(sorted(payload)),
        )
        self.assertEqual(tuple(payload["levels"]), tuple(sorted(payload["levels"])))

    def test_markdown_has_six_ordered_level_rows_and_enum_tokens(self) -> None:
        evidence = self.evidence
        unresolved = (
            evidence.UnresolvedItem("runtime|version", evidence.LevelName.L4, "need|build"),
        )
        report = evidence.build_phase_a_report(
            "generation_spec.json",
            self.level("L0", "PASS"),
            self.level("L1", "PASS"),
            unresolved,
        )

        markdown = evidence.report_markdown(report)
        lines = markdown.splitlines()
        header = "| Level | Name | Status | Evidence | Missing |"
        header_index = lines.index(header)
        level_rows = lines[header_index + 2 : header_index + 8]
        parsed_rows = [tuple(cell.strip() for cell in row.strip("|").split("|")) for row in level_rows]

        self.assertEqual(header.strip("| "), "Level | Name | Status | Evidence | Missing")
        self.assertEqual(len(level_rows), 6)
        self.assertEqual(tuple(row[0] for row in parsed_rows), tuple(f"L{i}" for i in range(6)))
        self.assertEqual(parsed_rows[4][2], "INCOMPLETE")
        self.assertIn("Highest level: `L1_STATIC_PASS`", lines)
        self.assertIn("Target level: `L1_STATIC_PASS`", lines)
        self.assertIn("Target satisfied: `true`", lines)
        self.assertIn(r"runtime\|version", markdown)
        self.assertIn(r"need\|build", markdown)
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))


class TestValidationReportIsolation(unittest.TestCase):
    def test_fixture_restores_canonical_module_sentinels(self) -> None:
        originals = {name: sys.modules.get(name) for name in CANONICAL_MODULES}
        sentinels = {name: ModuleType(f"sentinel_{name}") for name in CANONICAL_MODULES}
        sys.modules.update(sentinels)
        case = TestValidationReport("test_passed_phase_a_target_stops_at_l1")
        try:
            try:
                case.setUp()
            except ImportError as error:
                self.fail(f"fixture did not remove canonical sentinels: {error}")
            for name, sentinel in sentinels.items():
                self.assertIsNot(sys.modules.get(name), sentinel)
            case.doCleanups()
            for name, sentinel in sentinels.items():
                self.assertIs(sys.modules.get(name), sentinel)
        finally:
            case.doCleanups()
            for name, module in originals.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
