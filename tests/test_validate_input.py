#!/usr/bin/env python3
"""
Regression tests for scripts/validate_input.py (stdlib only, no third-party deps).

Run:
    python -m unittest discover -s tests -v          # from the skill directory
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PT_SLAB_H = """\
Pt(100) slab + H
1.0
5.6 0.0 0.0
0.0 5.6 0.0
0.0 0.0 20.0
Pt H
4 1
Direct
0.00 0.00 0.35
0.50 0.00 0.35
0.00 0.50 0.35
0.50 0.50 0.35
0.25 0.25 0.42
"""

CEO2 = """\
CeO2 fluorite
1.0
5.411 0.0 0.0
0.0 5.411 0.0
0.0 0.0 5.411
Ce O
4 8
Direct
0.00 0.00 0.00
0.00 0.50 0.50
0.50 0.00 0.50
0.50 0.50 0.00
0.25 0.25 0.25
0.25 0.75 0.75
0.75 0.25 0.75
0.75 0.75 0.25
0.75 0.75 0.75
0.75 0.25 0.25
0.25 0.75 0.25
0.25 0.25 0.75
"""

H2O = """\
water molecule
1.0
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
O H
1 2
Direct
0.500 0.500 0.500
0.457 0.500 0.549
0.543 0.500 0.549
"""

AL_CART = """\
Al FCC conventional, Cartesian coords
1.0
4.0495 0.0 0.0
0.0 4.0495 0.0
0.0 0.0 4.0495
Al
4
Cartesian
0.0 0.0 0.0
2.02475 2.02475 0.0
2.02475 0.0 2.02475
0.0 2.02475 2.02475
"""

VASP4 = """\
VASP4 style, no element line
1.0
4.0495 0.0 0.0
0.0 4.0495 0.0
0.0 0.0 4.0495
4
Direct
0.0 0.0 0.0
0.5 0.5 0.0
0.5 0.0 0.5
0.0 0.5 0.5
"""

LINEMODE_KPOINTS = """\
Band structure
20
Line-mode
rec
0.0 0.0 0.0 GAMMA
0.0 1.0 0.0 X
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        p = self.dir / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def incar(self, mapping):
        lines = [f"{k} = {v}" for k, v in mapping.items()]
        return self.write("INCAR", "\n".join(lines) + "\n")

    def codes(self, findings):
        return {x.code for x in findings}

    def errors(self, findings):
        return [x for x in findings if x.level == vi.ERROR]


# ---------------------------------------------------------------------------
# POSCAR parsing
# ---------------------------------------------------------------------------

