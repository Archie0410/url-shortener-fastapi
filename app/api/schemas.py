from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class ShortenRequest(BaseModel):
    url: HttpUrl
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Optional TTL in days from creation",
    )


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    expires_at: datetime | None
