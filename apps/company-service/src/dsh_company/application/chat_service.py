from dataclasses import dataclass
from datetime import UTC, datetime

from dsh_company.domain.conversation import (
    ChatExecution,
    ConversationMessage,
    MessageAuthorKind,
    MessageKind,
)
from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import (
    ChatExecutionId,
    MessageId,
    WorkId,
    WorkspaceId,
    new_id,
)

from .chat_commands import SendChatMessage
from .ports import (
    ChatDispatchQueue,
    ChatUnitOfWork,
    ConversationRecord,
    IdFactory,
)


@dataclass(frozen=True, slots=True)
class WorkCardSummary:
    id: WorkId
    objective: str
    status: str
    strategy: str
    employee_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatMessageView:
    record: ConversationRecord
    work_card: WorkCardSummary | None

    @property
    def message(self) -> ConversationMessage:
        return self.record.message

    @property
    def mention_employee_ids(self) -> tuple:
        return self.record.mention_employee_ids

    @property
    def executions(self) -> tuple[ChatExecution, ...]:
        return self.record.executions


class ChatService:
    def __init__(
        self,
        uow: ChatUnitOfWork,
        dispatch_queue: ChatDispatchQueue,
        *,
        id_factory: IdFactory = new_id,
    ) -> None:
        self._uow = uow
        self._dispatch_queue = dispatch_queue
        self._id_factory = id_factory

    def send(self, command: SendChatMessage) -> ChatMessageView:
        queued_ids: list[ChatExecutionId] = []
        with self._uow as uow:
            if uow.workspaces.get(command.workspace_id) is None:
                raise LookupError("workspace not found")
            if command.work_id is not None:
                work = uow.works.get(command.work_id)
                if work is None or work.work.workspace_id != command.workspace_id:
                    raise LookupError("work not found in workspace")

            message = ConversationMessage(
                id=MessageId(self._id_factory("message")),
                workspace_id=command.workspace_id,
                author_kind=MessageAuthorKind.USER,
                message_kind=MessageKind.TEXT,
                body=command.body,
                employee_id=None,
                reply_to_message_id=None,
                work_id=command.work_id,
                source_event_id=None,
                created_at=datetime.now(UTC),
            )
            executions: list[ChatExecution] = []
            for employee_id in command.mention_employee_ids:
                execution = ChatExecution.queue(
                    ChatExecutionId(self._id_factory("chat-execution")),
                    message.id,
                    employee_id,
                )
                employee = uow.employees.get(employee_id)
                if (
                    employee is None
                    or employee.employee.workspace_id != command.workspace_id
                    or employee.employee.status is not EmployeeStatus.ACTIVE
                ):
                    execution = execution.fail("employee_unavailable")
                elif not any(
                    grant.action == "conversation.respond" for grant in employee.grants
                ):
                    execution = execution.fail("conversation_permission_missing")
                else:
                    queued_ids.append(execution.id)
                executions.append(execution)

            uow.conversations.add(
                message,
                command.mention_employee_ids,
                tuple(executions),
            )
            uow.commit()
            created = uow.conversations.get_message(message.id)
            view = None if created is None else self._view(uow, created)
        if created is None:
            raise RuntimeError("chat message was not persisted")
        for execution_id in queued_ids:
            self._dispatch_queue.enqueue_chat(execution_id)
        if view is None:
            raise RuntimeError("chat message view was not created")
        return view

    def list_messages(
        self,
        workspace_id: WorkspaceId,
        *,
        work_id: WorkId | None = None,
    ) -> tuple[ChatMessageView, ...]:
        with self._uow as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            if work_id is not None:
                work = uow.works.get(work_id)
                if work is None or work.work.workspace_id != workspace_id:
                    raise LookupError("work not found in workspace")
                self._project_work_events(uow, workspace_id, work_id)
            return tuple(
                self._view(uow, record)
                for record in uow.conversations.list_for_workspace(workspace_id, work_id)
            )

    def ensure_work_card(self, work_id: WorkId) -> ChatMessageView:
        with self._uow as uow:
            aggregate = uow.works.get(work_id)
            if aggregate is None:
                raise LookupError("work not found")
            existing = next(
                (
                    record
                    for record in uow.conversations.list_for_workspace(
                        aggregate.work.workspace_id
                    )
                    if record.message.message_kind is MessageKind.WORK_CARD
                    and record.message.work_id == work_id
                ),
                None,
            )
            if existing is None:
                message = ConversationMessage(
                    id=MessageId(self._id_factory("message")),
                    workspace_id=aggregate.work.workspace_id,
                    author_kind=MessageAuthorKind.SYSTEM,
                    message_kind=MessageKind.WORK_CARD,
                    body=aggregate.work.objective,
                    employee_id=None,
                    reply_to_message_id=None,
                    work_id=work_id,
                    source_event_id=None,
                    created_at=datetime.now(UTC),
                )
                uow.conversations.add(message, (), ())
                uow.commit()
                existing = uow.conversations.get_message(message.id)
            if existing is None:
                raise RuntimeError("work card was not persisted")
            return self._view(uow, existing)

    def retry(self, execution_id: ChatExecutionId) -> ChatExecution:
        with self._uow as uow:
            record = uow.conversations.get_execution(execution_id)
            if record is None:
                raise LookupError("chat execution not found")
            retried = record.execution.retry()
            uow.conversations.update_execution(retried)
            uow.commit()
        self._dispatch_queue.enqueue_chat(retried.id)
        return retried

    def _project_work_events(
        self,
        uow: ChatUnitOfWork,
        workspace_id: WorkspaceId,
        work_id: WorkId,
    ) -> None:
        supported = {
            "work.started",
            "approval.requested",
            "work.completed",
            "work.failed",
        }
        existing_event_ids = {
            record.message.source_event_id
            for record in uow.conversations.list_for_workspace(workspace_id, work_id)
            if record.message.source_event_id is not None
        }
        added = False
        for event in uow.company_events.list_for_work(work_id):
            if event.event_type not in supported or event.id in existing_event_ids:
                continue
            uow.conversations.add(
                ConversationMessage(
                    id=MessageId(self._id_factory("message")),
                    workspace_id=workspace_id,
                    author_kind=MessageAuthorKind.SYSTEM,
                    message_kind=MessageKind.WORK_EVENT,
                    body=event.summary,
                    employee_id=None,
                    reply_to_message_id=None,
                    work_id=work_id,
                    source_event_id=str(event.id),
                    created_at=event.observed_at,
                ),
                (),
                (),
            )
            existing_event_ids.add(str(event.id))
            added = True
        if added:
            uow.commit()

    @staticmethod
    def _view(uow: ChatUnitOfWork, record: ConversationRecord) -> ChatMessageView:
        work_card = None
        if (
            record.message.message_kind is MessageKind.WORK_CARD
            and record.message.work_id is not None
        ):
            aggregate = uow.works.get(record.message.work_id)
            if aggregate is not None:
                work_card = WorkCardSummary(
                    id=aggregate.work.id,
                    objective=aggregate.work.objective,
                    status=aggregate.work.status.value,
                    strategy=aggregate.graph.strategy.value,
                    employee_ids=tuple(
                        dict.fromkeys(
                            str(node.assigned_employee_id) for node in aggregate.nodes
                        )
                    ),
                )
        return ChatMessageView(record=record, work_card=work_card)
