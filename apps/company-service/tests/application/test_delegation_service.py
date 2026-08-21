from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast

import pytest
from dsh_company.application.delegation_service import (
    DelegationCommand,
    DelegationDenied,
    DelegationService,
)
from dsh_company.application.ports import GovernanceUnitOfWork, WorkAggregate
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.application.runtime_governance import RuntimeGovernanceHandler
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.delegation import Delegation, DelegationProposal
from dsh_company.domain.employee import (
    Employee,
    EmployeeAgentBinding,
    EmployeeRevision,
    EmployeeStatus,
)
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CapabilityGrantId,
    DelegationId,
    EmployeeId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.policy import PolicyEngine
from dsh_company.domain.work import (
    ArtifactReference,
    CompanyEvent,
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkNodeStatus,
    WorkStatus,
)
from dsh_company.domain.workspace import Workspace
from dsh_company.dsh_gateway.contracts import GatewayResult, GatewaySubmission
from dsh_company.dsh_gateway.control_requests import (
    ApprovalControlRequest,
    ControlRequest,
    DelegationControlRequest,
)
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _grant(
    action: str,
    *,
    resources: tuple[str, ...] = ("repo-a",),
) -> CapabilityGrant:
    levels = {
        "work.delegate": CapabilityLevel.L1,
        "workspace.read": CapabilityLevel.L1,
    }
    return CapabilityGrant(
        id=CapabilityGrantId(f"grant-{action}"),
        employee_revision_id=None,
        action=action,
        level=levels[action],
        resource_kind="repository",
        resource_values=resources,
        requires_approval=False,
    )


@dataclass(slots=True)
class FakeEmployeeRecord:
    employee: Employee
    revision: EmployeeRevision
    binding: EmployeeAgentBinding
    grants: tuple[CapabilityGrant, ...]


class EmployeeRepository:
    def __init__(self, records: tuple[FakeEmployeeRecord, ...]) -> None:
        self.records = records

    def get(self, employee_id: EmployeeId) -> FakeEmployeeRecord | None:
        return next(
            (
                record
                for record in self.records
                if record.employee.id == employee_id
            ),
            None,
        )

    def get_revision(
        self, employee_id: EmployeeId, revision_id: object
    ) -> FakeEmployeeRecord | None:
        record = self.get(employee_id)
        if record is None or record.revision.id != revision_id:
            return None
        return record


class WorkRepository:
    def __init__(self, aggregate: WorkAggregate) -> None:
        self.aggregate = aggregate
        self.revisions: list[tuple[object, tuple[object, ...]]] = []

    def get(self, work_id: WorkId) -> WorkAggregate | None:
        return self.aggregate if self.aggregate.work.id == work_id else None

    def get_for_node(self, node_id: WorkNodeId) -> WorkAggregate | None:
        return (
            self.aggregate
            if any(node.id == node_id for node in self.aggregate.nodes)
            else None
        )

    def add_revision(self, graph: object, nodes: tuple[object, ...]) -> None:
        self.revisions.append((graph, nodes))

    def update(self, aggregate: WorkAggregate) -> None:
        self.aggregate = aggregate


class GrantRepository:
    def __init__(self, values: dict[object, tuple[CapabilityGrant, ...]]) -> None:
        self.values = values

    def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[CapabilityGrant, ...]:
        return self.values.get(workspace_id, ())

    def list_for_node(self, node_id: WorkNodeId) -> tuple[CapabilityGrant, ...]:
        return self.values.get(node_id, ())

    def replace(self, node_id: WorkNodeId, grants: tuple[CapabilityGrant, ...]) -> None:
        self.values[node_id] = grants


