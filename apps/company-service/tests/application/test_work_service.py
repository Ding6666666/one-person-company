from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from dsh_company.application.work_commands import CreateDirectWork
from dsh_company.application.work_service import WorkService
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import EmployeeId, WorkNodeId, WorkspaceId
from dsh_company.domain.work import ExecutionStatus
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from sqlalchemy.engine import Engine

_WORKSPACE_ID = WorkspaceId("ws-1")
_EMPLOYEE_ID = EmployeeId("emp-1")


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"


class RacingIds:
    def __init__(self, label: str, barrier: Barrier) -> None:
        self._label = label
        self._barrier = barrier
        self._next = 0

    def __call__(self, prefix: str) -> str:
        self._next += 1
        if self._next == 1:
            self._barrier.wait()
        return f"{prefix}-{self._label}-{self._next}"


class RecordingQueue:
    def __init__(self) -> None:
        self.node_ids: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.node_ids.append(node_id)


class CountingUnitOfWork(SqlAlchemyUnitOfWork):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self.commits = 0

    def commit(self) -> None:
        super().commit()
        self.commits += 1


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    yield engine
    engine.dispose()


def _seed_employee(
    engine: Engine,
    *,
    workspace_id: WorkspaceId = _WORKSPACE_ID,
    employee_id: EmployeeId = _EMPLOYEE_ID,
) -> None:
    with SqlAlchemyUnitOfWork(engine) as uow:
        workspace = Workspace.create(workspace_id, "Direct work")
        employee, revision, binding = Employee.create(
            employee_id=employee_id,
            workspace_id=workspace.id,
            display_name="Editor",
            responsibility="Write release notes",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
        )
        uow.workspaces.add(workspace)
        uow.employees.add(employee, revision, binding, ())
        uow.commit()


def _command(*, command_id: str = "cmd-1") -> CreateDirectWork:
    return CreateDirectWork(
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        objective=" Write a release note ",
        acceptance_criteria=(" Has a title ",),
        command_id=command_id,
    )


def test_create_direct_work_is_idempotent_by_normalized_workspace_command(
    sqlite_engine: Engine,
) -> None:
    _seed_employee(sqlite_engine)
    uow = CountingUnitOfWork(sqlite_engine)
    queue = RecordingQueue()
    service = WorkService(uow, queue, id_factory=SequentialIds())

    first = service.create_direct(_command(command_id=" cmd-1 "))
    second = service.create_direct(_command(command_id="cmd-1"))

    assert second.work.id == first.work.id
    assert first.work.command_id == "cmd-1"
    assert uow.commits == 1
    assert queue.node_ids == [first.nodes[0].id]


def test_concurrent_same_command_returns_one_persisted_work_and_enqueues_once(
    sqlite_engine: Engine,
) -> None:
    _seed_employee(sqlite_engine)
    barrier = Barrier(2)
    queue = RecordingQueue()
    services = (
        WorkService(
            SqlAlchemyUnitOfWork(sqlite_engine),
            queue,
            id_factory=RacingIds("first", barrier),
        ),
        WorkService(
            SqlAlchemyUnitOfWork(sqlite_engine),
            queue,
            id_factory=RacingIds("second", barrier),
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.create_direct, _command()) for service in services]
        results = tuple(future.result() for future in futures)

    assert results[0].work.id == results[1].work.id
    with SqlAlchemyUnitOfWork(sqlite_engine) as uow:
        stored = uow.works.list_for_workspace(WorkspaceId("ws-1"))
    assert len(stored) == 1
    assert queue.node_ids == [stored[0].nodes[0].id]


def test_create_direct_work_freezes_active_employee_revision_and_binding(
    sqlite_engine: Engine,
) -> None:
    _seed_employee(sqlite_engine)
    queue = RecordingQueue()
    service = WorkService(
        SqlAlchemyUnitOfWork(sqlite_engine), queue, id_factory=SequentialIds()
    )

    aggregate = service.create_direct(_command())

    with SqlAlchemyUnitOfWork(sqlite_engine) as uow:
        employee = uow.employees.get(EmployeeId("emp-1"))
    assert employee is not None
    assert aggregate.nodes[0].employee_revision_id == employee.revision.id
    assert aggregate.execution_links[0].dsh_session_id == employee.binding.dsh_session_id
    assert aggregate.execution_links[0].status is ExecutionStatus.DISPATCH_PENDING


def test_create_direct_work_rejects_employee_from_another_workspace(
    sqlite_engine: Engine,
) -> None:
    _seed_employee(sqlite_engine)
    with SqlAlchemyUnitOfWork(sqlite_engine) as uow:
        uow.workspaces.add(Workspace.create(WorkspaceId("ws-2"), "Other"))
        uow.commit()
    queue = RecordingQueue()
    service = WorkService(
        SqlAlchemyUnitOfWork(sqlite_engine), queue, id_factory=SequentialIds()
    )

    with pytest.raises(LookupError, match="employee not found in workspace"):
        service.create_direct(
            CreateDirectWork(
                workspace_id=WorkspaceId("ws-2"),
                employee_id=EmployeeId("emp-1"),
                objective="Write",
                acceptance_criteria=("Complete",),
                command_id="cmd-other",
            )
        )

    assert queue.node_ids == []


def test_create_direct_work_requires_an_active_employee(
    sqlite_engine: Engine,
) -> None:
    _seed_employee(sqlite_engine)
    with sqlite_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE employees SET status = 'paused' WHERE id = 'emp-1'"
        )
    queue = RecordingQueue()
    service = WorkService(
        SqlAlchemyUnitOfWork(sqlite_engine), queue, id_factory=SequentialIds()
    )

    with pytest.raises(ValueError, match="employee must be active"):
        service.create_direct(_command())

    assert queue.node_ids == []
