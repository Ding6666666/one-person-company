from collections.abc import Iterable

from .contracts import CapabilityEntry, CapabilityKind, CapabilitySource, CapabilitySourceDescriptor


class CapabilitySourceRegistry:
    def __init__(self, sources: Iterable[CapabilitySource] = ()) -> None:
        self._sources = tuple(sources)
        ids = tuple(source.descriptor.id for source in self._sources)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability source")

    def list_sources(self, kind: CapabilityKind) -> tuple[CapabilitySourceDescriptor, ...]:
        return tuple(
            source.descriptor for source in self._sources if source.descriptor.kind == kind
        )

    def list_entries(self, kind: CapabilityKind) -> tuple[CapabilityEntry, ...]:
        return tuple(
            entry
            for source in self._sources
            if source.descriptor.kind == kind
            for entry in source.list_entries()
        )

    def import_entry(
        self, kind: CapabilityKind, source_id: str, external_id: str
    ) -> CapabilityEntry:
        source = next(
            (
                candidate
                for candidate in self._sources
                if candidate.descriptor.kind == kind and candidate.descriptor.id == source_id
            ),
            None,
        )
        if source is None:
            raise LookupError("capability source not found")
        return source.import_entry(external_id)
