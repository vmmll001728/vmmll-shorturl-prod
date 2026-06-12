"""Link routes — create, query, delete, redirect."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import config
from app.models.link import Link
from app.types.models import (
    ErrorResponse,
    LinkCreate,
    LinkCreateResponse,
    LinkInfo,
    LinkRedirect,
    SuccessResponse,
)
from app.utils.slug import generate_slug, is_valid_alias

router = APIRouter(prefix="/api/v1", tags=["links"])


def get_db() -> Session:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post(
    "/links",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_link(body: LinkCreate, db: Session = Depends(get_db)) -> SuccessResponse:
    """Create a short link."""
    if body.custom_alias:
        if not is_valid_alias(body.custom_alias):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid alias: use only letters, numbers, dash, underscore",
            )
        if len(body.custom_alias) < config.min_alias_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alias must be at least {config.min_alias_length} characters",
            )
        existing = db.query(Link).filter(
            Link.alias == body.custom_alias,
            Link.is_deleted == False,  # noqa: E712
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Alias '{body.custom_alias}' already exists",
            )
        alias = body.custom_alias
    else:
        for _ in range(10):
            alias = generate_slug(length=6)
            if not db.query(Link).filter(Link.alias == alias).first():
                break
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate unique alias")

    expires_at: Optional[datetime] = None
    if body.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    link = Link(
        alias=alias,
        original_url=body.url,
        expires_at=expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return SuccessResponse(
        data={
            "short_url": f"{config.base_url}/{alias}",
            "original_url": link.original_url,
            "alias": alias,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "created_at": link.created_at.isoformat(),
        }
    )


@router.get(
    "/links/{alias}",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_link(alias: str, db: Session = Depends(get_db)) -> SuccessResponse:
    """Get info about a short link."""
    link = db.query(Link).filter(
        Link.alias == alias,
        Link.is_deleted == False,  # noqa: E712
    ).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    if link.is_expired:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Link has expired")
    return SuccessResponse(
        data={
            "alias": link.alias,
            "original_url": link.original_url,
            "click_count": link.click_count,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "created_at": link.created_at.isoformat(),
            "is_expired": link.is_expired,
        }
    )


@router.get(
    "/links",
    response_model=SuccessResponse,
)
def list_links(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """List all active links (paginated)."""
    total = db.query(Link).filter(Link.is_deleted == False).count()  # noqa: E712
    links = (
        db.query(Link)
        .filter(Link.is_deleted == False)  # noqa: E712
        .order_by(Link.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return SuccessResponse(
        data={
            "links": [
                {
                    "alias": l.alias,
                    "original_url": l.original_url,
                    "click_count": l.click_count,
                    "created_at": l.created_at.isoformat(),
                    "is_expired": l.is_expired,
                }
                for l in links
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.delete(
    "/links/{alias}",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}},
)
def delete_link(alias: str, db: Session = Depends(get_db)) -> SuccessResponse:
    """Soft-delete a link."""
    link = db.query(Link).filter(
        Link.alias == alias,
        Link.is_deleted == False,  # noqa: E712
    ).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    link.is_deleted = True
    db.commit()
    return SuccessResponse(data={"deleted": True, "alias": alias})


@router.get(
    "/{alias}",
    responses={
        302: {"description": "Redirect to original URL"},
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def redirect_to_original(alias: str, db: Session = Depends(get_db)):
    """Redirect to the original URL and increment click counter."""
    link = db.query(Link).filter(
        Link.alias == alias,
        Link.is_deleted == False,  # noqa: E712
    ).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    if link.is_expired:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Link has expired")
    link.click_count += 1
    db.commit()
    return RedirectResponse(url=link.original_url, status_code=status.HTTP_302_FOUND)