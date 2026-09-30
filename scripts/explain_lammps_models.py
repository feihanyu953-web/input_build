"""Frozen value objects for the LAMMPS explain mode (Phase I)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProvenanceExplanation:
    origin: str
    name: str
    section: str | None


@dataclass(frozen=True, slots=True)
class OfficialExampleRef:
    path: str
    lammps_version: str | None
    source_url: str | None
    resolved: bool


@dataclass(frozen=True, slots=True)
class CommandExplanation:
    index: int
    command: str
    args: tuple[str, ...]
    source_span: tuple[int, int] | None
    source_text: str | None
    provenance: ProvenanceExplanation | None
    official_example: OfficialExampleRef | None
    assigned_id: int | None
    id_type: str | None
    anchor: str | None
    ordering_rationale: str | None
    profile_contribution: str | None


@dataclass(frozen=True, slots=True)
class IdAllocation:
    id_type: str
    id: int
    command_index: int
    rationale: str


@dataclass(frozen=True, slots=True)
class RuleEntry:
    rule_id: str
    severity: str
    affected_evidence_level: str
    severity_meaning: str
    rationale: str
    source_reference: str
    trigger_condition: str


@dataclass(frozen=True, slots=True)
class FindingExplanation:
    code: str
    level: str
    message: str
    rule: RuleEntry | None
    explained: bool


@dataclass(frozen=True, slots=True)
class LevelSummary:
    level: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    highest_level: str
    target_level: str
    target_satisfied: bool
    stop_reason: str
    levels: tuple[LevelSummary, ...]


@dataclass(frozen=True, slots=True)
class UnresolvedAssumption:
    key: str
    blocks_level: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExplainReport:
    status: str
    exit_code: int
    exit_reason: str
    inputs: tuple[tuple[str, str | None], ...]
    missing_inputs: tuple[str, ...]
    commands: tuple[CommandExplanation, ...]
    id_allocations: tuple[IdAllocation, ...]
    findings: tuple[FindingExplanation, ...]
    unexplained_findings: tuple[str, ...]
    evidence: EvidenceSummary | None
    unresolved: tuple[UnresolvedAssumption, ...]
