#!/usr/bin/env python3
"""
LAMMPS dynamic control-flow and lifecycle tracking tests (Phase C).

Covers the parse_lammps.py INCOMPLETE marking for if/jump/label/loop/next, the
structured fix/compute/dump lifecycle records (create/destroy/duplicate/unknown
ID warnings), and deterministic serialization of repeated parses.

Sibling files test the command model + parser core + includes
(test_lammps_command_parser.py) and the validate_input compatibility adapter
(test_lammps_parser_adapter.py).

Run from the skill directory:
    python -m unittest discover -s tests -p "test_lammps_parser_lifecycle.py" -v
"""

import tempfile
import unittest
from pathlib import Path

from lammps_parser_support import SCRIPTS, load_script

lammps_command = load_script("lammps_command", SCRIPTS / "lammps_command.py")
parse_lammps_mod = load_script(
    "parse_lammps", SCRIPTS / "parse_lammps.py", deps=("lammps_command",))

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lammps_parser"


class TestDynamicControlFlow(unittest.TestCase):
    def test_jump_marks_incomplete(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "dynamic.in"))
        self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)
        codes = [i.code for i in result.issues]
        self.assertIn("LAMMPS_DYNAMIC_CONTROL_FLOW", codes)

    def test_dynamic_commands_remain_in_command_list(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "dynamic.in"))
        names = [c.name for c in result.commands]
        self.assertIn("label", names)
        self.assertIn("jump", names)
        self.assertIn("next", names)

    def test_if_marks_incomplete(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".in", delete=False, encoding="utf-8") as f:
            f.write('units metal\nif "${steps} > 10" then &\n  run 100\n')
            path = f.name
        result = parse_lammps_mod.parse_lammps_file(path)
        self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)


class TestLifecycleTracking(unittest.TestCase):
    def test_fix_unfix_lifecycle(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "lifecycle.in"))
        fix_records = [r for r in result.lifecycle
                       if r.kind == lammps_command.LifecycleKind.FIX]
        self.assertEqual(len(fix_records), 1)
        self.assertEqual(fix_records[0].identifier, "1")
        self.assertEqual(fix_records[0].group, "all")
        self.assertEqual(fix_records[0].style, "nvt")
        self.assertIsNotNone(fix_records[0].destroyed_at)

    def test_compute_lifecycle(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "lifecycle.in"))
        compute_records = [r for r in result.lifecycle
                           if r.kind == lammps_command.LifecycleKind.COMPUTE]
        self.assertEqual(len(compute_records), 1)
        self.assertEqual(compute_records[0].identifier, "1")
        self.assertEqual(compute_records[0].style, "pe")
        self.assertIsNone(compute_records[0].destroyed_at)

    def test_dump_undump_lifecycle(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "lifecycle.in"))
        dump_records = [r for r in result.lifecycle
                        if r.kind == lammps_command.LifecycleKind.DUMP]
        self.assertEqual(len(dump_records), 1)
        self.assertEqual(dump_records[0].identifier, "1")
        self.assertEqual(dump_records[0].group, "all")
        self.assertIsNotNone(dump_records[0].destroyed_at)

    def test_active_lifecycle_returns_undestroyed_only(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "lifecycle.in"))
        active = lammps_command.active_lifecycle(result)
        kinds = [r.kind for r in active]
        self.assertIn(lammps_command.LifecycleKind.COMPUTE, kinds)
        self.assertNotIn(lammps_command.LifecycleKind.FIX, kinds)
        self.assertNotIn(lammps_command.LifecycleKind.DUMP, kinds)

    def test_unfix_unknown_id_warns(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".in", delete=False, encoding="utf-8") as f:
            f.write("units metal\nunfix 99\n")
            path = f.name
        result = parse_lammps_mod.parse_lammps_file(path)
        codes = [i.code for i in result.issues]
        self.assertIn("LAMMPS_UNFIX_UNKNOWN", codes)


class TestDeterministicSerialization(unittest.TestCase):
    def test_repeated_parse_produces_identical_commands(self):
        r1 = parse_lammps_mod.parse_lammps_file(str(FIXTURES / "lifecycle.in"))
        r2 = parse_lammps_mod.parse_lammps_file(str(FIXTURES / "lifecycle.in"))
        self.assertEqual(
            [(c.name, c.args) for c in r1.commands],
            [(c.name, c.args) for c in r2.commands])
        self.assertEqual(r1.completeness, r2.completeness)
        self.assertEqual(r1.lifecycle, r2.lifecycle)

    def test_to_legacy_commands_is_stable(self):
        result = parse_lammps_mod.parse_lammps_file(str(FIXTURES / "lifecycle.in"))
        legacy1 = lammps_command.to_legacy_commands(result)
        legacy2 = lammps_command.to_legacy_commands(result)
        self.assertEqual(legacy1, legacy2)


if __name__ == "__main__":
    unittest.main()
