"""
TrainingExample model.

Captures every human correction made through the UI -- both
classification corrections and extraction field corrections -- as a
labeled training example: the original document text the model/rules
saw, what was predicted, and what a human said the correct answer
actually is. This is the raw material a future ML model trains on;
nothing in the live request-serving path reads from this table, so
writing to it is pure side-effect logging, never a dependency of the
correction itself succeeding.

One row per single correction (one field, or one classification
verdict) rather than one row per document, since a document can
accumulate multiple corrections over its lifetime and each is an
independent training signal.
"""
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class TrainingExample(Base, TimestampMixin):
    __tablename__ = "training_examples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    corrected_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # "classification" or "extraction" -- not an enum at the DB level
    # since this is a small, internal-only distinction, and a future
    # third task type should be addable without a migration.
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    document_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # The actual OCR'd text the prediction was made from -- the core
    # model input. Denormalized (copied) here rather than joined from
    # ocr_results at training time, so a training example remains
    # complete and reproducible even if the underlying OCR result is
    # later deleted/reprocessed.
    source_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Null for task_type="classification" (the whole document gets one
    # type, not a per-field value).
    field_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    predicted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)

    # Free-form bag for task-specific extras that don't warrant their
    # own column -- e.g. classification's full scores_by_type
    # breakdown at correction time, or extraction's confidence/
    # matched_text. Never read by the live app; purely for future
    # model-training feature engineering.
    extra_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document = relationship("Document", lazy="joined")
    corrected_by_user = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<TrainingExample id={self.id} task={self.task_type} "
            f"document_id={self.document_id} field={self.field_key}>"
        )
