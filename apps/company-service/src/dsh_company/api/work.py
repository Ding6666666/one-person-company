from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, status

from dsh_company.application.chat_service import ChatService
from dsh_company.application.ports import DuplicateCommand, WorkAggregate
from dsh_company.application.work_commands import CreateDirectWork
from dsh_company.application.work_service import WorkCancellationNotSupported, WorkService
from dsh_company.business_plugins.registry import BusinessPluginRegistry
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
from dsh_company.orchestration.graph_validation import GraphValidator, InvalidGraph
from dsh_company.orchestration.selector import EligibleEmployee, EmployeeCandidate, Selector
from dsh_company.orchestration.strategies import (
    ExplicitEdge,
    ExplicitNode,
    StarChild,
    StrategyFactory,
)

from .errors import ConflictError, ErrorEnvelope, ResourceNotFoundError, UnprocessableEntityError
from .schemas import (
    BattleStrategyInput,
    CompanyEvent,
    DirectStrategyInput,
    DirectWorkCreate,
    GraphNodeInput,
    GraphStrategyInput,
    StarStrategyInput,
    StrategyWorkCreate,
    WorkProjection,
)

router = APIRouter()
not_found_response: dict[int | str, dict[str, Any]] = {404: {"model": ErrorEnvelope}}
strategy_error_responses: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


def _work_service(request: Request) -> WorkService:
    assembly = request.app.state.assembly
    return WorkService(assembly.uow_factory(), assembly.work_coordinator)


WorkServiceDependency = Annotated[WorkService, Depends(_work_service)]


@router.post(
    "/workspaces/{workspace_id}/works",
    response_model=WorkProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**not_found_response, **strategy_error_responses},
)
def create_work(
    request: Request,
    workspace_id: str,
    body: DirectWorkCreate | StrategyWorkCreate,
    service: WorkServiceDependency,
) -> WorkProjection:
    if isinstance(body, DirectWorkCreate):
        projection = _create_legacy_direct(workspace_id, body, service)
        ChatService(
            request.app.state.assembly.uow_factory(),
            request.app.state.assembly.chat_dispatch_queue,
        ).ensure_work_card(WorkId(projection.id))
        return projection
    aggregate, _created = _create_strategy_work(request, WorkspaceId(workspace_id), body)
    ChatService(
        request.app.state.assembly.uow_factory(),
        request.app.state.assembly.chat_dispatch_queue,
    ).ensure_work_card(aggregate.work.id)
    # Starting the persisted current graph is idempotent.  A repeated command is
    # also the public, explicit retry signal for a retryable blocked attempt.
    request.app.state.assembly.orchestration_engine.start(aggregate.graph.id)
    aggregate = service.get(aggregate.work.id)
    return WorkProjection.from_aggregate(aggregate)


def _create_legacy_direct(
    workspace_id: str, body: DirectWorkCreate, service: WorkService
) -> WorkProjection:
    try:
        aggregate = service.create_direct(
            CreateDirectWork(
                workspace_id=WorkspaceId(workspace_id),
                employee_id=EmployeeId(body.employee_id),
                objective=body.objective,
                acceptance_criteria=tuple(body.acceptance_criteria),
                command_id=body.command_id,
            )
        )
    except LookupError as error:
        raise ResourceNotFoundError("employee") from error
    return WorkProjection.from_aggregate(aggregate)


