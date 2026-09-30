#!/usr/bin/env python3
"""
Consistency tests for base_templates/INDEX.json (task -> template -> modifiers routing).

Guarantees:
  1. every template referenced in INDEX exists on disk (and vice versa)
  2. every modifier referenced by a task exists in the modifiers map (and every
     modifier file exists on disk)
  3. every modifier is referenced by at least one task (except the 'empty'
     format-reference patch)
  4. modifier conflict declarations are symmetric
  5. every VASP template passes scripts/validate_input.py with zero ERROR

Run:
    python -m unittest discover -s tests -v          # from the skill directory
"""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory
TEMPLATES = ROOT / "base_templates"
INDEX = json.loads((TEMPLATES / "INDEX.json").read_text(encoding="utf-8"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")

# INDEX task name -> validator task name (only where they differ)
TASK_MAP = {"scf": "static", "dftu": "relax", "bader": "static", "hse": "static"}


def iter_tasks():
    for code, tasks in INDEX["tasks"].items():
        for task, spec in tasks.items():
            yield code, task, spec


class TestIndexCompleteness(unittest.TestCase):
    def test_every_indexed_template_exists(self):
        missing = [spec["template"] for _, _, spec in iter_tasks()
                   if not (TEMPLATES / spec["template"]).exists()]
        self.assertEqual(missing, [], f"templates in INDEX but not on disk: {missing}")

    def test_every_template_file_is_indexed(self):
        indexed = {spec["template"] for _, _, spec in iter_tasks()}
        on_disk = {p.name for p in TEMPLATES.iterdir()
                   if p.is_file() and p.suffix in (".incar", ".in", ".inp")}
        self.assertEqual(on_disk - indexed, set(),
                         "template files not referenced by INDEX.json")
        self.assertEqual(indexed - on_disk, set(),
                         "INDEX references files that do not exist")

    def test_indexed_modifiers_exist(self):
        known = set(INDEX["modifiers"])
        bad = [(code, task, m) for code, task, spec in iter_tasks()
               for m in spec["modifiers"] if m not in known]
        self.assertEqual(bad, [], f"tasks reference unknown modifiers: {bad}")

    def test_modifier_files_exist(self):
        missing = [m["file"] for m in INDEX["modifiers"].values()
                   if not (ROOT / "modifiers" / m["file"]).exists()]
        self.assertEqual(missing, [], f"modifier files missing: {missing}")

    def test_every_modifier_is_used(self):
        used = {m for _, _, spec in iter_tasks() for m in spec["modifiers"]}
        unused = set(INDEX["modifiers"]) - used - {"empty"}  # 'empty' documents the format
        self.assertEqual(unused, set(), f"modifiers never referenced by any task: {unused}")

    def test_conflicts_are_symmetric(self):
        mods = INDEX["modifiers"]
        asymmetric = [(a, b) for a, spec in mods.items() for b in spec["conflicts"]
                      if a not in mods.get(b, {}).get("conflicts", [])]
        self.assertEqual(asymmetric, [], f"asymmetric conflict declarations: {asymmetric}")


class TestTemplatesPassValidator(unittest.TestCase):
    def test_vasp_templates_have_zero_errors(self):
        failures = {}
        for code, task, spec in iter_tasks():
            if code != "vasp":
                continue
            params = vi.parse_incar(str(TEMPLATES / spec["template"]))
            findings = vi.validate(params, task_override=TASK_MAP.get(task, task))
            errors = [str(x) for x in findings if x.level == vi.ERROR]
            if errors:
                failures[spec["template"]] = errors
        self.assertEqual(failures, {},
                         msg=f"VASP templates with ERROR findings:\n{failures}")

    def test_cp2k_templates_have_zero_errors(self):
        failures = {}
        for code, task, spec in iter_tasks():
            if code != "cp2k":
                continue
            findings = vi.validate_cp2k_one(str(TEMPLATES / spec["template"]),
                                            task=TASK_MAP.get(task, task))
            errors = [str(x) for x in findings if x.level == vi.ERROR]
            if errors:
                failures[spec["template"]] = errors
        self.assertEqual(failures, {},
                         msg=f"CP2K templates with ERROR findings:\n{failures}")

    def test_lammps_templates_have_zero_errors(self):
        failures = {}
        for code, task, spec in iter_tasks():
            if code != "lammps":
                continue
            findings = vi.validate_lammps_one(str(TEMPLATES / spec["template"]),
                                              task=TASK_MAP.get(task, task))
            errors = [str(x) for x in findings if x.level == vi.ERROR]
            if errors:
                failures[spec["template"]] = errors
        self.assertEqual(failures, {},
                         msg=f"LAMMPS templates with ERROR findings:\n{failures}")

    def test_modifier_overrides_are_real_keywords(self):
        """Every 'overrides' entry must appear as a keyword in its patch file."""
        problems = {}
        for name, spec in INDEX["modifiers"].items():
            if name == "empty":
                continue
            text = (ROOT / "modifiers" / spec["file"]).read_text(encoding="utf-8")
            for kw in spec["overrides"]:
                if kw not in text:
                    problems.setdefault(name, []).append(kw)
        self.assertEqual(problems, {},
                         msg=f"overrides not found in patch files: {problems}")


if __name__ == "__main__":
    unittest.main()
