from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from dsh_company.application.delegation_service import DelegationService
from dsh_company.application.governance_service import GovernanceService, GovernedAction
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.application.runtime_governance import RuntimeGovernanceHandler
from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    CapabilityGrantId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.policy import DecisionKind, PolicyDecision, PolicyEngine
from dsh_company.domain.work import ArtifactReference, ExecutionStatus, WorkNodeStatus
from dsh_company.dsh_gateway.adapter import PublicSdkDshGateway
from dsh_company.dsh_gateway.contracts import GatewayCancelResult
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


def _grant(
    action: str,
    *,
    approval: bool = False,
    resources: tuple[str, ...] = ("repo-a",),
) -> CapabilityGrant:
    return CapabilityGrant(
        id=CapabilityGrantId(f"system-{action}"),
        employee_revision_id=None,
        action=action,
        level={
            "work.delegate": CapabilityLevel.L1,
            "workspace.read": CapabilityLevel.L1,
            "workspace.write": CapabilityLevel.L2,
        }[action],
        resource_kind="repository",
        resource_values=resources,
        requires_approval=approval,
    )


def _grant_payload(action: str, *, approval: bool = False) -> dict[str, object]:
    grant = _grant(action, approval=approval)
    return {
        "action": grant.action,
        "level": int(grant.level),
        "resource_kind": grant.resource_kind,
        "resource_values": list(grant.resource_values),
        "requires_approval": grant.requires_approval,
    }


def _create_employee(
    client: TestClient,
    workspace_id: str,
    display_name: str,
    *,
    runtime_profile: str = "workspace_write",
    grants: tuple[dict[str, object], ...] = (),
) -> dict[str, Any]:
    response = client.post(
        f"/workspaces/{workspace_id}/employees",
        json={
            "display_name": display_name,
            "responsibility": "Complete governed work safely",
            "runtime_profile": runtime_profile,
            "model": "dsh-company-keyless-model",
            "grants": list(grants),
        },
    )
    response.raise_for_status()
    return response.json()


def _create_work(
    client: TestClient,
    workspace_id: str,
    employee_id: str,
    command_id: str,
    *,
    objective: str = "Governed work",
) -> dict[str, Any]:
    response = client.post(
        f"/workspaces/{workspace_id}/works",
        json={
            "employee_id": employee_id,
            "objective": objective,
            "acceptance_criteria": ["Return a bounded result"],
            "command_id": command_id,
        },
    )
    response.raise_for_status()
    return response.json()


def _configure_grants(
    engine: Any,
    workspace_id: str,
    node_id: str,
    grants: tuple[CapabilityGrant, ...],
) -> None:
    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.workspace_grants.replace(WorkspaceId(workspace_id), grants)
        uow.node_grants.replace(WorkNodeId(node_id), grants)
        uow.commit()


def _mark_running(engine: Any, work_id: str) -> None:
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get(WorkId(work_id))
        assert aggregate is not None and len(aggregate.nodes) == 1
        node = aggregate.nodes[0]
        link = aggregate.execution_links[0]
        uow.works.update(
            replace(
                aggregate,
                work=aggregate.work.start(),
                nodes=(node.start(link.attempt_id),),
                execution_links=(link.mark_running(),),
            )
        )
        uow.commit()


