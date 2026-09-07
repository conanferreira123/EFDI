"""
OCRResult model.

Stores the outcome of running OCR on a Document: the full extracted
text, an overall confidence score, and the raw per-block detections
(text + confidence + bounding box) as JSON, for traceability and for
Phase 6's field-extraction step to consume.

One Document can have at most one *current* OCRResult per run, but we
don't enforce a hard one-to-one at the DB level -- re-running OCR
(e.g. after a manual rotation fix) creates a new row rather than
overwriting history, which matches the audit-trail spirit of the rest
of this system. The document's `status` field and the most recent
OCRResult (by created_at) represent the "current" state.
"""
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class OCRResult(Base, TimestampMixin):
    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    engine_name: Mapped[str] = mapped_column(String(30), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    average_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Raw per-block detections, structured as:
    # [{"page_number": 1, "blocks": [{"text": ..., "confidence": ..., "bounding_box": [...]}]}]
    # Stored as JSONB (not a normalized table) because this data is
    # write-once/read-whole -- nothing in the app queries individual
    # blocks by their own attributes, so a relational breakdown would
    # add join overhead with no query benefit.
    raw_blocks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document = relationship("Document", back_populates="ocr_results", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<OCRResult id={self.id} document_id={self.document_id} "
            f"engine={self.engine_name} confidence={self.average_confidence:.2f}>"
        )
