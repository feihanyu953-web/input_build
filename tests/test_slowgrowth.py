#!/usr/bin/env python3
"""
Regression tests for SG-AIMD (slow-growth) support: scripts/iconst.py,
scripts/iconst_helper.py and the validate_input.py SG rules.
Stdlib only, no third-party deps.

Run:
    python -m unittest discover -s tests -v          # from the skill directory
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory
PY = sys.executable


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ic = _load("iconst", "scripts/iconst.py")


def write(tmpdir, name, text):
    p = os.path.join(tmpdir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# ICONST for the NH3 -> NH2 proton transfer: two primitives feeding one
# difference coordinate. Officially only the S line is controlled.
ICONST_TRANSFER = """\
R 65 67 0
R 69 67 0
S 1 -1 0
"""

ICONST_SINGLE_BOND = """\
R 1 5 0
"""


class TestIconstParser(unittest.TestCase):
    def test_parses_flags_items_status(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", ICONST_TRANSFER))
        self.assertEqual([l.flag for l in f.lines], ["R", "R", "S"])
        self.assertEqual(f.lines[0].items, [65, 67])
        self.assertEqual(f.lines[2].items, [1.0, -1.0])
        self.assertEqual([l.status for l in f.lines], [0, 0, 0])
        self.assertEqual([x["code"] for x in f.issues], [])

    def test_complex_coordinate_voids_primitive_status(self):
        """Official ICONST rule: once a complex coordinate exists, the status of
        every preceding primitive is ignored. Three status=0 lines here, but
        only ONE controlled parameter -> exactly one INCREM value."""
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", ICONST_TRANSFER))
        self.assertEqual(len(f.primitives), 2)
        self.assertEqual(len(f.complexes), 1)
        self.assertEqual(f.n_controlled(), 1)

    def test_primitive_only_counts_status_zero_rows(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", ICONST_SINGLE_BOND))
            g = ic.parse_iconst(write(d, "ICONST2", "R 1 5 0\nR 2 6 0\nR 3 7 7\n"))
        self.assertEqual(f.n_controlled(), 1)
        self.assertEqual(g.n_controlled(), 2)

    def test_bad_arity_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 0\n"))
        codes = [x["code"] for x in f.issues]
        self.assertIn("ICONST_ARITY", codes)

    def test_complex_coefficient_count_must_match_primitives(self):
        """S and D take one coefficient per preceding primitive. Two primitives
        with three coefficients is an arity error."""
        with tempfile.TemporaryDirectory() as d:
            bad = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nR 3 4 0\nS 1 -1 1 0\n"))
            good = ic.parse_iconst(write(d, "ICONST2", "R 1 2 0\nR 3 4 0\nD 1.1 1.5 0\n"))
        self.assertIn("ICONST_ARITY", [x["code"] for x in bad.issues])
        self.assertEqual([x["code"] for x in good.issues], [])
        self.assertEqual(good.n_controlled(), 1)

    def test_d_flag_arity_follows_primitive_count_not_fixed_two(self):
        """rev2 fix: D is a complex coordinate whose coefficient count follows
        the number of preceding primitives. Three primitives -> three refs."""
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(
                d, "ICONST",
                "R 1 2 0\nR 3 4 0\nR 5 6 0\nD 1.1 1.5 1.3 0\n"))
        self.assertEqual([x["code"] for x in f.issues], [])
        self.assertEqual(f.n_controlled(), 1)

    def test_negative_d_reference_is_arity_error(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nD -1.1 0\n"))
        self.assertIn("ICONST_ARITY", [x["code"] for x in f.issues])

    def test_unknown_flag_vs_known_but_not_v1(self):
        with tempfile.TemporaryDirectory() as d:
            unknown = ic.parse_iconst(write(d, "ICONST", "Q 1 2 0\n"))
            not_v1 = ic.parse_iconst(write(d, "ICONST2", "M 1 2 3 0\n"))
        self.assertIn("ICONST_FLAG_UNKNOWN", [x["code"] for x in unknown.issues])
        self.assertIn("ICONST_FLAG_COVERAGE", [x["code"] for x in not_v1.issues])

    def test_status_coverage_and_invalid_status(self):
        with tempfile.TemporaryDirectory() as d:
            metadyn = ic.parse_iconst(write(d, "ICONST", "R 1 2 5\n"))
            broken = ic.parse_iconst(write(d, "ICONST2", "R 1 2 x\n"))
        self.assertIn("ICONST_STATUS_COVERAGE", [x["code"] for x in metadyn.issues])
        self.assertIn("ICONST_STATUS_INVALID", [x["code"] for x in broken.issues])

    def test_primitive_after_complex_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nS 1 0\nR 3 4 0\n"))
        self.assertIn("ICONST_ORDER", [x["code"] for x in f.issues])

    def test_status_seven_complex_is_not_controlled(self):
        """Pool switch + status filter combined: primitives' status is voided by
        the complex, and a status-7 complex is monitored, not controlled."""
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nS 1 7\n"))
        self.assertEqual(f.n_controlled(), 0)

    def test_empty_and_unreadable_files_yield_errors_not_raises(self):
        with tempfile.TemporaryDirectory() as d:
            empty = ic.parse_iconst(write(d, "ICONST", "\n\n  \n"))
            unreadable = ic.parse_iconst(os.path.join(d, "does_not_exist"))
            directory = ic.parse_iconst(d)  # a directory path must not raise
        self.assertIn("ICONST_EMPTY", [x["code"] for x in empty.issues])
        self.assertIn("ICONST_UNREADABLE", [x["code"] for x in unreadable.issues])
        self.assertIn("ICONST_UNREADABLE", [x["code"] for x in directory.issues])

    def test_comment_lines_are_reported_not_eaten(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "# a comment\nR 1 2 0\n"))
        self.assertIn("ICONST_COMMENT_UNSUPPORTED",
                      [x["code"] for x in f.issues])
        self.assertEqual(len(f.lines), 1)

    def test_lowercase_flag_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "r 1 2 0\n"))
        self.assertIn("ICONST_FLAG_UNKNOWN", [x["code"] for x in f.issues])


vi = _load("validate_input", "scripts/validate_input.py")

# Orthogonal cell, easy hand-checked geometry.
# Atom 1 (0,0,0), atom 2 (1.0,0,0), atom 3 (0,1.5,0) in Angstrom.
GEOM_POSCAR = """\
geometry probe
1.0
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
H
3
Direct
0.00 0.00 0.00
0.10 0.00 0.00
0.00 0.15 0.00
"""


class TestIconstGeometry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.structure = vi.parse_poscar(write(self.tmp.name, "POSCAR", GEOM_POSCAR))

    def tearDown(self):
        self.tmp.cleanup()

    def test_distance(self):
        line = ic.IconstLine("R", [1, 2], 0, 1, "R 1 2 0")
        self.assertAlmostEqual(ic.evaluate_primitive(line, self.structure), 1.0, places=6)

    def test_angle_in_degrees(self):
        # 2-1-3 with apex at atom 1: x-axis vs y-axis = 90 degrees
        line = ic.IconstLine("A", [2, 1, 3], 0, 1, "A 2 1 3 0")
        self.assertAlmostEqual(ic.evaluate_primitive(line, self.structure), 90.0, places=4)

    def test_minimum_image_wraps_across_boundary(self):
        """Atoms at fractional 0.05 and 0.95 are 1.0 A apart through the
        boundary, not 9.0 A across the cell."""
        poscar = GEOM_POSCAR.replace(
            "0.00 0.00 0.00\n0.10 0.00 0.00", "0.05 0.00 0.00\n0.95 0.00 0.00")
        s = vi.parse_poscar(write(self.tmp.name, "POSCAR_wrap", poscar))
        line = ic.IconstLine("R", [1, 2], 0, 1, "R 1 2 0")
        self.assertAlmostEqual(ic.evaluate_primitive(line, s), 1.0, places=6)

    def test_torsion_sign_follows_iupac_clockwise(self):
        """IUPAC: viewed down B->C, clockwise from A to D is positive.
        A sticks out +y at B; D's perpendicular part is rotated 60 deg
        clockwise (toward +z when looking along +x) -> dihedral +60 deg."""
        poscar = GEOM_POSCAR.replace(
            "Direct\n"
            "0.00 0.00 0.00\n"
            "0.10 0.00 0.00\n"
            "0.00 0.15 0.00\n",
            "Direct\n"
            "0.00 0.10 0.00\n"
            "0.00 0.00 0.00\n"
            "0.10 0.00 0.00\n"
            "0.10 0.05 0.08660254\n",
        ).replace("H\n3\n", "H\n4\n")
        s = vi.parse_poscar(write(self.tmp.name, "POSCAR_torsion", poscar))
        line = ic.IconstLine("T", [1, 2, 3, 4], 0, 1, "T 1 2 3 4 0")
        self.assertAlmostEqual(ic.evaluate_primitive(line, s), 60.0, places=3)

    def test_minimum_image_refines_across_lattice_translations(self):
        """Per-component wrapping is only exact for near-orthogonal cells. In a
        gamma=120 deg hexagonal cell (the standard fcc(111)/Ru(0001) slab), the
        true minimum image of the fractional delta (-0.45, 0.45, 0) sits one
        lattice translation away: 1.2686 A, not 1.9486 A."""
        poscar = (
            "hex minimum-image probe\n"
            "1.0\n"
            "2.5 0.0 0.0\n"
            "-1.25 2.1650635094611296 0.0\n"
            "0.0 0.0 10.0\n"
            "H\n2\nDirect\n"
            "0.0 0.0 0.0\n"
            "0.55 0.45 0.0\n"
        )
        s = vi.parse_poscar(write(self.tmp.name, "POSCAR_hex", poscar))
        # Also pins the lattice row-vector convention of _cart on a
        # non-diagonal cell.
        self.assertAlmostEqual(ic._cart(s, 2)[0], 0.8125, places=9)
        self.assertAlmostEqual(ic._cart(s, 2)[1],
                               2.1650635094611296 * 0.45, places=9)
        line = ic.IconstLine("R", [1, 2], 0, 1, "R 1 2 0")
        self.assertAlmostEqual(ic.evaluate_primitive(line, s),
                               1.268574, places=3)

    def test_degenerate_torsion_raises_instead_of_zero(self):
        """Collinear i-j-k collapses n1 to zero; atan2(0, 0) is 0.0, which
        would silently masquerade as a valid 0 deg dihedral."""
        poscar = GEOM_POSCAR.replace(
            "Direct\n"
            "0.00 0.00 0.00\n"
            "0.10 0.00 0.00\n"
            "0.00 0.15 0.00\n",
            "Direct\n"
            "0.00 0.00 0.00\n"
            "0.10 0.00 0.00\n"
            "0.20 0.00 0.00\n"
            "0.30 0.00 0.00\n",
        ).replace("H\n3\n", "H\n4\n")
        s = vi.parse_poscar(write(self.tmp.name, "POSCAR_collinear", poscar))
        line = ic.IconstLine("T", [1, 2, 3, 4], 0, 1, "T 1 2 3 4 0")
        with self.assertRaises(ValueError):
            ic.evaluate_primitive(line, s)

    def test_evaluate_cv_ignores_monitored_non_v1_primitives(self):
        """A monitored (status 7) flag outside v1 geometry support must not
        block evaluation of the controlled coordinate."""
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nZ 3 7\n"))
        value, kind = ic.evaluate_cv(f, self.structure)
        self.assertAlmostEqual(value, 1.0, places=6)
        self.assertEqual(kind, "distance")

    def test_d_nonpositive_reference_raises_valueerror_not_zerodivision(self):
        """parse_iconst flags a non-positive D reference as an arity ERROR but
        keeps the line; the geometry layer must then fail with the module's
        ValueError contract, not a raw ZeroDivisionError."""
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nD -1.0 0\n"))
        self.assertIn("ICONST_ARITY", [x["code"] for x in f.issues])
        with self.assertRaises(ValueError):
            ic.evaluate_cv(f, self.structure)

    def test_evaluate_cv_zero_controlled_raises(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 7\n"))
        with self.assertRaises(ValueError):
            ic.evaluate_cv(f, self.structure)

    def test_s_combination_is_signed_sum(self):
        line = ic.IconstLine("S", [1.0, -1.0], 0, 3, "S 1 -1 0")
        self.assertAlmostEqual(ic.evaluate_complex(line, [1.0, 1.5]), -0.5, places=6)

    def test_d_coordination_number_uses_fixed_9_14_exponents(self):
        line = ic.IconstLine("D", [1.0], 0, 2, "D 1.0 0")
        # q/c = 2 -> (1-2^9)/(1-2^14) = 511/16383
        self.assertAlmostEqual(ic.evaluate_complex(line, [2.0]),
                               511.0 / 16383.0, places=9)

    def test_d_singularity_at_q_equals_c_uses_limit(self):
        """q/c == 1 is a 0/0 removable singularity; the limit is 9/14."""
        line = ic.IconstLine("D", [1.3], 0, 2, "D 1.3 0")
        self.assertAlmostEqual(ic.evaluate_complex(line, [1.3]), 9.0 / 14.0, places=9)

    def test_basis_kind_and_tolerance_selection(self):
        prim_r = [ic.IconstLine("R", [1, 2], 0, 1, "")]
        prim_a = [ic.IconstLine("A", [2, 1, 3], 0, 1, "")]
        s_line = ic.IconstLine("S", [1.0], 0, 2, "")
        d_line = ic.IconstLine("D", [1.0], 0, 2, "")
        self.assertEqual(ic.basis_kind(prim_r[0], prim_r), "distance")
        self.assertEqual(ic.basis_kind(prim_a[0], prim_a), "angle")
        self.assertEqual(ic.basis_kind(s_line, prim_r), "distance")
        self.assertEqual(ic.basis_kind(d_line, prim_r), "dimensionless")
        # An S over mixed bases has no comparable unit.
        mixed = [ic.IconstLine("R", [1, 2], 0, 1, ""),
                 ic.IconstLine("A", [2, 1, 3], 0, 2, "")]
        self.assertEqual(ic.basis_kind(ic.IconstLine("S", [1.0, 1.0], 0, 3, ""),
                                       mixed), "mixed")

    def test_evaluate_cv_picks_the_controlled_coordinate(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nR 1 3 0\nS 1 -1 0\n"))
        value, kind = ic.evaluate_cv(f, self.structure)
        self.assertAlmostEqual(value, 1.0 - 1.5, places=6)
        self.assertEqual(kind, "distance")

    def test_evaluate_cv_rejects_multiple_controlled_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            f = ic.parse_iconst(write(d, "ICONST", "R 1 2 0\nR 1 3 0\n"))
        with self.assertRaises(ValueError):
            ic.evaluate_cv(f, self.structure)


MIN_SG_INCAR = """\
IBRION = 0
MDALGO = 2
POTIM = 1.0
NSW = 6000
TEBEG = 330
INCREM = -1.333E-4
LBLUEOUT = .TRUE.
NCORE = 4
ISYM = 0
"""


class TestSlowgrowthTaskInference(unittest.TestCase):
    def test_incar_with_increm_infers_slowgrowth_not_md(self):
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(d, "INCAR", MIN_SG_INCAR))
        self.assertEqual(vi.infer_task(params), "slowgrowth")

    def test_lblueout_alone_also_infers_slowgrowth(self):
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(
                d, "INCAR", "IBRION = 0\nMDALGO = 2\nLBLUEOUT = .TRUE.\n"))
        self.assertEqual(vi.infer_task(params), "slowgrowth")

    def test_plain_md_still_infers_md(self):
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(
                d, "INCAR", "IBRION = 0\nMDALGO = 3\nPOTIM = 1.0\n"))
        self.assertEqual(vi.infer_task(params), "md")

    def test_task_keyword_maps_directory_name(self):
        self.assertEqual(vi.task_hint_from_name("21_Pt100_NH3OH_slowgrowth"),
                         "slowgrowth")

    def test_validate_accepts_iconst_context(self):
        """validate() must take an iconst context without breaking positional
        callers already in the suite."""
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(d, "INCAR", MIN_SG_INCAR))
            f = ic.parse_iconst(write(d, "ICONST", ICONST_SINGLE_BOND))
        findings = vi.validate(params, None, None, False, "slowgrowth",
                               iconst=f)
        self.assertTrue(all(hasattr(x, "code") for x in findings))

    def test_validate_one_threads_iconst_path(self):
        """validate_one must accept iconst_path and parse it into the context."""
        with tempfile.TemporaryDirectory() as d:
            incar = write(d, "INCAR", MIN_SG_INCAR)
            iconst = write(d, "ICONST", ICONST_SINGLE_BOND)
            params, findings = vi.validate_one(incar, iconst_path=iconst)
        self.assertIsNotNone(params)
        codes = [x.code for x in findings]
        self.assertNotIn("SG_ICONST_MISSING", codes)


def sg_findings(incar_text, iconst_text=None, poscar_text=None, task=None):
    """Validate an INCAR (+optional ICONST/POSCAR) and return finding codes."""
    with tempfile.TemporaryDirectory() as d:
        incar = write(d, "INCAR", incar_text)
        iconst = (write(d, "ICONST", iconst_text)
                  if iconst_text is not None else None)
        poscar = write(d, "POSCAR", poscar_text) if poscar_text else None
        _params, findings = vi.validate_one(
            incar, poscar_path=poscar, iconst_path=iconst, task=task)
    return [x.code for x in findings], findings


GROWTH_INCAR = MIN_SG_INCAR
EQUIL_INCAR = """\
IBRION = 0
MDALGO = 2
POTIM = 1.0
NSW = 2000
TEBEG = 330
INCREM = 0
LBLUEOUT = .FALSE.
NCORE = 4
ISYM = 0
"""


class TestSlowgrowthRules(unittest.TestCase):
    def test_explicit_task_without_iconst_is_error(self):
        codes, _ = sg_findings(GROWTH_INCAR, task="slowgrowth")
        self.assertIn("SG_ICONST_MISSING", codes)

    def test_inferred_task_without_iconst_is_warn_not_error(self):
        """A standalone template must not hard-fail: inferred slowgrowth with no
        ICONST context is INCOMPLETE, not ERROR."""
        codes, findings = sg_findings(GROWTH_INCAR)
        self.assertIn("SG_ICONST_CONTEXT_MISSING", codes)
        self.assertNotIn("SG_ICONST_MISSING", codes)
        levels = {x.code: x.level for x in findings}
        self.assertEqual(levels["SG_ICONST_CONTEXT_MISSING"], vi.WARN)

    def test_increm_arity_uses_n_controlled_not_row_count(self):
        """rev2 core fix: three ICONST rows feeding one S coordinate need
        exactly ONE INCREM value. This must PASS."""
        codes, _ = sg_findings(GROWTH_INCAR, ICONST_TRANSFER, task="slowgrowth")
        self.assertNotIn("SG_INCREM_ARITY", codes)

    def test_increm_arity_fires_on_genuine_mismatch(self):
        two_vals = GROWTH_INCAR.replace("INCREM = -1.333E-4",
                                        "INCREM = -1.333E-4 -1.0E-4")
        codes, _ = sg_findings(two_vals, ICONST_TRANSFER, task="slowgrowth")
        self.assertIn("SG_INCREM_ARITY", codes)

    def test_increm_comma_style_fails_loudly(self):
        """Comma-separated INCREM is ordinary INCAR style that VASP accepts;
        get_num_list would silently drop the comma tokens and green-light a
        wrong arity."""
        comma = GROWTH_INCAR.replace("INCREM = -1.333E-4",
                                     "INCREM = -1.333E-4, -1.0E-4")
        codes, _ = sg_findings(comma, ICONST_TRANSFER, task="slowgrowth")
        self.assertIn("SG_INCREM_UNPARSEABLE", codes)

    def test_increm_pure_junk_is_not_misdiagnosed_as_equilibration(self):
        junk = GROWTH_INCAR.replace("INCREM = -1.333E-4", "INCREM = junk")
        codes, findings = sg_findings(junk, ICONST_TRANSFER, task="slowgrowth")
        self.assertIn("SG_INCREM_UNPARSEABLE", codes)
        self.assertNotIn("SG_INCREM_ALL_ZERO", codes)

    def test_ibrion_must_be_zero(self):
        bad = GROWTH_INCAR.replace("IBRION = 0", "IBRION = 2")
        codes, _ = sg_findings(bad, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_IBRION_NOT_MD", codes)

    def test_langevin_thermostat_rejected(self):
        bad = GROWTH_INCAR.replace("MDALGO = 2", "MDALGO = 3")
        codes, findings = sg_findings(bad, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_MDALGO_UNSUPPORTED", codes)
        msg = next(x.message for x in findings if x.code == "SG_MDALGO_UNSUPPORTED")
        self.assertIn("Langevin", msg)

    def test_mdalgo_unset_warns(self):
        bad = GROWTH_INCAR.replace("MDALGO = 2\n", "")
        codes, _ = sg_findings(bad, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_MDALGO_UNSET", codes)

    def test_mdalgo_andersen_is_supported(self):
        text = GROWTH_INCAR.replace("MDALGO = 2", "MDALGO = 1")
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertNotIn("SG_MDALGO_UNSUPPORTED", codes)
        self.assertNotIn("SG_MDALGO_UNSET", codes)

    def test_growth_without_lblueout_is_error(self):
        bad = GROWTH_INCAR.replace("LBLUEOUT = .TRUE.\n", "")
        codes, _ = sg_findings(bad, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_LBLUEOUT_MISSING", codes)

    def test_equil_stage_zero_increm_warns_and_lblueout_off_is_clean(self):
        codes, _ = sg_findings(EQUIL_INCAR, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_INCREM_ALL_ZERO", codes)
        self.assertNotIn("SG_LBLUEOUT_MISSING", codes)
        self.assertNotIn("SG_LBLUEOUT_EQUIL", codes)

    def test_equil_stage_with_lblueout_on_is_info(self):
        text = EQUIL_INCAR.replace("LBLUEOUT = .FALSE.", "LBLUEOUT = .TRUE.")
        codes, findings = sg_findings(text, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("SG_LBLUEOUT_EQUIL", codes)
        levels = {x.code: x.level for x in findings}
        self.assertEqual(levels["SG_LBLUEOUT_EQUIL"], vi.INFO)

    def test_no_controlled_coordinate_in_growth_stage(self):
        codes, _ = sg_findings(GROWTH_INCAR, "R 1 5 7\n", task="slowgrowth")
        self.assertIn("SG_NO_CONTROLLED_COORD", codes)
        self.assertNotIn("SG_INCREM_ARITY", codes)

    def test_atom_index_out_of_range(self):
        codes, _ = sg_findings(GROWTH_INCAR, "R 1 999 0\n",
                               poscar_text=GEOM_POSCAR, task="slowgrowth")
        self.assertIn("SG_ICONST_INDEX_RANGE", codes)

    def test_parser_arity_surfaces_as_sg_code(self):
        codes, _ = sg_findings(GROWTH_INCAR, "R 1 0\n", task="slowgrowth")
        self.assertIn("SG_ICONST_ARITY", codes)

    def test_flag_and_status_coverage_surface_as_sg_codes(self):
        flag_codes, _ = sg_findings(GROWTH_INCAR, "M 1 2 3 0\n", task="slowgrowth")
        status_codes, _ = sg_findings(GROWTH_INCAR, "R 1 2 5\nR 3 4 0\n",
                                      task="slowgrowth")
        self.assertIn("SG_ICONST_FLAG_COVERAGE", flag_codes)
        self.assertIn("SG_ICONST_STATUS_COVERAGE", status_codes)

    def test_clean_growth_setup_has_no_sg_errors(self):
        _codes, findings = sg_findings(GROWTH_INCAR, ICONST_TRANSFER,
                                       task="slowgrowth")
        sg_errors = [x for x in findings
                     if x.level == vi.ERROR and x.code.startswith("SG_")]
        self.assertEqual(sg_errors, [], f"unexpected SG errors: {sg_errors}")

    def test_lowercase_tag_still_infers_slowgrowth(self):
        """parse_incar upper-cases keys; pin that the SG inference relies on
        it and survives a lowercase INCAR."""
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(
                d, "INCAR", "ibrion = 0\nmdalgo = 2\nincrem = 3.74E-4\n"))
        self.assertEqual(vi.infer_task(params), "slowgrowth")

    def test_legacy_positional_validate_call_still_works(self):
        """The 6-positional call shape predates the iconst kwargs; lock it."""
        with tempfile.TemporaryDirectory() as d:
            params = vi.parse_incar(write(
                d, "INCAR", "IBRION = 0\nMDALGO = 2\nINCREM = 1E-4\n"))
        findings = vi.validate(params, None, None, False, "slowgrowth", False)
        self.assertTrue(all(hasattr(x, "code") for x in findings))

    def test_nonexistent_iconst_path_warns(self):
        with tempfile.TemporaryDirectory() as d:
            incar = write(d, "INCAR", MIN_SG_INCAR)
            _params, findings = vi.validate_one(
                incar, iconst_path=os.path.join(d, "NO_SUCH_ICONST"))
        codes = [x.code for x in findings]
        self.assertIn("SG_ICONST_UNREADABLE_PATH", codes)
        self.assertNotIn("SG_ICONST_MISSING", codes)

    def test_family_boundary_is_documented(self):
        """Rules outside the interface-AIMD family must NOT fire for
        slowgrowth. ISMEAR=-5 is equally dubious on an MD run, but the
        smearing gate deliberately covers only relax/md today — pin that
        boundary so widening it cannot happen silently."""
        # GROWTH_INCAR carries no ISMEAR line, so append -5 explicitly (a
        # replace() against "ISMEAR = 0" would be a silent no-op here).
        text = GROWTH_INCAR + "ISMEAR = -5\n"
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertNotIn("TETRA_ON_RELAX", codes)


# Pt slab + water + adsorbate: triggers the interface-AIMD rule family.
PT_WATER_SLAB = """\
Pt(100) + H2O
1.0
5.6 0.0 0.0
0.0 5.6 0.0
0.0 0.0 40.0
Pt O H
4 1 2
Direct
0.00 0.00 0.20
0.50 0.00 0.20
0.00 0.50 0.20
0.50 0.50 0.20
0.25 0.25 0.30
0.30 0.25 0.32
0.20 0.25 0.32
"""


class TestSlowgrowthInheritsMdFamily(unittest.TestCase):
    def test_timestep_cap_applies_with_hydrogen(self):
        text = GROWTH_INCAR.replace("POTIM = 1.0", "POTIM = 2.0")
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertIn("MD_TIMESTEP_CAP", codes)

    def test_mixing_trio_warning_applies(self):
        codes, _ = sg_findings(GROWTH_INCAR, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertIn("MD_MIXING_METAL_WATER", codes)

    def test_vacuum_sloshing_warning_applies(self):
        text = GROWTH_INCAR + "LDIPOL = .TRUE.\nIDIPOL = 3\nAMIX = 0.02\n"
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertIn("MD_VACUUM_SLOSHING", codes)

    def test_nbands_drift_and_ncore_rules_apply(self):
        text = GROWTH_INCAR.replace("NCORE = 4\n", "")
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertIn("MD_NBANDS_DRIFT", codes)
        self.assertIn("MD_NCORE_UNSET", codes)

    def test_isif_stress_warning_applies(self):
        text = GROWTH_INCAR + "ISIF = 2\n"
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("MD_ISIF_STRESS", codes)

    def test_isym_must_be_zero(self):
        text = GROWTH_INCAR.replace("ISYM = 0", "ISYM = 2")
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND, task="slowgrowth")
        self.assertIn("MD_ISYM", codes)

    def test_oxide_encut_warning_applies(self):
        """O present + low ENCUT is an md-family warning; SG runs on O-containing
        interfaces need it just as much."""
        text = GROWTH_INCAR + "ENCUT = 400\n"
        codes, _ = sg_findings(text, ICONST_SINGLE_BOND,
                               poscar_text=PT_WATER_SLAB, task="slowgrowth")
        self.assertIn("OXIDE_ENCUT_LOW", codes)


class TestExamplesRunnerAndCli(unittest.TestCase):
    def _sg_example_dir(self, tmp):
        d = os.path.join(tmp, "21_Pt100_NH3OH_slowgrowth")
        os.makedirs(d)
        write(d, "POSCAR", GEOM_POSCAR)
        write(d, "KPOINTS", "Automatic mesh\n0\nGamma\n1 1 1\n0.0 0.0 0.0\n")
        write(d, "ICONST", ICONST_SINGLE_BOND)
        write(d, "INCAR_growth", GROWTH_INCAR)
        write(d, "INCAR_equil", EQUIL_INCAR)
        return d

    def test_runner_validates_every_incar_stage_file(self):
        """Regression guard: both stage files must appear as labels. Before the
        fix the dir was silently treated as a KPOINTS-only example."""
        with tempfile.TemporaryDirectory() as tmp:
            self._sg_example_dir(tmp)
            results, _meta = vi.run_examples_dir_full(tmp)
        labels = set(results)
        self.assertIn("21_Pt100_NH3OH_slowgrowth/INCAR_growth", labels)
        self.assertIn("21_Pt100_NH3OH_slowgrowth/INCAR_equil", labels)

    def test_runner_feeds_iconst_context_so_no_context_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._sg_example_dir(tmp)
            results, _meta = vi.run_examples_dir_full(tmp)
        growth = [x.code for x in
                  results["21_Pt100_NH3OH_slowgrowth/INCAR_growth"]]
        self.assertNotIn("SG_ICONST_CONTEXT_MISSING", growth)
        self.assertNotIn("SG_ICONST_MISSING", growth)

    def test_plain_incar_directory_still_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "01_plain_relax")
            os.makedirs(d)
            write(d, "POSCAR", GEOM_POSCAR)
            write(d, "INCAR", "IBRION = 2\nNSW = 50\nENCUT = 400\n")
            results, _meta = vi.run_examples_dir_full(tmp)
        self.assertIn("01_plain_relax/INCAR", set(results))

    def test_cli_accepts_iconst_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            incar = write(tmp, "INCAR", GROWTH_INCAR)
            iconst = write(tmp, "ICONST", ICONST_TRANSFER)
            proc = subprocess.run(
                [PY, str(ROOT / "scripts" / "validate_input.py"),
                 "--incar", incar, "--iconst", iconst,
                 "--task", "slowgrowth", "--json"],
                capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertNotIn("SG_ICONST_MISSING", proc.stdout)

    def test_cli_exit_code_1_on_sg_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = write(tmp, "INCAR", GROWTH_INCAR.replace("MDALGO = 2",
                                                           "MDALGO = 3"))
            iconst = write(tmp, "ICONST", ICONST_SINGLE_BOND)
            proc = subprocess.run(
                [PY, str(ROOT / "scripts" / "validate_input.py"),
                 "--incar", bad, "--iconst", iconst, "--task", "slowgrowth"],
                capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("SG_MDALGO_UNSUPPORTED", proc.stdout)


class TestSlowgrowthTemplate(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "base_templates" / "vasp_slowgrowth.incar"
        self.index = __import__("json").loads(
            (ROOT / "base_templates" / "INDEX.json").read_text(encoding="utf-8"))

    def test_template_exists_and_is_routed(self):
        self.assertTrue(self.path.exists())
        entry = self.index["tasks"]["vasp"]["slowgrowth"]
        self.assertEqual(entry["template"], "vasp_slowgrowth.incar")

    def test_template_carries_the_sg_tags(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("IBRION   = 0", text)
        self.assertIn("MDALGO   = 2", text)
        self.assertIn("LBLUEOUT = .TRUE.", text)
        # INCREM stays a commented placeholder: the helper activates it with the
        # computed value, so the shipped template is never a runnable growth run
        # with a guessed rate.
        self.assertRegex(text, r"(?m)^#\s*INCREM\s*=")

    def test_template_validates_without_sg_errors(self):
        with tempfile.TemporaryDirectory() as d:
            import shutil
            incar = os.path.join(d, "INCAR")
            shutil.copyfile(self.path, incar)
            _params, findings = vi.validate_one(incar)
        errors = [x for x in findings if x.level == vi.ERROR]
        self.assertEqual(errors, [], f"template has ERRORs: {errors}")

    def test_template_modifiers_match_the_md_family(self):
        entry = self.index["tasks"]["vasp"]["slowgrowth"]
        self.assertEqual(set(entry["modifiers"]),
                         set(self.index["tasks"]["vasp"]["md"]["modifiers"]))


# NH3 + OH on a tiny Pt patch. Atom order: Pt(1-4) N(5) H(6,7,8) O(9) H(10).
# H7 is pre-oriented toward O9 (~1.7 A); H6/H8 point away.
NH3_OH_POSCAR = """\
Pt(100) + NH3 + OH probe
1.0
8.0 0.0 0.0
0.0 8.0 0.0
0.0 0.0 24.0
Pt N H O
4 1 3 1
Cartesian
0.0 0.0 5.0
4.0 0.0 5.0
0.0 4.0 5.0
4.0 4.0 5.0
2.0 2.0 7.0
1.1 2.0 7.4
2.6 2.0 8.0
2.0 1.1 7.4
3.0 2.0 9.4
"""

HELPER = str(ROOT / "scripts" / "iconst_helper.py")


def run_helper(*args):
    return subprocess.run([PY, HELPER, *args], capture_output=True, text=True)


class TestHelperCandidates(unittest.TestCase):
    def test_lists_indices_with_real_distances_to_acceptor(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            proc = run_helper("candidates", "--poscar", poscar,
                              "--species", "H", "--acceptor", "9")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        for idx in ("6", "7", "8"):
            self.assertIn(idx, out)
        # H7 (2.6, 2.0, 8.0) to O9 (3.0, 2.0, 9.4): sqrt(0.16 + 1.96) = 1.456 A,
        # the closest H (H6 is 2.759 A, H8 is 2.410 A).
        self.assertRegex(out, r"\b7\b.*1\.45")
        self.assertIn("SUGGESTION", out)
        self.assertRegex(out.split("SUGGESTION")[1], r"\b7\b")

    def test_explicit_indices_restrict_the_table(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            proc = run_helper("candidates", "--poscar", poscar,
                              "--indices", "6", "7", "--acceptor", "9")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [l for l in proc.stdout.splitlines() if l.strip().startswith(("6", "7", "8"))]
        self.assertTrue(any(l.strip().startswith("6") for l in rows))
        self.assertFalse(any(l.strip().startswith("8") for l in rows))

    def test_species_without_acceptor_still_lists_atoms(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            proc = run_helper("candidates", "--poscar", poscar, "--species", "N")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("5", proc.stdout)

    def test_unknown_species_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            proc = run_helper("candidates", "--poscar", poscar, "--species", "Zr")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Zr", proc.stderr + proc.stdout)

    def test_acceptor_out_of_range_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            proc = run_helper("candidates", "--poscar", poscar,
                              "--species", "H", "--acceptor", "999")
        self.assertEqual(proc.returncode, 1)

    def test_bonded_candidate_is_excluded_from_suggestion(self):
        """An H bonded to the acceptor (H9 at sqrt(0.8^2+0.8^2) = 1.131 A
        from O10) must not be suggested as the transferring atom; the ranking
        falls to the best non-bonded candidate."""
        poscar_text = """\