@pytest.mark.parametrize(
    ("missing_layer", "expected_reason"),
    [
        ("workspace", "workspace_not_granted"),
        ("employee", "employee_not_granted"),
        ("node", "node_not_granted"),
        ("runtime", "runtime_not_granted"),
    ],
)
def test_l2_write_requires_every_real_grant_layer(
    tmp_path: Path,
    missing_layer: str,
    expected_reason: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"{missing_layer}.db")
    create_tables(engine)
    coordinator = RecordingCoordinator()
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
    with TestClient(create_app(assembly=assembly)) as client:
        workspace = client.post("/workspaces", json={"name": "Layered policy"}).json()
        employee_grants = (
            ()
            if missing_layer == "employee"
            else (_grant_payload("workspace.write"),)
        )
        employee = _create_employee(
            client,
            workspace["id"],
            "Editor",
            runtime_profile=("workspace_read" if missing_layer == "runtime" else "workspace_write"),
            grants=employee_grants,
        )
        work = _create_work(client, workspace["id"], employee["id"], "layered-write")
        workspace_grants = () if missing_layer == "workspace" else (_grant("workspace.write"),)
        node_grants = () if missing_layer == "node" else (_grant("workspace.write"),)
        with SqlAlchemyUnitOfWork(engine) as uow:
            uow.workspace_grants.replace(WorkspaceId(workspace["id"]), workspace_grants)
            uow.node_grants.replace(WorkNodeId(work["nodes"][0]["id"]), node_grants)
            uow.commit()
        before = list(coordinator.enqueued)

        result = assembly.governance_service_factory().authorize(
            GovernedAction(
                node_id=WorkNodeId(work["nodes"][0]["id"]),
                action="workspace.write",
                resources=("repo-a",),
                reason="Update the repository",
            )
        )

        assert result == PolicyDecision(DecisionKind.DENY, expected_reason)
        assert coordinator.enqueued == before
    engine.dispose()


