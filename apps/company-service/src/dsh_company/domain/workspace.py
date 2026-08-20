from dataclasses import dataclass
from datetime import UTC, datetime

from .ids import WorkspaceId


@dataclass(frozen=True, slots=True)
class Workspace:
    id: WorkspaceId
    name: str
    created_at: datetime

    @classmethod
    def create(cls, workspace_id: WorkspaceId, name: str) -> "Workspace":
        normalized = name.strip()
        if not normalized:
            raise ValueError("workspace name must not be blank")
        return cls(id=workspace_id, name=normalized, created_at=datetime.now(UTC))
