#!/usr/bin/env python3
"""Artifact, provenance, unresolved, and runtime spec parsing."""

from __future__ import annotations

from lammps_evidence import LevelName, UnresolvedItem
from lammps_spec_models import SOURCES, ArtifactSpec, JsonValue, ProvenanceSpec
from lammps_spec_protocol import _ProtocolParser


class _MetadataParser(_ProtocolParser):
    def parse_artifacts(self, value: JsonValue) -> tuple[ArtifactSpec, ...]:
        if not isinstance(value, list):
            self.issue("$.potential.artifacts", "SPEC_VALUE_TYPE", "array required")
            return ()
        result: list[ArtifactSpec] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.potential.artifacts[{index}]"
            entry = self.closed(
                item, path, (frozenset({"path", "sha256"}), frozenset())
            )
            declared = self.text(entry, "path", path)
            expected = self.hash_value(entry, "sha256", path)
            if declared in seen:
                self.issue(
                    f"{path}.path", "SPEC_DUPLICATE_VALUE", "duplicate artifact path"
                )
            seen.add(declared)
            result.append(
                ArtifactSpec(
                    declared_path=declared,
                    resolved_path=(self.source_path.parent / declared).resolve(),
                    expected_sha256=expected,
                )
            )
        return tuple(result)

    def parse_provenance(self, value: JsonValue) -> ProvenanceSpec:
        entry = self.closed(
            value,
            "$.provenance",
            (
                frozenset({"structure", "type_map", "potential", "protocol"}),
                frozenset(),
            ),
        )
        keys = ("structure", "type_map", "potential", "protocol")
        values = tuple(self.text(entry, key, "$.provenance") for key in keys)
        for key, source in zip(keys, values, strict=True):
            if source not in SOURCES:
                self.issue(
                    f"$.provenance.{key}", "SPEC_VALUE_INVALID", "unknown provenance"
                )
        return ProvenanceSpec(
            structure=values[0],
            type_map=values[1],
            potential=values[2],
            protocol=values[3],
        )

    def parse_unresolved(self, value: JsonValue) -> tuple[UnresolvedItem, ...]:
        if not isinstance(value, list):
            self.issue("$.unresolved", "SPEC_VALUE_TYPE", "array required")
            return ()
        result: list[UnresolvedItem] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            path = f"$.unresolved[{index}]"
            entry = self.closed(
                item,
                path,
                (frozenset({"key", "blocks_level", "reason"}), frozenset()),
            )
            key = self.text(entry, "key", path)
            blocks = self.text(entry, "blocks_level", path)
            if key in seen:
                self.issue(
                    f"{path}.key", "SPEC_DUPLICATE_VALUE", "duplicate unresolved key"
                )
            seen.add(key)
            if blocks not in LevelName:
                self.issue(
                    f"{path}.blocks_level", "SPEC_VALUE_INVALID", "unknown level"
                )
            else:
                result.append(
                    UnresolvedItem(
                        key=key,
                        blocks_level=LevelName(blocks),
                        reason=self.text(entry, "reason", path),
                    )
                )
        return tuple(result)

    def parse_runtime(self, value: JsonValue) -> None:
        entry = self.closed(
            value,
            "$.runtime",
            (
                frozenset({"binary", "version", "packages", "target"}),
                frozenset(),
            ),
        )
        for key in ("binary", "version", "target"):
            self.text(entry, key, "$.runtime")
        packages = self.strings(entry.get("packages"), "$.runtime.packages")
        if len(packages) != len(set(packages)):
            self.issue("$.runtime.packages", "SPEC_DUPLICATE_VALUE", "duplicate value")
