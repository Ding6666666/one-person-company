import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Condition, Lock
from time import monotonic

from dsh_company.domain.conversation import (
    ChatExecutionStatus,
    ConversationMessage,
    MessageAuthorKind,
    MessageKind,
)
from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import ChatExecutionId, EmployeeId, MessageId, new_id
from dsh_company.dsh_gateway.contracts import (
    ChatContextMessage,
    ChatGateway,
    ChatGatewaySubmission,
    EmployeeRuntimeSnapshot,
)

from .ports import ChatUnitOfWorkFactory, IdFactory

_LOGGER = logging.getLogger(__name__)


class ChatCoordinator:
    def __init__(
        self,
        uow_factory: ChatUnitOfWorkFactory,
        gateway: ChatGateway,
        *,
        id_factory: IdFactory = new_id,
        runtime_concurrency: int = 4,
    ) -> None:
        if runtime_concurrency < 1:
            raise ValueError("runtime concurrency must be positive")
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._id_factory = id_factory
        self._executor = ThreadPoolExecutor(
            max_workers=runtime_concurrency,
            thread_name_prefix="dsh-company-chat",
        )
        self._lifecycle_lock = Lock()
        self._accepting = True
        self._shutdown_started = False
        self._execution_locks_lock = Lock()
        self._execution_locks: dict[ChatExecutionId, Lock] = {}
        self._idle_condition = Condition()
        self._pending_dispatches = 0

    def enqueue_chat(self, execution_id: ChatExecutionId) -> None:
        with self._lifecycle_lock:
            if not self._accepting:
                raise RuntimeError("chat coordinator is shutting down")
            with self._idle_condition:
                self._pending_dispatches += 1
            try:
                future = self._executor.submit(self.dispatch, execution_id)
            except BaseException:
                with self._idle_condition:
                    self._pending_dispatches -= 1
                    self._idle_condition.notify_all()
                raise
            future.add_done_callback(self._dispatch_finished)

    def dispatch(self, execution_id: ChatExecutionId) -> None:
        execution_lock = self._execution_lock(execution_id)
        with execution_lock:
            submission = self._mark_running(execution_id)
        if submission is None:
            return
        try:
            result = self._gateway.submit_chat(submission)
            if result.finish_reason != "completed" or not result.response_text:
                raise RuntimeError("chat execution did not return a completed response")
        except Exception:
            _LOGGER.exception("DSH chat execution failed")
            with execution_lock:
                self._fail_if_running(execution_id, "chat_execution_failed")
            return
        with execution_lock:
            self._complete_if_running(execution_id, result.response_text)

    def start(self) -> None:
        with self._uow_factory() as uow:
            interrupted = uow.conversations.list_by_status(ChatExecutionStatus.RUNNING)
            for record in interrupted:
                uow.conversations.update_execution(
                    record.execution.fail("runtime_process_lost")
                )
            queued = uow.conversations.list_by_status(ChatExecutionStatus.QUEUED)
            uow.commit()
        for record in queued:
            self.enqueue_chat(record.execution.id)

    def wait_for_idle(self, *, timeout_seconds: float) -> bool:
        deadline = monotonic() + timeout_seconds
        with self._idle_condition:
            while self._pending_dispatches:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._idle_condition.wait(timeout=remaining)
            return True

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lifecycle_lock:
            if not self._shutdown_started:
                self._shutdown_started = True
                self._accepting = False
                self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _mark_running(
        self, execution_id: ChatExecutionId
    ) -> ChatGatewaySubmission | None:
        with self._uow_factory() as uow:
            record = uow.conversations.get_execution(execution_id)
            if record is None or record.execution.status is not ChatExecutionStatus.QUEUED:
                return None
            employee = uow.employees.get(record.execution.employee_id)
            if (
                employee is None
                or employee.employee.workspace_id != record.message.workspace_id
                or employee.employee.status is not EmployeeStatus.ACTIVE
            ):
                uow.conversations.update_execution(
                    record.execution.fail("employee_unavailable")
                )
                uow.commit()
                return None
            if not any(
                grant.action == "conversation.respond" for grant in employee.grants
            ):
                uow.conversations.update_execution(
                    record.execution.fail("conversation_permission_missing")
                )
                uow.commit()
                return None
            running = record.execution.start()
            uow.conversations.update_execution(running)
            context_records = uow.conversations.list_for_workspace(
                record.message.workspace_id,
                record.message.work_id,
            )
            context = tuple(
                ChatContextMessage(
                    author=context_record.message.author_kind.value,
                    body=context_record.message.body,
                )
                for context_record in context_records
                if context_record.message.id != record.message.id
            )[-12:]
            work_context = None
            if record.message.work_id is not None:
                work = uow.works.get(record.message.work_id)
                if work is not None:
                    work_context = (
                        f"Objective: {work.work.objective}\n"
                        f"Status: {work.work.status.value}"
                    )
            uow.commit()
        return ChatGatewaySubmission(
            execution_id=running.id,
            employee=EmployeeRuntimeSnapshot(
                employee_id=employee.employee.id,
                employee_revision_id=employee.revision.id,
                responsibility=employee.revision.responsibility,
                system_prompt=employee.revision.system_prompt,
                runtime_profile=employee.revision.runtime_profile,
                model=employee.revision.model,
                dsh_session_id=employee.binding.dsh_session_id,
            ),
            instruction=record.message.body,
            context=context,
            work_context=work_context,
        )

    def _complete_if_running(self, execution_id: ChatExecutionId, response: str) -> None:
        with self._uow_factory() as uow:
            record = uow.conversations.get_execution(execution_id)
            if record is None or record.execution.status is not ChatExecutionStatus.RUNNING:
                return
            reply = ConversationMessage(
                id=MessageId(self._id_factory("message")),
                workspace_id=record.message.workspace_id,
                author_kind=MessageAuthorKind.EMPLOYEE,
                message_kind=MessageKind.TEXT,
                body=response,
                employee_id=EmployeeId(record.execution.employee_id),
                reply_to_message_id=record.message.id,
                work_id=record.message.work_id,
                source_event_id=None,
                created_at=datetime.now(UTC),
            )
            uow.conversations.add(reply, (), ())
            uow.conversations.update_execution(record.execution.complete())
            uow.commit()

    def _fail_if_running(self, execution_id: ChatExecutionId, code: str) -> None:
        with self._uow_factory() as uow:
            record = uow.conversations.get_execution(execution_id)
            if record is None or record.execution.status is not ChatExecutionStatus.RUNNING:
                return
            uow.conversations.update_execution(record.execution.fail(code))
            uow.commit()

    def _execution_lock(self, execution_id: ChatExecutionId) -> Lock:
        with self._execution_locks_lock:
            return self._execution_locks.setdefault(execution_id, Lock())

    def _dispatch_finished(self, _future: Future[None]) -> None:
        with self._idle_condition:
            self._pending_dispatches -= 1
            self._idle_condition.notify_all()
