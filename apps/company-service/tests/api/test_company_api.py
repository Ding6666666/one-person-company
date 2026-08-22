from collections.abc import Iterator
from pathlib import Path

import pytest
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_sqlite_engine(tmp_path / "company-api.db")
    create_tables(engine)
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as test_client:
        yield test_client
    engine.dispose()


def _employee_payload() -> dict[str, object]:
    return {
        "display_name": "编辑",
        "role_template_key": "product-manager",
        "work_type": "产品管理",
        "avatar_key": "product-manager",
        "responsibility": "撰写内容",
        "system_prompt": "# 角色定位\n你是一名专业编辑。",
        "runtime_profile": "workspace_read",
        "model": "deepseek-v4-flash",
        "skill_refs": [],
        "tool_refs": [],
        "grants": [],
    }


def test_create_workspace_and_employee_without_provider_credentials(
    client: TestClient,
) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"})
    employee = client.post(
        f"/workspaces/{workspace.json()['id']}/employees",
        json=_employee_payload(),
    )

    assert workspace.status_code == 201
    assert employee.status_code == 201
    assert employee.json()["binding"]["dsh_session_id"].startswith("employee-")
    assert (
        employee.json()["revision"]
        | {
            "role_template_key": "product-manager",
            "work_type": "产品管理",
            "avatar_key": "product-manager",
            "system_prompt": "# 角色定位\n你是一名专业编辑。",
            "skill_refs": [],
            "tool_refs": [],
        }
        == employee.json()["revision"]
    )


def test_non_work_request_validation_uses_fastapi_default_contract(
    client: TestClient,
) -> None:
    response = client.post("/workspaces", json={"name": "x" * 121})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert "error" not in response.json()
    openapi = client.get("/openapi.json").json()
    assert (
        openapi["paths"]["/workspaces"]["post"]["responses"]["422"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/HTTPValidationError"
    )


def test_list_get_and_revise_workspace_employee(client: TestClient) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=_employee_payload(),
    ).json()

    workspaces = client.get("/workspaces")
    fetched_workspace = client.get(f"/workspaces/{workspace['id']}")
    employees = client.get(f"/workspaces/{workspace['id']}/employees")
    fetched_employee = client.get(f"/employees/{employee['id']}")
    revised = client.post(
        f"/employees/{employee['id']}/revisions",
        json={
            "responsibility": "撰写和事实核查",
            "system_prompt": "# 角色定位\n你是一名资深事实核查编辑。",
            "runtime_profile": "workspace_write",
            "model": "deepseek-v4-flash",
            "grants": [],
        },
    )

    assert workspaces.status_code == 200
    assert workspaces.json() == [workspace]
    assert fetched_workspace.json() == workspace
    assert employees.status_code == 200
    assert [item["id"] for item in employees.json()] == [employee["id"]]
    assert fetched_employee.json() == employee
    assert revised.status_code == 200
    assert revised.json()["revision"]["revision_number"] == 2
    assert revised.json()["revision"]["system_prompt"] == "# 角色定位\n你是一名资深事实核查编辑。"
    assert revised.json()["binding"] == employee["binding"]


def test_unknown_workspace_uses_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/workspaces/missing/employees")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"
    assert response.json()["error"]["correlation_id"]


def test_unknown_employee_uses_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/employees/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "employee_not_found"
    assert response.json()["error"]["correlation_id"]


def test_blank_workspace_name_is_rejected_without_creating_workspace(
    client: TestClient,
) -> None:
    response = client.post("/workspaces", json={"name": "   "})

    assert response.status_code == 422
    assert client.get("/workspaces").json() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", "   "),
        ("responsibility", "   "),
        ("model", "   "),
    ],
)
def test_blank_employee_core_field_is_rejected_without_creating_employee(
    client: TestClient,
    field: str,
    value: str,
) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"}).json()
    payload = _employee_payload()
    payload[field] = value

    response = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=payload,
    )

    assert response.status_code == 422
    assert client.get(f"/workspaces/{workspace['id']}/employees").json() == []


@pytest.mark.parametrize("grant_field", ["action", "resource_kind"])
def test_blank_explicit_grant_field_is_rejected_without_creating_employee(
    client: TestClient,
    grant_field: str,
) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"}).json()
    payload = _employee_payload()
    grant = {
        "action": "workspace.write",
        "level": 2,
        "resource_kind": "workspace",
        "resource_values": [workspace["id"]],
        "requires_approval": False,
    }
    grant[grant_field] = "   "
    payload["grants"] = [grant]

    response = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=payload,
    )

    assert response.status_code == 422
    assert client.get(f"/workspaces/{workspace['id']}/employees").json() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("responsibility", "   "),
        ("model", "   "),
    ],
)
def test_blank_employee_revision_field_is_rejected_without_modifying_employee(
    client: TestClient,
    field: str,
    value: str,
) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=_employee_payload(),
    ).json()
    payload: dict[str, object] = {
        "responsibility": "撰写和事实核查",
        "runtime_profile": "workspace_write",
        "model": "deepseek-v4-flash",
        "grants": [],
    }
    payload[field] = value

    response = client.post(
        f"/employees/{employee['id']}/revisions",
        json=payload,
    )

    assert response.status_code == 422
    assert client.get(f"/employees/{employee['id']}").json() == employee


