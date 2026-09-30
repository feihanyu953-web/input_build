#!/usr/bin/env python3
"""Contract tests for mapping static validator output to L1 evidence."""

import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Final
from unittest.mock import patch


ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_SCRIPT: Final = ROOT / "scripts" / "lammps_evidence.py"
MODULE_NAME: Final = "lammps_evidence_l1"


def load_evidence() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        EVIDENCE_SCRIPT,
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError(EVIDENCE_SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    previous = (sys.modules[module_spec.name],) if module_spec.name in sys.modules else ()
    sys.modules[module_spec.name] = module
    try:
        module_spec.loader.exec_module(module)
    finally:
        if previous:
            sys.modules[module_spec.name] = previous[0]
        else:
            sys.modules.pop(module_spec.name, None)
    return module


class TestEvidenceLoaderIsolation(unittest.TestCase):
    @staticmethod
    def restore_module(previous: ModuleType | None) -> None:
        if previous is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous

    def setUp(self) -> None:
        previous = sys.modules.get(MODULE_NAME)
        self.addCleanup(self.restore_module, previous)
        self.sentinel = ModuleType("sentinel")
        sys.modules[MODULE_NAME] = self.sentinel

    def test_successful_load_restores_previous_fixed_name_module(self) -> None:
        loaded = load_evidence()

        self.assertIsNot(loaded, self.sentinel)
        self.assertIs(sys.modules[MODULE_NAME], self.sentinel)

    def test_failed_exec_restores_previous_fixed_name_module(self) -> None:
        with (
            patch.object(
                SourceFileLoader,
                "exec_module",
                side_effect=RuntimeError("simulated exec failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "simulated exec failure"),
        ):
            load_evidence()

        self.assertIs(sys.modules[MODULE_NAME], self.sentinel)


class TestStaticLevelFromValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = load_evidence()

    def test_l1_is_blocked_and_validator_data_ignored_when_l0_is_incomplete(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(
            level=evidence.LevelName.L0,
            status=evidence.LevelStatus.INCOMPLETE,
        )
        finding = evidence.FindingRecord(level="WARN", code="IGNORED", message="ignored")
        unresolved = evidence.UnresolvedItem(
            key="ignored.key",
            blocks_level=evidence.LevelName.L1,
            reason="ignored",
        )

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(
            l0,
            {"overall": "UNKNOWN"},
            (finding,),
            (unresolved,),
        )

        self.assertEqual(result.status, evidence.LevelStatus.BLOCKED)
        self.assertEqual(result.evidence, ())
        self.assertEqual(result.findings, ())
        self.assertEqual(result.warnings, ())
        self.assertEqual(result.missing, ())

    def test_l1_passes_and_preserves_warning_findings(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)
        findings = (
            evidence.FindingRecord(level="WARN", code="FIRST_WARN", message="first"),
            evidence.FindingRecord(level="INFO", code="INFO_ONLY", message="info"),
            evidence.FindingRecord(level="WARN", code="SECOND_WARN", message="second"),
        )

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(
            l0,
            {
                "overall": "STATIC_PASS",
                "syntax": "PASS",
                "combination": "PASS_WITH_WARNINGS",
                "physics": "NOT_EVALUATED",
            },
            findings,
            (),
        )

        self.assertEqual(result.status, evidence.LevelStatus.PASS)
        self.assertEqual(result.evidence, ("static_validation.json",))
        self.assertEqual(result.warnings, ("FIRST_WARN", "SECOND_WARN"))
        self.assertEqual(result.findings, findings)

    def test_l1_fails_when_validator_overall_fails(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(l0, {"overall": "FAIL"}, (), ())

        self.assertEqual(result.status, evidence.LevelStatus.FAIL)
        self.assertEqual(result.evidence, ("static_validation.json",))

    def test_l1_is_incomplete_when_validator_overall_is_incomplete(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(
            l0,
            {"overall": "INCOMPLETE"},
            (),
            (),
        )

        self.assertEqual(result.status, evidence.LevelStatus.INCOMPLETE)
        self.assertEqual(result.evidence, ("static_validation.json",))

    def test_l1_is_incomplete_with_declared_missing_keys(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)
        unresolved = (
            evidence.UnresolvedItem("first.key", evidence.LevelName.L1, "first"),
            evidence.UnresolvedItem("later.key", evidence.LevelName.L2, "later"),
            evidence.UnresolvedItem("second.key", evidence.LevelName.L1, "second"),
        )

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(
            l0,
            {"overall": "STATIC_PASS"},
            (),
            unresolved,
        )

        self.assertEqual(result.status, evidence.LevelStatus.INCOMPLETE)
        self.assertEqual(result.missing, ("first.key", "second.key"))

    def test_l1_fails_when_validator_tiers_are_missing(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(l0, None, (), ())

        self.assertEqual(result.status, evidence.LevelStatus.FAIL)
        self.assertEqual(result.evidence, ("static_validation.json",))

    def test_l1_fails_with_synthetic_finding_for_unknown_overall(self) -> None:
        evidence = self.evidence
        l0 = evidence.LevelEvidence(evidence.LevelName.L0, evidence.LevelStatus.PASS)
        original = evidence.FindingRecord(level="WARN", code="ORIGINAL", message="original")

        self.assertTrue(hasattr(evidence, "static_level_from_validator"))
        result = evidence.static_level_from_validator(
            l0,
            {"overall": "SURPRISE"},
            (original,),
            (),
        )

        self.assertEqual(result.status, evidence.LevelStatus.FAIL)
        self.assertEqual(result.findings[0], original)
        self.assertEqual(result.findings[1].level, "ERROR")
        self.assertEqual(result.findings[1].code, "STATIC_STATUS_UNKNOWN")
        self.assertIn("SURPRISE", result.findings[1].message)


if __name__ == "__main__":
    unittest.main()
