from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://graft:graft@localhost:5432/graft"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    encryption_key: str = ""  # Fernet key (urlsafe base64, 32 bytes)
    cors_origins: list[str] = []
    app_env: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
