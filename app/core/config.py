from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_postgres_url(url: str) -> str:
    """Render provides ``postgres://`` or ``postgresql://``.
    SQLAlchemy needs the driver suffix ``+psycopg2``."""
    url = re.sub(r"^postgres://", "postgresql+psycopg2://", url)
    url = re.sub(r"^postgresql://", "postgresql+psycopg2://", url)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "URL Shortener"
    debug: bool = False

    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/urlshortener",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    cache_ttl_seconds: int = Field(default=3600, ge=60)
    short_url_base: str = Field(
        default="http://localhost:8000",
        description="Public origin used when building short URLs in API responses",
    )

    max_shorten_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Retries when a generated short_code collides.",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        return _normalize_postgres_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
