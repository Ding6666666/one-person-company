from dataclasses import dataclass, replace
from datetime import UTC, datetime

from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.ids import (
    ApprovalId,
    CapabilityGrantId,
    CompanyEventId,
    WorkNodeId,
    new_id,
)
from dsh_company.domain.policy import (
    ACTION_LEVELS,
    ActionRequest,
    DecisionKind,
    PolicyDecision,
    PolicyEngine,
)
from dsh_company.domain.work import (
    CompanyEvent,
    ExecutionLink,
    ExecutionStatus,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
)
from dsh_company.policy.runtime_profiles import actions_for_runtime_profile

from .ports import (
    GovernanceUnitOfWork,
    IdFactory,
    WorkAggregate,
    WorkDispatchQueue,
)


@dataclass(frozen=True, slots=True)
class GovernedAction:
    node_id: WorkNodeId
    action: str
    resources: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        action = self.action.strip()
        resources = tuple(item.strip() for item in self.resources if item.strip())
        reason = self.reason.strip()
        if not action:
            raise ValueError("governed action must not be blank")
        if not resources:
            raise ValueError("governed action requires at least one resource")
        if any(len(item) > 200 for item in resources):
            raise ValueError("governed resource must not exceed 200 characters")
        if not reason or len(reason) > 500:
            raise ValueError("governed reason must contain 1 to 500 characters")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "reason", reason)


AuthorizationResult = Approval | PolicyDecision


