"""
ClassificationResult model.

Stores the outcome of running document classification: the predicted
type, confidence, and the per-type raw scores + matched signals (as
JSONB) for transparency -- so a user or auditor can see *why* a
document was classified a certain way, not just the final label.

Like OCRResult, this is append-only history rather than a single
overwritten row: re-classifying (e.g. after a manual OCR re-run)
creates a new row. Document.document_type always reflects the most
recent classification.
"""
from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.document_enums import DocumentType


class ClassificationResult(Base, TimestampMixin):
    __tablename__ = "classification_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    predicted_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DocumentType.UNKNOWN.value
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    engine_name: Mapped[str] = mapped_column(String(30), nullable=False)

    # [{"matched_text": "...", "rule_description": "...", "weight": 2.5}, ...]
    signals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # {"INVOICE": 0.88, "PURCHASE_ORDER": 0.0, ...} -- full score breakdown,
    # not just the winner, so borderline calls can be reviewed/debugged.
    scores_by_type: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    document = relationship("Document", back_populates="classification_results", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<ClassificationResult id={self.id} document_id={self.document_id} "
            f"type={self.predicted_type} confidence={self.confidence:.2f}>"
        )
