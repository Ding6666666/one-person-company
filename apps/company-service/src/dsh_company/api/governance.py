from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request

from dsh_company.application.delegation_service import (
    DelegationCommand,
    DelegationDenied,
    DelegationService,
)
from dsh_company.application.governance_service import GovernanceService
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.approval import Approval
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.delegation import Delegation, DelegationProposal
from dsh_company.domain.employee import EmployeeStatus
from dsh_company.domain.ids import (
    ApprovalId,
    CapabilityGrantId,
    EmployeeId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.persistence.governance_repositories import ConcurrentApprovalDecision

from .errors import (
    ConflictError,
    ErrorEnvelope,
    ResourceNotFoundError,
    UnprocessableEntityError,
)
from .schemas import (
    ApprovalDecision,
    ApprovalDecisionProjection,
    ApprovalProjection,
    DelegationCollection,
    DelegationCreate,
    DelegationProjection,
    DelegationResultProjection,
    EmployeeSummary,
    WorkProjection,
    WorkspaceCapabilities,
    WorkspaceCapabilitiesUpdate,
    WorkspaceGrant,
)

router = APIRouter()
not_found_response: dict[int | str, dict[str, Any]] = {404: {"model": ErrorEnvelope}}
conflict_response: dict[int | str, dict[str, Any]] = {409: {"model": ErrorEnvelope}}


def _governance_service(request: Request) -> GovernanceService:
    return cast(GovernanceService, request.app.state.assembly.governance_service_factory())


def _delegation_service(request: Request) -> DelegationService:
    return cast(DelegationService, request.app.state.assembly.delegation_service_factory())


GovernanceDependency = Annotated[GovernanceService, Depends(_governance_service)]
DelegationDependency = Annotated[DelegationService, Depends(_delegation_service)]


def _workspace_grant(grant: CapabilityGrant) -> WorkspaceGrant:
    return WorkspaceGrant(
        action=grant.action,
        level=cast(Any, int(grant.level)),
        resource_kind=grant.resource_kind,
        resource_values=list(grant.resource_values),
        requires_approval=grant.requires_approval,
    )


def _delegation(value: Delegation) -> DelegationProjection:
    return DelegationProjection(
        id=value.id,
        workspace_id=value.workspace_id,
        work_id=value.work_id,
        source_node_id=value.source_node_id,
        target_node_id=value.target_node_id,
        proposer_employee_id=value.proposer_employee_id,
        target_employee_id=value.target_employee_id,
        graph_revision_id=value.graph_revision_id,
        status=value.status,
        created_at=value.created_at,
    )


def _approval_projection(uow: Any, approval: Approval) -> ApprovalProjection:
    aggregate = uow.works.get(approval.work_id)
    if aggregate is None:
        raise ResourceNotFoundError("work")
    node = next((item for item in aggregate.nodes if item.id == approval.node_id), None)
    if node is None:
        raise ResourceNotFoundError("work")
    record = uow.employees.get(EmployeeId(node.assigned_employee_id))
    if record is None:
        raise ResourceNotFoundError("employee")
    return ApprovalProjection(
        id=approval.id,
        workspace_id=approval.workspace_id,
        work_id=approval.work_id,
        node_id=approval.node_id,
        action=approval.action,
        resources=list(approval.resources),
        reason=approval.reason,
        status=approval.status.value,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
        decided_by=approval.decided_by,
        requesting_employee=EmployeeSummary(
            id=record.employee.id,
            display_name=record.employee.display_name,
        ),
    )


@router.put(
    "/workspaces/{workspace_id}/capabilities",
    response_model=WorkspaceCapabilities,
    responses={**not_found_response, **{422: {"model": ErrorEnvelope}}},
)
def replace_workspace_capabilities(
    request: Request,
    workspace_id: str,
    body: WorkspaceCapabilitiesUpdate,
) -> WorkspaceCapabilities:
    value = WorkspaceId(workspace_id)
    catalog = BusinessPluginRegistry(request.app.state.assembly.uow_factory).action_catalog()
    actions = [grant.action for grant in body.grants]
    if len(actions) != len(set(actions)):
        raise UnprocessableEntityError(
            "invalid_capability_grant", "capability actions must be unique"
        )
    for grant in body.grants:
        required_level = catalog.level(grant.action)
        if required_level is None or grant.level != int(required_level):
            raise UnprocessableEntityError(
                "invalid_capability_grant",
                "capability action and level must match the registered catalog",
            )
    with request.app.state.assembly.uow_factory() as uow:
        if uow.workspaces.get(value) is None:
            raise ResourceNotFoundError("workspace")
        grants = tuple(
            CapabilityGrant(
                id=CapabilityGrantId(f"workspace:{workspace_id}:{item.action}"),
                employee_revision_id=None,
                action=item.action,
                level=CapabilityLevel(item.level),
                resource_kind=item.resource_kind,
                resource_values=tuple(item.resource_values),
                requires_approval=item.requires_approval,
            )
            for item in body.grants
        )
        uow.workspace_grants.replace(value, grants)
        uow.commit()
    return WorkspaceCapabilities(
        workspace_id=workspace_id,
        grants=[_workspace_grant(item) for item in grants],
    )


@router.get(
    "/workspaces/{workspace_id}/capabilities",
    response_model=WorkspaceCapabilities,
    responses=not_found_response,
)
def get_workspace_capabilities(
    request: Request,
    workspace_id: str,
) -> WorkspaceCapabilities:
    value = WorkspaceId(workspace_id)
    with request.app.state.assembly.uow_factory() as uow:
        if uow.workspaces.get(value) is None:
            raise ResourceNotFoundError("workspace")
        grants = uow.workspace_grants.list_for_workspace(value)
    return WorkspaceCapabilities(
        workspace_id=workspace_id,
        grants=[_workspace_grant(item) for item in grants],
    )


@router.get(
    "/workspaces/{workspace_id}/approvals",
    response_model=list[ApprovalProjection],
    responses=not_found_response,
)
def list_workspace_approvals(request: Request, workspace_id: str) -> list[ApprovalProjection]:
    value = WorkspaceId(workspace_id)
    with request.app.state.assembly.uow_factory() as uow:
        if uow.workspaces.get(value) is None:
            raise ResourceNotFoundError("workspace")
        return [_approval_projection(uow, item) for item in uow.approvals.list_for_workspace(value)]


def _decide(
    request: Request,
    approval_id: str,
    body: ApprovalDecision,
    service: GovernanceService,
    *,
    approve: bool,
) -> ApprovalDecisionProjection:
    try:
        approval = (
            service.approve(ApprovalId(approval_id), decided_by=body.decided_by)
            if approve
            else service.reject(ApprovalId(approval_id), decided_by=body.decided_by)
        )
        if approve:
            service.resume_approved(approval.id)
    except LookupError as error:
        raise ResourceNotFoundError("approval") from error
    except (ValueError, ConcurrentApprovalDecision) as error:
        if "already decided" in str(error) or isinstance(error, ConcurrentApprovalDecision):
            raise ConflictError(
                "approval_already_decided", "approval is already decided"
            ) from error
        raise
    with request.app.state.assembly.uow_factory() as uow:
        current = uow.approvals.get(approval.id)
        aggregate = uow.works.get(approval.work_id)
        if current is None or aggregate is None:
            raise ResourceNotFoundError("approval")
        return ApprovalDecisionProjection(
            approval=_approval_projection(uow, current),
            work=WorkProjection.from_aggregate(aggregate),
        )


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalDecisionProjection,
    responses={**not_found_response, **conflict_response},
)
def approve(
    approval_id: str, body: ApprovalDecision, request: Request, service: GovernanceDependency
) -> ApprovalDecisionProjection:
    return _decide(request, approval_id, body, service, approve=True)


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=ApprovalDecisionProjection,
    responses={**not_found_response, **conflict_response},
)
def reject(
    approval_id: str, body: ApprovalDecision, request: Request, service: GovernanceDependency
) -> ApprovalDecisionProjection:
    return _decide(request, approval_id, body, service, approve=False)


