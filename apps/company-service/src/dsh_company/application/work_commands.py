from dataclasses import dataclass

from dsh_company.domain.ids import EmployeeId, WorkspaceId


@dataclass(frozen=True, slots=True)
class CreateDirectWork:
    workspace_id: WorkspaceId
    employee_id: EmployeeId
    objective: str
    acceptance_criteria: tuple[str, ...]
    command_id: str
