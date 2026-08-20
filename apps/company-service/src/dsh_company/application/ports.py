from types import TracebackType
from typing import Protocol, Self

from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.employee import Employee, EmployeeAgentBinding, EmployeeRevision
from dsh_company.domain.ids import EmployeeId, WorkspaceId
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
        grants: tuple[CapabilityGrant, ...],
    ) -> None: ...


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
