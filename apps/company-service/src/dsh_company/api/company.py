from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from dsh_company.application.commands import (
    CreateEmployee,
    CreateWorkspace,
    GrantInput,
    ReviseEmployee,
)
from dsh_company.application.company_service import CompanyService
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.capabilities import CapabilityLevel
from dsh_company.domain.ids import EmployeeId, WorkspaceId

from .errors import ErrorEnvelope, ResourceNotFoundError, UnprocessableEntityError
from .schemas import (
    Employee,
    EmployeeCreate,
    EmployeeRevise,
    GrantCreate,
    Workspace,
    WorkspaceCreate,
)

router = APIRouter()
not_found_response: dict[int | str, dict[str, Any]] = {404: {"model": ErrorEnvelope}}
grant_error_responses: dict[int | str, dict[str, Any]] = {422: {"model": ErrorEnvelope}}


def _company_service(request: Request) -> CompanyService:
    return CompanyService(request.app.state.assembly.uow_factory())


CompanyServiceDependency = Annotated[CompanyService, Depends(_company_service)]


def _grants(items: list[GrantCreate]) -> tuple[GrantInput, ...]:
    return tuple(
        GrantInput(
            action=item.action,
            level=CapabilityLevel(item.level),
            resource_kind=item.resource_kind,
            resource_values=tuple(item.resource_values),
            requires_approval=item.requires_approval,
        )
        for item in items
    )


def _validate_grants(request: Request, items: list[GrantCreate]) -> None:
    actions = [item.action for item in items]
    if len(items) > 8 or len(actions) != len(set(actions)):
        raise UnprocessableEntityError(
            "invalid_capability_grant",
            "employee capability grants must contain at most eight unique actions",
        )
    catalog = BusinessPluginRegistry(request.app.state.assembly.uow_factory).action_catalog()
    if any(
        (required_level := catalog.level(item.action)) is None
        or int(required_level) != item.level
        for item in items
    ):
        raise UnprocessableEntityError(
            "invalid_capability_grant",
            "capability action and level must match the registered catalog",
        )


@router.post(
    "/workspaces",
    response_model=Workspace,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    body: WorkspaceCreate,
    service: CompanyServiceDependency,
) -> Workspace:
    return Workspace.from_domain(service.create_workspace(CreateWorkspace(name=body.name)))


@router.get("/workspaces", response_model=list[Workspace])
def list_workspaces(
    service: CompanyServiceDependency,
) -> list[Workspace]:
    return [Workspace.from_domain(item) for item in service.list_workspaces()]


@router.get(
    "/workspaces/{workspace_id}",
    response_model=Workspace,
    responses=not_found_response,
)
def get_workspace(
    workspace_id: str,
    service: CompanyServiceDependency,
) -> Workspace:
    try:
        return Workspace.from_domain(service.get_workspace(WorkspaceId(workspace_id)))
    except LookupError as error:
        raise ResourceNotFoundError("workspace") from error


@router.post(
    "/workspaces/{workspace_id}/employees",
    response_model=Employee,
    status_code=status.HTTP_201_CREATED,
    responses={**not_found_response, **grant_error_responses},
)
def create_employee(
    request: Request,
    workspace_id: str,
    body: EmployeeCreate,
    service: CompanyServiceDependency,
) -> Employee:
    _validate_grants(request, body.grants)
    try:
        record = service.create_employee(
            CreateEmployee(
                workspace_id=WorkspaceId(workspace_id),
                display_name=body.display_name,
                responsibility=body.responsibility,
                runtime_profile=body.runtime_profile,
                model=body.model,
                grants=_grants(body.grants),
            )
        )
    except LookupError as error:
        raise ResourceNotFoundError("workspace") from error
    return Employee.from_record(record)


@router.get(
    "/workspaces/{workspace_id}/employees",
    response_model=list[Employee],
    responses=not_found_response,
)
def list_employees(
    workspace_id: str,
    service: CompanyServiceDependency,
) -> list[Employee]:
    try:
        records = service.list_employees(WorkspaceId(workspace_id))
    except LookupError as error:
        raise ResourceNotFoundError("workspace") from error
    return [Employee.from_record(record) for record in records]


@router.get(
    "/employees/{employee_id}",
    response_model=Employee,
    responses=not_found_response,
)
def get_employee(
    employee_id: str,
    service: CompanyServiceDependency,
) -> Employee:
    try:
        return Employee.from_record(service.get_employee(EmployeeId(employee_id)))
    except LookupError as error:
        raise ResourceNotFoundError("employee") from error


@router.post(
    "/employees/{employee_id}/revisions",
    response_model=Employee,
    responses={**not_found_response, **grant_error_responses},
)
def revise_employee(
    request: Request,
    employee_id: str,
    body: EmployeeRevise,
    service: CompanyServiceDependency,
) -> Employee:
    _validate_grants(request, body.grants)
    try:
        record = service.revise_employee(
            ReviseEmployee(
                employee_id=EmployeeId(employee_id),
                responsibility=body.responsibility,
                runtime_profile=body.runtime_profile,
                model=body.model,
                grants=_grants(body.grants),
            )
        )
    except LookupError as error:
        raise ResourceNotFoundError("employee") from error
    return Employee.from_record(record)
