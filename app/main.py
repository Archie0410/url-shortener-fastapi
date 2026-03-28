from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings
from app.db.models import Base
from app.db.session import engine
from app.services.redis_cache import get_redis, reset_redis_client

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    get_settings.cache_clear()
    Base.metadata.create_all(bind=engine)

    try:
        get_redis(get_settings()).ping()
        logger.info("Redis connection OK")
    except redis.RedisError as exc:
        logger.warning("Redis unavailable: %s", exc)

    yield

    reset_redis_client()


app = FastAPI(
    title="URL Shortener",
    lifespan=lifespan,
)

app.include_router(router)
