"""
Validation engine: orchestrates all validators (required fields, date
format, amount format, tax-ID format, duplicate detection, business
rules) into a single ValidationReportData for a document.

Unlike OCR/classification/extraction, validation has no alternate
"engine" to swap in via a factory -- it's a fixed pipeline of
deterministic rule checks, not a pluggable strategy. (A future
ML-based anomaly-detection layer could be added as an additional
checker appended to ALL_FIELD_VALIDATORS without restructuring this
module.)
"""
from sqlalchemy.orm import Session

from app.models.document import Document
from app.validation.base import ValidationReportData
from app.validation.business_rules import validate_business_rules
from app.validation.duplicate_detection import validate_duplicate_document
from app.validation.field_validators import (
    validate_amount_fields,
    validate_date_fields,
    validate_required_fields,
    validate_tax_id_format,
)

ENGINE_NAME = "rule_based_validation"

# Field-level validators: take (fields_dict, document_type) -> issues.
ALL_FIELD_VALIDATORS = [
    validate_required_fields,
    validate_date_fields,
    validate_amount_fields,
    validate_tax_id_format,
]


def run_validation(db: Session, document: Document, document_type: str, fields: dict) -> ValidationReportData:
    """
    Run every validator against a document's extracted fields and
    return the aggregated report.

    `document_type` is passed explicitly by the caller (sourced from
    the ExtractionResult being validated, not re-read from
    `document.document_type`) because the two can diverge: extraction
    snapshots the type it actually extracted against, while
    Document.document_type reflects whichever classification happened
    to run most recently. Validating against the wrong type's mandatory
    field list would silently produce a wrong report.

    `fields` is the raw fields dict from the latest ExtractionResult
    (field_key -> {"value":..., "confidence":..., ...}), passed in
    rather than re-fetched here so the caller (ValidationService)
    controls exactly which extraction result is being validated.
    """
    report = ValidationReportData(document_type=document_type, engine_name=ENGINE_NAME)

    for validator_fn in ALL_FIELD_VALIDATORS:
        report.issues.extend(validator_fn(fields, document_type))

    report.issues.extend(validate_business_rules(fields, document_type))
    report.issues.extend(validate_duplicate_document(db, document))

    return report
