#!/usr/bin/env python3
"""Closed semantic parser for LAMMPS GenerationSpec JSON."""

from __future__ import annotations

import re

from lammps_spec_metadata import _MetadataParser
from lammps_spec_models import GenerationSpec, JsonValue


class _Parser(_MetadataParser):
    def parse(self, raw: JsonValue) -> GenerationSpec | None:
        top = self.closed(
            raw,
            "$",
            (
                frozenset(
                    {
                        "schema_version",
                        "code",
                        "task",
                        "input_file",
                        "system",
                        "potential",
                        "protocol",
                        "profiles",
                        "modifiers",
                        "provenance",
                        "unresolved",
                    }
                ),
                frozenset({"runtime"}),
            ),
        )
        schema_version = top.get("schema_version")
        if "schema_version" in top and type(schema_version) is not int:
            self.issue("$.schema_version", "SPEC_VALUE_TYPE", "integer required")
        elif "schema_version" in top and schema_version != 1:
            self.issue(
                "$.schema_version", "SPEC_VALUE_INVALID", "schema version must be 1"
            )
        if top.get("code") != "lammps":
            self.issue("$.code", "SPEC_VALUE_INVALID", "code must be lammps")
        task = self.text(top, "task", "$")
        input_declared = self.text(top, "input_file", "$")

        system = self.closed(
            top.get("system"),
            "$.system",
            (
                frozenset(
                    {
                        "data_file",
                        "data_sha256",
                        "atom_count",
                        "atom_types",
                        "type_map",
                        "has_h",
                        "atom_style",
                        "periodicity",
                    }
                ),
                frozenset(),
            ),
        )
        data_declared = self.text(system, "data_file", "$.system")
        data_sha256 = self.hash_value(system, "data_sha256", "$.system")
        atom_count = self.integer(system, "atom_count", "$.system", 1)
        atom_types = self.integer(system, "atom_types", "$.system", 1)
        type_map = self.parse_type_map(system.get("type_map"), atom_types)
        has_h_raw = system.get("has_h")
        if not isinstance(has_h_raw, bool):
            self.issue("$.system.has_h", "SPEC_VALUE_TYPE", "boolean required")
        has_h = has_h_raw if isinstance(has_h_raw, bool) else False
        if has_h != any(element == "H" for _, element in type_map):
            self.issue("$.system.has_h", "SPEC_HAS_H_MISMATCH", "hydrogen flag mismatch")
        atom_style = self.text(system, "atom_style", "$.system")
        periodicity = self.strings(system.get("periodicity"), "$.system.periodicity")
        if len(periodicity) != 3 or any(
            item not in {"p", "f", "s", "m"} for item in periodicity
        ):
            self.issue(
                "$.system.periodicity",
                "SPEC_VALUE_INVALID",
                "three boundary flags required",
            )

        potential = self.closed(
            top.get("potential"),
            "$.potential",
            (
                frozenset(
                    {"family", "pair_style", "pair_coeff", "artifacts", "type_elements"}
                ),
                frozenset(),
            ),
        )
        family = self.text(potential, "family", "$.potential")
        pair_style = self.text(potential, "pair_style", "$.potential")
        pair_coeff = self.text(potential, "pair_coeff", "$.potential")
        artifacts = self.parse_artifacts(potential.get("artifacts"))
        type_elements = self.strings(
            potential.get("type_elements"), "$.potential.type_elements", True
        )
        if type_elements != tuple(element for _, element in type_map):
            self.issue(
                "$.potential.type_elements",
                "SPEC_TYPE_ELEMENTS_MISMATCH",
                "element order mismatch",
            )

        protocol = self.parse_protocol(top.get("protocol"))
        profiles = self.strings(top.get("profiles"), "$.profiles", True)
        if len(profiles) != len(set(profiles)):
            self.issue("$.profiles", "SPEC_DUPLICATE_VALUE", "duplicate value")
        modifiers = self.parse_modifiers(top.get("modifiers"), protocol)
        provenance = self.parse_provenance(top.get("provenance"))
        unresolved = self.parse_unresolved(top.get("unresolved"))
        if "runtime" in top:
            self.parse_runtime(top["runtime"])
        if self.issues or protocol is None:
            return None
        return GenerationSpec(
            source_path=self.source_path,
            task=task,
            input_declared_path=input_declared,
            input_file=(self.source_path.parent / input_declared).resolve(),
            data_declared_path=data_declared,
            data_file=(self.source_path.parent / data_declared).resolve(),
            data_sha256=data_sha256,
            atom_count=atom_count,
            atom_types=atom_types,
            type_map=type_map,
            has_h=has_h,
            atom_style=atom_style,
            periodicity=(periodicity[0], periodicity[1], periodicity[2]),
            potential_family=family,
            pair_style=pair_style,
            pair_coeff=pair_coeff,
            artifacts=artifacts,
            type_elements=type_elements,
            profiles=profiles,
            protocol=protocol,
            modifiers=modifiers,
            provenance=provenance,
            unresolved=unresolved,
        )

    def parse_type_map(
        self, value: JsonValue, atom_types: int
    ) -> tuple[tuple[int, str], ...]:
        if not isinstance(value, dict):
            self.issue("$.system.type_map", "SPEC_VALUE_TYPE", "object required")
            return ()
        size_matches = len(value) == atom_types
        if not size_matches:
            self.issue(
                "$.system.type_map",
                "SPEC_TYPE_MAP_MISMATCH",
                "type map must cover atom types",
            )
        elements: dict[str, str] = {}
        for key, element in value.items():
            if re.fullmatch(r"[1-9][0-9]*", key) is None:
                self.issue(
                    f"$.system.type_map.{key}",
                    "SPEC_VALUE_INVALID",
                    "positive numeric key required",
                )
            elements[key] = self.text({key: element}, key, "$.system.type_map")
        if not size_matches:
            return ()
        expected_keys = {str(index) for index in range(1, len(value) + 1)}
        if value.keys() != expected_keys:
            self.issue(
                "$.system.type_map",
                "SPEC_TYPE_MAP_MISMATCH",
                "type map must cover atom types",
            )
            return ()
        return tuple(
            (index, elements[str(index)]) for index in range(1, len(value) + 1)
        )
