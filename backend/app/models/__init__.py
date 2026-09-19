"""
Model package initializer.

Importing `app.models` (directly or transitively) guarantees every ORM
model in this package is registered with SQLAlchemy's mapper registry.

This matters because relationship() targets declared as strings (e.g.
`relationship("Document", ...)` on User) are resolved lazily, the first
time mappers are configured -- which happens on the first query, not at
import time. If some entry point (a script, a test, a Celery task)
imports only `app.models.user` and never touches `app.models.document`,
that first query will fail with a confusing
"name 'Document' is not defined" error, even though the exact same code
works fine inside the main FastAPI app (which happens to import every
router, and therefore every model, during startup).

Rule going forward: every new model module added in later phases
(AuditLog in Phase 9, etc.) must be imported here too.
"""
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.chat import ChatMessage, ChatSession  # noqa: F401
from app.models.classification_result import ClassificationResult  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.document_chunk import DocumentChunk  # noqa: F401
from app.models.document_enums import AuditAction, DocumentStatus, DocumentType  # noqa: F401
from app.models.extraction_result import ExtractionResult  # noqa: F401
from app.models.ocr_result import OCRResult  # noqa: F401
from app.models.roles import UserRole  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
from app.models.training_example import TrainingExample  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.validation_result import ValidationResult  # noqa: F401
from app.models.vendor_knowledge import VendorKnowledge  # noqa: F401
from app.models.workflow_history import WorkflowHistory  # noqa: F401

__all__ = [
    "User", "Document", "OCRResult", "ClassificationResult", "ExtractionResult",
    "ValidationResult", "WorkflowHistory", "AuditLog", "TrainingExample", "UserRole", "DocumentType",
    "DocumentStatus", "AuditAction", "DocumentChunk", "VendorKnowledge", "SystemSetting",
    "ChatSession", "ChatMessage",
]
