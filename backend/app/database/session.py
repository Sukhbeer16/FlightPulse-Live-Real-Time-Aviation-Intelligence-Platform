"""Lazy SQLAlchemy engine and request-scoped database sessions."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the engine on first database use, not during API startup."""
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured to use the database.")
    options = {"connect_timeout": 3} if database_url.startswith("postgresql") else {}
    return create_engine(database_url, pool_pre_ping=True, connect_args=options)


def get_db() -> Generator[Session, None, None]:
    """Yield one session and always close it after the request finishes."""
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with session_factory() as session:
        yield session
