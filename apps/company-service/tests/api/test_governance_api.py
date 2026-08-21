from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dsh_company.application.delegation_service import DelegationService
from dsh_company.application.governance_service import GovernanceService, GovernedAction
from dsh_company.domain.approval import Approval
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.ids import CapabilityGrantId, WorkNodeId, WorkspaceId
from dsh_company.domain.policy import PolicyEngine
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


class RecordingCoordinator:
    def __init__(self) -> None:
        self.enqueued: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        del node_id


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = create_sqlite_engine(tmp_path / "governance-api.db")
    create_tables(value)
    yield value
    value.dispose()


@pytest.fixture
def coordinator() -> RecordingCoordinator:
    return RecordingCoordinator()


@pytest.fixture
def client(engine: Engine, coordinator: RecordingCoordinator) -> Iterator[TestClient]:
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        work_coordinator=coordinator,
        governance_service_factory=lambda: GovernanceService(
            SqlAlchemyUnitOfWork(engine), PolicyEngine(), coordinator
        ),
        delegation_service_factory=lambda: DelegationService(
            SqlAlchemyUnitOfWork(engine), PolicyEngine(), coordinator
        ),
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as value:
        yield value


def _grant(action: str, *, approval: bool = False) -> CapabilityGrant:
    return CapabilityGrant(
        id=CapabilityGrantId(f"grant-{action}"),
        employee_revision_id=None,
        action=action,
        level=CapabilityLevel.L2 if action == "workspace.write" else CapabilityLevel.L1,
        resource_kind="repository",
        resource_values=("repo-a",),
        requires_approval=approval,
    )


