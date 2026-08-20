from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from dsh_company.foundation.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["dsh-company"]


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="DSH Company Service", version="0.1.0")
    app.state.settings = settings or Settings()

    @app.get("/health", tags=["foundation"], response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="dsh-company")

    return app
