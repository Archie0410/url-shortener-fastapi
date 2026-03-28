from __future__ import annotations

import json
import ssl
from datetime import datetime, timezone
from typing import Any

import redis

from app.core.config import Settings, get_settings

_client: redis.Redis | None = None


def get_redis(settings: Settings | None = None) -> redis.Redis:
    global _client
    if _client is None:
        cfg = settings or get_settings()
        url = cfg.redis_url

        kwargs: dict[str, Any] = {
            "decode_responses": True,
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
        }

        if url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

        _client = redis.Redis.from_url(url, **kwargs)
    return _client


def reset_redis_client() -> None:
    """Close and clear client (useful for tests / hot reload)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def cache_key(short_code: str) -> str:
    return f"urlshort:v1:{short_code}"


def _ttl_until_expiry(expires_at: datetime | None, max_ttl: int) -> int:
    if expires_at is None:
        return max_ttl
    now = datetime.now(timezone.utc)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    seconds = int((exp - now).total_seconds())
    if seconds <= 0:
        return 0
    return min(max_ttl, seconds)


def cache_get(redis_client: redis.Redis, short_code: str) -> dict[str, Any] | None:
    raw = redis_client.get(cache_key(short_code))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def cache_set(
    redis_client: redis.Redis,
    short_code: str,
    payload: dict[str, Any],
    *,
    settings: Settings,
) -> None:
    ttl = _ttl_until_expiry(
        payload.get("expires_at"),
        settings.cache_ttl_seconds,
    )
    if ttl <= 0:
        return
    redis_client.setex(cache_key(short_code), ttl, json.dumps(payload, default=_json_default))


def cache_delete(redis_client: redis.Redis, short_code: str) -> None:
    redis_client.delete(cache_key(short_code))


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError
