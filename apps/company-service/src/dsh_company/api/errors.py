from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class ResourceNotFoundError(Exception):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(f"{resource} not found")


class ConflictError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class UnprocessableEntityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> Response:
        route = request.scope.get("route")
        is_strategy_request = (
            request.method == "POST"
            and getattr(route, "path", None) == "/workspaces/{workspace_id}/works"
        )
        if not is_strategy_request:
            return await request_validation_exception_handler(request, error)
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code="invalid_work_strategy",
                message="request body did not match the published contract",
                correlation_id=uuid4().hex,
            )
        )
        return JSONResponse(status_code=422, content=envelope.model_dump())

    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found(_request: Request, error: ResourceNotFoundError) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=f"{error.resource}_not_found",
                message=f"{error.resource} not found",
                correlation_id=uuid4().hex,
            )
        )
        return JSONResponse(status_code=404, content=envelope.model_dump())

    @app.exception_handler(ConflictError)
    async def conflict(_request: Request, error: ConflictError) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=error.code,
                message=error.message,
                correlation_id=uuid4().hex,
            )
        )
        return JSONResponse(status_code=409, content=envelope.model_dump())

    @app.exception_handler(UnprocessableEntityError)
    async def unprocessable(_request: Request, error: UnprocessableEntityError) -> JSONResponse:
        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=error.code,
                message=error.message,
                correlation_id=uuid4().hex,
            )
        )
        return JSONResponse(status_code=422, content=envelope.model_dump())
