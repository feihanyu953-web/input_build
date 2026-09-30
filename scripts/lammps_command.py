from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class LifecycleKind(StrEnum):
    FIX = "fix"
    COMPUTE = "compute"
    DUMP = "dump"


class IssueSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    source: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    args: tuple[str, ...]
    span: SourceSpan
    raw_text: str


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    commands: tuple[Command, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    kind: LifecycleKind
    identifier: str
    group: str
    style: str
    created_at: SourceSpan
    destroyed_at: SourceSpan | None


@dataclass(frozen=True, slots=True)
class ParseIssue:
    severity: IssueSeverity
    code: str
    message: str
    span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class ParseResult:
    commands: tuple[Command, ...]
    raw_text: str
    issues: tuple[ParseIssue, ...]
    completeness: Completeness
    lifecycle: tuple[LifecycleRecord, ...]
    includes: tuple[str, ...]


def to_legacy_commands(result: ParseResult) -> list[tuple[str, list[str]]]:
    """Project ParseResult to the legacy (cmd, [args]) list shape."""
    return [(c.name, list(c.args)) for c in result.commands]


def active_lifecycle(result: ParseResult) -> tuple[LifecycleRecord, ...]:
    """Return lifecycle records still active at end of file."""
    return tuple(r for r in result.lifecycle if r.destroyed_at is None)
