import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CompanyEventId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ArtifactReference,
    CompanyEvent,
    ExecutionLink,
    ExecutionStatus,
    Work,
)
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from dsh_company.persistence.work_repositories import (
    ConcurrentNodeUpdate,
    DuplicateCommand,
    WorkAggregate,
)
from sqlalchemy.engine import Engine

_UNUSED_REVISION_ID = EmployeeRevisionId("unused")


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sqlite_uow(sqlite_engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(sqlite_engine)


def _seed_company(uow: SqlAlchemyUnitOfWork) -> EmployeeRevisionId:
    workspace = Workspace.create(WorkspaceId("ws-1"), "Direct work")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"),
        workspace_id=workspace.id,
        display_name="Editor",
        responsibility="Write",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    uow.workspaces.add(workspace)
    uow.employees.add(employee, revision, binding, ())
    return revision.id


def _aggregate(
    *,
    work_id: str = "work-1",
    command_id: str = "cmd-1",
    status: ExecutionStatus = ExecutionStatus.DISPATCH_PENDING,
    employee_revision_id: EmployeeRevisionId = _UNUSED_REVISION_ID,
) -> WorkAggregate:
    work, graph, node = Work.create_direct(
        work_id=WorkId(work_id),
        graph_id=WorkGraphRevisionId(f"graph-{work_id}"),
        node_id=WorkNodeId(f"node-{work_id}"),
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=employee_revision_id,
        objective="Write a release note",
        acceptance_criteria=("Has a title", "Under 800 words"),
        command_id=command_id,
    )
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId(f"link-{work_id}"),
        attempt_id=AttemptId(f"attempt-{work_id}"),
        node_id=node.id,
        command_id=f"dispatch-{work_id}",
        dsh_session_id="employee-emp-1",
    )
    if status is ExecutionStatus.RUNNING:
        link = link.mark_running()
        work = work.start()
        node = node.start(link.attempt_id)
    artifact = ArtifactReference(
        id=ArtifactReferenceId(f"artifact-{work_id}"),
        workspace_id=work.workspace_id,
        kind="dsh_session_result",
        uri=f"dsh-session://employee-emp-1/attempt/{link.attempt_id}/result",
        source_session_id="employee-emp-1",
        source_attempt_id=link.attempt_id,
        created_at=datetime.now(UTC),
    )
    return WorkAggregate(work, graph, (node,), (link,), (artifact,))


