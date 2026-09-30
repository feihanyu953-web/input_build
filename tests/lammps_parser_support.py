#!/usr/bin/env python3
"""Shared module-loader for LAMMPS command-model / parser tests.

Loads stdlib-only scripts (lammps_command.py, parse_lammps.py,
validate_input.py) from the skill's scripts/ directory by file path and
registers them in sys.modules, so cross-module imports resolve deterministically
regardless of the harness's sys.path layout.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def load_script(name, path, deps=()):
    for dep in deps:
        if dep not in sys.modules:
            load_script(dep, SCRIPTS / f"{dep}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
