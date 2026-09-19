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
from typing import Any


from app.extraction.field_schemas import get_full_field_schema
from app.validation.base import ValidationIssue, ValidationRuleType, ValidationSeverity
from app.validation.mandatory_fields import get_mandatory_fields


def _extract_val(field_obj: Any) -> Any:
    if field_obj is None:
        return None
    if isinstance(field_obj, dict):
        return field_obj.get("value")
    if hasattr(field_obj, "value"):
        return getattr(field_obj, "value")
    return field_obj


def _lookup_field_data(fields: dict, key: str) -> tuple[str, Any]:
    """Look up field data by key, checking direct match, canonical/flat mapping, and nested dict.

    Returns (effective_key, field_data).
    """
    from app.extraction.field_schemas import (
        map_npo_canonical_to_flat,
        map_npo_flat_to_canonical,
    )

    # 1. Direct key match
    if key in fields:
        return key, fields[key]

    # 2. Canonical mapping for flat key (e.g. invoice_number -> invoice_information.invoice_number)
    canonical_key = map_npo_flat_to_canonical(key)
    if canonical_key in fields:
        return canonical_key, fields[canonical_key]

    # 3. Flat mapping for canonical key (e.g. invoice_information.invoice_number -> invoice_number)
    flat_key = map_npo_canonical_to_flat(key)
    if flat_key in fields:
        return flat_key, fields[flat_key]

    # 4. Nested dict traversal (e.g. fields["invoice_information"]["invoice_number"])
    path = canonical_key if "." in canonical_key else key
    if "." in path:
        parts = path.split(".")
        curr = fields
        found = True
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            elif hasattr(curr, part):
                curr = getattr(curr, part)
            else:
                found = False
                break
        if found and curr is not None:
            return path, curr

    # 5. Fallback inside canonical payload container if present
    if "canonical" in fields:
        c_root = fields["canonical"]
        if isinstance(c_root, dict) and "value" in c_root and isinstance(c_root["value"], dict):
            c_root = c_root["value"]
        if isinstance(c_root, dict):
            path = canonical_key if "." in canonical_key else key
            parts = path.split(".")
            curr = c_root
            found = True
            for part in parts:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                elif hasattr(curr, part):
                    curr = getattr(curr, part)
                else:
                    found = False
                    break
            if found and curr is not None:
                return path, curr

    return key, None


# Mandatory processing core specifications for NPO:
# Only these 6 fields are required for the invoice to be considered minimally processable
NPO_MANDATORY_CORE_SPECS = [
    ("invoice_number", "invoice_information.invoice_number"),
    ("invoice_date", "invoice_information.invoice_date"),
    ("currency", "invoice_information.currency"),
    ("seller_name", "seller.name"),
    ("buyer_name", "buyer.name"),
    ("grand_total_amount", "totals.grand_total"),
]