@pytest.mark.parametrize("grant_field", ["action", "resource_kind"])
def test_blank_revision_grant_field_is_rejected_without_modifying_employee(
    client: TestClient,
    grant_field: str,
) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=_employee_payload(),
    ).json()
    grant = {
        "action": "workspace.write",
        "level": 2,
        "resource_kind": "workspace",
        "resource_values": [workspace["id"]],
        "requires_approval": False,
    }
    grant[grant_field] = "   "

    response = client.post(
        f"/employees/{employee['id']}/revisions",
        json={
            "responsibility": "撰写和事实核查",
            "runtime_profile": "workspace_write",
            "model": "deepseek-v4-flash",
            "grants": [grant],
        },
    )

    assert response.status_code == 422
    assert client.get(f"/employees/{employee['id']}").json() == employee


def test_transport_trims_valid_core_and_grant_fields(client: TestClient) -> None:
    workspace = client.post("/workspaces", json={"name": "  内容公司  "}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json={
            "display_name": "  编辑  ",
            "responsibility": "  撰写内容  ",
            "runtime_profile": "workspace_read",
            "model": "  deepseek-v4-flash  ",
            "grants": [
                {
                    "action": "  workspace.write  ",
                    "level": 2,
                    "resource_kind": "  workspace  ",
                    "resource_values": [workspace["id"]],
                    "requires_approval": False,
                }
            ],
        },
    ).json()

    assert workspace["name"] == "内容公司"
    assert employee["display_name"] == "编辑"
    assert employee["revision"]["responsibility"] == "撰写内容"
    assert employee["revision"]["model"] == "deepseek-v4-flash"
    explicit = next(grant for grant in employee["grants"] if grant["action"] == "workspace.write")
    assert explicit["resource_kind"] == "workspace"


@pytest.mark.parametrize(
    "grants",
    [
        [
            {
                "action": "unknown.action",
                "level": 1,
                "resource_kind": "workspace",
                "resource_values": ["*"],
                "requires_approval": False,
            }
        ],
        [
            {
                "action": "workspace.read",
                "level": 3,
                "resource_kind": "workspace",
                "resource_values": ["*"],
                "requires_approval": False,
            }
        ],
        [
            {
                "action": "workspace.read",
                "level": 1,
                "resource_kind": "workspace",
                "resource_values": ["*"],
                "requires_approval": False,
            },
            {
                "action": "workspace.read",
                "level": 1,
                "resource_kind": "workspace",
                "resource_values": ["*"],
                "requires_approval": False,
            },
        ],
    ],
)
def test_invalid_employee_grant_catalog_facts_are_rejected(
    client: TestClient, grants: list[dict[str, object]]
) -> None:
    workspace = client.post("/workspaces", json={"name": "Catalog"}).json()
    payload = _employee_payload()
    payload["grants"] = grants

    response = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=payload,
    )

    assert response.status_code == 422
    assert client.get(f"/workspaces/{workspace['id']}/employees").json() == []


def test_invalid_revised_employee_grant_does_not_create_a_revision(
    client: TestClient,
) -> None:
    workspace = client.post("/workspaces", json={"name": "Catalog"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=_employee_payload(),
    ).json()

    response = client.post(
        f"/employees/{employee['id']}/revisions",
        json={
            "responsibility": "invalid catalog revision",
            "runtime_profile": "workspace_read",
            "model": "deepseek-v4-flash",
            "grants": [
                {
                    "action": "unknown.action",
                    "level": 1,
                    "resource_kind": "workspace",
                    "resource_values": [workspace["id"]],
                    "requires_approval": False,
                }
            ],
        },
    )

    assert response.status_code == 422
    current = client.get(f"/employees/{employee['id']}").json()
    assert current["revision"]["revision_number"] == 1


def test_registered_plugin_action_is_valid_for_employee_grants(client: TestClient) -> None:
    registered = client.post(
        "/business-plugins/register",
        json={
            "plugin_id": "content-studio",
            "version": "1.0.0",
            "display_name": "Content Studio",
            "capability_actions": [
                {
                    "action": "content-studio.publish",
                    "level": 3,
                    "runtime_profiles": ["workspace_write"],
                }
            ],
            "templates": [],
        },
    )
    assert registered.status_code == 201
    workspace = client.post("/workspaces", json={"name": "Catalog"}).json()
    payload = _employee_payload()
    payload["runtime_profile"] = "workspace_write"
    payload["grants"] = [
        {
            "action": "content-studio.publish",
            "level": 3,
            "resource_kind": "workspace",
            "resource_values": [workspace["id"]],
            "requires_approval": True,
        }
    ]

    response = client.post(
        f"/workspaces/{workspace['id']}/employees",
        json=payload,
    )

    assert response.status_code == 201
    assert any(grant["action"] == "content-studio.publish" for grant in response.json()["grants"])
