"""
Workflow routes.

Access model: document-access scoping (DocumentService.get_for_user)
applies to all actions and to viewing history. Role restrictions for
approve/reject are enforced inside WorkflowService itself (not via a
router-level dependency) since the exact allowed roles depend on the
action being performed, not the route as a whole.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.document_enums import AuditAction
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.schemas.workflow import WorkflowActionRequest, WorkflowHistoryResponse
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.workflow_service import WorkflowService
from app.workflow.state_machine import WorkflowAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["Workflow"])


@router.post("/documents/{document_id}/request-approval", response_model=DocumentResponse)
def request_approval(
    document_id: int,
    payload: WorkflowActionRequest = WorkflowActionRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """
    Move a VALIDATED document into PENDING_APPROVAL. Any user with
    access to the document may request approval (mirrors who can
    upload/process it in the first place).
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    workflow_service = WorkflowService(db)
    updated = workflow_service.perform_action(
        document, WorkflowAction.REQUEST_APPROVAL, current_user, payload.comment
    )

    AuditService(db).log(
        AuditAction.APPROVAL_REQUESTED,
        user_id=current_user.id,
        document_id=document.id,
        details={"comment": payload.comment},
    )

    return DocumentResponse.model_validate(updated)


@router.post("/documents/{document_id}/approve", response_model=DocumentResponse)
def approve_document(
    document_id: int,
    payload: WorkflowActionRequest = WorkflowActionRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Approve a PENDING_APPROVAL document. FINANCE_MANAGER, AUDITOR, or ADMIN only."""
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    workflow_service = WorkflowService(db)
    updated = workflow_service.perform_action(
        document, WorkflowAction.APPROVE, current_user, payload.comment
    )

    AuditService(db).log(
        AuditAction.DOCUMENT_APPROVED,
        user_id=current_user.id,
        document_id=document.id,
        details={"comment": payload.comment},
    )

    return DocumentResponse.model_validate(updated)


@router.post("/documents/{document_id}/reject", response_model=DocumentResponse)
def reject_document(
    document_id: int,
    payload: WorkflowActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """
    Reject a PENDING_APPROVAL document. FINANCE_MANAGER, AUDITOR, or
    ADMIN only. A comment is required, explaining what needs to be
    fixed. The document returns to a state where it must pass
    validation again (reach VALIDATED) before approval can be
    re-requested.
    """
    doc_service = DocumentService(db)
    document = doc_service.get_for_user(document_id, current_user)

    workflow_service = WorkflowService(db)
    updated = workflow_service.perform_action(
        document, WorkflowAction.REJECT, current_user, payload.comment
    )

    AuditService(db).log(
        AuditAction.DOCUMENT_REJECTED,
        user_id=current_user.id,
        document_id=document.id,
        details={"comment": payload.comment},
    )

    return DocumentResponse.model_validate(updated)


@router.get("/documents/{document_id}/history", response_model=list[WorkflowHistoryResponse])
def get_workflow_history(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowHistoryResponse]:
    """Full workflow history for a document, oldest first."""
    doc_service = DocumentService(db)
    doc_service.get_for_user(document_id, current_user)  # enforces access scoping

    workflow_service = WorkflowService(db)
    history = workflow_service.get_history(document_id)
    return [WorkflowHistoryResponse.model_validate(h) for h in history]
