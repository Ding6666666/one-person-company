import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock

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
)
from dsh_company.dsh_gateway.contracts import (
    DshGateway,
    EmployeeRuntimeSnapshot,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.events import ProjectedDshEvent

from .ports import IdFactory, UnitOfWorkFactory, WorkAggregate

_LOGGER = logging.getLogger(__name__)


class RuntimeCoordinator:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        gateway: DshGateway,
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
            thread_name_prefix="dsh-company-runtime",
        )
        self._lifecycle_lock = Lock()
        self._accepting = True
        self._started = False
        self._node_locks_lock = Lock()
        self._node_locks: dict[WorkNodeId, Lock] = {}

    def enqueue(self, node_id: WorkNodeId) -> None:
        with self._lifecycle_lock:
            if not self._accepting:
                raise RuntimeError("runtime coordinator is shutting down")
            self._executor.submit(self.dispatch, node_id)

    def dispatch(self, node_id: WorkNodeId) -> None:
        node_lock = self._node_lock(node_id)
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
            self._append_gateway_event(aggregate, projected)

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

        with node_lock:
            self._complete_if_running(
                node_id,
                submission.attempt_id,
                reference_uri=result.reference_uri,
                source_sequence=max(result.event_count, highest_event_sequence) + 1,
            )

    def request_cancel(self, node_id: WorkNodeId) -> None:
        node_lock = self._node_lock(node_id)
        with node_lock:
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                link = self._single_link(aggregate)
                requested = link.request_cancel()
                uow.works.update(
                    replace(aggregate, execution_links=(requested,))
                )
                uow.commit()
                attempt_id = requested.attempt_id

        try:
            result = self._gateway.cancel(attempt_id)
            runtime_closed = result.runtime_closed
        except Exception:
            _LOGGER.exception("DSH work cancellation could not be confirmed")
            runtime_closed = False

        with node_lock:
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                link = self._single_link(aggregate)
                if link.status is not ExecutionStatus.CANCEL_REQUESTED:
                    return
                node = self._single_node(aggregate)
                if runtime_closed:
                    updated = replace(
                        aggregate,
                        work=aggregate.work.cancel(),
                        nodes=(node.cancel(attempt_id),),
                        execution_links=(link.confirm_cancelled(),),
                    )
                else:
                    updated = replace(
                        aggregate,
                        work=aggregate.work.block(),
                        nodes=(node.block(attempt_id, "cancel_unconfirmed"),),
                        execution_links=(
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
                self._single_node(aggregate).id
                for aggregate in uow.works.list_running()
            )
        for node_id in running_node_ids:
            self._block_runtime_process_lost(node_id)

        with self._uow_factory() as uow:
            pending_node_ids = tuple(
                self._single_node(aggregate).id
                for aggregate in uow.works.list_dispatch_pending()
            )
        for node_id in pending_node_ids:
            self.enqueue(node_id)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lifecycle_lock:
            self._accepting = False
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _mark_running(
        self, node_id: WorkNodeId
    ) -> tuple[WorkAggregate, GatewaySubmission] | None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            link = self._single_link(aggregate)
            if link.status is not ExecutionStatus.DISPATCH_PENDING:
                return None
            node = self._single_node(aggregate)
            employee = uow.employees.get_revision(
                node.assigned_employee_id, node.employee_revision_id
            )
            if employee is None:
                raise RuntimeError("frozen employee revision not found")
            running_link = link.mark_running()
            running = replace(
                aggregate,
                work=aggregate.work.start(),
                nodes=(node.start(link.attempt_id),),
                execution_links=(running_link,),
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
        self, aggregate: WorkAggregate, projected: ProjectedDshEvent
    ) -> None:
        link = self._single_link(aggregate)
        if projected.attempt_id != link.attempt_id:
            raise ValueError("gateway event attempt does not match execution link")
        node = self._single_node(aggregate)
        with self._uow_factory() as uow:
            uow.company_events.append(
                CompanyEvent(
                    id=CompanyEventId(self._id_factory("company-event")),
                    workspace_id=aggregate.work.workspace_id,
                    work_id=aggregate.work.id,
                    node_id=node.id,
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
    ) -> None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            link = self._single_link(aggregate)
            if link.status is not ExecutionStatus.RUNNING:
                return
            node = self._single_node(aggregate)
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
            completed = replace(
                aggregate,
                work=aggregate.work.complete(),
                nodes=(node.complete(attempt_id, artifact_id),),
                execution_links=(link.complete(attempt_id, artifact_id),),
                artifacts=(*aggregate.artifacts, artifact),
            )
            uow.works.update(completed)
            uow.company_events.append(
                self._terminal_event(
                    completed,
                    attempt_id,
                    source_sequence,
                    event_type="work.completed",
                    summary="Work completed",
                )
            )
            uow.commit()

    def _fail_if_running(
        self, node_id: WorkNodeId, attempt_id: AttemptId, *, source_sequence: int
    ) -> None:
        with self._uow_factory() as uow:
            aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
            link = self._single_link(aggregate)
            if link.status is not ExecutionStatus.RUNNING:
                return
            node = self._single_node(aggregate)
            failed = replace(
                aggregate,
                work=aggregate.work.fail(),
                nodes=(node.fail(attempt_id, "gateway_error"),),
                execution_links=(link.fail(attempt_id, "gateway_error"),),
            )
            uow.works.update(failed)
            uow.company_events.append(
                self._terminal_event(
                    failed,
                    attempt_id,
                    source_sequence,
                    event_type="work.failed",
                    summary="Work failed",
                )
            )
            uow.commit()

    def _block_runtime_process_lost(self, node_id: WorkNodeId) -> None:
        with self._node_lock(node_id):
            with self._uow_factory() as uow:
                aggregate = self._require_node(uow.works.get_for_node(node_id), node_id)
                link = self._single_link(aggregate)
                if link.status is not ExecutionStatus.RUNNING:
                    return
                node = self._single_node(aggregate)
                blocked = replace(
                    aggregate,
                    work=aggregate.work.block(),
                    nodes=(
                        node.block(link.attempt_id, "runtime_process_lost"),
                    ),
                    execution_links=(
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
        event_type: str,
        summary: str,
    ) -> CompanyEvent:
        return CompanyEvent(
            id=CompanyEventId(self._id_factory("company-event")),
            workspace_id=aggregate.work.workspace_id,
            work_id=aggregate.work.id,
            node_id=self._single_node(aggregate).id,
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
    def _single_node(aggregate: WorkAggregate) -> WorkNode:
        if len(aggregate.nodes) != 1:
            raise RuntimeError("direct work requires exactly one node")
        return aggregate.nodes[0]

    @staticmethod
    def _single_link(aggregate: WorkAggregate) -> ExecutionLink:
        if len(aggregate.execution_links) != 1:
            raise RuntimeError("direct work requires exactly one execution link")
        return aggregate.execution_links[0]
