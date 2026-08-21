import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CompanyEventId,
    WorkId,
    WorkNodeId,
)
from dsh_company.domain.work import ArtifactReference, CompanyEvent
from dsh_company.dsh_gateway.contracts import (
    GatewayCancelResult,
    GatewayResult,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.events import ProjectedDshEvent
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


class NoActiveGateway:
    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult:
        del submission
        del on_event
        raise AssertionError("pending cancellation must prevent dispatch")

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult:
        del attempt_id
        raise AssertionError("pending cancellation has no active runtime to close")

    def shutdown(self) -> None:
        return None


class RecordingCoordinator:
    def __init__(self, engine: Engine) -> None:
        self.enqueued: list[WorkNodeId] = []
        self.cancelled: list[WorkNodeId] = []
        self._runtime = RuntimeCoordinator(
            lambda: SqlAlchemyUnitOfWork(engine), NoActiveGateway()
        )

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        self.cancelled.append(node_id)
        self._runtime.request_cancel(node_id)

    def close(self) -> None:
        self._runtime.shutdown()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_sqlite_engine(tmp_path / "work-api.db")
    create_tables(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


@pytest.fixture
def coordinator(engine: Engine) -> Iterator[RecordingCoordinator]:
    recording = RecordingCoordinator(engine)
    yield recording
    recording.close()


@pytest.fixture
def client(
    engine: Engine, coordinator: RecordingCoordinator
) -> Iterator[TestClient]:
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        work_coordinator=coordinator,
    )
    with TestClient(
        create_app(assembly=assembly), raise_server_exceptions=False
    ) as test_client:
        yield test_client


def test_create_direct_work_returns_accepted_projection(client: TestClient) -> None:
    workspace, employee = _seed_employee(client)

    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={
            "employee_id": employee["id"],
            "objective": "Write a release note",
            "acceptance_criteria": ["Has a title"],
            "command_id": "cmd-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["strategy"] == "direct"
    assert response.json()["nodes"][0]["status"] in {"ready", "running"}


def _seed_employee(
    client: TestClient, *, workspace_name: str = "Content"
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = client.post("/workspaces", json={"name": workspace_name}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json={
            "display_name": "Editor",
            "responsibility": "Write release notes",
            "runtime_profile": "workspace_read",
            "model": "deepseek-v4-flash",
            "grants": [],
        },
    ).json()
    return workspace, employee


def _create_work(
    client: TestClient,
    workspace: dict[str, Any],
    employee: dict[str, Any],
    *,
    command_id: str = "cmd-1",
) -> dict[str, Any]:
    response = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={
            "employee_id": employee["id"],
            "objective": "  Write a release note  ",
            "acceptance_criteria": ["  Has a title  "],
            "command_id": f"  {command_id}  ",
        },
    )
    assert response.status_code == 202
    return response.json()


def test_create_is_idempotent_and_trims_public_inputs(
    client: TestClient, coordinator: RecordingCoordinator
) -> None:
    workspace, employee = _seed_employee(client)

    first = _create_work(client, workspace, employee)
    second = _create_work(client, workspace, employee)

    assert second["id"] == first["id"]
    assert first["objective"] == "Write a release note"
    assert first["command_id"] == "cmd-1"
    assert first["nodes"][0]["acceptance_criteria"] == ["Has a title"]
    assert coordinator.enqueued == [WorkNodeId(first["nodes"][0]["id"])]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "employee_id": "employee",
            "objective": "   ",
            "acceptance_criteria": ["criterion"],
            "command_id": "cmd",
        },
        {
            "employee_id": "employee",
            "objective": "objective",
            "acceptance_criteria": [],
            "command_id": "cmd",
        },
        {
            "employee_id": "employee",
            "objective": "objective",
            "acceptance_criteria": ["   "],
            "command_id": "cmd",
        },
        {
            "employee_id": "employee",
            "objective": "objective",
            "acceptance_criteria": ["criterion"],
            "command_id": "   ",
        },
    ],
)
def test_create_rejects_invalid_public_inputs(
    client: TestClient, payload: dict[str, object]
) -> None:
    workspace, _employee = _seed_employee(client)

    response = client.post(f"/workspaces/{workspace['id']}/works", json=payload)

    assert response.status_code == 422
    assert client.get(f"/workspaces/{workspace['id']}/works").json() == []


