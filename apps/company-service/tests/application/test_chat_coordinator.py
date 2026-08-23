from collections.abc import Iterator
from pathlib import Path

import pytest
from dsh_company.application.chat_commands import SendChatMessage
from dsh_company.application.chat_coordinator import ChatCoordinator
from dsh_company.application.chat_service import ChatService
from dsh_company.application.commands import CreateEmployee, CreateWorkspace
from dsh_company.application.company_service import CompanyService
from dsh_company.domain.conversation import ChatExecutionStatus, MessageAuthorKind
from dsh_company.domain.ids import ChatExecutionId, EmployeeId, WorkspaceId
from dsh_company.dsh_gateway.contracts import ChatGatewayResult, ChatGatewaySubmission
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


class RecordingDispatch:
    def __init__(self) -> None:
        self.ids: list[ChatExecutionId] = []

    def enqueue_chat(self, execution_id: ChatExecutionId) -> None:
        self.ids.append(execution_id)


class RecordingChatGateway:
    def __init__(self, *, failing_employee_ids: set[EmployeeId] | None = None) -> None:
        self.submissions: list[ChatGatewaySubmission] = []
        self.failing_employee_ids = failing_employee_ids or set()

    def submit_chat(self, submission: ChatGatewaySubmission) -> ChatGatewayResult:
        self.submissions.append(submission)
        if submission.employee.employee_id in self.failing_employee_ids:
            raise RuntimeError("private provider failure")
        return ChatGatewayResult(
            finish_reason="completed",
            response_text=f"{submission.employee.employee_id} 已完成分析",
        )


@pytest.fixture
def sqlite_uow(tmp_path: Path) -> Iterator[SqlAlchemyUnitOfWork]:
    engine = create_sqlite_engine(tmp_path / "chat-coordinator.db")
    create_tables(engine)
    yield SqlAlchemyUnitOfWork(engine)
    engine.dispose()


def _company(sqlite_uow: SqlAlchemyUnitOfWork) -> tuple[WorkspaceId, tuple[EmployeeId, EmployeeId]]:
    company = CompanyService(sqlite_uow)
    workspace = company.create_workspace(CreateWorkspace(name="Chat company"))
    employee_ids: list[EmployeeId] = []
    for name in ("产品经理", "前端工程师"):
        employee = company.create_employee(
            CreateEmployee(
                workspace_id=workspace.id,
                display_name=name,
                responsibility=f"负责{name}工作",
                system_prompt=f"你是{name}",
                runtime_profile="workspace_read",
                model="deepseek-v4-flash",
                grants=(),
            )
        )
        employee_ids.append(employee.employee.id)
    return workspace.id, (employee_ids[0], employee_ids[1])


def test_coordinator_persists_employee_reply_and_completion(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_ids = _company(sqlite_uow)
    queued = RecordingDispatch()
    service = ChatService(sqlite_uow, queued)
    original = service.send(
        SendChatMessage(
            workspace_id=workspace_id,
            body="@产品经理 分析首次使用路径",
            mention_employee_ids=(EmployeeId(employee_ids[0]),),
        )
    )
    gateway = RecordingChatGateway()
    coordinator = ChatCoordinator(lambda: sqlite_uow, gateway)

    coordinator.dispatch(queued.ids[0])

    messages = service.list_messages(workspace_id)
    refreshed = messages[0].executions[0]
    reply = messages[1].message
    assert refreshed.status is ChatExecutionStatus.COMPLETED
    assert reply.author_kind is MessageAuthorKind.EMPLOYEE
    assert reply.employee_id == EmployeeId(employee_ids[0])
    assert reply.reply_to_message_id == original.message.id
    assert "已完成分析" in reply.body
    assert gateway.submissions[0].employee.dsh_session_id.startswith("employee-")


def test_one_failed_employee_does_not_fail_a_sibling_execution(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_ids = _company(sqlite_uow)
    queued = RecordingDispatch()
    service = ChatService(sqlite_uow, queued)
    service.send(
        SendChatMessage(
            workspace_id=workspace_id,
            body="@产品经理 @前端工程师 一起分析",
            mention_employee_ids=tuple(EmployeeId(item) for item in employee_ids),
        )
    )
    gateway = RecordingChatGateway(
        failing_employee_ids={EmployeeId(employee_ids[0])}
    )
    coordinator = ChatCoordinator(lambda: sqlite_uow, gateway)

    for execution_id in queued.ids:
        coordinator.dispatch(execution_id)

    executions = service.list_messages(workspace_id)[0].executions
    by_employee = {item.employee_id: item for item in executions}
    assert by_employee[EmployeeId(employee_ids[0])].status is ChatExecutionStatus.FAILED
    assert by_employee[EmployeeId(employee_ids[0])].failure_code == "chat_execution_failed"
    assert by_employee[EmployeeId(employee_ids[1])].status is ChatExecutionStatus.COMPLETED


def test_startup_marks_interrupted_execution_failed(
    sqlite_uow: SqlAlchemyUnitOfWork,
) -> None:
    workspace_id, employee_ids = _company(sqlite_uow)
    queued = RecordingDispatch()
    service = ChatService(sqlite_uow, queued)
    original = service.send(
        SendChatMessage(
            workspace_id=workspace_id,
            body="@产品经理 处理中",
            mention_employee_ids=(EmployeeId(employee_ids[0]),),
        )
    )
    with sqlite_uow as uow:
        running = original.executions[0].start()
        uow.conversations.update_execution(running)
        uow.commit()
    coordinator = ChatCoordinator(lambda: sqlite_uow, RecordingChatGateway())

    coordinator.start()
    coordinator.shutdown()

    execution = service.list_messages(workspace_id)[0].executions[0]
    assert execution.status is ChatExecutionStatus.FAILED
    assert execution.failure_code == "runtime_process_lost"
