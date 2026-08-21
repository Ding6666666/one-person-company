from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from .ids import (
    ArtifactReferenceId,
    AttemptId,
    CompanyEventId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)


class WorkStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkNodeStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    DISPATCH_PENDING = "dispatch_pending"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkStrategy(StrEnum):
    DIRECT = "direct"


class WorkEdgeKind(StrEnum):
    DEPENDS_ON = "depends_on"
    DELEGATES_TO = "delegates_to"
    REVIEWS = "reviews"
    SUMMARIZES = "summarizes"


def _expect_status(actual: StrEnum, expected: StrEnum) -> None:
    if actual is not expected:
        raise ValueError(f"transition requires {expected.name} status, got {actual.name}")


def _expect_attempt(actual: AttemptId | None, expected: AttemptId) -> None:
    if actual != expected:
        raise ValueError(
            f"transition attempt {expected!s} does not match active attempt {actual!s}"
        )


@dataclass(frozen=True, slots=True)
class WorkEdge:
    from_node_id: WorkNodeId
    to_node_id: WorkNodeId
    kind: WorkEdgeKind


@dataclass(frozen=True, slots=True)
class WorkGraphRevision:
    id: WorkGraphRevisionId
    work_id: WorkId
    revision_number: int
    strategy: WorkStrategy
    created_at: datetime
    node_ids: tuple[WorkNodeId, ...] = ()
    edges: tuple[WorkEdge, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("graph revision node IDs must be unique")
        known_nodes = set(self.node_ids)
        if any(
            edge.from_node_id not in known_nodes or edge.to_node_id not in known_nodes
            for edge in self.edges
        ):
            raise ValueError("graph edge references an unknown node")
        outgoing = {node_id: [] for node_id in self.node_ids}
        for edge in self.edges:
            outgoing[edge.from_node_id].append(edge.to_node_id)
        visiting: set[WorkNodeId] = set()
        visited: set[WorkNodeId] = set()

        def visit(node_id: WorkNodeId) -> None:
            if node_id in visiting:
                raise ValueError("work graph must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target_id in outgoing[node_id]:
                visit(target_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.node_ids:
            visit(node_id)


@dataclass(frozen=True, slots=True)
class WorkNode:
    id: WorkNodeId
    graph_revision_id: WorkGraphRevisionId
    work_id: WorkId
    objective: str
    acceptance_criteria: tuple[str, ...]
    assigned_employee_id: EmployeeId
    employee_revision_id: EmployeeRevisionId
    status: WorkNodeStatus
    active_attempt_id: AttemptId | None
    failure_code: str | None
    version: int
    required_actions: tuple[str, ...] = ()
    resource_values: tuple[str, ...] = ()
    input_references: tuple[ArtifactReferenceId | WorkNodeId, ...] = ()
    output_references: tuple[ArtifactReferenceId, ...] = ()
    max_attempts: int = 1
    attempt_count: int = 0

    def wait_for_approval(self) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.READY)
        return replace(
            self,
            status=WorkNodeStatus.WAITING_APPROVAL,
            active_attempt_id=None,
            failure_code=None,
            version=self.version + 1,
        )

    def approval_approved(self) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.WAITING_APPROVAL)
        return replace(
            self,
            status=WorkNodeStatus.READY,
            failure_code=None,
            version=self.version + 1,
        )

    def approval_rejected(self) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.WAITING_APPROVAL)
        return replace(
            self,
            status=WorkNodeStatus.FAILED,
            failure_code="approval_rejected",
            version=self.version + 1,
        )

    def start(self, attempt_id: AttemptId) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.READY)
        return replace(
            self,
            status=WorkNodeStatus.RUNNING,
            active_attempt_id=attempt_id,
            failure_code=None,
            version=self.version + 1,
        )

    def block_before_start(self, failure_code: str) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.READY)
        return replace(
            self,
            status=WorkNodeStatus.BLOCKED,
            failure_code=failure_code,
            version=self.version + 1,
        )

    def complete(
        self, attempt_id: AttemptId, result_reference_id: ArtifactReferenceId | None
    ) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.RUNNING)
        _expect_attempt(self.active_attempt_id, attempt_id)
        if result_reference_id is None:
            raise ValueError("node completion requires a result reference")
        return replace(
            self,
            status=WorkNodeStatus.COMPLETED,
            failure_code=None,
            output_references=(*self.output_references, result_reference_id),
            version=self.version + 1,
        )

    def block(self, attempt_id: AttemptId, failure_code: str) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.RUNNING)
        _expect_attempt(self.active_attempt_id, attempt_id)
        return replace(
            self,
            status=WorkNodeStatus.BLOCKED,
            failure_code=failure_code,
            version=self.version + 1,
        )

    def fail(self, attempt_id: AttemptId, failure_code: str) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.RUNNING)
        _expect_attempt(self.active_attempt_id, attempt_id)
        return replace(
            self,
            status=WorkNodeStatus.FAILED,
            failure_code=failure_code,
            version=self.version + 1,
        )

    def cancel(self, attempt_id: AttemptId) -> "WorkNode":
        _expect_status(self.status, WorkNodeStatus.RUNNING)
        _expect_attempt(self.active_attempt_id, attempt_id)
        return replace(
            self,
            status=WorkNodeStatus.CANCELLED,
            failure_code=None,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class Work:
    id: WorkId
    workspace_id: WorkspaceId
    command_id: str
    objective: str
    status: WorkStatus
    current_graph_revision_id: WorkGraphRevisionId
    created_at: datetime

    @classmethod
    def create_direct(
        cls,
        *,
        work_id: WorkId,
        graph_id: WorkGraphRevisionId,
        node_id: WorkNodeId,
        workspace_id: WorkspaceId,
        employee_id: EmployeeId,
        employee_revision_id: EmployeeRevisionId,
        objective: str,
        acceptance_criteria: tuple[str, ...],
        command_id: str,
    ) -> tuple["Work", WorkGraphRevision, WorkNode]:
        normalized_objective = objective.strip()
        if not normalized_objective:
            raise ValueError("work objective must not be blank")
        normalized_command_id = command_id.strip()
        if not normalized_command_id:
            raise ValueError("command ID must not be blank")
        normalized_criteria = tuple(
            criterion.strip() for criterion in acceptance_criteria if criterion.strip()
        )
        if not normalized_criteria:
            raise ValueError("at least one acceptance criterion must not be blank")

        now = datetime.now(UTC)
        work = cls(
            id=work_id,
            workspace_id=workspace_id,
            command_id=normalized_command_id,
            objective=normalized_objective,
            status=WorkStatus.QUEUED,
            current_graph_revision_id=graph_id,
            created_at=now,
        )
        graph = WorkGraphRevision(
            id=graph_id,
            work_id=work_id,
            revision_number=1,
            strategy=WorkStrategy.DIRECT,
            created_at=now,
            node_ids=(node_id,),
        )
        node = WorkNode(
            id=node_id,
            graph_revision_id=graph_id,
            work_id=work_id,
            objective=normalized_objective,
            acceptance_criteria=normalized_criteria,
            assigned_employee_id=employee_id,
            employee_revision_id=employee_revision_id,
            status=WorkNodeStatus.READY,
            active_attempt_id=None,
            failure_code=None,
            version=1,
        )
        return work, graph, node

    def start(self) -> "Work":
        _expect_status(self.status, WorkStatus.QUEUED)
        return replace(self, status=WorkStatus.RUNNING)

    def block_before_start(self) -> "Work":
        _expect_status(self.status, WorkStatus.QUEUED)
        return replace(self, status=WorkStatus.BLOCKED)

    def block(self) -> "Work":
        _expect_status(self.status, WorkStatus.RUNNING)
        return replace(self, status=WorkStatus.BLOCKED)

    def complete(self) -> "Work":
        _expect_status(self.status, WorkStatus.RUNNING)
        return replace(self, status=WorkStatus.COMPLETED)

    def fail(self) -> "Work":
        _expect_status(self.status, WorkStatus.RUNNING)
        return replace(self, status=WorkStatus.FAILED)

    def cancel(self) -> "Work":
        _expect_status(self.status, WorkStatus.RUNNING)
        return replace(self, status=WorkStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class ExecutionLink:
    id: ExecutionLinkId
    node_id: WorkNodeId
    attempt_id: AttemptId
    command_id: str
    dsh_session_id: str
    status: ExecutionStatus
    started_at: datetime | None
    finished_at: datetime | None
    diagnostic_code: str | None

    @classmethod
    def dispatch(
        cls,
        *,
        execution_link_id: ExecutionLinkId,
        attempt_id: AttemptId,
        node_id: WorkNodeId,
        command_id: str,
        dsh_session_id: str,
    ) -> "ExecutionLink":
        return cls(
            id=execution_link_id,
            node_id=node_id,
            attempt_id=attempt_id,
            command_id=command_id,
            dsh_session_id=dsh_session_id,
            status=ExecutionStatus.DISPATCH_PENDING,
            started_at=None,
            finished_at=None,
            diagnostic_code=None,
        )

    def mark_running(self) -> "ExecutionLink":
        _expect_status(self.status, ExecutionStatus.DISPATCH_PENDING)
        return replace(self, status=ExecutionStatus.RUNNING, started_at=datetime.now(UTC))

    def request_cancel(self) -> "ExecutionLink":
        if self.status not in {
            ExecutionStatus.DISPATCH_PENDING,
            ExecutionStatus.RUNNING,
        }:
            raise ValueError(
                "transition requires DISPATCH_PENDING or RUNNING status, "
                f"got {self.status.name}"
            )
        return replace(self, status=ExecutionStatus.CANCEL_REQUESTED)

    def confirm_cancelled(self) -> "ExecutionLink":
        _expect_status(self.status, ExecutionStatus.CANCEL_REQUESTED)
        return replace(self, status=ExecutionStatus.CANCELLED, finished_at=datetime.now(UTC))

    def block(self, attempt_id: AttemptId, diagnostic_code: str) -> "ExecutionLink":
        if self.status not in {ExecutionStatus.RUNNING, ExecutionStatus.CANCEL_REQUESTED}:
            raise ValueError(
                f"transition requires RUNNING or CANCEL_REQUESTED status, got {self.status.name}"
            )
        _expect_attempt(self.attempt_id, attempt_id)
        return replace(
            self,
            status=ExecutionStatus.BLOCKED,
            finished_at=datetime.now(UTC),
            diagnostic_code=diagnostic_code,
        )

    def complete(
        self, attempt_id: AttemptId, result_reference_id: ArtifactReferenceId | None
    ) -> "ExecutionLink":
        _expect_status(self.status, ExecutionStatus.RUNNING)
        _expect_attempt(self.attempt_id, attempt_id)
        if result_reference_id is None:
            raise ValueError("execution completion requires a result reference")
        return replace(
            self,
            status=ExecutionStatus.COMPLETED,
            finished_at=datetime.now(UTC),
            diagnostic_code=None,
        )

    def fail(self, attempt_id: AttemptId, diagnostic_code: str) -> "ExecutionLink":
        _expect_status(self.status, ExecutionStatus.RUNNING)
        _expect_attempt(self.attempt_id, attempt_id)
        return replace(
            self,
            status=ExecutionStatus.FAILED,
            finished_at=datetime.now(UTC),
            diagnostic_code=diagnostic_code,
        )


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    id: ArtifactReferenceId
    workspace_id: WorkspaceId
    kind: Literal["dsh_session_result"]
    uri: str
    source_session_id: str
    source_attempt_id: AttemptId
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CompanyEvent:
    id: CompanyEventId
    workspace_id: WorkspaceId
    work_id: WorkId
    node_id: WorkNodeId | None
    attempt_id: AttemptId | None
    source_sequence: int
    event_type: str
    summary: str
    source: str
    observed_at: datetime
