import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CompanyEventId,
    WorkNodeId,
    new_id,
)
from dsh_company.domain.work import (
    ArtifactReference,
    CompanyEvent,
    ExecutionLink,
    ExecutionStatus,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
)
from dsh_company.dsh_gateway.contracts import (
    DshGateway,
    EmployeeRuntimeSnapshot,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.control_requests import ControlRequest
from dsh_company.dsh_gateway.events import ProjectedDshEvent

from .ports import IdFactory, UnitOfWorkFactory, WorkAggregate

_LOGGER = logging.getLogger(__name__)


class RuntimeControlDenied(Exception):
    def __init__(self, diagnostic_code: str) -> None:
        super().__init__(diagnostic_code)
        self.diagnostic_code = diagnostic_code


class RuntimeGovernancePort(Protocol):
    def handle(
        self, source_node_id: WorkNodeId, request: ControlRequest
    ) -> tuple[WorkNodeId, ...]: ...

    def child_completed(
        self,
        target_node_id: WorkNodeId,
        artifact_reference_id: ArtifactReferenceId,
    ) -> tuple[WorkNodeId, ...]: ...


class RuntimeCoordinator:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        gateway: DshGateway,
        *,
        governance_handler: RuntimeGovernancePort | None = None,
        id_factory: IdFactory = new_id,
        runtime_concurrency: int = 4,
    ) -> None:
        if runtime_concurrency < 1:
            raise ValueError("runtime concurrency must be positive")
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._governance_handler = governance_handler
        self._id_factory = id_factory
        self._executor = ThreadPoolExecutor(
            max_workers=runtime_concurrency,
            thread_name_prefix="dsh-company-runtime",
        )
        self._lifecycle_lock = Lock()
        self._shutdown_lock = Lock()
        self._accepting = True
        self._started = False
        self._shutdown_started = False
        self._node_locks_lock = Lock()
        self._node_locks: dict[WorkNodeId, Lock] = {}

    def enqueue(self, node_id: WorkNodeId) -> None:
        with self._lifecycle_lock:
            if not self._accepting:
                raise RuntimeError("runtime coordinator is shutting down")
            self._executor.submit(self.dispatch, node_id)

    def dispatch(self, node_id: WorkNodeId) -> None:
        node_lock = self._node_lock(node_id)
        with self._lifecycle_lock:
            if not self._accepting:
                return
            with node_lock:
                prepared = self._mark_running(node_id)
        if prepared is None:
            return
        aggregate, submission = prepared
        highest_event_sequence = 0

        def on_event(projected: ProjectedDshEvent) -> None:
            nonlocal highest_event_sequence
            highest_event_sequence = max(
                highest_event_sequence, projected.source_sequence
            )
            self._append_gateway_event(aggregate, node_id, projected)

        try:
            result = self._gateway.submit(submission, on_event=on_event)
        except Exception:
            _LOGGER.exception("DSH work attempt failed")
            with node_lock:
                self._fail_if_running(
                    node_id,
                    submission.attempt_id,
                    source_sequence=highest_event_sequence + 1,
                )
            return

        enqueue_node_ids: tuple[WorkNodeId, ...] = ()
        with node_lock:
            source_sequence = max(result.event_count, highest_event_sequence) + 1
            if result.control_request is not None:
                enqueue_node_ids = self._handle_control_request(
                    node_id,
                    submission.attempt_id,
                    result.control_request,
                    source_sequence=source_sequence,
                )
            elif result.finish_reason == "completed" and result.reference_uri is not None:
                artifact_id = self._complete_if_running(
                    node_id,
                    submission.attempt_id,
                    reference_uri=result.reference_uri,
                    source_sequence=source_sequence,
                )
                if artifact_id is not None and self._governance_handler is not None:
                    enqueue_node_ids = self._governance_handler.child_completed(
                        node_id, artifact_id
                    )
            else:
                self._fail_if_running(
                    node_id,
                    submission.attempt_id,
                    source_sequence=source_sequence,
                )
        for queued_node_id in enqueue_node_ids:
            self.enqueue(queued_node_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        node_lock = self._node_lock(node_id)
        with node_lock:
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                node = self._node(aggregate, node_id)
                if node.status in {
                    WorkNodeStatus.BLOCKED,
                    WorkNodeStatus.COMPLETED,
                    WorkNodeStatus.FAILED,
                    WorkNodeStatus.CANCELLED,
                }:
                    return
                link = self._current_link(aggregate, node)
                if link.status in {
                    ExecutionStatus.BLOCKED,
                    ExecutionStatus.COMPLETED,
                    ExecutionStatus.FAILED,
                    ExecutionStatus.CANCELLED,
                }:
                    return
                if link.status is ExecutionStatus.CANCEL_REQUESTED:
                    requested = link
                else:
                    requested = link.request_cancel()
                    uow.works.update(
                        replace(
                            aggregate,
                            execution_links=self._replace_link(
                                aggregate, requested
                            ),
                        )
                    )
                    uow.commit()
                attempt_id = requested.attempt_id
                pending_without_runtime = (
                    node.status is WorkNodeStatus.READY
                )

            if pending_without_runtime:
                with self._uow_factory() as uow:
                    aggregate = self._require_node(
                        uow.works.get_for_node(node_id), node_id
                    )
                    node = self._node(aggregate, node_id)
                    link = self._current_link(aggregate, node)
                    if link.status is not ExecutionStatus.CANCEL_REQUESTED:
                        return
                    updated = replace(
                        aggregate,
                        work=aggregate.work.block_before_start(),
                        nodes=self._replace_node(
                            aggregate,
                            node.block_before_start("cancel_unconfirmed"),
                        ),
                        execution_links=self._replace_link(
                            aggregate,
                            link.block(attempt_id, "cancel_unconfirmed"),
                        ),
                    )
                    uow.works.update(updated)
                    uow.commit()
                return

        try:
            result = self._gateway.cancel(attempt_id)
            runtime_closed = result.runtime_closed
        except Exception:
            _LOGGER.exception("DSH work cancellation could not be confirmed")
            runtime_closed = False

        with node_lock:
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                node = self._node(aggregate, node_id)
                link = self._current_link(aggregate, node)
                if link.status is not ExecutionStatus.CANCEL_REQUESTED:
                    return
                if runtime_closed:
                    updated = replace(
                        aggregate,
                        work=aggregate.work.cancel(),
                        nodes=self._replace_node(
                            aggregate, node.cancel(attempt_id)
                        ),
                        execution_links=self._replace_link(
                            aggregate, link.confirm_cancelled()
                        ),
                    )
                else:
                    updated = replace(
                        aggregate,
                        work=aggregate.work.block(),
                        nodes=self._replace_node(
                            aggregate,
                            node.block(attempt_id, "cancel_unconfirmed"),
                        ),
                        execution_links=self._replace_link(
                            aggregate,
                            link.block(attempt_id, "cancel_unconfirmed"),
                        ),
                    )
                uow.works.update(updated)
                uow.commit()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            if not self._accepting:
                raise RuntimeError("runtime coordinator is shutting down")
            self._started = True

        with self._uow_factory() as uow:
            running_node_ids = tuple(
                link.node_id
                for aggregate in uow.works.list_running()
                for link in aggregate.execution_links
                if link.status is ExecutionStatus.RUNNING
            )
        for node_id in running_node_ids:
            self._block_runtime_process_lost(node_id)

        with self._uow_factory() as uow:
            pending_node_ids = tuple(
                link.node_id
                for aggregate in uow.works.list_dispatch_pending()
                for link in aggregate.execution_links
                if link.status is ExecutionStatus.DISPATCH_PENDING
            )
        for node_id in pending_node_ids:
            self.enqueue(node_id)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._shutdown_lock:
            with self._lifecycle_lock:
                if not self._shutdown_started:
                    self._shutdown_started = True
                    self._accepting = False
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    close_gateway = True
                else:
                    close_gateway = False
            try:
                if close_gateway:
                    self._gateway.shutdown()
            finally:
                self._executor.shutdown(wait=wait, cancel_futures=True)

    def _mark_running(
        self, node_id: WorkNodeId
    ) -> tuple[WorkAggregate, GatewaySubmission] | None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            node = self._node(aggregate, node_id)
            if node.status is not WorkNodeStatus.READY:
                return None
            link = self._pending_link(aggregate, node_id)
            employee = uow.employees.get_revision(
                node.assigned_employee_id, node.employee_revision_id
            )
            if employee is None:
                raise RuntimeError("frozen employee revision not found")
            running_link = link.mark_running()
            running_work = (
                aggregate.work.start()
                if aggregate.work.status is WorkStatus.QUEUED
                else aggregate.work
            )
            running = replace(
                aggregate,
                work=running_work,
                nodes=self._replace_node(aggregate, node.start(link.attempt_id)),
                execution_links=self._replace_link(aggregate, running_link),
            )
            uow.works.update(running)
            uow.commit()

        submission = GatewaySubmission(
            attempt_id=link.attempt_id,
            command_id=link.command_id,
            employee=EmployeeRuntimeSnapshot(
                employee_id=employee.employee.id,
                employee_revision_id=employee.revision.id,
                responsibility=employee.revision.responsibility,
                runtime_profile=employee.revision.runtime_profile,
                model=employee.revision.model,
                dsh_session_id=employee.binding.dsh_session_id,
            ),
            objective=node.objective,
            acceptance_criteria=node.acceptance_criteria,
        )
        return running, submission

    def _append_gateway_event(
        self,
        aggregate: WorkAggregate,
        node_id: WorkNodeId,
        projected: ProjectedDshEvent,
    ) -> None:
        link = self._link_for_attempt(aggregate, node_id, projected.attempt_id)
        if projected.attempt_id != link.attempt_id:
            raise ValueError("gateway event attempt does not match execution link")
        with self._uow_factory() as uow:
            uow.company_events.append(
                CompanyEvent(
                    id=CompanyEventId(self._id_factory("company-event")),
                    workspace_id=aggregate.work.workspace_id,
                    work_id=aggregate.work.id,
                    node_id=node_id,
                    attempt_id=link.attempt_id,
                    source_sequence=projected.source_sequence,
                    event_type=projected.event_type,
                    summary=projected.event_type,
                    source="dsh",
                    observed_at=datetime.now(UTC),
                )
            )
            uow.commit()

    def _complete_if_running(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        *,
        reference_uri: str,
        source_sequence: int,
    ) -> ArtifactReferenceId | None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            node = self._node(aggregate, node_id)
            link = self._link_for_attempt(aggregate, node_id, attempt_id)
            if link.status is not ExecutionStatus.RUNNING:
                return None
            artifact_id = ArtifactReferenceId(self._id_factory("artifact-reference"))
            artifact = ArtifactReference(
                id=artifact_id,
                workspace_id=aggregate.work.workspace_id,
                kind="dsh_session_result",
                uri=reference_uri,
                source_session_id=link.dsh_session_id,
                source_attempt_id=attempt_id,
                created_at=datetime.now(UTC),
            )
            completed_node = node.complete(attempt_id, artifact_id)
            completed_nodes = self._replace_node(aggregate, completed_node)
            work_completed = all(
                item.status is WorkNodeStatus.COMPLETED for item in completed_nodes
            )
            completed = replace(
                aggregate,
                work=(
                    aggregate.work.complete()
                    if work_completed
                    else aggregate.work
                ),
                nodes=completed_nodes,
                execution_links=self._replace_link(
                    aggregate, link.complete(attempt_id, artifact_id)
                ),
                artifacts=(*aggregate.artifacts, artifact),
            )
            uow.works.update(completed)
            uow.company_events.append(
                self._terminal_event(
                    completed,
                    attempt_id,
                    source_sequence,
                    node_id=node_id,
                    event_type=("work.completed" if work_completed else "node.completed"),
                    summary=("Work completed" if work_completed else "Node completed"),
                )
            )
            uow.commit()
        return artifact_id

    def _handle_control_request(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        request: ControlRequest,
        *,
        source_sequence: int,
    ) -> tuple[WorkNodeId, ...]:
        if self._governance_handler is None:
            self._block_control_request(
                node_id,
                attempt_id,
                "control_request_unhandled",
                source_sequence=source_sequence,
            )
            return ()
        try:
            return self._governance_handler.handle(node_id, request)
        except RuntimeControlDenied as denied:
            self._block_control_request(
                node_id,
                attempt_id,
                denied.diagnostic_code,
                source_sequence=source_sequence,
            )
            return ()
        except Exception:
            _LOGGER.exception("Company control request handling failed")
            self._fail_if_running(
                node_id,
                attempt_id,
                source_sequence=source_sequence,
            )
            return ()

    def _block_control_request(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        diagnostic_code: str,
        *,
        source_sequence: int,
    ) -> None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            node = self._node(aggregate, node_id)
            link = self._link_for_attempt(aggregate, node_id, attempt_id)
            if link.status is not ExecutionStatus.RUNNING:
                return
            blocked = replace(
                aggregate,
                work=aggregate.work.block(),
                nodes=self._replace_node(
                    aggregate, node.block(attempt_id, diagnostic_code)
                ),
                execution_links=self._replace_link(
                    aggregate, link.block(attempt_id, diagnostic_code)
                ),
            )
            uow.works.update(blocked)
            uow.company_events.append(
                self._terminal_event(
                    blocked,
                    attempt_id,
                    source_sequence,
                    node_id=node_id,
                    event_type="control_request.rejected",
                    summary=f"Control request rejected: {diagnostic_code}",
                )
            )
            uow.commit()

    def _fail_if_running(
        self, node_id: WorkNodeId, attempt_id: AttemptId, *, source_sequence: int
    ) -> None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            node = self._node(aggregate, node_id)
            link = self._link_for_attempt(aggregate, node_id, attempt_id)
            if link.status is not ExecutionStatus.RUNNING:
                return
            failed = replace(
                aggregate,
                work=aggregate.work.fail(),
                nodes=self._replace_node(
                    aggregate, node.fail(attempt_id, "gateway_error")
                ),
                execution_links=self._replace_link(
                    aggregate, link.fail(attempt_id, "gateway_error")
                ),
            )
            uow.works.update(failed)
            uow.company_events.append(
                self._terminal_event(
                    failed,
                    attempt_id,
                    source_sequence,
                    node_id=node_id,
                    event_type="work.failed",
                    summary="Work failed",
                )
            )
            uow.commit()

    def _block_runtime_process_lost(self, node_id: WorkNodeId) -> None:
        with self._node_lock(node_id):
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                node = self._node(aggregate, node_id)
                link = self._current_link(aggregate, node)
                if link.status is not ExecutionStatus.RUNNING:
                    return
                blocked = replace(
                    aggregate,
                    work=aggregate.work.block(),
                    nodes=self._replace_node(
                        aggregate,
                        node.block(link.attempt_id, "runtime_process_lost"),
                    ),
                    execution_links=self._replace_link(
                        aggregate,
                        link.block(link.attempt_id, "runtime_process_lost"),
                    ),
                )
                uow.works.update(blocked)
                uow.commit()

    def _terminal_event(
        self,
        aggregate: WorkAggregate,
        attempt_id: AttemptId,
        source_sequence: int,
        *,
        node_id: WorkNodeId,
        event_type: str,
        summary: str,
    ) -> CompanyEvent:
        return CompanyEvent(
            id=CompanyEventId(self._id_factory("company-event")),
            workspace_id=aggregate.work.workspace_id,
            work_id=aggregate.work.id,
            node_id=node_id,
            attempt_id=attempt_id,
            source_sequence=source_sequence,
            event_type=event_type,
            summary=summary,
            source="company",
            observed_at=datetime.now(UTC),
        )

    def _node_lock(self, node_id: WorkNodeId) -> Lock:
        with self._node_locks_lock:
            return self._node_locks.setdefault(node_id, Lock())

    @staticmethod
    def _require_node(
        aggregate: WorkAggregate | None, node_id: WorkNodeId
    ) -> WorkAggregate:
        if aggregate is None:
            raise LookupError(f"work node not found: {node_id}")
        return aggregate

    @staticmethod
    def _node(aggregate: WorkAggregate, node_id: WorkNodeId) -> WorkNode:
        matches = tuple(node for node in aggregate.nodes if node.id == node_id)
        if len(matches) != 1:
            raise LookupError(f"work node not found: {node_id}")
        return matches[0]

    @staticmethod
    def _pending_link(
        aggregate: WorkAggregate, node_id: WorkNodeId
    ) -> ExecutionLink:
        matches = tuple(
            link
            for link in aggregate.execution_links
            if link.node_id == node_id
            and link.status is ExecutionStatus.DISPATCH_PENDING
        )
        if len(matches) != 1:
            raise RuntimeError("work node requires exactly one pending execution link")
        return matches[0]

    @staticmethod
    def _link_for_attempt(
        aggregate: WorkAggregate, node_id: WorkNodeId, attempt_id: AttemptId
    ) -> ExecutionLink:
        matches = tuple(
            link
            for link in aggregate.execution_links
            if link.node_id == node_id and link.attempt_id == attempt_id
        )
        if len(matches) != 1:
            raise RuntimeError("work node attempt requires exactly one execution link")
        return matches[0]

    @classmethod
    def _current_link(
        cls, aggregate: WorkAggregate, node: WorkNode
    ) -> ExecutionLink:
        if node.active_attempt_id is not None:
            return cls._link_for_attempt(
                aggregate, node.id, node.active_attempt_id
            )
        matches = tuple(
            link
            for link in aggregate.execution_links
            if link.node_id == node.id
            and link.status
            in {ExecutionStatus.DISPATCH_PENDING, ExecutionStatus.CANCEL_REQUESTED}
        )
        if len(matches) != 1:
            raise RuntimeError("work node requires exactly one current execution link")
        return matches[0]

    @staticmethod
    def _replace_node(
        aggregate: WorkAggregate, replacement: WorkNode
    ) -> tuple[WorkNode, ...]:
        return tuple(
            replacement if node.id == replacement.id else node
            for node in aggregate.nodes
        )

    @staticmethod
    def _replace_link(
        aggregate: WorkAggregate, replacement: ExecutionLink
    ) -> tuple[ExecutionLink, ...]:
        return tuple(
            replacement if link.id == replacement.id else link
            for link in aggregate.execution_links
        )
