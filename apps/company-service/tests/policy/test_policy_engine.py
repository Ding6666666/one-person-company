from collections.abc import Iterable

import pytest
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.ids import CapabilityGrantId
from dsh_company.domain.policy import (
    ACTION_LEVELS,
    ActionRequest,
    DecisionKind,
    PolicyDecision,
    PolicyEngine,
)


def grant(
    action: str,
    level: CapabilityLevel,
    resources: Iterable[str] = ("*",),
    *,
    resource_kind: str = "workspace",
    requires_approval: bool = False,
) -> CapabilityGrant:
    return CapabilityGrant(
        id=CapabilityGrantId(f"grant-{action}-{level}"),
        employee_revision_id=None,
        action=action,
        level=level,
        resource_kind=resource_kind,
        resource_values=tuple(resources),
        requires_approval=requires_approval,
    )


def action_request(
    *,
    action: str = "workspace.write",
    level: CapabilityLevel = CapabilityLevel.L2,
    workspace_resources: Iterable[str] = ("repo-a",),
    employee_resources: Iterable[str] = ("repo-a",),
    node_resources: Iterable[str] = ("repo-a",),
    runtime_resources: Iterable[str] = ("repo-a",),
    workspace_grant: CapabilityGrant | None = None,
    employee_grant: CapabilityGrant | None = None,
    node_grant: CapabilityGrant | None = None,
    runtime_grant: CapabilityGrant | None = None,
    requires_approval: bool = False,
) -> ActionRequest:
    return ActionRequest(
        action=action,
        workspace_grant=workspace_grant
        or grant(action, level, workspace_resources, requires_approval=requires_approval),
        employee_grant=employee_grant
        or grant(action, level, employee_resources, requires_approval=requires_approval),
        node_grant=node_grant
        or grant(action, level, node_resources, requires_approval=requires_approval),
        runtime_grant=runtime_grant
        or grant(action, level, runtime_resources, requires_approval=requires_approval),
    )


def test_action_catalog_is_closed_and_assigns_exact_levels() -> None:
    assert ACTION_LEVELS == {
        "conversation.respond": CapabilityLevel.L0,
        "workspace.read": CapabilityLevel.L1,
        "session.history.read": CapabilityLevel.L1,
        "work.delegate": CapabilityLevel.L1,
        "workspace.write": CapabilityLevel.L2,
        "tool.shell": CapabilityLevel.L2,
        "tool.network": CapabilityLevel.L2,
        "external.publish": CapabilityLevel.L3,
    }


def test_action_requires_every_layer_and_intersects_resources() -> None:
    decision = PolicyEngine().decide(
        ActionRequest(
            action="workspace.write",
            workspace_grant=grant("workspace.write", CapabilityLevel.L2, {"repo-a", "repo-b"}),
            employee_grant=grant("workspace.write", CapabilityLevel.L2, {"repo-a"}),
            node_grant=grant("workspace.write", CapabilityLevel.L2, {"repo-a", "repo-c"}),
            runtime_grant=grant("workspace.write", CapabilityLevel.L2, {"repo-a"}),
        )
    )

    assert decision == PolicyDecision(
        DecisionKind.ALLOW,
        "granted",
        frozenset({"repo-a"}),
    )


@pytest.mark.parametrize(
    ("layer", "reason"),
    [
        ("workspace_grant", "workspace_not_granted"),
        ("employee_grant", "employee_not_granted"),
        ("node_grant", "node_not_granted"),
        ("runtime_grant", "runtime_not_granted"),
    ],
)
def test_missing_layer_denies_instead_of_inheriting(layer: str, reason: str) -> None:
    request = action_request()
    decision = PolicyEngine().decide(
        ActionRequest(
            action=request.action,
            workspace_grant=None if layer == "workspace_grant" else request.workspace_grant,
            employee_grant=None if layer == "employee_grant" else request.employee_grant,
            node_grant=None if layer == "node_grant" else request.node_grant,
            runtime_grant=None if layer == "runtime_grant" else request.runtime_grant,
        )
    )

    assert decision.kind is DecisionKind.DENY
    assert decision.reason == reason


