from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Thread

import pytest
from dsh_company.application.governance_service import GovernanceService
from dsh_company.application.ports import WorkAggregate
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.delegation import Delegation
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CapabilityGrantId,
    DelegationId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.policy import DecisionKind, PolicyEngine
from dsh_company.domain.work import (
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
    WorkStrategy,
)
from dsh_company.domain.workspace import Workspace
from dsh_company.dsh_gateway.contracts import GatewayCancelResult, GatewayResult
from dsh_company.foundation.assembly import create_production_assembly
from dsh_company.foundation.config import Settings
from dsh_company.orchestration.contracts import OrchestrationEngine
from dsh_company.orchestration.durable_graph import DurableGraphEngine
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from dsh_company.persistence.work_repositories import (
    ConcurrentWorkUpdate,
    WorkRepository,
)
from sqlalchemy.engine import Engine


class RecordingCoordinator:
    def __init__(self) -> None:
        self.enqueued: list[WorkNodeId] = []
        self.cancelled: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        self.cancelled.append(node_id)


class StableIds:
    def __call__(self, prefix: str) -> str:
        raise AssertionError(f"random ID requested for {prefix}")


class CompletingGateway:
    def __init__(self) -> None:
        self.node_ids: list[WorkNodeId] = []

    def submit(self, submission, *, on_event):  # type: ignore[no-untyped-def]
        del on_event
        command_parts = submission.command_id.split(":")
        self.node_ids.append(
            WorkNodeId(
                command_parts[-2]
                if len(command_parts) >= 4
                else submission.command_id.removesuffix("-command")
            )
        )
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


class FailingGateway(CompletingGateway):
    def submit(self, submission, *, on_event):  # type: ignore[no-untyped-def]
        del submission, on_event
        raise RuntimeError("private provider failure")


class ObserverProxy:
    target: DurableGraphEngine | None = None

    def __init__(self) -> None:
        self.work_ids: list[WorkId] = []

    def reconcile(self, work_id: WorkId) -> None:
        self.work_ids.append(work_id)
        assert self.target is not None
        self.target.reconcile(work_id)


class InlineRuntimeCoordinator(RuntimeCoordinator):
    def enqueue(self, node_id: WorkNodeId) -> None:
        self.dispatch(node_id)


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    yield engine
    engine.dispose()


def _factory(engine: Engine) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(engine)


def _node(
    node_id: str,
    *,
    status: WorkNodeStatus = WorkNodeStatus.DRAFT,
    max_attempts: int = 1,
    attempt_count: int = 0,
    required_actions: tuple[str, ...] = (),
) -> WorkNode:
    return WorkNode(
        id=WorkNodeId(node_id),
        graph_revision_id=WorkGraphRevisionId("graph-1"),
        work_id=WorkId("work-1"),
        objective=f"objective {node_id}",
        acceptance_criteria=("done",),
        assigned_employee_id=EmployeeId(f"employee-{node_id}"),
        employee_revision_id=EmployeeRevisionId(f"revision-{node_id}"),
        status=status,
        active_attempt_id=None,
        failure_code=None,
        version=1,
        max_attempts=max_attempts,
        attempt_count=attempt_count,
        required_actions=required_actions,
        resource_values=("ws-1",),
    )


