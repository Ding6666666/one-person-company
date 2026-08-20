from types import TracebackType

import pytest
from dsh_company.application.commands import (
    CreateEmployee,
    CreateWorkspace,
    GrantInput,
    ReviseEmployee,
)
from dsh_company.application.company_service import CompanyService
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.employee import Employee, EmployeeAgentBinding, EmployeeRevision
from dsh_company.domain.ids import EmployeeId, WorkspaceId
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.repositories import EmployeeRecord


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"


class FakeWorkspaceRepository:
    def __init__(self) -> None:
        self.items: dict[WorkspaceId, Workspace] = {}

    def add(self, workspace: Workspace) -> None:
        self.items[workspace.id] = workspace

    def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return self.items.get(workspace_id)


class FakeEmployeeRepository:
    def __init__(self) -> None:
        self.items: dict[EmployeeId, EmployeeRecord] = {}
        self.revisions: dict[EmployeeId, list[EmployeeRevision]] = {}

    def add(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        binding: EmployeeAgentBinding,
        grants: tuple[CapabilityGrant, ...],
    ) -> None:
        record = EmployeeRecord(employee, revision, binding, grants)
        self.items[employee.id] = record
        self.revisions[employee.id] = [revision]

    def get(self, employee_id: EmployeeId) -> EmployeeRecord | None:
        return self.items.get(employee_id)

    def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[EmployeeRecord, ...]:
        return tuple(
            record
            for record in self.items.values()
            if record.employee.workspace_id == workspace_id
        )

    def revise(
        self,
        employee: Employee,
        revision: EmployeeRevision,
        grants: tuple[CapabilityGrant, ...],
    ) -> None:
        current = self.items[employee.id]
        self.revisions[employee.id].append(revision)
        self.items[employee.id] = EmployeeRecord(
            employee,
            revision,
            current.binding,
            grants,
        )


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.workspaces = FakeWorkspaceRepository()
        self.employees = FakeEmployeeRepository()
        self.commits = 0

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def employee_revisions(self, employee_id: EmployeeId) -> tuple[EmployeeRevision, ...]:
        return tuple(self.employees.revisions[employee_id])


class ForbiddenGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []


@pytest.fixture
def fake_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def forbidden_gateway() -> ForbiddenGateway:
    return ForbiddenGateway()


def test_create_employee_is_local_and_does_not_start_dsh(
    fake_uow: FakeUnitOfWork, forbidden_gateway: ForbiddenGateway
) -> None:
    service = CompanyService(fake_uow, id_factory=SequentialIds())
    workspace = service.create_workspace(CreateWorkspace(name="内容公司"))

    result = service.create_employee(
        CreateEmployee(
            workspace_id=workspace.id,
            display_name="编辑",
            responsibility="写作",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(
                GrantInput(
                    action="workspace.read",
                    level=CapabilityLevel.L2,
                    resource_kind="workspace",
                    resource_values=(str(workspace.id),),
                    requires_approval=True,
                ),
            ),
        )
    )

    assert result.employee.display_name == "编辑"
    assert result.binding.dsh_session_id.startswith("employee-")
    assert {grant.action for grant in result.grants} == {
        "conversation.respond",
        "workspace.read",
        "session.history.read",
    }
    workspace_read = next(
        grant for grant in result.grants if grant.action == "workspace.read"
    )
    assert workspace_read.level is CapabilityLevel.L2
    assert workspace_read.requires_approval is True
    assert all(
        grant.employee_revision_id == result.revision.id for grant in result.grants
    )
    assert fake_uow.commits == 2
    assert forbidden_gateway.calls == []


def test_create_employee_requires_an_existing_workspace(
    fake_uow: FakeUnitOfWork,
) -> None:
    service = CompanyService(fake_uow, id_factory=SequentialIds())

    with pytest.raises(LookupError, match="workspace not found"):
        service.create_employee(
            CreateEmployee(
                workspace_id=WorkspaceId("missing"),
                display_name="编辑",
                responsibility="写作",
                runtime_profile="workspace_read",
                model="deepseek-v4-flash",
                grants=(),
            )
        )

    assert fake_uow.commits == 0


def test_revise_employee_appends_revision_without_rewriting_old_one(
    fake_uow: FakeUnitOfWork,
) -> None:
    service = CompanyService(fake_uow, id_factory=SequentialIds())
    workspace = service.create_workspace(CreateWorkspace(name="内容公司"))
    seeded = service.create_employee(
        CreateEmployee(
            workspace_id=workspace.id,
            display_name="编辑",
            responsibility="写作",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(),
        )
    )

    revised = service.revise_employee(
        ReviseEmployee(
            employee_id=seeded.employee.id,
            responsibility="写作和事实核查",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(),
        )
    )

    assert revised.revision.revision_number == 2
    assert revised.employee.current_revision_id == revised.revision.id
    assert revised.binding == seeded.binding
    assert fake_uow.employee_revisions(seeded.employee.id)[0].responsibility == "写作"
    assert all(
        grant.employee_revision_id == revised.revision.id for grant in revised.grants
    )
    assert fake_uow.commits == 3


def test_queries_preserve_workspace_boundary(fake_uow: FakeUnitOfWork) -> None:
    service = CompanyService(fake_uow, id_factory=SequentialIds())
    first = service.create_workspace(CreateWorkspace(name="一组"))
    second = service.create_workspace(CreateWorkspace(name="二组"))
    employee = service.create_employee(
        CreateEmployee(
            workspace_id=first.id,
            display_name="编辑",
            responsibility="写作",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(),
        )
    )
    assert service.get_workspace(first.id) == first
    assert service.list_employees(first.id) == (employee,)
    assert service.list_employees(second.id) == ()
    assert service.get_employee(employee.employee.id) == employee
