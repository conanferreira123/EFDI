"""
Business rule validators: cross-field consistency checks specific to
each document type's accounting logic. Unlike the generic field-level
validators (required/date/amount format), these encode domain
knowledge about how fields on a given document type should relate to
each other.

Each check is deliberately tolerant of missing inputs (if a field
needed for the check wasn't extracted, the check is skipped rather than
raising or reporting a false failure) and uses a small numeric
tolerance for amount comparisons, since OCR/extraction rounding can
introduce trivial cent-level discrepancies that shouldn't be treated as
real business-rule violations.
"""
from decimal import Decimal, InvalidOperation

from app.validation.base import ValidationIssue, ValidationRuleType, ValidationSeverity

_AMOUNT_TOLERANCE = Decimal("0.01")


def _get_decimal(fields: dict, key: str) -> Decimal | None:
    field_data = fields.get(key)
    if not field_data or field_data.get("value") is None:
        return None
    try:
        return Decimal(str(field_data["value"]))
    except (InvalidOperation, ValueError):
        return None


def _check_sum_consistency(
    fields: dict, *, total_key: str, part_keys: list[str], rule_description: str
) -> list[ValidationIssue]:
    """
    Generic helper: verifies total_key == sum(part_keys) within
    tolerance, e.g. invoice_amount == tax_amount + net_amount. Skipped
    entirely if any of the involved fields are missing.
    """
    total = _get_decimal(fields, total_key)
    parts = [_get_decimal(fields, k) for k in part_keys]

    if total is None or any(p is None for p in parts):
        return []

    expected = sum(parts, Decimal("0"))
    if abs(total - expected) > _AMOUNT_TOLERANCE:
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.WARNING,
                field_key=total_key,
                message=(
                    f"{rule_description}: expected {total_key}={expected}, "
                    f"but found {total_key}={total}."
                ),
            )
        ]
    return []


def validate_poi_npo_amounts(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Invoice Amount should equal Tax Amount + Net Amount (POI and NPO both have these three fields)."""
    if document_type not in ("POI", "NPO"):
        return []
    return _check_sum_consistency(
        fields,
        total_key="invoice_amount",
        part_keys=["tax_amount", "net_amount"],
        rule_description="Invoice Amount should equal Tax Amount + Net Amount",
    )


def validate_msi_amounts(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Sales Invoice Amount should equal Tax Amount + Net Amount."""
    if document_type != "MSI":
        return []
    return _check_sum_consistency(
        fields,
        total_key="invoice_amount",
        part_keys=["tax_amount", "net_amount"],
        rule_description="Invoice Amount should equal Tax Amount + Net Amount",
    )


def validate_jer_debit_equals_credit(fields: dict, document_type: str) -> list[ValidationIssue]:
    """
    Fundamental double-entry bookkeeping rule: a journal entry's debit
    and credit amounts must balance. Reported as an ERROR (not a
    WARNING like the other business rules) since an unbalanced journal
    entry is not just unusual -- it is invalid accounting.
    """
    if document_type != "JER":
        return []

    debit = _get_decimal(fields, "debit_amount")
    credit = _get_decimal(fields, "credit_amount")
    if debit is None or credit is None:
        return []

    if abs(debit - credit) > _AMOUNT_TOLERANCE:
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.ERROR,
                field_key="debit_amount",
                message=(
                    f"Journal entry does not balance: Debit Amount ({debit}) "
                    f"must equal Credit Amount ({credit})."
                ),
            )
        ]
    return []


def validate_ima_travel_dates(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Travel End Date must not be before Travel Start Date."""
    if document_type != "IMA":
        return []

    start_data = fields.get("travel_start_date")
    end_data = fields.get("travel_end_date")
    if not start_data or not end_data:
        return []

    start_value = start_data.get("value")
    end_value = end_data.get("value")
    if not start_value or not end_value:
        return []

    if end_value < start_value:  # ISO date strings compare correctly lexicographically
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.ERROR,
                field_key="travel_end_date",
                message=(
                    f"Travel End Date ({end_value}) is before Travel Start Date "
                    f"({start_value})."
                ),
            )
        ]
    return []


def validate_ima_approved_amount(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Approved Amount should not exceed the originally Claimed Amount."""
    if document_type != "IMA":
        return []

    claim = _get_decimal(fields, "claim_amount")
    approved = _get_decimal(fields, "approved_amount")
    if claim is None or approved is None:
        return []

    if approved > claim + _AMOUNT_TOLERANCE:
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.WARNING,
                field_key="approved_amount",
                message=(
                    f"Approved Amount ({approved}) exceeds the Claim Amount "
                    f"({claim}); this is unusual and worth a second look."
                ),
            )
        ]
    return []


def validate_lca_dates(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Letter of Credit Expiry Date must be after its Issue Date."""
    if document_type != "LCA":
        return []

    issue_data = fields.get("issue_date")
    expiry_data = fields.get("expiry_date")
    if not issue_data or not expiry_data:
        return []

    issue_value = issue_data.get("value")
    expiry_value = expiry_data.get("value")
    if not issue_value or not expiry_value:
        return []

    if expiry_value <= issue_value:
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.ERROR,
                field_key="expiry_date",
                message=(
                    f"Expiry Date ({expiry_value}) must be after Issue Date "
                    f"({issue_value})."
                ),
            )
        ]
    return []


def validate_dpr_advance_percentage(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Advance Percentage on a down payment request should be a sane 0-100 range."""
    if document_type != "DPR":
        return []

    field_data = fields.get("advance_percentage")
    if not field_data or field_data.get("value") is None:
        return []

    raw_value = str(field_data["value"]).replace("%", "").strip()
    try:
        percentage = Decimal(raw_value)
    except InvalidOperation:
        return []  # not parseable as a number -- a format concern, not this rule's job

    if percentage < 0 or percentage > 100:
        return [
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.ERROR,
                field_key="advance_percentage",
                message=f"Advance Percentage ({percentage}) is outside the valid 0-100 range.",
            )
        ]
    return []


# All business-rule checks, run unconditionally per document -- each
# function internally no-ops if document_type doesn't match what it
# checks, so this list can simply be iterated in full every time.
ALL_BUSINESS_RULES = [
    validate_poi_npo_amounts,
    validate_msi_amounts,
    validate_jer_debit_equals_credit,
    validate_ima_travel_dates,
    validate_ima_approved_amount,
    validate_lca_dates,
    validate_dpr_advance_percentage,
]


def validate_business_rules(fields: dict, document_type: str) -> list[ValidationIssue]:
    issues = []
    for rule_fn in ALL_BUSINESS_RULES:
        issues.extend(rule_fn(fields, document_type))
    return issues