Pt(100) + NH3 + OH (+ its own H) probe
1.0
8.0 0.0 0.0
0.0 8.0 0.0
0.0 0.0 24.0
Pt N H O
4 1 4 1
Cartesian
0.0 0.0 5.0
4.0 0.0 5.0
0.0 4.0 5.0
4.0 4.0 5.0
2.0 2.0 7.0
1.1 2.0 7.4
2.6 2.0 8.0
2.0 1.1 7.4
3.0 2.0 9.4
2.2 2.0 10.2
"""
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", poscar_text)
            proc = run_helper("candidates", "--poscar", poscar,
                              "--species", "H", "--acceptor", "10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("excluded from the ranking", proc.stdout)
        self.assertRegex(proc.stdout, r"\b9\b.*1\.131")
        self.assertRegex(proc.stdout.split("SUGGESTION")[1], r"\b7\b")
        self.assertNotIn("atom 9 is closest", proc.stdout)

    def test_all_bonded_candidates_yield_no_suggestion(self):
        """Scanning the H of a water molecule against its own O: every
        candidate is bonded; the tool must say so, not pick one."""
        water = """\
water probe
1.0
8.0 0.0 0.0
0.0 8.0 0.0
0.0 0.0 8.0
O H
1 2
Cartesian
4.0 4.0 4.0
4.8 4.0 4.6
3.2 4.0 4.6
"""
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", water)
            proc = run_helper("candidates", "--poscar", poscar,
                              "--species", "H", "--acceptor", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("every candidate is bonded", proc.stdout)
        self.assertNotIn("is closest to the acceptor", proc.stdout)


def incar_delta(params_a, params_b):
    """Tag names whose presence or value differs between two parsed INCARs.

    Comparing parsed tags instead of raw lines keeps the stage check meaningful:
    turning the commented INCREM placeholder into a live tag shifts every
    subsequent line, so a positional line diff would cascade.
    """
    keys = set(params_a) | set(params_b)
    return {k for k in keys if params_a.get(k) != params_b.get(k)}


class TestHelperRender(unittest.TestCase):
    def _render(self, d, *extra, xi="-1.0", xf="1.0", nsw="6000"):
        poscar = write(d, "POSCAR", NH3_OH_POSCAR)
        out = os.path.join(d, "ICONST")
        return run_helper("render", "--poscar", poscar,
                          "--cv", "R 5 7", "--cv", "R 9 7", "--cv", "S 1 -1",
                          "--xi", xi, "--xf", xf, "--nsw", nsw,
                          "--out", out, *extra), out

    def test_writes_iconst_and_reports_increm(self):
        with tempfile.TemporaryDirectory() as d:
            proc, out = self._render(d)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            text = open(out, encoding="utf-8").read()
        self.assertEqual(text.split("\n")[0].split(), ["R", "5", "7", "0"])
        self.assertIn("S 1 -1 0", text)
        # (1.0 - (-1.0)) / 6000 = 3.333e-4
        self.assertRegex(proc.stdout, r"INCREM\s*=\s*3\.333")

    def test_reports_per_ps_rate_for_comparison_with_literature(self):
        with tempfile.TemporaryDirectory() as d:
            proc, _ = self._render(d, "--potim", "1.0")
        self.assertIn("/ps", proc.stdout)

    def test_negative_increm_when_cv_decreases(self):
        with tempfile.TemporaryDirectory() as d:
            proc, _ = self._render(d, xi="1.0", xf="-1.0")
        self.assertRegex(proc.stdout, r"INCREM\s*=\s*-3\.333")
        self.assertIn("decreas", proc.stdout.lower())

    def test_initial_value_mismatch_warns_but_still_writes(self):
        """NH3_OH_POSCAR gives d(N5-H7) = sqrt(0.36+1.0) = 1.1662 A and
        d(O9-H7) = sqrt(0.16+1.96) = 1.4560 A, so xi = -0.2898 A. The default
        --xi of -1.0 is off by 0.71 A > 0.1 A -> WARN, file still written."""
        with tempfile.TemporaryDirectory() as d:
            proc, out = self._render(d)
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(os.path.exists(out))
        self.assertIn("WARNING", proc.stdout)
        self.assertIn("0.1", proc.stdout)

    def test_initial_value_match_is_silent_about_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            proc, _ = self._render(d, xi="-0.29")
        self.assertNotIn("does not match", proc.stdout)

    def test_angle_cv_uses_degree_tolerance(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            out = os.path.join(d, "ICONST")
            proc = run_helper("render", "--poscar", poscar,
                             "--cv", "A 6 5 7", "--xi", "0", "--xf", "10",
                             "--nsw", "1000", "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("deg", proc.stdout)

    def test_bad_atom_index_exits_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            out = os.path.join(d, "ICONST")
            proc = run_helper("render", "--poscar", poscar, "--cv", "R 5 999",
                             "--xi", "1", "--xf", "2", "--nsw", "100",
                             "--out", out)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(out))

    def test_bad_arity_exits_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            poscar = write(d, "POSCAR", NH3_OH_POSCAR)
            out = os.path.join(d, "ICONST")
            proc = run_helper("render", "--poscar", poscar, "--cv", "R 5",
                             "--xi", "1", "--xf", "2", "--nsw", "100",
                             "--out", out)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(out))

    def test_emit_incar_derives_both_stages_from_one_template(self):
        with tempfile.TemporaryDirectory() as d:
            growth = os.path.join(d, "INCAR_growth")
            equil = os.path.join(d, "INCAR_equil")
            proc, _ = self._render(
                d, "--emit-incar",
                "--template", str(ROOT / "base_templates" / "vasp_slowgrowth.incar"),
                "--incar-growth", growth, "--incar-equil", equil)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            g = open(growth, encoding="utf-8").read()
            e = open(equil, encoding="utf-8").read()
            gp = vi.parse_incar(growth)
            ep = vi.parse_incar(equil)
        self.assertRegex(g, r"(?m)^INCREM\s*=\s*3\.333")
        self.assertRegex(g, r"(?m)^LBLUEOUT\s*=\s*\.TRUE\.")
        self.assertRegex(e, r"(?m)^#\s*INCREM\s*=")
        self.assertRegex(e, r"(?m)^LBLUEOUT\s*=\s*\.FALSE\.")
        # Compare parsed tags, not raw lines: activating the commented INCREM
        # placeholder shifts every following line by one, so a zip of
        # non-comment lines would report a cascade of false differences.
        self.assertEqual(incar_delta(gp, ep), {"INCREM", "LBLUEOUT"})

    def test_emitted_stages_pass_the_validator(self):
        with tempfile.TemporaryDirectory() as d:
            growth = os.path.join(d, "INCAR_growth")
            equil = os.path.join(d, "INCAR_equil")
            _proc, out = self._render(
                d, "--emit-incar",
                "--template", str(ROOT / "base_templates" / "vasp_slowgrowth.incar"),
                "--incar-growth", growth, "--incar-equil", equil)
            for path in (growth, equil):
                _p, findings = vi.validate_one(
                    path, poscar_path=os.path.join(d, "POSCAR"),
                    iconst_path=out, task="slowgrowth")
                errors = [x for x in findings if x.level == vi.ERROR]
                self.assertEqual(errors, [], f"{path}: {errors}")


class TestGoldenExample(unittest.TestCase):
    DIR = ROOT / "examples" / "21_Pt100_NH3OH_slowgrowth"

    def test_ships_all_six_files(self):
        for name in ("POSCAR", "KPOINTS", "ICONST", "INCAR_equil",
                     "INCAR_growth", "README.md"):
            self.assertTrue((self.DIR / name).exists(), f"missing {name}")

    def test_vacuum_is_inside_the_verified_window(self):
        s = vi.parse_poscar(str(self.DIR / "POSCAR"))
        gap = max(s.vacuum_gaps().values())
        self.assertGreater(gap, 15.0)
        self.assertLess(gap, 17.0)

    def test_transferring_hydrogen_is_the_closest_to_the_acceptor(self):
        """The suggestion machinery must have an unambiguous winner: H18 sits
        ~1.76 A from O22 while the other NH3 hydrogens are > 2.4 A away."""
        s = vi.parse_poscar(str(self.DIR / "POSCAR"))
        d = {i: ic._norm(ic._min_image_vector(s, i, 22)) for i in (18, 19, 20)}
        self.assertLess(d[18], 1.9)
        self.assertGreater(min(d[19], d[20]), 2.3)

    def test_cv_initial_value_matches_the_declared_xi(self):
        s = vi.parse_poscar(str(self.DIR / "POSCAR"))
        f = ic.parse_iconst(str(self.DIR / "ICONST"))
        value, kind = ic.evaluate_cv(f, s)
        self.assertEqual(kind, "distance")
        self.assertAlmostEqual(value, -0.736, delta=0.05)

    def test_iconst_defines_exactly_one_controlled_parameter(self):
        f = ic.parse_iconst(str(self.DIR / "ICONST"))
        self.assertEqual([x["code"] for x in f.issues], [])
        self.assertEqual(f.n_controlled(), 1)

    def test_both_stages_validate_with_zero_errors(self):
        for stage in ("INCAR_equil", "INCAR_growth"):
            _p, findings = vi.validate_one(
                str(self.DIR / stage),
                poscar_path=str(self.DIR / "POSCAR"),
                kpoints_path=str(self.DIR / "KPOINTS"),
                iconst_path=str(self.DIR / "ICONST"),
                task="slowgrowth")
            errors = [x for x in findings if x.level == vi.ERROR]
            self.assertEqual(errors, [], f"{stage}: {errors}")

    def test_growth_stage_ships_no_avoidable_interface_warnings(self):
        """A golden example must not demonstrate the mistakes the skill warns
        about. ENCUT_NOT_VERIFIED is unavoidable (no POTCAR is distributed);
        every md-family interface warning is avoidable and must be absent."""
        _p, findings = vi.validate_one(
            str(self.DIR / "INCAR_growth"),
            poscar_path=str(self.DIR / "POSCAR"),
            kpoints_path=str(self.DIR / "KPOINTS"),
            iconst_path=str(self.DIR / "ICONST"),
            task="slowgrowth")
        warns = {x.code for x in findings if x.level == vi.WARN}
        avoidable = {
            "MD_MIXING_METAL_WATER",   # AMIX/BMIX/AMIN trio is set
            "MD_NBANDS_DRIFT",         # NBANDS is pinned
            "MD_NCORE_UNSET",          # NCORE = 4
            "MD_VACUUM_SLOSHING",      # vacuum is 16.3 A, inside 15-17
            "MD_ISIF_STRESS",          # ISIF is absent
            "MD_ISYM",                 # ISYM = 0
            "SG_MDALGO_UNSET",         # MDALGO = 2
            "SG_INCREM_ALL_ZERO",      # growth stage has a non-zero INCREM
            "SG_ICONST_CONTEXT_MISSING",
            "SG_ICONST_FLAG_COVERAGE",
            "SG_ICONST_STATUS_COVERAGE",
        }
        self.assertEqual(warns & avoidable, set(),
                         f"golden example ships avoidable warnings: "
                         f"{sorted(warns & avoidable)}")

    def test_only_the_stage_tags_differ_between_the_two_incars(self):
        """The two stages must be the same calculation apart from the growth
        switches, so a parameter fixed in one stage cannot silently drift in the
        other. SYSTEM differs because it names the stage."""
        gp = vi.parse_incar(str(self.DIR / "INCAR_growth"))
        ep = vi.parse_incar(str(self.DIR / "INCAR_equil"))
        self.assertEqual(incar_delta(gp, ep),
                         {"INCREM", "LBLUEOUT", "SYSTEM"})

    def test_candidates_suggestion_points_at_the_transferring_hydrogen(self):
        """On the golden geometry the helper must suggest H18 (the NH3
        hydrogen pre-oriented toward the OH oxygen) - not the OH's own
        hydrogen, which is bonding-distance to O22 and gets excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_helper("candidates",
                              "--poscar", str(self.DIR / "POSCAR"),
                              "--species", "H", "--acceptor", "22")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout.split("SUGGESTION")[1], r"\b18\b")

    def test_equil_stage_warning_set_is_pinned(self):
        """The README promises the equilibration stage's exact warning set;
        pin it so a future rule cannot add noise to the golden example
        unnoticed."""
        _p, findings = vi.validate_one(
            str(self.DIR / "INCAR_equil"),
            poscar_path=str(self.DIR / "POSCAR"),
            kpoints_path=str(self.DIR / "KPOINTS"),
            iconst_path=str(self.DIR / "ICONST"),
            task="slowgrowth")
        warns = {x.code for x in findings if x.level == vi.WARN}
        self.assertEqual(warns, {"ENCUT_NOT_VERIFIED", "SG_INCREM_ALL_ZERO"})


class TestDocumentation(unittest.TestCase):
    def test_references_vasp_documents_slow_growth(self):
        text = (ROOT / "references" / "vasp.md").read_text(encoding="utf-8")
        self.assertIn("Slow-growth AIMD", text)
        for tag in ("INCREM", "LBLUEOUT", "ICONST", "MDALGO"):
            self.assertIn(tag, text)
        # The record ids tie the practice numbers back to the paper kb.
        for rid in ("methods-0529", "methods-0008", "methods-0101"):
            self.assertIn(rid, text)

    def test_references_records_the_increm_sign_caveat(self):
        text = (ROOT / "references" / "vasp.md").read_text(encoding="utf-8")
        idx = text.find("Slow-growth AIMD")
        section = text[idx:idx + 6000]
        self.assertIn("sign", section.lower())

    def test_skill_md_routes_and_flags_slowgrowth(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("vasp_slowgrowth", text)
        self.assertIn("iconst_helper.py", text)
        self.assertIn("SG_INCREM_ARITY", text)
        self.assertIn("SG_MDALGO_UNSUPPORTED", text)

    def test_skill_md_red_flag_covers_the_arity_trap(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)complex coordinate.*status.*ignored")
