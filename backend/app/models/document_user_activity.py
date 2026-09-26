"""
DocumentUserActivity model.

Tracks user-initiated document interactions for the "Recently Viewed" feature.
Maintains exactly one record per (user_id, document_id) that updates on each
meaningful user action.
"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, utcnow


class DocumentUserActivity(Base, TimestampMixin):
    __tablename__ = "document_user_activity"
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", name="uq_document_user_activity_user_doc"),
        Index("ix_document_user_activity_user_last_activity", "user_id", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user = relationship("User", lazy="select")
    document = relationship("Document", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<DocumentUserActivity id={self.id} user_id={self.user_id} "
            f"document_id={self.document_id} last_activity_at={self.last_activity_at}>"
        )