def _seed(
    engine: Engine,
    nodes: tuple[WorkNode, ...],
    edges: tuple[WorkEdge, ...] = (),
    links: tuple[ExecutionLink, ...] = (),
    work_status: WorkStatus = WorkStatus.QUEUED,
    approval_action: str | None = None,
    approval_actions: tuple[str, ...] = (),
) -> None:
    governed_actions = approval_actions or (() if approval_action is None else (approval_action,))
    with SqlAlchemyUnitOfWork(engine) as uow:
        workspace = Workspace.create(WorkspaceId("ws-1"), "Graph tests")
        uow.workspaces.add(workspace)
        stored_nodes: list[WorkNode] = []
        for node in nodes:
            employee, revision, binding = Employee.create(
                employee_id=node.assigned_employee_id,
                workspace_id=workspace.id,
                display_name=f"Employee {node.id}",
                responsibility="Execute graph node",
                runtime_profile="workspace_read",
                model="model",
            )
            employee_grants = tuple(
                    CapabilityGrant(
                        id=CapabilityGrantId(f"employee-grant-{node.id}-{action}"),
                        employee_revision_id=revision.id,
                        action=action,
                        level=CapabilityLevel.L1,
                        resource_kind="workspace",
                        resource_values=("ws-1",),
                        requires_approval=True,
                    )
                    for action in governed_actions
            )
            uow.employees.add(employee, revision, binding, employee_grants)
            stored_nodes.append(replace(node, employee_revision_id=revision.id))
        graph = WorkGraphRevision(
            id=WorkGraphRevisionId("graph-1"),
            work_id=WorkId("work-1"),
            revision_number=1,
            strategy=WorkStrategy.DIRECT,
            created_at=datetime.now(UTC),
            node_ids=tuple(node.id for node in stored_nodes),
            edges=edges,
        )
        work = Work(
            id=WorkId("work-1"),
            workspace_id=workspace.id,
            command_id="graph-command",
            objective="execute graph",
            status=work_status,
            current_graph_revision_id=graph.id,
            created_at=datetime.now(UTC),
        )
        uow.works.add(WorkAggregate(work, graph, tuple(stored_nodes), links, ()))
        if governed_actions:
            uow.workspace_grants.replace(
                workspace.id,
                tuple(
                    CapabilityGrant(
                        id=CapabilityGrantId(f"workspace-grant-{action}"),
                        employee_revision_id=None,
                        action=action,
                        level=CapabilityLevel.L1,
                        resource_kind="workspace",
                        resource_values=("ws-1",),
                        requires_approval=False,
                    )
                    for action in governed_actions
                ),
            )
            for node in stored_nodes:
                uow.node_grants.replace(
                    node.id,
                    tuple(
                        CapabilityGrant(
                            id=CapabilityGrantId(f"node-grant-{node.id}-{action}"),
                            employee_revision_id=None,
                            action=action,
                            level=CapabilityLevel.L1,
                            resource_kind="workspace",
                            resource_values=("ws-1",),
                            requires_approval=False,
                        )
                        for action in governed_actions
                    ),
                )
        uow.commit()


def _engine(
    engine: Engine, coordinator: RecordingCoordinator, *, capacity: int = 4
) -> DurableGraphEngine:
    return DurableGraphEngine(
        _factory(engine),
        coordinator,
        runtime_concurrency=capacity,
        id_factory=StableIds(),
    )


def _add_parallel_work(engine: Engine, work_id: str, node_count: int = 4) -> None:
    with SqlAlchemyUnitOfWork(engine) as uow:
        workspace = uow.workspaces.get(WorkspaceId("ws-1"))
        if workspace is None:
            workspace = Workspace.create(WorkspaceId("ws-1"), "Capacity tests")
            uow.workspaces.add(workspace)
        graph_id = WorkGraphRevisionId(f"graph-{work_id}")
        nodes: list[WorkNode] = []
        for number in range(node_count):
            employee, revision, binding = Employee.create(
                employee_id=EmployeeId(f"employee-{work_id}-{number}"),
                workspace_id=workspace.id,
                display_name=f"Employee {work_id} {number}",
                responsibility="Execute graph node",
                runtime_profile="workspace_read",
                model="model",
            )
            uow.employees.add(employee, revision, binding, ())
            nodes.append(
                replace(
                    _node(f"node-{work_id}-{number}"),
                    graph_revision_id=graph_id,
                    work_id=WorkId(work_id),
                    assigned_employee_id=employee.id,
                    employee_revision_id=revision.id,
                )
            )
        graph = WorkGraphRevision(
            id=graph_id,
            work_id=WorkId(work_id),
            revision_number=1,
            strategy=WorkStrategy.DIRECT,
            created_at=datetime.now(UTC),
            node_ids=tuple(node.id for node in nodes),
        )
        work = Work(
            id=WorkId(work_id),
            workspace_id=workspace.id,
            command_id=f"command-{work_id}",
            objective="parallel capacity",
            status=WorkStatus.QUEUED,
            current_graph_revision_id=graph.id,
            created_at=datetime.now(UTC),
        )
        uow.works.add(WorkAggregate(work, graph, tuple(nodes), (), ()))
        uow.commit()


def test_engine_implements_exact_orchestration_port() -> None:
    assert OrchestrationEngine


def test_only_nodes_with_completed_dependencies_become_ready(
    sqlite_engine: Engine,
) -> None:
    a = _node("a", status=WorkNodeStatus.COMPLETED)
    b = _node("b", status=WorkNodeStatus.RUNNING)
    c = _node("c")
    _seed(
        sqlite_engine,
        (a, b, c),
        (
            WorkEdge(a.id, c.id, WorkEdgeKind.DEPENDS_ON),
            WorkEdge(b.id, c.id, WorkEdgeKind.DEPENDS_ON),
        ),
    )
    coordinator = RecordingCoordinator()

    ready = _engine(sqlite_engine, coordinator).dispatch_ready_nodes(WorkId("work-1"))

    assert ready == ()
    assert coordinator.enqueued == []


def test_dispatch_is_globally_bounded_stable_and_idempotent(
    sqlite_engine: Engine,
) -> None:
    nodes = tuple(_node(f"node-{number}") for number in range(1, 11))
    _seed(sqlite_engine, nodes)
    coordinator = RecordingCoordinator()
    engine = _engine(sqlite_engine, coordinator)

    dispatched = engine.dispatch_ready_nodes(WorkId("work-1"))
    repeated = engine.dispatch_ready_nodes(WorkId("work-1"))

    assert len(dispatched) == 4
    assert repeated == ()
    assert [item.command_id for item in dispatched[:2]] == [
        "work-1:graph-1:node-1:attempt-1",
        "work-1:graph-1:node-2:attempt-1",
    ]
    assert coordinator.enqueued == [item.node_id for item in dispatched]
    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert [node.attempt_count for node in stored.nodes[:4]] == [1, 1, 1, 1]


def test_capacity_reservation_is_atomic_across_independent_engines(
    sqlite_engine: Engine,
) -> None:
    _add_parallel_work(sqlite_engine, "work-a")
    _add_parallel_work(sqlite_engine, "work-b")
    database = sqlite_engine.url.database
    assert database is not None
    second_engine = create_sqlite_engine(Path(database))
    coordinators = (RecordingCoordinator(), RecordingCoordinator())
    engines = (
        DurableGraphEngine(
            _factory(sqlite_engine), coordinators[0], runtime_concurrency=4
        ),
        DurableGraphEngine(
            _factory(second_engine), coordinators[1], runtime_concurrency=4
        ),
    )
    barrier = Barrier(3)
    errors: list[BaseException] = []

    def dispatch(engine: DurableGraphEngine, work_id: WorkId) -> None:
        try:
            barrier.wait(timeout=2)
            engine.reconcile(work_id)
        except BaseException as error:
            errors.append(error)

    threads = [
        Thread(target=dispatch, args=(engines[0], WorkId("work-a"))),
        Thread(target=dispatch, args=(engines[1], WorkId("work-b"))),
    ]

    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    with _factory(sqlite_engine)() as uow:
        aggregates = tuple(
            uow.works.get(WorkId(work_id)) for work_id in ("work-a", "work-b")
        )
        assert all(aggregate is not None for aggregate in aggregates)
        persisted = sum(
            len(aggregate.execution_links)
            for aggregate in aggregates
            if aggregate is not None
        )
    assert persisted <= 4
    assert sum(len(item.enqueued) for item in coordinators) == persisted
    second_engine.dispose()


def test_failed_dependency_blocks_downstream_with_closed_reason(
    sqlite_engine: Engine,
) -> None:
    upstream = _node("upstream", status=WorkNodeStatus.FAILED)
    downstream = _node("downstream")
    _seed(
        sqlite_engine,
        (upstream, downstream),
        (WorkEdge(upstream.id, downstream.id, WorkEdgeKind.DEPENDS_ON),),
    )

    _engine(sqlite_engine, RecordingCoordinator()).reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[1].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[1].failure_code == "dependency_failed"


