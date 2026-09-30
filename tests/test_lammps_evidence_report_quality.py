#!/usr/bin/env python3
"""Import-identity and hostile Markdown tests for evidence reports."""

import importlib
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final
from unittest.mock import patch


ROOT: Final = Path(__file__).resolve().parent.parent
SCRIPTS: Final = ROOT / "scripts"
EVIDENCE_SCRIPT: Final = SCRIPTS / "lammps_evidence.py"
REPORT_SCRIPT: Final = SCRIPTS / "lammps_evidence_report.py"
CUSTOM_NAME: Final = "lammps_evidence_quality_test"
CANONICAL_MODULES: Final = (
    "lammps_evidence",
    "lammps_evidence_models",
    "lammps_evidence_report",
)
REPORT_API: Final = (
    "ValidationReport",
    "build_phase_a_report",
    "report_json",
    "report_markdown",
)


def load_path(name: str, path: Path) -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(module_spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        module_spec.loader.exec_module(module)
    finally:
        if name == CUSTOM_NAME:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def parse_markdown_row(row: str) -> tuple[str, ...]:
    separators: list[int] = []
    for index, character in enumerate(row):
        if character != "|":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and row[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            separators.append(index)
    return tuple(
        row[start + 1 : stop].strip()
        for start, stop in zip(separators[:-1], separators[1:], strict=True)
    )


class TestCanonicalReportImports(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = {name: sys.modules.get(name) for name in CANONICAL_MODULES}
        for name in CANONICAL_MODULES:
            sys.modules.pop(name, None)
        self.addCleanup(self.restore_modules)

    def restore_modules(self) -> None:
        for name, module in self.previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def assert_same_report_api(self, evidence: ModuleType, report: ModuleType) -> None:
        for name in REPORT_API:
            with self.subTest(name=name):
                self.assertIs(getattr(evidence, name), getattr(report, name))

    def test_custom_evidence_then_direct_report_share_report_api_identity(self) -> None:
        before = tuple(sys.path)

        evidence = load_path(CUSTOM_NAME, EVIDENCE_SCRIPT)
        try:
            report = importlib.import_module("lammps_evidence_report")
        except ModuleNotFoundError as error:
            self.fail(f"direct report import failed after facade load: {error}")

        self.assert_same_report_api(evidence, report)
        self.assertEqual(tuple(sys.path), before)

    def test_direct_report_then_custom_evidence_share_report_api_identity(self) -> None:
        before = tuple(sys.path)
        try:
            report = load_path("lammps_evidence_report", REPORT_SCRIPT)
        except ModuleNotFoundError as error:
            self.fail(f"direct report import failed before facade load: {error}")

        evidence = load_path(CUSTOM_NAME, EVIDENCE_SCRIPT)

        self.assert_same_report_api(evidence, report)
        self.assertEqual(tuple(sys.path), before)

    def test_loader_missing_spec_raises_import_error_and_rolls_back(self) -> None:
        sentinel = ModuleType("previous_lammps_evidence")
        sys.modules["lammps_evidence"] = sentinel
        real_spec_from_file = importlib.util.spec_from_file_location

        def missing_report_spec(name: str, location: str | Path):
            if name == "lammps_evidence_report":
                return None
            return real_spec_from_file(name, location)

        module_spec = real_spec_from_file(CUSTOM_NAME, EVIDENCE_SCRIPT)
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[CUSTOM_NAME] = module
        self.addCleanup(sys.modules.pop, CUSTOM_NAME, None)

        with (
            patch.object(
                importlib.util,
                "spec_from_file_location",
                side_effect=missing_report_spec,
            ),
            self.assertRaises(ImportError),
        ):
            module_spec.loader.exec_module(module)

        self.assertIs(sys.modules["lammps_evidence"], sentinel)
        self.assertNotIn("lammps_evidence_models", sys.modules)
        self.assertNotIn("lammps_evidence_report", sys.modules)


class TestHostileMarkdownCells(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = {name: sys.modules.get(name) for name in CANONICAL_MODULES}
        for name in CANONICAL_MODULES:
            sys.modules.pop(name, None)
        self.addCleanup(self.restore_modules)
        self.evidence = load_path(CUSTOM_NAME, EVIDENCE_SCRIPT)

    def restore_modules(self) -> None:
        for name, module in self.previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_control_characters_do_not_add_table_rows_or_columns(self) -> None:
        evidence = self.evidence
        hostile = "slash\\pipe|cr\rlf\ncrlf\r\nend"
        l0 = evidence.LevelEvidence(
            evidence.LevelName.L0,
            evidence.LevelStatus.PASS,
            evidence=(hostile,),
            missing=(hostile,),
        )
        l1 = evidence.LevelEvidence(evidence.LevelName.L1, evidence.LevelStatus.PASS)
        unresolved = (
            evidence.UnresolvedItem(hostile, evidence.LevelName.L4, hostile),
        )
        report = evidence.build_phase_a_report("generation_spec.json", l0, l1, unresolved)

        markdown = evidence.report_markdown(report)
        lines = markdown.splitlines()
        level_header = lines.index("| Level | Name | Status | Evidence | Missing |")
        unresolved_header = lines.index("| Key | Blocks level | Reason |")
        level_rows = lines[level_header + 2 : level_header + 8]
        unresolved_rows = lines[unresolved_header + 2 :]

        self.assertEqual(len(level_rows), 6)
        self.assertEqual(len(unresolved_rows), 1)
        self.assertTrue(all(len(parse_markdown_row(row)) == 5 for row in level_rows))
        self.assertTrue(all(len(parse_markdown_row(row)) == 3 for row in unresolved_rows))
        self.assertEqual(markdown.count("<br>"), 15)
        self.assertIn(r"slash\\pipe\|cr<br>lf<br>crlf<br>end", markdown)
        self.assertTrue(markdown.endswith("\n"))
        self.assertFalse(markdown.endswith("\n\n"))


class TestHostileMarkdownCellsIsolation(unittest.TestCase):
    def test_fixture_restores_canonical_module_sentinels(self) -> None:
        originals = {name: sys.modules.get(name) for name in CANONICAL_MODULES}
        sentinels = {name: ModuleType(f"sentinel_{name}") for name in CANONICAL_MODULES}
        sys.modules.update(sentinels)
        case = TestHostileMarkdownCells(
            "test_control_characters_do_not_add_table_rows_or_columns"
        )
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
