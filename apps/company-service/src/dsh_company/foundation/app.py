from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from dsh_company.api.errors import install_error_handlers
from dsh_company.foundation.assembly import ComponentAssembly, create_production_assembly
from dsh_company.foundation.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["dsh-company"]


class RuntimeOptions(BaseModel):
    provider: str
    default_model: str


def create_app(
    settings: Settings | None = None,
    assembly: ComponentAssembly | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_assembly = assembly or create_production_assembly(resolved_settings)
        app.state.assembly = resolved_assembly
        try:
            resolved_assembly.startup()
            yield
        finally:
            resolved_assembly.dispose()

    app = FastAPI(
        title="DSH Company Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.assembly = assembly or ComponentAssembly()
    install_error_handlers(app)

    @app.get("/health", tags=["foundation"], response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="dsh-company")

    @app.get("/runtime-options", tags=["foundation"], response_model=RuntimeOptions)
    def runtime_options() -> RuntimeOptions:
        return RuntimeOptions(
            provider=resolved_settings.dsh_provider,
            default_model=resolved_settings.dsh_model,
        )

    app.include_router(app.state.assembly.router, tags=["company"])

    return app
