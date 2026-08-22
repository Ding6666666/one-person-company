from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.foundation.config import Settings
from fastapi.testclient import TestClient


def test_default_capability_catalog_is_truthfully_empty() -> None:
    with TestClient(create_app(assembly=ComponentAssembly())) as client:
        assert client.get("/capability-sources/skill").json() == []
        assert client.get("/capability-entries/tool").json() == []


def test_unknown_capability_source_uses_stable_not_found_error() -> None:
    with TestClient(create_app(assembly=ComponentAssembly())) as client:
        response = client.post(
            "/capability-imports",
            json={"kind": "skill", "source_id": "missing", "external_id": "review"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "capability_source_not_found"


def test_runtime_options_expose_only_non_secret_model_facts() -> None:
    settings = Settings(dsh_provider="deepseek-official", dsh_model="deepseek-v4-flash")
    with TestClient(create_app(settings=settings, assembly=ComponentAssembly())) as client:
        response = client.get("/runtime-options")

    assert response.json() == {
        "provider": "deepseek-official",
        "default_model": "deepseek-v4-flash",
    }