class TestPoscarParsing(Case):
    def test_cartesian_coords_and_vacuum(self):
        s = vi.parse_poscar(self.write("POSCAR", AL_CART))
        self.assertEqual(s.elements, ["Al"])
        self.assertEqual(s.natoms, 4)
        # atom 2 = (2.02475, 2.02475, 0) -> frac (0.5, 0.5, 0)
        self.assertAlmostEqual(s.frac[1][0], 0.5, places=5)
        self.assertAlmostEqual(s.frac[1][1], 0.5, places=5)
        self.assertEqual(s.vacuum_axes(), [])  # bulk: no vacuum

    def test_slab_vacuum_detected(self):
        s = vi.parse_poscar(self.write("POSCAR", PT_SLAB_H))
        self.assertEqual(s.vacuum_axes(), ["c"])
        self.assertTrue(s.has_h)

    def test_wrapped_fractional_slab_uses_largest_circular_gap(self):
        structure = vi.Structure(
            lattice=[[4.0, 0.0, 0.0],
                     [0.0, 4.0, 0.0],
                     [0.0, 0.0, 20.0]],
            elements=["Pt"], counts=[4],
            frac=[[0.0, 0.0, 0.95],
                  [0.5, 0.0, 0.98],
                  [0.0, 0.5, 0.02],
                  [0.5, 0.5, 0.05]],
        )
        self.assertEqual(structure.vacuum_axes(), ["c"])

    def test_fractional_zero_and_one_share_periodic_boundary(self):
        structure = vi.Structure(
            lattice=[[4.0, 0.0, 0.0],
                     [0.0, 4.0, 0.0],
                     [0.0, 0.0, 20.0]],
            elements=["Pt"], counts=[4],
            frac=[[0.0, 0.0, 0.0],
                  [0.5, 0.0, 1.0],
                  [0.0, 0.5, 0.02],
                  [0.5, 0.5, 0.98]],
        )
        self.assertEqual(structure.vacuum_axes(), ["c"])

    def test_vasp4_counts_line(self):
        s = vi.parse_poscar(self.write("POSCAR", VASP4))
        self.assertIsNone(s.elements)
        self.assertEqual(s.counts, [4])
        self.assertEqual(s.natoms, 4)

    def test_negative_scale_factor(self):
        content = CEO2.replace("1.0\n5.411", "-157.9\n5.411", 1)
        s = vi.parse_poscar(self.write("POSCAR", content))
        # volume of 5.411^3 cell ~ 158.4; negative scale targets ~157.9
        self.assertAlmostEqual(abs(vi._det3(s.lattice)), 157.9, delta=1.0)

    def test_three_scaling_factors_scale_cartesian_components_and_coords(self):
        content = """\
non-orthogonal
2.0 3.0 4.0
1.0 1.0 0.0
0.0 1.0 1.0
1.0 0.0 1.0
X
1
Cartesian
0.5 0.5 0.5
"""
        s = vi.parse_poscar(self.write("POSCAR", content))
        self.assertEqual(s.lattice,
                         [[2.0, 3.0, 0.0], [0.0, 3.0, 4.0], [2.0, 0.0, 4.0]])
        self.assertAlmostEqual(s.frac[0][0], 0.25)
        self.assertAlmostEqual(s.frac[0][1], 0.25)
        self.assertAlmostEqual(s.frac[0][2], 0.25)

    def test_two_scaling_factors_are_rejected(self):
        content = AL_CART.replace("1.0\n4.0495", "2.0 3.0\n4.0495", 1)
        with self.assertRaisesRegex(ValueError, "1 or 3 scaling factors"):
            vi.parse_poscar(self.write("POSCAR", content))

    def test_non_finite_scaling_factor_is_rejected(self):
        content = AL_CART.replace("1.0\n4.0495", "nan\n4.0495", 1)
        with self.assertRaisesRegex(ValueError, "finite"):
            vi.parse_poscar(self.write("POSCAR", content))


class TestNonFiniteVaspScalars(Case):
    def test_non_finite_scalar_is_error_and_does_not_crash_inference(self):
        _, findings = vi.validate_one(self.incar({
            "IBRION": "nan", "NSW": "0", "ENCUT": "nan",
        }))
        hits = [x for x in findings if x.code == "VASP_VALUE_UNPARSEABLE"]
        self.assertEqual({x.level for x in hits}, {vi.ERROR})
        self.assertTrue(any("IBRION" in x.message for x in hits), hits)
        self.assertTrue(any("ENCUT" in x.message for x in hits), hits)


# ---------------------------------------------------------------------------
# Rule tests (each maps to a SKILL.md validation-table row)
# ---------------------------------------------------------------------------

