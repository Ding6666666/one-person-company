from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import pytest
from dsh_company.application.governance_service import (
    GovernanceService,
    GovernedAction,
)
from dsh_company.application.ports import GovernanceUnitOfWork, WorkAggregate
from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import (
    ApprovalId,
    AttemptId,
    CapabilityGrantId,
    EmployeeId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.policy import DecisionKind, PolicyDecision, PolicyEngine
from dsh_company.domain.work import (
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkNodeStatus,
)
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _grant(
    action: str = "workspace.write",
    *,
    requires_approval: bool = True,
    resources: tuple[str, ...] = ("repo-a",),
) -> CapabilityGrant:
    return CapabilityGrant(
        id=CapabilityGrantId(f"grant-{action}"),
        employee_revision_id=None,
        action=action,
        level=CapabilityLevel.L2,
        resource_kind="repository",
        resource_values=resources,
        requires_approval=requires_approval,
    )


class DictRepository:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self, _key: object) -> object:
        return self.value

    def get_for_node(self, _key: object) -> object:
        return self.value

    def get_revision(self, _employee: object, _revision: object) -> object:
        return self.value

    def list_for_workspace(self, _key: object) -> tuple[CapabilityGrant, ...]:
        assert isinstance(self.value, tuple)
        return self.value

    def list_for_node(self, _key: object) -> tuple[CapabilityGrant, ...]:
        assert isinstance(self.value, tuple)
        return self.value

    def update(self, value: object) -> None:
        if isinstance(self.value, WorkAggregate) and isinstance(value, WorkAggregate):
            old_nodes = {node.id: node for node in self.value.nodes}
            for node in value.nodes:
                old = old_nodes.get(node.id)
                if old is not None and node != old and node.version != old.version + 1:
                    raise RuntimeError("concurrent node update")
        self.value = value

    def append(self, value: object) -> None:
        assert isinstance(self.value, list)
        self.value.append(value)


class ApprovalRepository:
    def __init__(self) -> None:
        self.items: dict[ApprovalId, Approval] = {}

    def add(self, approval: Approval) -> None:
        self.items[approval.id] = approval

    def get(self, approval_id: ApprovalId) -> Approval | None:
        return self.items.get(approval_id)

    def decide(self, approval: Approval) -> None:
        current = self.items[approval.id]
        if current.status is not ApprovalStatus.PENDING:
            raise RuntimeError("concurrent approval decision")
        self.items[approval.id] = approval


class FakeUow:
    def __init__(self, *, runtime_profile: str = "workspace_write") -> None:
        workspace_id = WorkspaceId("ws-1")
        employee, revision, binding = Employee.create(
            employee_id=EmployeeId("emp-1"),
            workspace_id=workspace_id,
            display_name="Editor",
            responsibility="Edit",
            runtime_profile=runtime_profile,
            model="deepseek-chat",
        )
        employee_record = type(
            "EmployeeRecord",
            (),
            {
                "employee": employee,
                "revision": revision,
                "binding": binding,
                "grants": (_grant(),),
            },
        )()
        work, graph, node = Work.create_direct(
            work_id=WorkId("work-1"),
            graph_id=WorkGraphRevisionId("graph-1"),
            node_id=WorkNodeId("node-1"),
            workspace_id=workspace_id,
            employee_id=employee.id,
            employee_revision_id=revision.id,
            objective="Edit release notes",
            acceptance_criteria=("Accurate",),
            command_id="command-1",
        )
        link = ExecutionLink.dispatch(
            execution_link_id=ExecutionLinkId("link-1"),
            attempt_id=AttemptId("attempt-1"),
            node_id=node.id,
            command_id="command-1",
            dsh_session_id=binding.dsh_session_id,
        )
        self.works = DictRepository(WorkAggregate(work, graph, (node,), (link,), ()))
        self.employees = DictRepository(employee_record)
        self.workspace_grants = DictRepository((_grant(),))
        self.node_grants = DictRepository((_grant(),))
        self.approvals = ApprovalRepository()
        self.company_events = DictRepository([])
        self.commits = 0

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


