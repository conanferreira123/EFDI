"""
Duplicate document detection.

Uses Document.file_hash (SHA-256, computed at upload time in Phase 3)
to detect when the document currently being validated is byte-for-byte
identical to another, previously uploaded document. This catches exact
re-uploads (e.g. a user accidentally submitting the same scanned PDF
twice) -- it does not attempt fuzzy/semantic duplicate detection (e.g.
"this invoice has the same invoice number as another one"), which
belongs in business-rule validation instead, since that requires
comparing extracted field values, not file bytes.
"""
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.validation.base import ValidationIssue, ValidationRuleType, ValidationSeverity


def validate_duplicate_document(db: Session, document: Document) -> list[ValidationIssue]:
    repo = DocumentRepository(db)
    matches = repo.get_all_by_hash(document.file_hash)
    other_matches = [m for m in matches if m.id != document.id]

    if other_matches:
        earliest = other_matches[0]  # get_all_by_hash returns oldest-first
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.DUPLICATE_DOCUMENT,
                severity=ValidationSeverity.ERROR,
                field_key=None,
                message=(
                    f"This document is byte-for-byte identical to document "
                    f"#{earliest.id} ('{earliest.original_filename}', uploaded "
                    f"{earliest.created_at.date().isoformat()}). It may be a "
                    "duplicate submission."
                ),
            )
        ]

    return []