def test_approvals_delegations_and_restart_are_authoritative_company_facts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "governance.db"
    engine = create_sqlite_engine(database_path)
    create_tables(engine)
    coordinator = RecordingCoordinator()
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
    with TestClient(create_app(assembly=assembly)) as client:
        workspace = client.post("/workspaces", json={"name": "Governed"}).json()
        cross_workspace = client.post("/workspaces", json={"name": "Other"}).json()
        proposer = _create_employee(
            client,
            workspace["id"],
            "Proposer",
            grants=(
                _grant_payload("workspace.write", approval=True),
                _grant_payload("work.delegate"),
                _grant_payload("workspace.read"),
            ),
        )
        target = _create_employee(
            client,
            workspace["id"],
            "Reviewer",
            runtime_profile="workspace_read",
            grants=(_grant_payload("workspace.read"),),
        )
        other_target = _create_employee(
            client,
            cross_workspace["id"],
            "Outside reviewer",
            runtime_profile="workspace_read",
            grants=(_grant_payload("workspace.read"),),
        )
        governed_grants = (
            _grant("workspace.write", approval=True),
            _grant("work.delegate"),
            _grant("workspace.read"),
        )

        recheck_work = _create_work(client, workspace["id"], proposer["id"], "approval-recheck")
        _configure_grants(
            engine, workspace["id"], recheck_work["nodes"][0]["id"], governed_grants
        )
        before_approval = list(coordinator.enqueued)
        pending = assembly.governance_service_factory().authorize(
            GovernedAction(
                node_id=WorkNodeId(recheck_work["nodes"][0]["id"]),
                action="workspace.write",
                resources=("repo-a",),
                reason="Explicitly approved L2 write",
            )
        )
        assert isinstance(pending, Approval)
        assert pending.status is ApprovalStatus.PENDING
        assert coordinator.enqueued == before_approval
        client.put(
            f"/workspaces/{workspace['id']}/capabilities",
            json={"grants": [_grant_payload("work.delegate"), _grant_payload("workspace.read")]},
        ).raise_for_status()
        approved = client.post(
            f"/approvals/{pending.id}/approve", json={"decided_by": "operator"}
        )
        approved.raise_for_status()
        assert approved.json()["approval"]["status"] == "approved"
        assert approved.json()["work"]["nodes"][0]["failure_code"] == "workspace_not_granted"
        assert coordinator.enqueued == before_approval

        rejection_work = _create_work(client, workspace["id"], proposer["id"], "approval-reject")
        _configure_grants(
            engine, workspace["id"], rejection_work["nodes"][0]["id"], governed_grants
        )
        rejected_pending = assembly.governance_service_factory().authorize(
            GovernedAction(
                node_id=WorkNodeId(rejection_work["nodes"][0]["id"]),
                action="workspace.write",
                resources=("repo-a",),
                reason="Reject this write",
            )
        )
        assert isinstance(rejected_pending, Approval)
        before_rejection = list(coordinator.enqueued)
        rejection = client.post(
            f"/approvals/{rejected_pending.id}/reject", json={"decided_by": "operator"}
        )
        rejection.raise_for_status()
        assert rejection.json()["work"]["nodes"][0]["failure_code"] == "approval_rejected"
        assert coordinator.enqueued == before_rejection

        cross_work = _create_work(client, workspace["id"], proposer["id"], "cross-workspace")
        _configure_grants(engine, workspace["id"], cross_work["nodes"][0]["id"], governed_grants)
        _mark_running(engine, cross_work["id"])
        cross_denied = client.post(
            f"/works/{cross_work['id']}/delegations",
            json={
                "source_node_id": cross_work["nodes"][0]["id"],
                "proposer_employee_id": proposer["id"],
                "target_employee_id": other_target["id"],
                "objective": "Cross the workspace boundary",
                "acceptance_criteria": ["Should be rejected"],
                "required_actions": ["workspace.read"],
                "resource_values": ["repo-a"],
            },
        )
        assert cross_denied.status_code == 409
        with SqlAlchemyUnitOfWork(engine) as uow:
            cross_after = uow.works.get(WorkId(cross_work["id"]))
            cross_delegations = uow.delegations.list_for_work(WorkId(cross_work["id"]))
        assert cross_after is not None and cross_after.graph.revision_number == 1
        assert cross_after.graph.edges == ()
        assert len(cross_delegations) == 1 and cross_delegations[0].status == "rejected"

        broad_work = _create_work(client, workspace["id"], proposer["id"], "broader-resource")
        _configure_grants(engine, workspace["id"], broad_work["nodes"][0]["id"], governed_grants)
        _mark_running(engine, broad_work["id"])
        broad_denied = client.post(
            f"/works/{broad_work['id']}/delegations",
            json={
                "source_node_id": broad_work["nodes"][0]["id"],
                "proposer_employee_id": proposer["id"],
                "target_employee_id": target["id"],
                "objective": "Expand the resource boundary",
                "acceptance_criteria": ["Should be rejected"],
                "required_actions": ["workspace.read"],
                "resource_values": ["repo-outside"],
            },
        )
        assert broad_denied.status_code == 409
        with SqlAlchemyUnitOfWork(engine) as uow:
            broad_after = uow.works.get(WorkId(broad_work["id"]))
            broad_delegations = uow.delegations.list_for_work(WorkId(broad_work["id"]))
        assert broad_after is not None and broad_after.graph.revision_number == 1
        assert broad_after.graph.edges == ()
        assert len(broad_delegations) == 1 and broad_delegations[0].status == "rejected"

        accepted_work = _create_work(client, workspace["id"], proposer["id"], "accepted-delegation")
        _configure_grants(
            engine, workspace["id"], accepted_work["nodes"][0]["id"], governed_grants
        )
        _mark_running(engine, accepted_work["id"])
        accepted = client.post(
            f"/works/{accepted_work['id']}/delegations",
            json={
                "source_node_id": accepted_work["nodes"][0]["id"],
                "proposer_employee_id": proposer["id"],
                "target_employee_id": target["id"],
                "objective": "Review facts",
                "acceptance_criteria": ["Cite the source"],
                "required_actions": ["workspace.read"],
                "resource_values": ["repo-a"],
            },
        )
        accepted.raise_for_status()
        accepted_body = accepted.json()
        assert accepted_body["delegation"]["status"] == "accepted"
        assert accepted_body["work"]["graph_revision_number"] == 2
        assert len(accepted_body["work"]["nodes"]) == 2
        assert len(accepted_body["work"]["execution_links"]) == 2
        child_link = next(
            item
            for item in accepted_body["work"]["execution_links"]
            if item["node_id"] == accepted_body["delegation"]["target_node_id"]
        )
        assert child_link["status"] == "dispatch_pending"

        durable_pending_work = _create_work(
            client, workspace["id"], proposer["id"], "durable-pending"
        )
        _configure_grants(
            engine,
            workspace["id"],
            durable_pending_work["nodes"][0]["id"],
            governed_grants,
        )
        durable_pending = assembly.governance_service_factory().authorize(
            GovernedAction(
                node_id=WorkNodeId(durable_pending_work["nodes"][0]["id"]),
                action="workspace.write",
                resources=("repo-a",),
                reason="Persist this pending approval",
            )
        )
        assert isinstance(durable_pending, Approval)
        accepted_delegation_id = accepted_body["delegation"]["id"]

    engine.dispose()
    restarted_engine = create_sqlite_engine(database_path)
    create_tables(restarted_engine)
    with SqlAlchemyUnitOfWork(restarted_engine) as uow:
        restarted_approval = uow.approvals.get(durable_pending.id)
        restarted_delegations = uow.delegations.list_for_work(WorkId(accepted_work["id"]))
        restarted_work = uow.works.get(WorkId(accepted_work["id"]))
    assert restarted_approval is not None
    assert restarted_approval.status is ApprovalStatus.PENDING
    assert len(restarted_delegations) == 1
    assert str(restarted_delegations[0].id) == accepted_delegation_id
    assert restarted_delegations[0].status == "accepted"
    assert restarted_work is not None and restarted_work.graph.revision_number == 2
    restarted_engine.dispose()
    database_path.unlink()