class TestDftuRules(Case):
    BASE = {"LDAU": ".TRUE.", "LDAUTYPE": "2", "LDAUL": "3 -1",
            "LDAUU": "5.0 0.0", "LDAUJ": "0.0 0.0", "NELM": "100",
            "ENCUT": "400", "IBRION": "2", "NSW": "100"}

    def run_case(self, **overrides):
        params = dict(self.BASE, **overrides)
        poscar = self.write("POSCAR", CEO2)
        incar = self.incar(params)
        _, findings = vi.validate_one(incar, poscar)
        return findings

    def test_missing_lmaxmix_is_warn_for_self_consistent_dftu(self):
        params = dict(self.BASE); params.pop("LMAXMIX", None)
        poscar = self.write("POSCAR", CEO2)
        _, findings = vi.validate_one(self.incar(params), poscar)
        hit = next(x for x in findings if x.code == "DFTU_MISSING_LMAXMIX")
        self.assertEqual(hit.level, vi.WARN)

    def test_missing_lmaxmix_is_error_for_fixed_density_restart(self):
        params = dict(self.BASE, ICHARG="11"); params.pop("LMAXMIX", None)
        poscar = self.write("POSCAR", CEO2)
        _, findings = vi.validate_one(self.incar(params), poscar)
        hit = next(x for x in findings if x.code == "DFTU_MISSING_LMAXMIX")
        self.assertEqual(hit.level, vi.ERROR)

    def test_f_electron_requires_lmaxmix6(self):
        findings = self.run_case(LMAXMIX="4")
        hit = next(x for x in findings if x.code == "LMAXMIX_F_MISMATCH")
        self.assertEqual(hit.level, vi.WARN)
        findings = self.run_case(LMAXMIX="6")
        self.assertNotIn("LMAXMIX_F_MISMATCH", self.codes(findings))
        self.assertEqual(self.errors(findings), [])

    def test_d_electron_requires_lmaxmix4(self):
        findings = self.run_case(LDAUL="2 -1", LMAXMIX="2")
        hit = next(x for x in findings if x.code == "LMAXMIX_D_MISMATCH")
        self.assertEqual(hit.level, vi.WARN)
        findings = self.run_case(LDAUL="2 -1", LMAXMIX="4")
        self.assertNotIn("LMAXMIX_D_MISMATCH", self.codes(findings))

    def test_low_lmaxmix_is_error_for_fixed_density_restart(self):
        findings = self.run_case(ICHARG="11", LMAXMIX="4")
        hit = next(x for x in findings if x.code == "LMAXMIX_F_MISMATCH")
        self.assertEqual(hit.level, vi.ERROR)

    def test_incomplete_dftu(self):
        params = dict(self.BASE, LMAXMIX="6"); params.pop("LDAUL")
        poscar = self.write("POSCAR", CEO2)
        _, findings = vi.validate_one(self.incar(params), poscar)
        self.assertIn("DFTU_INCOMPLETE", self.codes(findings))

    def test_count_mismatch(self):
        findings = self.run_case(LDAUL="3", LMAXMIX="6")  # 1 value, 2 elements
        self.assertIn("DFTU_COUNT_MISMATCH", self.codes(findings))

    def test_nelm_low_warns(self):
        findings = self.run_case(LMAXMIX="6", NELM="60")
        self.assertIn("DFTU_NELM_LOW", self.codes(findings))


class TestDispersionRules(Case):
    def test_ivdw11_warns_zero_damping(self):
        """Regression: D3BJ is IVDW=12. IVDW=11 must always be flagged."""
        _, findings = vi.validate_one(self.incar({"IVDW": "11", "ENCUT": "400"}))
        self.assertIn("IVDW_ZERO_DAMPING", self.codes(findings))

    def test_ivdw12_clean(self):
        _, findings = vi.validate_one(self.incar({"IVDW": "12", "ENCUT": "400"}))
        self.assertNotIn("IVDW_ZERO_DAMPING", self.codes(findings))


