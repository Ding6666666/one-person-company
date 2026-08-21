from dataclasses import replace

from dsh_company.application.ports import (
    ConcurrentWorkUpdate,
    GovernanceUnitOfWork,
    GovernanceUnitOfWorkFactory,
    IdFactory,
    WorkAggregate,
    WorkCoordinator,
)
from dsh_company.domain.approval import Approval
from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.ids import (
    ApprovalId,
    ArtifactReferenceId,
    AttemptId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    new_id,
)
from dsh_company.domain.policy import (
    ActionRequest,
    DecisionKind,
    PolicyDecision,
    PolicyEngine,
)
from dsh_company.domain.work import (
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkEdgeKind,
    WorkNode,
    WorkNodeStatus,
    project_graph_work_status,
)

_TERMINAL_NODE_STATUSES = {
    WorkNodeStatus.COMPLETED,
    WorkNodeStatus.FAILED,
    WorkNodeStatus.CANCELLED,
}
_CLOSED_FAILURE_CODES = {
    "approval_rejected",
    "cancel_unconfirmed",
    "control_request_unhandled",
    "dependency_failed",
    "gateway_error",
    "runtime_error",
    "runtime_process_lost",
}


class DurableGraphEngine:
    """Derive runnable graph nodes from durable Company facts; never run an LLM."""

    def __init__(
        self,
        uow_factory: GovernanceUnitOfWorkFactory,
        coordinator: WorkCoordinator,
        *,
        policy_engine: PolicyEngine | None = None,
        runtime_concurrency: int = 4,
        id_factory: IdFactory = new_id,
    ) -> None:
        if runtime_concurrency < 1:
            raise ValueError("runtime concurrency must be positive")
        self._uow_factory = uow_factory
        self._coordinator = coordinator
        self._policy_engine = policy_engine or PolicyEngine()
        self._runtime_concurrency = runtime_concurrency
        self._id_factory = id_factory

    def start(self, graph_revision_id: WorkGraphRevisionId) -> None:
        with self._uow_factory() as uow:
            revision = uow.works.get_revision(graph_revision_id)
            if revision is None:
                raise LookupError("work graph revision not found")
            graph, _ = revision
            aggregate = uow.works.get(graph.work_id)
            if aggregate is None or aggregate.work.current_graph_revision_id != graph_revision_id:
                raise ValueError("only the current graph revision can be started")
        self.reconcile(graph.work_id)

    def dispatch_ready_nodes(self, work_id: WorkId) -> tuple[ExecutionLink, ...]:
        for _ in range(3):
            try:
                dispatched = self._prepare_dispatches(work_id)
                break
            except ConcurrentWorkUpdate:
                continue
        else:
            raise ConcurrentWorkUpdate(str(work_id))
        for link in dispatched:
            self._coordinator.enqueue(link.node_id)
        return dispatched

    def reconcile(self, work_id: WorkId) -> None:
        self.dispatch_ready_nodes(work_id)

    def record_completion(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        result_reference: ArtifactReferenceId,
    ) -> None:
        with self._uow_factory() as uow:
            aggregate = self._require_aggregate(uow.works.get_for_node(node_id))
            node = self._node(aggregate, node_id)
            link = self._link(aggregate, node_id, attempt_id)
            if node.status is WorkNodeStatus.COMPLETED and link.status is ExecutionStatus.COMPLETED:
                work_id = aggregate.work.id
            else:
                completed_node = node.complete(attempt_id, result_reference)
                completed_link = link.complete(attempt_id, result_reference)
                updated = replace(
                    aggregate,
                    nodes=self._replace_node(aggregate, completed_node),
                    execution_links=self._replace_link(aggregate, completed_link),
                )
                updated = replace(updated, work=self._project_work(updated))
                uow.works.update(updated)
                uow.commit()
                work_id = updated.work.id
        self.reconcile(work_id)

    def record_failure(self, node_id: WorkNodeId, attempt_id: AttemptId, reason: str) -> None:
        failure_code = reason if reason in _CLOSED_FAILURE_CODES else "runtime_error"
        with self._uow_factory() as uow:
            aggregate = self._require_aggregate(uow.works.get_for_node(node_id))
            node = self._node(aggregate, node_id)
            link = self._link(aggregate, node_id, attempt_id)
            if link.status is ExecutionStatus.FAILED:
                work_id = aggregate.work.id
            else:
                used_attempts = max(
                    node.attempt_count,
                    sum(item.node_id == node_id for item in aggregate.execution_links),
                )
                failed_node = (
                    node.block(attempt_id, failure_code)
                    if used_attempts < node.max_attempts
                    else node.fail(attempt_id, failure_code)
                )
                updated = replace(
                    aggregate,
                    nodes=self._replace_node(aggregate, failed_node),
                    execution_links=self._replace_link(
                        aggregate, link.fail(attempt_id, failure_code)
                    ),
                )
                updated = replace(updated, work=self._project_work(updated))
                uow.works.update(updated)
                uow.commit()
                work_id = updated.work.id
        self.reconcile(work_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        self._coordinator.request_cancel(node_id)

    def _prepare_dispatches(self, work_id: WorkId) -> tuple[ExecutionLink, ...]:
        with self._uow_factory() as uow:
            uow.works.lock_orchestration_capacity()
            aggregate = self._require_aggregate(uow.works.get(work_id))
            capacity = max(
                0,
                self._runtime_concurrency - uow.works.count_active_execution_links(),
            )
            nodes = list(aggregate.nodes)
            links = list(aggregate.execution_links)
            ready_links: list[ExecutionLink] = []
            changed = False

            for position, node in enumerate(nodes):
                if node.status not in {WorkNodeStatus.DRAFT, WorkNodeStatus.BLOCKED}:
                    continue
                if node.status is WorkNodeStatus.BLOCKED and (
                    node.failure_code in {"dependency_failed", "waiting_delegation"}
                    or node.attempt_count >= node.max_attempts
                ):
                    continue
                eligibility = self._edge_eligibility(uow, aggregate, node)
                if eligibility.blocked:
                    replacement = self._block_without_attempt(node, "dependency_failed")
                    if replacement != node:
                        nodes[position] = replacement
                        changed = True
                    continue
                if not eligibility.ready:
                    continue

                decision = self._policy_decision(uow, aggregate, node)
                if decision.kind is DecisionKind.DENY:
                    replacement = self._block_without_attempt(node, decision.reason)
                    if replacement != node:
                        nodes[position] = replacement
                        changed = True
                    continue
                if capacity == 0:
                    continue

                prepared = replace(
                    node,
                    status=WorkNodeStatus.READY,
                    active_attempt_id=None,
                    failure_code=None,
                    input_references=eligibility.inputs,
                    attempt_count=node.attempt_count + 1,
                    version=node.version + 1,
                )
                link = self._new_link(aggregate, prepared, uow)
                if decision.kind is DecisionKind.REQUIRE_APPROVAL:
                    prepared = replace(
                        prepared,
                        status=WorkNodeStatus.WAITING_APPROVAL,
                    )
                    uow.approvals.add(
                        Approval.request(
                            approval_id=ApprovalId(self._id_factory("approval")),
                            workspace_id=aggregate.work.workspace_id,
                            work_id=aggregate.work.id,
                            node_id=node.id,
                            action=decision.reason.removeprefix("approval_required:"),
                            resources=node.resource_values,
                            reason="Graph node requires approval",
                        )
                    )
                else:
                    ready_links.append(link)
                capacity -= 1
                nodes[position] = prepared
                links.append(link)
                changed = True

            if not changed:
                projected_work = self._project_work(aggregate)
                if projected_work == aggregate.work:
                    return ()
                uow.works.update(replace(aggregate, work=projected_work))
                uow.commit()
                return ()
            updated = replace(
                aggregate,
                nodes=tuple(nodes),
                execution_links=tuple(links),
            )
            updated = replace(updated, work=self._project_work(updated))
            uow.works.update(updated)
            uow.commit()
        return tuple(ready_links)

    def _edge_eligibility(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        node: WorkNode,
    ) -> "_Eligibility":
        by_id = {item.id: item for item in aggregate.nodes}
        incoming = tuple(edge for edge in aggregate.graph.edges if edge.to_node_id == node.id)
        inputs = list(node.input_references)
        for kind in WorkEdgeKind:
            edges = tuple(edge for edge in incoming if edge.kind is kind)
            if not edges:
                continue
            upstream = tuple(by_id[edge.from_node_id] for edge in edges)
            if kind in {WorkEdgeKind.DEPENDS_ON, WorkEdgeKind.REVIEWS}:
                if any(
                    item.status in {WorkNodeStatus.FAILED, WorkNodeStatus.CANCELLED}
                    for item in upstream
                ):
                    return _Eligibility(False, True, tuple(inputs))
                if not all(item.status is WorkNodeStatus.COMPLETED for item in upstream):
                    return _Eligibility(False, False, tuple(inputs))
                if kind is WorkEdgeKind.REVIEWS:
                    for item in upstream:
                        inputs.extend(item.output_references)
            elif kind is WorkEdgeKind.SUMMARIZES:
                if not all(item.status in _TERMINAL_NODE_STATUSES for item in upstream):
                    return _Eligibility(False, False, tuple(inputs))
                if not any(item.status is WorkNodeStatus.COMPLETED for item in upstream):
                    return _Eligibility(False, True, tuple(inputs))
                for item in upstream:
                    if item.status is WorkNodeStatus.COMPLETED:
                        inputs.extend(item.output_references)
                    else:
                        inputs.append(item.id)
            else:
                delegations = uow.delegations.list_for_work(aggregate.work.id)
                target = next(
                    (item for item in delegations if item.target_node_id == node.id),
                    None,
                )
                if target is None or target.status == "proposed":
                    return _Eligibility(False, False, tuple(inputs))
                if target.status == "rejected":
                    return _Eligibility(False, True, tuple(inputs))
        return _Eligibility(True, False, tuple(dict.fromkeys(inputs)))

    def _policy_decision(
        self,
        uow: GovernanceUnitOfWork,
        aggregate: WorkAggregate,
        node: WorkNode,
    ) -> PolicyDecision:
        if not node.required_actions:
            return PolicyDecision(DecisionKind.ALLOW, "granted")
        employee = uow.employees.get_revision(node.assigned_employee_id, node.employee_revision_id)
        if employee is None:
            return PolicyDecision(DecisionKind.DENY, "employee_not_found")
        workspace_grants = uow.workspace_grants.list_for_workspace(aggregate.work.workspace_id)
        node_grants = uow.node_grants.list_for_node(node.id)
        for action in node.required_actions:
            workspace_grant = self._for_action(workspace_grants, action)
            employee_grant = self._for_action(employee.grants, action)
            node_grant = self._for_action(node_grants, action)
            runtime_grant = self._policy_engine.runtime_grant(
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
            if decision.kind is DecisionKind.DENY:
                return decision
            requested = frozenset(node.resource_values)
            if (
                requested
                and "*" not in decision.effective_resources
                and not requested.issubset(decision.effective_resources)
            ):
                return PolicyDecision(DecisionKind.DENY, "requested_resource_not_granted")
            if decision.kind is DecisionKind.REQUIRE_APPROVAL:
                return PolicyDecision(
                    DecisionKind.REQUIRE_APPROVAL,
                    f"approval_required:{action}",
                    requested,
                )
        return PolicyDecision(DecisionKind.ALLOW, "granted")

    @staticmethod
    def _for_action(grants: tuple[CapabilityGrant, ...], action: str) -> CapabilityGrant | None:
        return next((grant for grant in grants if grant.action == action), None)

    @staticmethod
    def _block_without_attempt(node: WorkNode, reason: str) -> WorkNode:
        if node.status is WorkNodeStatus.BLOCKED and node.failure_code == reason:
            return node
        return replace(
            node,
            status=WorkNodeStatus.BLOCKED,
            active_attempt_id=None,
            failure_code=reason,
            version=node.version + 1,
        )

    @staticmethod
    def _new_link(
        aggregate: WorkAggregate,
        node: WorkNode,
        uow: GovernanceUnitOfWork,
    ) -> ExecutionLink:
        employee = uow.employees.get_revision(node.assigned_employee_id, node.employee_revision_id)
        if employee is None:
            raise RuntimeError("frozen employee revision not found")
        stem = f"{aggregate.work.id}:{aggregate.graph.id}:{node.id}:attempt-{node.attempt_count}"
        return ExecutionLink.dispatch(
            execution_link_id=ExecutionLinkId(f"{stem}:link"),
            attempt_id=AttemptId(stem),
            node_id=node.id,
            command_id=stem,
            dsh_session_id=employee.binding.dsh_session_id,
        )

    @staticmethod
    def _project_work(aggregate: WorkAggregate) -> Work:
        return replace(
            aggregate.work,
            status=project_graph_work_status(aggregate.graph, aggregate.nodes),
        )

    @staticmethod
    def _require_aggregate(aggregate: WorkAggregate | None) -> WorkAggregate:
        if aggregate is None:
            raise LookupError("work not found")
        return aggregate

    @staticmethod
    def _node(aggregate: WorkAggregate, node_id: WorkNodeId) -> WorkNode:
        matches = tuple(item for item in aggregate.nodes if item.id == node_id)
        if len(matches) != 1:
            raise LookupError("work node not found in current graph")
        return matches[0]

    @staticmethod
    def _link(
        aggregate: WorkAggregate, node_id: WorkNodeId, attempt_id: AttemptId
    ) -> ExecutionLink:
        matches = tuple(
            item
            for item in aggregate.execution_links
            if item.node_id == node_id and item.attempt_id == attempt_id
        )
        if len(matches) != 1:
            raise LookupError("work attempt not found in current graph")
        return matches[0]

    @staticmethod
    def _replace_node(aggregate: WorkAggregate, replacement: WorkNode) -> tuple[WorkNode, ...]:
        return tuple(replacement if item.id == replacement.id else item for item in aggregate.nodes)

    @staticmethod
    def _replace_link(
        aggregate: WorkAggregate, replacement: ExecutionLink
    ) -> tuple[ExecutionLink, ...]:
        return tuple(
            replacement if item.id == replacement.id else item for item in aggregate.execution_links
        )


class _Eligibility:
    __slots__ = ("ready", "blocked", "inputs")

    def __init__(
        self,
        ready: bool,
        blocked: bool,
        inputs: tuple[ArtifactReferenceId | WorkNodeId, ...],
    ) -> None:
        self.ready = ready
        self.blocked = blocked
        self.inputs = inputs
