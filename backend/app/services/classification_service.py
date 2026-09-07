"""
Classification service: orchestrates running document classification
against the latest OCR text and persisting the result.
"""
import logging

from sqlalchemy.orm import Session

from app.classification.factory import get_classification_engine
from app.core.exceptions import NotFoundException, ValidationFailedException
from app.models.document import Document
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.ocr_result_repository import OCRResultRepository

logger = logging.getLogger(__name__)


class ClassificationService:
    def __init__(self, db: Session):
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.ocr_repo = OCRResultRepository(db)
        self.classification_repo = ClassificationResultRepository(db)

    def classify(self, document: Document, *, engine_name: str | None = None):
        ocr_result = self.ocr_repo.get_latest_for_document(document.id)
        if not ocr_result:
            raise ValidationFailedException(
                "Cannot classify a document with no OCR result. Run OCR first "
                "via POST /ocr/documents/{id}/run."
            )

        engine = get_classification_engine(engine_name or "rule_based")
        result_data = engine.classify(ocr_result.full_text)

        signals = [
            {
                "matched_text": s.matched_text,
                "rule_description": s.rule_description,
                "weight": s.weight,
            }
            for s in result_data.signals
        ]

        classification_result = self.classification_repo.create(
            document_id=document.id,
            predicted_type=result_data.document_type.value,
            confidence=result_data.confidence,
            engine_name=result_data.engine_name,
            signals=signals,
            scores_by_type=result_data.scores_by_type,
        )

        # Update the document's document_type to reflect the latest
        # classification. Per design decision: classification does NOT
        # advance Document.status -- it stays at OCR_COMPLETED until
        # Phase 6 (extraction) advances it to EXTRACTED, since the
        # workflow spec has no dedicated "classified" state.
        document.document_type = result_data.document_type.value
        self.db.commit()
        self.db.refresh(document)

        logger.info(
            "Document classified: document_id=%s type=%s confidence=%.2f engine=%s",
            document.id, result_data.document_type.value, result_data.confidence, engine.name,
        )
        return classification_result

    def get_latest_result(self, document_id: int):
        return self.classification_repo.get_latest_for_document(document_id)

    def list_results(self, document_id: int):
        return self.classification_repo.list_for_document(document_id)

    def correct_type(self, document: Document, corrected_type: str):
        """
        Apply a human correction to a document's classification.
        Updates BOTH the stored ClassificationResult (so the UI/audit
        trail show the corrected type, not the original wrong guess)
        AND Document.document_type (the field that actually determines
        which field schema extraction uses downstream -- see
        ExtractionService.extract). Both must change together, or a
        "corrected" document would still extract against the wrong
        type's field schema.
        """
        result = self.classification_repo.get_latest_for_document(document.id)
        if not result:
            raise NotFoundException("Classification result for document", document.id)

        updated_result = self.classification_repo.correct_type(result, corrected_type)

        document.document_type = corrected_type
        self.db.commit()
        self.db.refresh(document)

        logger.info(
            "Classification manually corrected: document_id=%s corrected_type=%s",
            document.id, corrected_type,
        )
        return updated_result