def test_projection_only_concurrent_work_update_reloads_and_retries(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(
        sqlite_engine,
        (_node("completed", status=WorkNodeStatus.COMPLETED),),
        work_status=WorkStatus.RUNNING,
    )
    original_update = WorkRepository.update
    update_calls = 0

    def fail_first_update(
        repository: WorkRepository, aggregate: WorkAggregate
    ) -> None:
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            raise ConcurrentWorkUpdate(str(aggregate.work.id))
        original_update(repository, aggregate)

    monkeypatch.setattr(WorkRepository, "update", fail_first_update)

    _engine(sqlite_engine, RecordingCoordinator()).reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.work.status is WorkStatus.COMPLETED
    assert update_calls == 2


def test_review_and_summary_edges_add_only_typed_persistent_inputs(
    sqlite_engine: Engine,
) -> None:
    review_source = replace(
        _node("review-source", status=WorkNodeStatus.COMPLETED),
        output_references=(ArtifactReferenceId("artifact-review"),),
    )
    failed_source = _node("failed-source", status=WorkNodeStatus.FAILED)
    review = _node("review")
    summary = _node("summary")
    _seed(
        sqlite_engine,
        (review_source, failed_source, review, summary),
        (
            WorkEdge(review_source.id, review.id, WorkEdgeKind.REVIEWS),
            WorkEdge(review_source.id, summary.id, WorkEdgeKind.SUMMARIZES),
            WorkEdge(failed_source.id, summary.id, WorkEdgeKind.SUMMARIZES),
        ),
    )
    coordinator = RecordingCoordinator()

    _engine(sqlite_engine, coordinator).reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[2].input_references == (ArtifactReferenceId("artifact-review"),)
    assert stored.nodes[3].input_references == (
        ArtifactReferenceId("artifact-review"),
        WorkNodeId("failed-source"),
    )
    assert coordinator.enqueued == [WorkNodeId("review"), WorkNodeId("summary")]


def test_failure_retries_with_new_attempt_and_preserves_prior_link(
    sqlite_engine: Engine,
) -> None:
    node = _node("retry", status=WorkNodeStatus.RUNNING, max_attempts=2, attempt_count=1)
    attempt = AttemptId("work-1:graph-1:retry:attempt-1")
    node = replace(node, active_attempt_id=attempt)
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("work-1:graph-1:retry:link-1"),
        attempt_id=attempt,
        node_id=node.id,
        command_id="work-1:graph-1:retry:attempt-1",
        dsh_session_id="session-retry",
    ).mark_running()
    _seed(sqlite_engine, (node,), links=(link,))
    coordinator = RecordingCoordinator()
    engine = _engine(sqlite_engine, coordinator)

    engine.record_failure(node.id, attempt, "gateway_error")

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    by_attempt = {item.attempt_id: item for item in stored.execution_links}
    assert by_attempt[attempt].status is ExecutionStatus.FAILED
    assert (
        by_attempt[AttemptId("work-1:graph-1:retry:attempt-2")].status
        is ExecutionStatus.DISPATCH_PENDING
    )
    assert stored.nodes[0].attempt_count == 2
    assert (
        by_attempt[AttemptId("work-1:graph-1:retry:attempt-2")].command_id
        == "work-1:graph-1:retry:attempt-2"
    )


def test_policy_is_reevaluated_before_attempt_creation(sqlite_engine: Engine) -> None:
    _seed(sqlite_engine, (_node("governed", required_actions=("workspace.read",)),))
    coordinator = RecordingCoordinator()

    _engine(sqlite_engine, coordinator).reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[0].failure_code == "workspace_not_granted"
    assert stored.execution_links == ()
    assert coordinator.enqueued == []


def test_policy_denial_in_any_required_action_precedes_approval(
    sqlite_engine: Engine,
) -> None:
    node = _node(
        "mixed-policy",
        required_actions=("workspace.read", "workspace.write"),
    )
    _seed(sqlite_engine, (node,), approval_action="workspace.read")
    coordinator = RecordingCoordinator()

    _engine(sqlite_engine, coordinator).reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert stored is not None
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[0].failure_code == "workspace_not_granted"
    assert stored.execution_links == ()
    assert approvals == ()
    assert coordinator.enqueued == []


def test_policy_approval_waits_with_a_durable_attempt_then_resumes(
    sqlite_engine: Engine,
) -> None:
    action = "workspace.read"
    node = _node("approval", required_actions=(action,))
    _seed(sqlite_engine, (node,), approval_action=action)
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)

    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        waiting = uow.works.get(WorkId("work-1"))
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert waiting is not None
    assert waiting.nodes[0].status is WorkNodeStatus.WAITING_APPROVAL
    assert len(waiting.execution_links) == 1
    assert coordinator.enqueued == []
    assert len(approvals) == 1

    service = GovernanceService(
        _factory(sqlite_engine)(),
        PolicyEngine(),
        coordinator,
    )
    approved = service.approve(approvals[0].id, decided_by="operator")
    service.resume_approved(approved.id)

    assert coordinator.enqueued == [node.id]


def test_every_approval_required_action_is_decided_before_dispatch(
    sqlite_engine: Engine,
) -> None:
    actions = ("conversation.respond", "workspace.read")
    node = _node("multi-approval", required_actions=actions)
    _seed(sqlite_engine, (node,), approval_actions=actions)
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)

    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert tuple(item.action for item in approvals) == actions
    service = GovernanceService(_factory(sqlite_engine)(), PolicyEngine(), coordinator)
    first = service.approve(approvals[0].id, decided_by="operator")
    result = service.resume_approved(first.id)
    assert result.kind is DecisionKind.REQUIRE_APPROVAL
    assert coordinator.enqueued == []
    with _factory(sqlite_engine)() as uow:
        waiting = uow.works.get(WorkId("work-1"))
    assert waiting is not None
    assert waiting.nodes[0].status is WorkNodeStatus.WAITING_APPROVAL

    second = service.approve(approvals[1].id, decided_by="operator")
    result = service.resume_approved(second.id)

    assert result.kind is DecisionKind.ALLOW
    assert coordinator.enqueued == [node.id]


def test_rejecting_one_required_action_cancels_the_other_pending_approvals(
    sqlite_engine: Engine,
) -> None:
    actions = ("conversation.respond", "workspace.read")
    node = _node("multi-reject", required_actions=actions)
    _seed(sqlite_engine, (node,), approval_actions=actions)
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)
    engine.reconcile(WorkId("work-1"))
    with _factory(sqlite_engine)() as uow:
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))

    GovernanceService(
        _factory(sqlite_engine)(),
        PolicyEngine(),
        coordinator,
        terminal_observer=engine,
    ).reject(approvals[0].id, decided_by="operator")

    with _factory(sqlite_engine)() as uow:
        decided = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert [item.status.value for item in decided] == ["rejected", "cancelled"]


def test_approval_attempts_reserve_the_same_global_capacity_as_allowed_nodes(
    sqlite_engine: Engine,
) -> None:
    action = "workspace.read"
    nodes = tuple(
        _node(f"approval-{number}", required_actions=(action,))
        for number in range(6)
    )
    _seed(sqlite_engine, nodes, approval_action=action)
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(
        _factory(sqlite_engine), coordinator, runtime_concurrency=4
    )

    engine.reconcile(WorkId("work-1"))
    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert stored is not None
    assert len(stored.execution_links) == 4
    assert len(approvals) == 4
    assert [node.status for node in stored.nodes] == [
        *([WorkNodeStatus.WAITING_APPROVAL] * 4),
        WorkNodeStatus.DRAFT,
        WorkNodeStatus.DRAFT,
    ]
    assert coordinator.enqueued == []

    service = GovernanceService(
        _factory(sqlite_engine)(), PolicyEngine(), coordinator
    )
    approved = service.approve(approvals[0].id, decided_by="operator")
    service.resume_approved(approved.id)
    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        after_resume = uow.works.get(WorkId("work-1"))
    assert after_resume is not None
    assert len(after_resume.execution_links) == 4
    assert coordinator.enqueued == [approvals[0].node_id]


