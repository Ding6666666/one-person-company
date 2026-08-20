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
