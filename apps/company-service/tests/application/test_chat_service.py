from collections.abc import Iterator
from pathlib import Path

import pytest
from dsh_company.application.chat_commands import SendChatMessage
from dsh_company.application.chat_service import ChatService
from dsh_company.application.commands import CreateEmployee, CreateWorkspace
from dsh_company.application.company_service import CompanyService
from dsh_company.domain.conversation import ChatExecutionStatus
from dsh_company.domain.ids import ChatExecutionId, EmployeeId, WorkspaceId
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


class RecordingChatDispatch:
    def __init__(self) -> None:
        self.execution_ids: list[ChatExecutionId] = []

    def enqueue_chat(self, execution_id: ChatExecutionId) -> None:
        self.execution_ids.append(execution_id)


class SequentialIds:
    def __init__(self) -> None:
        self.next_value = 0

    def __call__(self, prefix: str) -> str:
        self.next_value += 1
        return f"{prefix}-{self.next_value}"


@pytest.fixture
def sqlite_uow(tmp_path: Path) -> Iterator[SqlAlchemyUnitOfWork]:
    engine = create_sqlite_engine(tmp_path / "chat-service.db")
    create_tables(engine)
    yield SqlAlchemyUnitOfWork(engine)
    engine.dispose()


def _company(sqlite_uow: SqlAlchemyUnitOfWork) -> tuple[WorkspaceId, EmployeeId]:
    company = CompanyService(sqlite_uow)
    workspace = company.create_workspace(CreateWorkspace(name="Chat company"))
    employee = company.create_employee(
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


def test_plain_message_persists_without_execution(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, _employee_id = _company(sqlite_uow)
    dispatch = RecordingChatDispatch()
    service = ChatService(sqlite_uow, dispatch, id_factory=SequentialIds())

    created = service.send(
        SendChatMessage(workspace_id=workspace_id, body="大家早上好", mention_employee_ids=())
    )

    assert created.message.body == "大家早上好"
    assert created.executions == ()
    assert dispatch.execution_ids == []
    assert service.list_messages(workspace_id) == (created,)


def test_valid_and_unknown_mentions_have_independent_states(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_id = _company(sqlite_uow)
    dispatch = RecordingChatDispatch()
    service = ChatService(sqlite_uow, dispatch, id_factory=SequentialIds())

    created = service.send(
        SendChatMessage(
            workspace_id=workspace_id,
            body="@产品经理 @已离职员工 分析首次使用路径",
            mention_employee_ids=(EmployeeId(employee_id), EmployeeId("employee-missing")),
        )
    )

    states = {item.employee_id: item for item in created.executions}
    assert states[EmployeeId(employee_id)].status is ChatExecutionStatus.QUEUED
    assert states[EmployeeId("employee-missing")].status is ChatExecutionStatus.FAILED
    assert states[EmployeeId("employee-missing")].failure_code == "employee_unavailable"
    assert dispatch.execution_ids == [states[EmployeeId(employee_id)].id]


def test_failed_execution_can_be_retried_without_creating_a_message(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, _employee_id = _company(sqlite_uow)
    dispatch = RecordingChatDispatch()
    service = ChatService(sqlite_uow, dispatch, id_factory=SequentialIds())
    created = service.send(
        SendChatMessage(
            workspace_id=workspace_id,
            body="@不存在员工 重试测试",
            mention_employee_ids=(EmployeeId("employee-missing"),),
        )
    )
    failed = created.executions[0]

    retried = service.retry(failed.id)

    assert retried.status is ChatExecutionStatus.QUEUED
    assert retried.retry_count == 1
    assert service.list_messages(workspace_id)[0].message.id == created.message.id
    assert dispatch.execution_ids == [retried.id]


def test_unknown_workspace_is_rejected_without_persisting_a_message(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    service = ChatService(sqlite_uow, RecordingChatDispatch())

    with pytest.raises(LookupError, match="workspace"):
        service.send(
            SendChatMessage(
                workspace_id=WorkspaceId("workspace-missing"),
                body="不会保存",
                mention_employee_ids=(),
            )
        )
