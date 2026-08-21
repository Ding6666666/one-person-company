from dataclasses import replace
from datetime import UTC, datetime

import pytest
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    EmployeeId,
    EmployeeRevisionId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ArtifactReference,
    WorkEdge,
    WorkEdgeKind,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStrategy,
)
from dsh_company.orchestration.graph_validation import GraphValidator, InvalidGraph


def _node(
    node_id: str,
    *,
    status: WorkNodeStatus = WorkNodeStatus.DRAFT,
    input_references: tuple[ArtifactReferenceId | WorkNodeId, ...] = (),
    required_actions: tuple[str, ...] = ("workspace.read",),
) -> WorkNode:
    return WorkNode(
        id=WorkNodeId(node_id),
        graph_revision_id=WorkGraphRevisionId("graph-1"),
        work_id=WorkId("work-1"),
        objective=f"objective {node_id}",
        acceptance_criteria=("done",),
        assigned_employee_id=EmployeeId(f"employee-{node_id}"),
        employee_revision_id=EmployeeRevisionId(f"revision-{node_id}"),
        status=status,
        active_attempt_id=None,
        failure_code=None,
        version=1,
        input_references=input_references,
        required_actions=required_actions,
    )


def _graph(
    nodes: tuple[WorkNode, ...],
    edges: tuple[WorkEdge, ...] = (),
) -> WorkGraphRevision:
    return WorkGraphRevision(
        id=WorkGraphRevisionId("graph-1"),
        work_id=WorkId("work-1"),
        revision_number=1,
        strategy=WorkStrategy.DIRECT,
        created_at=datetime.now(UTC),
        node_ids=tuple(node.id for node in nodes),
        edges=edges,
    )


def _unchecked_graph(
    node_ids: tuple[WorkNodeId, ...], edges: tuple[WorkEdge, ...]
) -> WorkGraphRevision:
    """Build invalid input that the legacy domain constructor rejects earlier."""
    graph = object.__new__(WorkGraphRevision)
    object.__setattr__(graph, "id", WorkGraphRevisionId("graph-1"))
    object.__setattr__(graph, "work_id", WorkId("work-1"))
    object.__setattr__(graph, "revision_number", 1)
    object.__setattr__(graph, "strategy", WorkStrategy.DIRECT)
    object.__setattr__(graph, "created_at", datetime.now(UTC))
    object.__setattr__(graph, "node_ids", node_ids)
    object.__setattr__(graph, "edges", edges)
    return graph


def test_valid_graph_accepts_all_four_edge_kinds_and_resolved_inputs() -> None:
    research = _node("research")
    draft = _node("draft", input_references=(research.id,))
    review = _node("review", input_references=(ArtifactReferenceId("artifact-draft"),))
    summary = _node("summary", input_references=(research.id,))
    nodes = (research, draft, review, summary)
    graph = _graph(
        nodes,
        (
            WorkEdge(research.id, draft.id, WorkEdgeKind.DEPENDS_ON),
            WorkEdge(draft.id, review.id, WorkEdgeKind.REVIEWS),
            WorkEdge(research.id, summary.id, WorkEdgeKind.SUMMARIZES),
            WorkEdge(draft.id, summary.id, WorkEdgeKind.DELEGATES_TO),
        ),
    )
    artifact = ArtifactReference(
        id=ArtifactReferenceId("artifact-draft"),
        workspace_id=WorkspaceId("ws-1"),
        kind="dsh_session_result",
        uri="dsh://session/employee-draft/result",
        source_session_id="employee-draft",
        source_attempt_id=AttemptId("attempt-draft"),
        created_at=datetime.now(UTC),
    )

    GraphValidator().validate(graph, nodes, artifact_references=(artifact,))


def test_work_node_graph_fields_have_direct_compatible_defaults() -> None:
    node = _node("node-a", required_actions=())

    assert node.required_actions == ()
    assert node.resource_values == ()
    assert node.input_references == ()
    assert node.output_references == ()
    assert node.max_attempts == 1
    assert node.attempt_count == 0


def test_cycle_is_rejected_with_deterministic_path() -> None:
    nodes = (_node("a"), _node("b"), _node("c"))
    graph = _unchecked_graph(
        tuple(node.id for node in nodes),
        (
            WorkEdge(nodes[0].id, nodes[1].id, WorkEdgeKind.DEPENDS_ON),
            WorkEdge(nodes[1].id, nodes[2].id, WorkEdgeKind.DEPENDS_ON),
            WorkEdge(nodes[2].id, nodes[0].id, WorkEdgeKind.DEPENDS_ON),
        ),
    )

    with pytest.raises(InvalidGraph, match="a -> b -> c -> a"):
        GraphValidator().validate(graph, nodes)


