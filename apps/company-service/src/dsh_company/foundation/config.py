from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DSH_COMPANY_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_root: Path = Path("../dsh-company-data")
    dsh_provider: str = "deepseek-official"
    dsh_model: str = "deepseek-v4-flash"
    session_root: Path = Path("../dsh-company-data/sessions")
    dsh_request_timeout_seconds: float = 60.0
    dsh_shutdown_timeout_seconds: float = 10.0
    dsh_base_url: str | None = None
    deepseek_api_key: SecretStr | None = Field(
        default=None, validation_alias="DEEPSEEK_API_KEY"
    )
    workspace_root: Path | None = None
    runtime_concurrency: int = Field(default=4, ge=1)

    @property
    def resolved_session_root(self) -> Path:
        if "session_root" in self.model_fields_set:
            return self.session_root
        return self.data_root / "sessions"

    @property
    def resolved_workspace_root(self) -> Path:
        return self.workspace_root or self.data_root / "workspaces"
