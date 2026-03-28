from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import redis
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import ShortLink
from app.encoding.base62 import Base62Error, decode_base62, encode_base62
from app.services import redis_cache

logger = logging.getLogger(__name__)


class ResolveStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    INVALID_CODE = "invalid_code"


@dataclass(frozen=True)
class ShortenResult:
    short_code: str
    long_url: str
    expires_at: datetime | None


@dataclass(frozen=True)
class ResolveResult:
    status: ResolveStatus
    long_url: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _allocate_id(db: Session) -> int:
    return db.execute(text("SELECT nextval('short_links_id_seq')")).scalar_one()


class UrlService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def shorten(
        self,
        db: Session,
        redis_client: redis.Redis | None,
        long_url: str,
        expires_in_days: int | None,
    ) -> ShortenResult:
        expires_at: datetime | None = None
        if expires_in_days is not None:
            expires_at = _utcnow() + timedelta(days=expires_in_days)

        last_error: Exception | None = None
        for attempt in range(self._settings.max_shorten_attempts):
            new_id = _allocate_id(db)
            short_code = encode_base62(new_id)
            link = ShortLink(
                id=new_id,
                short_code=short_code,
                long_url=long_url,
                expires_at=expires_at,
            )
            db.add(link)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                last_error = exc
                logger.warning(
                    "short_code collision on insert; retrying",
                    extra={"short_code": short_code, "attempt": attempt + 1},
                )
                continue

            db.refresh(link)
            logger.info("created short link", extra={"short_code": short_code, "id": new_id})

            if redis_client is not None:
                try:
                    redis_cache.cache_set(
                        redis_client,
                        short_code,
                        {"long_url": long_url, "expires_at": expires_at},
                        settings=self._settings,
                    )
                except redis.RedisError as exc:
                    logger.warning("redis cache set failed", extra={"error": str(exc)})

            return ShortenResult(
                short_code=short_code,
                long_url=long_url,
                expires_at=expires_at,
            )

        logger.error("exhausted shorten retries", exc_info=last_error)
        raise RuntimeError("Could not allocate a unique short code") from last_error

    def resolve(
        self,
        db: Session,
        redis_client: redis.Redis | None,
        short_code: str,
    ) -> ResolveResult:
        try:
            decode_base62(short_code)
        except Base62Error:
            return ResolveResult(status=ResolveStatus.INVALID_CODE)

        if redis_client is not None:
            try:
                cached = redis_cache.cache_get(redis_client, short_code)
            except redis.RedisError as exc:
                logger.warning("redis cache get failed", extra={"error": str(exc)})
                cached = None
            if cached is not None:
                return self._resolve_from_cache_payload(
                    db,
                    redis_client,
                    short_code,
                    cached,
                )

        link = db.execute(
            select(ShortLink).where(ShortLink.short_code == short_code),
        ).scalar_one_or_none()

        if link is None:
            return ResolveResult(status=ResolveStatus.NOT_FOUND)

        if link.expires_at is not None:
            exp = link.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < _utcnow():
                if redis_client is not None:
                    try:
                        redis_cache.cache_delete(redis_client, short_code)
                    except redis.RedisError as exc:
                        logger.warning("redis cache delete failed", extra={"error": str(exc)})
                return ResolveResult(status=ResolveStatus.EXPIRED)

        self._bump_clicks(db, short_code)

        if redis_client is not None:
            try:
                redis_cache.cache_set(
                    redis_client,
                    short_code,
                    {"long_url": link.long_url, "expires_at": link.expires_at},
                    settings=self._settings,
                )
            except redis.RedisError as exc:
                logger.warning("redis cache set failed", extra={"error": str(exc)})

        return ResolveResult(status=ResolveStatus.OK, long_url=link.long_url)

    def _resolve_from_cache_payload(
        self,
        db: Session,
        redis_client: redis.Redis,
        short_code: str,
        cached: dict,
    ) -> ResolveResult:
        raw_exp = cached.get("expires_at")
        expires_at: datetime | None = None
        if raw_exp:
            expires_at = datetime.fromisoformat(str(raw_exp).replace("Z", "+00:00"))

        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < _utcnow():
                try:
                    redis_cache.cache_delete(redis_client, short_code)
                except redis.RedisError as exc:
                    logger.warning("redis cache delete failed", extra={"error": str(exc)})
                return self.resolve(db, None, short_code)

        long_url = cached.get("long_url")
        if not long_url:
            try:
                redis_cache.cache_delete(redis_client, short_code)
            except redis.RedisError:
                pass
            return self.resolve(db, None, short_code)

        self._bump_clicks(db, short_code)
        return ResolveResult(status=ResolveStatus.OK, long_url=str(long_url))

    def _bump_clicks(self, db: Session, short_code: str) -> None:
        db.execute(
            update(ShortLink)
            .where(ShortLink.short_code == short_code)
            .values(click_count=ShortLink.click_count + 1),
        )
        db.commit()