def test_rejected_approval_projects_branch_and_dispatches_partial_summary(
    sqlite_engine: Engine,
) -> None:
    action = "workspace.read"
    completed = replace(
        _node("completed", status=WorkNodeStatus.COMPLETED),
        output_references=(ArtifactReferenceId("completed-output"),),
    )
    rejected = _node("rejected", required_actions=(action,))
    summary = _node("summary")
    _seed(
        sqlite_engine,
        (completed, rejected, summary),
        (
            WorkEdge(completed.id, summary.id, WorkEdgeKind.SUMMARIZES),
            WorkEdge(rejected.id, summary.id, WorkEdgeKind.SUMMARIZES),
        ),
        approval_action=action,
    )
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)
    engine.reconcile(WorkId("work-1"))
    with _factory(sqlite_engine)() as uow:
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
    assert len(approvals) == 1
    service = GovernanceService(
        _factory(sqlite_engine)(),
        PolicyEngine(),
        coordinator,
        terminal_observer=engine,
    )

    service.reject(approvals[0].id, decided_by="operator")

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[0].status is WorkNodeStatus.COMPLETED
    assert stored.nodes[1].status is WorkNodeStatus.FAILED
    assert stored.nodes[1].failure_code == "approval_rejected"
    assert stored.nodes[2].status is WorkNodeStatus.READY
    assert stored.work.status is WorkStatus.QUEUED
    rejected_links = tuple(
        link for link in stored.execution_links if link.node_id == rejected.id
    )
    assert len(rejected_links) == 1
    assert rejected_links[0].status is ExecutionStatus.BLOCKED
    assert coordinator.enqueued == [summary.id]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_approval_decision_targets_current_retry_link_and_preserves_history(
    sqlite_engine: Engine, decision: str
) -> None:
    action = "workspace.read"
    node = _node("approval-retry", required_actions=(action,), max_attempts=2)
    _seed(sqlite_engine, (node,), approval_action=action)
    coordinator = RecordingCoordinator()
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)
    engine.reconcile(WorkId("work-1"))
    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
        approvals = uow.approvals.list_for_workspace(WorkspaceId("ws-1"))
        assert stored is not None
        first = stored.execution_links[0]
        historical = replace(
            first,
            status=ExecutionStatus.FAILED,
            finished_at=datetime.now(UTC),
            diagnostic_code="gateway_error",
        )
        retry_attempt = AttemptId("approval-retry-attempt-2")
        retry = ExecutionLink.dispatch(
            execution_link_id=ExecutionLinkId("approval-retry-link-2"),
            attempt_id=retry_attempt,
            node_id=node.id,
            command_id="approval-retry-command-2",
            dsh_session_id=first.dsh_session_id,
        )
        retried_node = replace(
            stored.nodes[0], attempt_count=2, version=stored.nodes[0].version + 1
        )
        uow.works.update(
            replace(
                stored,
                nodes=(retried_node,),
                execution_links=(historical, retry),
            )
        )
        uow.commit()
    service = GovernanceService(
        _factory(sqlite_engine)(), PolicyEngine(), coordinator
    )

    if decision == "approve":
        approved = service.approve(approvals[0].id, decided_by="operator")
        service.resume_approved(approved.id)
    else:
        service.reject(approvals[0].id, decided_by="operator")

    with _factory(sqlite_engine)() as uow:
        decided = uow.works.get(WorkId("work-1"))
    assert decided is not None
    by_id = {link.id: link for link in decided.execution_links}
    assert by_id[first.id] == historical
    assert by_id[retry.id].status is (
        ExecutionStatus.DISPATCH_PENDING
        if decision == "approve"
        else ExecutionStatus.BLOCKED
    )


def test_cancel_is_delegated_to_runtime_coordinator(sqlite_engine: Engine) -> None:
    _seed(sqlite_engine, (_node("node"),))
    coordinator = RecordingCoordinator()

    _engine(sqlite_engine, coordinator).request_cancel(WorkNodeId("node"))

    assert coordinator.cancelled == [WorkNodeId("node")]


def test_runtime_terminal_callback_dispatches_newly_ready_nodes(
    sqlite_engine: Engine,
) -> None:
    first, second = _node("first"), _node("second")
    _seed(
        sqlite_engine,
        (first, second),
        (WorkEdge(first.id, second.id, WorkEdgeKind.DEPENDS_ON),),
    )
    proxy = ObserverProxy()
    gateway = CompletingGateway()
    coordinator = InlineRuntimeCoordinator(
        _factory(sqlite_engine),
        gateway,
        terminal_observer=proxy,
    )
    engine = DurableGraphEngine(
        _factory(sqlite_engine), coordinator, runtime_concurrency=1
    )
    proxy.target = engine

    engine.reconcile(WorkId("work-1"))

    assert gateway.node_ids == [WorkNodeId("first"), WorkNodeId("second")]
    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert [node.status for node in stored.nodes] == [
        WorkNodeStatus.COMPLETED,
        WorkNodeStatus.COMPLETED,
    ]
    coordinator.shutdown()


def test_terminal_callback_projects_completed_summary_sink_over_failed_upstream(
    sqlite_engine: Engine,
) -> None:
    failed = _node("failed", status=WorkNodeStatus.FAILED)
    completed = replace(
        _node("completed", status=WorkNodeStatus.COMPLETED),
        output_references=(ArtifactReferenceId("completed-output"),),
    )
    summary = _node("summary", status=WorkNodeStatus.READY)
    summary_attempt = AttemptId("summary-attempt")
    summary = replace(summary, attempt_count=1)
    summary_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("summary-link"),
        attempt_id=summary_attempt,
        node_id=summary.id,
        command_id="summary-command",
        dsh_session_id="summary-session",
    )
    _seed(
        sqlite_engine,
        (failed, completed, summary),
        (
            WorkEdge(failed.id, summary.id, WorkEdgeKind.SUMMARIZES),
            WorkEdge(completed.id, summary.id, WorkEdgeKind.SUMMARIZES),
        ),
        links=(summary_link,),
        work_status=WorkStatus.QUEUED,
    )
    proxy = ObserverProxy()
    coordinator = RuntimeCoordinator(
        _factory(sqlite_engine), CompletingGateway(), terminal_observer=proxy
    )
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)
    proxy.target = engine

    coordinator.dispatch(summary.id)

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.work.status is WorkStatus.COMPLETED
    coordinator.shutdown()


