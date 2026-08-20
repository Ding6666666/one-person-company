from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint
from dsh_company.dsh_gateway.spike_runtime import (
    DshSpikeRuntime,
    RecordingHarnessRuntime,
)


def test_attempt_cancel_is_harness_close_not_session_observe(tmp_path) -> None:
    runtime = RecordingHarnessRuntime(tmp_path)
    handle = runtime.start("employee-alpha", "wait for cancellation")

    result = handle.cancel()

    assert result.requested is True
    assert result.runtime_closed is True
    assert runtime.close_calls == 1


def test_two_employee_sessions_execute_without_crossing_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    with KeylessModelEndpoint() as endpoint:
        runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        alpha = runtime.run("employee-alpha", "remember ALPHA_ONLY")
        beta = runtime.run("employee-beta", "remember BETA_ONLY")

    assert alpha.session_id == "employee-alpha"
    assert beta.session_id == "employee-beta"
    assert alpha.finish_reason == "completed"
    assert beta.finish_reason == "completed"
    assert endpoint.request_for("remember ALPHA_ONLY").contains("ALPHA_ONLY")
    assert not endpoint.request_for("remember ALPHA_ONLY").contains("BETA_ONLY")
    assert endpoint.request_for("remember BETA_ONLY").contains("BETA_ONLY")
    assert not endpoint.request_for("remember BETA_ONLY").contains("ALPHA_ONLY")


def test_restart_continuation_is_not_exposed_by_public_sdk(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    with KeylessModelEndpoint() as endpoint:
        first_runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        first = first_runtime.run("employee-alpha", "remember ALPHA_ONLY")

        second_runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        restarted = second_runtime.run(
            "employee-alpha", "recall the employee marker"
        )

    assert first.finish_reason == "completed"
    assert restarted.session_id == "employee-alpha"
    assert restarted.finish_reason == "error"
    assert restarted.final_response == ""
    turn_end = next(event for event in restarted.events if event["type"] == "turn/end")
    data = turn_end["data"]
    assert isinstance(data, dict)
    reason = data["reason"]
    assert isinstance(reason, dict)
    assert reason["kind"] == "error"
    error = reason["error"]
    assert isinstance(error, dict)
    message = error["message"]
    assert isinstance(message, str)
    assert "id collision" in message
    assert len(endpoint.requests) == 1
    assert endpoint.requests[0].contains("ALPHA_ONLY")
    assert not endpoint.requests[0].contains("recall the employee marker")
