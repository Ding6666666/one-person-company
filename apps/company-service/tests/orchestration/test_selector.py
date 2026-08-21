from datetime import UTC, datetime

import pytest
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
    WorkspaceId,
)
from dsh_company.orchestration.selector import EmployeeCandidate, Selector


def _grant(
    employee: str,
    action: str,
    *,
    resources: tuple[str, ...] = ("ws-1",),
    kind: str = "workspace",
    approval: bool = False,
) -> CapabilityGrant:
    return CapabilityGrant(
        id=CapabilityGrantId(f"grant-{employee}-{action}"),
        employee_revision_id=EmployeeRevisionId(f"revision-{employee}"),
        action=action,
        level=CapabilityLevel.L1,
        resource_kind=kind,
        resource_values=resources,
        requires_approval=approval,
    )


def _candidate(
    employee_id: str,
    *,
    workspace_id: str = "ws-1",
    status: EmployeeStatus = EmployeeStatus.ACTIVE,
    action: str = "workspace.read",
    resources: tuple[str, ...] = ("ws-1",),
    kind: str = "workspace",
    approval: bool = False,
    runtime_profile: str = "workspace_read",
) -> EmployeeCandidate:
    now = datetime.now(UTC)
    revision_id = EmployeeRevisionId(f"revision-{employee_id}")
    grant = _grant(
        employee_id,
        action,
        resources=resources,
        kind=kind,
        approval=approval,
    )
    return EmployeeCandidate(
        employee=Employee(
            id=EmployeeId(employee_id),
            workspace_id=WorkspaceId(workspace_id),
            display_name=employee_id,
            status=status,
            current_revision_id=revision_id,
            created_at=now,
        ),
        revision=EmployeeRevision(
            id=revision_id,
            employee_id=EmployeeId(employee_id),
            revision_number=1,
            responsibility="research",
            runtime_profile=runtime_profile,
            model="deepseek-chat",
            created_at=now,
        ),
        binding=EmployeeAgentBinding(
            id=EmployeeAgentBindingId(f"binding-{employee_id}"),
            employee_id=EmployeeId(employee_id),
            dsh_agent_id=f"session-{employee_id}",
            dsh_session_id=f"session-{employee_id}",
            memory_scope_id=f"dsh-session:session-{employee_id}",
            created_at=now,
        ),
        employee_grants=(grant,),
        workspace_grants=(grant,),
        node_grants=(grant,),
    )


def test_selector_filters_before_ranking_and_never_selects_all_by_default() -> None:
    candidates = tuple(_candidate(f"emp-{index}") for index in range(1, 9))

    eligible = Selector().eligible(
        employees=candidates,
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset(
            {
                EmployeeId("emp-2"),
                EmployeeId("emp-3"),
                EmployeeId("emp-4"),
            }
        ),
        user_order=(EmployeeId("emp-4"), EmployeeId("emp-2")),
    )

    assert [item.employee_id for item in eligible] == ["emp-4", "emp-2", "emp-3"]
    assert Selector().choose(eligible, limit=2) == eligible[:2]


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate("wrong-workspace", workspace_id="ws-2"),
        _candidate("paused", status=EmployeeStatus.PAUSED),
        _candidate("wrong-resource", resources=("ws-2",)),
        _candidate("wrong-kind", kind="repository"),
        _candidate("runtime-denied", runtime_profile="network_denied", action="workspace.write"),
        _candidate("approval", approval=True),
    ],
)
def test_selector_requires_workspace_active_policy_runtime_and_approval_eligibility(
    candidate: EmployeeCandidate,
) -> None:
    required_action = (
        "workspace.write" if candidate.employee.id == "runtime-denied" else "workspace.read"
    )

    assert (
        Selector().eligible(
            employees=(candidate,),
            workspace_id=WorkspaceId("ws-1"),
            required_actions=(required_action,),
            resources=("ws-1",),
            resource_kinds=("workspace",),
            delegation_allowlist=frozenset({candidate.employee.id}),
        )
        == ()
    )


def test_selector_can_include_approval_candidates_only_when_explicitly_allowed() -> None:
    candidate = _candidate("approval", approval=True)

    selected = Selector().eligible(
        employees=(candidate,),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset({candidate.employee.id}),
        allow_approval_required=True,
    )

    assert selected[0].revision == candidate.revision
    assert selected[0].binding == candidate.binding
    assert selected[0].required_actions == ("workspace.read",)
    assert selected[0].resource_values == ("ws-1",)
    assert selected[0].resource_kinds == ("workspace",)


def test_selector_requires_an_explicit_small_limit() -> None:
    eligible = Selector().eligible(
        employees=tuple(_candidate(f"emp-{index}") for index in range(1, 6)),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset(EmployeeId(f"emp-{index}") for index in range(1, 6)),
    )

    with pytest.raises(ValueError, match="between 1 and 4"):
        Selector().choose(eligible, limit=5)


def test_selector_deduplicates_candidates_and_preserves_first_user_position() -> None:
    employee_a = _candidate("emp-a")
    employee_b = _candidate("emp-b")

    eligible = Selector().eligible(
        employees=(employee_a, employee_b, employee_a),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset({EmployeeId("emp-a"), EmployeeId("emp-b")}),
        user_order=(EmployeeId("emp-b"), EmployeeId("emp-a"), EmployeeId("emp-b")),
    )

    assert [item.employee_id for item in eligible] == ["emp-b", "emp-a"]


def test_selector_places_unordered_employees_after_deduplicated_user_order() -> None:
    eligible = Selector().eligible(
        employees=(_candidate("emp-a"), _candidate("emp-c"), _candidate("emp-z")),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset(
            {EmployeeId("emp-a"), EmployeeId("emp-c"), EmployeeId("emp-z")}
        ),
        user_order=(EmployeeId("emp-a"), EmployeeId("emp-a"), EmployeeId("emp-z")),
    )

    assert [item.employee_id for item in eligible] == ["emp-a", "emp-z", "emp-c"]


def test_choose_returns_unique_employees_even_for_a_duplicate_input_tuple() -> None:
    selected_a = Selector().eligible(
        employees=(_candidate("emp-a"),),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset({EmployeeId("emp-a")}),
    )[0]
    selected_b = Selector().eligible(
        employees=(_candidate("emp-b"),),
        workspace_id=WorkspaceId("ws-1"),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        resource_kinds=("workspace",),
        delegation_allowlist=frozenset({EmployeeId("emp-b")}),
    )[0]

    assert Selector().choose((selected_a, selected_a, selected_b), limit=2) == (
        selected_a,
        selected_b,
    )
