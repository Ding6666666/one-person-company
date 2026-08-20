from dsh_company.foundation.app import create_app
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
