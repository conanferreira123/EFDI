"""
ExtractionResult model.

Stores the outcome of running field extraction against a document's
OCR text: every field defined for that document's classified type
(app/extraction/field_schemas.py), each with its extracted value (or
null) and a confidence score -- so the future review/correction UI can
highlight OCR-found fields and let a user fill in the nulls.

Like OCRResult and ClassificationResult, this is append-only history:
re-running extraction creates a new row rather than overwriting.
`document_type` is snapshotted at extraction time (not re-read from
Document at query time) so a later re-classification doesn't silently
make historical extraction results inconsistent with the type they
were actually extracted against.
"""
from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class ExtractionResult(Base, TimestampMixin):
    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(30), nullable=False)

    # {"invoice_number": {"value": "INV-001", "confidence": 0.9, "matched_text": "..."}, ...}
    # One entry per field in that type's schema, value is null if not found.
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fields_found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document = relationship("Document", back_populates="extraction_results", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<ExtractionResult id={self.id} document_id={self.document_id} "
            f"type={self.document_type} found={self.fields_found_count}/{self.fields_total_count}>"
        )
