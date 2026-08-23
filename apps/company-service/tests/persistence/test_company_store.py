from collections.abc import Iterator
from pathlib import Path

import pytest
from dsh_company.application.commands import CreateEmployee, CreateWorkspace, ReviseEmployee
from dsh_company.application.company_service import CompanyService
from dsh_company.domain.capabilities import default_employee_grants
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import EmployeeId, WorkspaceId
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.repositories import EmployeeRecord
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sqlite_uow(sqlite_engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(sqlite_engine)


def test_sqlite_engine_enables_foreign_keys(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as connection:
        enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()

    assert enabled == 1


def _add_employee(
    uow: SqlAlchemyUnitOfWork, *, workspace_id: str, employee_id: str
) -> None:
    workspace = Workspace.create(WorkspaceId(workspace_id), f"Workspace {workspace_id}")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId(employee_id),
        workspace_id=workspace.id,
        display_name=f"Employee {employee_id}",
        responsibility="Write",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    uow.workspaces.add(workspace)
    uow.employees.add(
        employee,
        revision,
        binding,
        default_employee_grants(workspace.id),
    )


def test_workspace_employee_revision_grants_and_binding_round_trip(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace = Workspace.create(WorkspaceId("ws-1"), "内容公司")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"),
        workspace_id=workspace.id,
        display_name="编辑",
        responsibility="写作",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    grants = default_employee_grants(workspace.id)

    with sqlite_uow as uow:
        uow.workspaces.add(workspace)
        uow.employees.add(employee, revision, binding, grants)
        uow.commit()

    with sqlite_uow as uow:
        stored_workspace = uow.workspaces.get(workspace.id)
        stored = uow.employees.get(employee.id)

    assert stored_workspace == workspace
    assert isinstance(stored, EmployeeRecord)
    assert stored.employee == employee
    assert stored.revision == revision
    assert stored.binding == binding
    assert {grant.action for grant in stored.grants} == {
        "conversation.respond",
        "workspace.read",
        "session.history.read",
    }
    assert all(isinstance(grant.resource_values, tuple) for grant in stored.grants)
    assert all(grant.employee_revision_id == revision.id for grant in stored.grants)


def test_workspace_boundary_filters_employee_queries(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    with sqlite_uow as uow:
        _add_employee(uow, workspace_id="ws-a", employee_id="emp-a")
        _add_employee(uow, workspace_id="ws-b", employee_id="emp-b")
        uow.commit()

    with sqlite_uow as uow:
        employees = uow.employees.list_for_workspace(WorkspaceId("ws-a"))

    assert [item.employee.id for item in employees] == [EmployeeId("emp-a")]


def test_employee_revision_round_trip_preserves_binding(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    service = CompanyService(sqlite_uow)
    workspace = service.create_workspace(CreateWorkspace(name="Content company"))
    created = service.create_employee(
        CreateEmployee(
            workspace_id=workspace.id,
            display_name="Editor",
            responsibility="Write",
            system_prompt="# Role identity\nAct as a professional editor.",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(),
        )
    )

    revised = service.revise_employee(
        ReviseEmployee(
            employee_id=created.employee.id,
            responsibility="Write and fact check",
            system_prompt="# Role identity\nAct as a senior fact-checking editor.",
            runtime_profile="workspace_write",
            model="deepseek-v4-flash",
            grants=(),
        )
    )
    with sqlite_uow as uow:
        reloaded = uow.employees.get(created.employee.id)
        original = uow.employees.get_revision(created.employee.id, created.revision.id)

    assert reloaded == revised
    assert reloaded is not None
    assert reloaded.revision.revision_number == 2
    assert reloaded.revision.system_prompt == (
        "# Role identity\nAct as a senior fact-checking editor."
    )
    assert original is not None
    assert original.revision.system_prompt == "# Role identity\nAct as a professional editor."
    assert reloaded.employee.current_revision_id == revised.revision.id
    assert reloaded.binding == created.binding
    assert all(
        grant.employee_revision_id == revised.revision.id
        for grant in reloaded.grants
    )


def test_uncommitted_unit_of_work_rolls_back(sqlite_uow: SqlAlchemyUnitOfWork) -> None:
    with sqlite_uow as uow:
        uow.workspaces.add(Workspace.create(WorkspaceId("ws-rollback"), "Temporary"))

    with sqlite_uow as uow:
        stored = uow.workspaces.get(WorkspaceId("ws-rollback"))

    assert stored is None


def test_employee_commit_requires_an_existing_workspace(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-orphan"),
        workspace_id=WorkspaceId("ws-missing"),
        display_name="Orphan",
        responsibility="Write",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )

    with pytest.raises(IntegrityError):
        with sqlite_uow as uow:
            uow.employees.add(
                employee,
                revision,
                binding,
                default_employee_grants(employee.workspace_id),
            )
            uow.commit()

    with sqlite_uow as uow:
        stored = uow.employees.get(employee.id)

    assert stored is None
