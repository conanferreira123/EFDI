"""
Audit service.

Centralizes writing AuditLog entries so every router calls one
consistent `log()` method rather than constructing AuditLog rows
ad hoc. Deliberately called from routers, not from the
document/OCR/classification/extraction/validation/workflow services
themselves: those services don't currently take `current_user` unless
their business logic actually needs it (WorkflowService is the one
exception, since it needs the user for role-checking, not just
logging). Auditing is a cross-cutting API-boundary concern, so it
lives at the boundary -- this also means adding it doesn't change any
existing service's signature or risk the 160 tests already passing
through Phase 8.

`log()` never raises on its own account beyond what the repository
already does -- if writing an audit entry ever became "best effort"
(swallow and continue), every test depending on log presence would be
unable to distinguish "logging is broken" from "logging is skipped",
so failures are left to surface normally rather than being hidden.
"""
from sqlalchemy.orm import Session

from app.models.document_enums import AuditAction
from app.repositories.audit_log_repository import AuditLogRepository


class AuditService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AuditLogRepository(db)

    def log(
        self,
        action: AuditAction,
        *,
        user_id: int | None,
        document_id: int | None = None,
        details: dict | None = None,
    ):
        return self.repo.create(
            action=action.value,
            user_id=user_id,
            document_id=document_id,
            details=details,
        )

    def search(self, filters) -> tuple[list, int]:
        return self.repo.search(
            action=filters.action.value if filters.action else None,
            user_id=filters.user_id,
            document_id=filters.document_id,
            date_from=filters.date_from,
            date_to=filters.date_to,
            skip=filters.skip,
            limit=filters.limit,
        )

    def list_for_document(self, document_id: int) -> list:
        return self.repo.list_for_document(document_id)