def test_direct_graph_and_attempt_round_trip(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    aggregate = _aggregate()
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        aggregate = replace(
            aggregate,
            nodes=(replace(aggregate.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(aggregate)
        uow.commit()

    with sqlite_uow as uow:
        stored = uow.works.get(aggregate.work.id)

    assert stored == aggregate
    assert stored is not None
    assert isinstance(stored.nodes[0].acceptance_criteria, tuple)
    assert stored.work.created_at.tzinfo is UTC


def test_command_id_is_unique_per_workspace(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        uow.works.add(
            _aggregate(
                work_id="work-1",
                command_id="cmd-1",
                employee_revision_id=revision_id,
            )
        )
        uow.commit()

    with pytest.raises(DuplicateCommand):
        with sqlite_uow as uow:
            uow.works.add(
                _aggregate(
                    work_id="work-2",
                    command_id="cmd-1",
                    employee_revision_id=revision_id,
                )
            )
            uow.commit()


def test_work_queries_filter_workspace_and_lifecycle(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    pending = _aggregate(work_id="pending", command_id="cmd-pending")
    running = _aggregate(
        work_id="running", command_id="cmd-running", status=ExecutionStatus.RUNNING
    )
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        pending = replace(
            pending,
            nodes=(replace(pending.nodes[0], employee_revision_id=revision_id),),
        )
        running = replace(
            running,
            nodes=(replace(running.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(pending)
        uow.works.add(running)
        uow.commit()

    with sqlite_uow as uow:
        assert uow.works.get_by_command(WorkspaceId("ws-1"), "cmd-pending") == pending
        assert uow.works.get_by_command(WorkspaceId("missing"), "cmd-pending") is None
        assert {item.work.id for item in uow.works.list_for_workspace(WorkspaceId("ws-1"))} == {
            WorkId("pending"),
            WorkId("running"),
        }
        assert uow.works.list_dispatch_pending() == (pending,)
        assert uow.works.list_running() == (running,)


def test_company_events_keep_attempt_source_sequence(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    aggregate = _aggregate()
    observed_at = datetime.now(UTC)
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        aggregate = replace(
            aggregate,
            nodes=(replace(aggregate.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(aggregate)
        for sequence in (3, 1, 2):
            uow.company_events.append(
                CompanyEvent(
                    id=CompanyEventId(f"event-{sequence}"),
                    workspace_id=aggregate.work.workspace_id,
                    work_id=aggregate.work.id,
                    node_id=aggregate.nodes[0].id,
                    attempt_id=aggregate.execution_links[0].attempt_id,
                    source_sequence=sequence,
                    event_type="session.event",
                    summary=f"event {sequence}",
                    source="dsh",
                    observed_at=observed_at,
                )
            )
        uow.commit()

    with sqlite_uow as uow:
        events = uow.company_events.list_for_work(WorkId("work-1"))

    assert [event.source_sequence for event in events] == [1, 2, 3]
    assert all(event.observed_at.tzinfo is UTC for event in events)


def test_company_events_order_multiple_attempts_by_observation_time(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    aggregate = _aggregate()
    first_observed = datetime.now(UTC)
    event_specs = (
        ("attempt-a-2", AttemptId("attempt-a"), 2, first_observed + timedelta(seconds=1)),
        ("attempt-b-1", AttemptId("attempt-b"), 1, first_observed + timedelta(seconds=2)),
        ("attempt-a-1", AttemptId("attempt-a"), 1, first_observed),
    )
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        aggregate = replace(
            aggregate,
            nodes=(replace(aggregate.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(aggregate)
        for event_id, attempt_id, sequence, observed_at in event_specs:
            uow.company_events.append(
                CompanyEvent(
                    id=CompanyEventId(event_id),
                    workspace_id=aggregate.work.workspace_id,
                    work_id=aggregate.work.id,
                    node_id=aggregate.nodes[0].id,
                    attempt_id=attempt_id,
                    source_sequence=sequence,
                    event_type="session.event",
                    summary=event_id,
                    source="dsh",
                    observed_at=observed_at,
                )
            )
        uow.commit()

    with sqlite_uow as uow:
        events = uow.company_events.list_for_work(aggregate.work.id)

    assert [event.id for event in events] == [
        CompanyEventId("attempt-a-1"),
        CompanyEventId("attempt-a-2"),
        CompanyEventId("attempt-b-1"),
    ]


def test_node_update_uses_optimistic_version(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    aggregate = _aggregate()
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        aggregate = replace(
            aggregate,
            nodes=(replace(aggregate.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(aggregate)
        uow.commit()

    running_link = aggregate.execution_links[0].mark_running()
    running = replace(
        aggregate,
        work=aggregate.work.start(),
        nodes=(aggregate.nodes[0].start(running_link.attempt_id),),
        execution_links=(running_link,),
    )
    with sqlite_uow as uow:
        uow.works.update(running)
        uow.commit()

    stale = replace(running, nodes=(replace(running.nodes[0], version=1),))
    with pytest.raises(ConcurrentNodeUpdate):
        with sqlite_uow as uow:
            uow.works.update(stale)

    with sqlite_uow as uow:
        stored = uow.works.get(aggregate.work.id)
    assert stored == running


def test_divergent_node_with_same_version_is_concurrent(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    aggregate = _aggregate()
    with sqlite_uow as uow:
        revision_id = _seed_company(uow)
        aggregate = replace(
            aggregate,
            nodes=(replace(aggregate.nodes[0], employee_revision_id=revision_id),),
        )
        uow.works.add(aggregate)
        uow.commit()

    link = aggregate.execution_links[0].mark_running()
    running = replace(
        aggregate,
        work=aggregate.work.start(),
        nodes=(aggregate.nodes[0].start(link.attempt_id),),
        execution_links=(link,),
    )
    with sqlite_uow as uow:
        uow.works.update(running)
        uow.commit()

    divergent = replace(
        running,
        nodes=(
            replace(
                running.nodes[0],
                active_attempt_id=AttemptId("attempt-from-stale-caller"),
            ),
        ),
    )
    with pytest.raises(ConcurrentNodeUpdate):
        with sqlite_uow as uow:
            uow.works.update(divergent)


def test_work_schema_has_no_model_content_columns(sqlite_engine: Engine) -> None:
    forbidden = {"prompt", "transcript", "tool_args", "final_response"}
    with sqlite_engine.connect() as connection:
        tables = (
            "works",
            "work_graph_revisions",
            "work_nodes",
            "execution_links",
            "artifact_references",
            "company_events",
        )
        columns = {
            row[1]
            for table in tables
            for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        }

    assert columns.isdisjoint(forbidden)


def test_alembic_metadata_matches_migrated_work_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "alembic-check.db"
    monkeypatch.setenv("DSH_COMPANY_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    config = Config("apps/company-service/alembic.ini")

    command.upgrade(config, "head")
    process_environment = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
        if name in os.environ
    }
    process_environment["DSH_COMPANY_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/company-service/alembic.ini",
            "check",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=process_environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
