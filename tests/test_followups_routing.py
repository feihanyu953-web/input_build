#!/usr/bin/env python3
"""Guard the VASP follow-ups split: vasp.md exists, SKILL.md routes to it,
and the high-frequency summary keywords survive in SKILL.md.

Run from the skill directory:
    python -m unittest tests.test_followups_routing -v
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
VASP_REF = ROOT / "references" / "vasp.md"


def _section(text, start, end):
    m = re.search(start + r"(.*?)" + end, text, re.S)
    assert m, f"section {start!r} not found"
    return m.group(1)


class TestVaspReferenceExists(unittest.TestCase):
    def test_vasp_md_exists(self):
        self.assertTrue(VASP_REF.exists(), "references/vasp.md missing")

    def test_vasp_md_covers_key_followups(self):
        if not VASP_REF.exists():
            self.skipTest("vasp.md missing")
        body = VASP_REF.read_text(encoding="utf-8")
        for kw in ("VASPsol", "EFIELD", "NBANDS", "LASPH", "phonopy"):
            with self.subTest(kw=kw):
                self.assertIn(kw, body, f"vasp.md missing key followup {kw!r}")


class TestSkillRoutesToVaspRef(unittest.TestCase):
    def test_skill_references_vasp_md(self):
        # Summary + Reference Files table must point to references/vasp.md
        self.assertIn("references/vasp.md", SKILL)

    def test_skill_summary_keeps_high_freq_keywords(self):
        # SKILL.md must keep high-frequency summary keywords so AI does not
        # miss the most error-prone follow-ups even without opening vasp.md
        body = _section(SKILL, r"\*\*VASP:\*\*", r"\*\*LAMMPS:")
        for kw in ("VASPsol", "EFIELD", "NBANDS", "LASPH", "Phonon"):
            with self.subTest(kw=kw):
                self.assertIn(kw, body, f"SKILL.md VASP summary lost {kw!r}")


if __name__ == "__main__":
    unittest.main()
