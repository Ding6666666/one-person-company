from dataclasses import dataclass

from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.employee import (
    Employee,
    EmployeeAgentBinding,
    EmployeeRevision,
    EmployeeStatus,
)
from dsh_company.domain.ids import CapabilityGrantId, EmployeeId, WorkspaceId
from dsh_company.domain.policy import (
    ACTION_LEVELS,
    ActionRequest,
    DecisionKind,
    PolicyEngine,
)
from dsh_company.policy.runtime_profiles import actions_for_runtime_profile


@dataclass(frozen=True, slots=True)
class EmployeeCandidate:
    """Current persisted facts considered by deterministic selection."""

    employee: Employee
    revision: EmployeeRevision
    binding: EmployeeAgentBinding
    employee_grants: tuple[CapabilityGrant, ...]
    workspace_grants: tuple[CapabilityGrant, ...]
    node_grants: tuple[CapabilityGrant, ...]


@dataclass(frozen=True, slots=True)
class EligibleEmployee:
    """Frozen Employee and node policy facts assigned to a strategy node."""

    employee: Employee
    revision: EmployeeRevision
    binding: EmployeeAgentBinding
    employee_grants: tuple[CapabilityGrant, ...]
    required_actions: tuple[str, ...]
    resource_values: tuple[str, ...]
    resource_kinds: tuple[str, ...]

    @property
    def employee_id(self) -> EmployeeId:
        return self.employee.id


class Selector:
    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self._policy_engine = policy_engine or PolicyEngine()

    def eligible(
        self,
        *,
        employees: tuple[EmployeeCandidate, ...],
        workspace_id: WorkspaceId,
        required_actions: tuple[str, ...],
        resources: tuple[str, ...],
        resource_kinds: tuple[str, ...],
        delegation_allowlist: frozenset[EmployeeId],
        user_order: tuple[EmployeeId, ...] = (),
        allow_approval_required: bool = False,
    ) -> tuple[EligibleEmployee, ...]:
        if len(resource_kinds) != len(required_actions):
            raise ValueError("resource kinds must align with required actions")

        eligible: list[EligibleEmployee] = []
        eligible_ids: set[EmployeeId] = set()
        for candidate in employees:
            if not self._has_current_active_facts(candidate, workspace_id):
                continue
            if candidate.employee.id not in delegation_allowlist:
                continue
            if not self._policy_allows(
                candidate,
                required_actions,
                resources,
                resource_kinds,
                allow_approval_required=allow_approval_required,
            ):
                continue
            if candidate.employee.id in eligible_ids:
                continue
            eligible_ids.add(candidate.employee.id)
            eligible.append(
                EligibleEmployee(
                    employee=candidate.employee,
                    revision=candidate.revision,
                    binding=candidate.binding,
                    employee_grants=candidate.employee_grants,
                    required_actions=tuple(required_actions),
                    resource_values=tuple(resources),
                    resource_kinds=tuple(resource_kinds),
                )
            )

        positions: dict[EmployeeId, int] = {}
        for employee_id in user_order:
            if employee_id not in positions:
                positions[employee_id] = len(positions)
        return tuple(
            sorted(
                eligible,
                key=lambda item: (
                    positions.get(item.employee_id, len(positions)),
                    str(item.employee_id),
                ),
            )
        )

    @staticmethod
    def choose(
        candidates: tuple[EligibleEmployee, ...], *, limit: int
    ) -> tuple[EligibleEmployee, ...]:
        if limit < 1 or limit > 4:
            raise ValueError("selection limit must be between 1 and 4")
        unique: list[EligibleEmployee] = []
        seen: set[EmployeeId] = set()
        for candidate in candidates:
            if candidate.employee_id in seen:
                continue
            seen.add(candidate.employee_id)
            unique.append(candidate)
            if len(unique) == limit:
                break
        return tuple(unique)

    @staticmethod
    def _has_current_active_facts(candidate: EmployeeCandidate, workspace_id: WorkspaceId) -> bool:
        return (
            candidate.employee.workspace_id == workspace_id
            and candidate.employee.status is EmployeeStatus.ACTIVE
            and candidate.employee.current_revision_id == candidate.revision.id
            and candidate.revision.employee_id == candidate.employee.id
            and candidate.binding.employee_id == candidate.employee.id
            and candidate.binding.dsh_agent_id == candidate.binding.dsh_session_id
        )

    def _policy_allows(
        self,
        candidate: EmployeeCandidate,
        required_actions: tuple[str, ...],
        resources: tuple[str, ...],
        resource_kinds: tuple[str, ...],
        *,
        allow_approval_required: bool,
    ) -> bool:
        for action, resource_kind in zip(required_actions, resource_kinds, strict=True):
            workspace_grant = self._for_action(candidate.workspace_grants, action)
            employee_grant = self._for_action(candidate.employee_grants, action)
            node_grant = self._for_action(candidate.node_grants, action)
            template = workspace_grant or employee_grant or node_grant
            runtime_grant = self._runtime_grant(
                candidate.revision.runtime_profile, action, template
            )
            decision = self._policy_engine.decide(
                ActionRequest(
                    action=action,
                    workspace_grant=workspace_grant,
                    employee_grant=employee_grant,
                    node_grant=node_grant,
                    runtime_grant=runtime_grant,
                )
            )
            if decision.kind is DecisionKind.DENY:
                return False
            if decision.kind is DecisionKind.REQUIRE_APPROVAL and not allow_approval_required:
                return False
            if any(
                grant is None or grant.resource_kind != resource_kind
                for grant in (
                    workspace_grant,
                    employee_grant,
                    node_grant,
                    runtime_grant,
                )
            ):
                return False
            requested = frozenset(resources)
            if (
                requested
                and "*" not in decision.effective_resources
                and not requested.issubset(decision.effective_resources)
            ):
                return False
        return True

    @staticmethod
    def _for_action(grants: tuple[CapabilityGrant, ...], action: str) -> CapabilityGrant | None:
        return next((grant for grant in grants if grant.action == action), None)

    @staticmethod
    def _runtime_grant(
        runtime_profile: str,
        action: str,
        template: CapabilityGrant | None,
    ) -> CapabilityGrant | None:
        if template is None or action not in actions_for_runtime_profile(runtime_profile):
            return None
        required_level = ACTION_LEVELS.get(action)
        if required_level is None:
            return None
        return CapabilityGrant(
            id=CapabilityGrantId(f"runtime:{runtime_profile}:{action}"),
            employee_revision_id=None,
            action=action,
            level=required_level,
            resource_kind=template.resource_kind,
            resource_values=("*",),
            requires_approval=False,
        )
