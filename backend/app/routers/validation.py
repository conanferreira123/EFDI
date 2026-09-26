"""
Validation routes.

Access model mirrors documents/OCR/classification/extraction: re-uses
DocumentService's existing role-scoping rules via get_for_user.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundException
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.schemas.validation import ValidateRequest, ValidationResultResponse
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validation", tags=["Validation"])


@router.post(
    "/documents/{document_id}/validate",
    response_model=ValidationResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def validate_document(
    document_id: int,
    payload: ValidateRequest = ValidateRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationResultResponse:
    """
    Run validation (required fields, date/amount/tax-ID format,
    duplicate detection, business rules) against a document's latest
    extraction result. Requires extraction to have run first. Advances
    Document.status to VALIDATED only if zero errors were found.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)
    doc_service.record_activity(document.id, current_user)

    validation_service = ValidationService(db)
    result = validation_service.validate(document)

    AuditService(db).log(
        AuditAction.VALIDATION_RUN,
        user_id=current_user.id,
        document_id=document.id,
        details={
            "is_valid": result.is_valid,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
        },
    )

    return ValidationResultResponse.model_validate(result)


@router.get("/documents/{document_id}/result", response_model=ValidationResultResponse)
def get_latest_validation(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationResultResponse:
    """Fetch the most recent validation report for a document."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    validation_service = ValidationService(db)
    result = validation_service.get_latest_result(document_id)
    if not result:
        raise NotFoundException("Validation result for document", document_id)
    return ValidationResultResponse.model_validate(result)


@router.get("/documents/{document_id}/results", response_model=list[ValidationResultResponse])
def list_validations(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ValidationResultResponse]:
    """List all validation runs for a document, newest first."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    validation_service = ValidationService(db)
    results = validation_service.list_results(document_id)
    return [ValidationResultResponse.model_validate(r) for r in results]