@pytest.mark.parametrize(
    "status",
    [WorkNodeStatus.COMPLETED, WorkNodeStatus.FAILED, WorkNodeStatus.CANCELLED],
)
def test_new_revision_cannot_rewrite_terminal_node(status: WorkNodeStatus) -> None:
    previous_node = _node("node-a", status=status)
    previous = _graph((previous_node,))
    candidate_node = replace(previous_node, objective="rewritten")
    candidate = replace(previous, id=WorkGraphRevisionId("graph-2"), revision_number=2)

    with pytest.raises(InvalidGraph, match="completed_node_changed"):
        GraphValidator().validate_revision(
            previous,
            (previous_node,),
            candidate,
            (candidate_node,),
        )


def test_graph_rejects_empty_duplicate_unknown_and_self_edge_facts() -> None:
    validator = GraphValidator()
    with pytest.raises(InvalidGraph, match="empty_graph"):
        validator.validate(_graph(()), ())

    node = _node("node-a")
    duplicate_nodes = _unchecked_graph((node.id, node.id), ())
    with pytest.raises(InvalidGraph, match="duplicate_node_id"):
        validator.validate(duplicate_nodes, (node, node))

    unknown = _unchecked_graph(
        (node.id,),
        (WorkEdge(node.id, WorkNodeId("missing"), WorkEdgeKind.DEPENDS_ON),),
    )
    with pytest.raises(InvalidGraph, match="unknown_edge_endpoint"):
        validator.validate(unknown, (node,))

    self_edge = _unchecked_graph(
        (node.id,),
        (WorkEdge(node.id, node.id, WorkEdgeKind.DEPENDS_ON),),
    )
    with pytest.raises(InvalidGraph, match="self_edge"):
        validator.validate(self_edge, (node,))


def test_graph_rejects_duplicate_edge_identity() -> None:
    source, target = _node("source"), _node("target")
    edge = WorkEdge(source.id, target.id, WorkEdgeKind.DEPENDS_ON)
    graph = _graph((source, target), (edge, edge))

    with pytest.raises(InvalidGraph, match="duplicate_edge_id"):
        GraphValidator().validate(graph, (source, target))


def test_graph_requires_matching_node_facts_and_nonblank_assignments() -> None:
    node = _node("node-a")
    graph = _graph((node,))

    with pytest.raises(InvalidGraph, match="node_facts_mismatch"):
        GraphValidator().validate(graph, ())

    blank_employee = replace(node, assigned_employee_id=EmployeeId("  "))
    with pytest.raises(InvalidGraph, match="blank_assigned_employee_id"):
        GraphValidator().validate(graph, (blank_employee,))

    blank_revision = replace(node, employee_revision_id=EmployeeRevisionId(""))
    with pytest.raises(InvalidGraph, match="blank_employee_revision_id"):
        GraphValidator().validate(graph, (blank_revision,))

    wrong_work = replace(node, work_id=WorkId("work-2"))
    with pytest.raises(InvalidGraph, match="node_work_id_mismatch"):
        GraphValidator().validate(graph, (wrong_work,))


@pytest.mark.parametrize(
    ("max_attempts", "attempt_count"),
    [(0, 0), (1, -1), (2, 3)],
)
def test_graph_rejects_invalid_attempt_bounds(
    max_attempts: int, attempt_count: int
) -> None:
    node = replace(
        _node("node-a"),
        max_attempts=max_attempts,
        attempt_count=attempt_count,
    )

    with pytest.raises(InvalidGraph, match="invalid_attempt_bounds"):
        GraphValidator().validate(_graph((node,)), (node,))


def test_graph_rejects_unresolved_or_non_upstream_input_reference() -> None:
    source = _node("source")
    target = _node("target", input_references=(ArtifactReferenceId("missing"),))
    graph = _graph(
        (source, target),
        (WorkEdge(source.id, target.id, WorkEdgeKind.DEPENDS_ON),),
    )
    with pytest.raises(InvalidGraph, match="unresolved_input_reference"):
        GraphValidator().validate(graph, (source, target))

    unrelated = _node("unrelated")
    target = replace(target, input_references=(unrelated.id,))
    graph = _graph(
        (source, unrelated, target),
        (WorkEdge(source.id, target.id, WorkEdgeKind.DEPENDS_ON),),
    )
    with pytest.raises(InvalidGraph, match="unresolved_input_reference"):
        GraphValidator().validate(graph, (source, unrelated, target))


def test_graph_rejects_required_action_outside_catalog() -> None:
    node = _node("node-a", required_actions=("workspace.read", "unknown.action"))

    with pytest.raises(InvalidGraph, match="unknown_required_action: unknown.action"):
        GraphValidator().validate(_graph((node,)), (node,))
