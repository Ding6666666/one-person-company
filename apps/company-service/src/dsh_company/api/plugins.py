from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from dsh_company.business_plugins.manifest import (
    BusinessPluginManifest,
    BusinessPluginRegistration,
    WorkTemplate,
)
from dsh_company.business_plugins.registry import (
    BusinessPluginRegistry,
    InvalidPluginManifest,
)
from dsh_company.business_plugins.templates import (
    InvalidTemplateAssignment,
    TemplateInstantiator,
)
from dsh_company.domain.ids import WorkspaceId

from .errors import (
    ConflictError,
    ErrorEnvelope,
    ResourceNotFoundError,
    UnprocessableEntityError,
)
from .schemas import WorkProjection

router = APIRouter()
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TemplateInstantiation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: NonBlank
    employee_assignments: dict[NonBlank, NonBlank] = Field(min_length=1, max_length=32)


def _registry(request: Request) -> BusinessPluginRegistry:
    return BusinessPluginRegistry(request.app.state.assembly.uow_factory)


RegistryDependency = Annotated[BusinessPluginRegistry, Depends(_registry)]


@router.post(
    "/business-plugins/register",
    response_model=BusinessPluginRegistration,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}},
)
def register_business_plugin(
    manifest: BusinessPluginManifest,
    registry: RegistryDependency,
) -> BusinessPluginRegistration:
    try:
        return registry.register(manifest)
    except InvalidPluginManifest as error:
        raise ConflictError("invalid_plugin_manifest", str(error)) from error


@router.get(
    "/business-plugins",
    response_model=list[BusinessPluginRegistration],
)
def list_business_plugins(
    registry: RegistryDependency,
) -> list[BusinessPluginRegistration]:
    return list(registry.list())


@router.get(
    "/business-plugins/{plugin_id}/templates",
    response_model=list[WorkTemplate],
    responses={404: {"model": ErrorEnvelope}},
)
def list_business_plugin_templates(
    plugin_id: str,
    registry: RegistryDependency,
) -> list[WorkTemplate]:
    try:
        return list(registry.templates(plugin_id))
    except LookupError as error:
        raise ResourceNotFoundError("business_plugin") from error


@router.post(
    "/workspaces/{workspace_id}/templates/{plugin_id}/{template_id}/instantiate",
    response_model=WorkProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
)
def instantiate_business_plugin_template(
    request: Request,
    workspace_id: str,
    plugin_id: str,
    template_id: str,
    body: TemplateInstantiation,
    registry: RegistryDependency,
) -> WorkProjection:
    instantiator = TemplateInstantiator(
        request.app.state.assembly.uow_factory,
        registry,
        request.app.state.assembly.orchestration_engine,
    )
    try:
        aggregate = instantiator.instantiate(
            workspace_id=WorkspaceId(workspace_id),
            plugin_id=plugin_id,
            template_id=template_id,
            command_id=body.command_id,
            employee_assignments=body.employee_assignments,
        )
    except InvalidTemplateAssignment as error:
        if str(error) == "employee_ineligible":
            raise ConflictError("employee_ineligible", str(error)) from error
        raise UnprocessableEntityError(
            "invalid_template_assignment", str(error)
        ) from error
    except LookupError as error:
        resource = "workspace" if str(error) == "workspace not found" else "template"
        raise ResourceNotFoundError(resource) from error
    return WorkProjection.from_aggregate(aggregate)