class DelegationRepository:
    def __init__(self) -> None:
        self.items: dict[DelegationId, Delegation] = {}

    def add(self, delegation: Delegation) -> None:
        self.items[delegation.id] = delegation

    def get(self, delegation_id: DelegationId) -> Delegation | None:
        return self.items.get(delegation_id)

    def update(self, delegation: Delegation) -> None:
        self.items[delegation.id] = delegation

    def get_accepted_for_target(self, node_id: WorkNodeId) -> Delegation | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.target_node_id == node_id and item.status == "accepted"
            ),
            None,
        )


class EventRepository:
    def __init__(self) -> None:
        self.items: list[CompanyEvent] = []

    def append(self, event: CompanyEvent) -> None:
        self.items.append(event)


class WorkspaceRepository:
    def __init__(self, workspaces: tuple[Workspace, ...]) -> None:
        self.workspaces = workspaces

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return next((item for item in self.workspaces if item.id == workspace_id), None)


class FakeUow:
    def __init__(self) -> None:
        workspace = Workspace.create(WorkspaceId("ws-1"), "Company")
        other_workspace = Workspace.create(WorkspaceId("ws-2"), "Other")
        records = tuple(
            self._record(employee_id, employee_workspace)
            for employee_id, employee_workspace in (
                ("emp-a", workspace.id),
                ("emp-b", workspace.id),
                ("emp-other", other_workspace.id),
            )
        )
        proposer = records[0].employee
        proposer_revision = records[0].revision
        proposer_binding = records[0].binding
        work, graph, node = Work.create_direct(
            work_id=WorkId("work-1"),
            graph_id=WorkGraphRevisionId("graph-1"),
            node_id=WorkNodeId("node-parent"),
            workspace_id=workspace.id,
            employee_id=proposer.id,
            employee_revision_id=proposer_revision.id,
            objective="Prepare release",
            acceptance_criteria=("Accurate",),
            command_id="command-1",
        )
        attempt_id = AttemptId("attempt-parent-1")
        node = node.start(attempt_id)
        link = ExecutionLink.dispatch(
            execution_link_id=ExecutionLinkId("link-parent-1"),
            attempt_id=attempt_id,
            node_id=node.id,
            command_id="command-1",
            dsh_session_id=proposer_binding.dsh_session_id,
        ).mark_running()
        aggregate = WorkAggregate(
            replace(work, status=WorkStatus.RUNNING), graph, (node,), (link,), ()
        )
        grants = (_grant("work.delegate"), _grant("workspace.read"))
        for record in records:
            record.grants = grants
        self.workspaces = WorkspaceRepository((workspace, other_workspace))
        self.employees = EmployeeRepository(records)
        self.works = WorkRepository(aggregate)
        self.workspace_grants = GrantRepository({workspace.id: grants})
        self.node_grants = GrantRepository({node.id: grants})
        self.delegations = DelegationRepository()
        self.company_events = EventRepository()
        self.commits = 0

    @staticmethod
    def _record(employee_id: str, workspace_id: WorkspaceId) -> FakeEmployeeRecord:
        employee, revision, binding = Employee.create(
            employee_id=EmployeeId(employee_id),
            workspace_id=workspace_id,
            display_name=employee_id,
            responsibility="Research",
            runtime_profile="workspace_read",
            model="deepseek-chat",
        )
        return FakeEmployeeRecord(employee, revision, binding, ())

    def __enter__(self) -> "FakeUow":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def commit(self) -> None:
        self.commits += 1


class RecordingDispatch:
    def __init__(self) -> None:
        self.calls: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.calls.append(node_id)


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


class CompletingGateway:
    def __init__(self) -> None:
        self.submissions: list[GatewaySubmission] = []

    def submit(self, submission: GatewaySubmission, *, on_event: object) -> GatewayResult:
        del on_event
        self.submissions.append(submission)
        return GatewayResult(
            finish_reason="completed",
            reference_uri=f"dsh-session://{submission.employee.dsh_session_id}/result",
            event_count=0,
        )

    def shutdown(self) -> None:
        pass


