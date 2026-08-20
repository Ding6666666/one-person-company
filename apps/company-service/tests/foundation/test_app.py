from pathlib import Path
from typing import Never
from unittest.mock import MagicMock

import pytest
from dsh_company.foundation import assembly as assembly_module
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.foundation.config import Settings
from fastapi.testclient import TestClient


def test_health_endpoint() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "dsh-company"}


def test_openapi_describes_service_and_health_endpoint() -> None:
    schema = create_app().openapi()

    assert schema["info"]["title"] == "DSH Company Service"
    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]


def test_openapi_requires_health_response_fields() -> None:
    schema = create_app().openapi()

    assert schema["components"]["schemas"]["HealthResponse"]["required"] == [
        "status",
        "service",
    ]


def test_unstarted_default_app_does_not_create_company_database(tmp_path: Path) -> None:
    app = create_app(Settings(data_root=tmp_path))

    app.openapi()

    assert not (tmp_path / "company.db").exists()


def test_default_assembly_disposes_engine_when_table_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = MagicMock()
    monkeypatch.setattr(
        assembly_module, "create_sqlite_engine", lambda _database_path: engine
    )

    def fail_table_creation(_engine: object) -> None:
        raise RuntimeError("table creation failed")

    monkeypatch.setattr(assembly_module, "create_tables", fail_table_creation)

    with pytest.raises(RuntimeError, match="table creation failed"):
        with TestClient(create_app(Settings(data_root=tmp_path))):
            pass

    engine.dispose.assert_called_once_with()


def test_injected_assembly_disposes_after_request_failure() -> None:
    dispose = MagicMock()

    def fail_uow() -> Never:
        raise RuntimeError("request failed")

    assembly = ComponentAssembly(uow_factory=fail_uow, dispose=dispose)

    with pytest.raises(RuntimeError, match="request failed"):
        with TestClient(create_app(assembly=assembly)) as client:
            client.get("/workspaces")

    dispose.assert_called_once_with()
