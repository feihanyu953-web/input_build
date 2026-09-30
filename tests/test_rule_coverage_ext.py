#!/usr/bin/env python3
"""
Supplementary rule-coverage tests for rules listed in SKILL.md's Validation
Rules table that are implemented in validate_input.py but not yet covered by
test_audit_validator.py. Each test constructs a minimal triggering input and
asserts the expected finding code, so silent removal/regression of the rule
fails the test.

Covered rules (validator line numbers in comments):
  DIPOLE_WITHOUT_LDIPOL    ERROR  IDIPOL set but LDIPOL missing      :462
  IDIPOL4_NONMOLECULAR     WARN   IDIPOL=4 + workfunction task        :466
  TETRA_ON_RELAX           WARN   ISMEAR=-5 + relax/md task          :512
  ELF_NPAR                 ERROR  LELF=.TRUE. + NPAR!=1              :636
  PHONON_EDIFF_LOOSE       WARN   phonon task + EDIFF>1E-7           :686
  LEPSILON_LOPTICS_CONFLICT ERROR LEPSILON + LOPTICS in one INCAR    :657
  OPTICS_NBANDS            WARN   LOPTICS without explicit NBANDS    :660
  DIELECTRIC_NO_LEPSILON   ERROR  dielectric task without LEPSILON   :663

Run from the skill directory:
    python -m unittest tests.test_rule_coverage_ext -v
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vi = _load("validate_input", "scripts/validate_input.py")


class Case(unittest.TestCase):
    """Shared fixture: write an INCAR from a mapping and run validate()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return str(p)

    def incar(self, mapping):
        lines = [f"{k} = {v}" for k, v in mapping.items()]
        return self.write("INCAR", "\n".join(lines) + "\n")

    def vasp(self, mapping, poscar=None, task=None):
        params = vi.parse_incar(self.incar(mapping))
        structure = vi.parse_poscar(self.write("POSCAR", poscar)) if poscar else None
        return vi.validate(params, structure, task_override=task)

    def codes(self, findings):
        return {x.code for x in findings}


class TestDipoleWithoutLdipol(Case):
    """IDIPOL set but LDIPOL missing -> ERROR (validator:462)."""

    def test_idipol_without_ldipol_is_error(self):
        f = self.vasp({"IDIPOL": "3", "ENCUT": "400"})
        self.assertIn("DIPOLE_WITHOUT_LDIPOL", self.codes(f))

    def test_idipol_with_ldipol_clean(self):
        f = self.vasp({"IDIPOL": "3", "LDIPOL": ".TRUE.", "ENCUT": "400"})
        self.assertNotIn("DIPOLE_WITHOUT_LDIPOL", self.codes(f))


class TestIdipol4Nonmolecular(Case):
    """IDIPOL=4 + workfunction task -> WARN (validator:466)."""

    def test_idipol4_workfunction_warns(self):
        f = self.vasp({"IDIPOL": "4", "LDIPOL": ".TRUE.", "ENCUT": "400"},
                       task="workfunction")
        self.assertIn("IDIPOL4_NONMOLECULAR", self.codes(f))

    def test_idipol3_workfunction_clean(self):
        f = self.vasp({"IDIPOL": "3", "LDIPOL": ".TRUE.", "ENCUT": "400"},
                       task="workfunction")
        self.assertNotIn("IDIPOL4_NONMOLECULAR", self.codes(f))


class TestTetraOnRelax(Case):
    """ISMEAR=-5 + relax task -> WARN (validator:512)."""

    def test_tetra_on_relax_warns(self):
        f = self.vasp({"ISMEAR": "-5", "IBRION": "2", "NSW": "100",
                       "ENCUT": "400"}, task="relax")
        self.assertIn("TETRA_ON_RELAX", self.codes(f))

    def test_tetra_on_static_clean(self):
        f = self.vasp({"ISMEAR": "-5", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"}, task="static")
        self.assertNotIn("TETRA_ON_RELAX", self.codes(f))


class TestElfNpar(Case):
    """LELF=.TRUE. + NPAR!=1 -> ERROR (validator:636)."""

    def test_elf_with_npar4_is_error(self):
        f = self.vasp({"LELF": ".TRUE.", "NPAR": "4", "IBRION": "-1",
                       "NSW": "0", "ENCUT": "400"}, task="elf")
        self.assertIn("ELF_NPAR", self.codes(f))

    def test_elf_with_npar1_clean(self):
        f = self.vasp({"LELF": ".TRUE.", "NPAR": "1", "IBRION": "-1",
                       "NSW": "0", "ENCUT": "400"}, task="elf")
        self.assertNotIn("ELF_NPAR", self.codes(f))


class TestPhononEdiff(Case):
    """phonon task + EDIFF>1E-7 -> WARN (validator:686)."""

    def test_loose_ediff_warns(self):
        f = self.vasp({"EDIFF": "1E-6", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"}, task="phonon")
        self.assertIn("PHONON_EDIFF_LOOSE", self.codes(f))

    def test_tight_ediff_clean(self):
        f = self.vasp({"EDIFF": "1E-8", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"}, task="phonon")
        self.assertNotIn("PHONON_EDIFF_LOOSE", self.codes(f))


class TestLepsilonLopticsConflict(Case):
    """LEPSILON + LOPTICS in one INCAR -> ERROR (validator:657)."""

    def test_both_set_is_error(self):
        f = self.vasp({"LEPSILON": ".TRUE.", "LOPTICS": ".TRUE.",
                       "IBRION": "-1", "NSW": "0", "ENCUT": "400"})
        self.assertIn("LEPSILON_LOPTICS_CONFLICT", self.codes(f))

    def test_lepsilon_only_clean(self):
        f = self.vasp({"LEPSILON": ".TRUE.", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"})
        self.assertNotIn("LEPSILON_LOPTICS_CONFLICT", self.codes(f))


class TestOpticsNbands(Case):
    """LOPTICS without NBANDS -> WARN (validator:660)."""

    def test_loptics_no_nbands_warns(self):
        f = self.vasp({"LOPTICS": ".TRUE.", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"})
        self.assertIn("OPTICS_NBANDS", self.codes(f))

    def test_loptics_with_nbands_clean(self):
        f = self.vasp({"LOPTICS": ".TRUE.", "NBANDS": "64", "IBRION": "-1",
                       "NSW": "0", "ENCUT": "400"})
        self.assertNotIn("OPTICS_NBANDS", self.codes(f))


class TestDielectricNoLepsilon(Case):
    """dielectric task without LEPSILON -> ERROR (validator:663)."""

    def test_dielectric_without_lepsilon_is_error(self):
        f = self.vasp({"IBRION": "-1", "NSW": "0", "ENCUT": "400"},
                       task="dielectric")
        self.assertIn("DIELECTRIC_NO_LEPSILON", self.codes(f))

    def test_dielectric_with_lepsilon_clean(self):
        f = self.vasp({"LEPSILON": ".TRUE.", "IBRION": "-1", "NSW": "0",
                       "ENCUT": "400"}, task="dielectric")
        self.assertNotIn("DIELECTRIC_NO_LEPSILON", self.codes(f))


if __name__ == "__main__":
    unittest.main()
