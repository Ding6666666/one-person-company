from dsh_company.capability_sources.contracts import (
    CapabilityEntry,
    CapabilitySourceDescriptor,
)
from dsh_company.capability_sources.registry import CapabilitySourceRegistry


class FakeSource:
    descriptor = CapabilitySourceDescriptor(
        id="test-skills", kind="skill", display_name="Test Skills"
    )

    def list_entries(self) -> tuple[CapabilityEntry, ...]:
        return (
            CapabilityEntry(
                ref="test-skills:review",
                source_id="test-skills",
                kind="skill",
                name="Review",
                description="Review code",
                version="1",
            ),
        )

    def import_entry(self, external_id: str) -> CapabilityEntry:
        if external_id != "review":
            raise LookupError("capability not found")
        return self.list_entries()[0]


def test_registry_lists_filters_and_imports_provider_entries() -> None:
    registry = CapabilitySourceRegistry((FakeSource(),))

    assert registry.list_sources("skill") == (FakeSource.descriptor,)
    assert registry.list_sources("tool") == ()
    assert registry.list_entries("skill")[0].ref == "test-skills:review"
    assert registry.import_entry("skill", "test-skills", "review").name == "Review"
