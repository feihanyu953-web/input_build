#!/usr/bin/env python3
"""Canonical immutable models for LAMMPS generation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never


class LevelName(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class LevelStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    NOT_EVALUATED = "NOT_EVALUATED"
    BLOCKED = "BLOCKED"


class HighestLevel(StrEnum):
    NONE = "NONE"
    L0_SPEC_COMPLETE = "L0_SPEC_COMPLETE"
    L1_STATIC_PASS = "L1_STATIC_PASS"
    L2_BUILD_COMPATIBLE = "L2_BUILD_COMPATIBLE"
    L3_SMOKE_PASS = "L3_SMOKE_PASS"
    L4_TASK_READY = "L4_TASK_READY"
    L5_PRODUCTION_EVIDENCE = "L5_PRODUCTION_EVIDENCE"


LEVEL_ORDER: Final[tuple[LevelName, ...]] = tuple(LevelName)
LEVEL_TITLES: Final[Mapping[LevelName, str]] = {
    LevelName.L0: "SPEC_COMPLETE",
    LevelName.L1: "STATIC_PASS",
    LevelName.L2: "BUILD_COMPATIBLE",
    LevelName.L3: "SMOKE_PASS",
    LevelName.L4: "TASK_READY",
    LevelName.L5: "PRODUCTION_EVIDENCE",
}
HIGHEST_BY_LEVEL: Final[Mapping[LevelName, HighestLevel]] = {
    LevelName.L0: HighestLevel.L0_SPEC_COMPLETE,
    LevelName.L1: HighestLevel.L1_STATIC_PASS,
    LevelName.L2: HighestLevel.L2_BUILD_COMPATIBLE,
    LevelName.L3: HighestLevel.L3_SMOKE_PASS,
    LevelName.L4: HighestLevel.L4_TASK_READY,
    LevelName.L5: HighestLevel.L5_PRODUCTION_EVIDENCE,
}


@dataclass(frozen=True, slots=True)
class FindingRecord:
    level: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LevelEvidence:
    level: LevelName
    status: LevelStatus
    evidence: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    findings: tuple[FindingRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class UnresolvedItem:
    key: str
    blocks_level: LevelName
    reason: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    spec_file: str
    manifest_file: str
    target_level: HighestLevel
    target_satisfied: bool
    highest_level: HighestLevel
    levels: tuple[LevelEvidence, ...]
    unresolved: tuple[UnresolvedItem, ...]


def highest_contiguous_pass(
    statuses: Mapping[LevelName, LevelStatus],
) -> HighestLevel:
    highest = HighestLevel.NONE
    for level in LEVEL_ORDER:
        match statuses[level]:
            case LevelStatus.PASS:
                highest = HIGHEST_BY_LEVEL[level]
            case (
                LevelStatus.FAIL
                | LevelStatus.INCOMPLETE
                | LevelStatus.NOT_EVALUATED
                | LevelStatus.BLOCKED
            ):
                break
            case unreachable:
                assert_never(unreachable)
    return highest
