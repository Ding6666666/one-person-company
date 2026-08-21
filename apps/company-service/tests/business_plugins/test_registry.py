from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from dsh_company.business_plugins.manifest import (
    BusinessPluginManifest,
    EmployeeSlot,
    PluginAction,
    TemplateEdge,
    TemplateNode,
    WorkTemplate,
)
from dsh_company.business_plugins.registry import (
    BusinessPluginRegistry,
    InvalidPluginManifest,
)
from dsh_company.domain.capabilities import CapabilityLevel
from dsh_company.domain.work import WorkEdgeKind
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from pydantic import ValidationError
from sqlalchemy import event


def _manifest(*, version: str = "0.1.0") -> BusinessPluginManifest:
    return BusinessPluginManifest(
        plugin_id="content-studio",
        version=version,
        display_name="Content Studio",
        capability_actions=(
            PluginAction(
                action="content-studio.publish_draft",
                level=CapabilityLevel.L3,
            ),
        ),
        templates=(
            WorkTemplate(
                template_id="campaign",
                display_name="Research and publish",
                employee_slots=(EmployeeSlot(slot_id="author"),),
                nodes=(
                    TemplateNode(
                        key="draft",
                        employee_slot="author",
                        objective="Draft the article",
                        acceptance_criteria=("Ready for review",),
                    ),
                ),
                edges=(),
            ),
        ),
    )


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[BusinessPluginRegistry]:
    engine = create_sqlite_engine(tmp_path / "plugins.db")
    create_tables(engine)
    value = BusinessPluginRegistry(lambda: SqlAlchemyUnitOfWork(engine))
    yield value
    engine.dispose()


def test_plugin_can_register_namespaced_actions_and_templates(
    registry: BusinessPluginRegistry,
) -> None:
    registration = registry.register(_manifest())

    assert registration.plugin_id == "content-studio"
    assert registration.version == "0.1.0"
    assert registry.list() == (registration,)
    assert registry.templates("content-studio")[0].template_id == "campaign"


def test_plugin_cannot_replace_core_actions(registry: BusinessPluginRegistry) -> None:
    manifest = _manifest().model_copy(
        update={
            "capability_actions": (
                PluginAction(action="workspace.write", level=CapabilityLevel.L2),
            )
        }
    )

    with pytest.raises(InvalidPluginManifest, match="action_namespace"):
        registry.register(manifest)

    core_named_plugin = _manifest().model_copy(
        update={
            "plugin_id": "workspace",
            "capability_actions": (
                PluginAction(action="workspace.write", level=CapabilityLevel.L2),
            ),
        }
    )
    with pytest.raises(InvalidPluginManifest, match="core_action_replacement"):
        registry.register(core_named_plugin)


@pytest.mark.parametrize(
    "field",
    ["python", "prompt_override", "sql", "callback_url", "package_path"],
)
def test_plugin_models_reject_executable_or_runtime_fields(field: str) -> None:
    payload = _manifest().model_dump(mode="json")
    payload["templates"][0]["nodes"][0][field] = "not allowed"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BusinessPluginManifest.model_validate(payload)


def test_registration_is_idempotent_but_rejects_a_different_version(
    registry: BusinessPluginRegistry,
) -> None:
    first = registry.register(_manifest())

    assert registry.register(_manifest()) == first
    with pytest.raises(InvalidPluginManifest, match="version_conflict"):
        registry.register(_manifest(version="0.2.0"))


def test_manifest_validation_rejects_unknown_slots_and_invalid_edges() -> None:
    manifest = _manifest()
    template = manifest.templates[0]

    with pytest.raises(ValidationError, match="unknown employee slot"):
        template.model_copy(
            update={"nodes": (template.nodes[0].model_copy(update={"employee_slot": "missing"}),)}
        ).model_validate(
            template.model_copy(
                update={
                    "nodes": (template.nodes[0].model_copy(update={"employee_slot": "missing"}),)
                }
            ).model_dump()
        )

    with pytest.raises(ValidationError, match="unknown edge endpoint"):
        WorkTemplate.model_validate(
            {
                **template.model_dump(),
                "edges": [
                    TemplateEdge(
                        from_key="draft",
                        to_key="missing",
                        kind=WorkEdgeKind.DEPENDS_ON,
                    ).model_dump()
                ],
            }
        )


def test_registry_rejects_a_cyclic_declarative_template(
    registry: BusinessPluginRegistry,
) -> None:
    template = WorkTemplate(
        template_id="cycle",
        display_name="Cycle",
        employee_slots=(EmployeeSlot(slot_id="author"),),
        nodes=(
            TemplateNode(
                key="a",
                employee_slot="author",
                objective="A",
                acceptance_criteria=("A",),
            ),
            TemplateNode(
                key="b",
                employee_slot="author",
                objective="B",
                acceptance_criteria=("B",),
            ),
        ),
        edges=(
            TemplateEdge(from_key="a", to_key="b", kind=WorkEdgeKind.DEPENDS_ON),
            TemplateEdge(from_key="b", to_key="a", kind=WorkEdgeKind.DEPENDS_ON),
        ),
    )

    with pytest.raises(InvalidPluginManifest, match="template_cycle"):
        registry.register(_manifest().model_copy(update={"templates": (template,)}))


def test_registry_supports_declarative_runtime_profiles_and_node_requirements() -> None:
    payload = _manifest().model_dump(mode="json")
    payload["capability_actions"][0]["runtime_profiles"] = ["workspace_write"]
    payload["templates"][0]["nodes"][0].update(
        {
            "required_actions": ["content-studio.publish_draft"],
            "resource_kinds": ["content"],
            "resource_values": ["draft"],
        }
    )

    manifest = BusinessPluginManifest.model_validate(payload)

    assert manifest.capability_actions[0].runtime_profiles == ("workspace_write",)
    assert manifest.templates[0].nodes[0].required_actions == ("content-studio.publish_draft",)


def test_concurrent_identical_registration_returns_the_persisted_winner(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "plugins-race.db")
    create_tables(engine)
    registry = BusinessPluginRegistry(lambda: SqlAlchemyUnitOfWork(engine))
    insert_barrier = Barrier(2)

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_insert(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().startswith("INSERT INTO business_plugin_registrations"):
            insert_barrier.wait(timeout=5)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _index: registry.register(_manifest()), range(2)))
        assert results[0] == results[1]
        assert registry.list() == (results[0],)
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_insert)
        engine.dispose()
