"""
User model.

Represents a person who can log into the platform. Role-based access
control is enforced via the `role` column (see app/models/roles.py)
and the dependency guards in app/core/security.py.

`is_active` allows an admin to disable an account without deleting it
(preserving audit/foreign-key history), which is standard practice for
enterprise systems where users are never truly deleted.
"""
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.roles import UserRole


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default=UserRole.FINANCE_ANALYST.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    documents = relationship(
        "Document",
        back_populates="uploaded_by_user",
        foreign_keys="Document.uploaded_by",
        lazy="select",
    )

    # Added in Phase 9 now that AuditLog exists, following the same
    # back_populates pattern as `documents` above -- but deliberately
    # lazy="select" (load on demand), not "selectin" like `documents`.
    # Nothing in the application reads `user.audit_logs` as a Python
    # attribute (AuditService queries AuditLogRepository directly
    # instead), so eager-loading it would mean every single User fetch
    # anywhere -- which happens on every authenticated request, via
    # get_current_user -- also unconditionally loads that user's full
    # audit history. Worse: AuditLog.user is itself a relationship back
    # onto User, so eager-loading both sides creates a self-feeding
    # cascade as the audit_logs table grows. See AuditLog's lazy="select"
    # comment for the measured cost of getting this wrong.
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        foreign_keys="AuditLog.user_id",
        lazy="select",
        order_by="AuditLog.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
