"""
Field-level validators: required fields, date format, amount format,
and tax-ID-like format checks.

Each validator takes the extracted fields dict (field_key ->
{"value": ..., "confidence": ..., ...}, the shape persisted in
ExtractionResult.fields) plus the document_type, and returns a list of
ValidationIssue. Validators never raise -- a missing or malformed field
is reported as an issue, not an exception, since validation's entire
purpose is to surface exactly these problems for review.
"""
import re
from datetime import datetime

from app.extraction.field_schemas import get_full_field_schema
from app.validation.base import ValidationIssue, ValidationRuleType, ValidationSeverity
from app.validation.mandatory_fields import get_mandatory_fields


def validate_required_fields(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Every mandatory field for this document type must have a non-null value."""
    issues = []
    for field_key in sorted(get_mandatory_fields(document_type)):
        field_data = fields.get(field_key)
        value = field_data.get("value") if field_data else None
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.REQUIRED_FIELD,
                    severity=ValidationSeverity.ERROR,
                    field_key=field_key,
                    message=f"Required field '{field_key}' is missing.",
                )
            )
    return issues


# Fields whose field_type is "date" (per field_schemas.FieldDef) that
# actually carry a value should already be ISO-formatted by the
# extraction layer's normalize_date(); if they aren't, the original
# OCR text couldn't be parsed as a date and a human needs to look at it.
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date_fields(fields: dict, document_type: str) -> list[ValidationIssue]:
    issues = []
    date_field_keys = {
        f.key for f in get_full_field_schema(document_type) if f.field_type == "date"
    }

    for field_key in sorted(date_field_keys):
        field_data = fields.get(field_key)
        if not field_data or field_data.get("value") is None:
            continue  # absence is a REQUIRED_FIELD concern, not a format concern

        value = field_data["value"]
        if not _ISO_DATE_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.DATE_FORMAT,
                    severity=ValidationSeverity.ERROR,
                    field_key=field_key,
                    message=f"Field '{field_key}' value '{value}' is not a valid date.",
                )
            )
            continue

        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.DATE_FORMAT,
                    severity=ValidationSeverity.ERROR,
                    field_key=field_key,
                    message=f"Field '{field_key}' value '{value}' is not a real calendar date.",
                )
            )

    return issues


_AMOUNT_PATTERN = re.compile(r"^\d+(\.\d{1,2})?$")


def validate_amount_fields(fields: dict, document_type: str) -> list[ValidationIssue]:
    """
    Amount fields should be plain non-negative numeric strings with at
    most 2 decimal places (the shape produced by extraction's
    normalize_amount()). Negative amounts and non-numeric leftovers are
    flagged.
    """
    issues = []
    amount_field_keys = {
        f.key for f in get_full_field_schema(document_type) if f.field_type == "amount"
    }
    # ocr_confidence_score is typed "amount" in the schema but is a
    # system-computed metric, not a document-derived monetary value --
    # exclude it from amount-format validation.
    amount_field_keys.discard("ocr_confidence_score")

    for field_key in sorted(amount_field_keys):
        field_data = fields.get(field_key)
        if not field_data or field_data.get("value") is None:
            continue

        value = field_data["value"]
        if not _AMOUNT_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.AMOUNT_FORMAT,
                    severity=ValidationSeverity.ERROR,
                    field_key=field_key,
                    message=f"Field '{field_key}' value '{value}' is not a valid non-negative amount.",
                )
            )

    return issues


# Heuristic check for tax-ID-like identifiers. Modeled on India's GST
# registration number format (15 alphanumeric characters: 2-digit state
# code + 10-character PAN + entity/check digits) since that was the
# original spec's explicit reference point, but applied loosely (as a
# WARNING, not an ERROR) to identifying code fields across types --
# the new field schema has no single dedicated "GST Number" field, so
# this runs against vendor_code/customer_code where a tax-ID-shaped
# value would plausibly appear.
_GST_LIKE_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z A-Z]\d$", re.IGNORECASE)

_TAX_ID_CANDIDATE_FIELDS = {"vendor_code", "customer_code"}


def validate_tax_id_format(fields: dict, document_type: str) -> list[ValidationIssue]:
    """
    If a vendor_code/customer_code value happens to look like it was
    intended as a GST-style tax registration number (starts with 2
    digits, is around 15 characters), check it actually matches the
    expected pattern. This is intentionally a WARNING, not an ERROR:
    these fields are normally just internal vendor/customer codes, not
    tax IDs, so a mismatch here is a soft signal worth a reviewer's
    attention rather than a hard validation failure.
    """
    issues = []
    for field_key in sorted(_TAX_ID_CANDIDATE_FIELDS):
        field_data = fields.get(field_key)
        if not field_data or field_data.get("value") is None:
            continue

        value = field_data["value"].strip().upper()
        looks_like_tax_id_attempt = len(value) >= 13 and value[:2].isdigit()
        if not looks_like_tax_id_attempt:
            continue  # ordinary short internal code -- not a tax-ID candidate at all

        if not _GST_LIKE_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.TAX_ID_FORMAT,
                    severity=ValidationSeverity.WARNING,
                    field_key=field_key,
                    message=(
                        f"Field '{field_key}' value '{value}' resembles a tax "
                        "registration number but does not match the expected format."
                    ),
                )
            )

    return issues