class ControlGateway(CompletingGateway):
    def __init__(self, control_request: ControlRequest | None) -> None:
        super().__init__()
        self.control_request = control_request

    def submit(self, submission: GatewaySubmission, *, on_event: object) -> GatewayResult:
        del on_event
        self.submissions.append(submission)
        return GatewayResult(
            finish_reason="completed",
            reference_uri=(
                None
                if self.control_request is not None
                else f"dsh-session://{submission.employee.dsh_session_id}/result"
            ),
            event_count=0,
            control_request=self.control_request,
        )


class RecordingEnqueueCoordinator(RuntimeCoordinator):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.enqueued: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)


def _prepare_pending(uow: FakeUow) -> None:
    aggregate = uow.works.aggregate
    node = aggregate.nodes[0]
    link = ExecutionLink.dispatch(
        execution_link_id=aggregate.execution_links[0].id,
        attempt_id=aggregate.execution_links[0].attempt_id,
        node_id=node.id,
        command_id=aggregate.execution_links[0].command_id,
        dsh_session_id=aggregate.execution_links[0].dsh_session_id,
    )
    uow.works.aggregate = replace(
        aggregate,
        work=replace(aggregate.work, status=WorkStatus.QUEUED),
        nodes=(
            replace(
                node,
                status=WorkNodeStatus.READY,
                active_attempt_id=None,
                version=1,
            ),
        ),
        execution_links=(link,),
    )


def _runtime_handler(uow: FakeUow) -> RuntimeGovernanceHandler:
    return RuntimeGovernanceHandler(
        lambda: cast(GovernanceUnitOfWork, uow),
        PolicyEngine(),
        ids=SequentialIds(),
    )


def _command(
    *,
    target: str = "emp-b",
    resources: tuple[str, ...] = ("repo-a",),
    required_actions: tuple[str, ...] = ("workspace.read",),
) -> DelegationCommand:
    return DelegationCommand(
        source_node_id=WorkNodeId("node-parent"),
        proposal=DelegationProposal(
            proposer_employee_id=EmployeeId("emp-a"),
            target_employee_id=EmployeeId(target),
            objective="Verify release facts",
            acceptance_criteria=("Cite sources",),
            required_actions=required_actions,
            resource_values=resources,
        ),
    )


def _service(uow: FakeUow, dispatch: RecordingDispatch) -> DelegationService:
    return DelegationService(
        cast(GovernanceUnitOfWork, uow),
        PolicyEngine(),
        dispatch,
        ids=SequentialIds(),
    )


def test_delegation_accepts_eligible_target_and_persists_before_dispatch() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()

    result = _service(uow, dispatch).propose(_command())

    assert result.delegation.status == "accepted"
    assert result.target_node.status is WorkNodeStatus.READY
    assert result.parent_node.status is WorkNodeStatus.BLOCKED
    assert result.parent_node.failure_code == "waiting_delegation"
    assert uow.commits == 1
    assert dispatch.calls == [result.target_node.id]
    assert uow.works.aggregate.graph.revision_number == 2
    assert tuple(node.id for node in uow.works.aggregate.nodes) == (
        WorkNodeId("node-parent"),
        result.target_node.id,
    )
    assert tuple(link.node_id for link in uow.works.aggregate.execution_links) == (
        WorkNodeId("node-parent"),
        result.target_node.id,
    )


def test_delegation_cannot_expand_resource_scope_and_records_safe_rejection() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    original = uow.works.aggregate

    with pytest.raises(DelegationDenied, match="resource_scope_empty"):
        _service(uow, dispatch).propose(_command(resources=("repo-outside",)))

    assert uow.works.aggregate.graph == original.graph
    assert len(uow.works.aggregate.nodes) == 1
    assert uow.works.aggregate.nodes[0].status is WorkNodeStatus.BLOCKED
    assert uow.works.aggregate.nodes[0].failure_code == "delegation_rejected"
    assert uow.works.revisions == []
    assert dispatch.calls == []
    assert uow.commits == 1
    rejected = tuple(uow.delegations.items.values())
    assert len(rejected) == 1
    assert rejected[0].status == "rejected"
    assert rejected[0].target_node_id is None
    assert len(uow.company_events.items) == 1
    assert "repo-outside" not in repr(uow.company_events.items)
    assert "Verify release facts" not in repr(uow.company_events.items)