def _command() -> GovernedAction:
    return GovernedAction(
        node_id=WorkNodeId("node-1"),
        action="workspace.write",
        resources=("repo-a",),
        reason="Update the release notes",
    )


def _multi_node(uow: FakeUow) -> WorkAggregate:
    aggregate = cast(WorkAggregate, uow.works.value)
    first_node = aggregate.nodes[0]
    second_node = replace(
        first_node,
        id=WorkNodeId("node-2"),
        objective="Review release notes",
        version=1,
    )
    first_link = aggregate.execution_links[0]
    second_link = replace(
        first_link,
        id=ExecutionLinkId("link-2"),
        node_id=second_node.id,
        attempt_id=AttemptId("attempt-2"),
        command_id="command-2",
    )
    multi = replace(
        aggregate,
        graph=replace(
            aggregate.graph,
            node_ids=(first_node.id, second_node.id),
        ),
        nodes=(first_node, second_node),
        execution_links=(first_link, second_link),
    )
    uow.works.value = multi
    return multi


def _second_command() -> GovernedAction:
    return replace(_command(), node_id=WorkNodeId("node-2"))


def _service(
    uow: FakeUow,
    dispatch: RecordingDispatch,
    *,
    deterministic_ids: bool = False,
) -> GovernanceService:
    return GovernanceService(
        cast(GovernanceUnitOfWork, uow),
        PolicyEngine(),
        dispatch,
        **({"ids": lambda prefix: f"{prefix}-1"} if deterministic_ids else {}),
    )


def test_high_level_action_waits_for_approval_before_dispatch() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch, deterministic_ids=True)

    result = service.authorize(_command())

    assert isinstance(result, Approval)
    assert result.status is ApprovalStatus.PENDING
    assert dispatch.calls == []
    aggregate = uow.works.value
    assert isinstance(aggregate, WorkAggregate)
    assert aggregate.nodes[0].status is WorkNodeStatus.WAITING_APPROVAL


def test_runtime_profile_cap_denies_before_dispatch() -> None:
    uow = FakeUow(runtime_profile="workspace_read")
    dispatch = RecordingDispatch()

    result = _service(uow, dispatch).authorize(_command())

    assert isinstance(result, PolicyDecision)
    assert result.kind is DecisionKind.DENY
    assert result.reason == "runtime_not_granted"
    assert dispatch.calls == []
    aggregate = uow.works.value
    assert isinstance(aggregate, WorkAggregate)
    assert aggregate.nodes[0].status is WorkNodeStatus.BLOCKED


@pytest.mark.parametrize(
    ("layer", "reason"),
    [
        ("workspace", "workspace_not_granted"),
        ("employee", "employee_not_granted"),
        ("node", "node_not_granted"),
    ],
)
def test_every_persisted_grant_layer_is_loaded_before_dispatch(
    layer: str, reason: str
) -> None:
    uow = FakeUow()
    if layer == "workspace":
        uow.workspace_grants.value = ()
    elif layer == "employee":
        cast(Any, uow.employees.value).grants = ()
    else:
        uow.node_grants.value = ()
    dispatch = RecordingDispatch()

    result = _service(uow, dispatch).authorize(_command())

    assert isinstance(result, PolicyDecision)
    assert result == PolicyDecision(DecisionKind.DENY, reason)
    assert dispatch.calls == []


def test_allowed_action_dispatches_after_all_four_layers_allow() -> None:
    uow = FakeUow()
    allowed = (_grant(requires_approval=False),)
    uow.workspace_grants.value = allowed
    cast(Any, uow.employees.value).grants = allowed
    uow.node_grants.value = allowed
    dispatch = RecordingDispatch()

    result = _service(uow, dispatch).authorize(_command())

    assert result == PolicyDecision(
        DecisionKind.ALLOW, "granted", frozenset({"repo-a"})
    )
    assert dispatch.calls == [WorkNodeId("node-1")]


