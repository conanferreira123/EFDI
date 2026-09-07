"""
Audit routes.

Access model: deliberately stricter than every other router in the
app. Unlike documents/OCR/classification/extraction/validation/
workflow (all of which use DocumentService.get_for_user's ownership
scoping), audit logs are restricted to AUDITOR and ADMIN only --
including the per-document endpoint. This is different from
WorkflowHistory (visible to anyone with document access) because
AuditLog entries can include other users' identities and details
that have nothing to do with the requesting user's own documents
(e.g. another user's LOGIN_FAILED attempt, or a different analyst's
upload), so document-ownership is not the right access boundary here.
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_auditor_or_admin
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.schemas.audit import AuditLogFilterParams, AuditLogListResponse, AuditLogResponse
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audit", tags=["Audit"], dependencies=[Depends(require_auditor_or_admin)]
)


@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    action: AuditAction | None = None,
    user_id: int | None = None,
    document_id: int | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """
    System-wide audit log, newest first, with optional filters.
    AUDITOR or ADMIN only.
    """
    filters = AuditLogFilterParams(
        action=action, user_id=user_id, document_id=document_id, skip=skip, limit=limit
    )
    results, total = AuditService(db).search(filters)
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(r) for r in results],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/documents/{document_id}/logs", response_model=list[AuditLogResponse])
def get_document_audit_logs(document_id: int, db: Session = Depends(get_db)) -> list[AuditLogResponse]:
    """All audit log entries for a single document, newest first. AUDITOR or ADMIN only."""
    results = AuditService(db).list_for_document(document_id)
    return [AuditLogResponse.model_validate(r) for r in results]