def validate_required_fields(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Every mandatory field for this document type must have a non-null value."""
    issues = []
    doc_type_upper = (document_type or "").upper()

    if doc_type_upper == "NPO":
        uses_canonical = any("." in k for k in fields.keys()) or any(
            k in ("invoice_information", "seller", "buyer", "totals") for k in fields.keys()
        )
        for flat_key, canonical_path in NPO_MANDATORY_CORE_SPECS:
            search_key = canonical_path if uses_canonical else flat_key
            eff_key, field_data = _lookup_field_data(fields, search_key)
            val = _extract_val(field_data)
            if val is None or (isinstance(val, str) and not val.strip()):
                reported_key = eff_key if field_data is not None else search_key
                issues.append(
                    ValidationIssue(
                        rule_type=ValidationRuleType.REQUIRED_FIELD,
                        severity=ValidationSeverity.ERROR,
                        field_key=reported_key,
                        message=f"Required field '{reported_key}' is missing.",
                    )
                )
        return issues

    for field_key in sorted(get_mandatory_fields(document_type)):
        eff_key, field_data = _lookup_field_data(fields, field_key)
        val = _extract_val(field_data)
        if val is None or (isinstance(val, str) and not val.strip()):
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
    if (document_type or "").upper() == "NPO":
        date_field_keys.update({"invoice_information.invoice_date", "payment.due_date"})

    for field_key in sorted(date_field_keys):
        eff_key, field_data = _lookup_field_data(fields, field_key)
        if not field_data:
            continue
        raw_val = _extract_val(field_data)
        if raw_val is None:
            continue  # absence is a REQUIRED_FIELD concern, not a format concern

        value = str(raw_val).strip()
        if not _ISO_DATE_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.DATE_FORMAT,
                    severity=ValidationSeverity.ERROR,
                    field_key=eff_key,
                    message=f"Field '{eff_key}' value '{value}' is not a valid date.",
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
                    field_key=eff_key,
                    message=f"Field '{eff_key}' value '{value}' is not a real calendar date.",
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
    amount_field_keys.discard("ocr_confidence_score")
    if (document_type or "").upper() == "NPO":
        amount_field_keys.update({
            "totals.subtotal",
            "totals.total_tax",
            "totals.grand_total",
            "totals.discount",
            "totals.shipping",
            "totals.other_charges",
            "totals.rounding",
        })

    for field_key in sorted(amount_field_keys):
        eff_key, field_data = _lookup_field_data(fields, field_key)
        if not field_data:
            continue
        raw_val = _extract_val(field_data)
        if raw_val is None:
            continue

        value = str(raw_val).strip()
        if not _AMOUNT_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.AMOUNT_FORMAT,
                    severity=ValidationSeverity.ERROR,
                    field_key=eff_key,
                    message=f"Field '{eff_key}' value '{value}' is not a valid non-negative amount.",
                )
            )

    # Validate amount attributes on line_items if present, without failing on nullable/unsupported attributes
    line_items = fields.get("line_items")
    if isinstance(line_items, list):
        for idx, item in enumerate(line_items):
            if not isinstance(item, dict):
                continue
            for amt_field in ("unit_price", "net_amount", "tax_rate", "tax_amount", "gross_amount"):
                if amt_field in item:
                    item_amt_val = _extract_val(item[amt_field])
                    if item_amt_val is not None:
                        val_str = str(item_amt_val).strip()
                        if not _AMOUNT_PATTERN.match(val_str):
                            issues.append(
                                ValidationIssue(
                                    rule_type=ValidationRuleType.AMOUNT_FORMAT,
                                    severity=ValidationSeverity.ERROR,
                                    field_key=f"line_items[{idx}].{amt_field}",
                                    message=f"Line item #{idx + 1} field '{amt_field}' value '{val_str}' is not a valid non-negative amount.",
                                )
                            )

    return issues


# Heuristic check for tax-ID-like identifiers. Modeled on India's GST
# registration number format (15 alphanumeric characters: 2-digit state
# code + 10-character PAN + entity/check digits) since that was the
# original spec's explicit reference point, but applied loosely (as a
# WARNING, not an ERROR) to identifying code fields across types.
_GST_LIKE_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z A-Z]\d$", re.IGNORECASE)

_TAX_ID_CANDIDATE_FIELDS = {"vendor_code", "customer_code", "seller_tax_id", "buyer_tax_id"}


def validate_tax_id_format(fields: dict, document_type: str) -> list[ValidationIssue]:
    """
    If a vendor_code/customer_code/tax_id value happens to look like it was
    intended as a GST-style tax registration number (starts with 2
    digits, is around 15 characters), check it actually matches the
    expected pattern. This is intentionally a WARNING, not an ERROR.
    """
    issues = []
    candidate_keys = list(_TAX_ID_CANDIDATE_FIELDS)
    if (document_type or "").upper() == "NPO":
        candidate_keys.extend(["seller.tax_id", "buyer.tax_id"])

    for field_key in sorted(candidate_keys):
        eff_key, field_data = _lookup_field_data(fields, field_key)
        if not field_data:
            continue
        raw_val = _extract_val(field_data)
        if raw_val is None:
            continue

        value = str(raw_val).strip().upper()
        looks_like_tax_id_attempt = len(value) >= 13 and value[:2].isdigit()
        if not looks_like_tax_id_attempt:
            continue

        if not _GST_LIKE_PATTERN.match(value):
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.TAX_ID_FORMAT,
                    severity=ValidationSeverity.WARNING,
                    field_key=eff_key,
                    message=(
                        f"Field '{eff_key}' value '{value}' resembles a tax "
                        "registration number but does not match the expected format."
                    ),
                )
            )

    return issues


_RECOGNIZED_CURRENCIES = {
    "USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "CHF", "SGD", "CNY", "SEK", "NZD",
    "HKD", "NOK", "KRW", "MXN", "BRL", "ZAR", "AED", "SAR", "DKK", "PLN", "THB", "IDR",
    "HUF", "CZK", "ILS", "CLP", "PHP", "TRY", "TWD", "MYR",
    "$", "€", "£", "₹", "¥", "₩", "₪", "฿", "R$", "KR"
}


def validate_currency_fields(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Validate that currency is a recognized standard ISO 4217 code or common currency symbol."""
    issues = []
    keys_to_check = (
        ["currency", "invoice_information.currency"]
        if (document_type or "").upper() == "NPO"
        else ["currency"]
    )
    for key in keys_to_check:
        eff_key, field_data = _lookup_field_data(fields, key)
        if not field_data:
            continue
        raw_val = _extract_val(field_data)
        if raw_val is None:
            continue
        curr_str = str(raw_val).strip().upper()
        raw_str = str(raw_val).strip()
        if curr_str not in _RECOGNIZED_CURRENCIES and raw_str not in _RECOGNIZED_CURRENCIES:
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.BUSINESS_RULE,
                    severity=ValidationSeverity.WARNING,
                    field_key=eff_key,
                    message=f"Field '{eff_key}' value '{raw_val}' is not a recognized standard currency code or symbol.",
                )
            )
        break
    return issues
