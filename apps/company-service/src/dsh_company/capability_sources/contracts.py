from dataclasses import dataclass
from typing import Literal, Protocol

CapabilityKind = Literal["skill", "tool"]


@dataclass(frozen=True, slots=True)
class CapabilitySourceDescriptor:
    id: str
    kind: CapabilityKind
    display_name: str


@dataclass(frozen=True, slots=True)
class CapabilityEntry:
    ref: str
    source_id: str
    kind: CapabilityKind
    name: str
    description: str
    version: str
    required_actions: tuple[str, ...] = ()


class CapabilitySource(Protocol):
    descriptor: CapabilitySourceDescriptor

    def list_entries(self) -> tuple[CapabilityEntry, ...]: ...

    def import_entry(self, external_id: str) -> CapabilityEntry: ...
