from collections.abc import Collection

from dsh_company.domain.ids import WorkNodeId
from dsh_company.domain.policy import ACTION_LEVELS
from dsh_company.domain.work import (
    ArtifactReference,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
)


class InvalidGraph(ValueError):
    """A work graph violates a closed Company graph invariant."""


class GraphValidator:
    def __init__(self, action_catalog: Collection[str] = ACTION_LEVELS.keys()) -> None:
        self._action_catalog = frozenset(action_catalog)

    def validate(
        self,
        graph: WorkGraphRevision,
        nodes: tuple[WorkNode, ...],
        *,
        artifact_references: tuple[ArtifactReference, ...] = (),
    ) -> None:
        if not graph.node_ids:
            raise InvalidGraph("empty_graph")
        if len(set(graph.node_ids)) != len(graph.node_ids):
            raise InvalidGraph("duplicate_node_id")
        if tuple(node.id for node in nodes) != graph.node_ids:
            raise InvalidGraph("node_facts_mismatch")

        edge_identities = tuple(
            (edge.from_node_id, edge.to_node_id, edge.kind) for edge in graph.edges
        )
        if len(set(edge_identities)) != len(edge_identities):
            # WorkEdge has no public ID. Its complete immutable tuple is the stable
            # identity; persistence adds only a revision-local positional row ID.
            raise InvalidGraph("duplicate_edge_id")

        known_node_ids = set(graph.node_ids)
        for edge in graph.edges:
            if (
                edge.from_node_id not in known_node_ids
                or edge.to_node_id not in known_node_ids
            ):
                raise InvalidGraph("unknown_edge_endpoint")
            if edge.from_node_id == edge.to_node_id:
                raise InvalidGraph("self_edge")

        outgoing = {node_id: [] for node_id in graph.node_ids}
        incoming = {node_id: [] for node_id in graph.node_ids}
        indegrees = dict.fromkeys(graph.node_ids, 0)
        for edge in graph.edges:
            outgoing[edge.from_node_id].append(edge.to_node_id)
            incoming[edge.to_node_id].append(edge.from_node_id)
            indegrees[edge.to_node_id] += 1

        ready = sorted(node_id for node_id, degree in indegrees.items() if degree == 0)
        visited = 0
        while ready:
            node_id = ready.pop(0)
            visited += 1
            for target_id in sorted(outgoing[node_id]):
                indegrees[target_id] -= 1
                if indegrees[target_id] == 0:
                    ready.append(target_id)
                    ready.sort()
        if visited != len(graph.node_ids):
            path = self._cycle_path(graph.node_ids, outgoing)
            raise InvalidGraph(f"cycle: {' -> '.join(path)}")

        artifact_ids = {str(reference.id) for reference in artifact_references}
        for node in nodes:
            if node.work_id != graph.work_id:
                raise InvalidGraph("node_work_id_mismatch")
            if not str(node.assigned_employee_id).strip():
                raise InvalidGraph("blank_assigned_employee_id")
            if not str(node.employee_revision_id).strip():
                raise InvalidGraph("blank_employee_revision_id")
            if (
                node.max_attempts < 1
                or node.attempt_count < 0
                or node.attempt_count > node.max_attempts
            ):
                raise InvalidGraph("invalid_attempt_bounds")
            unknown_actions = sorted(
                action for action in node.required_actions if action not in self._action_catalog
            )
            if unknown_actions:
                raise InvalidGraph(f"unknown_required_action: {unknown_actions[0]}")

            upstream_ids = self._upstream_ids(node.id, incoming)
            for reference in node.input_references:
                reference_value = str(reference)
                if reference_value not in artifact_ids and reference_value not in upstream_ids:
                    raise InvalidGraph(
                        f"unresolved_input_reference: {reference_value} for {node.id}"
                    )

    def validate_revision(
        self,
        previous_graph: WorkGraphRevision,
        previous_nodes: tuple[WorkNode, ...],
        candidate_graph: WorkGraphRevision,
        candidate_nodes: tuple[WorkNode, ...],
        *,
        artifact_references: tuple[ArtifactReference, ...] = (),
    ) -> None:
        self.validate(
            previous_graph,
            previous_nodes,
            artifact_references=artifact_references,
        )
        self.validate(
            candidate_graph,
            candidate_nodes,
            artifact_references=artifact_references,
        )
        candidate_by_id = {node.id: node for node in candidate_nodes}
        for previous_node in previous_nodes:
            if previous_node.status in {
                WorkNodeStatus.COMPLETED,
                WorkNodeStatus.FAILED,
                WorkNodeStatus.CANCELLED,
            } and candidate_by_id.get(previous_node.id) != previous_node:
                raise InvalidGraph(f"completed_node_changed: {previous_node.id}")

    @staticmethod
    def _upstream_ids(
        node_id: WorkNodeId, incoming: dict[WorkNodeId, list[WorkNodeId]]
    ) -> set[str]:
        upstream: set[WorkNodeId] = set()
        pending = list(incoming[node_id])
        while pending:
            source_id = pending.pop()
            if source_id in upstream:
                continue
            upstream.add(source_id)
            pending.extend(incoming[source_id])
        return {str(item) for item in upstream}

    @staticmethod
    def _cycle_path(
        node_ids: tuple[WorkNodeId, ...],
        outgoing: dict[WorkNodeId, list[WorkNodeId]],
    ) -> tuple[str, ...]:
        visited: set[WorkNodeId] = set()
        active: set[WorkNodeId] = set()
        path: list[WorkNodeId] = []

        def visit(node_id: WorkNodeId) -> tuple[str, ...] | None:
            visited.add(node_id)
            active.add(node_id)
            path.append(node_id)
            for target_id in sorted(outgoing[node_id]):
                if target_id in active:
                    start = path.index(target_id)
                    return tuple(str(item) for item in (*path[start:], target_id))
                if target_id not in visited:
                    cycle = visit(target_id)
                    if cycle is not None:
                        return cycle
            path.pop()
            active.remove(node_id)
            return None

        for node_id in sorted(node_ids):
            if node_id not in visited:
                cycle = visit(node_id)
                if cycle is not None:
                    return cycle
        raise RuntimeError("topological cycle was not found by DFS")
