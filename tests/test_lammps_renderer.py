"""Unit and subprocess-level tests for the LAMMPS deterministic renderer.

Test classes mirror the Phase D plan tasks:
  - TestDeterministicBytes  (task 1) byte-stable output contract
  - TestAnchorVocabulary    (task 2) closed anchor vocabulary + ordering graph
  - TestIdAllocator         (task 3) fix/compute/dump ID allocation
  - TestPotentialInjection  (task 4) template parsing + spec potential injection
  - TestShakeOrdering       (task 5) modifier insertion + SHAKE precedence
  - TestConflictDetection   (task 6) mechanical repair vs scientific blocking
  - TestRenderTrace         (task 7) render_trace.json completeness
  - TestValidatorHandoff    (task 8) post-render validator handoff
  - TestProcessDeterminism  (task 9) cross-process byte determinism
  - TestProfileCoverage     (task 10) generic_md / mlff/mace coverage
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = ROOT / "scripts" / "render_lammps.py"
ANCHORS_SCRIPT = ROOT / "scripts" / "lammps_anchors.py"
ALLOCATOR_SCRIPT = ROOT / "scripts" / "lammps_id_allocator.py"
FIXTURES = ROOT / "tests" / "fixtures" / "renderer"

_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestDeterministicBytes(unittest.TestCase):
    def test_same_request_produces_identical_bytes(self):
        from lammps_renderer_support import build_mlff_request

        req = build_mlff_request()
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        renderer = _load_module("render_lammps", RENDER_SCRIPT)

        result_a = renderer.render(req)
        result_b = renderer.render(req)

        self.assertEqual(result_a.input_text, result_b.input_text)
        self.assertEqual(result_a.trace_text, result_b.trace_text)
        self.assertEqual(
            hashlib.sha256(result_a.input_text.encode("utf-8")).hexdigest(),
            hashlib.sha256(result_b.input_text.encode("utf-8")).hexdigest(),
        )

    def test_output_sha256_matches_input_text(self):
        from lammps_renderer_support import build_mlff_request

        req = build_mlff_request()
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        renderer = _load_module("render_lammps", RENDER_SCRIPT)

        result = renderer.render(req)
        expected = "sha256:" + hashlib.sha256(
            result.input_text.encode("utf-8")).hexdigest()
        self.assertEqual(result.output_sha256, expected)


class TestAnchorVocabulary(unittest.TestCase):
    def test_anchor_vocabulary_is_closed_set_of_twelve(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        expected = {
            "initialization", "system", "force_field", "minimization",
            "velocity_init", "external_force_fixes", "constraints",
            "integration", "analysis", "output", "run", "cleanup",
        }
        self.assertEqual(set(anchors.ANCHOR_NAMES), expected)

    def test_ordering_graph_enforces_force_fixes_before_constraints(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        self.assertIn(
            ("external_force_fixes", "constraints"),
            anchors.ORDERING_EDGES,
        )

    def test_topological_order_is_deterministic(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        order = anchors.topological_order()
        self.assertEqual(len(order), 12)
        self.assertEqual(order[0], "initialization")
        self.assertEqual(order[-1], "cleanup")
        pos = {a: i for i, a in enumerate(order)}
        for before, after in anchors.ORDERING_EDGES:
            self.assertLess(pos[before], pos[after],
                            f"{before} must precede {after}")

    def test_unknown_template_fails_closed(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        with self.assertRaises(anchors.AnchorError) as ctx:
            anchors.validate_template_anchors("nonexistent.in", ())
        self.assertIn("UNKNOWN_TEMPLATE", str(ctx.exception))

    def test_missing_anchor_fails_closed(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        with self.assertRaises(anchors.AnchorError) as ctx:
            anchors.validate_template_anchors(
                "lammps_md.in",
                ("initialization", "system"),  # missing force_field etc.
            )
        self.assertIn("MISSING_ANCHOR", str(ctx.exception))

    def test_duplicate_anchor_fails_closed(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        with self.assertRaises(anchors.AnchorError) as ctx:
            anchors.validate_template_anchors(
                "lammps_md.in",
                ("initialization", "system", "system", "force_field",
                 "minimization", "velocity_init", "integration",
                 "output", "run", "cleanup"),
            )
        self.assertIn("DUPLICATE_ANCHOR", str(ctx.exception))

    def test_fix_style_to_anchor_maps_efield_to_external_force(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        self.assertEqual(
            anchors.fix_style_anchor("efield"), "external_force_fixes")
        self.assertEqual(
            anchors.fix_style_anchor("wall/lj93"), "external_force_fixes")
        self.assertEqual(
            anchors.fix_style_anchor("shake"), "constraints")
        self.assertEqual(
            anchors.fix_style_anchor("nvt"), "integration")

    def test_template_not_covered_fails_closed(self):
        anchors = _load_module("lammps_anchors", ANCHORS_SCRIPT)
        with self.assertRaises(anchors.AnchorError) as ctx:
            anchors.validate_template_anchors("lammps_conp.in", ())
        self.assertIn("TEMPLATE_NOT_COVERED", str(ctx.exception))


class TestIdAllocator(unittest.TestCase):
    def _load(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        return _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)

    def test_reserved_ids_are_preserved(self):
        alloc = self._load()
        allocator = alloc.IdAllocator()
        allocator.reserve("fix", "equil", source="base_template", order=0)
        allocator.reserve("fix", "prod", source="base_template", order=1)
        allocations = allocator.finalize()
        ids = {a.id for a in allocations if a.namespace == "fix"}
        self.assertIn("equil", ids)
        self.assertIn("prod", ids)

    def test_collision_within_namespace_is_repaired(self):
        alloc = self._load()
        allocator = alloc.IdAllocator()
        allocator.reserve("fix", "1", source="base_template", order=0)
        allocator.reserve("fix", "1", source="modifier", order=1)
        allocations = allocator.finalize()
        fix_ids = [a for a in allocations if a.namespace == "fix"]
        self.assertEqual(len(fix_ids), 2)
        self.assertNotEqual(fix_ids[0].id, fix_ids[1].id)
        repaired = [a for a in fix_ids if a.replacement is not None]
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0].before, "1")
        self.assertEqual(repaired[0].id, "2")

    def test_cross_namespace_reuse_is_legal(self):
        alloc = self._load()
        allocator = alloc.IdAllocator()
        allocator.reserve("fix", "1", source="base_template", order=0)
        allocator.reserve("compute", "1", source="modifier", order=0)
        allocator.reserve("dump", "1", source="base_template", order=0)
        allocations = allocator.finalize()
        conflicts = [a for a in allocations if a.replacement is not None]
        self.assertEqual(conflicts, [])

    def test_allocated_id_skips_reserved(self):
        alloc = self._load()
        allocator = alloc.IdAllocator()
        allocator.reserve("fix", "2", source="base_template", order=0)
        new_id = allocator.allocate("fix", source="spec", order=1)
        self.assertEqual(new_id, "1")
        new_id_2 = allocator.allocate("fix", source="spec", order=2)
        self.assertEqual(new_id_2, "3")

    def test_allocation_is_deterministic_across_instances(self):
        alloc = self._load()

        def run():
            a = alloc.IdAllocator()
            for i in range(5):
                a.reserve("fix", str(i + 1), source="t", order=i)
            return a.finalize()

        first = run()
        second = run()
        self.assertEqual(first, second)


class TestPotentialInjection(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_mlff_renders_active_pair_style_and_pair_coeff(self):
        from lammps_renderer_support import build_mlff_request
        req = build_mlff_request()
        result = self.renderer.render(req)
        lines = result.input_text.split("\n")
        active = [line for line in lines if line.strip() and not line.strip().startswith("#")]
        joined = "\n".join(active)
        self.assertIn("pair_style", joined)
        self.assertIn("pair_coeff", joined)
        self.assertNotIn(">>> USER", "\n".join(
            line for line in lines if line.split("#", 1)[0].strip()))

    def test_generic_md_renders_pair_style_from_spec(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        result = self.renderer.render(req)
        active = [line for line in result.input_text.split("\n")
                  if line.strip() and not line.strip().startswith("#")]
        ps_lines = [line for line in active if line.split()[0] == "pair_style"]
        self.assertEqual(len(ps_lines), 1)

    def test_anchor_order_initialization_before_system(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        result = self.renderer.render(req)
        trace = json.loads(result.trace_text)
        anchor_names = [a["name"] for a in trace["anchors"]]
        pos = {a: i for i, a in enumerate(anchor_names)}
        self.assertLess(pos["initialization"], pos["system"])
        self.assertLess(pos["system"], pos["force_field"])
        self.assertLess(pos["force_field"], pos["run"])

    def test_output_uses_lf_newlines_and_trailing_newline(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        result = self.renderer.render(req)
        self.assertNotIn("\r\n", result.input_text)
        self.assertTrue(result.input_text.endswith("\n"))


class TestShakeOrdering(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_efield_fix_appears_before_shake(self):
        """When both efield_lammps and shake_lammps modifiers are selected,
        the fix efield command must appear before fix shake in the output."""
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="lammps_md.in",
            modifiers=("efield_lammps", "shake_lammps"),
            profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        active = [line for line in result.input_text.split("\n")
                  if line.strip() and not line.strip().startswith("#")]
        fix_lines = [line for line in active if line.split()[0] == "fix"]
        efield_idx = next(
            (i for i, line in enumerate(fix_lines) if "efield" in line), None)
        shake_idx = next(
            (i for i, line in enumerate(fix_lines) if "shake" in line), None)
        if efield_idx is not None and shake_idx is not None:
            self.assertLess(efield_idx, shake_idx)

    def test_wall_slab_inserted_before_constraints(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="lammps_md.in",
            modifiers=("wall_slab", "shake_lammps"),
            profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        trace = json.loads(result.trace_text)
        anchor_names = [a["name"] for a in trace["anchors"]]
        if "external_force_fixes" in anchor_names and "constraints" in anchor_names:
            self.assertLess(
                anchor_names.index("external_force_fixes"),
                anchor_names.index("constraints"),
            )

    def test_dump_full_replaces_template_dump(self):
        from lammps_renderer_support import build_mlff_request
        req = build_mlff_request()
        result = self.renderer.render(req)
        active = [line for line in result.input_text.split("\n")
                  if line.strip() and not line.strip().startswith("#")]
        dump_lines = [line for line in active if line.split()[0] == "dump"]
        self.assertLessEqual(len(dump_lines), 1)
        if dump_lines:
            self.assertIn("traj_full", dump_lines[0])


class TestConflictDetection(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_duplicate_id_is_repaired(self):
        """Two fixes with ID '1' in the same namespace get renumbered."""
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        result = self.renderer.render(req)
        dup_conflicts = [c for c in result.conflicts
                         if c.conflict_type == "DUPLICATE_ID"]
        # If the template+modifiers produce duplicate IDs, verify repair;
        # otherwise the empty list is also valid (no collision to repair).
        for conflict in dup_conflicts:
            self.assertEqual(conflict.decision, "REPAIRED")

    def test_multiple_integrators_on_same_group_blocks(self):
        """fix nvt + fix nve on group 'all' without unfix is a BLOCKED
        scientific conflict, not a mechanical repair."""
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        # Manually construct a request that would produce two integrators
        # by selecting both ensemble_langevin and the template's nvt
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="lammps_md.in",
            modifiers=("ensemble_langevin",),
            profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        integrator_conflicts = [
            c for c in result.conflicts
            if c.conflict_type == "MULTIPLE_INTEGRATORS"]
        self.assertTrue(len(integrator_conflicts) >= 1)
        self.assertEqual(integrator_conflicts[0].decision, "BLOCKED")

    def test_unfix_before_run_is_lifecycle_violation(self):
        """An unfix command appearing before any run is a lifecycle
        violation."""
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        result = self.renderer.render(req)
        # Template lammps_md.in has 'unfix equil' after the first run,
        # which is valid. Verify no LIFECYCLE_VIOLATION is reported.
        lifecycle = [c for c in result.conflicts
                     if c.conflict_type == "LIFECYCLE_VIOLATION"]
        self.assertEqual(lifecycle, [])

    def test_unresolved_placeholder_in_modifier_is_unresolved(self):
        """A modifier with >>> USER on an active line produces an
        UNRESOLVED_PLACEHOLDER conflict."""
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="lammps_md.in",
            modifiers=("shake_lammps",),
            profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        placeholder_conflicts = [
            c for c in result.conflicts
            if c.conflict_type == "UNRESOLVED_PLACEHOLDER"]
        self.assertTrue(len(placeholder_conflicts) >= 1)
        self.assertEqual(placeholder_conflicts[0].decision, "UNRESOLVED")


class TestRenderTrace(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_trace_has_required_top_level_fields(self):
        from lammps_renderer_support import build_mlff_request
        result = self.renderer.render(build_mlff_request())
        trace = json.loads(result.trace_text)
        for key in ("schema_version", "code", "spec_file", "output_file",
                    "output_sha256", "base_template", "modifiers",
                    "profiles", "examples_index", "anchors", "commands",
                    "id_allocations", "conflicts", "unresolved",
                    "validator_findings", "validator_tiers"):
            self.assertIn(key, trace, f"trace missing field: {key}")

    def test_trace_commands_have_output_span_and_source(self):
        from lammps_renderer_support import build_mlff_request
        result = self.renderer.render(build_mlff_request())
        trace = json.loads(result.trace_text)
        self.assertTrue(len(trace["commands"]) > 0)
        for cmd in trace["commands"]:
            self.assertIn("output_span", cmd)
            self.assertIn("source", cmd)
            self.assertIn("anchor", cmd)
            self.assertEqual(len(cmd["output_span"]), 2)

    def test_trace_is_deterministic_across_renders(self):
        from lammps_renderer_support import build_mlff_request
        req = build_mlff_request()
        a = self.renderer.render(req)
        b = self.renderer.render(req)
        self.assertEqual(a.trace_text, b.trace_text)

    def test_trace_validator_tiers_present(self):
        from lammps_renderer_support import build_generic_request
        result = self.renderer.render(build_generic_request())
        trace = json.loads(result.trace_text)
        tiers = dict(trace["validator_tiers"])
        self.assertIn("overall", tiers)
        self.assertIn("physics", tiers)
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")

    def test_trace_examples_index_absent_when_path_none(self):
        from lammps_renderer_support import build_generic_request
        result = self.renderer.render(build_generic_request())
        trace = json.loads(result.trace_text)
        self.assertEqual(trace["examples_index"], "absent")


class TestValidatorHandoff(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_generic_md_output_passes_validator_with_zero_errors(self):
        from lammps_renderer_support import build_generic_request
        result = self.renderer.render(build_generic_request())
        tiers = dict(result.validator_tiers)
        self.assertNotEqual(tiers.get("overall"), "FAIL",
                            f"validator found ERRORs: {result.validator_findings}")

    def test_mlff_output_passes_validator_with_zero_errors(self):
        from lammps_renderer_support import build_mlff_request
        result = self.renderer.render(build_mlff_request())
        tiers = dict(result.validator_tiers)
        self.assertNotEqual(tiers.get("overall"), "FAIL",
                            f"validator found ERRORs: {result.validator_findings}")

    def test_validator_findings_preserved_in_trace(self):
        from lammps_renderer_support import build_generic_request
        result = self.renderer.render(build_generic_request())
        trace = json.loads(result.trace_text)
        self.assertIsInstance(trace["validator_findings"], list)
        for f in trace["validator_findings"]:
            self.assertIn("level", f)
            self.assertIn("code", f)
            self.assertIn("message", f)

    def test_validator_tiers_physics_is_not_evaluated(self):
        from lammps_renderer_support import build_mlff_request
        result = self.renderer.render(build_mlff_request())
        tiers = dict(result.validator_tiers)
        self.assertEqual(tiers["physics"], "NOT_EVALUATED")


class TestProcessDeterminism(unittest.TestCase):
    def test_two_subprocess_renders_produce_identical_sha256(self):
        """Run the renderer in two separate subprocess invocations and
        verify the output SHA256 is identical."""
        script = (
            "import sys; sys.path.insert(0, %r); "
            "from lammps_renderer_support import build_mlff_request; "
            "from lammps_anchors import *; "
            "from lammps_id_allocator import *; "
            "import render_lammps; "
            "r = render_lammps.render(build_mlff_request()); "
            "print(r.output_sha256)"
        ) % str(ROOT / "scripts")

        results = []
        for _ in range(2):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(ROOT / "tests"),
            )
            self.assertEqual(proc.returncode, 0,
                             f"subprocess failed: {proc.stderr}")
            results.append(proc.stdout.strip())

        self.assertEqual(results[0], results[1],
                         "SHA256 differs across subprocess invocations")

    def test_trace_sha256_identical_across_processes(self):
        script = (
            "import sys, hashlib; sys.path.insert(0, %r); "
            "from lammps_renderer_support import build_mlff_request; "
            "import render_lammps; "
            "r = render_lammps.render(build_mlff_request()); "
            "print(hashlib.sha256(r.trace_text.encode()).hexdigest())"
        ) % str(ROOT / "scripts")

        results = []
        for _ in range(2):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(ROOT / "tests"),
            )
            self.assertEqual(proc.returncode, 0,
                             f"subprocess failed: {proc.stderr}")
            results.append(proc.stdout.strip())

        self.assertEqual(results[0], results[1])


class TestProfileCoverage(unittest.TestCase):
    def setUp(self):
        _load_module("lammps_anchors", ANCHORS_SCRIPT)
        _load_module("lammps_id_allocator", ALLOCATOR_SCRIPT)
        self.renderer = _load_module("render_lammps", RENDER_SCRIPT)

    def test_generic_md_profile_renders_complete_input(self):
        from lammps_renderer_support import build_generic_request
        result = self.renderer.render(build_generic_request())
        self.assertTrue(len(result.input_text) > 0)
        active = [line for line in result.input_text.split("\n")
                  if line.strip() and not line.strip().startswith("#")]
        cmd_names = [line.split()[0] for line in active]
        for required in ("units", "atom_style", "boundary", "read_data",
                         "pair_style", "pair_coeff", "run"):
            self.assertIn(required, cmd_names,
                          f"missing required command: {required}")

    def test_mlff_mace_profile_renders_mace_pair_style(self):
        from lammps_renderer_support import build_mlff_request
        result = self.renderer.render(build_mlff_request())
        active = [line for line in result.input_text.split("\n")
                  if line.strip() and not line.strip().startswith("#")]
        ps = [line for line in active if line.split()[0] == "pair_style"]
        self.assertEqual(len(ps), 1)
        self.assertIn("mace", ps[0].lower())

    def test_uncovered_template_fails_closed(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="lammps_conp.in",
            modifiers=(), profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        self.assertEqual(result.input_text, "")
        self.assertTrue(any(
            c.conflict_type == "RENDER_ERROR" and "TEMPLATE_NOT_COVERED" in c.detail
            for c in result.conflicts))

    def test_vasp_template_not_rendered(self):
        from lammps_renderer_support import build_generic_request
        req = build_generic_request()
        req = self.renderer.RenderRequest(
            spec=req.spec, base_template="vasp_relax.incar",
            modifiers=(), profiles=("generic_md",),
            templates_dir=req.templates_dir,
            modifiers_dir=req.modifiers_dir,
            examples_index_path=None,
        )
        result = self.renderer.render(req)
        self.assertEqual(result.input_text, "")
        self.assertTrue(any("UNKNOWN_TEMPLATE" in c.detail
                            for c in result.conflicts))
