"""Application configuration — all settings from environment or .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Config:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./shorturl.db")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
    default_expiry_days: int = int(os.getenv("DEFAULT_EXPIRY_DAYS", "30"))
    max_alias_length: int = int(os.getenv("MAX_ALIAS_LENGTH", "32"))
    min_alias_length: int = int(os.getenv("MIN_ALIAS_LENGTH", "3"))
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    prometheus_enabled: bool = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"
    cors_origins: List[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )
    app_version: str = os.getenv("APP_VERSION", "1.0.0")
    api_key: str = os.getenv("API_KEY", "")


config = Config()