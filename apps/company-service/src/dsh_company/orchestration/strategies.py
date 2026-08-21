from dataclasses import dataclass

from dsh_company.application.ports import WorkAggregate
from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import WorkNodeId
from dsh_company.domain.work import (
    Work,
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStrategy,
)

from .graph_validation import GraphValidator, InvalidGraph
from .selector import EligibleEmployee

BATTLE_SUMMARY_INSTRUCTION = "整理共同点、去重并明确列出分歧，不替用户作最终决定"


@dataclass(frozen=True, slots=True)
class StarChild:
    participant: EligibleEmployee
    objective: str
    criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplicitNode:
    key: str
    participant: EligibleEmployee
    objective: str
    criteria: tuple[str, ...]
    max_attempts: int = 1


@dataclass(frozen=True, slots=True)
class ExplicitEdge:
    from_key: str
    to_key: str
    kind: WorkEdgeKind


class StrategyFactory:
    """Build explicit DRAFT graphs; persistence and execution remain external."""

    def __init__(self, validator: GraphValidator | None = None) -> None:
        self._validator = validator or GraphValidator()

    def direct(
        self,
        *,
        work: Work,
        participant: EligibleEmployee,
        objective: str,
        criteria: tuple[str, ...],
    ) -> WorkAggregate:
        self._validate_employee(work, participant)
        node = self._node(
            work,
            WorkNodeId(f"{work.id}:direct"),
            participant,
            objective,
            criteria,
        )
        return self._aggregate(work, WorkStrategy.DIRECT, (node,), ())

    def star(
        self,
        *,
        work: Work,
        coordinator: EligibleEmployee,
        children: tuple[StarChild, ...],
        objective: str,
        criteria: tuple[str, ...],
    ) -> WorkAggregate:
        if not children:
            raise ValueError("star requires at least one explicit child objective")
        self._validate_employee(work, coordinator)
        child_nodes: list[WorkNode] = []
        for index, child in enumerate(children, start=1):
            self._validate_employee(work, child.participant)
            child_nodes.append(
                self._node(
                    work,
                    WorkNodeId(f"{work.id}:star:child-{index}:{child.participant.employee_id}"),
                    child.participant,
                    child.objective,
                    child.criteria,
                )
            )
        summary = self._node(
            work,
            WorkNodeId(f"{work.id}:star:summary:{coordinator.employee_id}"),
            coordinator,
            f"汇总子任务结果：{self._text(objective, 'objective')}",
            criteria,
        )
        edges = tuple(
            WorkEdge(node.id, summary.id, WorkEdgeKind.SUMMARIZES) for node in child_nodes
        )
        return self._aggregate(work, WorkStrategy.STAR, (*child_nodes, summary), edges)

    def graph(
        self,
        *,
        work: Work,
        nodes: tuple[ExplicitNode, ...],
        edges: tuple[ExplicitEdge, ...],
    ) -> WorkAggregate:
        keys = tuple(self._text(spec.key, "node key") for spec in nodes)
        if len(set(keys)) != len(keys):
            raise ValueError("explicit graph node keys must be unique")
        key_to_id = {key: WorkNodeId(f"{work.id}:graph:{key}") for key in keys}
        work_nodes: list[WorkNode] = []
        for key, spec in zip(keys, nodes, strict=True):
            self._validate_employee(work, spec.participant)
            work_nodes.append(
                self._node(
                    work,
                    key_to_id[key],
                    spec.participant,
                    spec.objective,
                    spec.criteria,
                    max_attempts=spec.max_attempts,
                )
            )
        work_edges: list[WorkEdge] = []
        for edge in edges:
            unknown_key = next(
                (key for key in (edge.from_key, edge.to_key) if key not in key_to_id),
                None,
            )
            if unknown_key is not None:
                raise InvalidGraph(f"unknown_edge_endpoint: {unknown_key}")
            work_edges.append(
                WorkEdge(
                    key_to_id[edge.from_key],
                    key_to_id[edge.to_key],
                    edge.kind,
                )
            )
        return self._aggregate(work, WorkStrategy.GRAPH, tuple(work_nodes), tuple(work_edges))

    def battle(
        self,
        *,
        work: Work,
        participants: tuple[EligibleEmployee, ...],
        summarizer: EligibleEmployee,
        objective: str,
        criteria: tuple[str, ...],
    ) -> WorkAggregate:
        participant_ids = tuple(item.employee_id for item in participants)
        if not 2 <= len(participants) <= 4 or len(set(participant_ids)) != len(participants):
            raise ValueError("battle requires 2 to 4 distinct participants")
        if summarizer.employee_id in participant_ids:
            raise ValueError("battle summarizer must be distinct from participants")

        normalized_objective = self._text(objective, "objective")
        participant_nodes: list[WorkNode] = []
        for index, participant in enumerate(participants, start=1):
            self._validate_employee(work, participant)
            participant_nodes.append(
                self._node(
                    work,
                    WorkNodeId(f"{work.id}:battle:participant-{index}:{participant.employee_id}"),
                    participant,
                    normalized_objective,
                    criteria,
                )
            )
        self._validate_employee(work, summarizer)
        summary = self._node(
            work,
            WorkNodeId(f"{work.id}:battle:summary:{summarizer.employee_id}"),
            summarizer,
            f"{normalized_objective}\n{BATTLE_SUMMARY_INSTRUCTION}",
            criteria,
        )
        edges = tuple(
            WorkEdge(node.id, summary.id, WorkEdgeKind.SUMMARIZES) for node in participant_nodes
        )
        return self._aggregate(
            work,
            WorkStrategy.BATTLE,
            (*participant_nodes, summary),
            edges,
        )

    def _aggregate(
        self,
        work: Work,
        strategy: WorkStrategy,
        nodes: tuple[WorkNode, ...],
        edges: tuple[WorkEdge, ...],
    ) -> WorkAggregate:
        graph = WorkGraphRevision(
            id=work.current_graph_revision_id,
            work_id=work.id,
            revision_number=1,
            strategy=strategy,
            created_at=work.created_at,
            node_ids=tuple(node.id for node in nodes),
            edges=edges,
        )
        self._validator.validate(graph, nodes)
        return WorkAggregate(
            work=work,
            graph=graph,
            nodes=nodes,
            execution_links=(),
            artifacts=(),
        )

    @staticmethod
    def _node(
        work: Work,
        node_id: WorkNodeId,
        participant: EligibleEmployee,
        objective: str,
        criteria: tuple[str, ...],
        *,
        max_attempts: int = 1,
    ) -> WorkNode:
        normalized_criteria = tuple(item.strip() for item in criteria if item.strip())
        if not normalized_criteria:
            raise ValueError("at least one acceptance criterion must not be blank")
        return WorkNode(
            id=node_id,
            graph_revision_id=work.current_graph_revision_id,
            work_id=work.id,
            objective=StrategyFactory._text(objective, "objective"),
            acceptance_criteria=normalized_criteria,
            assigned_employee_id=participant.employee_id,
            employee_revision_id=participant.revision.id,
            status=WorkNodeStatus.DRAFT,
            active_attempt_id=None,
            failure_code=None,
            version=1,
            required_actions=participant.required_actions,
            resource_values=participant.resource_values,
            max_attempts=max_attempts,
        )

    @staticmethod
    def _validate_employee(work: Work, participant: EligibleEmployee) -> None:
        if participant.employee.workspace_id != work.workspace_id:
            raise ValueError("employee selection must belong to the work workspace")
        if participant.employee.status is not EmployeeStatus.ACTIVE:
            raise ValueError("employee selection must be active")
        if (
            participant.employee.current_revision_id != participant.revision.id
            or participant.revision.employee_id != participant.employee_id
        ):
            raise ValueError("employee selection must freeze the current revision")
        if (
            participant.binding.employee_id != participant.employee_id
            or participant.binding.dsh_agent_id != participant.binding.dsh_session_id
        ):
            raise ValueError("employee selection must freeze a valid DSH binding")

    @staticmethod
    def _text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} must not be blank")
        return normalized
