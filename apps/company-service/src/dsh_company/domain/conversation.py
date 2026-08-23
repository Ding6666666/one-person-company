from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from .ids import (
    ChatExecutionId,
    EmployeeId,
    MessageId,
    WorkId,
    WorkspaceId,
)


class MessageAuthorKind(StrEnum):
    USER = "user"
    EMPLOYEE = "employee"
    SYSTEM = "system"


class MessageKind(StrEnum):
    TEXT = "text"
    WORK_CARD = "work_card"
    WORK_EVENT = "work_event"


class ChatExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: MessageId
    workspace_id: WorkspaceId
    author_kind: MessageAuthorKind
    message_kind: MessageKind
    body: str
    employee_id: EmployeeId | None
    reply_to_message_id: MessageId | None
    work_id: WorkId | None
    source_event_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        normalized_body = self.body.strip()
        if not normalized_body:
            raise ValueError("message body must not be blank")
        if self.author_kind is MessageAuthorKind.EMPLOYEE and self.employee_id is None:
            raise ValueError("employee author requires an employee ID")
        if self.author_kind is not MessageAuthorKind.EMPLOYEE and self.employee_id is not None:
            raise ValueError("only an employee author may have an employee ID")
        object.__setattr__(self, "body", normalized_body)


@dataclass(frozen=True, slots=True)
class ChatExecution:
    id: ChatExecutionId
    message_id: MessageId
    employee_id: EmployeeId
    status: ChatExecutionStatus
    failure_code: str | None
    retry_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def queue(
        cls,
        execution_id: ChatExecutionId,
        message_id: MessageId,
        employee_id: EmployeeId,
    ) -> "ChatExecution":
        now = datetime.now(UTC)
        return cls(
            id=execution_id,
            message_id=message_id,
            employee_id=employee_id,
            status=ChatExecutionStatus.QUEUED,
            failure_code=None,
            retry_count=0,
            created_at=now,
            updated_at=now,
        )

    def start(self) -> "ChatExecution":
        if self.status is not ChatExecutionStatus.QUEUED:
            raise ValueError(f"{self.status.value} execution cannot start")
        return replace(
            self,
            status=ChatExecutionStatus.RUNNING,
            failure_code=None,
            updated_at=datetime.now(UTC),
        )

    def complete(self) -> "ChatExecution":
        if self.status is not ChatExecutionStatus.RUNNING:
            raise ValueError(f"{self.status.value} execution cannot complete")
        return replace(
            self,
            status=ChatExecutionStatus.COMPLETED,
            failure_code=None,
            updated_at=datetime.now(UTC),
        )

    def fail(self, failure_code: str) -> "ChatExecution":
        if self.status not in {ChatExecutionStatus.QUEUED, ChatExecutionStatus.RUNNING}:
            raise ValueError(f"{self.status.value} execution cannot fail")
        normalized_code = failure_code.strip()
        if not normalized_code:
            raise ValueError("failure code must not be blank")
        return replace(
            self,
            status=ChatExecutionStatus.FAILED,
            failure_code=normalized_code,
            updated_at=datetime.now(UTC),
        )

    def retry(self) -> "ChatExecution":
        if self.status is not ChatExecutionStatus.FAILED:
            raise ValueError(f"{self.status.value} execution cannot retry")
        return replace(
            self,
            status=ChatExecutionStatus.QUEUED,
            failure_code=None,
            retry_count=self.retry_count + 1,
            updated_at=datetime.now(UTC),
        )
