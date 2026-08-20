from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint
from dsh_company.dsh_gateway.spike_runtime import DshSpikeRuntime


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
