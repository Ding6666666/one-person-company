import json
from dataclasses import dataclass
from datetime import UTC, datetime

from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.employee import (
    Employee,
    EmployeeAgentBinding,
    EmployeeRevision,
    EmployeeStatus,
)
from dsh_company.domain.ids import (
    CapabilityGrantId,
    EmployeeAgentBindingId,
    EmployeeId,
    EmployeeRevisionId,
    WorkspaceId,
)
from dsh_company.domain.workspace import Workspace
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    CapabilityGrantRow,
    EmployeeAgentBindingRow,
    EmployeeRevisionProfileRow,
    EmployeeRevisionRow,
    EmployeeRow,
    WorkspaceRow,
)


def _from_sqlite_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    employee: Employee
    revision: EmployeeRevision
    binding: EmployeeAgentBinding
    grants: tuple[CapabilityGrant, ...]


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace: Workspace) -> None:
        self._session.add(
            WorkspaceRow(
                id=workspace.id,
                name=workspace.name,
                created_at=workspace.created_at,
            )
        )

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            return None
        return Workspace(
            id=WorkspaceId(row.id),
            name=row.name,
            created_at=_from_sqlite_utc(row.created_at),
        )

    def list(self) -> tuple[Workspace, ...]:
        rows = self._session.scalars(
            select(WorkspaceRow).order_by(WorkspaceRow.created_at, WorkspaceRow.id)
        )
        return tuple(
            Workspace(
                id=WorkspaceId(row.id),
                name=row.name,
                created_at=_from_sqlite_utc(row.created_at),
            )
            for row in rows
        )


class EmployeeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        binding: EmployeeAgentBinding,
        grants: tuple[CapabilityGrant, ...],
    ) -> None:
        workspace_row = self._session.get(WorkspaceRow, employee.workspace_id)
        employee_row = EmployeeRow(
            id=employee.id,
            workspace_id=employee.workspace_id,
            display_name=employee.display_name,
            status=employee.status.value,
            current_revision_id=employee.current_revision_id,
            created_at=employee.created_at,
            workspace=workspace_row,
        )
        revision_row = EmployeeRevisionRow(
            id=revision.id,
            employee_id=revision.employee_id,
            revision_number=revision.revision_number,
            responsibility=revision.responsibility,
            runtime_profile=revision.runtime_profile,
            model=revision.model,
            created_at=revision.created_at,
            employee=employee_row,
        )
        binding_row = EmployeeAgentBindingRow(
            id=binding.id,
            employee_id=binding.employee_id,
            dsh_agent_id=binding.dsh_agent_id,
            dsh_session_id=binding.dsh_session_id,
            memory_scope_id=binding.memory_scope_id,
            created_at=binding.created_at,
            employee=employee_row,
        )
        profile_row = EmployeeRevisionProfileRow(
            employee_revision_id=revision.id,
            role_template_key=revision.role_template_key,
            work_type=revision.work_type,
            avatar_key=revision.avatar_key,
            skill_refs_json=json.dumps(revision.skill_refs, ensure_ascii=False),
            tool_refs_json=json.dumps(revision.tool_refs, ensure_ascii=False),
            revision=revision_row,
        )
        grant_rows = [
            CapabilityGrantRow(
                id=grant.id,
                employee_revision_id=grant.employee_revision_id or revision.id,
                action=grant.action,
                level=int(grant.level),
                resource_kind=grant.resource_kind,
                resource_values_json=json.dumps(grant.resource_values, ensure_ascii=False),
                requires_approval=grant.requires_approval,
                revision=revision_row,
            )
            for grant in grants
        ]
        self._session.add_all([employee_row, revision_row, profile_row, binding_row, *grant_rows])

    def get(self, employee_id: EmployeeId) -> EmployeeRecord | None:
        employee_row = self._session.get(EmployeeRow, employee_id)
        if employee_row is None:
            return None
        return self._record(employee_row)

    def get_revision(
        self, employee_id: EmployeeId, revision_id: EmployeeRevisionId
    ) -> EmployeeRecord | None:
        employee_row = self._session.get(EmployeeRow, employee_id)
        revision_row = self._session.get(EmployeeRevisionRow, revision_id)
        if (
            employee_row is None
            or revision_row is None
            or revision_row.employee_id != employee_row.id
        ):
            return None
        return self._record(employee_row, revision_row=revision_row)

    def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[EmployeeRecord, ...]:
        rows = self._session.scalars(
            select(EmployeeRow)
            .where(EmployeeRow.workspace_id == workspace_id)
            .order_by(EmployeeRow.created_at, EmployeeRow.id)
        )
        return tuple(self._record(row) for row in rows)

    def revise(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        binding: EmployeeAgentBinding,
        grants: tuple[CapabilityGrant, ...],
    ) -> None:
        employee_row = self._session.get(EmployeeRow, employee.id)
        if employee_row is None:
            raise LookupError("employee not found")
        revision_row = EmployeeRevisionRow(
            id=revision.id,
            employee_id=revision.employee_id,
            revision_number=revision.revision_number,
            responsibility=revision.responsibility,
            runtime_profile=revision.runtime_profile,
            model=revision.model,
            created_at=revision.created_at,
            employee=employee_row,
        )
        profile_row = EmployeeRevisionProfileRow(
            employee_revision_id=revision.id,
            role_template_key=revision.role_template_key,
            work_type=revision.work_type,
            avatar_key=revision.avatar_key,
            skill_refs_json=json.dumps(revision.skill_refs, ensure_ascii=False),
            tool_refs_json=json.dumps(revision.tool_refs, ensure_ascii=False),
            revision=revision_row,
        )
        grant_rows = [
            CapabilityGrantRow(
                id=grant.id,
                employee_revision_id=grant.employee_revision_id or revision.id,
                action=grant.action,
                level=int(grant.level),
                resource_kind=grant.resource_kind,
                resource_values_json=json.dumps(grant.resource_values, ensure_ascii=False),
                requires_approval=grant.requires_approval,
                revision=revision_row,
            )
            for grant in grants
        ]
        employee_row.current_revision_id = revision.id
        self._session.add_all([revision_row, profile_row, *grant_rows])

    def _record(
        self,
        employee_row: EmployeeRow,
        *,
        revision_row: EmployeeRevisionRow | None = None,
    ) -> EmployeeRecord:
        revision_row = revision_row or self._session.get(
            EmployeeRevisionRow, employee_row.current_revision_id
        )
        binding_row = self._session.scalar(
            select(EmployeeAgentBindingRow).where(
                EmployeeAgentBindingRow.employee_id == employee_row.id
            )
        )
        if revision_row is None or binding_row is None:
            raise RuntimeError("employee persistence record is incomplete")
        profile_row = self._session.get(EmployeeRevisionProfileRow, revision_row.id)
        grant_rows = self._session.scalars(
            select(CapabilityGrantRow)
            .where(CapabilityGrantRow.employee_revision_id == revision_row.id)
            .order_by(CapabilityGrantRow.action, CapabilityGrantRow.id)
        )
        return EmployeeRecord(
            employee=Employee(
                id=EmployeeId(employee_row.id),
                workspace_id=WorkspaceId(employee_row.workspace_id),
                display_name=employee_row.display_name,
                status=EmployeeStatus(employee_row.status),
                current_revision_id=EmployeeRevisionId(employee_row.current_revision_id),
                created_at=_from_sqlite_utc(employee_row.created_at),
            ),
            revision=EmployeeRevision(
                id=EmployeeRevisionId(revision_row.id),
                employee_id=EmployeeId(revision_row.employee_id),
                revision_number=revision_row.revision_number,
                responsibility=revision_row.responsibility,
                runtime_profile=revision_row.runtime_profile,
                model=revision_row.model,
                created_at=_from_sqlite_utc(revision_row.created_at),
                role_template_key=(
                    "custom" if profile_row is None else profile_row.role_template_key
                ),
                work_type="自定义工作" if profile_row is None else profile_row.work_type,
                avatar_key="custom" if profile_row is None else profile_row.avatar_key,
                skill_refs=(
                    () if profile_row is None else tuple(json.loads(profile_row.skill_refs_json))
                ),
                tool_refs=(
                    () if profile_row is None else tuple(json.loads(profile_row.tool_refs_json))
                ),
            ),
            binding=EmployeeAgentBinding(
                id=EmployeeAgentBindingId(binding_row.id),
                employee_id=EmployeeId(binding_row.employee_id),
                dsh_agent_id=binding_row.dsh_agent_id,
                dsh_session_id=binding_row.dsh_session_id,
                memory_scope_id=binding_row.memory_scope_id,
                created_at=_from_sqlite_utc(binding_row.created_at),
            ),
            grants=tuple(
                CapabilityGrant(
                    id=CapabilityGrantId(row.id),
                    employee_revision_id=EmployeeRevisionId(row.employee_revision_id),
                    action=row.action,
                    level=CapabilityLevel(row.level),
                    resource_kind=row.resource_kind,
                    resource_values=tuple(json.loads(row.resource_values_json)),
                    requires_approval=row.requires_approval,
                )
                for row in grant_rows
            ),
        )
