#!/usr/bin/env python3
"""
Docs-group regression tests for the 2026-07-19 external audit.

Covers:
  - audit 11.1: SKILL.md frontmatter `name` must stay the canonical
    `input_build`, and any directory mounted as a skill (under .claude/skills)
    must carry that name; release checkouts (repo clones) may be named freely;
    no lingering `input-build` self-references
  - audit 11.3 / P1-VASP-09: INDEX.json must not mount the `semiconductor`
    modifier (ISMEAR=-5 tetrahedron) on the relax task, and neither INDEX.json
    nor SKILL.md may claim INDEX.json is the "Single source of truth"
  - SKILL.md must carry the Version & Capability Gating baselines
    (VASP >= 6.3, CP2K >= 2024.3 with 2026.2 gates, LAMMPS >= 22Jul2025
    reax/c->reaxff, VTST LCLIMB)
  - SKILL.md Step 3 must ask the new mandatory questions (magnetic ordering,
    surface normal, boundary periodicity, potential format, program
    version/build)
  - Red Flags must cover the audit's blocking items (velocity create 0 K,
    IBRION=5 without NSW, hybrid band ICHARG=11, bader without chgsum,
    funcfl/eam pairing, barostat on non-periodic direction, OT + k-points,
    general mesh + WAVEFUNCTIONS REAL, all-zero DFT+U, &ADDED_MOS section)
  - examples/README.md documents runner status semantics, the K5 tolerance
    regression role, and the version-gating notes

Run:
    python -m unittest discover -s tests -p "test_audit_docs.py" -v   # from the skill directory
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # skill directory
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
INDEX = json.loads((ROOT / "base_templates" / "INDEX.json").read_text(encoding="utf-8"))
EXAMPLES_README = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
DIPOLE_PATCH = (ROOT / "modifiers" / "dipole.patch").read_text(encoding="utf-8")


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md has no YAML frontmatter block"
    return m.group(1)


def _section(text, start_pattern, end_pattern):
    m = re.search(start_pattern + r"(.*?)" + end_pattern, text, re.S)
    assert m, f"section {start_pattern!r} not found"
    return m.group(1)


class TestFrontmatterName(unittest.TestCase):
    """Audit 11.1: frontmatter name must match the skill directory name."""

    def test_name_matches_directory(self):
        fm = _frontmatter(SKILL)
        m = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        self.assertIsNotNone(m, "frontmatter has no name field")
        self.assertEqual(m.group(1), "input_build",
                         "frontmatter name must stay the canonical 'input_build'")
        # Audit 11.1 guards *installations*: a directory mounted as a skill must
        # carry the skill name. Release checkouts (repo clones) may be named
        # freely — install docs tell users to name the folder input_build.
        if ROOT.parent.name in (".claude", "skills"):
            self.assertEqual(ROOT.name, m.group(1),
                             f"installed skill dir {ROOT.name!r} != "
                             f"frontmatter name {m.group(1)!r}")

    def test_no_hyphenated_self_reference(self):
        self.assertNotIn("input-build", SKILL,
                         "SKILL.md still self-references the old 'input-build' name")


class TestIndexDrift(unittest.TestCase):
    """Audit 11.3 / P1-VASP-09: relax must not mount ISMEAR=-5; no SSOT claim."""

    def test_relax_has_no_semiconductor_modifier(self):
        mods = INDEX["tasks"]["vasp"]["relax"]["modifiers"]
        self.assertNotIn("semiconductor", mods,
                         "relax must not mount the semiconductor (ISMEAR=-5) modifier; "
                         "tetrahedron is forbidden for relax per SKILL.md")

    def test_relax_documents_tetrahedron_ban(self):
        notes = INDEX["tasks"]["vasp"]["relax"].get("notes", "")
        self.assertIn("ISMEAR=-5", notes,
                      "relax entry should document why semiconductor is excluded")

    def test_static_tasks_keep_semiconductor_modifier(self):
        # tetrahedron remains valid for static/DOS tasks — only relax is gated
        for task in ("scf", "dos"):
            self.assertIn("semiconductor", INDEX["tasks"]["vasp"][task]["modifiers"],
                          f"{task} should still allow the semiconductor modifier")

    def test_index_description_not_ssot(self):
        self.assertNotIn("Single source of truth", INDEX["description"],
                         "INDEX.json must not claim to be the single source of truth")

    def test_skill_not_ssot(self):
        self.assertNotIn("Single source of truth", SKILL,
                         "SKILL.md must not claim INDEX.json is the single source of truth")


class TestVersionGatingSection(unittest.TestCase):
    """New 'Version & Capability Gating' section with the agreed baselines."""

    def test_section_exists(self):
        self.assertIn("Version & Capability Gating", SKILL)

    def test_baselines_present(self):
        self.assertIn("6.3", SKILL)          # VASP >= 6.3
        self.assertIn("2024.3", SKILL)       # CP2K >= 2024.3
        self.assertIn("22Jul2025", SKILL)    # LAMMPS baseline

    def test_cp2k_2026_2_gates(self):
        body = _section(SKILL, r"## Version & Capability Gating", r"\n## ")
        self.assertIn("2026.2", body)
        self.assertIn("CELL_OPT", body)      # TYPE keyword removal gate
        self.assertIn("k-points", body)      # Mulliken DFT+U k-points gate

    def test_vtst_lclimb_gate(self):
        body = _section(SKILL, r"## Version & Capability Gating", r"\n## ")
        self.assertIn("VTST", body)
        self.assertIn("LCLIMB", body)

    def test_reaxff_rename(self):
        body = _section(SKILL, r"## Version & Capability Gating", r"\n## ")
        self.assertIn("reax/c", body)
        self.assertIn("reaxff", body)


class TestStep3MandatoryQuestions(unittest.TestCase):
    """Step 3 must ask the new mandatory questions (audit P1-VASP-06,
    P1-VASP-08, P1-LAMMPS-01/03, section 14 decision 4)."""

    def _step3(self):
        return _section(SKILL, r"### Step 3: Ask Minimal Questions", r"\*\*Code-specific follow-ups")

    def test_magnetic_ordering_question(self):
        body = self._step3()
        for token in ("FM", "AFM", "ferrimagnetic"):
            self.assertIn(token, body, f"magnetic-ordering question missing {token!r}")

    def test_surface_normal_question(self):
        self.assertIn("Surface normal", self._step3())

    def test_vacuum_detection_uses_periodic_circular_gap(self):
        self.assertIn("circular-gap", SKILL.lower())

    def test_periodicity_question(self):
        body = self._step3()
        self.assertIn("periodicity", body.lower())
        for token in ("3D", "2D", "0D"):
            self.assertIn(token, body, f"periodicity question missing {token!r}")

    def test_potential_format_question(self):
        body = self._step3()
        for token in ("funcfl", "setfl", "POTCAR"):
            self.assertIn(token, body, f"potential question missing {token!r}")

    def test_version_build_question(self):
        body = self._step3()
        self.assertIn("version", body.lower())
        self.assertIn("VTST", body)


class TestRedFlags(unittest.TestCase):
    """Red Flags must cover the audit's blocking / high-risk items."""

    def _red_flags(self):
        return _section(SKILL, r"## Red Flags\n", r"\Z")

    def test_velocity_zero_k(self):
        self.assertIn("create 0.0", self._red_flags())

    def test_ibrion5_needs_nsw(self):
        body = self._red_flags()
        self.assertIn("IBRION=5", body)
        self.assertIn("NSW", body)

    def test_hybrid_band_icharg11(self):
        body = self._red_flags()
        self.assertIn("ICHARG=11", body)
        self.assertIn("hybrid", body.lower())

    def test_bader_chgsum_first(self):
        self.assertIn("chgsum", self._red_flags())

    def test_funcfl_eam_pairing(self):
        body = self._red_flags()
        self.assertIn("funcfl", body)
        self.assertIn("eam/alloy", body)

    def test_nonperiodic_npt(self):
        self.assertIn("boundary p p f", self._red_flags())

    def test_ot_plus_kpoints(self):
        body = self._red_flags()
        self.assertIn("OT", body)
        self.assertIn("k-points", body)

    def test_wavefunctions_real(self):
        self.assertIn("WAVEFUNCTIONS REAL", self._red_flags())

    def test_dftu_all_zero(self):
        self.assertIn("LDAUL=-1", self._red_flags())

    def test_added_mos_not_section(self):
        self.assertIn("&ADDED_MOS", self._red_flags())

    def test_idipol4_is_molecule_only_and_symmetric_slab_needs_evidence(self):
        body = self._red_flags()
        self.assertIn("IDIPOL=4", body)
        self.assertIn("isolated molecule", body)
        self.assertIn("net dipole", body)

    def test_dipole_modifier_does_not_exempt_symmetric_slab_without_evidence(self):
        self.assertIn("net dipole", DIPOLE_PATCH.lower())
        self.assertNotIn("usually unnecessary", DIPOLE_PATCH.lower())


class TestExamplesReadme(unittest.TestCase):
    """examples/README.md: runner semantics, K5 role, version gating."""

    def test_runner_status_semantics(self):
        for token in ("STATIC_PASS", "INCOMPLETE", "ERROR", "syntax",
                      "combination", "physics", "NOT_EVALUATED"):
            self.assertIn(token, EXAMPLES_README,
                          f"runner status {token!r} not documented")

    def test_k5_tolerance_regression(self):
        self.assertRegex(EXAMPLES_README, r"K5[^\n]*(容差回归|symprec|tolerance)",
                         "K5 must be documented as a tolerance regression case")

    def test_version_gating_notes(self):
        self.assertIn("版本门控", EXAMPLES_README)
        self.assertIn("2026.2", EXAMPLES_README)
        self.assertIn("reaxff", EXAMPLES_README)


if __name__ == "__main__":
    unittest.main()
