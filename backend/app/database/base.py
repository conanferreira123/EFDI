"""
SQLAlchemy declarative base and common mixins.

Every ORM model in app/models/ should inherit from `Base`, and most
should also inherit `TimestampMixin` for created_at/updated_at tracking,
which is standard practice for enterprise audit-friendly schemas.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as a default for timestamp columns."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """
    Adds created_at / updated_at columns to a model.

    created_at is set once on insert. updated_at is refreshed on every
    update via onupdate, which is essential for audit trails showing
    when a record last changed.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def generate_uuid() -> str:
    """Generate a UUID4 string, used for public-facing resource identifiers."""
    return str(uuid.uuid4())
