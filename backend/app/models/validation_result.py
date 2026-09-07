"""
ValidationResult model.

Stores the outcome of running the validation engine against a
document's latest extraction result: every issue found (required
fields, date/amount/tax-ID format, duplicate detection, business
rules), plus a computed overall is_valid flag.

Append-only history, like OCRResult/ClassificationResult/
ExtractionResult: re-running validation (e.g. after a reviewer
manually corrects a field) creates a new row rather than overwriting,
preserving a full audit trail of how a document's validation status
changed over time.
"""
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class ValidationResult(Base, TimestampMixin):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(50), nullable=False)

    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # [{"rule_type": "REQUIRED_FIELD", "severity": "ERROR", "field_key": "po_number", "message": "..."}]
    issues: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    document = relationship("Document", back_populates="validation_results", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<ValidationResult id={self.id} document_id={self.document_id} "
            f"is_valid={self.is_valid} errors={self.error_count} warnings={self.warning_count}>"
        )
