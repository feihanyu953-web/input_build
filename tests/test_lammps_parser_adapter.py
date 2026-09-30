#!/usr/bin/env python3
"""
LAMMPS malformed-input and validate_input compatibility adapter tests (Phase C).

Covers the parse_lammps.py unclosed-quote ERROR handling and the lazy
delegation adapter in validate_input.parse_lammps: legacy (commands, raw_text)
return shape, simple-input equivalence, `>>> USER` marker scanning, and the
continuation-merge delegation proof.

Sibling files test the command model + parser core + includes
(test_lammps_command_parser.py) and lifecycle / dynamic control flow
(test_lammps_parser_lifecycle.py).

Run from the skill directory:
    python -m unittest discover -s tests -p "test_lammps_parser_adapter.py" -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

from lammps_parser_support import SCRIPTS, load_script

lammps_command = load_script("lammps_command", SCRIPTS / "lammps_command.py")
parse_lammps_mod = load_script(
    "parse_lammps", SCRIPTS / "parse_lammps.py", deps=("lammps_command",))


def _load_validate_input():
    if "validate_input" in sys.modules:
        return sys.modules["validate_input"]
    return load_script("validate_input", SCRIPTS / "validate_input.py")


class TestMalformedInput(unittest.TestCase):
    def test_unclosed_quote_emits_error_and_incomplete(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".in", delete=False, encoding="utf-8") as f:
            f.write('print "unclosed\nrun 10\n')
            path = f.name
        result = parse_lammps_mod.parse_lammps_file(path)
        codes = [i.code for i in result.issues]
        self.assertIn("LAMMPS_UNCLOSED_QUOTE", codes)
        self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)
        run_cmd = next(c for c in result.commands if c.name == "run")
        self.assertEqual(run_cmd.args, ("10",))

    def test_unclosed_quote_does_not_crash_parser(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".in", delete=False, encoding="utf-8") as f:
            f.write("units metal\nprint 'broken\nrun 10\n")
            path = f.name
        result = parse_lammps_mod.parse_lammps_file(path)
        names = [c.name for c in result.commands]
        self.assertIn("units", names)
        self.assertIn("run", names)


LAMMPS_OK = """\
units metal
atom_style atomic
boundary p p p
read_data system.data
pair_style eam/alloy
pair_coeff * * Al.eam Al
velocity all create 300.0 12345
neighbor 2.0 bin
timestep 0.0005
fix 1 all nvt temp 300.0 300.0 0.05
thermo 100
dump 1 all custom 100 traj.lammpstrj id type x y z
run 1000
"""


class TestCompatibilityAdapter(unittest.TestCase):
    def setUp(self):
        self.vi = _load_validate_input()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        p = self.dir / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_parse_lammps_returns_commands_and_raw_text(self):
        path = self.write("in.lammps", LAMMPS_OK)
        commands, raw_text = self.vi.parse_lammps(path)
        self.assertIsInstance(commands, list)
        self.assertIsInstance(raw_text, str)
        self.assertIn("units metal", raw_text)

    def test_legacy_simple_input_command_shape(self):
        path = self.write("in.lammps", LAMMPS_OK)
        commands, _ = self.vi.parse_lammps(path)
        self.assertEqual(commands[0], ("units", ["metal"]))
        self.assertEqual(commands[5], ("pair_coeff", ["*", "*", "Al.eam", "Al"]))
        self.assertEqual(commands[0][1], ["metal"])
        self.assertIsInstance(commands[0][1], list)

    def test_validate_lammps_one_clean_passes(self):
        path = self.write("in.lammps", LAMMPS_OK)
        findings = self.vi.validate_lammps_one(path)
        self.assertEqual(findings, [])

    def test_validate_lammps_one_missing_pair_style(self):
        text = LAMMPS_OK.replace("pair_style eam/alloy\n", "")
        path = self.write("in.lammps", text)
        findings = self.vi.validate_lammps_one(path)
        codes = {f.code for f in findings}
        self.assertIn("LAMMPS_NO_PAIR_STYLE", codes)

    def test_user_marker_satisfies_potential_rule(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "# >>> USER: insert pair_style/pair_coeff here <<<\n")
        path = self.write("in.lammps", text)
        findings = self.vi.validate_lammps_one(path)
        codes = {f.code for f in findings}
        self.assertNotIn("LAMMPS_NO_PAIR_STYLE", codes)

    def test_lammps_data_context_finds_read_data(self):
        path = self.write("in.lammps", LAMMPS_OK)
        data_path, reason = self.vi.lammps_data_context(path)
        self.assertIsNotNone(data_path)
        self.assertTrue(data_path.endswith("system.data"))

    def test_raw_text_preserves_user_marker_scan(self):
        text = LAMMPS_OK.replace(
            "pair_style eam/alloy\npair_coeff * * Al.eam Al\n",
            "pair_style >>> USER <<<\n")
        path = self.write("in.lammps", text)
        commands, raw_text = self.vi.parse_lammps(path)
        self.assertIn(">>> USER", raw_text)
        findings = self.vi.validate_lammps_one(path)
        codes = {f.code for f in findings}
        self.assertNotIn("LAMMPS_NO_PAIR_STYLE", codes)

    def test_parse_lammps_delegates_to_new_parser(self):
        path2 = self.write("in2.lammps", "units metal &\n  atom_style atomic\n")
        commands2, _ = self.vi.parse_lammps(path2)
        self.assertEqual(len(commands2), 1)
        self.assertEqual(commands2[0], ("units", ["metal", "atom_style", "atomic"]))


if __name__ == "__main__":
    unittest.main()
