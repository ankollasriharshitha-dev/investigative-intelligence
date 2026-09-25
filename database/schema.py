"""Database schema creation, inspection, and migration utilities."""

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from database.connection import get_engine, mask_database_url
from database.models import Base

logger = logging.getLogger(__name__)


def init_db(engine: Engine | None = None, database_url: str | None = None) -> None:
    """Create all configured tables if they do not already exist."""
    eng = engine or get_engine(database_url)
    masked = mask_database_url(str(eng.url))
    logger.info("Initializing database schema on %s", masked)
    Base.metadata.create_all(bind=eng)
    logger.info("Database schema initialization complete.")


def drop_db(engine: Engine | None = None, database_url: str | None = None) -> None:
    """Drop all configured tables (primarily for testing and resets)."""
    eng = engine or get_engine(database_url)
    masked = mask_database_url(str(eng.url))
    logger.warning("Dropping database schema on %s", masked)
    Base.metadata.drop_all(bind=eng)


def get_table_counts(engine: Engine | None = None, database_url: str | None = None) -> dict[str, int]:
    """Inspect and return row counts for all application tables."""
    eng = engine or get_engine(database_url)
    inspector = inspect(eng)
    counts: dict[str, int] = {}
    with eng.connect() as conn:
        for table_name in inspector.get_table_names():
            if table_name in Base.metadata.tables:
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
                counts[table_name] = int(result or 0)
    return counts


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        init_db()
        print("Schema created successfully.")
        counts = get_table_counts()
        print("Table row counts:", counts)
    except Exception as error:
        print(f"Schema initialization failed: {error}", file=sys.stderr)
        sys.exit(1)