@pytest.mark.parametrize(
    ("target", "status", "reason"),
    [
        ("emp-other", EmployeeStatus.ACTIVE, "target_workspace_mismatch"),
        ("emp-b", EmployeeStatus.PAUSED, "target_not_active"),
    ],
)
def test_delegation_requires_same_workspace_active_target(
    target: str, status: EmployeeStatus, reason: str
) -> None:
    uow = FakeUow()
    record = uow.employees.get(EmployeeId(target))
    assert record is not None
    record.employee = replace(record.employee, status=status)

    with pytest.raises(DelegationDenied, match=reason):
        _service(uow, RecordingDispatch()).propose(_command(target=target))


def test_delegation_validates_source_owner_and_target_required_action() -> None:
    uow = FakeUow()
    target = uow.employees.get(EmployeeId("emp-b"))
    assert target is not None
    target.grants = tuple(
        grant for grant in target.grants if grant.action != "workspace.read"
    )

    with pytest.raises(DelegationDenied, match="employee_not_granted"):
        _service(uow, RecordingDispatch()).propose(_command())

    mismatched = replace(
        _command(),
        proposal=replace(
            _command().proposal, proposer_employee_id=EmployeeId("emp-b")
        ),
    )
    with pytest.raises(DelegationDenied, match="proposer_not_source_owner"):
        _service(FakeUow(), RecordingDispatch()).propose(mismatched)


def test_completed_child_resumes_parent_with_reference_and_same_session_attempt() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch)
    accepted = service.propose(_command())
    aggregate = uow.works.aggregate
    child_link = next(
        link for link in aggregate.execution_links if link.node_id == accepted.target_node.id
    )
    child_running_link = child_link.mark_running()
    child_running = accepted.target_node.start(child_link.attempt_id)
    artifact_id = ArtifactReferenceId("artifact-child")
    artifact = ArtifactReference(
        id=artifact_id,
        workspace_id=aggregate.work.workspace_id,
        kind="dsh_session_result",
        uri="dsh://result/child",
        source_session_id=child_link.dsh_session_id,
        source_attempt_id=child_link.attempt_id,
        created_at=datetime.now(UTC),
    )
    child_completed = child_running.complete(child_link.attempt_id, artifact_id)
    uow.works.aggregate = replace(
        aggregate,
        nodes=(accepted.parent_node, child_completed),
        execution_links=(
            aggregate.execution_links[0],
            child_running_link.complete(child_link.attempt_id, artifact_id),
        ),
        artifacts=(artifact,),
    )

    resumed = service.child_completed(accepted.delegation.id, artifact_id)

    assert resumed.parent_node.status is WorkNodeStatus.READY
    assert resumed.input_references == (artifact_id,)
    assert resumed.parent_node.input_references == (artifact_id,)
    stored_delegation = uow.delegations.get(accepted.delegation.id)
    assert stored_delegation is not None
    assert stored_delegation.status == "completed"
    parent_links = tuple(
        link
        for link in uow.works.aggregate.execution_links
        if link.node_id == WorkNodeId("node-parent")
    )
    assert len(parent_links) == 2
    assert parent_links[-1].status is ExecutionStatus.DISPATCH_PENDING
    parent_record = uow.employees.get(EmployeeId("emp-a"))
    assert parent_record is not None
    assert parent_links[-1].dsh_session_id == parent_record.binding.dsh_session_id
    assert tuple(node.id for node in uow.works.aggregate.nodes) == (
        WorkNodeId("node-parent"),
        accepted.target_node.id,
    )
    assert dispatch.calls == [accepted.target_node.id, WorkNodeId("node-parent")]


