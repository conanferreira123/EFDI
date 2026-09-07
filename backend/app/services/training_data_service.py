"""
Training data service.

Captures every human correction (classification or extraction) as a
TrainingExample row -- the raw material a future ML model trains on.
Deliberately a thin, fire-and-forget logging layer: writing a training
example is never allowed to block or fail the actual correction the
user is making. If this logging fails, the correction itself must
still succeed -- a lost training example is a future-model-quality
problem; a failed correction is an immediate user-facing bug, and the
two must never be coupled.
"""
import logging

from sqlalchemy.orm import Session

from app.models.training_example import TrainingExample

logger = logging.getLogger(__name__)


class TrainingDataService:
    def __init__(self, db: Session):
        self.db = db

    def record_extraction_correction(
        self,
        *,
        document_id: int,
        corrected_by: int,
        document_type: str,
        source_text: str,
        field_key: str,
        predicted_value: str | None,
        corrected_value: str,
        extra_context: dict | None = None,
    ) -> None:
        try:
            example = TrainingExample(
                document_id=document_id,
                corrected_by=corrected_by,
                task_type="extraction",
                document_type=document_type,
                source_text=source_text,
                field_key=field_key,
                predicted_value=predicted_value,
                corrected_value=corrected_value,
                extra_context=extra_context,
            )
            self.db.add(example)
            self.db.commit()
        except Exception:
            # Deliberately broad: ANY failure here (DB hiccup, a
            # constraint we didn't anticipate, whatever) must not
            # propagate up into the correction request. Logged for
            # visibility, swallowed so the user-facing action succeeds
            # regardless.
            logger.exception(
                "Failed to record extraction training example for document_id=%s field=%s",
                document_id, field_key,
            )
            self.db.rollback()

    def record_classification_correction(
        self,
        *,
        document_id: int,
        corrected_by: int,
        document_type: str,
        source_text: str,
        predicted_value: str | None,
        corrected_value: str,
        extra_context: dict | None = None,
    ) -> None:
        try:
            example = TrainingExample(
                document_id=document_id,
                corrected_by=corrected_by,
                task_type="classification",
                document_type=document_type,
                source_text=source_text,
                field_key=None,
                predicted_value=predicted_value,
                corrected_value=corrected_value,
                extra_context=extra_context,
            )
            self.db.add(example)
            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to record classification training example for document_id=%s",
                document_id,
            )
            self.db.rollback()

    def record_validation_override(
        self,
        *,
        document_id: int,
        approved_by: int,
        document_type: str,
        source_text: str,
        field_key: str | None,
        rule_type: str,
        message: str,
    ) -> None:
        """
        Records the case where a document had a WARNING-severity
        validation issue (a business rule flagged something as
        anomalous, but not blocking) and a human approved it anyway.
        This is a genuinely useful signal distinct from a classification
        or extraction correction: the system's pattern-matching logic
        thought something looked off, and a human judged it acceptable.
        Over time, a rule that gets overridden constantly is a
        candidate for re-tuning (its threshold is probably too strict);
        a rule that's rarely overridden is probably calibrated well.

        Same fire-and-forget contract as the other record_* methods:
        this must never block or fail the approval action itself.
        """
        try:
            example = TrainingExample(
                document_id=document_id,
                corrected_by=approved_by,
                task_type="validation_override",
                document_type=document_type,
                source_text=source_text,
                field_key=field_key,
                predicted_value=rule_type,
                corrected_value="approved_despite_warning",
                extra_context={"message": message, "rule_type": rule_type},
            )
            self.db.add(example)
            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to record validation override training example for document_id=%s",
                document_id,
            )
            self.db.rollback()

    def record_rejection_reason(
        self,
        *,
        document_id: int,
        rejected_by: int,
        document_type: str,
        source_text: str,
        from_status: str,
        comment: str,
    ) -> None:
        """
        Records a workflow rejection's comment as a raw training signal:
        a human caught something the pipeline let through (the document
        had already reached from_status, meaning OCR/classification/
        extraction/validation all completed without blocking it) and
        rejected it with a stated reason. Unlike the other record_*
        methods this is free text rather than a structured field
        correction -- it doesn't map to a specific predicted/corrected
        value pair -- but it's still valuable raw material for a future
        rejection-reason classifier or for surfacing common rejection
        patterns to whoever tunes the rule sets.

        Same fire-and-forget contract as the other record_* methods:
        this must never block or fail the rejection action itself.
        """
        try:
            example = TrainingExample(
                document_id=document_id,
                corrected_by=rejected_by,
                task_type="workflow_rejection",
                document_type=document_type,
                source_text=source_text,
                field_key=None,
                predicted_value=from_status,
                corrected_value=comment,
                extra_context={"from_status": from_status},
            )
            self.db.add(example)
            self.db.commit()
        except Exception:
            logger.exception(
                "Failed to record rejection reason training example for document_id=%s",
                document_id,
            )
            self.db.rollback()
