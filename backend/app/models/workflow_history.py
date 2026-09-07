"""
WorkflowHistory model.

Append-only audit log of every approval-workflow transition performed
on a document: who did what, when, what the status was before/after,
and any comment (mandatory for rejections, optional otherwise). This is
the "workflow history" deliverable called for by the spec, and is also
a natural feed for Phase 9's audit system.
"""
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class WorkflowHistory(Base, TimestampMixin):
    __tablename__ = "workflow_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    document = relationship("Document", back_populates="workflow_history", lazy="joined")
    performed_by_user = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<WorkflowHistory id={self.id} document_id={self.document_id} "
            f"action={self.action} {self.from_status}->{self.to_status}>"
        )
