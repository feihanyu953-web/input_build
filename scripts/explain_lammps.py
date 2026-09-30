#!/usr/bin/env python3
"""Read-only LAMMPS input explainer (Phase I).

Loads existing artifacts (generation spec, rendered input, render trace,
examples index, validation report, static validation) and joins them into a
deterministic ``explain_report.json`` and ``explain_report.md``. It never
parses, validates, executes, repairs or upgrades evidence.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

_SIBLING_MODULES: Final = (
    "explain_lammps_models",
    "explain_lammps_evidence",
    "explain_lammps_commands",
    "explain_lammps_join",
    "explain_lammps_report",
)


def _restore_module(name: str, previous: ModuleType | None) -> None:
    if previous is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


def _load_api() -> None:
    global build_explain_report, load_rule_registry
    global report_json, report_markdown

    previous = {name: sys.modules.get(name) for name in _SIBLING_MODULES}
    loaded = False
    try:
        for name in _SIBLING_MODULES:
            if name in sys.modules:
                continue
            path = Path(__file__).with_name(f"{name}.py")
            module_spec = importlib.util.spec_from_file_location(name, path)
            if module_spec is None or module_spec.loader is None:
                msg = f"unable to load explain sibling module: {path}"
                raise ImportError(msg)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[name] = module
            module_spec.loader.exec_module(module)

        from explain_lammps_join import build_explain_report, load_rule_registry
        from explain_lammps_report import report_json, report_markdown

        loaded = True
    finally:
        if not loaded:
            for name, module in previous.items():
                _restore_module(name, module)


_load_api()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Explain a LAMMPS input by joining provenance, findings, "
            "and evidence artifacts."
        ),
    )
    parser.add_argument("--spec", required=True, help="generation_spec.json")
    parser.add_argument("--input", required=True, help="rendered in.lammps")
    parser.add_argument(
        "--render-trace", default=None, help="render_trace.json from Phase D"
    )
    parser.add_argument(
        "--examples-index",
        default=None,
        help="lammps_examples_index.json from Phase B",
    )
    parser.add_argument(
        "--validation-report",
        default=None,
        help="validation_report.json from Phase A",
    )
    parser.add_argument(
        "--static-validation",
        default=None,
        help="static_validation.json from Phase A",
    )
    parser.add_argument(
        "--output-dir", required=True, help="output directory for the two reports"
    )
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    rules = load_rule_registry(skill_root)

    report = build_explain_report(
        spec_path=Path(args.spec) if args.spec else None,
        input_path=Path(args.input) if args.input else None,
        render_trace_path=Path(args.render_trace) if args.render_trace else None,
        examples_index_path=Path(args.examples_index) if args.examples_index else None,
        validation_report_path=(
            Path(args.validation_report) if args.validation_report else None
        ),
        static_validation_path=(
            Path(args.static_validation) if args.static_validation else None
        ),
        rules=rules,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "explain_report.json").write_text(
        report_json(report), encoding="utf-8", newline="\n"
    )
    (output_dir / "explain_report.md").write_text(
        report_markdown(report), encoding="utf-8", newline="\n"
    )

    print(
        f"status={report.status} exit_code={report.exit_code} "
        f"json={output_dir / 'explain_report.json'} "
        f"md={output_dir / 'explain_report.md'}"
    )
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
