from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from .ids import (
    DelegationId,
    EmployeeId,
    EmployeeRevisionId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from .work import (
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
)


class IdFactory(Protocol):
    def __call__(self, prefix: str) -> str: ...


DelegationStatus = Literal["proposed", "accepted", "rejected", "completed"]


@dataclass(frozen=True, slots=True)
class Delegation:
    id: DelegationId
    workspace_id: WorkspaceId
    work_id: WorkId
    source_node_id: WorkNodeId
    target_node_id: WorkNodeId | None
    proposer_employee_id: EmployeeId
    target_employee_id: EmployeeId
    graph_revision_id: WorkGraphRevisionId
    status: DelegationStatus
    created_at: datetime

    def __post_init__(self) -> None:
        if self.status in {"accepted", "completed"} and self.target_node_id is None:
            raise ValueError("accepted delegation requires a target node")
        if self.status == "rejected" and self.target_node_id is not None:
            raise ValueError("rejected delegation cannot have a target node")


@dataclass(frozen=True, slots=True)
class DelegationProposal:
    proposer_employee_id: EmployeeId
    target_employee_id: EmployeeId
    objective: str
    acceptance_criteria: tuple[str, ...]
    required_actions: tuple[str, ...]
    resource_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DelegationRevision:
    graph: WorkGraphRevision
    nodes: tuple[WorkNode, ...]


def apply_delegation(
    original: WorkGraphRevision,
    nodes: tuple[WorkNode, ...],
    proposal: DelegationProposal,
    *,
    workspace_id: WorkspaceId,
    source_node_id: WorkNodeId,
    target_employee_revision_id: EmployeeRevisionId,
    ids: IdFactory,
) -> tuple[DelegationRevision, Delegation]:
    if tuple(node.id for node in nodes) != original.node_ids:
        raise ValueError("graph node facts must match revision node IDs")
    source = next((node for node in nodes if node.id == source_node_id), None)
    if source is None:
        raise ValueError("delegation source node is not in the graph revision")
    if source.assigned_employee_id != proposal.proposer_employee_id:
        raise ValueError("delegation proposer does not own the source node")

    graph_id = WorkGraphRevisionId(ids("work-graph"))
    target_node_id = WorkNodeId(ids("work-node"))
    target = WorkNode(
        id=target_node_id,
        graph_revision_id=graph_id,
        work_id=original.work_id,
        objective=proposal.objective,
        acceptance_criteria=proposal.acceptance_criteria,
        required_actions=tuple(proposal.required_actions),
        resource_values=tuple(proposal.resource_values),
        assigned_employee_id=proposal.target_employee_id,
        employee_revision_id=target_employee_revision_id,
        status=WorkNodeStatus.READY,
        active_attempt_id=None,
        failure_code=None,
        version=1,
    )
    revised_nodes = (*nodes, target)
    revised_graph = WorkGraphRevision(
        id=graph_id,
        work_id=original.work_id,
        revision_number=original.revision_number + 1,
        strategy=original.strategy,
        created_at=datetime.now(UTC),
        node_ids=tuple(node.id for node in revised_nodes),
        edges=(
            *original.edges,
            WorkEdge(source_node_id, target_node_id, WorkEdgeKind.DELEGATES_TO),
        ),
    )
    delegation = Delegation(
        id=DelegationId(ids("delegation")),
        workspace_id=workspace_id,
        work_id=original.work_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        proposer_employee_id=proposal.proposer_employee_id,
        target_employee_id=proposal.target_employee_id,
        graph_revision_id=graph_id,
        status="accepted",
        created_at=datetime.now(UTC),
    )
    return DelegationRevision(revised_graph, revised_nodes), delegation