class GovernanceService:
    def __init__(
        self,
        uow: GovernanceUnitOfWork,
        policy_engine: PolicyEngine,
        dispatch_queue: WorkDispatchQueue | None = None,
        *,
        ids: IdFactory = new_id,
    ) -> None:
        self._uow = uow
        self._policy_engine = policy_engine
        self._dispatch_queue = dispatch_queue
        self._ids = ids

    def authorize(self, command: GovernedAction) -> AuthorizationResult:
        dispatch = False
        with self._uow as uow:
            aggregate = self._require_aggregate(uow.works.get_for_node(command.node_id))
            node = self._require_single_node(aggregate, command.node_id)
            self._require_execution_link(aggregate, command.node_id)
            if node.status is not WorkNodeStatus.READY:
                raise ValueError("governed action requires a ready work node")
            decision = self._decide(uow, aggregate, command)
            if decision.kind is DecisionKind.DENY:
                uow.works.update(
                    self._blocked(aggregate, command.node_id, decision.reason)
                )
                uow.commit()
                return decision
            if decision.kind is DecisionKind.REQUIRE_APPROVAL:
                approval = Approval.request(
                    approval_id=ApprovalId(self._ids("approval")),
                    workspace_id=aggregate.work.workspace_id,
                    work_id=aggregate.work.id,
                    node_id=node.id,
                    action=command.action,
                    resources=command.resources,
                    reason=command.reason,
                )
                uow.approvals.add(approval)
                uow.works.update(
                    self._with_node(aggregate, node.wait_for_approval())
                )
                uow.commit()
                return approval
            dispatch = True
        if dispatch and self._dispatch_queue is not None:
            self._dispatch_queue.enqueue(command.node_id)
        return decision

    def approve(self, approval_id: ApprovalId, *, decided_by: str) -> Approval:
        with self._uow as uow:
            approval = self._require_approval(uow.approvals.get(approval_id), approval_id)
            approved = approval.approve(decided_by=decided_by.strip())
            uow.approvals.decide(approved)
            uow.commit()
        return approved

    def reject(self, approval_id: ApprovalId, *, decided_by: str) -> Approval:
        with self._uow as uow:
            approval = self._require_approval(uow.approvals.get(approval_id), approval_id)
            rejected = approval.reject(decided_by=decided_by.strip())
            aggregate = self._require_aggregate(
                uow.works.get_for_node(approval.node_id)
            )
            node = self._require_single_node(aggregate, approval.node_id)
            link = self._require_execution_link(aggregate, approval.node_id)
            failed = replace(
                self._with_node(aggregate, node.approval_rejected()),
                work=replace(aggregate.work, status=WorkStatus.FAILED),
            )
            failed = self._with_link(
                failed,
                replace(
                    link,
                    status=ExecutionStatus.BLOCKED,
                    finished_at=datetime.now(UTC),
                    diagnostic_code="approval_rejected",
                ),
            )
            uow.approvals.decide(rejected)
            uow.works.update(failed)
            uow.company_events.append(
                CompanyEvent(
                    id=CompanyEventId(self._ids("company-event")),
                    workspace_id=approval.workspace_id,
                    work_id=approval.work_id,
                    node_id=approval.node_id,
                    attempt_id=None,
                    source_sequence=0,
                    event_type="approval.rejected",
                    summary="Approval rejected",
                    source="company",
                    observed_at=datetime.now(UTC),
                )
            )
            uow.commit()
        return rejected

    def resume_approved(self, approval_id: ApprovalId) -> PolicyDecision:
        with self._uow as uow:
            approval = self._require_approval(uow.approvals.get(approval_id), approval_id)
            if approval.status is not ApprovalStatus.APPROVED:
                raise ValueError("approval is not approved")
            aggregate = self._require_aggregate(
                uow.works.get_for_node(approval.node_id)
            )
            node = self._require_single_node(aggregate, approval.node_id)
            self._require_execution_link(aggregate, approval.node_id)
            if node.status is not WorkNodeStatus.WAITING_APPROVAL:
                raise ValueError("approved action is not waiting for approval")
            command = GovernedAction(
                node_id=approval.node_id,
                action=approval.action,
                resources=approval.resources,
                reason=approval.reason,
            )
            decision = self._decide(uow, aggregate, command)
            ready_node = node.approval_approved()
            if decision.kind is DecisionKind.DENY:
                ready = self._with_node(aggregate, ready_node)
                uow.works.update(ready)
                uow.works.update(
                    self._blocked(ready, approval.node_id, decision.reason)
                )
                uow.commit()
                return decision
            uow.works.update(self._with_node(aggregate, ready_node))
            uow.commit()
        if self._dispatch_queue is not None:
            self._dispatch_queue.enqueue(approval.node_id)
        return PolicyDecision(
            DecisionKind.ALLOW,
            "approved",
            frozenset(approval.resources),
        )

    def _decide(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        command: GovernedAction,
    ) -> PolicyDecision:
        node = self._require_single_node(aggregate, command.node_id)
        employee = uow.employees.get_revision(
            node.assigned_employee_id, node.employee_revision_id
        )
        if employee is None:
            return PolicyDecision(DecisionKind.DENY, "employee_not_found")
        workspace_grant = self._for_action(
            uow.workspace_grants.list_for_workspace(aggregate.work.workspace_id),
            command.action,
        )
        employee_grant = self._for_action(employee.grants, command.action)
        node_grant = self._for_action(
            uow.node_grants.list_for_node(node.id), command.action
        )
        runtime_grant = self._runtime_grant(
            employee.revision.runtime_profile,
            command.action,
            workspace_grant or employee_grant or node_grant,
        )
        decision = self._policy_engine.decide(
            ActionRequest(
                action=command.action,
                workspace_grant=workspace_grant,
                employee_grant=employee_grant,
                node_grant=node_grant,
                runtime_grant=runtime_grant,
            )
        )
        if decision.kind is DecisionKind.DENY:
            return decision
        effective = decision.effective_resources
        requested = frozenset(command.resources)
        if "*" not in effective and not requested.issubset(effective):
            return PolicyDecision(DecisionKind.DENY, "requested_resource_not_granted")
        return PolicyDecision(decision.kind, decision.reason, requested)

    @staticmethod
    def _runtime_grant(
        runtime_profile: str,
        action: str,
        resource_template: CapabilityGrant | None,
    ) -> CapabilityGrant | None:
        if action not in actions_for_runtime_profile(runtime_profile):
            return None
        level = ACTION_LEVELS.get(action)
        if level is None or resource_template is None:
            return None
        return CapabilityGrant(
            id=CapabilityGrantId(f"runtime:{runtime_profile}:{action}"),
            employee_revision_id=None,
            action=action,
            level=level,
            resource_kind=resource_template.resource_kind,
            resource_values=("*",),
            requires_approval=False,
        )

    @staticmethod
    def _for_action(
        grants: tuple[CapabilityGrant, ...], action: str
    ) -> CapabilityGrant | None:
        return next((grant for grant in grants if grant.action == action), None)

    @classmethod
    def _blocked(
        cls, aggregate: WorkAggregate, node_id: WorkNodeId, reason: str
    ) -> WorkAggregate:
        node = cls._require_single_node(aggregate, node_id)
        link = cls._require_execution_link(aggregate, node_id)
        if node.status is not WorkNodeStatus.READY:
            raise ValueError("only a ready node can be blocked before dispatch")
        if link.status is not ExecutionStatus.DISPATCH_PENDING:
            raise ValueError("governed action must be blocked before dispatch")
        blocked = replace(
            cls._with_node(aggregate, node.block_before_start(reason)),
            work=aggregate.work.block_before_start(),
        )
        return cls._with_link(
            blocked,
            replace(
                link,
                status=ExecutionStatus.BLOCKED,
                finished_at=datetime.now(UTC),
                diagnostic_code=reason,
            ),
        )

    @staticmethod
    def _require_aggregate(aggregate: WorkAggregate | None) -> WorkAggregate:
        if aggregate is None:
            raise LookupError("work node not found")
        return aggregate

    @staticmethod
    def _require_single_node(
        aggregate: WorkAggregate, node_id: WorkNodeId
    ) -> WorkNode:
        matching = tuple(node for node in aggregate.nodes if node.id == node_id)
        if len(matching) != 1:
            raise LookupError("work node not found")
        return matching[0]

    @staticmethod
    def _require_execution_link(
        aggregate: WorkAggregate, node_id: WorkNodeId
    ) -> ExecutionLink:
        matching = tuple(
            link for link in aggregate.execution_links if link.node_id == node_id
        )
        if len(matching) != 1:
            raise ValueError("governed node requires exactly one execution link")
        return matching[0]

    @staticmethod
    def _with_node(aggregate: WorkAggregate, replacement: WorkNode) -> WorkAggregate:
        return replace(
            aggregate,
            nodes=tuple(
                replacement if node.id == replacement.id else node
                for node in aggregate.nodes
            ),
        )

    @staticmethod
    def _with_link(
        aggregate: WorkAggregate, replacement: ExecutionLink
    ) -> WorkAggregate:
        return replace(
            aggregate,
            execution_links=tuple(
                replacement if link.id == replacement.id else link
                for link in aggregate.execution_links
            ),
        )

    @staticmethod
    def _require_approval(
        approval: Approval | None, approval_id: ApprovalId
    ) -> Approval:
        if approval is None:
            raise LookupError(f"approval not found: {approval_id}")
        return approval
