"""Shared fixture builders for LAMMPS deterministic renderer tests.

Both builders construct a frozen ``RenderRequest`` through Phase A's
``write_complete_case()`` so the L0 spec assessment runs against the same
deterministic fixtures as the evidence suite. ``build_mlff_request()`` writes a
MACE-flavoured spec JSON beside the generic case (reusing the data file and
system fields) with a fixed placeholder model artifact so SHA256 hashes stay
stable across test runs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "renderer"
TEMPLATES = ROOT / "base_templates"
MODIFIERS = ROOT / "modifiers" / "lammps"

_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

MODEL_NAME = "mace_model.pth"
MODEL_BYTES = b"MACE_PLACEHOLDER\n"


def _load_evidence_modules() -> dict[str, Any]:
    for name, script in [
        ("lammps_evidence", ROOT / "scripts" / "lammps_evidence.py"),
        ("lammps_spec", ROOT / "scripts" / "lammps_spec.py"),
    ]:
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, script)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    return {
        "lammps_evidence": sys.modules["lammps_evidence"],
        "lammps_spec": sys.modules["lammps_spec"],
    }


def _assess(spec_path: Path) -> Any:
    lammps_spec = sys.modules["lammps_spec"]
    assessment = lammps_spec.assess_generation_spec(spec_path)
    assert assessment.spec is not None, (
        f"spec assessment failed: {assessment.issues}"
    )
    return assessment.spec


def _spec_from_case(temp_dir: Path) -> Any:
    from lammps_evidence_support import write_complete_case

    spec_path = write_complete_case(temp_dir)
    return _assess(spec_path)


def _mlff_spec_from_case(temp_dir: Path) -> Any:
    from lammps_evidence_support import write_complete_case

    write_complete_case(temp_dir)
    (temp_dir / MODEL_NAME).write_bytes(MODEL_BYTES)
    spec_path = temp_dir / "generation_spec.json"
    raw: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
    raw["potential"] = {
        "family": "mace",
        "pair_style": "mace",
        "pair_coeff": f"* * {MODEL_NAME} Al",
        "artifacts": [
            {
                "path": MODEL_NAME,
                "sha256": f"sha256:{hashlib.sha256(MODEL_BYTES).hexdigest()}",
            }
        ],
        "type_elements": ["Al"],
    }
    raw["profiles"] = ["mlff/mace"]
    raw["task"] = "md"
    mlff_path = temp_dir / "generation_spec_mlff.json"
    mlff_path.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _assess(mlff_path)


def build_generic_request(tmp: Path | None = None):
    _load_evidence_modules()
    temp_dir = tmp or Path(tempfile.mkdtemp(prefix="render_generic_"))
    spec = _spec_from_case(temp_dir)
    from render_lammps import RenderRequest

    return RenderRequest(
        spec=spec,
        base_template="lammps_md.in",
        modifiers=(),
        profiles=("generic_md",),
        templates_dir=TEMPLATES,
        modifiers_dir=MODIFIERS,
        examples_index_path=None,
    )


def build_mlff_request(tmp: Path | None = None):
    _load_evidence_modules()
    temp_dir = tmp or Path(tempfile.mkdtemp(prefix="render_mlff_"))
    spec = _mlff_spec_from_case(temp_dir)
    from render_lammps import RenderRequest

    return RenderRequest(
        spec=spec,
        base_template="lammps_mlff.in",
        modifiers=("dump_full",),
        profiles=("mlff/mace",),
        templates_dir=TEMPLATES,
        modifiers_dir=MODIFIERS,
        examples_index_path=None,
    )
