from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://graft:graft@localhost:5432/graft"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    encryption_key: str = ""  # Fernet key (urlsafe base64, 32 bytes)
    cors_origins: list[str] = []
    app_env: str = "dev"
    # Where uploaded originals live. App and worker must mount the same volume:
    # the worker re-reads the original on every attempt.
    storage_root: Path = Path("/data/uploads")

    @model_validator(mode="after")
    def _reject_placeholder_secrets_in_prod(self) -> "Settings":
        """Fail startup rather than run production on defaults.

        Dev stays bootable with no secrets so `/health` works out of the box;
        anything that actually touches a provider key still needs a valid Fernet
        key, because crypto raises on its own. Messages name the variable and
        never echo its value.
        """
        if self.app_env != "prod":
            return self
        if self.jwt_secret in ("", "change-me"):
            raise ValueError("JWT_SECRET must be set to a real secret when APP_ENV=prod")
        try:
            Fernet(self.encryption_key.encode())
        except Exception as exc:
            raise ValueError(
                "ENCRYPTION_KEY must be a valid Fernet key when APP_ENV=prod"
            ) from exc
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
