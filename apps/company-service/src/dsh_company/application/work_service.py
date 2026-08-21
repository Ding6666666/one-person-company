from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import (
    AttemptId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
    new_id,
)
from dsh_company.domain.work import CompanyEvent, ExecutionLink, Work, WorkStrategy

from .ports import (
    DuplicateCommand,
    IdFactory,
    WorkAggregate,
    WorkCoordinator,
    WorkDispatchQueue,
    WorkUnitOfWork,
)
from .work_commands import CreateDirectWork


class WorkService:
    def __init__(
        self,
        uow: WorkUnitOfWork,
        dispatch_queue: WorkDispatchQueue,
        *,
        id_factory: IdFactory = new_id,
    ) -> None:
        self._uow = uow
        self._dispatch_queue = dispatch_queue
        self._id_factory = id_factory

    def create_direct(self, command: CreateDirectWork) -> WorkAggregate:
        normalized_command_id = command.command_id.strip()
        try:
            with self._uow as uow:
                existing = uow.works.get_by_command(
                    command.workspace_id, normalized_command_id
                )
                if existing is not None:
                    return existing

                employee = uow.employees.get(command.employee_id)
                if (
                    employee is None
                    or employee.employee.workspace_id != command.workspace_id
                ):
                    raise LookupError("employee not found in workspace")
                if employee.employee.status is not EmployeeStatus.ACTIVE:
                    raise ValueError("employee must be active")

                work, graph, node = Work.create_direct(
                    work_id=WorkId(self._id_factory("work")),
                    graph_id=WorkGraphRevisionId(self._id_factory("work-graph")),
                    node_id=WorkNodeId(self._id_factory("work-node")),
                    workspace_id=command.workspace_id,
                    employee_id=employee.employee.id,
                    employee_revision_id=employee.revision.id,
                    objective=command.objective,
                    acceptance_criteria=command.acceptance_criteria,
                    command_id=normalized_command_id,
                )
                link = ExecutionLink.dispatch(
                    execution_link_id=ExecutionLinkId(
                        self._id_factory("execution-link")
                    ),
                    attempt_id=AttemptId(self._id_factory("attempt")),
                    node_id=node.id,
                    command_id=normalized_command_id,
                    dsh_session_id=employee.binding.dsh_session_id,
                )
                aggregate = WorkAggregate(work, graph, (node,), (link,), ())
                uow.works.add(aggregate)
                uow.commit()
        except DuplicateCommand:
            with self._uow as uow:
                winner = uow.works.get_by_command(
                    command.workspace_id, normalized_command_id
                )
            if winner is None:
                raise
            return winner

        self._dispatch_queue.enqueue(node.id)
        return aggregate

    def list_for_workspace(
        self, workspace_id: WorkspaceId
    ) -> tuple[WorkAggregate, ...]:
        with self._uow as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            return uow.works.list_for_workspace(workspace_id)

    def get(self, work_id: WorkId) -> WorkAggregate:
        with self._uow as uow:
            aggregate = uow.works.get(work_id)
        if aggregate is None:
            raise LookupError("work not found")
        return aggregate

    def list_events(self, work_id: WorkId) -> tuple[CompanyEvent, ...]:
        with self._uow as uow:
            if uow.works.get(work_id) is None:
                raise LookupError("work not found")
            return uow.company_events.list_for_work(work_id)

    def request_cancel(
        self, work_id: WorkId, coordinator: WorkCoordinator
    ) -> WorkAggregate:
        aggregate = self.get(work_id)
        if aggregate.graph.strategy is not WorkStrategy.DIRECT or len(aggregate.nodes) != 1:
            raise WorkCancellationNotSupported(
                "cancellation is currently supported only for Direct work"
            )
        coordinator.request_cancel(aggregate.nodes[0].id)
        return self.get(work_id)


class WorkCancellationNotSupported(ValueError):
    """The public DSH cancellation boundary cannot cancel an entire Work graph."""
