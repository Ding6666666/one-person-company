from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.approval import ApprovalStatus
from dsh_company.domain.ids import AttemptId, WorkGraphRevisionId
from dsh_company.domain.policy import PolicyEngine
from dsh_company.dsh_gateway.contracts import (
    GatewayCancelResult,
    GatewayResult,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.events import ProjectedDshEvent
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
        self.fail_next_start = False

    def start(self, graph_revision_id: WorkGraphRevisionId) -> None:
        self.started.append(graph_revision_id)
        with SqlAlchemyUnitOfWork(self._engine) as uow:
            self.persisted_at_start.append(uow.works.get_revision(graph_revision_id) is not None)
        if self.fail_next_start:
            self.fail_next_start = False
            raise RuntimeError("injected start failure")


class RecordingGateway:
    def __init__(self) -> None:
        self.submissions: list[GatewaySubmission] = []

    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult:
        del on_event
        self.submissions.append(submission)
        return GatewayResult(
            finish_reason="completed",
            reference_uri=f"dsh-session://result/{submission.attempt_id}",
            event_count=0,
        )

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult:
        del attempt_id
        return GatewayCancelResult(requested=True, runtime_closed=True)

    def shutdown(self) -> None:
        return None


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_sqlite_engine(tmp_path / "graph-api.db")
    create_tables(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


@pytest.fixture
def graph_engine(engine: Engine) -> RecordingGraphEngine:
    return RecordingGraphEngine(engine)


@pytest.fixture
def client(engine: Engine, graph_engine: RecordingGraphEngine) -> Iterator[TestClient]:
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        orchestration_engine=graph_engine,  # type: ignore[arg-type]
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as value:
        yield value


def _seed(client: TestClient, count: int = 5) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    workspace = client.post("/workspaces", json={"name": "Strategy Lab"}).json()
    employees = [
        client.post(
            f"/workspaces/{workspace['id']}/employees",
            json={
                "display_name": f"Employee {index}",
                "responsibility": "Collaborate",
                "runtime_profile": "workspace_read",
                "model": "deepseek-chat",
                "grants": [],
            },
        ).json()
        for index in range(count)
    ]
    return workspace, employees


def _common(command_id: str) -> dict[str, Any]:
    return {
        "objective": "Propose a launch campaign",
        "acceptance_criteria": ["Cites evidence"],
        "command_id": command_id,
    }


def _plugin_manifest() -> dict[str, Any]:
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
        "templates": [],
    }


def test_battle_creation_persists_parallel_graph_and_starts_after_commit(
    client: TestClient, graph_engine: RecordingGraphEngine
) -> None:
    workspace, employees = _seed(client)
    payload = {
        **_common("battle-1"),
        "kind": "battle",
        "participant_employee_ids": [item["id"] for item in employees[:3]],
        "summarizer_employee_id": employees[3]["id"],
    }

    response = client.post(f"/workspaces/{workspace['id']}/works", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["strategy"] == "battle"
    assert len(body["nodes"]) == 4
    assert [edge["kind"] for edge in body["edges"]] == [
        "summarizes",
        "summarizes",
        "summarizes",
    ]
    assert body["nodes"][-1]["assigned_employee_id"] == employees[3]["id"]
    assert graph_engine.started == [WorkGraphRevisionId(body["graph_revision_id"])]
    assert graph_engine.persisted_at_start == [True]
    assert client.get(f"/works/{body['id']}").json() == body


def test_graph_work_cancel_is_rejected_with_a_stable_conflict(
    client: TestClient,
) -> None:
    workspace, employees = _seed(client)
    created = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={
            **_common("graph-cancel"),
            "kind": "graph",
            "nodes": [
                {
                    "key": "approval-node",
                    "employee_id": employees[0]["id"],
                    "objective": "Prepare a governed change",
                    "acceptance_criteria": ["Safe"],
                    "required_actions": [],
                    "resource_values": [],
                    "resource_kinds": [],
                }
            ],
            "edges": [],
        },
    )
    assert created.status_code == 202

    response = client.post(f"/works/{created.json()['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "work_cancel_not_supported"


def test_same_workspace_command_is_idempotent_for_graph_creation(
    client: TestClient, graph_engine: RecordingGraphEngine
) -> None:
    workspace, employees = _seed(client)
    payload = {
        **_common("same-command"),
        "kind": "star",
        "coordinator_employee_id": employees[0]["id"],
        "children": [
            {
                "employee_id": employees[1]["id"],
                "objective": "Research customers",
                "acceptance_criteria": ["List sources"],
            }
        ],
    }

    first = client.post(f"/workspaces/{workspace['id']}/works", json=payload)
    second = client.post(f"/workspaces/{workspace['id']}/works", json=payload)

    assert first.status_code == second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    graph_id = WorkGraphRevisionId(first.json()["graph_revision_id"])
    assert graph_engine.started == [graph_id, graph_id]


def test_same_command_retries_start_after_the_graph_was_persisted(
    client: TestClient, graph_engine: RecordingGraphEngine
) -> None:
    workspace, employees = _seed(client)
    payload = {
        **_common("retry-start"),
        "kind": "direct",
        "employee_id": employees[0]["id"],
    }
    graph_engine.fail_next_start = True

    first = client.post(f"/workspaces/{workspace['id']}/works", json=payload)
    second = client.post(f"/workspaces/{workspace['id']}/works", json=payload)

    assert first.status_code == 500
    assert second.status_code == 202
    works = client.get(f"/workspaces/{workspace['id']}/works").json()
    assert len(works) == 1
    graph_id = WorkGraphRevisionId(second.json()["graph_revision_id"])
    assert graph_engine.started == [graph_id, graph_id]
    assert graph_engine.persisted_at_start == [True, True]


def test_discriminated_direct_uses_the_graph_creation_path(
    client: TestClient, graph_engine: RecordingGraphEngine
) -> None:
    workspace, employees = _seed(client)

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={
            **_common("direct-strategy"),
            "kind": "direct",
            "employee_id": employees[0]["id"],
        },
    )

    assert response.status_code == 202
    assert graph_engine.started == [WorkGraphRevisionId(response.json()["graph_revision_id"])]


@pytest.mark.parametrize(
    "strategy_fields",
    [
        {"kind": "unknown", "employee_id": "legacy-employee"},
        {
            "kind": "battle",
            "employee_id": "legacy-employee",
            "participant_employee_ids": ["duplicate", "duplicate"],
            "summarizer_employee_id": "summary",
        },
    ],
)
def test_kind_cannot_fall_back_to_the_legacy_direct_shape(
    client: TestClient, strategy_fields: dict[str, Any]
) -> None:
    workspace, employees = _seed(client)
    strategy_fields = {
        key: employees[0]["id"] if value == "legacy-employee" else value
        for key, value in strategy_fields.items()
    }

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={**_common("no-discriminator-bypass"), **strategy_fields},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_work_strategy"
    assert client.get(f"/workspaces/{workspace['id']}/works").json() == []


def test_strategy_validation_envelope_is_the_documented_422_contract(
    client: TestClient,
) -> None:
    workspace, _employees = _seed(client)

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={**_common("invalid-contract"), "kind": "unknown"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_work_strategy"
    openapi = client.get("/openapi.json").json()
    assert (
        openapi["paths"]["/workspaces/{workspace_id}/works"]["post"]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ErrorEnvelope"
    )


@pytest.mark.parametrize(
    ("strategy", "code"),
    [
        (
            {
                "kind": "battle",
                "participant_employee_ids": ["duplicate", "duplicate"],
                "summarizer_employee_id": "summary",
            },
            "invalid_work_strategy",
        ),
        (
            {
                "kind": "graph",
                "nodes": [
                    {
                        "key": "a",
                        "employee_id": "first",
                        "objective": "A",
                        "acceptance_criteria": ["A"],
                    },
                    {
                        "key": "b",
                        "employee_id": "second",
                        "objective": "B",
                        "acceptance_criteria": ["B"],
                    },
                ],
                "edges": [
                    {"from_key": "a", "to_key": "b", "kind": "depends_on"},
                    {"from_key": "b", "to_key": "a", "kind": "depends_on"},
                ],
            },
            "invalid_work_graph",
        ),
        (
            {
                "kind": "graph",
                "nodes": [
                    {
                        "key": "a",
                        "employee_id": "first",
                        "objective": "A",
                        "acceptance_criteria": ["A"],
                        "required_actions": ["unknown.action"],
                    }
                ],
                "edges": [],
            },
            "invalid_work_strategy",
        ),
    ],
)
def test_malformed_strategy_has_stable_422_code(
    client: TestClient, strategy: dict[str, Any], code: str
) -> None:
    workspace, employees = _seed(client)
    if "nodes" in strategy:
        strategy["nodes"] = [
            {
                key: (
                    employees[0]["id"]
                    if value == "first"
                    else employees[1]["id"]
                    if value == "second"
                    else value
                )
                for key, value in node.items()
            }
            for node in strategy["nodes"]
        ]

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={**_common("invalid"), **strategy},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert client.get(f"/workspaces/{workspace['id']}/works").json() == []


def test_ineligible_employee_is_stable_conflict(client: TestClient) -> None:
    workspace, _employees = _seed(client)

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={**_common("ineligible"), "kind": "direct", "employee_id": "missing"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "employee_ineligible"


def test_graph_policy_selection_persists_the_bounded_node_grant(
    client: TestClient, engine: Engine
) -> None:
    workspace, employees = _seed(client)
    workspace_id = workspace["id"]
    capability = {
        "action": "workspace.read",
        "level": 1,
        "resource_kind": "workspace",
        "resource_values": [workspace_id],
        "requires_approval": False,
    }
    assert (
        client.put(
            f"/workspaces/{workspace_id}/capabilities", json={"grants": [capability]}
        ).status_code
        == 200
    )

    response = client.post(
        f"/workspaces/{workspace_id}/works",
        json={
            **_common("policy-graph"),
            "kind": "graph",
            "nodes": [
                {
                    "key": "research",
                    "employee_id": employees[0]["id"],
                    "objective": "Research",
                    "acceptance_criteria": ["Evidence"],
                    "required_actions": ["workspace.read"],
                    "resource_kinds": ["workspace"],
                    "resource_values": [workspace_id],
                }
            ],
            "edges": [],
        },
    )

    assert response.status_code == 202
    node_id = response.json()["nodes"][0]["id"]
    with SqlAlchemyUnitOfWork(engine) as uow:
        grants = uow.node_grants.list_for_node(node_id)
    assert [(grant.action, grant.resource_values) for grant in grants] == [
        ("workspace.read", (workspace_id,))
    ]


def test_approval_required_graph_is_accepted_and_waits_without_gateway_dispatch(
    engine: Engine,
) -> None:
    factory = lambda: SqlAlchemyUnitOfWork(engine)  # noqa: E731
    gateway = RecordingGateway()
    coordinator = RuntimeCoordinator(factory, gateway, runtime_concurrency=1)
    graph_engine = DurableGraphEngine(factory, coordinator, runtime_concurrency=1)
    assembly = ComponentAssembly(
        uow_factory=factory,
        work_coordinator=coordinator,
        orchestration_engine=graph_engine,
        dispose=coordinator.shutdown,
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as api:
        workspace = api.post("/workspaces", json={"name": "Approval Lab"}).json()
        workspace_id = workspace["id"]
        grant = {
            "action": "workspace.read",
            "level": 1,
            "resource_kind": "workspace",
            "resource_values": [workspace_id],
            "requires_approval": True,
        }
        employee = api.post(
            f"/workspaces/{workspace_id}/employees",
            json={
                "display_name": "Reviewer",
                "responsibility": "Review evidence",
                "runtime_profile": "workspace_read",
                "model": "deepseek-chat",
                "grants": [grant],
            },
        ).json()
        assert (
            api.put(
                f"/workspaces/{workspace_id}/capabilities",
                json={"grants": [{**grant, "requires_approval": False}]},
            ).status_code
            == 200
        )

        response = api.post(
            f"/workspaces/{workspace_id}/works",
            json={
                **_common("approval-graph"),
                "kind": "graph",
                "nodes": [
                    {
                        "key": "review",
                        "employee_id": employee["id"],
                        "objective": "Review",
                        "acceptance_criteria": ["Evidence"],
                        "required_actions": ["workspace.read"],
                        "resource_kinds": ["workspace"],
                        "resource_values": [workspace_id],
                    }
                ],
                "edges": [],
            },
        )

        assert response.status_code == 202
        body = response.json()
        assert body["nodes"][0]["status"] == "waiting_approval"
        assert body["nodes"][0]["attempt_count"] == 1
        assert body["execution_links"][0]["status"] == "dispatch_pending"
        assert api.get(f"/works/{body['id']}").json() == body
        assert gateway.submissions == []
        with SqlAlchemyUnitOfWork(engine) as uow:
            approvals = uow.approvals.list_for_workspace(workspace["id"])
            node_grants = uow.node_grants.list_for_node(body["nodes"][0]["id"])
        assert len(approvals) == 1
        assert approvals[0].status is ApprovalStatus.PENDING
        assert approvals[0].action == "workspace.read"
        assert [
            (item.action, item.resource_values, item.requires_approval) for item in node_grants
        ] == [("workspace.read", (workspace_id,), True)]


def test_registered_plugin_action_graph_uses_existing_approval_path(
    engine: Engine,
) -> None:
    factory = lambda: SqlAlchemyUnitOfWork(engine)  # noqa: E731
    registry = BusinessPluginRegistry(factory)
    gateway = RecordingGateway()
    coordinator = RuntimeCoordinator(factory, gateway, runtime_concurrency=1)
    policy = PolicyEngine(registry.action_catalog)
    graph_engine = DurableGraphEngine(
        factory, coordinator, policy_engine=policy, runtime_concurrency=1
    )
    assembly = ComponentAssembly(
        uow_factory=factory,
        work_coordinator=coordinator,
        orchestration_engine=graph_engine,
        dispose=coordinator.shutdown,
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as api:
        assert api.post("/business-plugins/register", json=_plugin_manifest()).status_code == 201
        workspace = api.post("/workspaces", json={"name": "Plugin Graph"}).json()
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
        assert (
            api.put(
                f"/workspaces/{workspace['id']}/capabilities",
                json={"grants": [grant]},
            ).status_code
            == 200
        )

        response = api.post(
            f"/workspaces/{workspace['id']}/works",
            json={
                **_common("plugin-graph"),
                "kind": "graph",
                "nodes": [
                    {
                        "key": "publish",
                        "employee_id": employee["id"],
                        "objective": "Publish the draft",
                        "acceptance_criteria": ["Published"],
                        "required_actions": ["content-studio.publish_draft"],
                        "resource_kinds": ["content"],
                        "resource_values": ["draft"],
                    }
                ],
                "edges": [],
            },
        )

        assert response.status_code == 202
        assert response.json()["nodes"][0]["status"] == "waiting_approval"
        approvals = api.get(f"/workspaces/{workspace['id']}/approvals").json()
        assert approvals[0]["action"] == "content-studio.publish_draft"
        assert gateway.submissions == []
