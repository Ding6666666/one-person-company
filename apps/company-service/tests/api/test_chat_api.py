from collections.abc import Iterator
from pathlib import Path

import pytest
from dsh_company.domain.ids import ChatExecutionId
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient


class RecordingChatDispatch:
    def __init__(self) -> None:
        self.execution_ids: list[ChatExecutionId] = []

    def enqueue_chat(self, execution_id: ChatExecutionId) -> None:
        self.execution_ids.append(execution_id)


@pytest.fixture
def client_and_dispatch(tmp_path: Path) -> Iterator[tuple[TestClient, RecordingChatDispatch]]:
    engine = create_sqlite_engine(tmp_path / "chat-api.db")
    create_tables(engine)
    dispatch = RecordingChatDispatch()
    assembly = ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        chat_dispatch_queue=dispatch,
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as client:
        yield client, dispatch
    engine.dispose()


def _employee_payload() -> dict[str, object]:
    return {
        "display_name": "产品经理",
        "responsibility": "梳理需求",
        "system_prompt": "保持专业",
        "runtime_profile": "workspace_read",
        "model": "deepseek-v4-flash",
        "grants": [],
    }


def _company(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    workspace = client.post("/workspaces", json={"name": "Chat company"}).json()
    employee = client.post(
        f"/workspaces/{workspace['id']}/employees", json=_employee_payload()
    ).json()
    return workspace, employee


def test_post_and_list_company_messages(
    client_and_dispatch: tuple[TestClient, RecordingChatDispatch],
) -> None:
    client, dispatch = client_and_dispatch
    workspace, employee = _company(client)

    created = client.post(
        f"/workspaces/{workspace['id']}/messages",
        json={
            "body": "@产品经理 梳理首次使用路径",
            "mention_employee_ids": [employee["id"]],
        },
    )
    listed = client.get(f"/workspaces/{workspace['id']}/messages")

    assert created.status_code == 202
    assert created.json()["body"] == "@产品经理 梳理首次使用路径"
    assert created.json()["mentions"] == [employee["id"]]
    assert created.json()["executions"][0]["status"] == "queued"
    assert listed.status_code == 200
    assert listed.json()["messages"] == [created.json()]
    assert dispatch.execution_ids == [
        ChatExecutionId(created.json()["executions"][0]["id"])
    ]


def test_unknown_workspace_uses_stable_error_envelope(
    client_and_dispatch: tuple[TestClient, RecordingChatDispatch],
) -> None:
    client, _dispatch = client_and_dispatch

    response = client.post(
        "/workspaces/missing/messages",
        json={"body": "不会保存", "mention_employee_ids": []},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"


def test_retry_failed_chat_execution(
    client_and_dispatch: tuple[TestClient, RecordingChatDispatch],
) -> None:
    client, dispatch = client_and_dispatch
    workspace, _employee = _company(client)
    created = client.post(
        f"/workspaces/{workspace['id']}/messages",
        json={"body": "@已离职员工 再试一次", "mention_employee_ids": ["employee-missing"]},
    ).json()

    retried = client.post(f"/chat-executions/{created['executions'][0]['id']}/retry")

    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert retried.json()["retry_count"] == 1
    assert dispatch.execution_ids == [ChatExecutionId(retried.json()["id"])]


def test_blank_message_is_rejected_without_persistence(
    client_and_dispatch: tuple[TestClient, RecordingChatDispatch],
) -> None:
    client, _dispatch = client_and_dispatch
    workspace, _employee = _company(client)

    response = client.post(
        f"/workspaces/{workspace['id']}/messages",
        json={"body": "   ", "mention_employee_ids": []},
    )

    assert response.status_code == 422
    assert client.get(f"/workspaces/{workspace['id']}/messages").json() == {
        "messages": []
    }
