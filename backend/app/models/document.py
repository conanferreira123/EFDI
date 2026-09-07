"""
Document model.

Represents an uploaded financial document and its lifecycle metadata.
The actual file bytes live on disk (or, in a production deployment,
object storage like S3) under settings.UPLOAD_DIR; this table tracks
everything needed to locate, identify, and govern that file.

`stored_filename` is a generated UUID-based name (never the user-supplied
original filename) to eliminate path traversal risk and filename
collisions. `original_filename` preserves what the user actually
uploaded, for display purposes.

`file_hash` (SHA-256) is stored now, ahead of need, because Phase 7's
duplicate-detection validation rule will query against it directly.

`is_deleted` implements a soft-delete: financial documents must remain
auditable even after a user "removes" them, so rows are never physically
deleted via the API.
"""
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.document_enums import DocumentStatus, DocumentType


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    document_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DocumentType.UNKNOWN.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DocumentStatus.UPLOADED.value, index=True
    )

    # New fields for company, vendor, and validation tracking
    company_code: Mapped[str] = mapped_column(String(20), nullable=True, index=True)
    vendor_code: Mapped[str] = mapped_column(String(20), nullable=True, index=True)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=True, index=True)
    

    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # SHA-256 hex digest
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploaded_by_user = relationship("User", back_populates="documents", lazy="joined")

    ocr_results = relationship(
        "OCRResult", back_populates="document", lazy="selectin",
        order_by="OCRResult.created_at.desc()",
    )
    classification_results = relationship(
        "ClassificationResult", back_populates="document", lazy="selectin",
        order_by="ClassificationResult.created_at.desc()",
    )
    extraction_results = relationship(
        "ExtractionResult", back_populates="document", lazy="selectin",
        order_by="ExtractionResult.created_at.desc()",
    )
    validation_results = relationship(
        "ValidationResult", back_populates="document", lazy="selectin",
        order_by="ValidationResult.created_at.desc()",
    )
    workflow_history = relationship(
        "WorkflowHistory", back_populates="document", lazy="selectin",
        order_by="WorkflowHistory.created_at.asc()",
    )
    document_chunks = relationship(
        "DocumentChunk", back_populates="document", lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.id.asc()",
    )
    # Deliberately lazy="select" (load on demand), unlike the
    # selectin relationships above -- AuditLog has its own
    # relationships back onto User and Document (see AuditLog's
    # lazy="select" comment), so eager-loading this one specifically
    # would create a self-feeding cascade that gets worse as the audit
    # trail grows. Nothing in the application reads
    # `document.audit_logs` as a Python attribute; AuditService queries
    # AuditLogRepository directly instead.
    audit_logs = relationship(
        "AuditLog", back_populates="document", lazy="select",
        order_by="AuditLog.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.original_filename!r} status={self.status}>"
