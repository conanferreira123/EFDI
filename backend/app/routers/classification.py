"""
Classification routes.

Access model mirrors documents/OCR: re-uses DocumentService's existing
role-scoping rules via get_for_user.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundException
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.schemas.classification import (
    ClassificationCorrectionRequest,
    ClassificationResultResponse,
    ClassifyRequest,
)
from app.services.audit_service import AuditService
from app.services.classification_service import ClassificationService
from app.services.document_service import DocumentService
from app.services.ocr_service import OCRService
from app.services.training_data_service import TrainingDataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classification", tags=["Classification"])


@router.post(
    "/documents/{document_id}/classify",
    response_model=ClassificationResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def classify_document(
    document_id: int,
    payload: ClassifyRequest = ClassifyRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassificationResultResponse:
    """
    Classify a document's type based on its most recent OCR text.
    Requires OCR to have been run first. Updates Document.document_type
    but does not change Document.status.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)
    doc_service.record_activity(document.id, current_user)

    classification_service = ClassificationService(db)
    result = classification_service.classify(document, engine_name=payload.engine)

    AuditService(db).log(
        AuditAction.CLASSIFICATION_RUN,
        user_id=current_user.id,
        document_id=document.id,
        details={"predicted_type": result.predicted_type, "confidence": result.confidence},
    )

    return ClassificationResultResponse.model_validate(result)


@router.get("/documents/{document_id}/result", response_model=ClassificationResultResponse)
def get_latest_classification(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassificationResultResponse:
    """Fetch the most recent classification result for a document."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    classification_service = ClassificationService(db)
    result = classification_service.get_latest_result(document_id)
    if not result:
        raise NotFoundException("Classification result for document", document_id)
    return ClassificationResultResponse.model_validate(result)


@router.get("/documents/{document_id}/results", response_model=list[ClassificationResultResponse])
def list_classifications(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ClassificationResultResponse]:
    """List all classification runs for a document, newest first."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    classification_service = ClassificationService(db)
    results = classification_service.list_results(document_id)
    return [ClassificationResultResponse.model_validate(r) for r in results]


@router.patch("/documents/{document_id}/correct", response_model=ClassificationResultResponse)
def correct_classification(
    document_id: int,
    payload: ClassificationCorrectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassificationResultResponse:
    """
    Manually correct a wrong classification verdict. Updates both the
    stored ClassificationResult and Document.document_type (the field
    that determines which schema a subsequent extraction run uses --
    see ClassificationService.correct_type for why both must change
    together).

    Also records this correction as a TrainingExample, the same way
    update_extracted_field does for extraction corrections -- the
    original (wrong) predicted_type, the human-supplied corrected_type,
    and the source OCR text the original prediction was made from.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    classification_service = ClassificationService(db)

    # Captured BEFORE correct_type mutates it.
    pre_correction_result = classification_service.get_latest_result(document_id)
    predicted_value = pre_correction_result.predicted_type if pre_correction_result else None

    result = classification_service.correct_type(document, payload.corrected_type.value)

    AuditService(db).log(
        AuditAction.CLASSIFICATION_CORRECTED,
        user_id=current_user.id,
        document_id=document_id,
        details={"corrected_type": payload.corrected_type.value, "previous_type": predicted_value},
    )

    ocr_result = OCRService(db).get_latest_result(document_id)
    TrainingDataService(db).record_classification_correction(
        document_id=document_id,
        corrected_by=current_user.id,
        document_type=payload.corrected_type.value,
        source_text=ocr_result.full_text if ocr_result else "",
        predicted_value=predicted_value,
        corrected_value=payload.corrected_type.value,
        extra_context={"scores_by_type": pre_correction_result.scores_by_type} if pre_correction_result else None,
    )

    return ClassificationResultResponse.model_validate(result)
