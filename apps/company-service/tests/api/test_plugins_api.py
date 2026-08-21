from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.ids import WorkGraphRevisionId
from dsh_company.domain.policy import PolicyEngine
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.orchestration.durable_graph import DurableGraphEngine
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


class RecordingGraphEngine:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.started: list[WorkGraphRevisionId] = []
        self.persisted_at_start: list[bool] = []

    def start(self, graph_revision_id: WorkGraphRevisionId) -> None:
        self.started.append(graph_revision_id)
        with SqlAlchemyUnitOfWork(self._engine) as uow:
            self.persisted_at_start.append(uow.works.get_revision(graph_revision_id) is not None)


class FailsFirstGraphEngine(RecordingGraphEngine):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self.attempts = 0

    def start(self, graph_revision_id: WorkGraphRevisionId) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("start failed once")
        super().start(graph_revision_id)


class RecordingCoordinator:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, node_id: str) -> None:
        self.enqueued.append(node_id)

    def request_cancel(self, node_id: str) -> None:
        del node_id


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = create_sqlite_engine(tmp_path / "plugins-api.db")
    create_tables(value)
    yield value
    value.dispose()


@pytest.fixture
def graph_engine(engine: Engine) -> RecordingGraphEngine:
    return RecordingGraphEngine(engine)


@pytest.fixture
def client(engine: Engine, graph_engine: RecordingGraphEngine) -> Iterator[TestClient]:
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        orchestration_engine=graph_engine,  # type: ignore[arg-type]
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as api:
        yield api


def _manifest() -> dict[str, Any]:
    return {
        "plugin_id": "content-studio",
        "version": "0.1.0",
        "display_name": "Content Studio",
        "capability_actions": [{"action": "content-studio.publish_draft", "level": 3}],
        "templates": [
            {
                "template_id": "campaign",
                "display_name": "Research, write, review, summarize",
                "employee_slots": [
                    {"slot_id": "researcher"},
                    {"slot_id": "writer"},
                    {"slot_id": "reviewer"},
                    {"slot_id": "summarizer"},
                ],
                "nodes": [
                    {
                        "key": "research",
                        "employee_slot": "researcher",
                        "objective": "Research the subject",
                        "acceptance_criteria": ["Cite evidence"],
                    },
                    {
                        "key": "write",
                        "employee_slot": "writer",
                        "objective": "Write the draft",
                        "acceptance_criteria": ["Use the research"],
                    },
                    {
                        "key": "review",
                        "employee_slot": "reviewer",
                        "objective": "Review the draft",
                        "acceptance_criteria": ["List required corrections"],
                    },
                    {
                        "key": "summary",
                        "employee_slot": "summarizer",
                        "objective": "Summarize the approved result",
                        "acceptance_criteria": ["Publish-ready summary"],
                    },
                ],
                "edges": [
                    {"from_key": "research", "to_key": "write", "kind": "depends_on"},
                    {"from_key": "write", "to_key": "review", "kind": "reviews"},
                    {"from_key": "review", "to_key": "summary", "kind": "summarizes"},
                ],
            }
        ],
    }


def _operational_manifest() -> dict[str, Any]:
    return {
        "plugin_id": "content-studio",
        "version": "0.1.0",
        "display_name": "Content Studio",
        "capability_actions": [
            {
                "action": "content-studio.publish_draft",
                "level": 3,
                "runtime_profiles": ["workspace_write"],
            }
        ],
        "templates": [
            {
                "template_id": "publish",
                "display_name": "Publish draft",
                "employee_slots": [{"slot_id": "publisher"}],
                "nodes": [
                    {
                        "key": "publish",
                        "employee_slot": "publisher",
                        "objective": "Publish the approved draft",
                        "acceptance_criteria": ["Published"],
                        "required_actions": ["content-studio.publish_draft"],
                        "resource_kinds": ["content"],
                        "resource_values": ["draft"],
                    }
                ],
                "edges": [],
            }
        ],
    }


