import json
from datetime import UTC, datetime
from typing import Any, Literal, cast

from dsh_company.application.ports import (
    ConcurrentWorkUpdate,
    DuplicateCommand,
    WorkAggregate,
)
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CompanyEventId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ArtifactReference,
    CompanyEvent,
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
    WorkStrategy,
)
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .work_models import (
    ArtifactReferenceRow,
    CompanyEventRow,
    ExecutionLinkRow,
    OrchestrationCapacityRow,
    WorkEdgeRow,
    WorkGraphNodeRow,
    WorkGraphRevisionRow,
    WorkNodeRow,
    WorkRow,
)

_TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.BLOCKED.value,
    ExecutionStatus.CANCELLED.value,
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.FAILED.value,
}


class ConcurrentNodeUpdate(Exception):
    """A node was changed since the caller read its version."""


def _from_sqlite_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _from_sqlite_utc(value)


class WorkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, aggregate: WorkAggregate) -> None:
        work_row = WorkRow(
            id=aggregate.work.id,
            workspace_id=aggregate.work.workspace_id,
            command_id=aggregate.work.command_id,
            objective=aggregate.work.objective,
            status=aggregate.work.status.value,
            current_graph_revision_id=aggregate.work.current_graph_revision_id,
            created_at=aggregate.work.created_at,
        )
        graph_row = WorkGraphRevisionRow(
            id=aggregate.graph.id,
            work_id=aggregate.graph.work_id,
            revision_number=aggregate.graph.revision_number,
            strategy=aggregate.graph.strategy.value,
            created_at=aggregate.graph.created_at,
            work=work_row,
        )
        node_rows = {
            node.id: WorkNodeRow(
                id=node.id,
                graph_revision_id=node.graph_revision_id,
                work_id=node.work_id,
                objective=node.objective,
                acceptance_criteria_json=json.dumps(node.acceptance_criteria, ensure_ascii=False),
                required_actions_json=json.dumps(node.required_actions, ensure_ascii=False),
                resource_values_json=json.dumps(node.resource_values, ensure_ascii=False),
                input_references_json=json.dumps(node.input_references, ensure_ascii=False),
                output_references_json=json.dumps(node.output_references, ensure_ascii=False),
                max_attempts=node.max_attempts,
                attempt_count=node.attempt_count,
                assigned_employee_id=node.assigned_employee_id,
                employee_revision_id=node.employee_revision_id,
                status=node.status.value,
                active_attempt_id=node.active_attempt_id,
                failure_code=node.failure_code,
                version=node.version,
                work=work_row,
                graph_revision=graph_row,
            )
            for node in aggregate.nodes
        }
        graph_node_rows = [
            WorkGraphNodeRow(
                graph_revision_id=graph_row.id,
                node_id=node_id,
                position=position,
            )
            for position, node_id in enumerate(aggregate.graph.node_ids)
        ]
        edge_rows = self._edge_rows(aggregate.graph)
        link_rows = [
            ExecutionLinkRow(
                id=link.id,
                node_id=link.node_id,
                attempt_id=link.attempt_id,
                command_id=link.command_id,
                dsh_session_id=link.dsh_session_id,
                status=link.status.value,
                started_at=link.started_at,
                finished_at=link.finished_at,
                diagnostic_code=link.diagnostic_code,
                node=node_rows[link.node_id],
            )
            for link in aggregate.execution_links
        ]
        artifact_rows = [
            ArtifactReferenceRow(
                id=artifact.id,
                workspace_id=artifact.workspace_id,
                kind=artifact.kind,
                uri=artifact.uri,
                source_session_id=artifact.source_session_id,
                source_attempt_id=artifact.source_attempt_id,
                created_at=artifact.created_at,
            )
            for artifact in aggregate.artifacts
        ]
        self._session.add_all(
            [work_row, graph_row, *node_rows.values(), *link_rows, *artifact_rows]
        )
        try:
            self._session.flush()
            self._session.add_all([*graph_node_rows, *edge_rows])
            self._session.flush()
        except IntegrityError as error:
            if "works.workspace_id, works.command_id" in str(error):
                raise DuplicateCommand(aggregate.work.command_id) from error
            raise

    def get(self, work_id: WorkId) -> WorkAggregate | None:
        work_row = self._session.get(WorkRow, work_id)
        if work_row is None:
            return None
        return self._aggregate(work_row)

    def add_revision(self, graph: WorkGraphRevision, nodes: tuple[WorkNode, ...]) -> None:
        if tuple(node.id for node in nodes) != graph.node_ids:
            raise ValueError("graph node facts must match revision node IDs")
        work_row = self._session.get(WorkRow, graph.work_id)
        if work_row is None:
            raise LookupError("work not found")
        graph_row = WorkGraphRevisionRow(
            id=graph.id,
            work_id=graph.work_id,
            revision_number=graph.revision_number,
            strategy=graph.strategy.value,
            created_at=graph.created_at,
            work=work_row,
        )
        self._session.add(graph_row)
        self._session.flush()
        for node in nodes:
            stored = self._session.get(WorkNodeRow, node.id)
            if stored is None:
                self._session.add(self._node_row(node))
            elif self._node(stored) != node:
                raise ValueError("graph revision cannot rewrite existing node facts")
        self._session.flush()
        self._session.add_all(
            [
                *(
                    WorkGraphNodeRow(
                        graph_revision_id=graph.id,
                        node_id=node_id,
                        position=position,
                    )
                    for position, node_id in enumerate(graph.node_ids)
                ),
                *self._edge_rows(graph),
            ]
        )
        work_row.current_graph_revision_id = graph.id

    def get_revision(
        self, revision_id: WorkGraphRevisionId
    ) -> tuple[WorkGraphRevision, tuple[WorkNode, ...]] | None:
        graph_row = self._session.get(WorkGraphRevisionRow, revision_id)
        if graph_row is None:
            return None
        membership_rows = tuple(
            self._session.scalars(
                select(WorkGraphNodeRow)
                .where(WorkGraphNodeRow.graph_revision_id == revision_id)
                .order_by(WorkGraphNodeRow.position)
            )
        )
        node_rows = tuple(
            self._session.get(WorkNodeRow, membership.node_id) for membership in membership_rows
        )
        if any(row is None for row in node_rows):
            raise RuntimeError("graph revision references a missing node")
        edges = tuple(
            WorkEdge(
                WorkNodeId(row.from_node_id),
                WorkNodeId(row.to_node_id),
                WorkEdgeKind(row.kind),
            )
            for row in self._session.scalars(
                select(WorkEdgeRow)
                .where(WorkEdgeRow.graph_revision_id == revision_id)
                .order_by(WorkEdgeRow.id)
            )
        )
        graph = WorkGraphRevision(
            id=WorkGraphRevisionId(graph_row.id),
            work_id=WorkId(graph_row.work_id),
            revision_number=graph_row.revision_number,
            strategy=WorkStrategy(graph_row.strategy),
            created_at=_from_sqlite_utc(graph_row.created_at),
            node_ids=tuple(WorkNodeId(row.node_id) for row in membership_rows),
            edges=edges,
        )
        return graph, tuple(self._node(cast(WorkNodeRow, row)) for row in node_rows)

    def get_by_command(self, workspace_id: WorkspaceId, command_id: str) -> WorkAggregate | None:
        row = self._session.scalar(
            select(WorkRow).where(
                WorkRow.workspace_id == workspace_id,
                WorkRow.command_id == command_id,
            )
        )
        return None if row is None else self._aggregate(row)

    def get_for_node(self, node_id: WorkNodeId) -> WorkAggregate | None:
        row = self._session.scalar(
            select(WorkRow)
            .join(WorkNodeRow, WorkNodeRow.work_id == WorkRow.id)
            .where(WorkNodeRow.id == node_id)
        )
        return None if row is None else self._aggregate(row)

    def get_for_attempt(self, attempt_id: AttemptId) -> WorkAggregate | None:
        row = self._session.scalar(
            select(WorkRow)
            .join(WorkNodeRow, WorkNodeRow.work_id == WorkRow.id)
            .join(ExecutionLinkRow, ExecutionLinkRow.node_id == WorkNodeRow.id)
            .where(ExecutionLinkRow.attempt_id == attempt_id)
        )
        return None if row is None else self._aggregate(row)

    def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[WorkAggregate, ...]:
        rows = self._session.scalars(
            select(WorkRow)
            .where(WorkRow.workspace_id == workspace_id)
            .order_by(WorkRow.created_at, WorkRow.id)
        )
        return tuple(self._aggregate(row) for row in rows)

    def list_dispatch_pending(self) -> tuple[WorkAggregate, ...]:
        return self._list_for_execution_status(ExecutionStatus.DISPATCH_PENDING)

    def list_running(self) -> tuple[WorkAggregate, ...]:
        return self._list_for_execution_status(ExecutionStatus.RUNNING)

    def count_active_execution_links(self) -> int:
        return int(
            self._session.scalar(
                select(func.count(ExecutionLinkRow.id))
                .where(
                    ExecutionLinkRow.status.in_(
                        (
                            ExecutionStatus.DISPATCH_PENDING.value,
                            ExecutionStatus.RUNNING.value,
                            ExecutionStatus.CANCEL_REQUESTED.value,
                        ),
                    )
                )
            )
            or 0
        )

    def lock_orchestration_capacity(self) -> None:
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(OrchestrationCapacityRow)
                .where(OrchestrationCapacityRow.id == "runtime")
                .values(revision=OrchestrationCapacityRow.revision + 1)
            ),
        )
        if result.rowcount != 1:
            raise RuntimeError("orchestration capacity row is not configured")

    def update(self, aggregate: WorkAggregate) -> None:
        work_result = cast(
            CursorResult[Any],
            self._session.execute(
                update(WorkRow)
                .where(
                    WorkRow.id == aggregate.work.id,
                    WorkRow.current_graph_revision_id == aggregate.graph.id,
                )
                .values(
                    objective=aggregate.work.objective,
                    status=aggregate.work.status.value,
                    current_graph_revision_id=aggregate.work.current_graph_revision_id,
                )
            ),
        )
        if work_result.rowcount == 0:
            raise ConcurrentWorkUpdate(str(aggregate.work.id))

        for node in aggregate.nodes:
            stored_node_row = self._session.get(WorkNodeRow, node.id)
            if stored_node_row is None:
                raise LookupError("work node not found")
            if stored_node_row.version == node.version:
                if self._node(stored_node_row) == node:
                    continue
                raise ConcurrentNodeUpdate(str(node.id))
            result = cast(
                CursorResult[Any],
                self._session.execute(
                    update(WorkNodeRow)
                    .where(
                        WorkNodeRow.id == node.id,
                        WorkNodeRow.version == node.version - 1,
                    )
                    .values(
                        objective=node.objective,
                        acceptance_criteria_json=json.dumps(
                            node.acceptance_criteria, ensure_ascii=False
                        ),
                        required_actions_json=json.dumps(
                            node.required_actions, ensure_ascii=False
                        ),
                        resource_values_json=json.dumps(
                            node.resource_values, ensure_ascii=False
                        ),
                        input_references_json=json.dumps(
                            node.input_references, ensure_ascii=False
                        ),
                        output_references_json=json.dumps(
                            node.output_references, ensure_ascii=False
                        ),
                        max_attempts=node.max_attempts,
                        attempt_count=node.attempt_count,
                        assigned_employee_id=node.assigned_employee_id,
                        employee_revision_id=node.employee_revision_id,
                        status=node.status.value,
                        active_attempt_id=node.active_attempt_id,
                        failure_code=node.failure_code,
                        version=node.version,
                    )
                ),
            )
            if result.rowcount == 0:
                raise ConcurrentNodeUpdate(str(node.id))

        for link in aggregate.execution_links:
            link_row = self._session.get(ExecutionLinkRow, link.id)
            if link_row is None:
                self._session.add(self._link_row(link))
                continue
            if link.status.value not in _TERMINAL_EXECUTION_STATUSES:
                result = cast(
                    CursorResult[Any],
                    self._session.execute(
                        update(ExecutionLinkRow)
                        .where(
                            ExecutionLinkRow.id == link.id,
                            ExecutionLinkRow.status.not_in(
                                _TERMINAL_EXECUTION_STATUSES
                            ),
                        )
                        .values(
                            status=link.status.value,
                            started_at=link.started_at,
                            finished_at=link.finished_at,
                            diagnostic_code=link.diagnostic_code,
                        )
                    ),
                )
                if result.rowcount == 0:
                    continue
            link_row.status = link.status.value
            link_row.started_at = link.started_at
            link_row.finished_at = link.finished_at
            link_row.diagnostic_code = link.diagnostic_code

        for artifact in aggregate.artifacts:
            if self._session.get(ArtifactReferenceRow, artifact.id) is None:
                self._session.add(
                    ArtifactReferenceRow(
                        id=artifact.id,
                        workspace_id=artifact.workspace_id,
                        kind=artifact.kind,
                        uri=artifact.uri,
                        source_session_id=artifact.source_session_id,
                        source_attempt_id=artifact.source_attempt_id,
                        created_at=artifact.created_at,
                    )
                )

    def _list_for_execution_status(self, status: ExecutionStatus) -> tuple[WorkAggregate, ...]:
        rows = self._session.scalars(
            select(WorkRow)
            .join(WorkNodeRow, WorkNodeRow.work_id == WorkRow.id)
            .join(ExecutionLinkRow, ExecutionLinkRow.node_id == WorkNodeRow.id)
            .where(ExecutionLinkRow.status == status.value)
            .distinct()
            .order_by(WorkRow.created_at, WorkRow.id)
        )
        return tuple(self._aggregate(row) for row in rows)

    def _aggregate(self, work_row: WorkRow) -> WorkAggregate:
        revision = self.get_revision(WorkGraphRevisionId(work_row.current_graph_revision_id))
        if revision is None:
            raise RuntimeError("work persistence record has no current graph")
        graph, nodes = revision
        node_rows = tuple(
            cast(WorkNodeRow, self._session.get(WorkNodeRow, node.id)) for node in nodes
        )
        node_ids = [row.id for row in node_rows]
        link_rows = (
            tuple(
                self._session.scalars(
                    select(ExecutionLinkRow)
                    .where(ExecutionLinkRow.node_id.in_(node_ids))
                    .order_by(ExecutionLinkRow.id)
                )
            )
            if node_ids
            else ()
        )
        attempt_ids = [row.attempt_id for row in link_rows]
        artifact_rows = (
            tuple(
                self._session.scalars(
                    select(ArtifactReferenceRow)
                    .where(ArtifactReferenceRow.source_attempt_id.in_(attempt_ids))
                    .order_by(ArtifactReferenceRow.created_at, ArtifactReferenceRow.id)
                )
            )
            if attempt_ids
            else ()
        )
        return WorkAggregate(
            work=Work(
                id=WorkId(work_row.id),
                workspace_id=WorkspaceId(work_row.workspace_id),
                command_id=work_row.command_id,
                objective=work_row.objective,
                status=WorkStatus(work_row.status),
                current_graph_revision_id=WorkGraphRevisionId(work_row.current_graph_revision_id),
                created_at=_from_sqlite_utc(work_row.created_at),
            ),
            graph=graph,
            nodes=nodes,
            execution_links=tuple(self._link(row) for row in link_rows),
            artifacts=tuple(self._artifact(row) for row in artifact_rows),
        )

    @staticmethod
    def _node(row: WorkNodeRow) -> WorkNode:
        return WorkNode(
            id=WorkNodeId(row.id),
            graph_revision_id=WorkGraphRevisionId(row.graph_revision_id),
            work_id=WorkId(row.work_id),
            objective=row.objective,
            acceptance_criteria=tuple(json.loads(row.acceptance_criteria_json)),
            required_actions=tuple(json.loads(row.required_actions_json)),
            resource_values=tuple(json.loads(row.resource_values_json)),
            input_references=tuple(
                ArtifactReferenceId(value)
                for value in json.loads(row.input_references_json)
            ),
            output_references=tuple(
                ArtifactReferenceId(value)
                for value in json.loads(row.output_references_json)
            ),
            max_attempts=row.max_attempts,
            attempt_count=row.attempt_count,
            assigned_employee_id=EmployeeId(row.assigned_employee_id),
            employee_revision_id=EmployeeRevisionId(row.employee_revision_id),
            status=WorkNodeStatus(row.status),
            active_attempt_id=(
                None if row.active_attempt_id is None else AttemptId(row.active_attempt_id)
            ),
            failure_code=row.failure_code,
            version=row.version,
        )

    @staticmethod
    def _node_row(node: WorkNode) -> WorkNodeRow:
        return WorkNodeRow(
            id=node.id,
            graph_revision_id=node.graph_revision_id,
            work_id=node.work_id,
            objective=node.objective,
            acceptance_criteria_json=json.dumps(node.acceptance_criteria, ensure_ascii=False),
            required_actions_json=json.dumps(node.required_actions, ensure_ascii=False),
            resource_values_json=json.dumps(node.resource_values, ensure_ascii=False),
            input_references_json=json.dumps(node.input_references, ensure_ascii=False),
            output_references_json=json.dumps(node.output_references, ensure_ascii=False),
            max_attempts=node.max_attempts,
            attempt_count=node.attempt_count,
            assigned_employee_id=node.assigned_employee_id,
            employee_revision_id=node.employee_revision_id,
            status=node.status.value,
            active_attempt_id=node.active_attempt_id,
            failure_code=node.failure_code,
            version=node.version,
        )

    @staticmethod
    def _edge_rows(graph: WorkGraphRevision) -> list[WorkEdgeRow]:
        return [
            WorkEdgeRow(
                id=f"{graph.id}:edge:{position:08d}",
                graph_revision_id=graph.id,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                kind=edge.kind.value,
            )
            for position, edge in enumerate(graph.edges)
        ]

    @staticmethod
    def _link(row: ExecutionLinkRow) -> ExecutionLink:
        return ExecutionLink(
            id=ExecutionLinkId(row.id),
            node_id=WorkNodeId(row.node_id),
            attempt_id=AttemptId(row.attempt_id),
            command_id=row.command_id,
            dsh_session_id=row.dsh_session_id,
            status=ExecutionStatus(row.status),
            started_at=_optional_utc(row.started_at),
            finished_at=_optional_utc(row.finished_at),
            diagnostic_code=row.diagnostic_code,
        )

    @staticmethod
    def _link_row(link: ExecutionLink) -> ExecutionLinkRow:
        return ExecutionLinkRow(
            id=link.id,
            node_id=link.node_id,
            attempt_id=link.attempt_id,
            command_id=link.command_id,
            dsh_session_id=link.dsh_session_id,
            status=link.status.value,
            started_at=link.started_at,
            finished_at=link.finished_at,
            diagnostic_code=link.diagnostic_code,
        )

    @staticmethod
    def _artifact(row: ArtifactReferenceRow) -> ArtifactReference:
        return ArtifactReference(
            id=ArtifactReferenceId(row.id),
            workspace_id=WorkspaceId(row.workspace_id),
            kind=cast(Literal["dsh_session_result"], row.kind),
            uri=row.uri,
            source_session_id=row.source_session_id,
            source_attempt_id=AttemptId(row.source_attempt_id),
            created_at=_from_sqlite_utc(row.created_at),
        )


class CompanyEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: CompanyEvent) -> None:
        self._session.add(
            CompanyEventRow(
                id=event.id,
                workspace_id=event.workspace_id,
                work_id=event.work_id,
                node_id=event.node_id,
                attempt_id=event.attempt_id,
                source_sequence=event.source_sequence,
                event_type=event.event_type,
                summary=event.summary,
                source=event.source,
                observed_at=event.observed_at,
            )
        )

    def list_for_work(self, work_id: WorkId) -> tuple[CompanyEvent, ...]:
        rows = self._session.scalars(
            select(CompanyEventRow)
            .where(CompanyEventRow.work_id == work_id)
            .order_by(
                CompanyEventRow.observed_at,
                CompanyEventRow.attempt_id,
                CompanyEventRow.source_sequence,
                CompanyEventRow.id,
            )
        )
        return tuple(
            CompanyEvent(
                id=CompanyEventId(row.id),
                workspace_id=WorkspaceId(row.workspace_id),
                work_id=WorkId(row.work_id),
                node_id=None if row.node_id is None else WorkNodeId(row.node_id),
                attempt_id=(None if row.attempt_id is None else AttemptId(row.attempt_id)),
                source_sequence=row.source_sequence,
                event_type=row.event_type,
                summary=row.summary,
                source=row.source,
                observed_at=_from_sqlite_utc(row.observed_at),
            )
            for row in rows
        )
