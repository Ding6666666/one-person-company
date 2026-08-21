from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from .capabilities import CapabilityGrant, CapabilityLevel
from .ids import CapabilityGrantId

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


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    action: str
    level: CapabilityLevel
    runtime_profiles: frozenset[str]


class ActionCatalog:
    """Immutable policy facts for core and registered declarative actions."""

    def __init__(self, definitions: Iterable[ActionDefinition]) -> None:
        values = tuple(definitions)
        actions = tuple(item.action for item in values)
        if len(actions) != len(set(actions)):
            raise ValueError("duplicate action definition")
        self._definitions = {item.action: item for item in values}

    @property
    def actions(self) -> frozenset[str]:
        return frozenset(self._definitions)

    @property
    def definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._definitions[action] for action in sorted(self._definitions))

    def level(self, action: str) -> CapabilityLevel | None:
        definition = self._definitions.get(action)
        return None if definition is None else definition.level

    def supports_runtime(self, action: str, runtime_profile: str) -> bool:
        definition = self._definitions.get(action)
        return definition is not None and runtime_profile in definition.runtime_profiles


ActionCatalogProvider = Callable[[], ActionCatalog]


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
    def __init__(
        self,
        action_catalog: ActionCatalog | ActionCatalogProvider | None = None,
    ) -> None:
        if action_catalog is None:
            from dsh_company.policy.runtime_profiles import core_action_catalog

            self._action_catalog = core_action_catalog
        elif isinstance(action_catalog, ActionCatalog):
            self._action_catalog = lambda: action_catalog
        else:
            self._action_catalog = action_catalog

    @property
    def catalog(self) -> ActionCatalog:
        return self._action_catalog()

    def required_level(self, action: str) -> CapabilityLevel | None:
        return self.catalog.level(action)

    def runtime_grant(
        self,
        runtime_profile: str,
        action: str,
        template: CapabilityGrant | None,
    ) -> CapabilityGrant | None:
        catalog = self.catalog
        level = catalog.level(action)
        if (
            template is None
            or level is None
            or not catalog.supports_runtime(action, runtime_profile)
        ):
            return None
        return CapabilityGrant(
            id=CapabilityGrantId(f"runtime:{runtime_profile}:{action}"),
            employee_revision_id=None,
            action=action,
            level=level,
            resource_kind=template.resource_kind,
            resource_values=("*",),
            requires_approval=False,
        )

    def decide(self, request: ActionRequest) -> PolicyDecision:
        required_level = self.required_level(request.action)
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
