from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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


def install_error_handlers(app: FastAPI) -> None:
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
