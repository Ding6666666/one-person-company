from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.domain.employee import Employee, EmployeeRevision
from dsh_company.domain.ids import (
    AttemptId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkNodeStatus,
    WorkStatus,
)
from dsh_company.domain.workspace import Workspace
from dsh_company.dsh_gateway.contracts import (
    GatewayCancelResult,
    GatewayResult,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.events import ProjectedDshEvent
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from dsh_company.persistence.work_repositories import WorkAggregate
from sqlalchemy.engine import Engine


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"


class RecordingGateway:
    def __init__(
        self,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        *,
        fail: BaseException | None = None,
        cancel_closed: bool = True,
        cancel_fail: BaseException | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._fail = fail
        self._cancel_closed = cancel_closed
        self._cancel_fail = cancel_fail
        self.submissions: list[GatewaySubmission] = []
        self.status_at_submit: list[ExecutionStatus] = []
        self.status_at_cancel: list[ExecutionStatus] = []

    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult:
        with self._uow_factory() as uow:
            aggregate = uow.works.get_for_attempt(submission.attempt_id)
        assert aggregate is not None
        self.status_at_submit.append(aggregate.execution_links[0].status)
        self.submissions.append(submission)
        on_event(
            ProjectedDshEvent(
                attempt_id=submission.attempt_id,
                source_sequence=1,
                details={"method": "session.event", "event_type": "assistant/end"},
            )
        )
        if self._fail is not None:
            raise self._fail
        return GatewayResult(
            finish_reason="completed",
            reference_uri=(
                f"dsh-session://{submission.employee.dsh_session_id}"
                f"/attempt/{submission.attempt_id}/result"
            ),
            event_count=1,
        )

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult:
        with self._uow_factory() as uow:
            aggregate = uow.works.get_for_attempt(attempt_id)
        assert aggregate is not None
        self.status_at_cancel.append(aggregate.execution_links[0].status)
        if self._cancel_fail is not None:
            raise self._cancel_fail
        return GatewayCancelResult(
            requested=self._cancel_closed, runtime_closed=self._cancel_closed
        )


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    yield engine
    engine.dispose()


def _uow_factory(engine: Engine) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(engine)


def _seed(
    engine: Engine,
    *,
    work_id: str = "work-1",
    execution_status: ExecutionStatus = ExecutionStatus.DISPATCH_PENDING,
) -> WorkAggregate:
    with SqlAlchemyUnitOfWork(engine) as uow:
        if uow.workspaces.get(WorkspaceId("ws-1")) is None:
            workspace = Workspace.create(WorkspaceId("ws-1"), "Direct work")
            employee, revision, binding = Employee.create(
                employee_id=EmployeeId("emp-1"),
                workspace_id=workspace.id,
                display_name="Editor",
                responsibility="Frozen responsibility",
                runtime_profile="workspace_read",
                model="deepseek-v4-flash",
            )
            uow.workspaces.add(workspace)
            uow.employees.add(employee, revision, binding, ())
        else:
            record = uow.employees.get(EmployeeId("emp-1"))
            assert record is not None
            revision = record.revision
            binding = record.binding
        work, graph, node = Work.create_direct(
            work_id=WorkId(work_id),
            graph_id=WorkGraphRevisionId(f"graph-{work_id}"),
            node_id=WorkNodeId(f"node-{work_id}"),
            workspace_id=WorkspaceId("ws-1"),
            employee_id=EmployeeId("emp-1"),
            employee_revision_id=revision.id,
            objective="Write a release note",
            acceptance_criteria=("Has a title",),
            command_id=f"command-{work_id}",
        )
        link = ExecutionLink.dispatch(
            execution_link_id=ExecutionLinkId(f"link-{work_id}"),
            attempt_id=AttemptId(f"attempt-{work_id}"),
            node_id=node.id,
            command_id=f"command-{work_id}",
            dsh_session_id=binding.dsh_session_id,
        )
        if execution_status is ExecutionStatus.RUNNING:
            link = link.mark_running()
            work = work.start()
            node = node.start(link.attempt_id)
        aggregate = WorkAggregate(work, graph, (node,), (link,), ())
        uow.works.add(aggregate)
        uow.commit()
    return aggregate


def test_coordinator_commits_running_before_calling_dsh_and_completes_safely(
    sqlite_engine: Engine,
) -> None:
    aggregate = _seed(sqlite_engine)
    factory = _uow_factory(sqlite_engine)
    gateway = RecordingGateway(factory)
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.dispatch(aggregate.nodes[0].id)

    assert gateway.status_at_submit == [ExecutionStatus.RUNNING]
    assert gateway.submissions[0].employee.employee_revision_id == EmployeeRevisionId(
        aggregate.nodes[0].employee_revision_id
    )
    with factory() as uow:
        stored = uow.works.get(aggregate.work.id)
        events = uow.company_events.list_for_work(aggregate.work.id)
    assert stored is not None
    assert stored.work.status is WorkStatus.COMPLETED
    assert stored.nodes[0].status is WorkNodeStatus.COMPLETED
    assert stored.execution_links[0].status is ExecutionStatus.COMPLETED
    assert len(stored.artifacts) == 1
    assert [event.event_type for event in events] == ["assistant/end", "work.completed"]


def test_coordinator_uses_revision_frozen_by_work_creation(
    sqlite_engine: Engine,
) -> None:
    aggregate = _seed(sqlite_engine)
    factory = _uow_factory(sqlite_engine)
    with factory() as uow:
        current = uow.employees.get(EmployeeId("emp-1"))
        assert current is not None
        revised = EmployeeRevision(
            id=EmployeeRevisionId("revision-new"),
            employee_id=current.employee.id,
            revision_number=2,
            responsibility="Later responsibility",
            runtime_profile="network_denied",
            model="later-model",
            created_at=datetime.now(UTC),
        )
        uow.employees.revise(
            replace(current.employee, current_revision_id=revised.id),
            revised,
            current.binding,
            (),
        )
        uow.commit()
    gateway = RecordingGateway(factory)
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.dispatch(aggregate.nodes[0].id)

    snapshot = gateway.submissions[0].employee
    assert snapshot.employee_revision_id == aggregate.nodes[0].employee_revision_id
    assert snapshot.responsibility == "Frozen responsibility"
    assert snapshot.runtime_profile == "workspace_read"


def test_coordinator_stores_only_closed_failure_diagnostic(
    sqlite_engine: Engine,
) -> None:
    aggregate = _seed(sqlite_engine)
    factory = _uow_factory(sqlite_engine)
    gateway = RecordingGateway(factory, fail=RuntimeError("private provider detail"))
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.dispatch(aggregate.nodes[0].id)

    with factory() as uow:
        stored = uow.works.get(aggregate.work.id)
        events = uow.company_events.list_for_work(aggregate.work.id)
    assert stored is not None
    assert stored.work.status is WorkStatus.FAILED
    assert stored.nodes[0].failure_code == "gateway_error"
    assert stored.execution_links[0].diagnostic_code == "gateway_error"
    assert "private provider detail" not in repr((stored, events))


@pytest.mark.parametrize(
    ("runtime_closed", "expected_status", "expected_code"),
    [
        (True, ExecutionStatus.CANCELLED, None),
        (False, ExecutionStatus.BLOCKED, "cancel_unconfirmed"),
    ],
)
def test_cancel_is_persisted_before_gateway_and_distinguishes_confirmation(
    sqlite_engine: Engine,
    runtime_closed: bool,
    expected_status: ExecutionStatus,
    expected_code: str | None,
) -> None:
    aggregate = _seed(sqlite_engine, execution_status=ExecutionStatus.RUNNING)
    factory = _uow_factory(sqlite_engine)
    gateway = RecordingGateway(factory, cancel_closed=runtime_closed)
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.request_cancel(aggregate.nodes[0].id)

    assert gateway.status_at_cancel == [ExecutionStatus.CANCEL_REQUESTED]
    with factory() as uow:
        stored = uow.works.get(aggregate.work.id)
    assert stored is not None
    assert stored.execution_links[0].status is expected_status
    assert stored.execution_links[0].diagnostic_code == expected_code
    expected_work = WorkStatus.CANCELLED if runtime_closed else WorkStatus.BLOCKED
    assert stored.work.status is expected_work


def test_cancel_close_exception_is_blocked_without_storing_exception_text(
    sqlite_engine: Engine,
) -> None:
    aggregate = _seed(sqlite_engine, execution_status=ExecutionStatus.RUNNING)
    factory = _uow_factory(sqlite_engine)
    gateway = RecordingGateway(
        factory, cancel_fail=RuntimeError("private close detail")
    )
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.request_cancel(aggregate.nodes[0].id)

    with factory() as uow:
        stored = uow.works.get(aggregate.work.id)
    assert stored is not None
    assert stored.work.status is WorkStatus.BLOCKED
    assert stored.nodes[0].failure_code == "cancel_unconfirmed"
    assert stored.execution_links[0].diagnostic_code == "cancel_unconfirmed"
    assert "private close detail" not in repr(stored)


def test_startup_requeues_pending_and_blocks_only_running_attempts(
    sqlite_engine: Engine,
) -> None:
    pending = _seed(sqlite_engine, work_id="pending")
    running = _seed(
        sqlite_engine, work_id="running", execution_status=ExecutionStatus.RUNNING
    )
    factory = _uow_factory(sqlite_engine)
    gateway = RecordingGateway(factory)
    coordinator = RuntimeCoordinator(factory, gateway, id_factory=SequentialIds())

    coordinator.start()
    coordinator.shutdown(wait=True)

    with factory() as uow:
        pending_stored = uow.works.get(pending.work.id)
        running_stored = uow.works.get(running.work.id)
    assert pending_stored is not None
    assert pending_stored.work.status is WorkStatus.COMPLETED
    assert running_stored is not None
    assert running_stored.work.status is WorkStatus.BLOCKED
    assert running_stored.nodes[0].failure_code == "runtime_process_lost"
    assert (
        running_stored.execution_links[0].diagnostic_code == "runtime_process_lost"
    )
