from datetime import datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, Field, StringConstraints

from dsh_company.application.ports import EmployeeRecord
from dsh_company.domain.workspace import Workspace as DomainWorkspace

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Responsibility = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
ModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Action = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ResourceKind = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WorkspaceCreate(BaseModel):
    name: Name


class GrantCreate(BaseModel):
    action: Action
    level: Literal[0, 1, 2, 3]
    resource_kind: ResourceKind
    resource_values: list[str]
    requires_approval: bool


class EmployeeCreate(BaseModel):
    display_name: Name
    responsibility: Responsibility
    runtime_profile: Literal["workspace_read", "workspace_write", "network_denied"]
    model: ModelName
    grants: list[GrantCreate] = Field(default_factory=list)


class EmployeeRevise(BaseModel):
    responsibility: Responsibility
    runtime_profile: Literal["workspace_read", "workspace_write", "network_denied"]
    model: ModelName
    grants: list[GrantCreate] = Field(default_factory=list)


class Workspace(BaseModel):
    id: str
    name: str
    created_at: datetime

    @classmethod
    def from_domain(cls, workspace: DomainWorkspace) -> "Workspace":
        return cls(id=workspace.id, name=workspace.name, created_at=workspace.created_at)


class Grant(BaseModel):
    id: str
    employee_revision_id: str | None
    action: str
    level: Literal[0, 1, 2, 3]
    resource_kind: str
    resource_values: list[str]
    requires_approval: bool


class EmployeeRevision(BaseModel):
    id: str
    employee_id: str
    revision_number: int
    responsibility: str
    runtime_profile: str
    model: str
    created_at: datetime


class EmployeeBinding(BaseModel):
    id: str
    employee_id: str
    dsh_agent_id: str
    dsh_session_id: str
    memory_scope_id: str
    created_at: datetime


class Employee(BaseModel):
    id: str
    workspace_id: str
    display_name: str
    status: Literal["active", "paused", "archived"]
    current_revision_id: str
    created_at: datetime
    revision: EmployeeRevision
    binding: EmployeeBinding
    grants: list[Grant]

    @classmethod
    def from_record(cls, record: EmployeeRecord) -> "Employee":
        employee = record.employee
        revision = record.revision
        binding = record.binding
        return cls(
            id=employee.id,
            workspace_id=employee.workspace_id,
            display_name=employee.display_name,
            status=cast(Literal["active", "paused", "archived"], employee.status.value),
            current_revision_id=employee.current_revision_id,
            created_at=employee.created_at,
            revision=EmployeeRevision(
                id=revision.id,
                employee_id=revision.employee_id,
                revision_number=revision.revision_number,
                responsibility=revision.responsibility,
                runtime_profile=revision.runtime_profile,
                model=revision.model,
                created_at=revision.created_at,
            ),
            binding=EmployeeBinding(
                id=binding.id,
                employee_id=binding.employee_id,
                dsh_agent_id=binding.dsh_agent_id,
                dsh_session_id=binding.dsh_session_id,
                memory_scope_id=binding.memory_scope_id,
                created_at=binding.created_at,
            ),
            grants=[
                Grant(
                    id=grant.id,
                    employee_revision_id=grant.employee_revision_id,
                    action=grant.action,
                    level=cast(Literal[0, 1, 2, 3], int(grant.level)),
                    resource_kind=grant.resource_kind,
                    resource_values=list(grant.resource_values),
                    requires_approval=grant.requires_approval,
                )
                for grant in record.grants
            ],
        )
