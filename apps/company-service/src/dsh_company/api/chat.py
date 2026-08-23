from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from dsh_company.application.chat_commands import SendChatMessage
from dsh_company.application.chat_service import ChatService
from dsh_company.domain.ids import ChatExecutionId, EmployeeId, WorkId, WorkspaceId

from .errors import ErrorEnvelope, ResourceNotFoundError, UnprocessableEntityError
from .schemas import (
    ChatExecutionProjection,
    ChatMessageCollection,
    ChatMessageCreate,
    ChatMessageProjection,
)

router = APIRouter()
not_found_response: dict[int | str, dict[str, Any]] = {404: {"model": ErrorEnvelope}}


def _chat_service(request: Request) -> ChatService:
    assembly = request.app.state.assembly
    return ChatService(assembly.uow_factory(), assembly.chat_dispatch_queue)


ChatServiceDependency = Annotated[ChatService, Depends(_chat_service)]


@router.get(
    "/workspaces/{workspace_id}/messages",
    response_model=ChatMessageCollection,
    responses=not_found_response,
)
def list_messages(
    workspace_id: str,
    service: ChatServiceDependency,
    work_id: str | None = None,
) -> ChatMessageCollection:
    try:
        records = service.list_messages(
            WorkspaceId(workspace_id),
            work_id=None if work_id is None else WorkId(work_id),
        )
    except LookupError as error:
        resource = "work" if str(error).startswith("work ") else "workspace"
        raise ResourceNotFoundError(resource) from error
    return ChatMessageCollection(
        messages=[ChatMessageProjection.from_record(record) for record in records]
    )


@router.post(
    "/workspaces/{workspace_id}/messages",
    response_model=ChatMessageProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses=not_found_response,
)
def send_message(
    workspace_id: str,
    body: ChatMessageCreate,
    service: ChatServiceDependency,
) -> ChatMessageProjection:
    try:
        record = service.send(
            SendChatMessage(
                workspace_id=WorkspaceId(workspace_id),
                body=body.body,
                mention_employee_ids=tuple(
                    EmployeeId(employee_id) for employee_id in body.mention_employee_ids
                ),
                work_id=None if body.work_id is None else WorkId(body.work_id),
            )
        )
    except LookupError as error:
        resource = "work" if str(error).startswith("work ") else "workspace"
        raise ResourceNotFoundError(resource) from error
    except ValueError as error:
        raise UnprocessableEntityError("invalid_chat_message", str(error)) from error
    return ChatMessageProjection.from_record(record)


@router.post(
    "/chat-executions/{execution_id}/retry",
    response_model=ChatExecutionProjection,
    status_code=status.HTTP_202_ACCEPTED,
    responses=not_found_response,
)
def retry_execution(
    execution_id: str,
    service: ChatServiceDependency,
) -> ChatExecutionProjection:
    try:
        execution = service.retry(ChatExecutionId(execution_id))
    except LookupError as error:
        raise ResourceNotFoundError("chat_execution") from error
    except ValueError as error:
        raise UnprocessableEntityError("chat_execution_not_retryable", str(error)) from error
    return ChatExecutionProjection.from_domain(execution)
