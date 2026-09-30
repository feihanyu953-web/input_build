from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Sequence

PROFILE_ROOT: Final[Path] = Path(__file__).resolve().parent

PROFILE_PRIORITY: Final[tuple[str, ...]] = (
    "mlff/mace", "interface_water", "constant_potential",
)

CONFLICT_PAIRS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("mlff/mace", "constant_potential", "PROFILE_CONFLICT_MLFF_CONP",
     "MLFF does not expose per-atom charges; constant_potential requires charges"),
)


@dataclass(frozen=True, slots=True)
class RendererExtension:
    anchor: str
    description: str
    ordering: str
    conflict_anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StaticRuleDecl:
    code: str
    severity: str
    check_id: str
    description: str


@dataclass(frozen=True, slots=True)
class CapabilityReq:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class L4EvidenceReq:
    key: str
    metric: str
    blocks_without: str


@dataclass(frozen=True, slots=True)
class ProfileContract:
    profile_id: str
    profile_version: int
    trigger_activation: str
    trigger_auto_infer: bool
    trigger_spec_conditions: tuple[str, ...]
    required_spec_fields: tuple[str, ...]
    renderer_extensions: tuple[RendererExtension, ...]
    static_rules: tuple[StaticRuleDecl, ...]
    capability_requirements: tuple[CapabilityReq, ...]
    smoke_steps: tuple[str, ...]
    smoke_checks: tuple[str, ...]
    smoke_thresholds: tuple[tuple[str, float], ...]
    l4_required_evidence: tuple[L4EvidenceReq, ...]
    l4_fail_closed: bool
    unresolved_behavior: tuple[tuple[str, str], ...]
    official_refs: tuple[str, ...]
    handoff_outputs: tuple[str, ...]
    handoff_targets: tuple[str, ...]
    source_dir: str


@dataclass(frozen=True, slots=True)
class ProfileConflict:
    profile_a: str
    profile_b: str
    conflict_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ComposedProfile:
    active_ids: tuple[str, ...]
    contracts: tuple[ProfileContract, ...]
    merged_static_rule_codes: tuple[str, ...]
    merged_capability_requirements: tuple[CapabilityReq, ...]
    merged_renderer_anchors: tuple[str, ...]
    conflicts: tuple[ProfileConflict, ...]
    has_conflict: bool


def load_profile(profile_dir: Path) -> ProfileContract:
    json_path = profile_dir / "profile.json"
    if not json_path.exists():
        raise FileNotFoundError(f"profile.json not found: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    exts = tuple(
        RendererExtension(e["anchor"], e["description"], e["ordering"],
                          tuple(e.get("conflict_anchors", [])))
        for e in data.get("renderer_extensions", [])
    )
    rules = tuple(
        StaticRuleDecl(r["code"], r["severity"], r["check_id"], r["description"])
        for r in data.get("static_rules", [])
    )
    caps = tuple(CapabilityReq(c["kind"], c["value"]) for c in data.get("capability_requirements", []))
    smoke = data.get("smoke_protocol", {})
    thresholds = smoke.get("thresholds", {})
    l4 = data.get("l4_acceptance", {})
    return ProfileContract(
        profile_id=data["profile_id"], profile_version=data["profile_version"],
        trigger_activation=data["trigger"]["activation"],
        trigger_auto_infer=data["trigger"]["auto_infer"],
        trigger_spec_conditions=tuple(data["trigger"].get("spec_conditions", [])),
        required_spec_fields=tuple(data.get("required_spec_fields", [])),
        renderer_extensions=exts, static_rules=rules, capability_requirements=caps,
        smoke_steps=tuple(smoke.get("steps", [])), smoke_checks=tuple(smoke.get("checks", [])),
        smoke_thresholds=tuple(sorted(thresholds.items())),
        l4_required_evidence=tuple(
            L4EvidenceReq(e["key"], e["metric"], e["blocks_without"])
            for e in l4.get("required_evidence", [])
        ),
        l4_fail_closed=l4.get("fail_closed", True),
        unresolved_behavior=tuple((u["missing_fact"], u["blocks_level"]) for u in data.get("unresolved_behavior", [])),
        official_refs=tuple(data.get("official_refs", [])),
        handoff_outputs=tuple(data.get("post_run_handoff", {}).get("outputs", [])),
        handoff_targets=tuple(data.get("post_run_handoff", {}).get("handoff_targets", [])),
        source_dir=str(profile_dir),
    )


def discover_profiles(root: Path | None = None) -> dict[str, ProfileContract]:
    base = root or PROFILE_ROOT
    result: dict[str, ProfileContract] = {}
    for json_path in sorted(base.rglob("profile.json")):
        contract = load_profile(json_path.parent)
        result[contract.profile_id] = contract
    return result


def _detect_conflicts(active_ids: tuple[str, ...]) -> tuple[ProfileConflict, ...]:
    id_set = set(active_ids)
    return tuple(
        ProfileConflict(a, b, code, reason)
        for a, b, code, reason in CONFLICT_PAIRS
        if a in id_set and b in id_set
    )


def activate_profiles(requested: Sequence[str], available: Mapping[str, ProfileContract] | None = None) -> ComposedProfile:
    avail = available if available is not None else discover_profiles()
    conflicts: list[ProfileConflict] = []
    valid_ids: list[str] = []
    for rid in requested:
        if rid not in avail:
            conflicts.append(ProfileConflict(rid, "", "PROFILE_UNKNOWN_ID", f"profile '{rid}' not found"))
        else:
            valid_ids.append(rid)
    conflicts.extend(_detect_conflicts(tuple(valid_ids)))
    ordered = tuple(sorted(valid_ids, key=lambda x: PROFILE_PRIORITY.index(x) if x in PROFILE_PRIORITY else len(PROFILE_PRIORITY)))
    contracts = tuple(avail[rid] for rid in ordered if rid in avail)
    rule_codes = [r.code for c in contracts for r in c.static_rules]
    caps = [cap for c in contracts for cap in c.capability_requirements]
    anchors = [e.anchor for c in contracts for e in c.renderer_extensions]
    return ComposedProfile(
        active_ids=ordered, contracts=contracts,
        merged_static_rule_codes=tuple(rule_codes),
        merged_capability_requirements=tuple(caps),
        merged_renderer_anchors=tuple(anchors),
        conflicts=tuple(conflicts), has_conflict=bool(conflicts),
    )


def _load_rules_module(contract: ProfileContract):
    rules_path = Path(contract.source_dir) / "rules.py"
    if not rules_path.exists():
        return None
    mod_name = f"profile_rules_{contract.profile_id.replace('/', '_')}"
    module_spec = importlib.util.spec_from_file_location(mod_name, rules_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[mod_name] = module
    try:
        module_spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def run_profile_static_rules(contract: ProfileContract, spec: dict, commands: list, raw_text: str = "") -> list:
    mod = _load_rules_module(contract)
    if mod is None or not hasattr(mod, "check_static"):
        return []
    return list(mod.check_static(spec, commands, raw_text))


def assess_profile_l4(contract: ProfileContract, l3_status: str, context: dict) -> tuple[str, tuple[str, ...]]:
    mod = _load_rules_module(contract)
    if mod is None or not hasattr(mod, "assess_l4"):
        return ("NOT_EVALUATED", ())
    return mod.assess_l4(l3_status, context)
