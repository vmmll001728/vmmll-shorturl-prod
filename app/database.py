"""SQLAlchemy database engine and session factory."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import config
from app.models.link import Base

_is_sqlite = "sqlite" in config.database_url

engine = create_engine(
    config.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    echo=config.debug,
    pool_pre_ping=True,
    # P2: connection pool settings (PostgreSQL/MySQL; SQLite uses StaticPool)
    **(dict(
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        pool_recycle=config.db_pool_recycle,
    ) if not _is_sqlite else {}),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all tables (for testing)."""
    Base.metadata.drop_all(bind=engine)