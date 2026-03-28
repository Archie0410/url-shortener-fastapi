from __future__ import annotations

import redis

from app.core.config import get_settings
from app.db.session import get_db
from app.services.redis_cache import get_redis
from app.services.url_service import UrlService


def get_redis_client() -> redis.Redis:
    return get_redis(get_settings())


def get_url_service() -> UrlService:
    return UrlService(get_settings())