class TestDipoleRules(Case):
    def test_idipol_without_ldipol_is_error(self):
        findings = vi.validate(vi.parse_incar(self.incar({"IDIPOL": "3", "ENCUT": "400"})))
        self.assertIn("DIPOLE_WITHOUT_LDIPOL", self.codes(findings))

    def test_vacuum_without_dipole_warns(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(self.incar({"ENCUT": "400"}), poscar)
        self.assertIn("DIPOLE_MISSING", self.codes(findings))

    def test_missing_dipole_warning_requires_symmetric_slab_evidence(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(self.incar({"ENCUT": "400"}), poscar)
        message = next(
            x.message for x in findings if x.code == "DIPOLE_MISSING")
        self.assertIn("symmetric", message.lower())
        self.assertIn("net dipole", message.lower())

    def test_missing_dipole_message_is_molecule_aware(self):
        molecule = vi.Structure(
            lattice=[[20.0, 0.0, 0.0],
                     [0.0, 20.0, 0.0],
                     [0.0, 0.0, 20.0]],
            elements=["H"], counts=[1], frac=[[0.5, 0.5, 0.5]],
        )
        findings = vi.validate({"ENCUT": ["400"]}, structure=molecule)
        message = next(
            x.message for x in findings if x.code == "DIPOLE_MISSING")
        self.assertIn("isolated molecule", message.lower())
        self.assertIn("total dipole", message.lower())
        self.assertNotIn("two surfaces", message.lower())

    def test_slab_with_dipole_clean(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"ENCUT": "400", "IDIPOL": "3", "LDIPOL": ".TRUE."}), poscar)
        self.assertNotIn("DIPOLE_MISSING", self.codes(findings))
        self.assertNotIn("DIPOLE_WITHOUT_LDIPOL", self.codes(findings))

    def test_dipole_axis_mismatch_warns(self):
        # PT_SLAB_H has vacuum along c; IDIPOL=1 would correct along a — wrong axis.
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"ENCUT": "400", "IDIPOL": "1", "LDIPOL": ".TRUE."}), poscar)
        self.assertIn("DIPOLE_AXIS_MISMATCH", self.codes(findings))

    def test_dipole_axis_match_is_clean(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"ENCUT": "400", "IDIPOL": "3", "LDIPOL": ".TRUE."}), poscar)
        self.assertNotIn("DIPOLE_AXIS_MISMATCH", self.codes(findings))

    def test_idipol4_on_slab_warns(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"ENCUT": "400", "IDIPOL": "4", "LDIPOL": ".TRUE."}),
            poscar)
        self.assertIn("IDIPOL4_NONMOLECULAR", self.codes(findings))

    def test_idipol4_on_isolated_molecule_is_allowed(self):
        molecule = vi.Structure(
            lattice=[[20.0, 0.0, 0.0],
                     [0.0, 20.0, 0.0],
                     [0.0, 0.0, 20.0]],
            elements=["H"], counts=[1], frac=[[0.5, 0.5, 0.5]],
        )
        params = {"ENCUT": ["400"], "IDIPOL": ["4"],
                  "LDIPOL": [".TRUE."]}
        findings = vi.validate(params, structure=molecule)
        self.assertNotIn("IDIPOL4_NONMOLECULAR", self.codes(findings))

    def test_idipol4_on_workfunction_task_warns_even_with_three_axis_vacuum(self):
        molecule_like_box = vi.Structure(
            lattice=[[20.0, 0.0, 0.0],
                     [0.0, 20.0, 0.0],
                     [0.0, 0.0, 20.0]],
            elements=["H"], counts=[1], frac=[[0.5, 0.5, 0.5]],
        )
        params = {"ENCUT": ["400"], "IDIPOL": ["4"],
                  "LDIPOL": [".TRUE."], "LVHAR": [".TRUE."]}
        findings = vi.validate(
            params, structure=molecule_like_box, task_override="workfunction")
        self.assertIn("IDIPOL4_NONMOLECULAR", self.codes(findings))

    def test_idipol4_on_workfunction_warns_without_poscar(self):
        params = {"ENCUT": ["400"], "IDIPOL": ["4"],
                  "LDIPOL": [".TRUE."], "LVHAR": [".TRUE."]}
        findings = vi.validate(params, task_override="workfunction")
        self.assertIn("IDIPOL4_NONMOLECULAR", self.codes(findings))


class TestSolvationEfieldRules(Case):
    def test_lsol_warns_binary_and_prec(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"LSOL": ".TRUE.", "PREC": "Normal", "ENCUT": "400"})))
        self.assertIn("VASPSOL_BINARY_UNVERIFIED", self.codes(findings))
        self.assertIn("VASPSOL_PREC_LOW", self.codes(findings))

    def test_lsol_accurate_prec_only_binary_warn(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"LSOL": ".TRUE.", "PREC": "Accurate", "ENCUT": "400"})))
        self.assertIn("VASPSOL_BINARY_UNVERIFIED", self.codes(findings))
        self.assertNotIn("VASPSOL_PREC_LOW", self.codes(findings))

    def test_efield_without_dipole_is_error(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"EFIELD": "0.1", "ENCUT": "400"})))
        self.assertIn("EFIELD_WITHOUT_DIPOLE", self.codes(findings))

    def test_efield_with_dipole_passes(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"EFIELD": "0.1", "ENCUT": "400",
                        "IDIPOL": "3", "LDIPOL": ".TRUE."}), poscar)
        self.assertNotIn("EFIELD_WITHOUT_DIPOLE", self.codes(findings))

    def test_nelect_slab_without_dipole_warns(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"NELECT": "100", "ENCUT": "400"}), poscar)
        self.assertIn("NELECT_SLAB_NO_DIPOLE", self.codes(findings))