def _create_strategy_work(
    request: Request, workspace_id: WorkspaceId, body: StrategyWorkCreate
) -> tuple[WorkAggregate, bool]:
    uow_factory = request.app.state.assembly.uow_factory
    normalized_command_id = body.command_id.strip()
    action_catalog = BusinessPluginRegistry(uow_factory).action_catalog()
    if isinstance(body, GraphStrategyInput):
        unknown_action = next(
            (
                action
                for node in body.nodes
                for action in node.required_actions
                if action not in action_catalog.actions
            ),
            None,
        )
        if unknown_action is not None:
            raise UnprocessableEntityError(
                "invalid_work_strategy", f"unknown required action: {unknown_action}"
            )
    policy_engine = PolicyEngine(action_catalog)
    try:
        with uow_factory() as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise ResourceNotFoundError("workspace")
            existing = uow.works.get_by_command(workspace_id, normalized_command_id)
            if existing is not None:
                return existing, False
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
            work = Work(
                id=WorkId(new_id("work")),
                workspace_id=workspace_id,
                command_id=normalized_command_id,
                objective=body.objective.strip(),
                status=WorkStatus.QUEUED,
                current_graph_revision_id=WorkGraphRevisionId(new_id("work-graph")),
                created_at=datetime.now(UTC),
            )
            aggregate = _build_strategy(
                work,
                body,
                candidates,
                policy_engine,
                GraphValidator(action_catalog),
            )
            uow.works.add(aggregate)
            if isinstance(body, GraphStrategyInput):
                for node, node_input in zip(aggregate.nodes, body.nodes, strict=True):
                    candidate = _candidate(candidates, node_input.employee_id)
                    uow.node_grants.replace(
                        node.id,
                        _requested_node_grants(work, candidate, node_input),
                    )
            uow.commit()
    except DuplicateCommand:
        with uow_factory() as uow:
            winner = uow.works.get_by_command(workspace_id, normalized_command_id)
        if winner is None:
            raise
        return winner, False
    except InvalidGraph as error:
        raise UnprocessableEntityError("invalid_work_graph", str(error)) from error
    except ValueError as error:
        code = (
            "invalid_work_graph"
            if isinstance(body, GraphStrategyInput)
            else "invalid_work_strategy"
        )
        raise UnprocessableEntityError(code, str(error)) from error
    return aggregate, True


def _build_strategy(
    work: Work,
    body: StrategyWorkCreate,
    candidates: tuple[EmployeeCandidate, ...],
    policy_engine: PolicyEngine,
    graph_validator: GraphValidator,
) -> WorkAggregate:
    factory = StrategyFactory(graph_validator)
    criteria = tuple(body.acceptance_criteria)
    if isinstance(body, DirectStrategyInput):
        return factory.direct(
            work=work,
            participant=_select_one(work, candidates, body.employee_id, policy_engine),
            objective=body.objective,
            criteria=criteria,
        )
    if isinstance(body, BattleStrategyInput):
        return factory.battle(
            work=work,
            participants=tuple(
                _select_one(work, candidates, employee_id, policy_engine)
                for employee_id in body.participant_employee_ids
            ),
            summarizer=_select_one(work, candidates, body.summarizer_employee_id, policy_engine),
            objective=body.objective,
            criteria=criteria,
        )
    if isinstance(body, StarStrategyInput):
        return factory.star(
            work=work,
            coordinator=_select_one(work, candidates, body.coordinator_employee_id, policy_engine),
            children=tuple(
                StarChild(
                    participant=_select_one(work, candidates, child.employee_id, policy_engine),
                    objective=child.objective,
                    criteria=tuple(child.acceptance_criteria),
                )
                for child in body.children
            ),
            objective=body.objective,
            criteria=criteria,
        )
    graph_body = cast(GraphStrategyInput, body)
    return factory.graph(
        work=work,
        nodes=tuple(
            ExplicitNode(
                key=node.key,
                participant=_select_graph_employee(work, candidates, node, policy_engine),
                objective=node.objective,
                criteria=tuple(node.acceptance_criteria),
                max_attempts=node.max_attempts,
            )
            for node in graph_body.nodes
        ),
        edges=tuple(
            ExplicitEdge(edge.from_key, edge.to_key, edge.kind) for edge in graph_body.edges
        ),
    )


def _select_one(
    work: Work,
    candidates: tuple[EmployeeCandidate, ...],
    employee_id: str,
    policy_engine: PolicyEngine,
) -> EligibleEmployee:
    return _select(work, candidates, employee_id, (), (), (), policy_engine)


def _select_graph_employee(
    work: Work,
    candidates: tuple[EmployeeCandidate, ...],
    node: GraphNodeInput,
    policy_engine: PolicyEngine,
) -> EligibleEmployee:
    scoped_candidates = tuple(
        EmployeeCandidate(
            employee=candidate.employee,
            revision=candidate.revision,
            binding=candidate.binding,
            employee_grants=candidate.employee_grants,
            workspace_grants=candidate.workspace_grants,
            node_grants=_requested_node_grants(work, candidate, node),
        )
        for candidate in candidates
    )
    return _select(
        work,
        scoped_candidates,
        node.employee_id,
        tuple(node.required_actions),
        tuple(node.resource_values),
        tuple(node.resource_kinds),
        policy_engine,
    )


