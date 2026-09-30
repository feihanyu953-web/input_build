#!/usr/bin/env python3
"""
Audit-regression tests for scripts/kpoints_helper.py (group: kpoints).

Covers audit items P0-03 and P1-KPOINTS-01..04:
  - P1-KPOINTS-01: POSCAR scaling-factor parsing per the VASP spec
    (three per-axis factors; single negative = target total volume via
    |s|^(1/3); malformed input -> clear PoscarScalingError)
  - P1-KPOINTS-04: importing/running the module NEVER auto-installs; missing
    deps are only reported; --bootstrap-deps installs pinned versions
  - P1-KPOINTS-02: supercell band paths are refused by default
    (SupercellWarning / is_supercell), opt-in via --allow-supercell
  - P1-KPOINTS-03: missing seekpath.get_path_orig_cell fails closed
  - P0-03: K5 symprec tolerance sensitivity (default refuses, never a silent
    mC path; --symprec 1e-4 writes the hexagonal hP path); --lattice /
    POSCAR-comment declarations conflicting with the identification abort

Run (from the skill directory):
    python -m unittest discover -s tests -p "test_audit_kpoints.py" -v
"""

import contextlib
import importlib.util
import io
import math
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent  # skill directory

try:
    import ase  # noqa: F401
    import spglib  # noqa: F401
    import seekpath  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Importing kpoints_helper runs its dependency check at module level; only
# import it when the deps are present (then the check is a no-op).
kph = _load("kpoints_helper", "scripts/kpoints_helper.py") if HAVE_DEPS else None

EXAMPLES = ROOT / "examples"
SCRIPT = ROOT / "scripts" / "kpoints_helper.py"
K5_POSCAR = EXAMPLES / "02_MoS2_monolayer" / "POSCAR"

# Minimal POSCAR body: comment, {scaling}, 2x2x2 cubic cell, one atom.
_POSCAR_TEMPLATE = """\
{comment}
{scaling}
2.0 0.0 0.0
0.0 2.0 0.0
0.0 0.0 2.0
X
1
Direct
0.0 0.0 0.0
"""


def _write_poscar(path, scaling="1.0", comment="test"):
    Path(path).write_text(_POSCAR_TEMPLATE.format(comment=comment, scaling=scaling))


def _run_cli(*argv):
    """Run kpoints_helper.py as a subprocess; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT),
    )


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestScalingParsing(unittest.TestCase):
    """P1-KPOINTS-01: POSCAR line-2 scaling per VASP wiki (POSCAR)."""

    def test_three_scaling_factors_scale_each_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="1.0 2.0 3.0")
            a, b, c = kph.read_poscar_lattice(str(p))
        self.assertEqual(a, [2.0, 0.0, 0.0])
        self.assertEqual(b, [0.0, 4.0, 0.0])
        self.assertEqual(c, [0.0, 0.0, 6.0])

    def test_three_scaling_factors_scale_cartesian_components(self):
        """VASP's three factors scale x/y/z Cartesian components (columns),
        not the lattice vectors a/b/c (rows).  A diagonal cell cannot expose
        that distinction, so keep this non-orthogonal regression fixture."""
        content = """\
