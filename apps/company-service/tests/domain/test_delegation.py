from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from dsh_company.domain.delegation import (
    Delegation,
    DelegationProposal,
    apply_delegation,
)
from dsh_company.domain.ids import (
    DelegationId,
    EmployeeId,
    EmployeeRevisionId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStrategy,
)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"


def direct_node(
    *,
    node_id: str = "node-parent",
    employee_id: str = "emp-a",
    status: WorkNodeStatus = WorkNodeStatus.RUNNING,
) -> WorkNode:
    return WorkNode(
        id=WorkNodeId(node_id),
        graph_revision_id=WorkGraphRevisionId("graph-1"),
        work_id=WorkId("work-1"),
        objective="撰写发布稿",
        acceptance_criteria=("包含来源",),
        assigned_employee_id=EmployeeId(employee_id),
        employee_revision_id=EmployeeRevisionId(f"revision-{employee_id}"),
        status=status,
        active_attempt_id=None,
        failure_code=None,
        version=1,
    )


def test_delegation_creates_new_revision_without_rewriting_completed_nodes() -> None:
    completed = direct_node(
        node_id="node-completed",
        employee_id="emp-c",
        status=WorkNodeStatus.COMPLETED,
    )
    parent = direct_node()
    original = WorkGraphRevision(
        id=WorkGraphRevisionId("graph-1"),
        work_id=WorkId("work-1"),
        revision_number=1,
        strategy=WorkStrategy.DIRECT,
        created_at=datetime.now(UTC),
        node_ids=(completed.id, parent.id),
        edges=(WorkEdge(completed.id, parent.id, WorkEdgeKind.DEPENDS_ON),),
    )
    proposal = DelegationProposal(
        proposer_employee_id=EmployeeId("emp-a"),
        target_employee_id=EmployeeId("emp-b"),
        objective="事实核查",
        acceptance_criteria=("列出来源",),
        required_actions=("workspace.read",),
        resource_values=("ws-1",),
    )

    revised, delegation = apply_delegation(
        original,
        (completed, parent),
        proposal,
        workspace_id=WorkspaceId("ws-1"),
        source_node_id=parent.id,
        target_employee_revision_id=EmployeeRevisionId("revision-emp-b"),
        ids=SequentialIds(),
    )

    assert revised.graph.revision_number == original.revision_number + 1
    assert revised.nodes[:2] == (completed, parent)
    assert revised.nodes[0] is completed
    assert revised.nodes[-1].status is WorkNodeStatus.READY
    assert revised.nodes[-1].required_actions == proposal.required_actions
    assert revised.nodes[-1].resource_values == proposal.resource_values
    assert revised.graph.node_ids == tuple(node.id for node in revised.nodes)
    assert revised.graph.edges[:-1] == original.edges
    assert revised.graph.edges[-1] == WorkEdge(
        parent.id, revised.nodes[-1].id, WorkEdgeKind.DELEGATES_TO
    )
    assert delegation.id == DelegationId("delegation-3")
    assert delegation.target_employee_id == EmployeeId("emp-b")
    assert delegation.graph_revision_id == revised.graph.id
    assert delegation.status == "accepted"
    with pytest.raises(FrozenInstanceError):
        revised.graph.revision_number = 9  # type: ignore[misc]


def test_graph_revision_rejects_cycles_and_unknown_edge_nodes() -> None:
    now = datetime.now(UTC)
    node_a = WorkNodeId("node-a")
    node_b = WorkNodeId("node-b")

    with pytest.raises(ValueError, match="unknown node"):
        WorkGraphRevision(
            WorkGraphRevisionId("graph-1"),
            WorkId("work-1"),
            1,
            WorkStrategy.DIRECT,
            now,
            (node_a,),
            (WorkEdge(node_a, node_b, WorkEdgeKind.DEPENDS_ON),),
        )
    with pytest.raises(ValueError, match="acyclic"):
        WorkGraphRevision(
            WorkGraphRevisionId("graph-1"),
            WorkId("work-1"),
            1,
            WorkStrategy.DIRECT,
            now,
            (node_a, node_b),
            (
                WorkEdge(node_a, node_b, WorkEdgeKind.DEPENDS_ON),
                WorkEdge(node_b, node_a, WorkEdgeKind.DELEGATES_TO),
            ),
        )


def test_rejected_delegation_has_no_false_target_node() -> None:
    rejected = Delegation(
        id=DelegationId("delegation-rejected"),
        workspace_id=WorkspaceId("ws-1"),
        work_id=WorkId("work-1"),
        source_node_id=WorkNodeId("node-parent"),
        target_node_id=None,
        proposer_employee_id=EmployeeId("emp-a"),
        target_employee_id=EmployeeId("emp-b"),
        graph_revision_id=WorkGraphRevisionId("graph-1"),
        status="rejected",
        created_at=datetime.now(UTC),
    )

    assert rejected.target_node_id is None
    with pytest.raises(ValueError, match="accepted delegation requires a target node"):
        replace(rejected, status="accepted")
    with pytest.raises(ValueError, match="rejected delegation cannot have a target node"):
        replace(rejected, target_node_id=WorkNodeId("node-placeholder"))
