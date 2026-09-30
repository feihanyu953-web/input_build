#!/usr/bin/env python3
"""Protocol-stage and modifier parsing for LAMMPS GenerationSpec JSON."""

from __future__ import annotations

from lammps_spec_fields import _FieldParser
from lammps_spec_models import (
    MODIFIERS,
    Ensemble,
    JsonValue,
    MdStage,
    MinimizeStage,
    ModifierSelection,
    ProtocolSpec,
    LammpsUnits,
)


class _ProtocolParser(_FieldParser):
    def parse_protocol(self, value: JsonValue) -> ProtocolSpec | None:
        protocol = self.closed(
            value,
            "$.protocol",
            (frozenset({"units", "timestep_fs", "stages"}), frozenset()),
        )
        units_raw = self.text(protocol, "units", "$.protocol")
        if units_raw not in LammpsUnits:
            self.issue("$.protocol.units", "SPEC_PROTOCOL_INVALID", "unsupported units")
        timestep = self.number(protocol, "timestep_fs", "$.protocol")
        if timestep is not None and timestep <= 0:
            self.issue(
                "$.protocol.timestep_fs",
                "SPEC_VALUE_INVALID",
                "positive timestep required",
            )
        stages_raw = protocol.get("stages")
        if not isinstance(stages_raw, list):
            self.issue("$.protocol.stages", "SPEC_VALUE_TYPE", "array required")
            stages_raw = []
        if not stages_raw:
            self.issue("$.protocol.stages", "SPEC_VALUE_INVALID", "stage required")
        stages: list[MinimizeStage | MdStage] = []
        stage_ids: set[str] = set()
        for index, item in enumerate(stages_raw):
            stage = self.parse_stage(item, index)
            if stage is None:
                continue
            if stage.stage_id in stage_ids:
                self.issue(
                    f"$.protocol.stages[{index}].stage_id",
                    "SPEC_STAGE_DUPLICATE_ID",
                    "duplicate stage id",
                )
            stage_ids.add(stage.stage_id)
            stages.append(stage)
        if units_raw not in LammpsUnits or timestep is None:
            return None
        return ProtocolSpec(
            units=LammpsUnits(units_raw),
            timestep_fs=timestep,
            stages=tuple(stages),
        )

    def parse_stage(
        self, value: JsonValue, index: int
    ) -> MinimizeStage | MdStage | None:
        path = f"$.protocol.stages[{index}]"
        if not isinstance(value, dict):
            self.issue(path, "SPEC_VALUE_TYPE", "object required")
            return None
        kind = value.get("kind")
        if kind == "minimize":
            return self.parse_minimize_stage(value, path)
        if kind == "md":
            return self.parse_md_stage(value, path)
        self.issue(f"{path}.kind", "SPEC_STAGE_UNKNOWN_KIND", "unknown stage kind")
        return None

    def parse_minimize_stage(
        self, value: dict[str, JsonValue], path: str
    ) -> MinimizeStage:
        stage = self.closed(
            value,
            path,
            (
                frozenset(
                    {"kind", "stage_id", "style", "etol", "ftol", "maxiter", "maxeval"}
                ),
                frozenset(),
            ),
        )
        etol = self.number(stage, "etol", path)
        ftol = self.number(stage, "ftol", path)
        return MinimizeStage(
            stage_id=self.text(stage, "stage_id", path),
            style=self.text(stage, "style", path),
            etol=etol if etol is not None else 0.0,
            ftol=ftol if ftol is not None else 0.0,
            maxiter=self.integer(stage, "maxiter", path),
            maxeval=self.integer(stage, "maxeval", path),
        )

    def parse_md_stage(self, value: dict[str, JsonValue], path: str) -> MdStage | None:
        stage = self.closed(
            value,
            path,
            (
                frozenset(
                    {
                        "kind",
                        "stage_id",
                        "ensemble",
                        "steps",
                        "temperature_start_K",
                        "temperature_stop_K",
                        "damping_fs",
                        "velocity_temperature_K",
                        "velocity_seed",
                    }
                ),
                frozenset(),
            ),
        )
        ensemble_raw = self.text(stage, "ensemble", path)
        if ensemble_raw not in Ensemble:
            self.issue(f"{path}.ensemble", "SPEC_VALUE_INVALID", "unsupported ensemble")
            return None
        thermal = tuple(
            self.number(stage, key, path, True)
            for key in ("temperature_start_K", "temperature_stop_K", "damping_fs")
        )
        velocity_temperature = self.number(stage, "velocity_temperature_K", path, True)
        velocity_seed_raw = stage.get("velocity_seed")
        if velocity_seed_raw is not None and (
            not isinstance(velocity_seed_raw, int) or isinstance(velocity_seed_raw, bool)
        ):
            self.issue(
                f"{path}.velocity_seed", "SPEC_VALUE_TYPE", "integer or null required"
            )
        velocity_seed = (
            velocity_seed_raw
            if isinstance(velocity_seed_raw, int)
            and not isinstance(velocity_seed_raw, bool)
            else None
        )
        if ensemble_raw == Ensemble.NVE and any(item is not None for item in thermal):
            self.issue(
                f"{path}.damping_fs",
                "SPEC_STAGE_NULL_FORBIDDEN",
                "nve thermal fields must be null",
            )
        if ensemble_raw != Ensemble.NVE and any(item is None for item in thermal):
            self.issue(
                f"{path}.damping_fs",
                "SPEC_STAGE_NULL_FORBIDDEN",
                "thermostat fields required",
            )
        if (velocity_temperature is None) != (velocity_seed is None):
            self.issue(
                f"{path}.velocity_seed",
                "SPEC_STAGE_NULL_FORBIDDEN",
                "velocity fields must be paired",
            )
        return MdStage(
            stage_id=self.text(stage, "stage_id", path),
            ensemble=Ensemble(ensemble_raw),
            steps=self.integer(stage, "steps", path),
            temperature_start_K=thermal[0],
            temperature_stop_K=thermal[1],
            damping_fs=thermal[2],
            velocity_temperature_K=velocity_temperature,
            velocity_seed=velocity_seed,
        )

    def parse_modifiers(
        self, value: JsonValue, protocol: ProtocolSpec | None
    ) -> tuple[ModifierSelection, ...]:
        if not isinstance(value, list):
            self.issue("$.modifiers", "SPEC_VALUE_TYPE", "array required")
            return ()
        stage_ids = {stage.stage_id for stage in protocol.stages} if protocol else set()
        seen: set[tuple[str, str | None]] = set()
        result: list[ModifierSelection] = []
        for index, item in enumerate(value):
            path = f"$.modifiers[{index}]"
            entry = self.closed(
                item, path, (frozenset({"name", "stage_id"}), frozenset())
            )
            name = self.text(entry, "name", path)
            stage_id_raw = entry.get("stage_id")
            if name not in MODIFIERS:
                self.issue(
                    f"{path}.name", "SPEC_MODIFIER_UNKNOWN_NAME", "unknown modifier"
                )
            if stage_id_raw is not None and not isinstance(stage_id_raw, str):
                self.issue(
                    f"{path}.stage_id",
                    "SPEC_VALUE_TYPE",
                    "string or null required",
                )
            stage_id = stage_id_raw if isinstance(stage_id_raw, str) else None
            if stage_id is not None and stage_id not in stage_ids:
                self.issue(
                    f"{path}.stage_id", "SPEC_MODIFIER_STAGE_REF", "unknown stage"
                )
            pair = (name, stage_id)
            if pair in seen:
                self.issue(path, "SPEC_MODIFIER_DUPLICATE", "duplicate modifier selection")
            seen.add(pair)
            result.append(ModifierSelection(name=name, stage_id=stage_id))
        return tuple(result)