non-orthogonal
2.0 3.0 4.0
1.0 1.0 0.0
0.0 1.0 1.0
1.0 0.0 1.0
X
1
Direct
0.0 0.0 0.0
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            p.write_text(content)
            a, b, c = kph.read_poscar_lattice(str(p))
        self.assertEqual(a, [2.0, 3.0, 0.0])
        self.assertEqual(b, [0.0, 3.0, 4.0])
        self.assertEqual(c, [2.0, 0.0, 4.0])

    def test_negative_scaling_is_target_volume(self):
        """Raw cell volume = 8 A^3; scaling -1.0 must give a cell of volume
        1 A^3, i.e. each vector scaled by (1/8)^(1/3) = 0.5 — NOT by -1."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="-1.0")
            a, b, c = kph.read_poscar_lattice(str(p))
        for vec, expected in ((a, 1.0), (b, 1.0), (c, 1.0)):
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in vec)), expected)

    def test_single_positive_scaling_unchanged_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="2.5")
            a, b, c = kph.read_poscar_lattice(str(p))
        self.assertEqual(a, [5.0, 0.0, 0.0])

    def test_two_tokens_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="1.0 2.0")
            with self.assertRaises(kph.PoscarScalingError) as ctx:
                kph.read_poscar_lattice(str(p))
        self.assertIn("1 or 3 scaling factors", str(ctx.exception))

    def test_zero_factor_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="0.0")
            with self.assertRaises(kph.PoscarScalingError) as ctx:
                kph.read_poscar_lattice(str(p))
        self.assertIn("0 is invalid", str(ctx.exception))

    def test_non_numeric_factor_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="abc")
            with self.assertRaises(kph.PoscarScalingError) as ctx:
                kph.read_poscar_lattice(str(p))
        self.assertIn("not numeric", str(ctx.exception))

    def test_non_finite_factor_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="nan")
            with self.assertRaises(kph.PoscarScalingError) as ctx:
                kph.read_poscar_lattice(str(p))
        self.assertIn("finite", str(ctx.exception))

    def test_negative_inside_three_factor_form_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "POSCAR"
            _write_poscar(p, scaling="1.0 -2.0 3.0")
            with self.assertRaises(kph.PoscarScalingError) as ctx:
                kph.read_poscar_lattice(str(p))
        self.assertIn("must all be positive", str(ctx.exception))


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestNoAutoInstall(unittest.TestCase):
    """P1-KPOINTS-04: import must never install; bootstrap is explicit+pinned."""

    def test_missing_deps_report_only_and_never_call_installer(self):
        with mock.patch.object(kph, "_find_missing_deps", return_value=["ase"]), \
             mock.patch.object(kph.subprocess, "check_call") as installer:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    kph._check_deps_or_die()
        self.assertEqual(ctx.exception.code, 1)
        installer.assert_not_called()
        out = buf.getvalue()
        self.assertIn("Missing Python dependencies", out)
        self.assertIn("--bootstrap-deps", out)

    def test_bootstrap_deps_installs_only_missing_pinned(self):
        with mock.patch.object(kph, "_find_missing_deps",
                               side_effect=[["seekpath"], []]), \
             mock.patch.object(kph.subprocess, "check_call") as installer:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                kph._bootstrap_deps()
        installer.assert_called_once()
        cmd = installer.call_args[0][0]
        self.assertIn("seekpath==2.2.1", cmd)
        # unpinned name must not be what gets installed
        self.assertNotIn(cmd[-1], ["seekpath"])

    def test_bootstrap_deps_noop_when_all_present(self):
        with mock.patch.object(kph, "_find_missing_deps", return_value=[]), \
             mock.patch.object(kph.subprocess, "check_call") as installer:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                kph._bootstrap_deps()
        installer.assert_not_called()
        self.assertIn("nothing to install", buf.getvalue())


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestSupercellGuard(unittest.TestCase):
    """P1-KPOINTS-02: supercell band path refused unless explicitly allowed."""

    def _make_supercell_poscar(self, tmp):
        import numpy as np
        import ase.io
        from ase.build import make_supercell
        atoms = ase.io.read(str(K5_POSCAR))
        sc = make_supercell(atoms, np.array([[2, 0, 0], [0, 2, 0], [0, 0, 1]]))
        p = Path(tmp) / "POSCAR"
        ase.io.write(str(p), sc, format="vasp")
        return p

    def test_supercell_refused_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            poscar = self._make_supercell_poscar(tmp)
            out = Path(tmp) / "KPOINTS"
            with self.assertRaises(kph.KpointsHelperError) as ctx:
                kph.seekpath_band(str(poscar), 20, str(out), symprec=1e-4)
            self.assertIn("SUPERCELL", str(ctx.exception))
            self.assertIn("unfold", str(ctx.exception))
            self.assertFalse(out.exists(), "no KPOINTS may be written on refusal")

    def test_supercell_allowed_with_explicit_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            poscar = self._make_supercell_poscar(tmp)
            out = Path(tmp) / "KPOINTS"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                kph.seekpath_band(str(poscar), 20, str(out), symprec=1e-4,
                                  allow_supercell=True)
            self.assertTrue(out.exists())
            self.assertIn("--allow-supercell", buf.getvalue())


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestFallbackFailsClosed(unittest.TestCase):
    """P1-KPOINTS-03: no get_path_orig_cell -> refuse, no basis-mismatch write."""

    def test_missing_get_path_orig_cell_exits_without_writing(self):
        fake_seekpath = types.SimpleNamespace(
            get_path=lambda *a, **k: None,  # present but must NOT be used
            SupercellWarning=Warning,
        )
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(kph, "seekpath", fake_seekpath):
            out = Path(tmp) / "KPOINTS"
            with self.assertRaises(kph.KpointsHelperError) as ctx:
                kph.seekpath_band(str(K5_POSCAR), 20, str(out), symprec=1e-4)
            self.assertIn("seekpath < 2.0", str(ctx.exception))
            self.assertIn("fail closed", str(ctx.exception))
            self.assertFalse(out.exists(), "fallback must not write a file")


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestK5ToleranceRegression(unittest.TestCase):
    """P0-03: the K5 MoS2 monolayer POSCAR is classified mC at symprec 1e-5
    but hP at 1e-4. The helper must refuse at the default (never silently
    write the monoclinic path) and write the hexagonal path at 1e-4."""

    def test_default_symprec_refuses_in_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "KPOINTS"
            with self.assertRaises(kph.KpointsHelperError) as ctx:
                kph.seekpath_band(str(K5_POSCAR), 20, str(out))  # default 1e-5
            msg = str(ctx.exception)
            self.assertIn("SENSITIVE to symprec", msg)
            self.assertIn("mC", msg)
            self.assertIn("hP", msg)
            self.assertFalse(out.exists(), "must not silently write the mC path")

    def test_default_symprec_refuses_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "KPOINTS"
            r = _run_cli("--poscar", str(K5_POSCAR), "--band-structure",
                         "--npoints", "20", "-o", str(out))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("SENSITIVE to symprec", r.stdout)
            self.assertFalse(out.exists())

    def test_symprec_1e4_writes_hexagonal_hP_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "KPOINTS"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                kph.seekpath_band(str(K5_POSCAR), 20, str(out), symprec=1e-4,
                                  declared_lattice="hexagonal")
            self.assertTrue(out.exists())
            labels = [line.split()[-1] for line in
                      out.read_text().splitlines()[4:]]
        self.assertIn("K", labels, "hexagonal hP path must contain the K point")
        self.assertNotIn("C_2", labels, "monoclinic mC labels must not appear")

    def test_conflicting_lattice_declaration_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "KPOINTS"
            with self.assertRaises(kph.KpointsHelperError) as ctx:
                kph.seekpath_band(str(K5_POSCAR), 20, str(out), symprec=1e-4,
                                  declared_lattice="monoclinic")
            self.assertIn("conflicts", str(ctx.exception))
            self.assertFalse(out.exists())

    def test_comment_declaration_parsed(self):
        self.assertEqual(
            kph.parse_declared_lattice("MoS2 monolayer, hexagonal cell"),
            "hexagonal")
        self.assertIsNone(kph.parse_declared_lattice("MoS2_monolayer"))

    def test_poscar_comment_declaration_enforced_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            poscar = Path(tmp) / "POSCAR"
            body = K5_POSCAR.read_text().splitlines()
            body[0] = "monoclinic MoS2-like structure"
            poscar.write_text("\n".join(body) + "\n")
            out = Path(tmp) / "KPOINTS"
            r = _run_cli("--poscar", str(poscar), "--band-structure",
                         "--symprec", "1e-4", "-o", str(out))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("conflicts", r.stdout)
            self.assertFalse(out.exists())


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestSymprecPassthrough(unittest.TestCase):
    """P0-03: --symprec / --angle-tolerance must reach seekpath."""

    _CANNED = {
        "point_coords": {"GAMMA": (0.0, 0.0, 0.0), "X": (0.5, 0.0, 0.0)},
        "path": [("GAMMA", "X")],
        "spacegroup_number": 1,
        "spacegroup_international": "P1",
        "bravais_lattice": "aP",
        "is_supercell": False,
    }

    def test_symprec_and_angle_tolerance_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(kph.seekpath, "get_path_orig_cell",
                               return_value=dict(self._CANNED)) as gp:
            out = Path(tmp) / "KPOINTS"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                kph.seekpath_band(str(K5_POSCAR), 20, str(out),
                                  symprec=3e-4, angle_tolerance=2.0)
            self.assertTrue(out.exists())
            self.assertGreaterEqual(gp.call_count, 1)
            # first call: the requested symprec; probe call(s): symprec x10
            expected = [3e-4] + [3e-4 * 10.0] * (gp.call_count - 1)
            for call, exp in zip(gp.call_args_list, expected):
                self.assertAlmostEqual(call.kwargs["symprec"], exp)
                self.assertEqual(call.kwargs["angle_tolerance"], 2.0)


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestLatticeFamilyMapping(unittest.TestCase):
    """Supporting checks for the P0-03 declaration machinery."""

    def test_bravais_family_mapping(self):
        cases = {"cP": "cubic", "cF": "cubic", "cI": "cubic",
                 "tP": "tetragonal", "tI": "tetragonal",
                 "oP": "orthorhombic", "oF": "orthorhombic", "oC": "orthorhombic",
                 "mP": "monoclinic", "mC": "monoclinic",
                 "hP": "hexagonal", "hR": "rhombohedral",
                 "aP": "triclinic"}
        for symbol, family in cases.items():
            self.assertEqual(kph.bravais_family(symbol), family, symbol)

    def test_classify_lattice_detects_rhombohedral(self):
        # a=b=c, alpha=beta=gamma=60 deg (rhombohedral), previously "triclinic"
        s3 = math.sqrt(3.0)
        a = [1.0, 0.0, 0.0]
        b = [0.5, s3 / 2.0, 0.0]
        c = [0.5, 0.5 / s3, math.sqrt(2.0 / 3.0)]
        lat = kph.classify_lattice(a, b, c)
        self.assertEqual(lat[0], "rhombohedral")


if __name__ == "__main__":
    unittest.main()