def test_confirmed_active_cancel_projects_siblings_and_reconciles_summary(
    sqlite_engine: Engine,
) -> None:
    first = _node("first", status=WorkNodeStatus.RUNNING, attempt_count=1)
    second = _node("second", status=WorkNodeStatus.RUNNING, attempt_count=1)
    summary = _node("summary")
    first_attempt = AttemptId("first-attempt")
    second_attempt = AttemptId("second-attempt")
    first = replace(first, active_attempt_id=first_attempt)
    second = replace(second, active_attempt_id=second_attempt)
    first_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("first-link"),
        attempt_id=first_attempt,
        node_id=first.id,
        command_id="first-command",
        dsh_session_id="first-session",
    ).mark_running()
    second_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("second-link"),
        attempt_id=second_attempt,
        node_id=second.id,
        command_id="second-command",
        dsh_session_id="second-session",
    ).mark_running()
    _seed(
        sqlite_engine,
        (first, second, summary),
        (
            WorkEdge(first.id, summary.id, WorkEdgeKind.SUMMARIZES),
            WorkEdge(second.id, summary.id, WorkEdgeKind.SUMMARIZES),
        ),
        links=(first_link, second_link),
        work_status=WorkStatus.RUNNING,
    )
    proxy = ObserverProxy()
    gateway = CompletingGateway()
    coordinator = InlineRuntimeCoordinator(
        _factory(sqlite_engine), gateway, terminal_observer=proxy
    )
    engine = DurableGraphEngine(_factory(sqlite_engine), coordinator)
    proxy.target = engine

    coordinator.request_cancel(first.id)

    with _factory(sqlite_engine)() as uow:
        after_cancel = uow.works.get(WorkId("work-1"))
    assert after_cancel is not None
    assert after_cancel.work.status is WorkStatus.RUNNING
    assert after_cancel.nodes[0].status is WorkNodeStatus.CANCELLED
    assert after_cancel.nodes[1].status is WorkNodeStatus.RUNNING
    assert proxy.work_ids == [WorkId("work-1")]
    engine.record_completion(
        second.id,
        second_attempt,
        ArtifactReferenceId("second-output"),
    )

    assert gateway.node_ids == [WorkNodeId("summary")]
    with _factory(sqlite_engine)() as uow:
        terminal = uow.works.get(WorkId("work-1"))
    assert terminal is not None
    assert terminal.work.status is WorkStatus.COMPLETED
    coordinator.shutdown()


def test_runtime_process_lost_requires_explicit_reconcile_for_new_attempt(
    sqlite_engine: Engine,
) -> None:
    node = _node("restart", status=WorkNodeStatus.RUNNING, max_attempts=2, attempt_count=1)
    attempt = AttemptId("work-1:graph-1:restart:attempt-1")
    node = replace(node, active_attempt_id=attempt)
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("restart-link-1"),
        attempt_id=attempt,
        node_id=node.id,
        command_id=str(attempt),
        dsh_session_id="session-restart",
    ).mark_running()
    blocked_node = node.block(attempt, "runtime_process_lost")
    blocked_link = link.block(attempt, "runtime_process_lost")
    _seed(sqlite_engine, (blocked_node,), links=(blocked_link,))
    coordinator = RecordingCoordinator()
    engine = _engine(sqlite_engine, coordinator)

    assert coordinator.enqueued == []
    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[0].attempt_count == 2
    assert len(stored.execution_links) == 2
    assert coordinator.enqueued == [WorkNodeId("restart")]


