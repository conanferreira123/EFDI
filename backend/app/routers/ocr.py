"""
OCR routes.

Access model mirrors documents: any authenticated user can run/view
OCR results for documents they're permitted to access (re-using
DocumentService's existing role-scoping rules via get_for_user).
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundException
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.ocr.factory import get_engine_status
from app.ocr.table_reconstruction import reconstruct_table
from app.schemas.ocr import (
    OCREngineStatus,
    OCREngineStatusResponse,
    OCRResultResponse,
    OCRRunRequest,
)
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.ocr_service import OCRService, get_default_ocr_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr", tags=["OCR"])


from app.ocr.normalization import normalize_table_data
from app.ocr.quality_scoring import calculate_quality_score
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.validation import validate_ocr_output


def _to_response(ocr_result) -> OCRResultResponse:
    response = OCRResultResponse.model_validate(ocr_result)
    response.is_stub_result = ocr_result.engine_name == "stub"
    if ocr_result.raw_blocks and isinstance(ocr_result.raw_blocks, list) and len(ocr_result.raw_blocks) > 0:
        page_0 = ocr_result.raw_blocks[0]
        blocks = page_0.get("blocks", [])
        pw = page_0.get("page_width", 1000.0)
        ph = page_0.get("page_height", 1400.0)
        if blocks:
            table_obj = reconstruct_table(blocks, page_width=pw, page_height=ph)
            table_dict = table_obj.to_dict()
            response.table_data = table_dict

            normalized_items = normalize_table_data(table_dict)
            response.normalized_data = {
                "line_items": [itm.to_dict() for itm in normalized_items]
            }

            validation_res = validate_ocr_output(normalized_items, raw_full_text=ocr_result.full_text)
            response.validation_results = validation_res.to_dict()

            quality_breakdown = calculate_quality_score(
                avg_confidence=ocr_result.average_confidence,
                full_text=ocr_result.full_text,
                table_data=table_dict,
                validation_result=validation_res,
            )
            response.quality_score = quality_breakdown.to_dict()
    return response


@router.get("/engines", response_model=OCREngineStatusResponse)
def get_ocr_engines() -> OCREngineStatusResponse:
    """
    Report availability of every supported OCR engine, so a caller can
    tell whether 'paddleocr'/'easyocr' are realistically usable in this
    deployment before attempting a real run.
    """
    status_map = get_engine_status()
    return OCREngineStatusResponse(
        engines={name: OCREngineStatus(**info) for name, info in status_map.items()},
        default_engine=settings.OCR_DEFAULT_ENGINE,
    )


@router.post(
    "/documents/{document_id}/run",
    response_model=OCRResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_ocr(
    document_id: int,
    payload: OCRRunRequest = OCRRunRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OCRResultResponse:
    """
    Run OCR on a document using the specified (or default) engine.
    Persists the result and advances the document's status to
    OCR_COMPLETED.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    ocr_service = OCRService(db)
    # Determine OCR engine: use payload if provided, otherwise fallback to stored default
    engine_name = payload.engine or get_default_ocr_engine(db)
    ocr_result = ocr_service.run_ocr(document, engine_name=engine_name)

    AuditService(db).log(
        AuditAction.OCR_RUN,
        user_id=current_user.id,
        document_id=document.id,
        details={"engine": ocr_result.engine_name, "page_count": ocr_result.page_count},
    )

    return _to_response(ocr_result)


@router.get("/documents/{document_id}/result", response_model=OCRResultResponse)
def get_latest_ocr_result(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OCRResultResponse:
    """Fetch the most recent OCR result for a document."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    ocr_service = OCRService(db)
    ocr_result = ocr_service.get_latest_result(document_id)
    if not ocr_result:
        raise NotFoundException("OCR result for document", document_id)
    return _to_response(ocr_result)


@router.get("/documents/{document_id}/results", response_model=list[OCRResultResponse])
def list_ocr_results(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OCRResultResponse]:
    """List all OCR runs ever performed on a document, newest first."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    ocr_service = OCRService(db)
    results = ocr_service.list_results(document_id)
    return [_to_response(r) for r in results]
