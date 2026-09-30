#!/usr/bin/env python3
"""
Regression tests for scripts/kpoints_helper.py.

Covers the two P0 fixes:
  - seekpath band paths must be in the ORIGINAL cell basis (get_path_orig_cell)
  - fcc/hexagonal must auto-select Gamma-centered meshes (spglib centering)

These tests need ase/spglib/seekpath; they are skipped cleanly when the
dependencies are not installed. Run:
    python -m unittest discover -s tests -v          # from the skill directory
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

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


@unittest.skipUnless(HAVE_DEPS, "ase/spglib/seekpath not installed")
class TestKpointsHelper(unittest.TestCase):
    # --- mesh formula: k_i = ceil(|b_i| / spacing), |b| includes 2 pi ---
    def test_mesh_formula_al(self):
        a, b, c = kph.read_poscar_lattice(str(EXAMPLES / "01_Al_FCC_bulk" / "POSCAR"))
        b1, b2, b3 = kph.reciprocal_vectors(a, b, c)
        k1, k2, k3 = kph.compute_kmesh(b1, b2, b3, 0.18)
        # |b| = 2*pi/4.0495 = 1.5516 A^-1; 1.5516/0.18 = 8.62 -> 9
        self.assertEqual((k1, k2, k3), (9, 9, 9))

    # --- scheme selection ---
    def test_fcc_auto_selects_gamma(self):
        """Regression: VASP wiki recommends Gamma meshes for fcc. AUTO must not
        return MP for a face-centered lattice."""
        self.assertEqual(kph.recommend_scheme("cubic", has_vacuum=False, centering="F"),
                         "Gamma")

    def test_hexagonal_auto_selects_gamma(self):
        self.assertEqual(kph.recommend_scheme("hexagonal"), "Gamma")

    def test_bcc_stays_mp(self):
        self.assertEqual(kph.recommend_scheme("cubic", has_vacuum=False, centering="I"), "MP")

    def test_vacuum_selects_gamma(self):
        self.assertEqual(kph.recommend_scheme("tetragonal", has_vacuum=True, centering="P"),
                         "Gamma")

    def test_bravais_centering_al_is_f(self):
        self.assertEqual(kph.bravais_centering(str(EXAMPLES / "01_Al_FCC_bulk" / "POSCAR")), "F")

    # --- band path coordinate basis (P0 regression) ---
    def test_band_path_uses_original_cell_basis(self):
        """Regression: for a CONVENTIONAL fcc cell, the Γ-X segment must land on
        a boundary point with an integer coordinate (X = (0,1,0) type), not the
        primitive-basis (0.5,0,0.5) that seekpath.get_path() would produce."""
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "KPOINTS")
            kph.seekpath_band(str(EXAMPLES / "04_Al_FCC_band" / "POSCAR"), 20, out)
            lines = [l.split() for l in Path(out).read_text().splitlines()[4:6]]
        coords = [[float(v) for v in line[:3]] for line in lines]
        gamma, x_point = coords
        self.assertEqual(gamma, [0.0, 0.0, 0.0])
        self.assertIn(1.0, [abs(v) for v in x_point],
                      msg=f"X point {x_point} is not in the conventional-cell basis "
                          "(expected an integer coordinate, e.g. (0,1,0))")


if __name__ == "__main__":
    unittest.main()
