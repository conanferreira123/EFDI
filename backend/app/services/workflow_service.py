"""
Workflow service: enforces the approval state machine (app/workflow/
state_machine.py) and records every transition in WorkflowHistory.
"""
import logging

from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationException, ValidationFailedException, WorkflowException
from app.models.document import Document
from app.validation.base import ValidationSeverity
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.ocr_result_repository import OCRResultRepository
from app.repositories.validation_result_repository import ValidationResultRepository
from app.repositories.workflow_history_repository import WorkflowHistoryRepository
from app.services.training_data_service import TrainingDataService
from app.workflow.state_machine import (
    WorkflowAction,
    get_required_status,
    get_resulting_status,
    is_comment_required,
    is_role_allowed,
)

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.history_repo = WorkflowHistoryRepository(db)
        self.validation_repo = ValidationResultRepository(db)
        self.ocr_repo = OCRResultRepository(db)
        self.training_data_service = TrainingDataService(db)

    def perform_action(
        self, document: Document, action: WorkflowAction, current_user: User, comment: str | None
    ) -> Document:
        if not is_role_allowed(action, current_user.role):
            raise AuthorizationException(
                f"Your role ({current_user.role}) is not permitted to perform {action.value}."
            )

        required_status = get_required_status(action)
        if document.status != required_status:
            raise WorkflowException(
                f"Cannot {action.value.lower().replace('_', ' ')}: document is in status "
                f"'{document.status}', but this action requires status '{required_status}'.",
                details={"current_status": document.status, "required_status": required_status},
            )

        if is_comment_required(action) and not (comment and comment.strip()):
            raise ValidationFailedException(
                f"A comment is required when performing {action.value}."
            )

        resulting_status = get_resulting_status(action)
        from_status = document.status

        self.document_repo.update_status(document, resulting_status)

        self.history_repo.create(
            document_id=document.id,
            action=action.value,
            from_status=from_status,
            to_status=resulting_status,
            performed_by=current_user.id,
            comment=comment,
        )

        # Capture training signal for APPROVE (warnings overridden) and
        # REJECT (human-stated reason) -- both fire-and-forget, same
        # contract as every other TrainingDataService call: a failure
        # here must never break the workflow action that already
        # succeeded above.
        if action == WorkflowAction.APPROVE:
            self._capture_warning_overrides(document, current_user)
        elif action == WorkflowAction.REJECT:
            self._capture_rejection_reason(document, current_user, from_status, comment)

        logger.info(
            "Workflow action performed: document_id=%s action=%s %s->%s by_user=%s",
            document.id, action.value, from_status, resulting_status, current_user.username,
        )

        return document

    def get_history(self, document_id: int):
        return self.history_repo.list_for_document(document_id)

    def _capture_warning_overrides(self, document: Document, current_user: User) -> None:
        """
        A document can reach VALIDATED (and thus be approvable) with
        WARNING-severity issues still present -- warnings never block
        the status transition, only ERRORs do (see ValidationService).
        Approving such a document is an implicit human judgment that
        each warning was a false positive or otherwise acceptable;
        that's worth capturing per-warning, not just as one blob.
        """
        validation_result = self.validation_repo.get_latest_for_document(document.id)
        if not validation_result or not validation_result.issues:
            return

        ocr_result = self.ocr_repo.get_latest_for_document(document.id)
        source_text = ocr_result.full_text if ocr_result else ""

        for issue in validation_result.issues:
            if issue.get("severity") != ValidationSeverity.WARNING.value:
                continue
            self.training_data_service.record_validation_override(
                document_id=document.id,
                approved_by=current_user.id,
                document_type=validation_result.document_type,
                source_text=source_text,
                field_key=issue.get("field_key"),
                rule_type=issue.get("rule_type", "UNKNOWN"),
                message=issue.get("message", ""),
            )

    def _capture_rejection_reason(
        self, document: Document, current_user: User, from_status: str, comment: str | None
    ) -> None:
        """See TrainingDataService.record_rejection_reason."""
        if not comment or not comment.strip():
            return  # REJECT technically allows an empty comment in some transitions; nothing to learn from
        ocr_result = self.ocr_repo.get_latest_for_document(document.id)
        source_text = ocr_result.full_text if ocr_result else ""
        self.training_data_service.record_rejection_reason(
            document_id=document.id,
            rejected_by=current_user.id,
            document_type=document.document_type,
            source_text=source_text,
            from_status=from_status,
            comment=comment,
        )