def _select(
    work: Work,
    candidates: tuple[EmployeeCandidate, ...],
    employee_id: str,
    required_actions: tuple[str, ...],
    resources: tuple[str, ...],
    resource_kinds: tuple[str, ...],
    policy_engine: PolicyEngine,
) -> EligibleEmployee:
    selected_id = EmployeeId(employee_id)
    eligible = Selector(policy_engine).eligible(
        employees=candidates,
        workspace_id=work.workspace_id,
        required_actions=required_actions,
        resources=resources,
        resource_kinds=resource_kinds,
        delegation_allowlist=frozenset({selected_id}),
        user_order=(selected_id,),
        allow_approval_required=True,
    )
    if not eligible:
        raise ConflictError(
            "employee_ineligible", "selected employee is not eligible for this work node"
        )
    return eligible[0]


def _candidate(candidates: tuple[EmployeeCandidate, ...], employee_id: str) -> EmployeeCandidate:
    selected_id = EmployeeId(employee_id)
    candidate = next((item for item in candidates if item.employee.id == selected_id), None)
    if candidate is None:
        raise ConflictError(
            "employee_ineligible", "selected employee is not eligible for this work node"
        )
    return candidate


def _requested_node_grants(
    work: Work, candidate: EmployeeCandidate, node: GraphNodeInput
) -> tuple[CapabilityGrant, ...]:
    grants: list[CapabilityGrant] = []
    for action, resource_kind in zip(node.required_actions, node.resource_kinds, strict=True):
        employee_grant = next(
            (grant for grant in candidate.employee_grants if grant.action == action),
            None,
        )
        if employee_grant is None:
            continue
        resources = tuple(node.resource_values) or employee_grant.resource_values
        grants.append(
            CapabilityGrant(
                id=CapabilityGrantId(f"node-grant:{work.id}:{node.key}:{action}"),
                employee_revision_id=None,
                action=action,
                level=employee_grant.level,
                resource_kind=resource_kind,
                resource_values=resources,
                requires_approval=employee_grant.requires_approval,
            )
        )
    return tuple(grants)


@router.get(
    "/workspaces/{workspace_id}/works",
    response_model=list[WorkProjection],
    responses=not_found_response,
)
def list_workspace_works(
    workspace_id: str,
    service: WorkServiceDependency,
) -> list[WorkProjection]:
    try:
        aggregates = service.list_for_workspace(WorkspaceId(workspace_id))
    except LookupError as error:
        raise ResourceNotFoundError("workspace") from error
    return [WorkProjection.from_aggregate(aggregate) for aggregate in aggregates]


@router.get(
    "/works/{work_id}",
    response_model=WorkProjection,
    responses=not_found_response,
)
def get_work(work_id: str, service: WorkServiceDependency) -> WorkProjection:
    try:
        return WorkProjection.from_aggregate(service.get(WorkId(work_id)))
    except LookupError as error:
        raise ResourceNotFoundError("work") from error


@router.get(
    "/works/{work_id}/events",
    response_model=list[CompanyEvent],
    responses=not_found_response,
)
def list_work_events(work_id: str, service: WorkServiceDependency) -> list[CompanyEvent]:
    try:
        events = service.list_events(WorkId(work_id))
    except LookupError as error:
        raise ResourceNotFoundError("work") from error
    return [CompanyEvent.from_domain(event) for event in events]


@router.post(
    "/works/{work_id}/cancel",
    response_model=WorkProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**not_found_response, **{409: {"model": ErrorEnvelope}}},
)
def cancel_work(
    request: Request,
    work_id: str,
    service: WorkServiceDependency,
) -> WorkProjection:
    try:
        aggregate = service.request_cancel(
            WorkId(work_id), request.app.state.assembly.work_coordinator
        )
    except LookupError as error:
        raise ResourceNotFoundError("work") from error
    except WorkCancellationNotSupported as error:
        raise ConflictError("work_cancel_not_supported", str(error)) from error
    return WorkProjection.from_aggregate(aggregate)
