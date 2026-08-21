from datetime import UTC, datetime

import pytest
from dsh_company.application.ports import WorkAggregate
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.employee import (
    Employee,
    EmployeeAgentBinding,
    EmployeeRevision,
    EmployeeStatus,
)
from dsh_company.domain.ids import (
    CapabilityGrantId,
    EmployeeAgentBindingId,
    EmployeeId,
    EmployeeRevisionId,
    WorkGraphRevisionId,
    WorkId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    Work,
    WorkEdgeKind,
    WorkNodeStatus,
    WorkStatus,
    WorkStrategy,
)
from dsh_company.orchestration.graph_validation import InvalidGraph
from dsh_company.orchestration.selector import EligibleEmployee, EmployeeCandidate, Selector
from dsh_company.orchestration.strategies import (
    BATTLE_SUMMARY_INSTRUCTION,
    ExplicitEdge,
    ExplicitNode,
    StarChild,
    StrategyFactory,
)


def _candidate(
    employee_id: str, *, status: EmployeeStatus = EmployeeStatus.ACTIVE
) -> EmployeeCandidate:
    now = datetime.now(UTC)
    revision_id = EmployeeRevisionId(f"revision-{employee_id}")
    grant = CapabilityGrant(
        id=CapabilityGrantId(f"grant-{employee_id}"),
        employee_revision_id=revision_id,
        action="workspace.read",
        level=CapabilityLevel.L1,
        resource_kind="workspace",
        resource_values=("ws-1",),
        requires_approval=False,
    )
    return EmployeeCandidate(
        employee=Employee(
            EmployeeId(employee_id),
            WorkspaceId("ws-1"),
            employee_id,
            status,
            revision_id,
            now,
        ),
        revision=EmployeeRevision(
            revision_id,
            EmployeeId(employee_id),
            1,
            "research",
            "workspace_read",
            "deepseek-chat",
            now,
        ),
        binding=EmployeeAgentBinding(
            EmployeeAgentBindingId(f"binding-{employee_id}"),
            EmployeeId(employee_id),
            f"session-{employee_id}",
            f"session-{employee_id}",
            f"dsh-session:session-{employee_id}",
            now,
        ),
        employee_grants=(grant,),
        workspace_grants=(grant,),
        node_grants=(grant,),
    )


def _work(strategy: str) -> Work:
    return Work(
        id=WorkId("work-1"),
        workspace_id=WorkspaceId("ws-1"),
        command_id="command-1",
        objective="提出品牌方案",
        status=WorkStatus.QUEUED,
        current_graph_revision_id=WorkGraphRevisionId(f"graph-{strategy}"),
        created_at=datetime.now(UTC),
    )


def _selected(*employee_ids: str):
    candidates = tuple(_candidate(employee_id) for employee_id in employee_ids)
    return Selector().eligible(
        employees=candidates,
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset(EmployeeId(item) for item in employee_ids),
    )


def test_direct_preserves_one_node_semantics_as_a_draft_aggregate() -> None:
    participant = _selected("emp-a")[0]

    aggregate = StrategyFactory().direct(
        work=_work("direct"),
        participant=participant,
        objective="提出品牌方案",
        criteria=("列出依据",),
    )

    assert isinstance(aggregate, WorkAggregate)
    assert aggregate.graph.strategy is WorkStrategy.DIRECT
    assert len(aggregate.nodes) == 1
    assert aggregate.nodes[0].status is WorkNodeStatus.DRAFT
    assert aggregate.nodes[0].assigned_employee_id == EmployeeId("emp-a")
    assert aggregate.nodes[0].employee_revision_id == participant.revision.id
    assert aggregate.nodes[0].required_actions == participant.required_actions
    assert aggregate.nodes[0].resource_values == participant.resource_values


def test_star_builds_explicit_children_and_coordinator_summary() -> None:
    child_a, child_b, coordinator = _selected("emp-a", "emp-b", "emp-c")

    aggregate = StrategyFactory().star(
        work=_work("star"),
        coordinator=coordinator,
        children=(
            StarChild(child_a, "调研受众", ("列出三类受众",)),
            StarChild(child_b, "调研竞品", ("列出两项差异",)),
        ),
        objective="提出品牌方案",
        criteria=("列出依据",),
    )

    assert aggregate.graph.strategy is WorkStrategy.STAR
    assert [node.objective for node in aggregate.nodes[:2]] == ["调研受众", "调研竞品"]
    assert aggregate.nodes[-1].assigned_employee_id == EmployeeId("emp-c")
    assert [edge.kind for edge in aggregate.graph.edges] == [
        WorkEdgeKind.SUMMARIZES,
        WorkEdgeKind.SUMMARIZES,
    ]