class TestTaskRules(Case):
    def test_elf_requires_npar1(self):
        findings = vi.validate(vi.parse_incar(self.incar({"LELF": ".TRUE.", "NPAR": "4"})))
        self.assertIn("ELF_NPAR", self.codes(findings))
        findings = vi.validate(vi.parse_incar(self.incar({"LELF": ".TRUE.", "NPAR": "1"})))
        self.assertNotIn("ELF_NPAR", self.codes(findings))

    def test_lepsilon_loptics_conflict(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"LEPSILON": ".TRUE.", "LOPTICS": ".TRUE."})))
        self.assertIn("LEPSILON_LOPTICS_CONFLICT", self.codes(findings))

    def test_workfunction_requires_output(self):
        findings = vi.validate(vi.parse_incar(self.incar({"ENCUT": "400"})),
                               task_override="workfunction")
        self.assertIn("WF_NO_OUTPUT", self.codes(findings))
        findings = vi.validate(vi.parse_incar(self.incar({"LVHAR": ".TRUE."})),
                               task_override="workfunction")
        self.assertNotIn("WF_NO_OUTPUT", self.codes(findings))

    def test_wf_dipole_warns_without_task_hint(self):
        """WF dipole check fires on LVHAR/LVTOT alone — no --task or filename hint needed."""
        poscar = self.write("POSCAR", PT_SLAB_H)  # slab with vacuum, INCAR has no IDIPOL
        _, findings = vi.validate_one(
            self.incar({"LVHAR": ".TRUE.", "ENCUT": "400"}), poscar)
        self.assertIn("WF_NO_DIPOLE", self.codes(findings))
        # with a dipole correction present the warning must stay silent
        _, findings = vi.validate_one(
            self.incar({"LVHAR": ".TRUE.", "ENCUT": "400",
                        "IDIPOL": "3", "LDIPOL": ".TRUE."}), poscar)
        self.assertNotIn("WF_NO_DIPOLE", self.codes(findings))

    def test_dielectric_requires_lepsilon(self):
        findings = vi.validate(vi.parse_incar(self.incar({"ENCUT": "400"})),
                               task_override="dielectric")
        self.assertIn("DIELECTRIC_NO_LEPSILON", self.codes(findings))

    def test_md_timestep_cap_with_hydrogen(self):
        poscar = self.write("POSCAR", H2O)
        _, findings = vi.validate_one(
            self.incar({"IBRION": "0", "POTIM": "2.0", "NSW": "100", "ENCUT": "400"}), poscar)
        self.assertIn("MD_TIMESTEP_CAP", self.codes(findings))
        _, findings = vi.validate_one(
            self.incar({"IBRION": "0", "POTIM": "0.5", "NSW": "100", "ENCUT": "400",
                        "ISYM": "0"}), poscar)
        self.assertNotIn("MD_TIMESTEP_CAP", self.codes(findings))

    def test_cg_potim_adsorbate(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"IBRION": "2", "POTIM": "0.5", "NSW": "100", "ENCUT": "400",
                        "IDIPOL": "3", "LDIPOL": ".TRUE."}), poscar)
        self.assertIn("CG_POTIM_ADSORBATE", self.codes(findings))

    def test_tetrahedron_on_linemode_is_error(self):
        poscar = self.write("POSCAR", AL_CART)
        kpoints = self.write("KPOINTS", LINEMODE_KPOINTS)
        _, findings = vi.validate_one(
            self.incar({"ISMEAR": "-5", "ICHARG": "11", "ENCUT": "400"}), poscar,
            kpoints_path=kpoints)
        self.assertIn("TETRA_ON_LINEMODE", self.codes(findings))

    def test_freq_on_linemode_is_error(self):
        """IBRION=5 + line-mode KPOINTS: VASP aborts ('I REFUSE TO CONTINUE', 6.4.2)."""
        poscar = self.write("POSCAR", AL_CART)
        kpoints = self.write("KPOINTS", LINEMODE_KPOINTS)
        _, findings = vi.validate_one(
            self.incar({"IBRION": "5", "NSW": "1", "POTIM": "0.015",
                        "ENCUT": "400"}), poscar,
            kpoints_path=kpoints)
        self.assertIn("FREQ_ON_LINEMODE", self.codes(findings))
        self.assertNotIn("STATIC_ON_LINEMODE", self.codes(findings))

    def test_freq_on_uniform_mesh_is_clean(self):
        poscar = self.write("POSCAR", AL_CART)
        _, findings = vi.validate_one(
            self.incar({"IBRION": "5", "NSW": "1", "POTIM": "0.015",
                        "ENCUT": "400"}), poscar)
        self.assertNotIn("FREQ_ON_LINEMODE", self.codes(findings))

    def test_static_on_linemode_warns(self):
        """Plain static (ICHARG != 11) on a k-path: usually band KPOINTS in the wrong folder."""
        poscar = self.write("POSCAR", AL_CART)
        kpoints = self.write("KPOINTS", LINEMODE_KPOINTS)
        _, findings = vi.validate_one(
            self.incar({"NSW": "0", "ENCUT": "400"}), poscar,
            kpoints_path=kpoints)
        self.assertIn("STATIC_ON_LINEMODE", self.codes(findings))

    def test_band_icharg11_on_linemode_no_static_warning(self):
        poscar = self.write("POSCAR", AL_CART)
        kpoints = self.write("KPOINTS", LINEMODE_KPOINTS)
        _, findings = vi.validate_one(
            self.incar({"NSW": "0", "ICHARG": "11", "ENCUT": "400"}), poscar,
            kpoints_path=kpoints)
        self.assertNotIn("STATIC_ON_LINEMODE", self.codes(findings))

    def test_tetrahedron_allowed_for_semiconductor_static(self):
        poscar = self.write("POSCAR", AL_CART)
        _, findings = vi.validate_one(
            self.incar({"ISMEAR": "-5", "IBRION": "-1", "NSW": "0", "ENCUT": "400"}), poscar)
        self.assertNotIn("TETRA_ON_LINEMODE", self.codes(findings))
        self.assertNotIn("TETRA_ON_RELAX", self.codes(findings))

    def test_lreal_auto_small_cell(self):
        poscar = self.write("POSCAR", H2O)
        _, findings = vi.validate_one(
            self.incar({"LREAL": "Auto", "ENCUT": "400"}), poscar)
        self.assertIn("LREAL_AUTO_SMALL", self.codes(findings))

    def test_clean_metal_slab_relax_has_no_errors(self):
        poscar = self.write("POSCAR", PT_SLAB_H)
        _, findings = vi.validate_one(
            self.incar({"SYSTEM": "Pt slab", "ENCUT": "400", "IBRION": "2", "ISIF": "2",
                        "NSW": "100", "POTIM": "0.3", "ISMEAR": "0", "SIGMA": "0.1",
                        "IDIPOL": "3", "LDIPOL": ".TRUE.", "NELMIN": "4", "NELM": "60",
                        "IVDW": "12"}),
            poscar)
        self.assertEqual(self.errors(findings), [],
                         msg="; ".join(str(x) for x in self.errors(findings)))