class UnusedGateway:
    def submit(self, *_args: object, **_kwargs: object) -> Any:
        raise AssertionError("startup recording coordinator must not dispatch")

    def cancel(self, _attempt_id: object) -> GatewayCancelResult:
        return GatewayCancelResult(requested=False, runtime_closed=False)

    def shutdown(self) -> None:
        return None


class StartupRecordingCoordinator(RuntimeCoordinator):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.enqueued: list[WorkNodeId] = []
        super().__init__(*args, **kwargs)

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)


@pytest.mark.parametrize("remove_current_grant", [False, True])
def test_startup_reconciles_committed_approved_waiting_action_once(
    tmp_path: Path,
    remove_current_grant: bool,
) -> None:
    database_path = tmp_path / "approved-intermediate.db"
    engine = create_sqlite_engine(database_path)
    create_tables(engine)
    recording = RecordingCoordinator()
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        work_coordinator=recording,
        governance_service_factory=lambda: GovernanceService(
            SqlAlchemyUnitOfWork(engine), PolicyEngine(), recording
        ),
    )
    with TestClient(create_app(assembly=assembly)) as client:
        workspace = client.post("/workspaces", json={"name": "Approval restart"}).json()
        employee = _create_employee(
            client,
            workspace["id"],
            "Approver",
            grants=(_grant_payload("workspace.write", approval=True),),
        )
        work = _create_work(client, workspace["id"], employee["id"], "approval-restart")
        grants = (_grant("workspace.write", approval=True),)
        _configure_grants(engine, workspace["id"], work["nodes"][0]["id"], grants)
        service = assembly.governance_service_factory()
        approval = service.authorize(
            GovernedAction(
                node_id=WorkNodeId(work["nodes"][0]["id"]),
                action="workspace.write",
                resources=("repo-a",),
                reason="Recover an approved action",
            )
        )
        assert isinstance(approval, Approval)
        service.approve(approval.id, decided_by="operator")
        if remove_current_grant:
            with SqlAlchemyUnitOfWork(engine) as uow:
                uow.workspace_grants.replace(WorkspaceId(workspace["id"]), ())
                uow.commit()
    engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    handler = RuntimeGovernanceHandler(
        lambda: SqlAlchemyUnitOfWork(restarted_engine), PolicyEngine()
    )
    coordinator = StartupRecordingCoordinator(
        lambda: SqlAlchemyUnitOfWork(restarted_engine),
        UnusedGateway(),
        governance_handler=handler,
    )
    coordinator.start()
    handler.reconcile_startup()
    coordinator.start()
    with SqlAlchemyUnitOfWork(restarted_engine) as uow:
        stored = uow.works.get(WorkId(work["id"]))
        stored_approval = uow.approvals.get(approval.id)
    coordinator.shutdown(wait=True)

    assert stored is not None and stored_approval is not None
    assert stored_approval.status is ApprovalStatus.APPROVED
    if remove_current_grant:
        assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
        assert stored.nodes[0].failure_code == "workspace_not_granted"
        assert coordinator.enqueued == []
    else:
        assert stored.nodes[0].status is WorkNodeStatus.READY
        assert stored.nodes[0].failure_code is None
        assert coordinator.enqueued == [WorkNodeId(work["nodes"][0]["id"])]
    restarted_engine.dispose()
    database_path.unlink()


