#!/usr/bin/env python3
"""Immutable domain models for LAMMPS GenerationSpec assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeAlias

from lammps_evidence import LevelEvidence, UnresolvedItem

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
HASH_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
MODIFIERS: Final = frozenset(
    {
        "efield_lammps",
        "shake_lammps",
        "analysis_rdf_msd",
        "analysis_hbond",
        "ensemble_langevin",
        "temp_ramp",
        "dump_full",
        "wall_slab",
    }
)
SOURCES: Final = frozenset(
    {"user-provided", "user-confirmed", "detected", "generated", "ai-inferred"}
)


class LammpsUnits(StrEnum):
    METAL = "metal"
    REAL = "real"


class Ensemble(StrEnum):
    NVE = "nve"
    NVT = "nvt"
    NVE_LANGEVIN = "nve_langevin"


@dataclass(frozen=True, slots=True)
class MinimizeStage:
    stage_id: str
    style: str
    etol: float
    ftol: float
    maxiter: int
    maxeval: int


@dataclass(frozen=True, slots=True)
class MdStage:
    stage_id: str
    ensemble: Ensemble
    steps: int
    temperature_start_K: float | None
    temperature_stop_K: float | None
    damping_fs: float | None
    velocity_temperature_K: float | None
    velocity_seed: int | None


@dataclass(frozen=True, slots=True)
class ProtocolSpec:
    units: LammpsUnits
    timestep_fs: float
    stages: tuple[MinimizeStage | MdStage, ...]


@dataclass(frozen=True, slots=True)
class ModifierSelection:
    name: str
    stage_id: str | None


@dataclass(frozen=True, slots=True)
class SpecIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    declared_path: str
    resolved_path: Path
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class ProvenanceSpec:
    structure: str
    type_map: str
    potential: str
    protocol: str


@dataclass(frozen=True, slots=True)
class GenerationSpec:
    source_path: Path
    task: str
    input_declared_path: str
    input_file: Path
    data_declared_path: str
    data_file: Path
    data_sha256: str
    atom_count: int
    atom_types: int
    type_map: tuple[tuple[int, str], ...]
    has_h: bool
    atom_style: str
    periodicity: tuple[str, str, str]
    potential_family: str
    pair_style: str
    pair_coeff: str
    artifacts: tuple[ArtifactSpec, ...]
    type_elements: tuple[str, ...]
    profiles: tuple[str, ...]
    protocol: ProtocolSpec
    modifiers: tuple[ModifierSelection, ...]
    provenance: ProvenanceSpec
    unresolved: tuple[UnresolvedItem, ...]


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    role: str
    path: str
    exists: bool
    sha256: str | None
    expected_sha256: str | None
    matches_expected: bool | None


@dataclass(frozen=True, slots=True)
class ToolEntry:
    name: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SpecAssessment:
    spec: GenerationSpec | None
    level: LevelEvidence
    issues: tuple[SpecIssue, ...]
    manifest: tuple[ManifestEntry, ...]