def test_runtime_coordinator_dispatches_and_completes_exact_child_only() -> None:
    uow = FakeUow()
    accepted = _service(uow, RecordingDispatch()).propose(_command())
    gateway = CompletingGateway()
    coordinator = RuntimeCoordinator(
        lambda: cast(GovernanceUnitOfWork, uow),
        gateway,  # type: ignore[arg-type]
        id_factory=SequentialIds(),
    )

    coordinator.dispatch(accepted.target_node.id)

    assert [submission.attempt_id for submission in gateway.submissions] == [
        next(
            link.attempt_id
            for link in uow.works.aggregate.execution_links
            if link.node_id == accepted.target_node.id
        )
    ]
    parent = next(
        node
        for node in uow.works.aggregate.nodes
        if node.id == WorkNodeId("node-parent")
    )
    child = next(
        node
        for node in uow.works.aggregate.nodes
        if node.id == accepted.target_node.id
    )
    assert parent.status is WorkNodeStatus.BLOCKED
    assert parent.failure_code == "waiting_delegation"
    assert child.status is WorkNodeStatus.COMPLETED
    assert uow.works.aggregate.work.status is WorkStatus.RUNNING


def test_nonexistent_target_persists_truthful_rejection_without_graph_mutation(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    workspace = Workspace.create(WorkspaceId("ws-1"), "Company")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-a"),
        workspace_id=workspace.id,
        display_name="Author",
        responsibility="Write",
        runtime_profile="workspace_read",
        model="deepseek-chat",
    )
    work, graph, node = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-parent"),
        workspace_id=workspace.id,
        employee_id=employee.id,
        employee_revision_id=revision.id,
        objective="Prepare release",
        acceptance_criteria=("Accurate",),
        command_id="command-1",
    )
    attempt_id = AttemptId("attempt-parent")
    node = node.start(attempt_id)
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-parent"),
        attempt_id=attempt_id,
        node_id=node.id,
        command_id=work.command_id,
        dsh_session_id=binding.dsh_session_id,
    ).mark_running()
    grants = (_grant("work.delegate"), _grant("workspace.read"))
    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.workspaces.add(workspace)
        uow.employees.add(employee, revision, binding, grants)
        uow.works.add(
            WorkAggregate(
                replace(work, status=WorkStatus.RUNNING),
                graph,
                (node,),
                (link,),
                (),
            )
        )
        uow.workspace_grants.replace(workspace.id, grants)
        uow.node_grants.replace(node.id, grants)
        uow.commit()
    service = DelegationService(
        SqlAlchemyUnitOfWork(engine),
        PolicyEngine(),
        ids=SequentialIds(),
    )

    with pytest.raises(DelegationDenied, match="target_not_found"):
        service.propose(_command(target="emp-missing"))

    with SqlAlchemyUnitOfWork(engine) as uow:
        stored = uow.works.get(work.id)
        events = uow.company_events.list_for_work(work.id)
        rejected = uow.delegations.get(DelegationId("delegation-1"))
    assert stored is not None
    assert stored.graph == graph
    assert len(stored.nodes) == 1
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert stored.nodes[0].failure_code == "delegation_rejected"
    assert rejected is not None
    assert rejected.target_employee_id == EmployeeId("emp-missing")
    assert rejected.target_node_id is None
    assert [event.event_type for event in events] == ["delegation.rejected"]
    engine.dispose()


