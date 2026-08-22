from dataclasses import dataclass

from dsh_company.domain.capabilities import CapabilityLevel
from dsh_company.domain.ids import EmployeeId, WorkspaceId


@dataclass(frozen=True, slots=True)
class CreateWorkspace:
    name: str


@dataclass(frozen=True, slots=True)
class GrantInput:
    action: str
    level: CapabilityLevel
    resource_kind: str
    resource_values: tuple[str, ...]
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class CreateEmployee:
    workspace_id: WorkspaceId
    display_name: str
    responsibility: str
    runtime_profile: str
    model: str
    grants: tuple[GrantInput, ...]
    role_template_key: str = "custom"
    work_type: str = "自定义工作"
    avatar_key: str = "custom"
    skill_refs: tuple[str, ...] = ()
    tool_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviseEmployee:
    employee_id: EmployeeId
    responsibility: str
    runtime_profile: str
    model: str
    grants: tuple[GrantInput, ...]
    role_template_key: str | None = None
    work_type: str | None = None
    avatar_key: str | None = None
    skill_refs: tuple[str, ...] | None = None
    tool_refs: tuple[str, ...] | None = None