@router.get(
    "/works/{work_id}/delegations",
    response_model=DelegationCollection,
    responses=not_found_response,
)
def list_work_delegations(request: Request, work_id: str) -> DelegationCollection:
    value = WorkId(work_id)
    with request.app.state.assembly.uow_factory() as uow:
        aggregate = uow.works.get(value)
        if aggregate is None:
            raise ResourceNotFoundError("work")
        employees = uow.employees.list_for_workspace(aggregate.work.workspace_id)
        return DelegationCollection(
            delegations=[_delegation(item) for item in uow.delegations.list_for_work(value)],
            eligible_employees=[
                EmployeeSummary(id=item.employee.id, display_name=item.employee.display_name)
                for item in employees
                if item.employee.status is EmployeeStatus.ACTIVE
            ],
        )


@router.post(
    "/works/{work_id}/delegations",
    response_model=DelegationResultProjection,
    responses={
        **not_found_response,
        **conflict_response,
        422: {"model": ErrorEnvelope},
    },
)
def create_delegation(
    request: Request,
    work_id: str,
    body: DelegationCreate,
    service: DelegationDependency,
) -> DelegationResultProjection:
    action_catalog = BusinessPluginRegistry(
        request.app.state.assembly.uow_factory
    ).action_catalog()
    unknown_action = next(
        (
            action
            for action in body.required_actions
            if action not in action_catalog.actions
        ),
        None,
    )
    if unknown_action is not None:
        raise UnprocessableEntityError(
            "invalid_delegation_action",
            f"unknown delegation action: {unknown_action}",
        )
    with request.app.state.assembly.uow_factory() as uow:
        aggregate = uow.works.get(WorkId(work_id))
        if aggregate is None:
            raise ResourceNotFoundError("work")
        if not any(node.id == WorkNodeId(body.source_node_id) for node in aggregate.nodes):
            raise ConflictError("delegation_denied", "delegation source does not belong to work")
    try:
        result = service.propose(
            DelegationCommand(
                source_node_id=WorkNodeId(body.source_node_id),
                proposal=DelegationProposal(
                    proposer_employee_id=EmployeeId(body.proposer_employee_id),
                    target_employee_id=EmployeeId(body.target_employee_id),
                    objective=body.objective,
                    acceptance_criteria=tuple(body.acceptance_criteria),
                    required_actions=tuple(body.required_actions),
                    resource_values=tuple(body.resource_values),
                ),
            )
        )
    except DelegationDenied as error:
        raise ConflictError("delegation_denied", str(error)) from error
    with request.app.state.assembly.uow_factory() as uow:
        aggregate = uow.works.get(WorkId(work_id))
        if aggregate is None:
            raise ResourceNotFoundError("work")
        return DelegationResultProjection(
            delegation=_delegation(result.delegation),
            work=WorkProjection.from_aggregate(aggregate),
        )
