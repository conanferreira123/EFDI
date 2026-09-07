"""
Database engine and session management.

Provides:
- `engine`: the SQLAlchemy engine, configured once from settings.
- `SessionLocal`: a session factory.
- `get_db`: a FastAPI dependency that yields a session and guarantees
  it is closed after the request, even if an exception is raised.
"""
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# pool_pre_ping avoids "server closed the connection unexpectedly" errors
# after periods of idleness (common with managed Postgres / long-lived
# containers). pool_size/max_overflow are conservative defaults suitable
# for a single-instance API; tune for production load.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage:
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context-manager variant for use outside of FastAPI request handling
    (e.g. in scripts, background tasks, or startup seeding logic).
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> bool:
    """
    Verify the database is reachable. Used at startup to fail fast
    with a clear error instead of surfacing a confusing first-request
    failure.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database connection check failed: %s", exc)
        return False
