"""
ClassificationResult repository: data-access layer.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.classification_result import ClassificationResult


class ClassificationResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_latest_for_document(self, document_id: int) -> ClassificationResult | None:
        stmt = (
            select(ClassificationResult)
            .where(ClassificationResult.document_id == document_id)
            .order_by(ClassificationResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_document(self, document_id: int) -> list[ClassificationResult]:
        stmt = (
            select(ClassificationResult)
            .where(ClassificationResult.document_id == document_id)
            .order_by(ClassificationResult.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(
        self,
        *,
        document_id: int,
        predicted_type: str,
        confidence: float,
        engine_name: str,
        signals: list,
        scores_by_type: dict,
    ) -> ClassificationResult:
        result = ClassificationResult(
            document_id=document_id,
            predicted_type=predicted_type,
            confidence=confidence,
            engine_name=engine_name,
            signals=signals,
            scores_by_type=scores_by_type,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def correct_type(self, result: ClassificationResult, corrected_type: str) -> ClassificationResult:
        """
        Overwrite a stored classification result's predicted_type with
        a human-corrected value, setting confidence to 1.0 (a human
        verified this, full confidence) -- mirrors how
        ExtractionResultRepository.update_field marks a manually
        corrected field. The original engine_name/signals/scores_by_type
        are deliberately left untouched: they're the historical record
        of what the rule-based engine actually predicted and why, which
        is exactly the signal a future ML model needs to learn from
        (see TrainingExample, which separately stores the before/after
        pair) -- overwriting them here would destroy that record.
        """
        result.predicted_type = corrected_type
        result.confidence = 1.0
        self.db.commit()
        self.db.refresh(result)
        return result
