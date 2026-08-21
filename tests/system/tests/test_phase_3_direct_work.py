import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint
from dsh_company.foundation.app import create_app
from dsh_company.foundation.config import Settings
from fastapi.testclient import TestClient


def _employee_payload(display_name: str) -> dict[str, object]:
    return {
        "display_name": display_name,
        "responsibility": "Complete direct work safely",
        "runtime_profile": "network_denied",
        "model": "dsh-company-keyless-model",
        "grants": [],
    }


def _wait_for_terminal(client: TestClient, work_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/works/{work_id}")
        response.raise_for_status()
        work = response.json()
        if work["status"] in {"blocked", "completed", "failed", "cancelled"}:
            return work
        time.sleep(0.02)
    raise AssertionError(f"work {work_id} did not reach a terminal state")


def _create_work(
    client: TestClient,
    workspace_id: str,
    employee_id: str,
    *,
    objective: str,
    command_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/workspaces/{workspace_id}/works",
        json={
            "employee_id": employee_id,
            "objective": objective,
            "acceptance_criteria": ["Return the marker"],
            "command_id": command_id,
        },
    )
    response.raise_for_status()
    return response.json()


def test_direct_work_runs_safely_and_isolates_employee_sessions(
    tmp_path: Path, monkeypatch
) -> None:
    with KeylessModelEndpoint() as endpoint:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsh-company-keyless-test")
        settings = Settings(
            data_root=tmp_path / "data",
            session_root=tmp_path / "sessions",
            dsh_base_url=endpoint.base_url,
            dsh_request_timeout_seconds=20,
            dsh_shutdown_timeout_seconds=2,
        )
        with TestClient(create_app(settings=settings)) as client:
            workspace_response = client.post("/workspaces", json={"name": "Direct work"})
            workspace_response.raise_for_status()
            workspace = workspace_response.json()
            employee_response = client.post(
                f"/workspaces/{workspace['id']}/employees",
                json=_employee_payload("Writer"),
            )
            employee_response.raise_for_status()
            employee = employee_response.json()

            first = _create_work(
                client,
                workspace["id"],
                employee["id"],
                objective="remember DIRECT_WORK_RESULT",
                command_id="direct-work-1",
            )
            work = _wait_for_terminal(client, first["id"])
            events_response = client.get(f"/works/{work['id']}/events")
            events_response.raise_for_status()
            events = events_response.json()

            second = _create_work(
                client,
                workspace["id"],
                employee["id"],
                objective="remember SECOND_SAME_EMPLOYEE",
                command_id="direct-work-2",
            )
            second_terminal = _wait_for_terminal(client, second["id"])

            other_workspace_response = client.post("/workspaces", json={"name": "Isolated work"})
            other_workspace_response.raise_for_status()
            other_workspace = other_workspace_response.json()
            other_employee_response = client.post(
                f"/workspaces/{other_workspace['id']}/employees",
                json=_employee_payload("Other writer"),
            )
            other_employee_response.raise_for_status()
            other_employee = other_employee_response.json()
            isolated = _create_work(
                client,
                other_workspace["id"],
                other_employee["id"],
                objective="remember ISOLATED_EMPLOYEE_RESULT",
                command_id="isolated-work-1",
            )
            isolated_terminal = _wait_for_terminal(client, isolated["id"])

            all_api_content = json.dumps([work, events, second_terminal, isolated_terminal])

    assert work["status"] == "completed"
    assert len(work["artifacts"]) == 1
    assert events[-1]["event_type"] == "work.completed"
    assert all(
        event["summary"] == event["event_type"] or event["source"] == "company" for event in events
    )
    assert "final_response" not in all_api_content
    assert "stored remember DIRECT_WORK_RESULT" not in all_api_content

    # The fixed public SDK exposes no resume operation. Reusing the stable Session
    # ID in a fresh Attempt returns its closed error result before a second model
    # request; Company must not mistake that result for completed work.
    assert second_terminal["status"] == "failed"
    assert second_terminal["execution_links"][0]["diagnostic_code"] == "gateway_error"
    assert not any(request.contains("SECOND_SAME_EMPLOYEE") for request in endpoint.requests)

    isolated_request = next(
        request for request in endpoint.requests if request.contains("ISOLATED_EMPLOYEE_RESULT")
    )
    assert not isolated_request.contains("DIRECT_WORK_RESULT")

    assert isolated_terminal["status"] == "completed"
    assert (
        work["artifacts"][0]["uri"].split("/attempt/")[0]
        != isolated_terminal["artifacts"][0]["uri"].split("/attempt/")[0]
    )

    database_path = settings.data_root / "company.db"
    with closing(sqlite3.connect(database_path)) as connection:
        stored_text = json.dumps(
            connection.execute(
                "SELECT event_type, summary FROM company_events ORDER BY observed_at"
            ).fetchall()
        )
    assert "stored remember DIRECT_WORK_RESULT" not in stored_text


def test_cancel_persists_request_before_real_runtime_close(tmp_path: Path, monkeypatch) -> None:
    with KeylessModelEndpoint() as endpoint:
        held = endpoint.hold("SLOW_DIRECT_WORK")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsh-company-keyless-test")
        settings = Settings(
            data_root=tmp_path / "data",
            session_root=tmp_path / "sessions",
            dsh_base_url=endpoint.base_url,
            dsh_request_timeout_seconds=20,
            dsh_shutdown_timeout_seconds=2,
        )
        with TestClient(create_app(settings=settings)) as client:
            workspace_response = client.post("/workspaces", json={"name": "Cancellation"})
            workspace_response.raise_for_status()
            workspace = workspace_response.json()
            employee_response = client.post(
                f"/workspaces/{workspace['id']}/employees",
                json=_employee_payload("Slow writer"),
            )
            employee_response.raise_for_status()
            employee = employee_response.json()
            work = _create_work(
                client,
                workspace["id"],
                employee["id"],
                objective="remember SLOW_DIRECT_WORK",
                command_id="slow-work-1",
            )
            assert held.request_started.wait(timeout=10)

            cancel_response: list[dict[str, Any]] = []

            def cancel() -> None:
                response = client.post(f"/works/{work['id']}/cancel")
                response.raise_for_status()
                cancel_response.append(response.json())

            cancel_thread = threading.Thread(target=cancel)
            cancel_thread.start()
            saw_cancel_requested = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and cancel_thread.is_alive():
                current = client.get(f"/works/{work['id']}").json()
                if current["execution_links"][0]["status"] == "cancel_requested":
                    saw_cancel_requested = True
                    break
            held.release_response.set()
            cancel_thread.join(timeout=10)
            assert not cancel_thread.is_alive()

        assert saw_cancel_requested
        assert cancel_response[0]["status"] == "cancelled"
        assert cancel_response[0]["execution_links"][0]["status"] == "cancelled"


def test_restart_blocks_a_seeded_running_attempt_without_inventing_a_result(
    tmp_path: Path, monkeypatch
) -> None:
    with KeylessModelEndpoint() as endpoint:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsh-company-keyless-test")
        settings = Settings(
            data_root=tmp_path / "data",
            session_root=tmp_path / "sessions",
            dsh_base_url=endpoint.base_url,
            dsh_request_timeout_seconds=20,
            dsh_shutdown_timeout_seconds=2,
        )
        with TestClient(create_app(settings=settings)) as client:
            workspace_response = client.post("/workspaces", json={"name": "Restart recovery"})
            workspace_response.raise_for_status()
            workspace = workspace_response.json()
            employee_response = client.post(
                f"/workspaces/{workspace['id']}/employees",
                json=_employee_payload("Recovery writer"),
            )
            employee_response.raise_for_status()
            employee = employee_response.json()
            created = _create_work(
                client,
                workspace["id"],
                employee["id"],
                objective="remember RESTART_SEED",
                command_id="restart-seed-1",
            )
            completed = _wait_for_terminal(client, created["id"])
            assert completed["status"] == "completed"

        database_path = settings.data_root / "company.db"
        attempt_id = completed["execution_links"][0]["attempt_id"]
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute("UPDATE works SET status = 'running' WHERE id = ?", (created["id"],))
            connection.execute(
                "UPDATE work_nodes SET status = 'running', active_attempt_id = ?, "
                "failure_code = NULL, version = version + 1 WHERE work_id = ?",
                (attempt_id, created["id"]),
            )
            connection.execute(
                "UPDATE execution_links SET status = 'running', finished_at = NULL, "
                "diagnostic_code = NULL WHERE attempt_id = ?",
                (attempt_id,),
            )
            connection.execute(
                "DELETE FROM artifact_references WHERE source_attempt_id = ?",
                (attempt_id,),
            )
            connection.commit()

        request_count_before_restart = len(endpoint.requests)
        with TestClient(create_app(settings=settings)) as client:
            recovered_response = client.get(f"/works/{created['id']}")
            recovered_response.raise_for_status()
            recovered = recovered_response.json()

        assert recovered["status"] == "blocked"
        assert recovered["nodes"][0]["failure_code"] == "runtime_process_lost"
        assert recovered["execution_links"][0]["diagnostic_code"] == "runtime_process_lost"
        assert recovered["artifacts"] == []
        assert len(endpoint.requests) == request_count_before_restart

        database_path.unlink()
        assert not database_path.exists()
