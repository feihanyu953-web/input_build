"""Deterministic ID allocator for LAMMPS fix/compute/dump namespaces.

Three independent namespaces (fix, compute, dump). Reserved IDs come from the
template/modifier text in (anchor_ordinal, source_declaration_order); collisions
within one namespace are repaired deterministically by renumbering the later
command to the next available integer; cross-namespace reuse is legal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True, slots=True)
class IdAllocation:
    namespace: str        # "fix" / "compute" / "dump"
    id: str               # final assigned ID
    source: str           # base_template / modifier / spec
    allocated: bool       # False = reserved (pre-existing), True = newly allocated
    replacement: str | None  # original ID before repair (None if not repaired)
    before: str | None    # same as replacement, for ConflictDecision compat


_NAMESPACES: Final[tuple[str, ...]] = ("fix", "compute", "dump")


@dataclass
class _NamespaceState:
    reserved: list[tuple[str, str, int, str]] = field(default_factory=list)
    # (id, source, order, before)  before=None means not repaired
    _reserved_set: set[str] = field(default_factory=set)
    _next_counter: int = 1

    def reserve(self, id_value: str, source: str, order: int) -> None:
        self.reserved.append((id_value, source, order, None))
        self._reserved_set.add(id_value)

    def allocate(self, source: str, order: int) -> str:
        while str(self._next_counter) in self._reserved_set:
            self._next_counter += 1
        new_id = str(self._next_counter)
        self._reserved_set.add(new_id)
        self.reserved.append((new_id, source, order, None))
        self._next_counter += 1
        return new_id

    def finalize(self) -> list[IdAllocation]:
        result: list[IdAllocation] = []
        used: set[str] = set()
        for id_value, source, order, _ in self.reserved:
            if id_value in used:
                repaired = self._next_available(used)
                used.add(repaired)
                result.append(IdAllocation(
                    namespace="", id=repaired, source=source,
                    allocated=True, replacement=id_value, before=id_value,
                ))
            else:
                used.add(id_value)
                result.append(IdAllocation(
                    namespace="", id=id_value, source=source,
                    allocated=False, replacement=None, before=None,
                ))
        return result

    def _next_available(self, used: set[str]) -> str:
        n = 1
        while str(n) in used:
            n += 1
        return str(n)


class IdAllocator:
    """Deterministic ID allocator for fix/compute/dump namespaces."""

    def __init__(self) -> None:
        self._states: dict[str, _NamespaceState] = {
            ns: _NamespaceState() for ns in _NAMESPACES
        }

    def reserve(
        self, namespace: str, id_value: str, source: str, order: int
    ) -> None:
        if namespace not in self._states:
            raise ValueError(f"UNKNOWN_NAMESPACE:{namespace}")
        self._states[namespace].reserve(id_value, source, order)

    def allocate(self, namespace: str, source: str, order: int) -> str:
        if namespace not in self._states:
            raise ValueError(f"UNKNOWN_NAMESPACE:{namespace}")
        return self._states[namespace].allocate(source, order)

    def finalize(self) -> tuple[IdAllocation, ...]:
        result: list[IdAllocation] = []
        for ns in _NAMESPACES:
            for alloc in self._states[ns].finalize():
                result.append(IdAllocation(
                    namespace=ns, id=alloc.id, source=alloc.source,
                    allocated=alloc.allocated, replacement=alloc.replacement,
                    before=alloc.before,
                ))
        return tuple(result)
