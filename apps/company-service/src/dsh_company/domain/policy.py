from dataclasses import dataclass
from enum import StrEnum

from .capabilities import CapabilityGrant, CapabilityLevel

ACTION_LEVELS: dict[str, CapabilityLevel] = {
    "conversation.respond": CapabilityLevel.L0,
    "workspace.read": CapabilityLevel.L1,
    "session.history.read": CapabilityLevel.L1,
    "work.delegate": CapabilityLevel.L1,
    "workspace.write": CapabilityLevel.L2,
    "tool.shell": CapabilityLevel.L2,
    "tool.network": CapabilityLevel.L2,
    "external.publish": CapabilityLevel.L3,
}


class DecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: DecisionKind
    reason: str
    effective_resources: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action: str
    workspace_grant: CapabilityGrant | None
    employee_grant: CapabilityGrant | None
    node_grant: CapabilityGrant | None
    runtime_grant: CapabilityGrant | None


class PolicyEngine:
    def decide(self, request: ActionRequest) -> PolicyDecision:
        required_level = ACTION_LEVELS.get(request.action)
        if required_level is None:
            return PolicyDecision(DecisionKind.DENY, "unknown_action")

        layers = (
            ("workspace", request.workspace_grant),
            ("employee", request.employee_grant),
            ("node", request.node_grant),
            ("runtime", request.runtime_grant),
        )
        grants: list[CapabilityGrant] = []

        for layer, grant in layers:
            if grant is None or grant.action != request.action:
                return PolicyDecision(DecisionKind.DENY, f"{layer}_not_granted")
            if grant.level < required_level:
                return PolicyDecision(DecisionKind.DENY, f"{layer}_level_insufficient")
            grants.append(grant)

        if len({grant.resource_kind for grant in grants}) != 1:
            return PolicyDecision(DecisionKind.DENY, "resource_kind_mismatch")

        bounded_resources: frozenset[str] | None = None
        requires_approval = required_level is CapabilityLevel.L3
        for grant in grants:
            resources = frozenset(grant.resource_values)
            if "*" not in resources:
                bounded_resources = (
                    resources
                    if bounded_resources is None
                    else bounded_resources.intersection(resources)
                )
            requires_approval = requires_approval or grant.requires_approval

        effective_resources = bounded_resources or frozenset()
        if bounded_resources is None:
            effective_resources = frozenset({"*"})
        elif not bounded_resources:
            return PolicyDecision(DecisionKind.DENY, "resource_scope_empty")

        if requires_approval:
            return PolicyDecision(
                DecisionKind.REQUIRE_APPROVAL,
                "approval_required",
                effective_resources,
            )
        return PolicyDecision(DecisionKind.ALLOW, "granted", effective_resources)