def test_approved_action_is_rechecked_before_dispatch() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch, deterministic_ids=True)
    approval = service.authorize(_command())
    assert isinstance(approval, Approval)
    service.approve(approval.id, decided_by="operator")
    record = cast(Any, uow.employees.value)
    record.grants = ()

    result = service.resume_approved(approval.id)

    assert result.kind is DecisionKind.DENY
    assert result.reason == "employee_not_granted"
    assert dispatch.calls == []


def test_approved_action_dispatches_only_after_current_policy_recheck() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch, deterministic_ids=True)
    approval = service.authorize(_command())
    assert isinstance(approval, Approval)

    service.approve(approval.id, decided_by="operator")
    result = service.resume_approved(approval.id)

    assert result.kind is DecisionKind.ALLOW
    assert dispatch.calls == [WorkNodeId("node-1")]
    aggregate = uow.works.value
    assert isinstance(aggregate, WorkAggregate)
    assert aggregate.nodes[0].status is WorkNodeStatus.READY


def test_rejection_fails_waiting_node_and_appends_safe_event() -> None:
    uow = FakeUow()
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch, deterministic_ids=True)
    approval = service.authorize(_command())
    assert isinstance(approval, Approval)

    rejected = service.reject(approval.id, decided_by="operator")

    assert rejected.status is ApprovalStatus.REJECTED
    aggregate = uow.works.value
    assert isinstance(aggregate, WorkAggregate)
    assert aggregate.nodes[0].status is WorkNodeStatus.FAILED
    assert aggregate.nodes[0].failure_code == "approval_rejected"
    assert aggregate.execution_links[0].status is ExecutionStatus.BLOCKED
    assert aggregate.execution_links[0].diagnostic_code == "approval_rejected"
    assert dispatch.calls == []
    assert len(cast(list[object], uow.company_events.value)) == 1
    assert "Update the release notes" not in repr(uow.company_events.value)


def test_approval_decision_is_optimistic() -> None:
    uow = FakeUow()
    service = _service(uow, RecordingDispatch(), deterministic_ids=True)
    approval = service.authorize(_command())
    assert isinstance(approval, Approval)
    service.approve(approval.id, decided_by="operator")

    with pytest.raises(RuntimeError, match="concurrent"):
        uow.approvals.decide(approval.reject(decided_by="other"))


def test_real_uow_rechecks_removed_grant_without_dispatch(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    workspace = Workspace.create(WorkspaceId("ws-1"), "Governed")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"),
        workspace_id=workspace.id,
        display_name="Editor",
        responsibility="Edit",
        runtime_profile="workspace_write",
        model="deepseek-chat",
    )
    work, graph, node = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=workspace.id,
        employee_id=employee.id,
        employee_revision_id=revision.id,
        objective="Edit release notes",
        acceptance_criteria=("Accurate",),
        command_id="command-1",
    )
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-1"),
        attempt_id=AttemptId("attempt-1"),
        node_id=node.id,
        command_id="command-1",
        dsh_session_id=binding.dsh_session_id,
    )
    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.workspaces.add(workspace)
        uow.employees.add(employee, revision, binding, (_grant(),))
        uow.works.add(WorkAggregate(work, graph, (node,), (link,), ()))
        uow.workspace_grants.replace(workspace.id, (_grant(),))
        uow.node_grants.replace(node.id, (_grant(),))
        uow.commit()
    dispatch = RecordingDispatch()
    service = GovernanceService(
        SqlAlchemyUnitOfWork(engine),
        PolicyEngine(),
        dispatch,
        ids=lambda prefix: f"{prefix}-1",
    )
    approval = service.authorize(_command())
    assert isinstance(approval, Approval)
    service.approve(approval.id, decided_by="operator")
    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.workspace_grants.replace(workspace.id, ())
        uow.commit()

    result = service.resume_approved(approval.id)

    assert result == PolicyDecision(DecisionKind.DENY, "workspace_not_granted")
    assert dispatch.calls == []
    with SqlAlchemyUnitOfWork(engine) as uow:
        stored = uow.works.get(work.id)
    engine.dispose()
    assert stored is not None
    assert stored.nodes[0].status is WorkNodeStatus.BLOCKED
    assert stored.execution_links[0].status is ExecutionStatus.BLOCKED


