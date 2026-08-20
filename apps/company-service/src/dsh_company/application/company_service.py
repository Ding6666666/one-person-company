from dataclasses import replace
from datetime import UTC, datetime

from dsh_company.domain.capabilities import CapabilityGrant, default_employee_grants
from dsh_company.domain.employee import Employee, EmployeeRevision
from dsh_company.domain.ids import (
    CapabilityGrantId,
    EmployeeId,
    EmployeeRevisionId,
    WorkspaceId,
    new_id,
)
from dsh_company.domain.workspace import Workspace

from .commands import CreateEmployee, CreateWorkspace, GrantInput, ReviseEmployee
from .ports import EmployeeRecord, IdFactory, UnitOfWork


class CompanyService:
    def __init__(self, uow: UnitOfWork, *, id_factory: IdFactory = new_id) -> None:
        self._uow = uow
        self._id_factory = id_factory

    def create_workspace(self, command: CreateWorkspace) -> Workspace:
        workspace = Workspace.create(
            WorkspaceId(self._id_factory("workspace")), command.name
        )
        with self._uow as uow:
            uow.workspaces.add(workspace)
            uow.commit()
        return workspace

    def create_employee(self, command: CreateEmployee) -> EmployeeRecord:
        with self._uow as uow:
            if uow.workspaces.get(command.workspace_id) is None:
                raise LookupError("workspace not found")
            employee, revision, binding = Employee.create(
                employee_id=EmployeeId(self._id_factory("employee")),
                workspace_id=command.workspace_id,
                display_name=command.display_name,
                responsibility=command.responsibility,
                runtime_profile=command.runtime_profile,
                model=command.model,
            )
            grants = self._grant_snapshot(command.workspace_id, revision.id, command.grants)
            uow.employees.add(employee, revision, binding, grants)
            uow.commit()
            record = uow.employees.get(employee.id)
        if record is None:
            raise RuntimeError("employee was not persisted")
        return record

    def revise_employee(self, command: ReviseEmployee) -> EmployeeRecord:
        with self._uow as uow:
            current = uow.employees.get(command.employee_id)
            if current is None:
                raise LookupError("employee not found")
            revision = EmployeeRevision(
                id=EmployeeRevisionId(self._id_factory("revision")),
                employee_id=current.employee.id,
                revision_number=current.revision.revision_number + 1,
                responsibility=command.responsibility.strip(),
                runtime_profile=command.runtime_profile,
                model=command.model,
                created_at=datetime.now(UTC),
            )
            if not revision.responsibility:
                raise ValueError("employee responsibility must not be blank")
            employee = replace(current.employee, current_revision_id=revision.id)
            grants = self._grant_snapshot(
                employee.workspace_id, revision.id, command.grants
            )
            uow.employees.revise(employee, revision, grants)
            uow.commit()
            record = uow.employees.get(employee.id)
        if record is None:
            raise RuntimeError("employee revision was not persisted")
        return record

    def get_workspace(self, workspace_id: WorkspaceId) -> Workspace:
        with self._uow as uow:
            workspace = uow.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError("workspace not found")
        return workspace

    def list_employees(self, workspace_id: WorkspaceId) -> tuple[EmployeeRecord, ...]:
        with self._uow as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            return uow.employees.list_for_workspace(workspace_id)

    def get_employee(self, employee_id: EmployeeId) -> EmployeeRecord:
        with self._uow as uow:
            record = uow.employees.get(employee_id)
        if record is None:
            raise LookupError("employee not found")
        return record

    def _grant_snapshot(
        self,
        workspace_id: WorkspaceId,
        revision_id: EmployeeRevisionId,
        explicit: tuple[GrantInput, ...],
    ) -> tuple[CapabilityGrant, ...]:
        by_action = {
            grant.action: replace(grant, employee_revision_id=revision_id)
            for grant in default_employee_grants(workspace_id)
        }
        by_action.update(
            {
                item.action: CapabilityGrant(
                    id=CapabilityGrantId(self._id_factory("grant")),
                    employee_revision_id=revision_id,
                    action=item.action,
                    level=item.level,
                    resource_kind=item.resource_kind,
                    resource_values=item.resource_values,
                    requires_approval=item.requires_approval,
                )
                for item in explicit
            }
        )
        return tuple(by_action.values())
