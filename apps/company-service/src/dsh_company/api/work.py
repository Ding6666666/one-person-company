from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from dsh_company.application.work_commands import CreateDirectWork
from dsh_company.application.work_service import WorkService
from dsh_company.domain.ids import EmployeeId, WorkId, WorkspaceId

from .errors import ErrorEnvelope, ResourceNotFoundError
from .schemas import CompanyEvent, DirectWorkCreate, WorkProjection

router = APIRouter()
not_found_response: dict[int | str, dict[str, Any]] = {404: {"model": ErrorEnvelope}}


def _work_service(request: Request) -> WorkService:
    assembly = request.app.state.assembly
    return WorkService(assembly.uow_factory(), assembly.work_coordinator)


WorkServiceDependency = Annotated[WorkService, Depends(_work_service)]


@router.post(
    "/workspaces/{workspace_id}/works",
    response_model=WorkProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses=not_found_response,
)
def create_direct_work(
    workspace_id: str,
    body: DirectWorkCreate,
    service: WorkServiceDependency,
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
def list_work_events(
    work_id: str, service: WorkServiceDependency
) -> list[CompanyEvent]:
    try:
        events = service.list_events(WorkId(work_id))
    except LookupError as error:
        raise ResourceNotFoundError("work") from error
    return [CompanyEvent.from_domain(event) for event in events]


@router.post(
    "/works/{work_id}/cancel",
    response_model=WorkProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses=not_found_response,
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
    return WorkProjection.from_aggregate(aggregate)
