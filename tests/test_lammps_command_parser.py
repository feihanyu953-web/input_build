#!/usr/bin/env python3
"""
LAMMPS command-model and parser core tests (Phase C).

Covers the immutable value objects in scripts/lammps_command.py and the
multiline parser in scripts/parse_lammps.py: continuation merging, quote-aware
comment stripping and tokenization, source-line spans, and include expansion
with cycle / escape / depth / missing-file handling.

Sibling files test the same parser's lifecycle + dynamic control flow
(test_lammps_parser_lifecycle.py) and the validate_input compatibility adapter
(test_lammps_parser_adapter.py).

Run from the skill directory:
    python -m unittest discover -s tests -p "test_lammps_command_parser.py" -v
"""

import tempfile
import unittest
from pathlib import Path

from lammps_parser_support import SCRIPTS, load_script

lammps_command = load_script("lammps_command", SCRIPTS / "lammps_command.py")
parse_lammps_mod = load_script(
    "parse_lammps", SCRIPTS / "parse_lammps.py", deps=("lammps_command",))

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lammps_parser"


class TestCommandModel(unittest.TestCase):
    def test_source_span_is_frozen(self):
        span = lammps_command.SourceSpan(source="/abs/in.lammps", start_line=3, end_line=5)
        with self.assertRaises(Exception):
            span.start_line = 99

    def test_command_args_is_tuple(self):
        span = lammps_command.SourceSpan("/abs/in.lammps", 1, 1)
        cmd = lammps_command.Command("fix", ("1", "all", "nvt"), span, "fix 1 all nvt")
        self.assertIsInstance(cmd.args, tuple)

    def test_completeness_values(self):
        self.assertEqual(lammps_command.Completeness.COMPLETE, "COMPLETE")
        self.assertEqual(lammps_command.Completeness.INCOMPLETE, "INCOMPLETE")

    def test_to_legacy_commands_projects_name_and_args(self):
        span = lammps_command.SourceSpan("/abs/in.lammps", 1, 1)
        commands = (
            lammps_command.Command("units", ("metal",), span, "units metal"),
            lammps_command.Command("fix", ("1", "all", "nvt"), span, "fix 1 all nvt"),
        )
        result = lammps_command.ParseResult(
            commands=commands, raw_text="", issues=(),
            completeness=lammps_command.Completeness.COMPLETE,
            lifecycle=(), includes=())
        legacy = lammps_command.to_legacy_commands(result)
        self.assertEqual(legacy, [
            ("units", ["metal"]),
            ("fix", ["1", "all", "nvt"]),
        ])
        self.assertIsInstance(legacy[0][1], list)

    def test_active_lifecycle_filters_undestroyed(self):
        created = lammps_command.SourceSpan("/abs/in.lammps", 5, 5)
        destroyed = lammps_command.SourceSpan("/abs/in.lammps", 10, 10)
        active = lammps_command.LifecycleRecord(
            lammps_command.LifecycleKind.FIX, "1", "all", "nvt", created, None)
        gone = lammps_command.LifecycleRecord(
            lammps_command.LifecycleKind.FIX, "2", "all", "shake", created, destroyed)
        result = lammps_command.ParseResult(
            commands=(), raw_text="", issues=(),
            completeness=lammps_command.Completeness.COMPLETE,
            lifecycle=(active, gone), includes=())
        self.assertEqual(lammps_command.active_lifecycle(result), (active,))


