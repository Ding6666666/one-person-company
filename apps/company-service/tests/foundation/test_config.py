from pathlib import Path

from dsh_company.foundation.config import Settings


def test_settings_read_company_environment(monkeypatch) -> None:
    monkeypatch.setenv("DSH_COMPANY_HOST", "0.0.0.0")
    monkeypatch.setenv("DSH_COMPANY_PORT", "8123")
    monkeypatch.setenv("DSH_COMPANY_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.host == "0.0.0.0"
    assert settings.port == 8123
    assert settings.log_level == "DEBUG"


def test_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DSH_COMPANY_HOST", raising=False)
    monkeypatch.delenv("DSH_COMPANY_PORT", raising=False)
    monkeypatch.delenv("DSH_COMPANY_LOG_LEVEL", raising=False)

    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.log_level == "INFO"


def test_settings_read_dsh_spike_environment(monkeypatch, tmp_path: Path) -> None:
    session_root = tmp_path / "sessions"
    monkeypatch.setenv("DSH_COMPANY_DSH_PROVIDER", "test-provider")
    monkeypatch.setenv("DSH_COMPANY_DSH_MODEL", "test-model")
    monkeypatch.setenv("DSH_COMPANY_SESSION_ROOT", str(session_root))

    settings = Settings()

    assert settings.dsh_provider == "test-provider"
    assert settings.dsh_model == "test-model"
    assert settings.session_root == session_root
    assert isinstance(settings.session_root, Path)
    assert settings.dsh_request_timeout_seconds == 60.0
    assert settings.dsh_shutdown_timeout_seconds == 10.0


def test_settings_resolve_runtime_roots_and_explicit_host_credential(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "keyless-explicit-credential")

    settings = Settings(data_root=tmp_path)

    assert settings.resolved_session_root == tmp_path / "sessions"
    assert settings.resolved_workspace_root == tmp_path / "workspaces"
    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "keyless-explicit-credential"
    assert "keyless-explicit-credential" not in repr(settings)