def test_startup_resumes_committed_completed_delegation_child_once(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "delegation-intermediate.db"
    engine = create_sqlite_engine(database_path)
    create_tables(engine)
    recording = RecordingCoordinator()
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        work_coordinator=recording,
        delegation_service_factory=lambda: DelegationService(
            SqlAlchemyUnitOfWork(engine), PolicyEngine(), recording
        ),
    )
    with TestClient(create_app(assembly=assembly)) as client:
        workspace = client.post("/workspaces", json={"name": "Delegation restart"}).json()
        proposer = _create_employee(
            client,
            workspace["id"],
            "Proposer",
            grants=(_grant_payload("work.delegate"), _grant_payload("workspace.read")),
        )
        target = _create_employee(
            client,
            workspace["id"],
            "Target",
            runtime_profile="workspace_read",
            grants=(_grant_payload("workspace.read"),),
        )
        work = _create_work(client, workspace["id"], proposer["id"], "delegation-restart")
        _configure_grants(
            engine,
            workspace["id"],
            work["nodes"][0]["id"],
            (_grant("work.delegate"), _grant("workspace.read")),
        )
        _mark_running(engine, work["id"])
        delegated = client.post(
            f"/works/{work['id']}/delegations",
            json={
                "source_node_id": work["nodes"][0]["id"],
                "proposer_employee_id": proposer["id"],
                "target_employee_id": target["id"],
                "objective": "Complete the child",
                "acceptance_criteria": ["Return a reference"],
                "required_actions": ["workspace.read"],
                "resource_values": ["repo-a"],
            },
        )
        delegated.raise_for_status()
        delegation_id = delegated.json()["delegation"]["id"]
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get(WorkId(work["id"]))
        assert aggregate is not None
        parent, child = aggregate.nodes
        child_link = next(
            link for link in aggregate.execution_links if link.node_id == child.id
        )
        uow.works.update(
            replace(
                aggregate,
                nodes=(parent, child.start(child_link.attempt_id)),
                execution_links=tuple(
                    child_link.mark_running() if link.id == child_link.id else link
                    for link in aggregate.execution_links
                ),
            )
        )
        uow.commit()
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get(WorkId(work["id"]))
        assert aggregate is not None
        parent, running_child = aggregate.nodes
        running_link = next(
            link for link in aggregate.execution_links if link.node_id == running_child.id
        )
        artifact_id = ArtifactReferenceId("artifact-restart-child")
        artifact = ArtifactReference(
            id=artifact_id,
            workspace_id=aggregate.work.workspace_id,
            kind="dsh_session_result",
            uri=f"dsh-session://{running_link.dsh_session_id}/attempt/{running_link.attempt_id}/result",
            source_session_id=running_link.dsh_session_id,
            source_attempt_id=running_link.attempt_id,
            created_at=datetime.now(UTC),
        )
        uow.works.update(
            replace(
                aggregate,
                nodes=(parent, running_child.complete(running_link.attempt_id, artifact_id)),
                execution_links=tuple(
                    running_link.complete(running_link.attempt_id, artifact_id)
                    if link.id == running_link.id
                    else link
                    for link in aggregate.execution_links
                ),
                artifacts=(*aggregate.artifacts, artifact),
            )
        )
        uow.commit()
    engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    handler = RuntimeGovernanceHandler(
        lambda: SqlAlchemyUnitOfWork(restarted_engine), PolicyEngine()
    )
    coordinator = StartupRecordingCoordinator(
        lambda: SqlAlchemyUnitOfWork(restarted_engine),
        UnusedGateway(),
        governance_handler=handler,
    )
    coordinator.start()
    handler.reconcile_startup()
    coordinator.start()
    with SqlAlchemyUnitOfWork(restarted_engine) as uow:
        recovered = uow.works.get(WorkId(work["id"]))
        delegation = uow.delegations.get(delegation_id)
    coordinator.shutdown(wait=True)

    assert recovered is not None and delegation is not None
    parent = recovered.nodes[0]
    assert delegation.status == "completed"
    assert parent.status is WorkNodeStatus.READY
    assert parent.input_references == (artifact_id,)
    parent_links = tuple(
        link for link in recovered.execution_links if link.node_id == parent.id
    )
    assert len(parent_links) == 2
    assert coordinator.enqueued == [parent.id]
    restarted_engine.dispose()
    database_path.unlink()