def _seed_work(
    client: TestClient, engine: Engine
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    workspace = client.post("/workspaces", json={"name": "Governed"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json={
            "display_name": "Publisher",
            "responsibility": "Publish",
            "runtime_profile": "workspace_write",
            "model": "deepseek-chat",
            "grants": [
                {
                    "action": "workspace.write",
                    "level": 2,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": True,
                },
                {
                    "action": "work.delegate",
                    "level": 1,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": False,
                },
            ],
        },
    ).json()
    work = client.post(
        f"/workspaces/{workspace['id']}/works",
        json={
            "employee_id": employee["id"],
            "objective": "Publish notes",
            "acceptance_criteria": ["Published"],
            "command_id": "governed-1",
        },
    ).json()
    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.workspace_grants.replace(
            WorkspaceId(workspace["id"]),
            (_grant("workspace.write", approval=True), _grant("work.delegate")),
        )
        uow.node_grants.replace(
            WorkNodeId(work["nodes"][0]["id"]),
            (_grant("workspace.write", approval=True), _grant("work.delegate")),
        )
        uow.commit()
    return workspace, employee, work


def test_capabilities_are_replaced_as_authoritative_workspace_projection(
    client: TestClient,
) -> None:
    workspace = client.post("/workspaces", json={"name": "Governed"}).json()

    response = client.put(
        f"/workspaces/{workspace['id']}/capabilities",
        json={
            "grants": [
                {
                    "action": "workspace.write",
                    "level": 2,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": True,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": workspace["id"],
        "grants": [
            {
                "action": "workspace.write",
                "level": 2,
                "resource_kind": "repository",
                "resource_values": ["repo-a"],
                "requires_approval": True,
            }
        ],
    }
    assert client.get(f"/workspaces/{workspace['id']}/capabilities").json() == response.json()
    assert client.put("/workspaces/missing/capabilities", json={"grants": []}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {
            "grants": [
                {
                    "action": "unknown.action",
                    "level": 2,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": False,
                }
            ]
        },
        {
            "grants": [
                {
                    "action": "workspace.write",
                    "level": 1,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": False,
                }
            ]
        },
        {
            "grants": [
                {
                    "action": "workspace.write",
                    "level": 2,
                    "resource_kind": "repository",
                    "resource_values": [],
                    "requires_approval": False,
                }
            ]
        },
    ],
)
def test_capabilities_reject_invalid_closed_catalog_inputs(
    client: TestClient, payload: dict[str, Any]
) -> None:
    workspace = client.post("/workspaces", json={"name": "Governed"}).json()
    assert (
        client.put(f"/workspaces/{workspace['id']}/capabilities", json=payload).status_code == 422
    )


def test_pending_approval_lists_requesting_employee_and_approve_refreshes_work(
    client: TestClient, engine: Engine, coordinator: RecordingCoordinator
) -> None:
    workspace, employee, work = _seed_work(client, engine)
    approval = GovernanceService(
        SqlAlchemyUnitOfWork(engine),
        PolicyEngine(),
        coordinator,
        ids=lambda prefix: f"{prefix}-api",
    ).authorize(
        GovernedAction(
            node_id=WorkNodeId(work["nodes"][0]["id"]),
            action="workspace.write",
            resources=("repo-a",),
            reason="Publish externally",
        )
    )
    assert isinstance(approval, Approval)

    listed = client.get(f"/workspaces/{workspace['id']}/approvals")
    approved = client.post(f"/approvals/{approval.id}/approve", json={"decided_by": "operator"})
    repeated = client.post(f"/approvals/{approval.id}/reject", json={"decided_by": "operator"})

    assert listed.status_code == 200
    assert listed.json()[0]["requesting_employee"] == {
        "id": employee["id"],
        "display_name": "Publisher",
    }
    assert listed.json()[0]["resources"] == ["repo-a"]
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"
    assert approved.json()["work"]["nodes"][0]["status"] == "ready"
    assert coordinator.enqueued[-1] == WorkNodeId(work["nodes"][0]["id"])
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "approval_already_decided"


def test_rejection_returns_authoritative_failed_work_without_dispatch(
    client: TestClient, engine: Engine, coordinator: RecordingCoordinator
) -> None:
    workspace, _employee, work = _seed_work(client, engine)
    approval = GovernanceService(
        SqlAlchemyUnitOfWork(engine),
        PolicyEngine(),
        coordinator,
        ids=lambda prefix: f"{prefix}-reject",
    ).authorize(
        GovernedAction(
            node_id=WorkNodeId(work["nodes"][0]["id"]),
            action="workspace.write",
            resources=("repo-a",),
            reason="Publish externally",
        )
    )
    assert isinstance(approval, Approval)
    before = list(coordinator.enqueued)

    response = client.post(f"/approvals/{approval.id}/reject", json={"decided_by": "operator"})

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "rejected"
    assert response.json()["work"]["nodes"][0]["failure_code"] == "approval_rejected"
    assert coordinator.enqueued == before


def test_delegation_is_work_scoped_and_lists_server_eligible_active_employees(
    client: TestClient, engine: Engine
) -> None:
    workspace, proposer, work = _seed_work(client, engine)
    target = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json={
            "display_name": "Reviewer",
            "responsibility": "Review",
            "runtime_profile": "workspace_read",
            "model": "deepseek-chat",
            "grants": [
                {
                    "action": "workspace.read",
                    "level": 1,
                    "resource_kind": "repository",
                    "resource_values": ["repo-a"],
                    "requires_approval": False,
                }
            ],
        },
    ).json()

    listed = client.get(f"/works/{work['id']}/delegations")
    denied = client.post(
        f"/works/{work['id']}/delegations",
        json={
            "source_node_id": work["nodes"][0]["id"],
            "proposer_employee_id": proposer["id"],
            "target_employee_id": target["id"],
            "objective": "Review facts",
            "acceptance_criteria": ["Cite sources"],
            "required_actions": ["workspace.read"],
            "resource_values": ["repo-outside"],
        },
    )

    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["eligible_employees"]} == {
        proposer["id"],
        target["id"],
    }
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "delegation_denied"
    assert client.get("/works/missing/delegations").status_code == 404


def test_delegation_rejects_oversized_objective_before_domain_mutation(
    client: TestClient, engine: Engine
) -> None:
    _workspace, proposer, work = _seed_work(client, engine)

    response = client.post(
        f"/works/{work['id']}/delegations",
        json={
            "source_node_id": work["nodes"][0]["id"],
            "proposer_employee_id": proposer["id"],
            "target_employee_id": proposer["id"],
            "objective": "x" * 501,
            "acceptance_criteria": ["Cite sources"],
            "required_actions": ["workspace.read"],
            "resource_values": ["repo-a"],
        },
    )

    assert response.status_code == 422