def test_waiting_delegation_parent_is_not_retried_before_explicit_resume(
    sqlite_engine: Engine,
) -> None:
    parent_attempt = AttemptId("parent-attempt")
    child_attempt = AttemptId("child-attempt")
    parent = replace(
        _node(
            "parent",
            status=WorkNodeStatus.BLOCKED,
            max_attempts=2,
            attempt_count=1,
        ),
        active_attempt_id=parent_attempt,
        failure_code="waiting_delegation",
    )
    child = replace(
        _node("child", status=WorkNodeStatus.RUNNING, attempt_count=1),
        active_attempt_id=child_attempt,
    )
    parent_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("parent-link"),
        attempt_id=parent_attempt,
        node_id=parent.id,
        command_id="parent-command",
        dsh_session_id="parent-session",
    ).mark_running().block(parent_attempt, "waiting_delegation")
    child_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("child-link"),
        attempt_id=child_attempt,
        node_id=child.id,
        command_id="child-command",
        dsh_session_id="child-session",
    ).mark_running()
    _seed(
        sqlite_engine,
        (parent, child),
        (WorkEdge(parent.id, child.id, WorkEdgeKind.DELEGATES_TO),),
        links=(parent_link, child_link),
        work_status=WorkStatus.RUNNING,
    )
    with _factory(sqlite_engine)() as uow:
        uow.delegations.add(
            Delegation(
                id=DelegationId("delegation-1"),
                workspace_id=WorkspaceId("ws-1"),
                work_id=WorkId("work-1"),
                source_node_id=parent.id,
                target_node_id=child.id,
                proposer_employee_id=parent.assigned_employee_id,
                target_employee_id=child.assigned_employee_id,
                graph_revision_id=WorkGraphRevisionId("graph-1"),
                status="accepted",
                created_at=datetime.now(UTC),
            )
        )
        uow.commit()
    coordinator = RecordingCoordinator()
    engine = _engine(sqlite_engine, coordinator)

    engine.reconcile(WorkId("work-1"))

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[0].failure_code == "waiting_delegation"
    assert stored.nodes[0].attempt_count == 1
    assert len(stored.execution_links) == 2
    assert coordinator.enqueued == []


def test_pending_node_can_be_cancelled_while_another_graph_node_is_running(
    sqlite_engine: Engine,
) -> None:
    running = _node("running", status=WorkNodeStatus.RUNNING)
    pending = _node("pending", status=WorkNodeStatus.READY)
    running_attempt = AttemptId("running-attempt")
    running = replace(running, active_attempt_id=running_attempt)
    running_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("running-link"),
        attempt_id=running_attempt,
        node_id=running.id,
        command_id="running-command",
        dsh_session_id="running-session",
    ).mark_running()
    pending_link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("pending-link"),
        attempt_id=AttemptId("pending-attempt"),
        node_id=pending.id,
        command_id="pending-command",
        dsh_session_id="pending-session",
    )
    _seed(
        sqlite_engine,
        (running, pending),
        links=(running_link, pending_link),
        work_status=WorkStatus.RUNNING,
    )
    coordinator = RuntimeCoordinator(_factory(sqlite_engine), CompletingGateway())

    coordinator.request_cancel(pending.id)

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
    assert stored is not None
    assert stored.work.status is WorkStatus.RUNNING
    assert stored.nodes[1].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[1].failure_code == "cancel_unconfirmed"
    coordinator.shutdown()


def test_retryable_runtime_failure_does_not_record_work_as_terminal(
    sqlite_engine: Engine,
) -> None:
    node = _node(
        "retry-event",
        status=WorkNodeStatus.READY,
        max_attempts=2,
        attempt_count=1,
    )
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("retry-event-link"),
        attempt_id=AttemptId("retry-event-attempt"),
        node_id=node.id,
        command_id="retry-event-command",
        dsh_session_id="retry-event-session",
    )
    _seed(sqlite_engine, (node,), links=(link,))
    coordinator = RuntimeCoordinator(_factory(sqlite_engine), FailingGateway())

    coordinator.dispatch(node.id)

    with _factory(sqlite_engine)() as uow:
        stored = uow.works.get(WorkId("work-1"))
        events = uow.company_events.list_for_work(WorkId("work-1"))
    assert stored is not None
    assert stored.work.status is WorkStatus.BLOCKED
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert [event.event_type for event in events] == ["node.attempt_failed"]
    coordinator.shutdown()


def test_production_assembly_exposes_composed_graph_engine(tmp_path: Path) -> None:
    assembly = create_production_assembly(Settings(data_root=tmp_path))
    try:
        assert isinstance(assembly.orchestration_engine, DurableGraphEngine)
    finally:
        assembly.dispose()
