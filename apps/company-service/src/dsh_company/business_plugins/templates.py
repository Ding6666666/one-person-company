from datetime import UTC, datetime

from dsh_company.application.ports import (
    DuplicateCommand,
    GovernanceUnitOfWorkFactory,
    WorkAggregate,
)
from dsh_company.domain.capabilities import CapabilityGrant
from dsh_company.domain.ids import (
    CapabilityGrantId,
    EmployeeId,
    WorkGraphRevisionId,
    WorkId,
    WorkspaceId,
    new_id,
)
from dsh_company.domain.policy import PolicyEngine
from dsh_company.domain.work import Work, WorkStatus
from dsh_company.orchestration.contracts import OrchestrationEngine
from dsh_company.orchestration.graph_validation import GraphValidator
from dsh_company.orchestration.selector import EligibleEmployee, EmployeeCandidate, Selector
from dsh_company.orchestration.strategies import (
    ExplicitEdge,
    ExplicitNode,
    StrategyFactory,
)

from .manifest import TemplateNode, WorkTemplate
from .registry import BusinessPluginRegistry


class InvalidTemplateAssignment(ValueError):
    """The caller did not provide an exact, eligible Employee assignment."""


class TemplateInstantiator:
    def __init__(
        self,
        uow_factory: GovernanceUnitOfWorkFactory,
        registry: BusinessPluginRegistry,
        orchestration_engine: OrchestrationEngine,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._orchestration_engine = orchestration_engine
        policy_engine = PolicyEngine(registry.action_catalog)
        self._selector = Selector(policy_engine)
        self._policy_engine = policy_engine
        self._strategy_factory = StrategyFactory(GraphValidator(registry.action_catalog))

    def instantiate(
        self,
        *,
        workspace_id: WorkspaceId,
        plugin_id: str,
        template_id: str,
        command_id: str,
        employee_assignments: dict[str, str],
    ) -> WorkAggregate:
        template = self._template(plugin_id, template_id)
        required_slots = {slot.slot_id for slot in template.employee_slots}
        if set(employee_assignments) != required_slots:
            raise InvalidTemplateAssignment("every employee slot must be assigned exactly once")
        normalized_command_id = command_id.strip()
        if not normalized_command_id:
            raise InvalidTemplateAssignment("command_id must not be blank")

        try:
            with self._uow_factory() as uow:
                if uow.workspaces.get(workspace_id) is None:
                    raise LookupError("workspace not found")
                existing = uow.works.get_by_command(workspace_id, normalized_command_id)
                if existing is not None:
                    aggregate = existing
                else:
                    records = uow.employees.list_for_workspace(workspace_id)
                    workspace_grants = uow.workspace_grants.list_for_workspace(workspace_id)
                    candidates = tuple(
                        EmployeeCandidate(
                            employee=record.employee,
                            revision=record.revision,
                            binding=record.binding,
                            employee_grants=record.grants,
                            workspace_grants=workspace_grants,
                            node_grants=(),
                        )
                        for record in records
                    )
                    selected = {
                        node.key: self._select(
                            candidates,
                            workspace_id,
                            EmployeeId(employee_assignments[node.employee_slot]),
                            self._node_grants(node),
                            node.required_actions,
                            node.resource_values,
                            node.resource_kinds,
                        )
                        for node in template.nodes
                    }
                    created_at = datetime.now(UTC)
                    work = Work(
                        id=WorkId(new_id("work")),
                        workspace_id=workspace_id,
                        command_id=normalized_command_id,
                        objective=template.display_name,
                        status=WorkStatus.QUEUED,
                        current_graph_revision_id=WorkGraphRevisionId(new_id("work-graph")),
                        created_at=created_at,
                    )
                    aggregate = self._build(work, template, selected)
                    uow.works.add(aggregate)
                    for work_node, template_node in zip(
                        aggregate.nodes, template.nodes, strict=True
                    ):
                        uow.node_grants.replace(work_node.id, self._node_grants(template_node))
                    uow.commit()
        except DuplicateCommand:
            with self._uow_factory() as uow:
                winner = uow.works.get_by_command(workspace_id, normalized_command_id)
            if winner is None:
                raise
            aggregate = winner

        self._orchestration_engine.start(aggregate.graph.id)
        with self._uow_factory() as uow:
            return uow.works.get(aggregate.work.id) or aggregate

    def _template(self, plugin_id: str, template_id: str) -> WorkTemplate:
        registration = self._registry.get(plugin_id)
        if registration is None:
            raise LookupError("business plugin not found")
        template = next(
            (item for item in registration.manifest.templates if item.template_id == template_id),
            None,
        )
        if template is None:
            raise LookupError("business plugin template not found")
        return template

    def _select(
        self,
        candidates: tuple[EmployeeCandidate, ...],
        workspace_id: WorkspaceId,
        employee_id: EmployeeId,
        node_grants: tuple[CapabilityGrant, ...],
        required_actions: tuple[str, ...],
        resources: tuple[str, ...],
        resource_kinds: tuple[str, ...],
    ) -> EligibleEmployee:
        scoped_candidates = tuple(
            EmployeeCandidate(
                employee=candidate.employee,
                revision=candidate.revision,
                binding=candidate.binding,
                employee_grants=candidate.employee_grants,
                workspace_grants=candidate.workspace_grants,
                node_grants=node_grants,
            )
            for candidate in candidates
        )
        eligible = self._selector.eligible(
            employees=scoped_candidates,
            workspace_id=workspace_id,
            required_actions=required_actions,
            resources=resources,
            resource_kinds=resource_kinds,
            delegation_allowlist=frozenset({employee_id}),
            user_order=(employee_id,),
            allow_approval_required=True,
        )
        if not eligible:
            raise InvalidTemplateAssignment("employee_ineligible")
        return eligible[0]

    def _build(
        self,
        work: Work,
        template: WorkTemplate,
        selected: dict[str, EligibleEmployee],
    ) -> WorkAggregate:
        return self._strategy_factory.graph(
            work=work,
            nodes=tuple(
                ExplicitNode(
                    key=node.key,
                    participant=selected[node.key],
                    objective=node.objective,
                    criteria=node.acceptance_criteria,
                )
                for node in template.nodes
            ),
            edges=tuple(
                ExplicitEdge(edge.from_key, edge.to_key, edge.kind) for edge in template.edges
            ),
        )

    def _node_grants(self, node: TemplateNode) -> tuple[CapabilityGrant, ...]:
        grants: list[CapabilityGrant] = []
        for action, resource_kind in zip(node.required_actions, node.resource_kinds, strict=True):
            level = self._policy_engine.required_level(action)
            if level is None:
                raise InvalidTemplateAssignment("unknown_plugin_action")
            grants.append(
                CapabilityGrant(
                    id=CapabilityGrantId(f"template:{action}"),
                    employee_revision_id=None,
                    action=action,
                    level=level,
                    resource_kind=resource_kind,
                    resource_values=node.resource_values,
                    requires_approval=False,
                )
            )
        return tuple(grants)
