from datetime import UTC, datetime

import pytest
from dsh_company.domain.conversation import (
    ChatExecution,
    ChatExecutionStatus,
    ConversationMessage,
    MessageAuthorKind,
    MessageKind,
)
from dsh_company.domain.ids import (
    ChatExecutionId,
    EmployeeId,
    MessageId,
    WorkspaceId,
)


def test_employee_execution_moves_from_queued_to_running_to_completed() -> None:
    execution = ChatExecution.queue(
        ChatExecutionId("chat-exec-1"),
        MessageId("message-1"),
        EmployeeId("employee-1"),
    )

    completed = execution.start().complete()

    assert completed.status is ChatExecutionStatus.COMPLETED
    assert completed.failure_code is None
    assert completed.retry_count == 0


def test_failed_execution_can_be_retried() -> None:
    failed = (
        ChatExecution.queue(
            ChatExecutionId("chat-exec-1"),
            MessageId("message-1"),
            EmployeeId("employee-1"),
        )
        .start()
        .fail("session_unavailable")
    )

    retried = failed.retry()

    assert retried.status is ChatExecutionStatus.QUEUED
    assert retried.failure_code is None
    assert retried.retry_count == 1


def test_execution_rejects_an_invalid_transition() -> None:
    execution = ChatExecution.queue(
        ChatExecutionId("chat-exec-1"),
        MessageId("message-1"),
        EmployeeId("employee-1"),
    )

    with pytest.raises(ValueError, match="queued execution cannot complete"):
        execution.complete()


def test_employee_message_requires_an_employee_author() -> None:
    with pytest.raises(ValueError, match="employee author"):
        ConversationMessage(
            id=MessageId("message-1"),
            workspace_id=WorkspaceId("workspace-1"),
            author_kind=MessageAuthorKind.EMPLOYEE,
            message_kind=MessageKind.TEXT,
            body="回复",
            employee_id=None,
            reply_to_message_id=None,
            work_id=None,
            source_event_id=None,
            created_at=datetime.now(UTC),
        )