def test_unknown_action_denies_before_inspecting_grants() -> None:
    decision = PolicyEngine().decide(
        ActionRequest(
            action="unknown.action",
            workspace_grant=None,
            employee_grant=None,
            node_grant=None,
            runtime_grant=None,
        )
    )

    assert decision == PolicyDecision(DecisionKind.DENY, "unknown_action")


@pytest.mark.parametrize("invalid_layer", ["workspace", "employee", "node", "runtime"])
def test_grant_for_another_action_does_not_authorize_layer(invalid_layer: str) -> None:
    request = action_request()
    grants = {
        "workspace": request.workspace_grant,
        "employee": request.employee_grant,
        "node": request.node_grant,
        "runtime": request.runtime_grant,
    }
    grants[invalid_layer] = grant("workspace.read", CapabilityLevel.L2)

    decision = PolicyEngine().decide(
        ActionRequest(
            action=request.action,
            workspace_grant=grants["workspace"],
            employee_grant=grants["employee"],
            node_grant=grants["node"],
            runtime_grant=grants["runtime"],
        )
    )

    assert decision == PolicyDecision(DecisionKind.DENY, f"{invalid_layer}_not_granted")


@pytest.mark.parametrize("insufficient_layer", ["workspace", "employee", "node", "runtime"])
def test_each_layer_must_meet_the_action_level(insufficient_layer: str) -> None:
    request = action_request()
    grants = {
        "workspace": request.workspace_grant,
        "employee": request.employee_grant,
        "node": request.node_grant,
        "runtime": request.runtime_grant,
    }
    grants[insufficient_layer] = grant("workspace.write", CapabilityLevel.L1)

    decision = PolicyEngine().decide(
        ActionRequest(
            action=request.action,
            workspace_grant=grants["workspace"],
            employee_grant=grants["employee"],
            node_grant=grants["node"],
            runtime_grant=grants["runtime"],
        )
    )

    assert decision == PolicyDecision(DecisionKind.DENY, f"{insufficient_layer}_level_insufficient")


@pytest.mark.parametrize("mismatched_layer", ["workspace", "employee", "node", "runtime"])
def test_resource_kinds_must_match_before_values_or_approval(
    mismatched_layer: str,
) -> None:
    grants = {
        layer: grant(
            "workspace.write",
            CapabilityLevel.L2,
            {"repo-a"},
            requires_approval=True,
        )
        for layer in ("workspace", "employee", "node", "runtime")
    }
    grants[mismatched_layer] = grant(
        "workspace.write",
        CapabilityLevel.L2,
        {"repo-b"},
        resource_kind="repository",
        requires_approval=True,
    )

    decision = PolicyEngine().decide(
        ActionRequest(
            action="workspace.write",
            workspace_grant=grants["workspace"],
            employee_grant=grants["employee"],
            node_grant=grants["node"],
            runtime_grant=grants["runtime"],
        )
    )

    assert decision == PolicyDecision(DecisionKind.DENY, "resource_kind_mismatch")


def test_unbounded_resource_layer_does_not_expand_other_layers() -> None:
    decision = PolicyEngine().decide(
        action_request(
            workspace_resources={"repo-a", "repo-b"},
            employee_resources={"*"},
            node_resources={"repo-b"},
            runtime_resources={"*"},
        )
    )

    assert decision.effective_resources == frozenset({"repo-b"})


def test_all_unbounded_layers_remain_unbounded() -> None:
    decision = PolicyEngine().decide(
        action_request(
            workspace_resources={"*"},
            employee_resources={"*"},
            node_resources={"*"},
            runtime_resources={"*"},
        )
    )

    assert decision.effective_resources == frozenset({"*"})


def test_empty_resource_intersection_denies() -> None:
    decision = PolicyEngine().decide(
        action_request(workspace_resources={"repo-a"}, employee_resources={"repo-b"})
    )

    assert decision == PolicyDecision(DecisionKind.DENY, "resource_scope_empty")


@pytest.mark.parametrize(
    "action_case",
    [
        action_request(action="external.publish", level=CapabilityLevel.L3),
        action_request(requires_approval=True),
    ],
)
def test_l3_or_explicit_flag_requires_approval(action_case: ActionRequest) -> None:
    decision = PolicyEngine().decide(action_case)

    assert decision.kind is DecisionKind.REQUIRE_APPROVAL
    assert decision.reason == "approval_required"
    assert decision.effective_resources == frozenset({"repo-a"})
