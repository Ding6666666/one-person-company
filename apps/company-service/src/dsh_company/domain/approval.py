from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from .ids import ApprovalId, WorkId, WorkNodeId, WorkspaceId


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Approval:
    id: ApprovalId
    workspace_id: WorkspaceId
    work_id: WorkId
    node_id: WorkNodeId
    action: str
    resources: tuple[str, ...]
    reason: str
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None

    @classmethod
    def request(
        cls,
        *,
        approval_id: ApprovalId,
        workspace_id: WorkspaceId,
        work_id: WorkId,
        node_id: WorkNodeId,
        action: str,
        resources: tuple[str, ...],
        reason: str,
    ) -> "Approval":
        return cls(
            id=approval_id,
            workspace_id=workspace_id,
            work_id=work_id,
            node_id=node_id,
            action=action,
            resources=resources,
            reason=reason,
            status=ApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
            decided_at=None,
            decided_by=None,
        )

    def approve(self, *, decided_by: str) -> "Approval":
        return self._decide(ApprovalStatus.APPROVED, decided_by)

    def reject(self, *, decided_by: str) -> "Approval":
        return self._decide(ApprovalStatus.REJECTED, decided_by)

    def cancel(self, *, decided_by: str) -> "Approval":
        return self._decide(ApprovalStatus.CANCELLED, decided_by)

    def _decide(self, status: ApprovalStatus, decided_by: str) -> "Approval":
        if self.status is not ApprovalStatus.PENDING:
            raise ValueError("approval is already decided")
        return replace(
            self,
            status=status,
            decided_at=datetime.now(UTC),
            decided_by=decided_by,
        )