def test_multi_node_deny_changes_only_target_node_and_link() -> None:
    uow = FakeUow()
    original = _multi_node(uow)
    uow.workspace_grants.value = ()

    result = _service(uow, RecordingDispatch()).authorize(_second_command())

    assert result == PolicyDecision(DecisionKind.DENY, "workspace_not_granted")
    updated = cast(WorkAggregate, uow.works.value)
    assert tuple(node.id for node in updated.nodes) == (
        WorkNodeId("node-1"),
        WorkNodeId("node-2"),
    )
    assert updated.nodes[0] == original.nodes[0]
    assert updated.nodes[1].status is WorkNodeStatus.BLOCKED
    assert tuple(link.id for link in updated.execution_links) == (
        ExecutionLinkId("link-1"),
        ExecutionLinkId("link-2"),
    )
    assert updated.execution_links[0] == original.execution_links[0]
    assert updated.execution_links[1].status is ExecutionStatus.BLOCKED


def test_multi_node_approval_resume_preserves_non_target_facts_and_order() -> None:
    uow = FakeUow()
    original = _multi_node(uow)
    dispatch = RecordingDispatch()
    service = _service(uow, dispatch, deterministic_ids=True)

    approval = service.authorize(_second_command())
    assert isinstance(approval, Approval)
    waiting = cast(WorkAggregate, uow.works.value)
    assert waiting.nodes[0] == original.nodes[0]
    assert waiting.nodes[1].status is WorkNodeStatus.WAITING_APPROVAL
    assert waiting.execution_links == original.execution_links
    service.approve(approval.id, decided_by="operator")
    result = service.resume_approved(approval.id)

    assert result.kind is DecisionKind.ALLOW
    updated = cast(WorkAggregate, uow.works.value)
    assert updated.nodes[0] == original.nodes[0]
    assert updated.nodes[1].status is WorkNodeStatus.READY
    assert updated.execution_links == original.execution_links
    assert dispatch.calls == [WorkNodeId("node-2")]


def test_multi_node_rejection_changes_only_target_node_and_link() -> None:
    uow = FakeUow()
    original = _multi_node(uow)
    service = _service(uow, RecordingDispatch(), deterministic_ids=True)
    approval = service.authorize(_second_command())
    assert isinstance(approval, Approval)

    service.reject(approval.id, decided_by="operator")

    updated = cast(WorkAggregate, uow.works.value)
    assert updated.nodes[0] == original.nodes[0]
    assert updated.nodes[1].status is WorkNodeStatus.FAILED
    assert updated.execution_links[0] == original.execution_links[0]
    assert updated.execution_links[1].status is ExecutionStatus.BLOCKED
    assert tuple(node.id for node in updated.nodes) == (
        WorkNodeId("node-1"),
        WorkNodeId("node-2"),
    )
    assert tuple(link.id for link in updated.execution_links) == (
        ExecutionLinkId("link-1"),
        ExecutionLinkId("link-2"),
    )


@pytest.mark.parametrize("link_shape", ["missing", "ambiguous"])
def test_governance_closes_when_target_link_is_not_exactly_one(link_shape: str) -> None:
    uow = FakeUow()
    original = _multi_node(uow)
    target_link = original.execution_links[1]
    links = (
        (original.execution_links[0],)
        if link_shape == "missing"
        else (
            *original.execution_links,
            replace(
                target_link,
                id=ExecutionLinkId("link-3"),
                attempt_id=AttemptId("attempt-3"),
            ),
        )
    )
    malformed = replace(original, execution_links=links)
    uow.works.value = malformed

    with pytest.raises(ValueError, match="exactly one execution link"):
        _service(
            uow, RecordingDispatch(), deterministic_ids=True
        ).authorize(_second_command())

    assert uow.works.value == malformed
    assert uow.approvals.items == {}
