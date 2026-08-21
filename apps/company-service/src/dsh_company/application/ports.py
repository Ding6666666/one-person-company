from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from dsh_company.domain.approval import Approval
from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.delegation import Delegation
from dsh_company.domain.employee import Employee, EmployeeAgentBinding, EmployeeRevision
from dsh_company.domain.ids import (
    ApprovalId,
    AttemptId,
    DelegationId,
    EmployeeId,
    EmployeeRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ArtifactReference,
    CompanyEvent,
    ExecutionLink,
    Work,
    WorkGraphRevision,
    WorkNode,
)
from dsh_company.domain.workspace import Workspace


class EmployeeRecord(Protocol):
    @property
    def employee(self) -> Employee: ...

    @property
    def revision(self) -> EmployeeRevision: ...

    @property
    def binding(self) -> EmployeeAgentBinding: ...

    @property
    def grants(self) -> tuple[CapabilityGrant, ...]: ...


class IdFactory(Protocol):
    def __call__(self, prefix: str) -> str: ...


class WorkspaceRepository(Protocol):
    def add(self, workspace: Workspace) -> None: ...

    def get(self, workspace_id: WorkspaceId) -> Workspace | None: ...

    def list(self) -> tuple[Workspace, ...]: ...


class EmployeeRepository(Protocol):
    def add(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        binding: EmployeeAgentBinding,
        grants: tuple[CapabilityGrant, ...],
    ) -> None: ...

    def get(self, employee_id: EmployeeId) -> EmployeeRecord | None: ...

    def list_for_workspace(
        self, workspace_id: WorkspaceId
    ) -> tuple[EmployeeRecord, ...]: ...

    def revise(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        binding: EmployeeAgentBinding,
        grants: tuple[CapabilityGrant, ...],
    ) -> None: ...


class WorkEmployeeRepository(EmployeeRepository, Protocol):
    def get_revision(
        self, employee_id: EmployeeId, revision_id: EmployeeRevisionId
    ) -> EmployeeRecord | None: ...


@dataclass(frozen=True, slots=True)
class WorkAggregate:
    work: Work
    graph: WorkGraphRevision
    nodes: tuple[WorkNode, ...]
    execution_links: tuple[ExecutionLink, ...]
    artifacts: tuple[ArtifactReference, ...]


class DuplicateCommand(Exception):
    """A workspace already owns the supplied command ID."""


class WorkRepository(Protocol):
    def add(self, aggregate: WorkAggregate) -> None: ...

    def get(self, work_id: WorkId) -> WorkAggregate | None: ...

    def get_by_command(
        self, workspace_id: WorkspaceId, command_id: str
    ) -> WorkAggregate | None: ...

    def get_for_node(self, node_id: WorkNodeId) -> WorkAggregate | None: ...

    def get_for_attempt(self, attempt_id: AttemptId) -> WorkAggregate | None: ...

    def add_revision(
        self, graph: WorkGraphRevision, nodes: tuple[WorkNode, ...]
    ) -> None: ...

    def list_for_workspace(
        self, workspace_id: WorkspaceId
    ) -> tuple[WorkAggregate, ...]: ...

    def list_dispatch_pending(self) -> tuple[WorkAggregate, ...]: ...

    def list_running(self) -> tuple[WorkAggregate, ...]: ...

    def update(self, aggregate: WorkAggregate) -> None: ...


class CompanyEventRepository(Protocol):
    def append(self, event: CompanyEvent) -> None: ...

    def list_for_work(self, work_id: WorkId) -> tuple[CompanyEvent, ...]: ...


class WorkspaceGrantRepository(Protocol):
    def list_for_workspace(
        self, workspace_id: WorkspaceId
    ) -> tuple[CapabilityGrant, ...]: ...


class NodeGrantRepository(Protocol):
    def list_for_node(self, node_id: WorkNodeId) -> tuple[CapabilityGrant, ...]: ...

    def replace(
        self, node_id: WorkNodeId, grants: tuple[CapabilityGrant, ...]
    ) -> None: ...


class ApprovalRepository(Protocol):
    def add(self, approval: Approval) -> None: ...

    def get(self, approval_id: ApprovalId) -> Approval | None: ...

    def decide(self, approval: Approval) -> None: ...


class DelegationRepository(Protocol):
    def add(self, delegation: Delegation) -> None: ...

    def get(self, delegation_id: DelegationId) -> Delegation | None: ...

    def update(self, delegation: Delegation) -> None: ...

    def get_accepted_for_target(self, node_id: WorkNodeId) -> Delegation | None: ...


class WorkDispatchQueue(Protocol):
    def enqueue(self, node_id: WorkNodeId) -> None: ...


class WorkCoordinator(WorkDispatchQueue, Protocol):
    def request_cancel(self, node_id: WorkNodeId) -> None: ...


class UnitOfWork(Protocol):
    @property
    def workspaces(self) -> WorkspaceRepository: ...

    @property
    def employees(self) -> EmployeeRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class WorkUnitOfWork(UnitOfWork, Protocol):
    @property
    def employees(self) -> WorkEmployeeRepository: ...

    @property
    def works(self) -> WorkRepository: ...

    @property
    def company_events(self) -> CompanyEventRepository: ...


class GovernanceUnitOfWork(WorkUnitOfWork, Protocol):
    @property
    def workspace_grants(self) -> WorkspaceGrantRepository: ...

    @property
    def node_grants(self) -> NodeGrantRepository: ...

    @property
    def approvals(self) -> ApprovalRepository: ...

    @property
    def delegations(self) -> DelegationRepository: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> WorkUnitOfWork: ...


class GovernanceUnitOfWorkFactory(Protocol):
    def __call__(self) -> GovernanceUnitOfWork: ...
