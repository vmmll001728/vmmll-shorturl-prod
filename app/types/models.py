"""Shared Pydantic types."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class LinkCreate(BaseModel):
    url: str = Field(..., description="Original URL to shorten")
    custom_alias: Optional[str] = Field(None, max_length=32, description="Custom short code")
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650, description="Expiry in days")

    @field_validator("url")
    @classmethod
    def url_must_be_valid(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.strip().rstrip("/")

    @field_validator("custom_alias")
    @classmethod
    def alias_must_be_alphanumeric(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.replace("-", "").replace("_", "").isalnum():
                raise ValueError("Alias must be alphanumeric (dash/underscore allowed)")
            v = v.lower()
        return v


class LinkCreateResponse(BaseModel):
    short_url: str
    original_url: str
    alias: str
    expires_at: Optional[datetime]
    created_at: datetime


class LinkInfo(BaseModel):
    alias: str
    original_url: str
    click_count: int
    expires_at: Optional[datetime]
    created_at: datetime
    is_expired: bool


class LinkRedirect(BaseModel):
    original_url: str


class HealthCheck(BaseModel):
    status: str = "ok"
    timestamp: datetime
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    success: bool = False
    data: Optional[object] = None
    error: dict


class SuccessResponse(BaseModel):
    """Unified success response wrapper."""

    success: bool = True
    data: Optional[object] = None