class TestSocMetaggaPhonon(Case):
    def test_soc_without_nbands_warns(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"LSORBIT": ".TRUE.", "ENCUT": "400"})))
        self.assertIn("SOC_NBANDS", self.codes(findings))

    def test_soc_with_nbands_clean(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"LSORBIT": ".TRUE.", "NBANDS": "128", "ENCUT": "400"})))
        self.assertNotIn("SOC_NBANDS", self.codes(findings))

    def test_metagga_without_lasph_is_error(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"METAGGA": "R2SCAN", "ENCUT": "400"})))
        self.assertIn("METAGGA_NO_LASPH", self.codes(findings))

    def test_metagga_lasph_without_addgrid_warns(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"METAGGA": "R2SCAN", "LASPH": ".TRUE.", "ENCUT": "400"})))
        self.assertNotIn("METAGGA_NO_LASPH", self.codes(findings))
        self.assertIn("METAGGA_NO_ADDGRID", self.codes(findings))

    def test_metagga_complete_clean(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"METAGGA": "R2SCAN", "LASPH": ".TRUE.",
                        "ADDGRID": ".TRUE.", "ENCUT": "400"})))
        self.assertNotIn("METAGGA_NO_LASPH", self.codes(findings))
        self.assertNotIn("METAGGA_NO_ADDGRID", self.codes(findings))

    def test_phonon_ediff_loose_warns(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"IBRION": "-1", "NSW": "0", "EDIFF": "1E-5", "ENCUT": "400"})),
            task_override="phonon")
        self.assertIn("PHONON_EDIFF_LOOSE", self.codes(findings))

    def test_phonon_ediff_tight_clean(self):
        findings = vi.validate(vi.parse_incar(
            self.incar({"IBRION": "-1", "NSW": "0", "EDIFF": "1E-8", "ENCUT": "400"})),
            task_override="phonon")
        self.assertNotIn("PHONON_EDIFF_LOOSE", self.codes(findings))


