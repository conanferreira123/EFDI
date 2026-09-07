"""
Extraction routes.

Access model mirrors documents/OCR/classification: re-uses
DocumentService's existing role-scoping rules via get_for_user.
"""
import csv
import io
import json
import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.schemas.extraction import ExtractionResultResponse, ExtractRequest, FieldUpdateRequest
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService
from app.services.training_data_service import TrainingDataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extraction", tags=["Extraction"])


@router.post(
    "/documents/{document_id}/extract",
    response_model=ExtractionResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_document_fields(
    document_id: int,
    payload: ExtractRequest = ExtractRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtractionResultResponse:
    """
    Extract structured fields from a document's OCR text, using the
    field schema for its most recently classified document type.
    Requires OCR and classification to have run first. Advances
    Document.status to EXTRACTED.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    extraction_service = ExtractionService(db)
    result = extraction_service.extract(document, engine_name=payload.engine or payload.engine_name)

    AuditService(db).log(
        AuditAction.EXTRACTION_RUN,
        user_id=current_user.id,
        document_id=document.id,
        details={
            "document_type": result.document_type,
            "fields_found_count": result.fields_found_count,
            "fields_total_count": result.fields_total_count,
        },
    )

    return ExtractionResultResponse.model_validate(result)


@router.get("/documents/{document_id}/result", response_model=ExtractionResultResponse)
def get_latest_extraction(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtractionResultResponse:
    """Fetch the most recent extraction result for a document."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    extraction_service = ExtractionService(db)
    result = extraction_service.get_latest_result(document_id)
    if not result:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Extraction result for document", document_id)
    return ExtractionResultResponse.model_validate(result)


@router.get("/documents/{document_id}/results", response_model=list[ExtractionResultResponse])
def list_extractions(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExtractionResultResponse]:
    """List all extraction runs for a document, newest first."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    extraction_service = ExtractionService(db)
    results = extraction_service.list_results(document_id)
    return [ExtractionResultResponse.model_validate(r) for r in results]


@router.patch("/documents/{document_id}/fields/{field_key}", response_model=ExtractionResultResponse)
def update_extracted_field(
    document_id: int,
    field_key: str,
    payload: FieldUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtractionResultResponse:
    """
    Manually correct or fill in a single field on the latest extraction
    result -- the basis for the review/correction UI's "fill in the
    nulls" workflow. The field is marked as manually entered with full
    confidence.

    Also records this correction as a TrainingExample (see
    app/services/training_data_service.py) -- the predicted value
    before this edit, the human-supplied corrected value, and the
    source OCR text the original prediction was made from. This is
    pure side-effect logging: if it fails for any reason, the
    correction itself still succeeds (see TrainingDataService's
    broad try/except -- a lost training example is a future-model-
    quality problem, not a reason to fail a user-facing request).
    """
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    extraction_service = ExtractionService(db)

    # Captured BEFORE update_field mutates it -- this is the
    # "predicted value" half of the training example.
    pre_update_result = extraction_service.get_latest_result(document_id)
    predicted_value = None
    if pre_update_result and field_key in pre_update_result.fields:
        predicted_value = pre_update_result.fields[field_key].get("value")

    result = extraction_service.update_field(document_id, field_key, payload.value)

    AuditService(db).log(
        AuditAction.EXTRACTION_FIELD_CORRECTED,
        user_id=current_user.id,
        document_id=document_id,
        details={"field_key": field_key, "new_value": payload.value},
    )

    ocr_result = OCRService(db).get_latest_result(document_id)
    TrainingDataService(db).record_extraction_correction(
        document_id=document_id,
        corrected_by=current_user.id,
        document_type=result.document_type,
        source_text=ocr_result.full_text if ocr_result else "",
        field_key=field_key,
        predicted_value=predicted_value,
        corrected_value=payload.value,
    )

    return ExtractionResultResponse.model_validate(result)
@router.get("/documents/{document_id}/export")
def export_extraction_fields(
    document_id: int,
    format: str = Query(default="json", pattern="^(json|csv|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """
    Export a document's latest extracted fields as a downloadable
    file -- json, csv, or excel (default json). All three formats are
    built from the same underlying row data
    (ExtractionService.get_export_rows), so adding a fourth format
    later means adding one more serializer branch here, not
    re-deriving the export data.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    extraction_service = ExtractionService(db)
    rows = extraction_service.get_export_rows(document_id)

    base_filename = document.original_filename.rsplit(".", 1)[0]

    if format == "json":
        content = json.dumps(
            {
                "document_id": document_id,
                "filename": document.original_filename,
                "document_type": document.document_type,
                "fields": rows,
            },
            indent=2,
            default=str,
        )
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{base_filename}_export.json"'},
        )

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Field", "Value", "Confidence", "Found"])
        for row in rows:
            writer.writerow([row["label"], row["value"] or "", row["confidence"], row["is_found"]])
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{base_filename}_export.csv"'},
        )

    # format == "excel"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Extracted Fields"
    sheet.append(["Field", "Value", "Confidence", "Found"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([row["label"], row["value"] or "", row["confidence"], "Yes" if row["is_found"] else "No"])
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None)
        sheet.column_dimensions[column_cells[0].column_letter].width = max(12, min(max_length + 2, 50))

    buffer = io.BytesIO()
    workbook.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{base_filename}_export.xlsx"'},
    )
