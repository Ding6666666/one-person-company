import json
from datetime import UTC
from typing import Any, cast

from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.delegation import Delegation, DelegationStatus
from dsh_company.domain.ids import (
    ApprovalId,
    CapabilityGrantId,
    DelegationId,
    EmployeeId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from .models import (
    ApprovalRow,
    DelegationRow,
    NodeCapabilityGrantRow,
    WorkspaceCapabilityGrantRow,
)


class ConcurrentApprovalDecision(Exception):
    """An approval was decided since the caller read it."""


def _grant(row: WorkspaceCapabilityGrantRow | NodeCapabilityGrantRow) -> CapabilityGrant:
    scope = (
        f"workspace:{row.workspace_id}"
        if isinstance(row, WorkspaceCapabilityGrantRow)
        else f"node:{row.node_id}"
    )
    return CapabilityGrant(
        id=CapabilityGrantId(f"{scope}:{row.action}"),
        employee_revision_id=None,
        action=row.action,
        level=CapabilityLevel(row.level),
        resource_kind=row.resource_kind,
        resource_values=tuple(json.loads(row.resource_values_json)),
        requires_approval=row.requires_approval,
    )


class WorkspaceCapabilityGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(self, workspace_id: WorkspaceId, grants: tuple[CapabilityGrant, ...]) -> None:
        self._session.execute(
            delete(WorkspaceCapabilityGrantRow).where(
                WorkspaceCapabilityGrantRow.workspace_id == workspace_id
            )
        )
        self._session.add_all(
            WorkspaceCapabilityGrantRow(
                workspace_id=workspace_id,
                action=grant.action,
                level=int(grant.level),
                resource_kind=grant.resource_kind,
                resource_values_json=json.dumps(grant.resource_values, ensure_ascii=False),
                requires_approval=grant.requires_approval,
            )
            for grant in grants
        )

    def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[CapabilityGrant, ...]:
        rows = self._session.scalars(
            select(WorkspaceCapabilityGrantRow)
            .where(WorkspaceCapabilityGrantRow.workspace_id == workspace_id)
            .order_by(WorkspaceCapabilityGrantRow.action)
        )
        return tuple(_grant(row) for row in rows)


class NodeCapabilityGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(self, node_id: WorkNodeId, grants: tuple[CapabilityGrant, ...]) -> None:
        self._session.execute(
            delete(NodeCapabilityGrantRow).where(NodeCapabilityGrantRow.node_id == node_id)
        )
        self._session.add_all(
            NodeCapabilityGrantRow(
                node_id=node_id,
                action=grant.action,
                level=int(grant.level),
                resource_kind=grant.resource_kind,
                resource_values_json=json.dumps(grant.resource_values, ensure_ascii=False),
                requires_approval=grant.requires_approval,
            )
            for grant in grants
        )

    def list_for_node(self, node_id: WorkNodeId) -> tuple[CapabilityGrant, ...]:
        rows = self._session.scalars(
            select(NodeCapabilityGrantRow)
            .where(NodeCapabilityGrantRow.node_id == node_id)
            .order_by(NodeCapabilityGrantRow.action)
        )
        return tuple(_grant(row) for row in rows)


class ApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, approval: Approval) -> None:
        if len(approval.reason) > 500:
            raise ValueError("approval reason must not exceed 500 characters")
        self._session.add(
            ApprovalRow(
                id=approval.id,
                workspace_id=approval.workspace_id,
                work_id=approval.work_id,
                node_id=approval.node_id,
                action=approval.action,
                resources_json=json.dumps(approval.resources, ensure_ascii=False),
                reason=approval.reason,
                status=approval.status.value,
                requested_at=approval.requested_at,
                decided_at=approval.decided_at,
                decided_by=approval.decided_by,
            )
        )

    def get(self, approval_id: ApprovalId) -> Approval | None:
        row = self._session.get(ApprovalRow, approval_id)
        if row is None:
            return None
        return Approval(
            id=ApprovalId(row.id),
            workspace_id=WorkspaceId(row.workspace_id),
            work_id=WorkId(row.work_id),
            node_id=WorkNodeId(row.node_id),
            action=row.action,
            resources=tuple(json.loads(row.resources_json)),
            reason=row.reason,
            status=ApprovalStatus(row.status),
            requested_at=row.requested_at.replace(tzinfo=UTC),
            decided_at=None if row.decided_at is None else row.decided_at.replace(tzinfo=UTC),
            decided_by=row.decided_by,
        )

    def decide(self, approval: Approval) -> None:
        if approval.status is ApprovalStatus.PENDING or approval.decided_at is None:
            raise ValueError("approval decision must be closed")
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(ApprovalRow)
                .where(
                    ApprovalRow.id == approval.id,
                    ApprovalRow.status == ApprovalStatus.PENDING.value,
                )
                .values(
                    status=approval.status.value,
                    decided_at=approval.decided_at,
                    decided_by=approval.decided_by,
                )
            ),
        )
        if result.rowcount == 0:
            raise ConcurrentApprovalDecision(str(approval.id))


class DelegationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, delegation: Delegation) -> None:
        self._session.add(
            DelegationRow(
                id=delegation.id,
                workspace_id=delegation.workspace_id,
                work_id=delegation.work_id,
                source_node_id=delegation.source_node_id,
                target_node_id=delegation.target_node_id,
                proposer_employee_id=delegation.proposer_employee_id,
                target_employee_id=delegation.target_employee_id,
                graph_revision_id=delegation.graph_revision_id,
                status=delegation.status,
                created_at=delegation.created_at,
            )
        )

    def get(self, delegation_id: DelegationId) -> Delegation | None:
        row = self._session.get(DelegationRow, delegation_id)
        if row is None:
            return None
        return Delegation(
            id=DelegationId(row.id),
            workspace_id=WorkspaceId(row.workspace_id),
            work_id=WorkId(row.work_id),
            source_node_id=WorkNodeId(row.source_node_id),
            target_node_id=WorkNodeId(row.target_node_id),
            proposer_employee_id=EmployeeId(row.proposer_employee_id),
            target_employee_id=EmployeeId(row.target_employee_id),
            graph_revision_id=WorkGraphRevisionId(row.graph_revision_id),
            status=cast(DelegationStatus, row.status),
            created_at=row.created_at.replace(tzinfo=UTC),
        )
