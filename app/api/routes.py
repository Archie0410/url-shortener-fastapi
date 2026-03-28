from __future__ import annotations

import logging
import redis
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_redis_client, get_url_service
from app.api.schemas import ShortenRequest, ShortenResponse
from app.core.config import Settings, get_settings
from app.services.url_service import ResolveStatus, UrlService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


def _public_short_url(settings: Settings, short_code: str) -> str:
    base = str(settings.short_url_base).rstrip("/") + "/"
    return urljoin(base, short_code)


@router.post(
    "/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
)
def shorten_url(
    body: ShortenRequest,
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
    service: UrlService = Depends(get_url_service),
    settings: Settings = Depends(get_settings),
) -> ShortenResponse:
    long_url = str(body.url)
    try:
        result = service.shorten(
            db,
            redis_client,
            long_url,
            body.expires_in_days,
        )
    except RuntimeError as exc:
        logger.exception("shorten failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create a short link. Try again.",
        ) from exc

    return ShortenResponse(
        short_code=result.short_code,
        short_url=_public_short_url(settings, result.short_code),
        long_url=result.long_url,
        expires_at=result.expires_at,
    )


@router.get("/{short_code}")
def redirect_short_code(
    short_code: str,
    db: Session = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
    service: UrlService = Depends(get_url_service),
) -> RedirectResponse:
    resolved = service.resolve(db, redis_client, short_code)

    if resolved.status == ResolveStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This short link has expired.",
        )
    if resolved.status in (ResolveStatus.NOT_FOUND, ResolveStatus.INVALID_CODE):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short link not found.",
        )
    if not resolved.long_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short link not found.",
        )

    return RedirectResponse(url=resolved.long_url, status_code=status.HTTP_302_FOUND)
