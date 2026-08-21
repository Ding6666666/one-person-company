from dataclasses import dataclass, replace
from datetime import UTC, datetime

from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.delegation import (
    Delegation,
    DelegationProposal,
    apply_delegation,
)
from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    CapabilityGrantId,
    CompanyEventId,
    DelegationId,
    ExecutionLinkId,
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
)
from dsh_company.policy.runtime_profiles import actions_for_runtime_profile

from .ports import (
    EmployeeRecord,
    GovernanceUnitOfWork,
    IdFactory,
    WorkAggregate,
    WorkDispatchQueue,
)


class DelegationDenied(ValueError):
    """A delegation proposal exceeded its verified Company bounds."""


@dataclass(frozen=True, slots=True)
class DelegationCommand:
    source_node_id: WorkNodeId
    proposal: DelegationProposal


@dataclass(frozen=True, slots=True)
class DelegationResult:
    delegation: Delegation
    parent_node: WorkNode
    target_node: WorkNode


@dataclass(frozen=True, slots=True)
class DelegationCompletion:
    delegation: Delegation
    parent_node: WorkNode
    input_references: tuple[ArtifactReferenceId, ...]


class DelegationService:
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

    def propose(self, command: DelegationCommand) -> DelegationResult:
        target_node_id: WorkNodeId | None = None
        result: DelegationResult | None = None
        with self._uow as uow:
            aggregate = self._require_aggregate(
                uow.works.get_for_node(command.source_node_id), command.source_node_id
            )
            source = self._require_node(aggregate, command.source_node_id)
            try:
                proposer, target = self._validate_participants(
                    uow, aggregate, source, command.proposal
                )
                self._require_allowed(
                    self._decision(
                        uow,
                        aggregate,
                        source,
                        proposer,
                        action="work.delegate",
                        resources=command.proposal.resource_values,
                    )
                )
                target_grants = tuple(
                    self._target_grant(
                        uow,
                        aggregate,
                        source,
                        target,
                        action,
                        command.proposal.resource_values,
                    )
                    for action in command.proposal.required_actions
                )
                revision, delegation = apply_delegation(
                    aggregate.graph,
                    aggregate.nodes,
                    command.proposal,
                    workspace_id=aggregate.work.workspace_id,
                    source_node_id=source.id,
                    target_employee_revision_id=target.revision.id,
                    ids=self._ids,
                )
                target_node = revision.nodes[-1]
                parent_node = source.block(
                    self._active_attempt(source), "waiting_delegation"
                )
                parent_link = self._active_link(aggregate, source)
                blocked_parent_link = parent_link.block(
                    parent_link.attempt_id, "waiting_delegation"
                )
                child_attempt_id = AttemptId(self._ids("attempt"))
                child_link = ExecutionLink.dispatch(
                    execution_link_id=ExecutionLinkId(self._ids("execution-link")),
                    attempt_id=child_attempt_id,
                    node_id=target_node.id,
                    command_id=f"{aggregate.work.command_id}:delegation:{delegation.id}",
                    dsh_session_id=target.binding.dsh_session_id,
                )
                updated_nodes = tuple(
                    parent_node if node.id == source.id else node
                    for node in revision.nodes
                )
                updated_links = tuple(
                    blocked_parent_link if link.id == parent_link.id else link
                    for link in aggregate.execution_links
                ) + (child_link,)
                updated = replace(
                    aggregate,
                    work=replace(
                        aggregate.work,
                        current_graph_revision_id=revision.graph.id,
                    ),
                    graph=revision.graph,
                    nodes=updated_nodes,
                    execution_links=updated_links,
                )
                uow.works.add_revision(revision.graph, revision.nodes)
                uow.node_grants.replace(target_node.id, target_grants)
                uow.delegations.add(delegation)
                uow.works.update(updated)
                uow.commit()
                target_node_id = target_node.id
                result = DelegationResult(delegation, parent_node, target_node)
            except DelegationDenied as denied:
                self._record_rejection(uow, aggregate, source, command.proposal, str(denied))
                uow.commit()
                raise

        if target_node_id is not None and self._dispatch_queue is not None:
            self._dispatch_queue.enqueue(target_node_id)
        if result is None:
            raise RuntimeError("delegation result was not produced")
        return result

    def child_completed(
        self,
        delegation_id: DelegationId,
        artifact_reference_id: ArtifactReferenceId,
    ) -> DelegationCompletion:
        parent_node_id: WorkNodeId | None = None
        result: DelegationCompletion | None = None
        with self._uow as uow:
            delegation = uow.delegations.get(delegation_id)
            if delegation is None:
                raise LookupError(f"delegation not found: {delegation_id}")
            if delegation.status != "accepted":
                raise ValueError("delegation is not accepted")
            if delegation.target_node_id is None:
                raise ValueError("accepted delegation has no target node")
            aggregate = uow.works.get(delegation.work_id)
            if aggregate is None:
                raise LookupError(f"work not found: {delegation.work_id}")
            parent = self._require_node(aggregate, delegation.source_node_id)
            child = self._require_node(aggregate, delegation.target_node_id)
            if (
                parent.status is not WorkNodeStatus.BLOCKED
                or parent.failure_code != "waiting_delegation"
            ):
                raise ValueError("parent is not waiting for delegation")
            if child.status is not WorkNodeStatus.COMPLETED:
                raise ValueError("delegated child is not completed")
            artifact = next(
                (
                    item
                    for item in aggregate.artifacts
                    if item.id == artifact_reference_id
                ),
                None,
            )
            if artifact is None or artifact.workspace_id != delegation.workspace_id:
                raise ValueError("delegated artifact reference not found")
            child_links = tuple(
                link
                for link in aggregate.execution_links
                if link.node_id == child.id
                and link.attempt_id == artifact.source_attempt_id
                and link.status is ExecutionStatus.COMPLETED
            )
            if len(child_links) != 1:
                raise ValueError("delegated artifact does not belong to completed child")
            parent_record = uow.employees.get_revision(
                parent.assigned_employee_id, parent.employee_revision_id
            )
            if parent_record is None:
                raise RuntimeError("frozen parent employee revision not found")
            references = (*parent.input_references, artifact_reference_id)
            resumed_parent = replace(
                parent,
                status=WorkNodeStatus.READY,
                active_attempt_id=None,
                failure_code=None,
                version=parent.version + 1,
                input_references=references,
            )
            attempt_id = AttemptId(self._ids("attempt"))
            resumed_link = ExecutionLink.dispatch(
                execution_link_id=ExecutionLinkId(self._ids("execution-link")),
                attempt_id=attempt_id,
                node_id=parent.id,
                command_id=f"{aggregate.work.command_id}:resume:{delegation.id}:{attempt_id}",
                dsh_session_id=parent_record.binding.dsh_session_id,
            )
            updated = replace(
                aggregate,
                nodes=tuple(
                    resumed_parent if node.id == parent.id else node
                    for node in aggregate.nodes
                ),
                execution_links=(*aggregate.execution_links, resumed_link),
            )
            completed_delegation = replace(delegation, status="completed")
            uow.works.update(updated)
            uow.delegations.update(completed_delegation)
            uow.commit()
            parent_node_id = parent.id
            result = DelegationCompletion(
                completed_delegation, resumed_parent, references
            )

        if parent_node_id is not None and self._dispatch_queue is not None:
            self._dispatch_queue.enqueue(parent_node_id)
        if result is None:
            raise RuntimeError("delegation completion was not produced")
        return result

    def child_completed_for_node(
        self,
        target_node_id: WorkNodeId,
        artifact_reference_id: ArtifactReferenceId,
    ) -> DelegationCompletion | None:
        with self._uow as uow:
            delegation = uow.delegations.get_accepted_for_target(target_node_id)
        if delegation is None:
            return None
        return self.child_completed(delegation.id, artifact_reference_id)

    def _validate_participants(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        source: WorkNode,
        proposal: DelegationProposal,
    ) -> tuple[EmployeeRecord, EmployeeRecord]:
        if source.assigned_employee_id != proposal.proposer_employee_id:
            raise DelegationDenied("proposer_not_source_owner")
        if source.status is not WorkNodeStatus.RUNNING:
            raise DelegationDenied("source_not_running")
        proposer_current = uow.employees.get(proposal.proposer_employee_id)
        proposer = uow.employees.get_revision(
            proposal.proposer_employee_id, source.employee_revision_id
        )
        if proposer_current is None or proposer is None:
            raise DelegationDenied("proposer_not_found")
        if proposer_current.employee.workspace_id != aggregate.work.workspace_id:
            raise DelegationDenied("proposer_workspace_mismatch")
        if proposer_current.employee.status is not EmployeeStatus.ACTIVE:
            raise DelegationDenied("proposer_not_active")
        target = uow.employees.get(proposal.target_employee_id)
        if target is None:
            raise DelegationDenied("target_not_found")
        if target.employee.workspace_id != aggregate.work.workspace_id:
            raise DelegationDenied("target_workspace_mismatch")
        if target.employee.status is not EmployeeStatus.ACTIVE:
            raise DelegationDenied("target_not_active")
        return proposer, target

    def _target_grant(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        source: WorkNode,
        target: EmployeeRecord,
        action: str,
        resources: tuple[str, ...],
    ) -> CapabilityGrant:
        decision = self._decision(
            uow,
            aggregate,
            source,
            target,
            action=action,
            resources=resources,
        )
        self._require_allowed(decision)
        template = self._for_action(
            uow.node_grants.list_for_node(source.id), action
        )
        level = ACTION_LEVELS.get(action)
        if template is None or level is None:
            raise DelegationDenied("node_not_granted")
        return CapabilityGrant(
            id=CapabilityGrantId(self._ids("capability-grant")),
            employee_revision_id=None,
            action=action,
            level=level,
            resource_kind=template.resource_kind,
            resource_values=resources,
            requires_approval=False,
        )

    def _decision(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        source: WorkNode,
        employee: EmployeeRecord,
        *,
        action: str,
        resources: tuple[str, ...],
    ) -> PolicyDecision:
        workspace_grant = self._for_action(
            uow.workspace_grants.list_for_workspace(aggregate.work.workspace_id), action
        )
        employee_grant = self._for_action(employee.grants, action)
        node_grant = self._for_action(uow.node_grants.list_for_node(source.id), action)
        runtime_grant = self._runtime_grant(
            employee.revision.runtime_profile,
            action,
            workspace_grant or employee_grant or node_grant,
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
        if decision.kind is not DecisionKind.ALLOW:
            return decision
        requested = frozenset(resources)
        if not requested:
            return PolicyDecision(DecisionKind.DENY, "resource_scope_empty")
        if (
            "*" not in decision.effective_resources
            and not requested.issubset(decision.effective_resources)
        ):
            return PolicyDecision(DecisionKind.DENY, "resource_scope_empty")
        return PolicyDecision(DecisionKind.ALLOW, decision.reason, requested)

    @staticmethod
    def _require_allowed(decision: PolicyDecision) -> None:
        if decision.kind is DecisionKind.REQUIRE_APPROVAL:
            raise DelegationDenied("approval_required")
        if decision.kind is DecisionKind.DENY:
            raise DelegationDenied(decision.reason)

    def _record_rejection(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        source: WorkNode,
        proposal: DelegationProposal,
        reason: str,
    ) -> None:
        if source.status is WorkNodeStatus.RUNNING:
            parent_link = self._active_link(aggregate, source)
            blocked_source = source.block(
                parent_link.attempt_id, "delegation_rejected"
            )
            blocked_link = parent_link.block(
                parent_link.attempt_id, "delegation_rejected"
            )
            uow.works.update(
                replace(
                    aggregate,
                    work=aggregate.work.block(),
                    nodes=tuple(
                        blocked_source if node.id == source.id else node
                        for node in aggregate.nodes
                    ),
                    execution_links=tuple(
                        blocked_link if link.id == parent_link.id else link
                        for link in aggregate.execution_links
                    ),
                )
            )
        rejected = Delegation(
            id=DelegationId(self._ids("delegation")),
            workspace_id=aggregate.work.workspace_id,
            work_id=aggregate.work.id,
            source_node_id=source.id,
            target_node_id=None,
            proposer_employee_id=proposal.proposer_employee_id,
            target_employee_id=proposal.target_employee_id,
            graph_revision_id=aggregate.graph.id,
            status="rejected",
            created_at=datetime.now(UTC),
        )
        uow.delegations.add(rejected)
        uow.company_events.append(
            CompanyEvent(
                id=CompanyEventId(self._ids("company-event")),
                workspace_id=aggregate.work.workspace_id,
                work_id=aggregate.work.id,
                node_id=source.id,
                attempt_id=None,
                source_sequence=0,
                event_type="delegation.rejected",
                summary=f"Delegation rejected: {reason}",
                source="company",
                observed_at=datetime.now(UTC),
            )
        )

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

    @staticmethod
    def _require_aggregate(
        aggregate: WorkAggregate | None, node_id: WorkNodeId
    ) -> WorkAggregate:
        if aggregate is None:
            raise LookupError(f"work node not found: {node_id}")
        return aggregate

    @staticmethod
    def _require_node(aggregate: WorkAggregate, node_id: WorkNodeId) -> WorkNode:
        matches = tuple(node for node in aggregate.nodes if node.id == node_id)
        if len(matches) != 1:
            raise LookupError(f"work node not found: {node_id}")
        return matches[0]

    @staticmethod
    def _active_attempt(node: WorkNode) -> AttemptId:
        if node.active_attempt_id is None:
            raise DelegationDenied("source_attempt_missing")
        return node.active_attempt_id

    @staticmethod
    def _active_link(aggregate: WorkAggregate, node: WorkNode) -> ExecutionLink:
        links = tuple(
            link
            for link in aggregate.execution_links
            if link.node_id == node.id
            and link.attempt_id == node.active_attempt_id
            and link.status is ExecutionStatus.RUNNING
        )
        if len(links) != 1:
            raise DelegationDenied("source_attempt_missing")
        return links[0]