# ---------------------------------------------------------------------------
# Parallelization sizing rules (2026-10-23 MPI-overhead case study)
# ---------------------------------------------------------------------------

class TestParallelSizingRules(Case):
    SLAB17 = vi.Structure(
        lattice=[[5.55, 0.0, 0.0],
                 [2.77, 4.80, 0.0],
                 [0.0, 0.0, 22.0]],
        elements=["Pt", "H"], counts=[16, 1],
        frac=[[0.1, 0.1, 0.1]] * 17,
    )

    def test_ncore_small_cell_warns(self):
        findings = vi.validate({"NCORE": ["4"], "ENCUT": ["400"]},
                               structure=self.SLAB17, task_override="relax")
        self.assertIn("PARA_NCORE_SMALL_CELL", self.codes(findings))

    def test_ncore_one_small_cell_no_warn(self):
        findings = vi.validate({"NCORE": ["1"], "ENCUT": ["400"]},
                               structure=self.SLAB17, task_override="relax")
        self.assertNotIn("PARA_NCORE_SMALL_CELL", self.codes(findings))

    def test_kpar_small_mesh_warns(self):
        findings = vi.validate({"KPAR": ["3"], "ENCUT": ["400"]},
                               mesh=(6, 6, 1), task_override="relax")
        self.assertIn("PARA_KPAR_SMALL_MESH", self.codes(findings))

    def test_kpar_dense_mesh_no_warn(self):
        findings = vi.validate({"KPAR": ["3"], "ENCUT": ["400"]},
                               mesh=(9, 9, 1), task_override="relax")
        self.assertNotIn("PARA_KPAR_SMALL_MESH", self.codes(findings))


# ---------------------------------------------------------------------------
# Task-chain consistency rules (2026-10-23 PREC charge-sloshing case)
# ---------------------------------------------------------------------------

class TestChainConsistencyRules(Case):
    PT_SLAB = vi.Structure(
        lattice=[[5.55, 0.0, 0.0],
                 [2.77, 4.80, 0.0],
                 [0.0, 0.0, 22.0]],
        elements=["Pt", "H"], counts=[16, 1],
        frac=[[0.1, 0.1, 0.1]] * 17,
    )
    H2_BOX = vi.Structure(
        lattice=[[10.0, 0.0, 0.0],
                 [0.0, 10.0, 0.0],
                 [0.0, 0.0, 10.0]],
        elements=["H"], counts=[2],
        frac=[[0.4, 0.5, 0.5], [0.6, 0.5, 0.5]],
    )

    def test_freq_ediff_loose_warns(self):
        findings = vi.validate({"EDIFF": ["1E-6"], "ENCUT": ["400"]},
                               task_override="freq")
        self.assertIn("FREQ_EDIFF_LOOSE", self.codes(findings))

    def test_freq_ediff_tight_no_warn(self):
        findings = vi.validate({"EDIFF": ["1E-8"], "ENCUT": ["400"]},
                               task_override="freq")
        self.assertNotIn("FREQ_EDIFF_LOOSE", self.codes(findings))

    def test_prec_accurate_metal_slab_warns(self):
        findings = vi.validate(
            {"PREC": ["Accurate"], "ENCUT": ["400"], "NELMIN": ["6"]},
            structure=self.PT_SLAB, task_override="freq")
        self.assertIn("PREC_ACCURATE_METAL_SLAB", self.codes(findings))

    def test_prec_normal_metal_slab_no_warn(self):
        findings = vi.validate(
            {"PREC": ["Normal"], "ENCUT": ["400"], "NELMIN": ["6"]},
            structure=self.PT_SLAB, task_override="freq")
        self.assertNotIn("PREC_ACCURATE_METAL_SLAB", self.codes(findings))

    def test_prec_accurate_molecule_no_warn(self):
        findings = vi.validate(
            {"PREC": ["Accurate"], "ENCUT": ["400"]},
            structure=self.H2_BOX, task_override="freq")
        self.assertNotIn("PREC_ACCURATE_METAL_SLAB", self.codes(findings))