def test_graph_uses_explicit_nodes_and_edges_and_runs_shared_validation() -> None:
    employee_a, employee_b = _selected("emp-a", "emp-b")
    factory = StrategyFactory()
    nodes = (
        ExplicitNode("research", employee_a, "调研", ("有依据",)),
        ExplicitNode("draft", employee_b, "撰写", ("有草稿",)),
    )

    aggregate = factory.graph(
        work=_work("explicit"),
        nodes=nodes,
        edges=(ExplicitEdge("research", "draft", WorkEdgeKind.DEPENDS_ON),),
    )
    assert aggregate.graph.strategy is WorkStrategy.GRAPH
    assert aggregate.graph.edges[0].from_node_id == aggregate.nodes[0].id

    with pytest.raises((InvalidGraph, ValueError), match="cycle|acyclic"):
        factory.graph(
            work=_work("cycle"),
            nodes=nodes,
            edges=(
                ExplicitEdge("research", "draft", WorkEdgeKind.DEPENDS_ON),
                ExplicitEdge("draft", "research", WorkEdgeKind.DEPENDS_ON),
            ),
        )


@pytest.mark.parametrize(
    "edge",
    [
        ExplicitEdge("missing", "draft", WorkEdgeKind.DEPENDS_ON),
        ExplicitEdge("research", "missing", WorkEdgeKind.DEPENDS_ON),
    ],
)
def test_graph_rejects_unknown_explicit_edge_endpoints_with_stable_error(
    edge: ExplicitEdge,
) -> None:
    employee_a, employee_b = _selected("emp-a", "emp-b")

    with pytest.raises(InvalidGraph, match="^unknown_edge_endpoint: missing$"):
        StrategyFactory().graph(
            work=_work("unknown-edge"),
            nodes=(
                ExplicitNode("research", employee_a, "调研", ("有依据",)),
                ExplicitNode("draft", employee_b, "撰写", ("有草稿",)),
            ),
            edges=(edge,),
        )


def test_battle_builds_parallel_workers_and_one_summary_node() -> None:
    participant_a, participant_b, participant_c, summarizer = _selected(
        "emp-a", "emp-b", "emp-c", "emp-s"
    )

    aggregate = StrategyFactory().battle(
        work=_work("battle"),
        participants=(participant_a, participant_b, participant_c),
        summarizer=summarizer,
        objective="提出品牌方案",
        criteria=("列出依据",),
    )

    assert len(aggregate.nodes) == 4
    assert [edge.kind for edge in aggregate.graph.edges] == [
        WorkEdgeKind.SUMMARIZES,
        WorkEdgeKind.SUMMARIZES,
        WorkEdgeKind.SUMMARIZES,
    ]
    assert aggregate.nodes[-1].assigned_employee_id == EmployeeId("emp-s")
    assert aggregate.nodes[-1].objective.endswith(BATTLE_SUMMARY_INSTRUCTION)
    assert all(node.status is WorkNodeStatus.DRAFT for node in aggregate.nodes)


@pytest.mark.parametrize("participant_count", [1, 5])
def test_battle_requires_two_to_four_distinct_participants(participant_count: int) -> None:
    selected = _selected(*(f"emp-{index}" for index in range(participant_count)), "emp-s")

    with pytest.raises(ValueError, match="2 to 4 distinct participants"):
        StrategyFactory().battle(
            work=_work("battle"),
            participants=selected[:-1],
            summarizer=selected[-1],
            objective="提出品牌方案",
            criteria=("列出依据",),
        )


def test_battle_requires_a_distinct_eligible_summarizer() -> None:
    participant_a, participant_b = _selected("emp-a", "emp-b")

    with pytest.raises(ValueError, match="summarizer must be distinct"):
        StrategyFactory().battle(
            work=_work("battle"),
            participants=(participant_a, participant_b),
            summarizer=participant_a,
            objective="提出品牌方案",
            criteria=("列出依据",),
        )

    paused = _candidate("emp-s", status=EmployeeStatus.PAUSED)
    with pytest.raises(ValueError, match="employee selection must be active"):
        StrategyFactory().battle(
            work=_work("battle"),
            participants=(participant_a, participant_b),
            summarizer=EligibleEmployee(
                employee=paused.employee,
                revision=paused.revision,
                binding=paused.binding,
                employee_grants=paused.employee_grants,
                required_actions=("workspace.read",),
                resource_values=("ws-1",),
                resource_kinds=("workspace",),
            ),
            objective="提出品牌方案",
            criteria=("列出依据",),
        )


def test_strategy_ids_are_stable_for_the_same_explicit_inputs() -> None:
    participant_a, participant_b, summarizer = _selected("emp-a", "emp-b", "emp-s")
    factory = StrategyFactory()

    first = factory.battle(
        work=_work("battle"),
        participants=(participant_a, participant_b),
        summarizer=summarizer,
        objective="提出品牌方案",
        criteria=("列出依据",),
    )
    second = factory.battle(
        work=_work("battle"),
        participants=(participant_a, participant_b),
        summarizer=summarizer,
        objective="提出品牌方案",
        criteria=("列出依据",),
    )

    assert first.graph.id == second.graph.id
    assert first.graph.node_ids == second.graph.node_ids
    assert first.nodes == second.nodes
