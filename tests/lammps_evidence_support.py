#!/usr/bin/env python3
"""Shared fixtures for LAMMPS generation evidence tests."""

import hashlib
import json
from pathlib import Path
from typing import Final, Literal, Sequence, TypedDict


VALID_INPUT: Final = """units metal
atom_style atomic
boundary p p p
read_data system.data
pair_style lj/cut 8.5
pair_coeff * * 0.0103 2.5
timestep 0.001
fix integrator all nve
thermo 10
run 10
"""

VALID_DATA: Final = """LAMMPS data

1 atoms
1 atom types

Masses

1 26.9815

Atoms # atomic

1 1 0.0 0.0 0.0
"""


class UnresolvedInput(TypedDict):
    key: str
    blocks_level: Literal["L0", "L1", "L2", "L3", "L4", "L5"]
    reason: str


def write_complete_case(
    root: Path,
    input_text: str = VALID_INPUT,
    unresolved: Sequence[UnresolvedInput] | None = None,
) -> Path:
    """Write a complete deterministic LAMMPS evidence fixture."""
    input_bytes = input_text.encode("utf-8")
    data_bytes = VALID_DATA.encode("utf-8")
    (root / "in.lammps").write_bytes(input_bytes)
    (root / "system.data").write_bytes(data_bytes)

    unresolved_entries = [
        {
            "key": entry["key"],
            "blocks_level": entry["blocks_level"],
            "reason": entry["reason"],
        }
        for entry in unresolved or ()
    ]
    generation_spec = {
        "schema_version": 1,
        "code": "lammps",
        "task": "md",
        "input_file": "in.lammps",
        "system": {
            "data_file": "system.data",
            "data_sha256": f"sha256:{hashlib.sha256(data_bytes).hexdigest()}",
            "atom_count": 1,
            "atom_types": 1,
            "type_map": {"1": "Al"},
            "has_h": False,
            "atom_style": "atomic",
            "periodicity": ["p", "p", "p"],
        },
        "potential": {
            "family": "inline_lj",
            "pair_style": "lj/cut 8.5",
            "pair_coeff": "* * 0.0103 2.5",
            "artifacts": [],
            "type_elements": ["Al"],
        },
        "protocol": {
            "units": "metal",
            "timestep_fs": 1.0,
            "stages": [
                {
                    "kind": "md",
                    "stage_id": "run",
                    "ensemble": "nve",
                    "steps": 10,
                    "temperature_start_K": None,
                    "temperature_stop_K": None,
                    "damping_fs": None,
                    "velocity_temperature_K": None,
                    "velocity_seed": None,
                }
            ],
        },
        "profiles": ["generic_md"],
        "modifiers": [],
        "provenance": {
            "structure": "detected",
            "type_map": "detected",
            "potential": "user-provided",
            "protocol": "user-confirmed",
        },
        "unresolved": unresolved_entries,
    }
    spec_path = root / "generation_spec.json"
    spec_path.write_bytes(
        (json.dumps(generation_spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )
    return spec_path
