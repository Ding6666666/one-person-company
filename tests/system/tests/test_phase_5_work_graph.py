import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
)
from dsh_company.domain.policy import PolicyEngine
from dsh_company.domain.work import (
    ExecutionStatus,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
)
from dsh_company.dsh_gateway.contracts import (
    GatewayCancelResult,
    GatewayResult,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.events import ProjectedDshEvent
from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.foundation.config import Settings
from dsh_company.orchestration.durable_graph import DurableGraphEngine
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

_KEYLESS_STRATEGY_BUDGET_SECONDS = 15


class QuietGateway:
    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult:
        del submission, on_event
        raise AssertionError("system test dispatch is controlled explicitly")

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult:
        del attempt_id
        return GatewayCancelResult(requested=True, runtime_closed=True)

    def shutdown(self) -> None:
        return None


class ManualCoordinator(RuntimeCoordinator):
    def __init__(self, factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        super().__init__(factory, QuietGateway(), runtime_concurrency=4)
        self.enqueued: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = create_sqlite_engine(tmp_path / "phase-5-graph.db")
    create_tables(value)
    yield value
    value.dispose()


def _factory(engine: Engine) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(engine)


def _system(
    engine: Engine, *, capacity: int
) -> tuple[TestClient, DurableGraphEngine, ManualCoordinator]:
    factory = _factory(engine)
    coordinator = ManualCoordinator(factory)
    registry = BusinessPluginRegistry(factory)
    graph = DurableGraphEngine(
        factory,
        coordinator,
        policy_engine=PolicyEngine(registry.action_catalog),
        runtime_concurrency=capacity,
    )
    assembly = ComponentAssembly(
        uow_factory=factory,
        work_coordinator=coordinator,
        orchestration_engine=graph,
    )
    return TestClient(create_app(assembly=assembly)), graph, coordinator


def _employee(client: TestClient, workspace_id: str, name: str) -> dict[str, object]:
    response = client.post(
        f"/workspaces/{workspace_id}/employees",
        json={
            "display_name": name,
            "responsibility": "Execute a bounded graph node",
            "runtime_profile": "workspace_read",
            "model": "keyless-system-model",
            "grants": [],
        },
    )
    response.raise_for_status()
    return response.json()


def _wait_for_terminal(client: TestClient, work_id: str) -> dict[str, object]:
    deadline = time.monotonic() + _KEYLESS_STRATEGY_BUDGET_SECONDS
    while time.monotonic() < deadline:
        response = client.get(f"/works/{work_id}")
        response.raise_for_status()
        work = response.json()
        if work["status"] in {"completed", "failed", "blocked", "cancelled"}:
            return work
        time.sleep(0.02)
    raise AssertionError(f"work {work_id} did not reach a terminal state")


def _mark_running(engine: Engine, node_id: WorkNodeId) -> AttemptId:
    with SqlAlchemyUnitOfWork(engine) as uow:
        aggregate = uow.works.get_for_node(node_id)
        assert aggregate is not None
        node = next(item for item in aggregate.nodes if item.id == node_id)
        link = next(
            item
            for item in aggregate.execution_links
            if item.node_id == node_id
            and item.status is ExecutionStatus.DISPATCH_PENDING
        )
        work = (
            aggregate.work.start()
            if aggregate.work.status is WorkStatus.QUEUED
            else aggregate.work
        )
        uow.works.update(
            replace(
                aggregate,
                work=work,
                nodes=tuple(
                    node.start(link.attempt_id) if item.id == node_id else item
                    for item in aggregate.nodes
                ),
                execution_links=tuple(
                    link.mark_running() if item.id == link.id else item
                    for item in aggregate.execution_links
                ),
            )
        )
        uow.commit()
        return link.attempt_id


def _immutable_revision_facts(
    revision: tuple[WorkGraphRevision, tuple[WorkNode, ...]],
) -> tuple[WorkGraphRevision, tuple[tuple[object, ...], ...]]:
    graph, nodes = revision
    return graph, tuple(
        (
            node.id,
            node.graph_revision_id,
            node.work_id,
            node.objective,
            node.acceptance_criteria,
            node.assigned_employee_id,
            node.employee_revision_id,
            node.required_actions,
            node.resource_values,
            node.max_attempts,
        )
        for node in nodes
    )


def test_graph_system_bounds_dispatch_and_preserves_partial_summary_facts(
    engine: Engine,
) -> None:
    client, graph, coordinator = _system(engine, capacity=2)
    with client:
        workspace = client.post("/workspaces", json={"name": "Graph system"}).json()
        employees = [
            _employee(client, workspace["id"], name)
            for name in ("First", "Second", "Dependent", "Summary")
        ]
        response = client.post(
            f"/workspaces/{workspace['id']}/works",
            json={
                "kind": "graph",
                "objective": "Exercise durable graph facts",
                "acceptance_criteria": ["Every transition is durable"],
                "command_id": "phase-5-graph-system",
                "nodes": [
                    {
                        "key": key,
                        "employee_id": employee["id"],
                        "objective": key,
                        "acceptance_criteria": ["Recorded"],
                    }
                    for key, employee in zip(
                        ("first", "second", "dependent", "summary"),
                        employees,
                        strict=True,
                    )
                ],
                "edges": [
                    {"from_key": "first", "to_key": "dependent", "kind": "depends_on"},
                    {"from_key": "first", "to_key": "summary", "kind": "summarizes"},
                    {"from_key": "second", "to_key": "summary", "kind": "summarizes"},
                ],
            },
        )
        response.raise_for_status()
        created = response.json()
        node_ids = {
            node["objective"]: WorkNodeId(node["id"]) for node in created["nodes"]
        }
        graph_id = WorkGraphRevisionId(created["graph_revision_id"])
        with SqlAlchemyUnitOfWork(engine) as uow:
            original_revision = uow.works.get_revision(graph_id)
        assert original_revision is not None
        assert coordinator.enqueued == [node_ids["first"], node_ids["second"]]

        first_attempt = _mark_running(engine, node_ids["first"])
        second_attempt = _mark_running(engine, node_ids["second"])
        graph.record_completion(
            node_ids["first"], first_attempt, ArtifactReferenceId("artifact-first")
        )
        assert coordinator.enqueued[-1] == node_ids["dependent"]
        graph.record_failure(node_ids["second"], second_attempt, "gateway_error")
        assert coordinator.enqueued[-1] == node_ids["summary"]
        graph.request_cancel(node_ids["dependent"])

        with SqlAlchemyUnitOfWork(engine) as uow:
            aggregate = uow.works.get(WorkId(created["id"]))
            preserved_revision = uow.works.get_revision(graph_id)
        assert aggregate is not None
        by_id = {node.id: node for node in aggregate.nodes}
        assert by_id[node_ids["first"]].status is WorkNodeStatus.COMPLETED
        assert by_id[node_ids["second"]].status is WorkNodeStatus.FAILED
        assert by_id[node_ids["dependent"]].failure_code == "cancel_unconfirmed"
        assert by_id[node_ids["summary"]].input_references == (
            ArtifactReferenceId("artifact-first"),
            node_ids["second"],
        )
        assert preserved_revision is not None
        assert _immutable_revision_facts(preserved_revision) == _immutable_revision_facts(
            original_revision
        )
        coordinator.shutdown()


def test_retry_and_restart_create_new_attempts_without_cold_resume(
    engine: Engine,
) -> None:
    client, graph, coordinator = _system(engine, capacity=1)
    with client:
        workspace = client.post("/workspaces", json={"name": "Retry system"}).json()
        employee = _employee(client, workspace["id"], "Retry employee")
        response = client.post(
            f"/workspaces/{workspace['id']}/works",
            json={
                "kind": "graph",
                "objective": "Retry explicitly",
                "acceptance_criteria": ["Attempts remain immutable"],
                "command_id": "phase-5-retry-system",
                "nodes": [
                    {
                        "key": "retry",
                        "employee_id": employee["id"],
                        "objective": "retry",
                        "acceptance_criteria": ["Recorded"],
                        "max_attempts": 3,
                    }
                ],
                "edges": [],
            },
        )
        response.raise_for_status()
        created = response.json()
        work_id = WorkId(created["id"])
        node_id = WorkNodeId(created["nodes"][0]["id"])
        graph_id = WorkGraphRevisionId(created["graph_revision_id"])
        with SqlAlchemyUnitOfWork(engine) as uow:
            original_revision = uow.works.get_revision(graph_id)

        first_attempt = _mark_running(engine, node_id)
        graph.record_failure(node_id, first_attempt, "gateway_error")
        second_attempt = _mark_running(engine, node_id)
        restart = ManualCoordinator(_factory(engine))
        restart.start()

        with SqlAlchemyUnitOfWork(engine) as uow:
            blocked = uow.works.get(work_id)
        assert blocked is not None
        assert blocked.nodes[0].status is WorkNodeStatus.BLOCKED
        assert blocked.nodes[0].failure_code == "runtime_process_lost"
        assert [link.status for link in blocked.execution_links] == [
            ExecutionStatus.FAILED,
            ExecutionStatus.BLOCKED,
        ]
        assert blocked.execution_links[1].attempt_id == second_attempt

        graph.reconcile(work_id)
        with SqlAlchemyUnitOfWork(engine) as uow:
            retried = uow.works.get(work_id)
            preserved_revision = uow.works.get_revision(graph_id)
        assert retried is not None
        assert retried.nodes[0].attempt_count == 3
        assert len(retried.execution_links) == 3
        assert original_revision is not None and preserved_revision is not None
        assert _immutable_revision_facts(preserved_revision) == _immutable_revision_facts(
            original_revision
        )
        restart.shutdown()
        coordinator.shutdown()


def test_graph_approval_waits_before_runtime_dispatch(engine: Engine) -> None:
    client, _graph, coordinator = _system(engine, capacity=1)
    with client:
        workspace = client.post("/workspaces", json={"name": "Approval system"}).json()
        grant = {
            "action": "workspace.read",
            "level": 1,
            "resource_kind": "workspace",
            "resource_values": [workspace["id"]],
            "requires_approval": True,
        }
        employee = client.post(
            f"/workspaces/{workspace['id']}/employees",
            json={
                "display_name": "Approval employee",
                "responsibility": "Wait for approval",
                "runtime_profile": "workspace_read",
                "model": "keyless-system-model",
                "grants": [grant],
            },
        ).json()
        assert (
            client.put(
                f"/workspaces/{workspace['id']}/capabilities",
                json={"grants": [{**grant, "requires_approval": False}]},
            ).status_code
            == 200
        )
        response = client.post(
            f"/workspaces/{workspace['id']}/works",
            json={
                "kind": "graph",
                "objective": "Wait for approval",
                "acceptance_criteria": ["No early dispatch"],
                "command_id": "phase-5-approval-system",
                "nodes": [
                    {
                        "key": "approval",
                        "employee_id": employee["id"],
                        "objective": "approval",
                        "acceptance_criteria": ["Approved"],
                        "required_actions": ["workspace.read"],
                        "resource_kinds": ["workspace"],
                        "resource_values": [workspace["id"]],
                    }
                ],
                "edges": [],
            },
        )

        assert response.status_code == 202
        assert response.json()["nodes"][0]["status"] == "waiting_approval"
        assert coordinator.enqueued == []
        approvals = client.get(f"/workspaces/{workspace['id']}/approvals").json()
        assert len(approvals) == 1
        assert approvals[0]["status"] == "pending"
        coordinator.shutdown()


def test_direct_star_graph_and_battle_share_one_keyless_model_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dsh-company-keyless-test")
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    with KeylessModelEndpoint() as endpoint:
        settings = Settings(
            data_root=tmp_path / "keyless-data",
            session_root=tmp_path / "keyless-sessions",
            workspace_root=tmp_path / "keyless-workspaces",
            dsh_base_url=endpoint.base_url,
            dsh_request_timeout_seconds=20,
            dsh_shutdown_timeout_seconds=2,
            # This comparison isolates strategy topology. The pinned public DSH
            # runtime does not guarantee concurrent Session.run completion, so
            # bounded parallel scheduling is verified separately above.
            runtime_concurrency=1,
        )
        with TestClient(create_app(settings=settings)) as client:
            workspace = client.post(
                "/workspaces", json={"name": "Fixed strategy comparison"}
            ).json()
            employees = [
                _employee(client, workspace["id"], f"Comparison {index}")
                for index in range(8)
            ]
            common = {
                "objective": "remember PHASE_5_FIXED_COMPARISON",
                "acceptance_criteria": ["Return the keyless result"],
            }
            payloads = (
                {
                    **common,
                    "kind": "direct",
                    "command_id": "baseline-direct",
                    "employee_id": employees[0]["id"],
                },
                {
                    **common,
                    "kind": "star",
                    "command_id": "baseline-star",
                    "coordinator_employee_id": employees[1]["id"],
                    "children": [
                        {
                            "employee_id": employees[2]["id"],
                            "objective": "remember PHASE_5_FIXED_COMPARISON",
                            "acceptance_criteria": ["Return the keyless result"],
                        }
                    ],
                },
                {
                    **common,
                    "kind": "graph",
                    "command_id": "baseline-graph",
                    "nodes": [
                        {
                            "key": "first",
                            "employee_id": employees[3]["id"],
                            "objective": "remember PHASE_5_FIXED_COMPARISON",
                            "acceptance_criteria": ["Return the keyless result"],
                        },
                        {
                            "key": "second",
                            "employee_id": employees[4]["id"],
                            "objective": "remember PHASE_5_FIXED_COMPARISON",
                            "acceptance_criteria": ["Return the keyless result"],
                        },
                    ],
                    "edges": [
                        {"from_key": "first", "to_key": "second", "kind": "depends_on"}
                    ],
                },
                {
                    **common,
                    "kind": "battle",
                    "command_id": "baseline-battle",
                    "participant_employee_ids": [employees[5]["id"], employees[6]["id"]],
                    "summarizer_employee_id": employees[7]["id"],
                },
            )

            completed = []
            for payload in payloads:
                response = client.post(
                    f"/workspaces/{workspace['id']}/works", json=payload
                )
                response.raise_for_status()
                completed.append(_wait_for_terminal(client, response.json()["id"]))

        assert [work["status"] for work in completed] == ["completed"] * 4
        assert len(endpoint.requests) == 8
