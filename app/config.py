from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    session_cookie_secure: bool = True
    session_hours: int = Field(default=12, ge=1, le=168)


@lru_cache
def get_settings() -> Settings:
    return Settings()
