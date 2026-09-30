from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "profile_fixtures"


def load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def make_commands(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    return [(cmd, args_str.split()) for cmd, args_str in pairs]


VALID_MACE_SPEC = {
    "schema_version": 1, "code": "lammps", "task": "mlff-md", "input_file": "in.lammps",
    "system": {"data_file":"system.data","data_sha256":"sha256:aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000","atom_count":27,"atom_types":4,"type_map":{"1":"C","2":"H","3":"O","4":"N"},"has_h":True,"atom_style":"atomic","periodicity":["p","p","p"]},
    "potential": {"family":"mace","pair_style":"mace","pair_coeff":"* * mace.model C H O N","artifacts":[{"path":"mace.model","sha256":"sha256:bbbb1111bbbb1111bbbb1111bbbb1111bbbb1111bbbb1111bbbb1111bbbb1111"}],"type_elements":["C","H","O","N"]},
    "protocol": {"timestep_fs":0.5,"stages":[{"name":"minimize","maxiter":1000},{"name":"equilibrate","ensemble":"nvt","temperature_K":300,"duration_ps":10},{"name":"production","ensemble":"nvt","temperature_K":300,"duration_ps":100}]},
    "profiles": ["mlff/mace"], "modifiers": ["dump_full"],
    "provenance": {"structure":"user-provided","type_map":"user-confirmed","potential":"user-provided","protocol":"user-confirmed"},
    "unresolved": [],
}

VALID_CONP_SPEC = {
    "schema_version": 1, "code": "lammps", "task": "conp-md", "input_file": "in.lammps",
    "system": {"data_file":"system.data","data_sha256":"sha256:cccc2222cccc2222cccc2222cccc2222cccc2222cccc2222cccc2222cccc2222","atom_count":500,"atom_types":7,"type_map":{"1":"O","2":"H","3":"C","4":"N","5":"Na","6":"Au","7":"Au"},"has_h":True,"atom_style":"full","periodicity":["p","p","p"]},
    "potential": {"family":"lj_coul","pair_style":"lj/cut/coul/long 12.0","pair_coeff":"* * params.dat O H C N Na Au","artifacts":[{"path":"params.dat","sha256":"sha256:dddd3333dddd3333dddd3333dddd3333dddd3333dddd3333dddd3333dddd3333"}],"type_elements":["O","H","C","N","Na","Au","Au"]},
    "protocol": {"timestep_fs":1.0,"stages":[{"name":"equilibrate_0V","ensemble":"nvt","temperature_K":300,"duration_ps":50},{"name":"production","ensemble":"nvt","temperature_K":300,"duration_ps":100}]},
    "profiles": ["constant_potential"], "modifiers": [],
    "provenance": {"structure":"user-provided","type_map":"user-confirmed","potential":"user-provided","protocol":"user-confirmed"},
    "unresolved": [],
}

VALID_WATER_SPEC = {
    "schema_version": 1, "code": "lammps", "task": "interface-md", "input_file": "in.lammps",
    "system": {"data_file":"system.data","data_sha256":"sha256:eeee4444eeee4444eeee4444eeee4444eeee4444eeee4444eeee4444eeee4444","atom_count":451,"atom_types":5,"type_map":{"1":"Pt","2":"O","3":"H","4":"N","5":"Na"},"has_h":True,"atom_style":"full","periodicity":["p","p","f"]},
    "potential": {"family":"lj_coul","pair_style":"lj/cut/coul/long 10.0","pair_coeff":"* * params.dat Pt O H N Na","artifacts":[{"path":"params.dat","sha256":"sha256:ffff5555ffff5555ffff5555ffff5555ffff5555ffff5555ffff5555ffff5555"}],"type_elements":["Pt","O","H","N","Na"]},
    "protocol": {"timestep_fs":1.0,"stages":[{"name":"equilibrate","ensemble":"nvt","temperature_K":300,"duration_ps":20},{"name":"production","ensemble":"nvt","temperature_K":300,"duration_ps":100}]},
    "profiles": ["interface_water"], "modifiers": ["analysis_rdf_msd"],
    "provenance": {"structure":"user-provided","type_map":"user-confirmed","potential":"user-provided","protocol":"user-confirmed"},
    "unresolved": [],
}
