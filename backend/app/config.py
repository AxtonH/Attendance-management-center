"""Application settings, loaded from environment variables.

Centralized so no other module reads os.environ directly. Tests override by
constructing Settings(...) with explicit kwargs.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (backend/app/config.py).
# Used to anchor relative CONFIG_DIR values so the backend works regardless
# of which directory uvicorn was launched from.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")

    app_timezone: str = Field(default="Asia/Amman", alias="APP_TIMEZONE")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    config_dir: Path = Field(default=Path("./config"), alias="CONFIG_DIR")

    cors_allow_origins: str = Field(
        default="http://localhost:3000",
        alias="CORS_ALLOW_ORIGINS",
    )

    # Odoo (phase 2). When odoo_url is empty the app falls back to the
    # punch-derived phase-1 roster — that's the seam that lets either side
    # run independently in dev.
    odoo_url: str = Field(default="", alias="ODOO_URL")
    odoo_db: str = Field(default="", alias="ODOO_DB")
    odoo_username: str = Field(default="", alias="ODOO_USERNAME")
    odoo_password: str = Field(default="", alias="ODOO_PASSWORD")
    odoo_employee_cache_ttl: int = Field(default=300, alias="ODOO_EMPLOYEE_CACHE_TTL")
    odoo_batch_size: int = Field(default=500, alias="ODOO_BATCH_SIZE")

    @property
    def odoo_configured(self) -> bool:
        return bool(self.odoo_url and self.odoo_db and self.odoo_username and self.odoo_password)

    @property
    def resolved_config_dir(self) -> Path:
        """Absolute path to the config directory.

        Relative paths in CONFIG_DIR are resolved against the repo root, not
        the current working directory — uvicorn can be launched from anywhere.
        """
        if self.config_dir.is_absolute():
            return self.config_dir
        return (_REPO_ROOT / self.config_dir).resolve()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
