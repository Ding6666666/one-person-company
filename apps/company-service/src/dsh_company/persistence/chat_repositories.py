from dataclasses import dataclass
from datetime import UTC, datetime

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
    WorkId,
    WorkspaceId,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .chat_models import ChatExecutionRow, ConversationMentionRow, ConversationMessageRow


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    message: ConversationMessage
    mention_employee_ids: tuple[EmployeeId, ...]
    executions: tuple[ChatExecution, ...]


@dataclass(frozen=True, slots=True)
class ChatExecutionRecord:
    execution: ChatExecution
    message: ConversationMessage


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        message: ConversationMessage,
        mention_employee_ids: tuple[EmployeeId, ...],
        executions: tuple[ChatExecution, ...],
    ) -> None:
        self._session.add(self._message_row(message))
        self._session.flush()
        for employee_id in mention_employee_ids:
            self._session.add(
                ConversationMentionRow(
                    message_id=message.id,
                    employee_id=employee_id,
                )
            )
        for execution in executions:
            self._session.add(self._execution_row(execution))

    def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        work_id: WorkId | None = None,
    ) -> tuple[ConversationRecord, ...]:
        statement = select(ConversationMessageRow).where(
            ConversationMessageRow.workspace_id == workspace_id
        )
        if work_id is None:
            statement = statement.where(
                or_(
                    ConversationMessageRow.work_id.is_(None),
                    ConversationMessageRow.message_kind == MessageKind.WORK_CARD.value,
                )
            )
        else:
            statement = statement.where(ConversationMessageRow.work_id == work_id)
        rows = self._session.scalars(
            statement.order_by(
                ConversationMessageRow.created_at,
                ConversationMessageRow.id,
            )
        ).all()
        return tuple(self._record(row) for row in rows)

    def get_message(self, message_id: MessageId) -> ConversationRecord | None:
        row = self._session.get(ConversationMessageRow, message_id)
        return None if row is None else self._record(row)

    def get_execution(
        self, execution_id: ChatExecutionId
    ) -> ChatExecutionRecord | None:
        row = self._session.get(ChatExecutionRow, execution_id)
        if row is None:
            return None
        message = self._session.get(ConversationMessageRow, row.message_id)
        if message is None:
            raise RuntimeError("chat execution message is missing")
        return ChatExecutionRecord(self._execution(row), self._message(message))

    def update_execution(self, execution: ChatExecution) -> None:
        row = self._session.get(ChatExecutionRow, execution.id)
        if row is None:
            raise LookupError("chat execution not found")
        row.status = execution.status.value
        row.failure_code = execution.failure_code
        row.retry_count = execution.retry_count
        row.updated_at = execution.updated_at

    def list_by_status(
        self, status: ChatExecutionStatus
    ) -> tuple[ChatExecutionRecord, ...]:
        rows = self._session.scalars(
            select(ChatExecutionRow)
            .where(ChatExecutionRow.status == status.value)
            .order_by(ChatExecutionRow.created_at, ChatExecutionRow.id)
        ).all()
        records: list[ChatExecutionRecord] = []
        for row in rows:
            message = self._session.get(ConversationMessageRow, row.message_id)
            if message is None:
                raise RuntimeError("chat execution message is missing")
            records.append(ChatExecutionRecord(self._execution(row), self._message(message)))
        return tuple(records)

    def _record(self, row: ConversationMessageRow) -> ConversationRecord:
        mentions = self._session.scalars(
            select(ConversationMentionRow.employee_id)
            .where(ConversationMentionRow.message_id == row.id)
            .order_by(ConversationMentionRow.employee_id)
        ).all()
        executions = self._session.scalars(
            select(ChatExecutionRow)
            .where(ChatExecutionRow.message_id == row.id)
            .order_by(ChatExecutionRow.created_at, ChatExecutionRow.id)
        ).all()
        return ConversationRecord(
            self._message(row),
            tuple(EmployeeId(employee_id) for employee_id in mentions),
            tuple(self._execution(execution) for execution in executions),
        )

    @staticmethod
    def _message_row(message: ConversationMessage) -> ConversationMessageRow:
        return ConversationMessageRow(
            id=message.id,
            workspace_id=message.workspace_id,
            author_kind=message.author_kind.value,
            message_kind=message.message_kind.value,
            body=message.body,
            employee_id=message.employee_id,
            reply_to_message_id=message.reply_to_message_id,
            work_id=message.work_id,
            source_event_id=message.source_event_id,
            created_at=message.created_at,
        )

    @staticmethod
    def _message(row: ConversationMessageRow) -> ConversationMessage:
        return ConversationMessage(
            id=MessageId(row.id),
            workspace_id=WorkspaceId(row.workspace_id),
            author_kind=MessageAuthorKind(row.author_kind),
            message_kind=MessageKind(row.message_kind),
            body=row.body,
            employee_id=None if row.employee_id is None else EmployeeId(row.employee_id),
            reply_to_message_id=(
                None
                if row.reply_to_message_id is None
                else MessageId(row.reply_to_message_id)
            ),
            work_id=None if row.work_id is None else WorkId(row.work_id),
            source_event_id=row.source_event_id,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _execution_row(execution: ChatExecution) -> ChatExecutionRow:
        return ChatExecutionRow(
            id=execution.id,
            message_id=execution.message_id,
            employee_id=execution.employee_id,
            status=execution.status.value,
            failure_code=execution.failure_code,
            retry_count=execution.retry_count,
            created_at=execution.created_at,
            updated_at=execution.updated_at,
        )

    @staticmethod
    def _execution(row: ChatExecutionRow) -> ChatExecution:
        return ChatExecution(
            id=ChatExecutionId(row.id),
            message_id=MessageId(row.message_id),
            employee_id=EmployeeId(row.employee_id),
            status=ChatExecutionStatus(row.status),
            failure_code=row.failure_code,
            retry_count=row.retry_count,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )
