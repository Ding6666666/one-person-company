from pathlib import Path
from typing import Literal

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
