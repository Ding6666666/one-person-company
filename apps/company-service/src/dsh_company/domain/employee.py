from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .ids import (
    EmployeeAgentBindingId,
    EmployeeId,
    EmployeeRevisionId,
    WorkspaceId,
    new_id,
)


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class EmployeeRevision:
    id: EmployeeRevisionId
    employee_id: EmployeeId
    revision_number: int
    responsibility: str
    runtime_profile: str
    model: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EmployeeAgentBinding:
    id: EmployeeAgentBindingId
    employee_id: EmployeeId
    dsh_agent_id: str
    dsh_session_id: str
    memory_scope_id: str
    created_at: datetime

    @classmethod
    def create(
        cls, *, employee_id: EmployeeId, dsh_agent_id: str, dsh_session_id: str
    ) -> "EmployeeAgentBinding":
        if dsh_agent_id != dsh_session_id:
            raise ValueError("DSH Agent ID must equal Session ID for the verified SDK")
        return cls(
            id=EmployeeAgentBindingId(new_id("binding")),
            employee_id=employee_id,
            dsh_agent_id=dsh_agent_id,
            dsh_session_id=dsh_session_id,
            memory_scope_id=f"dsh-session:{dsh_session_id}",
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class Employee:
    id: EmployeeId
    workspace_id: WorkspaceId
    display_name: str
    status: EmployeeStatus
    current_revision_id: EmployeeRevisionId
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        employee_id: EmployeeId,
        workspace_id: WorkspaceId,
        display_name: str,
        responsibility: str,
        runtime_profile: str,
        model: str,
    ) -> tuple["Employee", EmployeeRevision, EmployeeAgentBinding]:
        name = display_name.strip()
        duty = responsibility.strip()
        if not name or not duty:
            raise ValueError("employee name and responsibility must not be blank")
        now = datetime.now(UTC)
        revision = EmployeeRevision(
            id=EmployeeRevisionId(new_id("revision")),
            employee_id=employee_id,
            revision_number=1,
            responsibility=duty,
            runtime_profile=runtime_profile,
            model=model,
            created_at=now,
        )
        session_id = f"employee-{employee_id}"
        binding = EmployeeAgentBinding.create(
            employee_id=employee_id,
            dsh_agent_id=session_id,
            dsh_session_id=session_id,
        )
        return (
            cls(employee_id, workspace_id, name, EmployeeStatus.ACTIVE, revision.id, now),
            revision,
            binding,
        )
