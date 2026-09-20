"""SQLAlchemy database connection, pooling, and session management."""

import logging
import os
import re
from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_ENGINE_CACHE: dict[str, Engine] = {}
_SESSION_FACTORY_CACHE: dict[str, sessionmaker[Session]] = {}


def mask_database_url(url: str | None) -> str:
    """Mask database passwords in connection URLs for safe logging and error display."""
    if not url:
        return "None"
    try:
        parts = urlsplit(url)
        if parts.password:
            netloc = f"{parts.username}:***@{parts.hostname}"
            if parts.port:
                netloc += f":{parts.port}"
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return url
    except Exception:
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def normalize_database_url(url: str | None) -> str:
    """Ensure appropriate driver prefix for PostgreSQL URLs."""
    if not url:
        raise ValueError("Database URL is not configured.")
    trimmed = url.strip()
    if trimmed.startswith("postgres://"):
        return "postgresql+psycopg2://" + trimmed[len("postgres://"):]
    if trimmed.startswith("postgresql://") and not trimmed.startswith("postgresql+"):
        return "postgresql+psycopg2://" + trimmed[len("postgresql://"):]
    return trimmed


def get_engine(database_url: str | None = None, **engine_kwargs) -> Engine:
    """Create or retrieve a cached SQLAlchemy engine with connection pooling."""
    raw_url = database_url or os.getenv("DATABASE_URL")
    if not raw_url:
        raise ValueError("DATABASE_URL is not set.")
    url = normalize_database_url(raw_url)
    if url in _ENGINE_CACHE:
        return _ENGINE_CACHE[url]

    kwargs = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update({"pool_size": 10, "max_overflow": 20})
    kwargs.update(engine_kwargs)

    try:
        engine = create_engine(url, **kwargs)
        _ENGINE_CACHE[url] = engine
        return engine
    except Exception as error:
        masked = mask_database_url(url)
        raise RuntimeError(f"Failed to initialize database engine for {masked}: {error}") from error


def get_session_factory(engine: Engine | None = None, database_url: str | None = None) -> sessionmaker[Session]:
    """Retrieve or create a sessionmaker bound to the given engine."""
    eng = engine or get_engine(database_url)
    cache_key = str(eng.url)
    if cache_key in _SESSION_FACTORY_CACHE:
        return _SESSION_FACTORY_CACHE[cache_key]

    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    _SESSION_FACTORY_CACHE[cache_key] = factory
    return factory


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_connection(database_url: str | None = None) -> tuple[bool, str]:
    """Verify database connectivity without throwing unhandled exceptions."""
    try:
        engine = get_engine(database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connection successful"
    except Exception as error:
        masked = mask_database_url(database_url or os.getenv("DATABASE_URL"))
        return False, f"Could not connect to database ({masked}): {error}"


def clear_engine_cache() -> None:
    """Dispose and clear cached engines (useful for tests)."""
    for engine in _ENGINE_CACHE.values():
        try:
            engine.dispose()
        except Exception:
            pass
    _ENGINE_CACHE.clear()
    _SESSION_FACTORY_CACHE.clear()