class TestParserCore(unittest.TestCase):
    def parse(self, text):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".in", delete=False, encoding="utf-8") as f:
            f.write(text)
            path = f.name
        return parse_lammps_mod.parse_lammps_file(path)

    def test_simple_input_commands_and_raw_text(self):
        result = parse_lammps_mod.parse_lammps_file(str(FIXTURES / "simple.in"))
        names = [c.name for c in result.commands]
        self.assertEqual(names, [
            "units", "atom_style", "boundary", "read_data",
            "pair_style", "pair_coeff", "timestep", "fix", "run"])
        self.assertEqual(result.commands[0].args, ("metal",))
        self.assertEqual(result.commands[5].args, ("*", "*", "Al.eam", "Al"))
        self.assertEqual(result.completeness, lammps_command.Completeness.COMPLETE)
        self.assertIn("units metal", result.raw_text)

    def test_inline_comment_stripped_from_args(self):
        result = self.parse("timestep 0.001 # 1 fs\nrun 10\n")
        ts = next(c for c in result.commands if c.name == "timestep")
        self.assertEqual(ts.args, ("0.001",))

    def test_continuation_merges_lines_and_span(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "continuation.in"))
        units = result.commands[0]
        self.assertEqual(units.name, "units")
        self.assertEqual(units.args, ("metal", "atom_style", "atomic"))
        self.assertEqual(units.span.start_line, 1)
        self.assertEqual(units.span.end_line, 2)
        fix = next(c for c in result.commands if c.name == "fix")
        self.assertEqual(fix.args, ("1", "all", "nvt", "temp", "300.0", "300.0", "0.05"))
        self.assertEqual(fix.span.start_line, 4)
        self.assertEqual(fix.span.end_line, 5)

    def test_comment_after_ampersand_is_stripped(self):
        result = self.parse("units metal & # comment\n  atom_style atomic\n")
        cmd = result.commands[0]
        self.assertEqual(cmd.name, "units")
        self.assertEqual(cmd.args, ("metal", "atom_style", "atomic"))

    def test_comment_only_line_breaks_continuation(self):
        result = self.parse("units metal &\n# comment only\n  atom_style atomic\n")
        names = [c.name for c in result.commands]
        self.assertEqual(names, ["units", "atom_style"])
        self.assertEqual(result.commands[0].args, ("metal",))

    def test_quotes_containing_hash_preserved(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "quotes.in"))
        print_cmd = next(c for c in result.commands if c.name == "print")
        self.assertEqual(print_cmd.args, ("hash # inside quotes",))

    def test_source_span_source_is_root_path(self):
        result = parse_lammps_mod.parse_lammps_file(str(FIXTURES / "simple.in"))
        self.assertTrue(result.commands[0].span.source.endswith("simple.in"))

    def test_empty_file_is_complete_with_no_commands(self):
        result = self.parse("")
        self.assertEqual(result.commands, ())
        self.assertEqual(result.completeness, lammps_command.Completeness.COMPLETE)

    def test_comment_only_file_is_complete_with_no_commands(self):
        result = self.parse("# just a comment\n# another\n")
        self.assertEqual(result.commands, ())
        self.assertEqual(result.completeness, lammps_command.Completeness.COMPLETE)

    def test_command_order_preserved(self):
        result = self.parse("units metal\nboundary p p p\nrun 10\n")
        self.assertEqual([c.name for c in result.commands], ["units", "boundary", "run"])


class TestIncludeHandling(unittest.TestCase):
    def test_include_expands_commands_in_place(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "includes" / "main.in"))
        names = [c.name for c in result.commands]
        self.assertEqual(names, ["units", "atom_style", "boundary", "run"])
        self.assertEqual(result.includes, (
            str((FIXTURES / "includes" / "sub.in").resolve()),))
        sub_cmd = result.commands[1]
        self.assertTrue(sub_cmd.span.source.endswith("sub.in"))

    def test_include_command_not_in_command_list(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "includes" / "main.in"))
        self.assertFalse(any(c.name == "include" for c in result.commands))

    def test_include_cycle_detected(self):
        result = parse_lammps_mod.parse_lammps_file(
            str(FIXTURES / "includes" / "cycle_a.in"))
        codes = [i.code for i in result.issues]
        self.assertIn("LAMMPS_INCLUDE_CYCLE", codes)
        self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)

    def test_include_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "in.lammps"
            root.write_text("include ../../../etc/passwd\n", encoding="utf-8")
            result = parse_lammps_mod.parse_lammps_file(str(root))
            codes = [i.code for i in result.issues]
            self.assertIn("LAMMPS_INCLUDE_ESCAPE", codes)
            self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)

    def test_include_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "in.lammps"
            root.write_text("include nonexistent.in\nrun 10\n", encoding="utf-8")
            result = parse_lammps_mod.parse_lammps_file(str(root))
            codes = [i.code for i in result.issues]
            self.assertIn("LAMMPS_INCLUDE_MISSING", codes)
            self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)
            run_cmd = next(c for c in result.commands if c.name == "run")
            self.assertEqual(run_cmd.args, ("10",))

    def test_include_depth_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "in.lammps"
            root.write_text("include a.in\n", encoding="utf-8")
            (tmp / "a.in").write_text("include b.in\n", encoding="utf-8")
            (tmp / "b.in").write_text("run 10\n", encoding="utf-8")
            result = parse_lammps_mod.parse_lammps_file(str(root), max_depth=1)
            codes = [i.code for i in result.issues]
            self.assertIn("LAMMPS_INCLUDE_DEPTH", codes)
            self.assertEqual(result.completeness, lammps_command.Completeness.INCOMPLETE)


if __name__ == "__main__":
    unittest.main()