def test_runtime_routes_delegation_control_to_authoritative_service() -> None:
    uow = FakeUow()
    _prepare_pending(uow)
    control = DelegationControlRequest(
        kind="delegation",
        target_employee_id="emp-b",
        objective="Verify release facts",
        acceptance_criteria=("Cite sources",),
        required_actions=("workspace.read",),
        resource_values=("repo-a",),
        reason="Independent check",
    )
    gateway = ControlGateway(control)
    coordinator = RecordingEnqueueCoordinator(
        lambda: cast(GovernanceUnitOfWork, uow),
        gateway,  # type: ignore[arg-type]
        governance_handler=_runtime_handler(uow),
        id_factory=SequentialIds(),
    )

    coordinator.dispatch(WorkNodeId("node-parent"))

    aggregate = uow.works.aggregate
    parent, child = aggregate.nodes
    assert parent.status is WorkNodeStatus.BLOCKED
    assert parent.failure_code == "waiting_delegation"
    assert child.status is WorkNodeStatus.READY
    assert coordinator.enqueued == [child.id]
    assert aggregate.artifacts == ()
    assert all(node.failure_code != "gateway_error" for node in aggregate.nodes)


def test_runtime_rejected_delegation_blocks_source_intentionally() -> None:
    uow = FakeUow()
    _prepare_pending(uow)
    original_graph = uow.works.aggregate.graph
    control = DelegationControlRequest(
        kind="delegation",
        target_employee_id="emp-missing",
        objective="Verify release facts",
        acceptance_criteria=("Cite sources",),
        required_actions=("workspace.read",),
        resource_values=("repo-a",),
        reason="Independent check",
    )
    coordinator = RecordingEnqueueCoordinator(
        lambda: cast(GovernanceUnitOfWork, uow),
        ControlGateway(control),  # type: ignore[arg-type]
        governance_handler=_runtime_handler(uow),
        id_factory=SequentialIds(),
    )

    coordinator.dispatch(WorkNodeId("node-parent"))

    aggregate = uow.works.aggregate
    assert aggregate.graph == original_graph
    assert len(aggregate.nodes) == 1
    assert aggregate.nodes[0].status is WorkNodeStatus.BLOCKED
    assert aggregate.nodes[0].failure_code == "delegation_rejected"
    assert tuple(uow.delegations.items.values())[0].status == "rejected"
    assert [event.event_type for event in uow.company_events.items] == [
        "delegation.rejected"
    ]
    assert coordinator.enqueued == []


def test_runtime_child_completion_resumes_parent_with_artifact_id_only() -> None:
    uow = FakeUow()
    accepted = _service(uow, RecordingDispatch()).propose(_command())
    gateway = ControlGateway(None)
    coordinator = RecordingEnqueueCoordinator(
        lambda: cast(GovernanceUnitOfWork, uow),
        gateway,  # type: ignore[arg-type]
        governance_handler=_runtime_handler(uow),
        id_factory=SequentialIds(),
    )

    coordinator.dispatch(accepted.target_node.id)

    aggregate = uow.works.aggregate
    parent = aggregate.nodes[0]
    assert parent.status is WorkNodeStatus.READY
    assert len(parent.input_references) == 1
    assert parent.input_references == tuple(item.id for item in aggregate.artifacts)
    parent_links = tuple(
        link for link in aggregate.execution_links if link.node_id == parent.id
    )
    assert len(parent_links) == 2
    assert parent_links[-1].status is ExecutionStatus.DISPATCH_PENDING
    assert coordinator.enqueued == [parent.id]


def test_runtime_approval_control_is_explicitly_closed() -> None:
    uow = FakeUow()
    _prepare_pending(uow)
    control = ApprovalControlRequest(
        kind="approval",
        action="workspace.read",
        resources=("repo-a",),
        reason="Need approval",
    )
    coordinator = RecordingEnqueueCoordinator(
        lambda: cast(GovernanceUnitOfWork, uow),
        ControlGateway(control),  # type: ignore[arg-type]
        governance_handler=_runtime_handler(uow),
        id_factory=SequentialIds(),
    )

    coordinator.dispatch(WorkNodeId("node-parent"))

    aggregate = uow.works.aggregate
    assert aggregate.nodes[0].status is WorkNodeStatus.BLOCKED
    assert aggregate.nodes[0].failure_code == "approval_control_not_exposed"
    assert aggregate.artifacts == ()