def _seed(client: TestClient, workspace_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    workspace = client.post("/workspaces", json={"name": workspace_name}).json()
    employees = [
        client.post(
            f"/workspaces/{workspace['id']}/employees",
            json={
                "display_name": f"Employee {index}",
                "responsibility": "Content work",
                "runtime_profile": "workspace_read",
                "model": "deepseek-chat",
                "grants": [],
            },
        ).json()
        for index in range(4)
    ]
    return workspace, employees


def test_plugin_registration_listing_and_templates_use_public_api(client: TestClient) -> None:
    response = client.post("/business-plugins/register", json=_manifest())

    assert response.status_code == 201
    assert response.json()["plugin_id"] == "content-studio"
    assert client.get("/business-plugins").json() == [response.json()]
    templates = client.get("/business-plugins/content-studio/templates")
    assert templates.status_code == 200
    assert templates.json()[0]["template_id"] == "campaign"


def test_instantiation_requires_every_explicit_employee_slot(client: TestClient) -> None:
    assert client.post("/business-plugins/register", json=_manifest()).status_code == 201
    workspace, employees = _seed(client, "Content Lab")

    response = client.post(
        f"/workspaces/{workspace['id']}/templates/content-studio/campaign/instantiate",
        json={
            "command_id": "campaign-1",
            "employee_assignments": {"researcher": employees[0]["id"]},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_template_assignment"
    assert client.get(f"/workspaces/{workspace['id']}/works").json() == []


def test_instantiation_rejects_an_employee_from_another_workspace(
    client: TestClient,
) -> None:
    client.post("/business-plugins/register", json=_manifest())
    workspace, employees = _seed(client, "Content Lab")
    _other, outsiders = _seed(client, "Other Lab")
    assignments = dict(
        zip(
            ("researcher", "writer", "reviewer", "summarizer"),
            [employees[0]["id"], employees[1]["id"], employees[2]["id"], outsiders[0]["id"]],
            strict=True,
        )
    )

    response = client.post(
        f"/workspaces/{workspace['id']}/templates/content-studio/campaign/instantiate",
        json={"command_id": "campaign-cross-workspace", "employee_assignments": assignments},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "employee_ineligible"


def test_instantiation_persists_validated_graph_then_starts_engine(
    client: TestClient, graph_engine: RecordingGraphEngine
) -> None:
    client.post("/business-plugins/register", json=_manifest())
    workspace, employees = _seed(client, "Content Lab")
    assignments = dict(
        zip(
            ("researcher", "writer", "reviewer", "summarizer"),
            [employee["id"] for employee in employees],
            strict=True,
        )
    )

    response = client.post(
        f"/workspaces/{workspace['id']}/templates/content-studio/campaign/instantiate",
        json={"command_id": "campaign-valid", "employee_assignments": assignments},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["strategy"] == "graph"
    assert [node["assigned_employee_id"] for node in body["nodes"]] == [
        employee["id"] for employee in employees
    ]
    assert [edge["kind"] for edge in body["edges"]] == [
        "depends_on",
        "reviews",
        "summarizes",
    ]
    assert graph_engine.started == [WorkGraphRevisionId(body["graph_revision_id"])]
    assert graph_engine.persisted_at_start == [True]


def test_retry_of_persisted_command_starts_current_graph_without_duplicate(
    engine: Engine,
) -> None:
    graph_engine = FailsFirstGraphEngine(engine)
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        orchestration_engine=graph_engine,  # type: ignore[arg-type]
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as api:
        api.post("/business-plugins/register", json=_manifest())
        workspace, employees = _seed(api, "Retry Lab")
        assignments = dict(
            zip(
                ("researcher", "writer", "reviewer", "summarizer"),
                [employee["id"] for employee in employees],
                strict=True,
            )
        )
        path = f"/workspaces/{workspace['id']}/templates/content-studio/campaign/instantiate"
        payload = {
            "command_id": "retry-current-graph",
            "employee_assignments": assignments,
        }

        first = api.post(path, json=payload)
        second = api.post(path, json=payload)

        assert first.status_code == 500
        assert second.status_code == 202
        works = api.get(f"/workspaces/{workspace['id']}/works").json()
        assert len(works) == 1
        assert second.json()["id"] == works[0]["id"]
        assert graph_engine.attempts == 2
        assert graph_engine.started == [WorkGraphRevisionId(works[0]["graph_revision_id"])]


def test_l3_template_without_all_policy_layers_is_denied_without_work(
    client: TestClient,
) -> None:
    assert (
        client.post("/business-plugins/register", json=_operational_manifest()).status_code == 201
    )
    workspace, employees = _seed(client, "Denied Plugin")

    response = client.post(
        f"/workspaces/{workspace['id']}/templates/content-studio/publish/instantiate",
        json={
            "command_id": "missing-plugin-grants",
            "employee_assignments": {"publisher": employees[0]["id"]},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "employee_ineligible"
    assert client.get(f"/workspaces/{workspace['id']}/works").json() == []


def test_registered_l3_action_uses_four_layers_and_waits_for_approval(
    engine: Engine,
) -> None:
    factory = lambda: SqlAlchemyUnitOfWork(engine)  # noqa: E731
    registry = BusinessPluginRegistry(factory)
    coordinator = RecordingCoordinator()
    policy = PolicyEngine(registry.action_catalog)
    graph_engine = DurableGraphEngine(factory, coordinator, policy_engine=policy)
    assembly = ComponentAssembly(
        uow_factory=factory,
        orchestration_engine=graph_engine,
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as api:
        assert (
            api.post("/business-plugins/register", json=_operational_manifest()).status_code == 201
        )
        workspace = api.post("/workspaces", json={"name": "Operational Plugin"}).json()
        grant = {
            "action": "content-studio.publish_draft",
            "level": 3,
            "resource_kind": "content",
            "resource_values": ["draft"],
            "requires_approval": False,
        }
        employee = api.post(
            f"/workspaces/{workspace['id']}/employees",
            json={
                "display_name": "Publisher",
                "responsibility": "Publish approved drafts",
                "runtime_profile": "workspace_write",
                "model": "deepseek-chat",
                "grants": [grant],
            },
        ).json()
        workspace_grant = api.put(
            f"/workspaces/{workspace['id']}/capabilities",
            json={"grants": [grant]},
        )

        response = api.post(
            f"/workspaces/{workspace['id']}/templates/content-studio/publish/instantiate",
            json={
                "command_id": "approved-plugin-action",
                "employee_assignments": {"publisher": employee["id"]},
            },
        )

        assert workspace_grant.status_code == 200
        assert response.status_code == 202
        body = response.json()
        assert body["nodes"][0]["status"] == "waiting_approval"
        approvals = api.get(f"/workspaces/{workspace['id']}/approvals").json()
        assert approvals[0]["action"] == "content-studio.publish_draft"
        assert coordinator.enqueued == []


def test_template_cannot_reference_an_unregistered_plugin_action(
    client: TestClient,
) -> None:
    manifest = _operational_manifest()
    manifest["templates"][0]["nodes"][0]["required_actions"] = ["content-studio.unknown"]

    response = client.post("/business-plugins/register", json=manifest)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_plugin_manifest"


def test_registration_conflict_maps_to_stable_api_error(client: TestClient) -> None:
    assert client.post("/business-plugins/register", json=_manifest()).status_code == 201
    changed = _manifest()
    changed["version"] = "0.2.0"

    response = client.post("/business-plugins/register", json=changed)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_plugin_manifest"
    assert response.json()["error"]["message"] == "version_conflict"
