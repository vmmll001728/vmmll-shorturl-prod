"""Version endpoint — returns service version information."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import config

router = APIRouter(prefix="/api", tags=["version"])


@router.get("/version")
def get_version():
    """Return service version information.
    
    Returns:
        dict: Version metadata with 'version' and 'service' fields.
    """
    return {
        "version": config.app_version,
        "service": "shorturl",
    }