class _GovernanceModelServer(ThreadingHTTPServer):
    requests: list[dict[str, Any]]
    target_employee_id: str


class _GovernanceModelHandler(BaseHTTPRequestHandler):
    server: _GovernanceModelServer

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append(body)
        rendered = json.dumps(body)
        if "RUNTIME_DELEGATION_CONTROL" in rendered:
            response = json.dumps(
                {
                    "kind": "delegation",
                    "target_employee_id": self.server.target_employee_id,
                    "objective": "remember DELEGATED_CHILD",
                    "acceptance_criteria": ["Return the child marker"],
                    "required_actions": ["workspace.read"],
                    "resource_values": ["repo-a"],
                    "reason": "Delegate through the exposed control path",
                }
            )
        else:
            response = "stored remember DELEGATED_CHILD"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        chunks = (
            'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n',
            f"data: {json.dumps({'choices': [{'delta': {'content': response}}]})}\n\n",
            'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":3}}\n\n',
            "data: [DONE]\n\n",
        )
        for chunk in chunks:
            self.wfile.write(chunk.encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


class GovernanceModelEndpoint:
    def __init__(self) -> None:
        self._server = _GovernanceModelServer(("127.0.0.1", 0), _GovernanceModelHandler)
        self._server.requests = []
        self._server.target_employee_id = ""
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> GovernanceModelEndpoint:
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    @property
    def base_url(self) -> str:
        host = str(self._server.server_address[0])
        port = int(self._server.server_address[1])
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self._server.requests

    def target(self, employee_id: str) -> None:
        self._server.target_employee_id = employee_id


@pytest.fixture
def runtime_database(tmp_path: Path) -> Iterator[tuple[Engine, Path]]:
    database_path = tmp_path / "runtime-governance.db"
    engine = create_sqlite_engine(database_path)
    create_tables(engine)
    try:
        yield engine, database_path
    finally:
        engine.dispose()
        if database_path.exists():
            database_path.unlink()


def test_keyless_runtime_delegation_resumes_parent_by_reference_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_database: tuple[Engine, Path],
) -> None:
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    engine, database_path = runtime_database
    recording = RecordingCoordinator()
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        work_coordinator=recording,
    )
    with GovernanceModelEndpoint() as endpoint:
        with TestClient(create_app(assembly=assembly)) as client:
            workspace = client.post("/workspaces", json={"name": "Runtime governance"}).json()
            proposer = _create_employee(
                client,
                workspace["id"],
                "Runtime proposer",
                grants=(_grant_payload("work.delegate"), _grant_payload("workspace.read")),
            )
            target = _create_employee(
                client,
                workspace["id"],
                "Runtime target",
                runtime_profile="workspace_read",
                grants=(_grant_payload("workspace.read"),),
            )
            endpoint.target(target["id"])
            work = _create_work(
                client,
                workspace["id"],
                proposer["id"],
                "runtime-delegation",
                objective="remember RUNTIME_DELEGATION_CONTROL",
            )
            _configure_grants(
                engine,
                workspace["id"],
                work["nodes"][0]["id"],
                (_grant("work.delegate"), _grant("workspace.read")),
            )

        (tmp_path / "sessions").mkdir()
        (tmp_path / "workspace").mkdir()
        gateway = PublicSdkDshGateway(
            session_root=tmp_path / "sessions",
            working_directory=tmp_path / "workspace",
            base_url=endpoint.base_url,
            api_key="dsh-company-keyless-test",
            request_timeout_seconds=20,
            shutdown_timeout_seconds=2,
        )
        handler = RuntimeGovernanceHandler(
            lambda: SqlAlchemyUnitOfWork(engine), PolicyEngine()
        )
        coordinator = RuntimeCoordinator(
            lambda: SqlAlchemyUnitOfWork(engine),
            gateway,
            governance_handler=handler,
            runtime_concurrency=1,
        )
        try:
            coordinator.enqueue(WorkNodeId(work["nodes"][0]["id"]))
            deadline = time.monotonic() + 30
            aggregate = None
            while time.monotonic() < deadline:
                with SqlAlchemyUnitOfWork(engine) as uow:
                    aggregate = uow.works.get(WorkId(work["id"]))
                assert aggregate is not None
                parent = aggregate.nodes[0]
                if (
                    len(aggregate.nodes) == 2
                    and parent.status is WorkNodeStatus.FAILED
                    and len(aggregate.execution_links) == 3
                ):
                    break
                time.sleep(0.02)
        finally:
            coordinator.shutdown(wait=True)
        with SqlAlchemyUnitOfWork(engine) as uow:
            aggregate = uow.works.get(WorkId(work["id"]))
            events = uow.company_events.list_for_work(WorkId(work["id"]))

        with TestClient(create_app(assembly=assembly)) as client:
            work_response = client.get(f"/works/{work['id']}")
            events_response = client.get(f"/works/{work['id']}/events")
            work_response.raise_for_status()
            events_response.raise_for_status()
            api_facts = [work_response.json(), events_response.json()]

    assert aggregate is not None
    assert aggregate.graph.revision_number == 2
    assert len(aggregate.graph.edges) == 1
    parent, child = aggregate.nodes
    assert child.status is WorkNodeStatus.COMPLETED
    assert len(aggregate.artifacts) == 1
    assert parent.input_references == (aggregate.artifacts[0].id,)
    parent_links = tuple(link for link in aggregate.execution_links if link.node_id == parent.id)
    assert len(parent_links) == 2
    resumed_link = next(
        link for link in parent_links if link.status is ExecutionStatus.FAILED
    )
    assert resumed_link.diagnostic_code == "gateway_error"
    assert parent.status is WorkNodeStatus.FAILED
    assert parent.failure_code == "gateway_error"
    assert len(endpoint.requests) == 2
    serialized_company_facts = json.dumps(
        {
            "api": api_facts,
            "events": [
                {"type": item.event_type, "summary": item.summary}
                for item in events
            ]
        }
    )
    with closing(sqlite3.connect(database_path)) as connection:
        database_dump = "\n".join(connection.iterdump())
    assert "final_response" not in serialized_company_facts
    assert "stored remember DELEGATED_CHILD" not in serialized_company_facts
    assert "stored remember DELEGATED_CHILD" not in database_dump
