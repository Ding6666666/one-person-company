from pathlib import Path

import pytest
from dsh_company.foundation.app import create_app
from dsh_company.foundation.config import Settings
from fastapi.testclient import TestClient


def _employee_payload(display_name: str) -> dict[str, object]:
    return {
        "display_name": display_name,
        "responsibility": "编辑内容",
        "runtime_profile": "workspace_read",
        "model": "deepseek-v4-flash",
        "grants": [],
    }


def test_company_core_is_durable_and_isolated_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DSH_COMPANY_DATA_ROOT", str(tmp_path))
    settings = Settings()

    assert settings.data_root == tmp_path

    with TestClient(create_app(settings=settings)) as client:
        workspace_a_response = client.post("/workspaces", json={"name": "公司 A"})
        workspace_b_response = client.post("/workspaces", json={"name": "公司 B"})
        workspace_a_response.raise_for_status()
        workspace_b_response.raise_for_status()
        workspace_a = workspace_a_response.json()
        workspace_b = workspace_b_response.json()
        client.post(
            f"/workspaces/{workspace_a['id']}/employees",
            json=_employee_payload("编辑 A"),
        ).raise_for_status()
        client.post(
            f"/workspaces/{workspace_b['id']}/employees",
            json=_employee_payload("编辑 B"),
        ).raise_for_status()

    with TestClient(create_app(settings=settings)) as client:
        list_a = client.get(f"/workspaces/{workspace_a['id']}/employees")
        list_b = client.get(f"/workspaces/{workspace_b['id']}/employees")

    assert [item["display_name"] for item in list_a.json()] == ["编辑 A"]
    assert [item["display_name"] for item in list_b.json()] == ["编辑 B"]
    assert (
        list_a.json()[0]["binding"]["dsh_session_id"]
        != list_b.json()[0]["binding"]["dsh_session_id"]
    )

    database_path = tmp_path / "company.db"
    database_path.unlink()
    assert not database_path.exists()
