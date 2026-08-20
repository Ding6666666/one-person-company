from dataclasses import dataclass
from enum import IntEnum

from .ids import CapabilityGrantId, EmployeeRevisionId, WorkspaceId, new_id


class CapabilityLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    id: CapabilityGrantId
    employee_revision_id: EmployeeRevisionId | None
    action: str
    level: CapabilityLevel
    resource_kind: str
    resource_values: tuple[str, ...]
    requires_approval: bool


def default_employee_grants(workspace_id: WorkspaceId) -> tuple[CapabilityGrant, ...]:
    values = (str(workspace_id),)
    return tuple(
        CapabilityGrant(
            id=CapabilityGrantId(new_id("grant")),
            employee_revision_id=None,
            action=action,
            level=level,
            resource_kind="workspace",
            resource_values=values,
            requires_approval=False,
        )
        for action, level in (
            ("conversation.respond", CapabilityLevel.L0),
            ("workspace.read", CapabilityLevel.L1),
            ("session.history.read", CapabilityLevel.L1),
        )
    )
