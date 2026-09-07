"""
AuditLog model.

Append-only system-wide audit trail, distinct from WorkflowHistory
(Phase 8): WorkflowHistory is specifically the approval state machine's
transition log; AuditLog is the broader record of every significant
user action across the whole platform -- login, registration, upload,
delete, OCR, classification, extraction, manual field correction,
validation, and every workflow action -- per the original Phase 9 spec.

`document_id` is nullable because not every audited action concerns a
document (e.g. LOGIN_SUCCESS, LOGIN_FAILED, USER_REGISTERED).

`user_id` is nullable specifically for LOGIN_FAILED: a failed login
attempt is exactly the case where we may not have a valid user to
attach the event to (wrong username entirely), but the attempt itself
is still security-relevant and must be recorded.

`details` is a JSON blob for action-specific context (e.g. the
attempted username on a failed login, the OCR engine used, the field
key on a manual correction) without needing a different column -- or a
different table -- per action type.
"""
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )

    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # NOTE: lazy="select" (the default, loaded on demand) rather than
    # "joined" here -- deliberately, unlike WorkflowHistory's analogous
    # relationships. AuditLog sits at the center of a relationship
    # cycle: Document.audit_logs (selectin) -> AuditLog.user (if
    # joined) -> User.audit_logs (selectin) -> AuditLog.document (if
    # joined) -> Document.audit_logs (selectin) -> ... Eager-loading
    # either side here turns one Document fetch into a cascade that
    # keeps re-triggering itself through every other user/document the
    # audit trail touches, growing without bound as the table grows.
    # Measured impact of getting this wrong: a single Document fetch
    # went from ~1s to ~30s+ (and climbing across repeated calls in the
    # same process) once audit_logs reached a few hundred rows.
    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id], lazy="select")
    document = relationship("Document", back_populates="audit_logs", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action} "
            f"user_id={self.user_id} document_id={self.document_id}>"
        )
