"""
Validation service: orchestrates running the validation engine against
the latest extraction result, persisting the report, and conditionally
advancing Document.status to VALIDATED.

Design decision: Document.status only advances to VALIDATED when the
report has zero ERROR-severity issues (ValidationResult.is_valid is
True). Warnings alone do not block the transition. If there are errors,
status remains at EXTRACTED -- this makes "stuck, needs fixing" visible
directly from the workflow status rather than requiring a separate
query against ValidationResult every time.
"""
import logging

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailedException
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.repositories.validation_result_repository import ValidationResultRepository
from app.validation.engine import run_validation

logger = logging.getLogger(__name__)


class ValidationService:
    def __init__(self, db: Session):
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.extraction_repo = ExtractionResultRepository(db)
        self.validation_repo = ValidationResultRepository(db)

    def validate(self, document: Document):
        extraction_result = self.extraction_repo.get_latest_for_document(document.id)
        if not extraction_result:
            raise ValidationFailedException(
                "Cannot validate a document with no extraction result. "
                "Run extraction first via POST /extraction/documents/{id}/extract."
            )

        report = run_validation(self.db, document, extraction_result.document_type, extraction_result.fields)

        issues_payload = [
            {
                "rule_type": issue.rule_type.value,
                "severity": issue.severity.value,
                "field_key": issue.field_key,
                "message": issue.message,
            }
            for issue in report.issues
        ]

        validation_result = self.validation_repo.create(
            document_id=document.id,
            document_type=report.document_type,
            engine_name=report.engine_name,
            is_valid=report.is_valid,
            error_count=report.error_count,
            warning_count=report.warning_count,
            issues=issues_payload,
        )

        if report.is_valid:
            self.document_repo.update_status(document, DocumentStatus.VALIDATED.value)
        # else: status remains at EXTRACTED, visibly indicating the
        # document needs fixes before it can proceed.

        logger.info(
            "Document validated: document_id=%s is_valid=%s errors=%s warnings=%s",
            document.id, report.is_valid, report.error_count, report.warning_count,
        )

        return validation_result

    def get_latest_result(self, document_id: int):
        return self.validation_repo.get_latest_for_document(document_id)

    def list_results(self, document_id: int):
        return self.validation_repo.list_for_document(document_id)
