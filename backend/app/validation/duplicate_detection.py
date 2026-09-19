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


def _extract_scalar_val(fields: dict, key: str) -> str | None:
    if key in fields:
        fd = fields[key]
        if isinstance(fd, dict):
            val = fd.get("value")
        elif hasattr(fd, "value"):
            val = getattr(fd, "value")
        else:
            val = fd
        return str(val) if val is not None else None

    # Check canonical container if present
    if "canonical" in fields:
        c = fields["canonical"]
        if isinstance(c, dict) and "value" in c and isinstance(c["value"], dict):
            c = c["value"]
        if isinstance(c, dict) and "." in key:
            parts = key.split(".")
            curr = c
            for p in parts:
                if isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                elif hasattr(curr, p):
                    curr = getattr(curr, p)
                else:
                    curr = None
                    break
            if curr is not None:
                if isinstance(curr, dict):
                    val = curr.get("value")
                elif hasattr(curr, "value"):
                    val = getattr(curr, "value")
                else:
                    val = curr
                return str(val) if val is not None else None
    return None


def validate_duplicate_document(
    db: Session, document: Document, fields: dict | None = None
) -> list[ValidationIssue]:
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

    # Semantic duplicate detection based on extracted fields
    if fields and document.document_type in ("NPO", "POI", "MSI"):
        inv_num = None
        for k in ("invoice_information.invoice_number", "invoice_number"):
            v = _extract_scalar_val(fields, k)
            if v:
                inv_num = v.strip().lower()
                break

        seller = None
        for k in ("seller.name", "seller_name", "vendor_code"):
            v = _extract_scalar_val(fields, k)
            if v:
                seller = v.strip().lower()
                break

        # Only perform semantic duplicate match if both invoice_number AND seller are present (no wildcards)
        if inv_num and seller:
            from app.models.extraction_result import ExtractionResult
            from sqlalchemy import select
            from decimal import Decimal, InvalidOperation

            def _clean_num(val: str | None) -> str | None:
                if not val:
                    return None
                try:
                    return str(Decimal(val.replace(",", "").strip()))
                except (InvalidOperation, ValueError):
                    return val.replace(",", "").strip()

            date = None
            for k in ("invoice_information.invoice_date", "invoice_date"):
                v = _extract_scalar_val(fields, k)
                if v:
                    date = v.strip()
                    break

            grand_total = None
            for k in ("totals.grand_total", "grand_total_amount", "invoice_amount"):
                v = _extract_scalar_val(fields, k)
                if v:
                    grand_total = _clean_num(v)
                    break

            stmt = (
                select(ExtractionResult, Document)
                .join(Document, ExtractionResult.document_id == Document.id)
                .where(
                    Document.id != document.id,
                    Document.is_deleted.is_(False),
                    Document.document_type == document.document_type,
                )
                .order_by(ExtractionResult.id.desc())
                .limit(50)
            )
            rows = db.execute(stmt).all()
            for other_ext, other_doc in rows:
                other_fields = other_ext.fields or {}
                other_inv = None
                for k in ("invoice_information.invoice_number", "invoice_number"):
                    v = _extract_scalar_val(other_fields, k)
                    if v:
                        other_inv = v.strip().lower()
                        break

                other_seller = None
                for k in ("seller.name", "seller_name", "vendor_code"):
                    v = _extract_scalar_val(other_fields, k)
                    if v:
                        other_seller = v.strip().lower()
                        break

                # Seller and invoice number must both match
                if other_inv != inv_num or other_seller != seller:
                    continue

                other_date = None
                for k in ("invoice_information.invoice_date", "invoice_date"):
                    v = _extract_scalar_val(other_fields, k)
                    if v:
                        other_date = v.strip()
                        break

                other_grand_total = None
                for k in ("totals.grand_total", "grand_total_amount", "invoice_amount"):
                    v = _extract_scalar_val(other_fields, k)
                    if v:
                        other_grand_total = _clean_num(v)
                        break

                both_have_date = bool(date and other_date)
                both_have_total = bool(grand_total and other_grand_total)

                # If dates are both explicitly provided and differ -> not the same duplicate (different date)
                if both_have_date and date != other_date:
                    continue

                # If totals are both explicitly provided and differ -> not the same duplicate (different total)
                if both_have_total and grand_total != other_grand_total:
                    continue

                field_key = (
                    "invoice_information.invoice_number"
                    if "invoice_information.invoice_number" in fields
                    else "invoice_number"
                )

                # Tier A: Strong semantic duplicate (all four components match)
                if both_have_date and both_have_total and date == other_date and grand_total == other_grand_total:
                    return [
                        ValidationIssue(
                            rule_type=ValidationRuleType.DUPLICATE_DOCUMENT,
                            severity=ValidationSeverity.WARNING,
                            field_key=field_key,
                            message=(
                                f"Strong duplicate invoice detected: document #{other_doc.id} "
                                f"('{other_doc.original_filename}') shares matching seller '{seller}', "
                                f"invoice number '{inv_num}', date '{date}', and grand total '{grand_total}'."
                            ),
                        )
                    ]

                # Tier B: Potential duplicate (partial match: seller + invoice_number match, but date or total unavailable)
                missing_evidence = []
                if not both_have_date:
                    missing_evidence.append("invoice date")
                if not both_have_total:
                    missing_evidence.append("grand total")

                return [
                    ValidationIssue(
                        rule_type=ValidationRuleType.DUPLICATE_DOCUMENT,
                        severity=ValidationSeverity.WARNING,
                        field_key=field_key,
                        message=(
                            f"Potential duplicate invoice (partial match): document #{other_doc.id} "
                            f"('{other_doc.original_filename}') matches seller '{seller}' and invoice number '{inv_num}', "
                            f"but {', '.join(missing_evidence)} is unavailable for complete duplicate verification."
                        ),
                    )
                ]

    return []