# ---------------------------------------------------------------------------
# Golden test: every shipped example INCAR must be ERROR-free
# ---------------------------------------------------------------------------

class TestGoldenExamples(unittest.TestCase):
    def test_examples_have_no_errors(self):
        results = vi.run_examples_dir(str(ROOT / "examples"))
        bad = {name: [str(x) for x in fs if x.level == vi.ERROR]
               for name, fs in results.items()}
        bad = {k: v for k, v in bad.items() if v}
        self.assertEqual(bad, {}, msg=f"Examples with ERROR findings:\n{bad}")

    def test_examples_found(self):
        results = vi.run_examples_dir(str(ROOT / "examples"))
        self.assertGreaterEqual(len(results), 10,
                                "golden test should cover the shipped VASP examples")


# ---------------------------------------------------------------------------
# VTST optimizer coupling rules (2026-10-29 CI-NEB continuation case)
# ---------------------------------------------------------------------------

class TestVtstOptimizerRules(Case):
    def test_iopt_with_ibrion1_errors(self):
        findings = vi.validate({"IOPT": ["7"], "IBRION": ["1"], "ENCUT": ["400"]},
                               task_override="neb")
        self.assertIn("VASP_IOPT_REQUIRES_IBRION3_POTIM0", self.codes(findings))

    def test_iopt_with_potim_errors(self):
        findings = vi.validate({"IOPT": ["7"], "IBRION": ["3"], "POTIM": ["0.3"],
                                "ENCUT": ["400"]}, task_override="neb")
        self.assertIn("VASP_IOPT_REQUIRES_IBRION3_POTIM0", self.codes(findings))

    def test_iopt_full_contract_clean(self):
        findings = vi.validate({"IOPT": ["7"], "IBRION": ["3"], "POTIM": ["0"],
                                "ENCUT": ["400"]}, task_override="neb")
        self.assertNotIn("VASP_IOPT_REQUIRES_IBRION3_POTIM0", self.codes(findings))
        self.assertNotIn("VASP_IBRION3_POTIM0_NO_IOPT", self.codes(findings))

    def test_ibrion3_potim0_without_iopt_warns(self):
        findings = vi.validate({"IBRION": ["3"], "POTIM": ["0"], "ENCUT": ["400"]})
        self.assertIn("VASP_IBRION3_POTIM0_NO_IOPT", self.codes(findings))
        self.assertEqual([f.level for f in findings if f.code == "VASP_IBRION3_POTIM0_NO_IOPT"], [vi.WARN])

    def test_ibrion3_default_potim_no_warn(self):
        findings = vi.validate({"IBRION": ["3"], "ENCUT": ["400"]})
        self.assertNotIn("VASP_IBRION3_POTIM0_NO_IOPT", self.codes(findings))

    def test_neb_stock_optimizer_info(self):
        findings = vi.validate({"IBRION": ["1"], "IMAGES": ["4"], "ENCUT": ["400"]})
        self.assertIn("VASP_NEB_STOCK_OPTIMIZER", self.codes(findings))
        self.assertEqual([f.level for f in findings if f.code == "VASP_NEB_STOCK_OPTIMIZER"], [vi.INFO])

    def test_neb_fire_no_stock_hint(self):
        findings = vi.validate({"IBRION": ["3"], "POTIM": ["0"], "IOPT": ["7"],
                                "IMAGES": ["4"], "ENCUT": ["400"]})
        self.assertNotIn("VASP_NEB_STOCK_OPTIMIZER", self.codes(findings))


if __name__ == "__main__":
    unittest.main()
