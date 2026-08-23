from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dsh_company.application.commands import CreateEmployee, CreateWorkspace
from dsh_company.application.company_service import CompanyService
from dsh_company.application.work_commands import CreateDirectWork
from dsh_company.application.work_service import WorkService
from dsh_company.domain.conversation import (
    ChatExecution,
    ConversationMessage,
    MessageAuthorKind,
    MessageKind,
)
from dsh_company.domain.ids import (
    ChatExecutionId,
    EmployeeId,
    MessageId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from sqlalchemy.exc import IntegrityError


class NoopDispatch:
    def enqueue(self, node_id: WorkNodeId) -> None:
        del node_id
        return None


@pytest.fixture
def sqlite_uow(tmp_path: Path) -> Iterator[SqlAlchemyUnitOfWork]:
    engine = create_sqlite_engine(tmp_path / "chat.db")
    create_tables(engine)
    yield SqlAlchemyUnitOfWork(engine)
    engine.dispose()


def _company(sqlite_uow: SqlAlchemyUnitOfWork) -> tuple[WorkspaceId, EmployeeId]:
    service = CompanyService(sqlite_uow)
    workspace = service.create_workspace(CreateWorkspace(name="Chat company"))
    employee = service.create_employee(
        CreateEmployee(
            workspace_id=workspace.id,
            display_name="产品经理",
            responsibility="梳理需求",
            system_prompt="保持专业",
            runtime_profile="workspace_read",
            model="deepseek-v4-flash",
            grants=(),
        )
    )
    return workspace.id, employee.employee.id


def test_message_mentions_and_executions_round_trip(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_id = _company(sqlite_uow)
    message = ConversationMessage(
        id=MessageId("message-1"),
        workspace_id=workspace_id,
        author_kind=MessageAuthorKind.USER,
        message_kind=MessageKind.TEXT,
        body="@产品经理 梳理首次使用路径",
        employee_id=None,
        reply_to_message_id=None,
        work_id=None,
        source_event_id=None,
        created_at=datetime.now(UTC),
    )
    execution = ChatExecution.queue(
        ChatExecutionId("chat-execution-1"),
        message.id,
        employee_id,
    )

    with sqlite_uow as uow:
        uow.conversations.add(message, (EmployeeId(employee_id),), (execution,))
        uow.commit()

    with sqlite_uow as uow:
        records = uow.conversations.list_for_workspace(workspace_id)
        stored_execution = uow.conversations.get_execution(execution.id)

    assert len(records) == 1
    assert records[0].message == message
    assert records[0].mention_employee_ids == (EmployeeId(employee_id),)
    assert records[0].executions == (execution,)
    assert stored_execution is not None
    assert stored_execution.execution == execution


def test_database_allows_only_one_task_card_per_work(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_id = _company(sqlite_uow)
    work = WorkService(sqlite_uow, NoopDispatch()).create_direct(
        CreateDirectWork(
            workspace_id=workspace_id,
            employee_id=employee_id,
            objective="整理用户路径",
            acceptance_criteria=("路径完整",),
            command_id="work-command-1",
        )
    ).work

    def card(message_id: str) -> ConversationMessage:
        return ConversationMessage(
            id=MessageId(message_id),
            workspace_id=workspace_id,
            author_kind=MessageAuthorKind.SYSTEM,
            message_kind=MessageKind.WORK_CARD,
            body="正式工作：整理用户路径",
            employee_id=None,
            reply_to_message_id=None,
            work_id=WorkId(work.id),
            source_event_id=None,
            created_at=datetime.now(UTC),
        )

    with sqlite_uow as uow:
        uow.conversations.add(card("message-card-1"), (), ())
        uow.commit()

    with pytest.raises(IntegrityError):
        with sqlite_uow as uow:
            uow.conversations.add(card("message-card-2"), (), ())
            uow.commit()
