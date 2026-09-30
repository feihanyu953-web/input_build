#!/usr/bin/env python3
"""Primitive closed-field parsing for LAMMPS GenerationSpec JSON."""

from __future__ import annotations

import math
from pathlib import Path

from lammps_spec_models import HASH_RE, JsonValue, SpecIssue


class _FieldParser:
    """Accumulate deterministic boundary issues while parsing primitive fields."""

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path.resolve()
        self.issues: list[SpecIssue] = []

    def issue(self, path: str, code: str, message: str) -> None:
        self.issues.append(SpecIssue(path=path, code=code, message=message))

    def closed(
        self,
        value: JsonValue,
        path: str,
        fields: tuple[frozenset[str], frozenset[str]],
    ) -> dict[str, JsonValue]:
        if not isinstance(value, dict):
            code = "SPEC_ROOT_TYPE" if path == "$" else "SPEC_VALUE_TYPE"
            self.issue(path, code, "object required")
            return {}
        required, optional = fields
        for key in sorted(value.keys() - required - optional):
            self.issue(f"{path}.{key}", "SPEC_UNKNOWN_FIELD", "unknown field")
        for key in sorted(required - value.keys()):
            self.issue(f"{path}.{key}", "SPEC_REQUIRED_FIELD", "required field")
        return value

    def text(self, values: dict[str, JsonValue], key: str, path: str) -> str:
        value = values.get(key)
        if not isinstance(value, str):
            if key in values:
                self.issue(f"{path}.{key}", "SPEC_VALUE_TYPE", "string required")
            return ""
        if not value.strip():
            self.issue(
                f"{path}.{key}", "SPEC_VALUE_INVALID", "non-empty string required"
            )
        return value

    def integer(
        self,
        values: dict[str, JsonValue],
        key: str,
        path: str,
        minimum: int = 0,
    ) -> int:
        value = values.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            if key in values:
                self.issue(f"{path}.{key}", "SPEC_VALUE_TYPE", "integer required")
            return 0
        if value < minimum:
            self.issue(f"{path}.{key}", "SPEC_VALUE_INVALID", "integer out of range")
        return value

    def number(
        self,
        values: dict[str, JsonValue],
        key: str,
        path: str,
        nullable: bool = False,
    ) -> float | None:
        value = values.get(key)
        if value is None and nullable:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            if key in values:
                self.issue(f"{path}.{key}", "SPEC_VALUE_TYPE", "number required")
            return None
        try:
            parsed = float(value)
        except OverflowError:
            self.issue(f"{path}.{key}", "SPEC_VALUE_INVALID", "finite number required")
            return None
        if not math.isfinite(parsed):
            self.issue(f"{path}.{key}", "SPEC_VALUE_INVALID", "finite number required")
            return None
        return parsed

    def hash_value(self, values: dict[str, JsonValue], key: str, path: str) -> str:
        value = self.text(values, key, path)
        if value and HASH_RE.fullmatch(value) is None:
            self.issue(f"{path}.{key}", "SPEC_HASH_FORMAT", "invalid sha256")
        return value

    def strings(
        self, value: JsonValue, path: str, nonempty: bool = False
    ) -> tuple[str, ...]:
        if not isinstance(value, list):
            self.issue(path, "SPEC_VALUE_TYPE", "array required")
            return ()
        result: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                self.issue(f"{path}[{index}]", "SPEC_VALUE_TYPE", "string required")
            elif not item.strip():
                self.issue(
                    f"{path}[{index}]", "SPEC_VALUE_INVALID", "non-empty string required"
                )
            else:
                result.append(item)
        if nonempty and not result:
            self.issue(path, "SPEC_VALUE_INVALID", "non-empty array required")
        return tuple(result)