def test_workspace_work_list_is_isolated_and_unknown_workspace_is_stable_404(
    client: TestClient,
) -> None:
    first_workspace, first_employee = _seed_employee(client, workspace_name="First")
    second_workspace, second_employee = _seed_employee(client, workspace_name="Second")
    first_work = _create_work(
        client, first_workspace, first_employee, command_id="shared-command"
    )
    second_work = _create_work(
        client, second_workspace, second_employee, command_id="shared-command"
    )

    response = client.get(f"/workspaces/{first_workspace['id']}/works")
    missing = client.get("/workspaces/missing/works")

    assert [item["id"] for item in response.json()] == [first_work["id"]]
    assert second_work["id"] != first_work["id"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "workspace_not_found"


def test_get_work_returns_safe_artifact_reference_only(
    client: TestClient, engine: Engine
) -> None:
    workspace, employee = _seed_employee(client)
    created = _create_work(client, workspace, employee)
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get(WorkId(created["id"]))
        assert aggregate is not None
        link = aggregate.execution_links[0]
        artifact = ArtifactReference(
            id=ArtifactReferenceId("artifact-1"),
            workspace_id=aggregate.work.workspace_id,
            kind="dsh_session_result",
            uri="dsh-session://employee-1/attempt/attempt-1/result",
            source_session_id="employee-private",
            source_attempt_id=link.attempt_id,
            created_at=datetime.now(UTC),
        )
        uow.works.update(replace(aggregate, artifacts=(artifact,)))
        uow.commit()

    response = client.get(f"/works/{created['id']}")
    missing = client.get("/works/missing")

    assert response.status_code == 200
    assert response.json()["artifacts"] == [
        {
            "id": "artifact-1",
            "kind": "dsh_session_result",
            "uri": "dsh-session://employee-1/attempt/attempt-1/result",
            "created_at": response.json()["artifacts"][0]["created_at"],
        }
    ]
    assert "source_session_id" not in response.text
    assert "source_attempt_id" not in response.text
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "work_not_found"


def test_history_contains_safe_company_events_not_model_content(
    client: TestClient, engine: Engine
) -> None:
    workspace, employee = _seed_employee(client)
    created = _create_work(client, workspace, employee)
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get(WorkId(created["id"]))
        assert aggregate is not None
        uow.company_events.append(
            CompanyEvent(
                id=CompanyEventId("event-1"),
                workspace_id=aggregate.work.workspace_id,
                work_id=aggregate.work.id,
                node_id=aggregate.nodes[0].id,
                attempt_id=aggregate.execution_links[0].attempt_id,
                source_sequence=1,
                event_type="work.completed",
                summary="Work completed",
                source="company",
                observed_at=datetime.now(UTC),
            )
        )
        uow.commit()

    response = client.get(f"/works/{created['id']}/events")
    body = response.json()

    assert response.status_code == 200
    assert body[-1]["event_type"] == "work.completed"
    serialized = json.dumps(body)
    assert "final_response" not in serialized
    assert "prompt" not in serialized
    assert "tool_arguments" not in serialized
    missing = client.get("/works/missing/events")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "work_not_found"


def test_cancel_returns_accepted_and_targets_direct_work_node(
    client: TestClient, coordinator: RecordingCoordinator
) -> None:
    workspace, employee = _seed_employee(client)
    created = _create_work(client, workspace, employee)

    response = client.post(f"/works/{created['id']}/cancel")
    repeated = client.post(f"/works/{created['id']}/cancel")
    missing = client.post("/works/missing/cancel")

    assert response.status_code == 202
    assert response.json()["id"] == created["id"]
    assert response.json()["status"] == "blocked"
    assert response.json()["nodes"][0]["failure_code"] == "cancel_unconfirmed"
    assert response.json()["execution_links"][0]["status"] == "blocked"
    assert repeated.status_code == 202
    assert repeated.json() == response.json()
    assert coordinator.cancelled == [
        WorkNodeId(created["nodes"][0]["id"]),
        WorkNodeId(created["nodes"][0]["id"]),
    ]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "work_not_found"


def test_openapi_publishes_closed_authoritative_work_statuses(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert set(schemas["WorkStatus"]["enum"]) == {
        "queued",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    }
    assert set(schemas["WorkNodeStatus"]["enum"]) == {
        "ready",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    }
    assert set(schemas["ExecutionStatus"]["enum"]) == {
        "dispatch_pending",
        "running",
        "cancel_requested",
        "blocked",
        "completed",
        "failed",
        "cancelled",
    }
