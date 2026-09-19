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
import enum
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.validation.base import ValidationIssue, ValidationRuleType, ValidationSeverity

_AMOUNT_TOLERANCE = Decimal("0.01")


class ArithmeticReconciliationStatus(str, enum.Enum):
    """Classification for arithmetic verification.

    Distinguishes missing information from invalid information:
    - VALID: Operands exist and equation balances within tolerance.
    - MISMATCH: Operands exist and equation fails tolerance (discrepancy).
    - NOT_CHECKABLE: Required operands are missing/null; calculation cannot be
      performed. Not checkable is NOT invalid.
    """
    VALID = "VALID"
    MISMATCH = "MISMATCH"
    NOT_CHECKABLE = "NOT_CHECKABLE"


@dataclass
class ArithmeticReconciliationResult:
    rule_name: str
    status: ArithmeticReconciliationStatus
    is_valid: bool
    message: str
    total_amount: Decimal | None = None
    subtotal_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    calculated_total: Decimal | None = None
    difference: Decimal | None = None


def _get_decimal(fields: dict, key: str) -> Decimal | None:
    """Extract a Decimal value from fields, supporting flat keys, canonical paths, and nested sections."""
    from app.extraction.field_schemas import (
        map_npo_canonical_to_flat,
        map_npo_flat_to_canonical,
    )

    field_data = None
    # 1. Direct match
    if key in fields:
        field_data = fields[key]
    # 2. Canonical mapping for flat key
    elif map_npo_flat_to_canonical(key) in fields:
        field_data = fields[map_npo_flat_to_canonical(key)]
    # 3. Flat mapping for canonical key
    elif map_npo_canonical_to_flat(key) in fields:
        field_data = fields[map_npo_canonical_to_flat(key)]
    # 4. Nested dict traversal (e.g. fields["totals"]["grand_total"])
    else:
        path = map_npo_flat_to_canonical(key) if "." not in key else key
        if "." in path:
            parts = path.split(".")
            curr = fields
            for part in parts:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                elif hasattr(curr, part):
                    curr = getattr(curr, part)
                else:
                    curr = None
                    break
            if curr is not None:
                field_data = curr

    if field_data is None:
        return None

    raw_val = None
    if isinstance(field_data, dict):
        raw_val = field_data.get("value")
    elif hasattr(field_data, "value"):
        raw_val = getattr(field_data, "value")
    else:
        raw_val = field_data

    if raw_val is None:
        return None

    try:
        cleaned = str(raw_val).replace(",", "").strip()
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def reconcile_npo_totals(fields: dict) -> ArithmeticReconciliationResult:
    """
    Document-level reconciliation: Reconcile grand total == subtotal + total tax (+ charges/discounts/rounding) for NPO invoices.

    CRITICAL ARCHITECTURAL PRINCIPLE:
    Document-level reconciliation is completely independent of line_items[].
    An empty line_items collection (`line_items = []`) makes ONLY line-item-level reconciliation
    unavailable; it must NOT automatically prevent document-level reconciliation.
    If subtotal, total_tax, grand_total, and any applicable discounts/charges/rounding are available,
    document-level reconciliation evaluates to VALID or MISMATCH regardless of whether line_items is empty.

    Missing information is NOT invalid information:
    If required document-level values (e.g. subtotal, total_tax, or grand_total) are unavailable,
    document-level reconciliation is classified as NOT_CHECKABLE (is_valid=True), producing 0 validation errors.
    """
    total = _get_decimal(fields, "totals.grand_total")
    subtotal = _get_decimal(fields, "totals.subtotal")
    tax = _get_decimal(fields, "totals.total_tax")

    # If any required document-level operand is unavailable, document-level reconciliation is NOT_CHECKABLE
    if total is None or subtotal is None or tax is None:
        missing_parts = []
        if total is None:
            missing_parts.append("grand_total")
        if subtotal is None:
            missing_parts.append("subtotal")
        if tax is None:
            missing_parts.append("total_tax")
        return ArithmeticReconciliationResult(
            rule_name="npo_totals_reconciliation",
            status=ArithmeticReconciliationStatus.NOT_CHECKABLE,
            is_valid=True,
            message=(
                f"Document-level arithmetic reconciliation is not checkable: missing required values "
                f"({', '.join(missing_parts)}). Missing information is not invalid information."
            ),
            total_amount=total,
            subtotal_amount=subtotal,
            tax_amount=tax,
        )

    discount = _get_decimal(fields, "totals.discount") or Decimal("0")
    shipping = _get_decimal(fields, "totals.shipping") or Decimal("0")
    other_charges = _get_decimal(fields, "totals.other_charges") or Decimal("0")
    rounding = _get_decimal(fields, "totals.rounding") or Decimal("0")

    expected = subtotal + tax - discount + shipping + other_charges + rounding
    diff = abs(total - expected)
    if diff <= _AMOUNT_TOLERANCE:
        details = f"subtotal ({subtotal}) + tax ({tax})"
        if discount:
            details += f" - discount ({discount})"
        if shipping:
            details += f" + shipping ({shipping})"
        if other_charges:
            details += f" + other_charges ({other_charges})"
        if rounding:
            details += f" + rounding ({rounding})"
        return ArithmeticReconciliationResult(
            rule_name="npo_totals_reconciliation",
            status=ArithmeticReconciliationStatus.VALID,
            is_valid=True,
            message=f"Document totals reconcile accurately: {details} == grand_total ({total}).",
            total_amount=total,
            subtotal_amount=subtotal,
            tax_amount=tax,
            calculated_total=expected,
            difference=diff,
        )

    return ArithmeticReconciliationResult(
        rule_name="npo_totals_reconciliation",
        status=ArithmeticReconciliationStatus.MISMATCH,
        is_valid=False,
        message=(
            f"Grand Total Amount should equal Subtotal + Tax (+ charges/discounts/rounding): "
            f"expected grand_total={expected}, but found grand_total={total}."
        ),
        total_amount=total,
        subtotal_amount=subtotal,
        tax_amount=tax,
        calculated_total=expected,
        difference=diff,
    )


def _extract_decimal_from_obj(val: Any) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("value")
    elif hasattr(val, "value"):
        val = getattr(val, "value")
    if val is None:
        return None
    try:
        cleaned = str(val).replace(",", "").replace("%", "").strip()
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _get_line_items(fields: dict) -> list:
    items = fields.get("line_items")
    if isinstance(items, dict):
        items = items.get("value")
    if items is None and "canonical" in fields:
        c = fields["canonical"]
        if isinstance(c, dict) and "value" in c and isinstance(c["value"], dict):
            c = c["value"]
        if isinstance(c, dict):
            items = c.get("line_items")
    if isinstance(items, list):
        return items
    return []


def _get_taxes(fields: dict) -> list:
    taxes = fields.get("taxes")
    if isinstance(taxes, dict):
        taxes = taxes.get("value")
    if taxes is None and "canonical" in fields:
        c = fields["canonical"]
        if isinstance(c, dict) and "value" in c and isinstance(c["value"], dict):
            c = c["value"]
        if isinstance(c, dict):
            taxes = c.get("taxes")
    if isinstance(taxes, list):
        return taxes
    return []


def reconcile_line_items_arithmetic(fields: dict) -> ArithmeticReconciliationResult:
    """
    Line-item-level reconciliation: Reconcile sum(line_item.net_amount) == subtotal.

    CRITICAL ARCHITECTURAL PRINCIPLE:
    This check is strictly separate from document-level totals reconciliation.
    `line_items = []` skips only this line-item check and returns NOT_CHECKABLE (is_valid=True).
    It does NOT make document-level reconciliation NOT_CHECKABLE.

    Classified as NOT_CHECKABLE if:
    - line_items is empty (valid zero-or-many collection; skip line-item arithmetic)
    - any line item has net_amount is None (e.g. narrative or unsupported decomposition)
    - subtotal is None
    """
    line_items = _get_line_items(fields)
    if not line_items or not isinstance(line_items, list):
        return ArithmeticReconciliationResult(
            rule_name="line_items_vs_subtotal",
            status=ArithmeticReconciliationStatus.NOT_CHECKABLE,
            is_valid=True,
            message="No line items present (line_items is zero-or-many collection). Not checkable, not invalid.",
        )

    subtotal = _get_decimal(fields, "totals.subtotal")
    if subtotal is None:
        return ArithmeticReconciliationResult(
            rule_name="line_items_vs_subtotal",
            status=ArithmeticReconciliationStatus.NOT_CHECKABLE,
            is_valid=True,
            message="Subtotal is null/unavailable. Line item reconciliation is not checkable, not invalid.",
        )

    item_nets: list[Decimal] = []
    for itm in line_items:
        net_val = _extract_decimal_from_obj(itm.get("net_amount") if isinstance(itm, dict) else None)
        if net_val is None:
            return ArithmeticReconciliationResult(
                rule_name="line_items_vs_subtotal",
                status=ArithmeticReconciliationStatus.NOT_CHECKABLE,
                is_valid=True,
                message="One or more line items lack explicit net_amount (narrative or unsupported itemization). Not checkable, not invalid.",
                subtotal_amount=subtotal,
            )
        item_nets.append(net_val)

    sum_nets = sum(item_nets, Decimal("0"))
    diff = abs(sum_nets - subtotal)
    if diff <= _AMOUNT_TOLERANCE:
        return ArithmeticReconciliationResult(
            rule_name="line_items_vs_subtotal",
            status=ArithmeticReconciliationStatus.VALID,
            is_valid=True,
            message=f"Sum of line items ({sum_nets}) matches subtotal ({subtotal}).",
            subtotal_amount=subtotal,
            calculated_total=sum_nets,
            difference=diff,
        )

    return ArithmeticReconciliationResult(
        rule_name="line_items_vs_subtotal",
        status=ArithmeticReconciliationStatus.MISMATCH,
        is_valid=False,
        message=f"Sum of line items ({sum_nets}) differs from subtotal ({subtotal}) by {diff}.",
        subtotal_amount=subtotal,
        calculated_total=sum_nets,
        difference=diff,
    )


def reconcile_line_item_math(item: dict) -> ArithmeticReconciliationResult:
    """
    Reconcile quantity * unit_price == net_amount for an individual line item.

    If quantity or unit_price is unstated/null (e.g. narrative consulting services),
    returns NOT_CHECKABLE and is_valid=True.
    """
    qty = _extract_decimal_from_obj(item.get("quantity"))
    price = _extract_decimal_from_obj(item.get("unit_price"))
    net = _extract_decimal_from_obj(item.get("net_amount"))

    if qty is None or price is None or net is None:
        return ArithmeticReconciliationResult(
            rule_name="line_item_math",
            status=ArithmeticReconciliationStatus.NOT_CHECKABLE,
            is_valid=True,
            message="Quantity, unit price, or net amount is null (narrative or unsupported itemization). Not checkable, not invalid.",
        )

    expected = qty * price
    diff = abs(expected - net)
    if diff <= _AMOUNT_TOLERANCE:
        return ArithmeticReconciliationResult(
            rule_name="line_item_math",
            status=ArithmeticReconciliationStatus.VALID,
            is_valid=True,
            message=f"Line item math balances: {qty} * {price} == {net}.",
            calculated_total=expected,
            difference=diff,
        )

    return ArithmeticReconciliationResult(
        rule_name="line_item_math",
        status=ArithmeticReconciliationStatus.MISMATCH,
        is_valid=False,
        message=f"Line item math mismatch: {qty} * {price} expected {expected}, but found net {net}.",
        calculated_total=expected,
        difference=diff,
    )


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
    """Grand Total Amount should equal Total Tax Amount + Subtotal Net Amount (POI and NPO both have these fields)."""
    if document_type not in ("POI", "NPO"):
        return []

    doc_type_upper = document_type.upper()
    if doc_type_upper == "NPO":
        res = reconcile_npo_totals(fields)
        if res.status == ArithmeticReconciliationStatus.MISMATCH:
            total_key = "totals.grand_total" if "totals.grand_total" in fields or "totals" in fields else "grand_total_amount"
            return [
                ValidationIssue(
                    rule_type=ValidationRuleType.BUSINESS_RULE,
                    severity=ValidationSeverity.WARNING,
                    field_key=total_key,
                    message=res.message,
                )
            ]
        # VALID or NOT_CHECKABLE produces no failure issues
        return []

    total_key = "grand_total_amount" if "grand_total_amount" in fields else "invoice_amount"
    tax_key = "total_tax_amount" if "total_tax_amount" in fields else "tax_amount"
    net_key = "subtotal_net_amount" if "subtotal_net_amount" in fields else "net_amount"
    return _check_sum_consistency(
        fields,
        total_key=total_key,
        part_keys=[tax_key, net_key],
        rule_description="Grand Total Amount should equal Total Tax Amount + Subtotal Net Amount",
    )


def validate_msi_amounts(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Sales Invoice Amount should equal Total Tax Amount + Subtotal Net Amount."""
    if document_type != "MSI":
        return []
    total_key = "grand_total_amount" if "grand_total_amount" in fields else "invoice_amount"
    tax_key = "total_tax_amount" if "total_tax_amount" in fields else "tax_amount"
    net_key = "subtotal_net_amount" if "subtotal_net_amount" in fields else "net_amount"
    return _check_sum_consistency(
        fields,
        total_key=total_key,
        part_keys=[tax_key, net_key],
        rule_description="Grand Total Amount should equal Total Tax Amount + Subtotal Net Amount",
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
def validate_npo_line_items(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Validate NPO line-item consistency where data exists.

    1. line_items=[] is a valid structural state (0 issues).
    2. Where line items exist and subtotal exists, validate sum(net_amount) == subtotal.
    3. Where individual line items have quantity and unit_price, validate quantity * unit_price == net_amount.
       If quantity or unit_price is None (e.g. narrative service invoice), it is NOT_CHECKABLE (0 issues).
    4. Where individual line items have net_amount and tax_amount, validate net_amount + tax_amount == gross_amount if gross_amount is present.
    """
    if (document_type or "").upper() != "NPO":
        return []

    line_items = _get_line_items(fields)
    if not line_items:
        # line_items = [] is a valid zero-or-many collection; skip line-item checks
        return []

    issues = []

    # 1. Line-item sum vs subtotal
    subtotal_res = reconcile_line_items_arithmetic(fields)
    if subtotal_res.status == ArithmeticReconciliationStatus.MISMATCH:
        issues.append(
            ValidationIssue(
                rule_type=ValidationRuleType.BUSINESS_RULE,
                severity=ValidationSeverity.WARNING,
                field_key="totals.subtotal",
                message=subtotal_res.message,
            )
        )

    # 2. Individual line item checks
    for idx, item in enumerate(line_items):
        if not isinstance(item, dict):
            continue
        math_res = reconcile_line_item_math(item)
        if math_res.status == ArithmeticReconciliationStatus.MISMATCH:
            issues.append(
                ValidationIssue(
                    rule_type=ValidationRuleType.BUSINESS_RULE,
                    severity=ValidationSeverity.WARNING,
                    field_key=f"line_items[{idx}].net_amount",
                    message=f"Line item {idx + 1}: {math_res.message}",
                )
            )

        net = _extract_decimal_from_obj(item.get("net_amount"))
        tax = _extract_decimal_from_obj(item.get("tax_amount"))
        gross = _extract_decimal_from_obj(item.get("gross_amount"))
        if net is not None and tax is not None and gross is not None:
            expected_gross = net + tax
            if abs(expected_gross - gross) > _AMOUNT_TOLERANCE:
                issues.append(
                    ValidationIssue(
                        rule_type=ValidationRuleType.BUSINESS_RULE,
                        severity=ValidationSeverity.WARNING,
                        field_key=f"line_items[{idx}].gross_amount",
                        message=(
                            f"Line item {idx + 1}: net_amount ({net}) + tax_amount ({tax}) "
                            f"expected gross {expected_gross}, but found {gross}."
                        ),
                    )
                )

    return issues


def validate_npo_taxes(fields: dict, document_type: str) -> list[ValidationIssue]:
    """Validate NPO tax items consistency where data exists.

    1. taxes=[] is a valid structural state (0 issues).
    2. Where taxes exist and total_tax exists, validate sum(tax_amount) == total_tax.
    3. Where individual tax items have taxable_amount and rate_percentage, validate taxable_amount * (rate_percentage / 100) == tax_amount.
       If rate or taxable_amount is missing, it is NOT_CHECKABLE (0 issues).
    """
    if (document_type or "").upper() != "NPO":
        return []

    taxes = _get_taxes(fields)
    if not taxes:
        # taxes = [] is a valid zero-or-many collection; skip tax checks
        return []

    issues = []

    # 1. Sum of tax items vs total_tax
    total_tax = _get_decimal(fields, "totals.total_tax")
    if total_tax is not None:
        tax_amounts: list[Decimal] = []
        all_have_amount = True
        for itm in taxes:
            if not isinstance(itm, dict):
                continue
            amt = _extract_decimal_from_obj(itm.get("tax_amount"))
            if amt is None:
                all_have_amount = False
                break
            tax_amounts.append(amt)

        if all_have_amount and tax_amounts:
            sum_taxes = sum(tax_amounts, Decimal("0"))
            if abs(sum_taxes - total_tax) > _AMOUNT_TOLERANCE:
                issues.append(
                    ValidationIssue(
                        rule_type=ValidationRuleType.BUSINESS_RULE,
                        severity=ValidationSeverity.WARNING,
                        field_key="totals.total_tax",
                        message=(
                            f"Sum of tax items ({sum_taxes}) differs from total tax ({total_tax}) "
                            f"by {abs(sum_taxes - total_tax)}."
                        ),
                    )
                )

    # 2. Individual tax rate calculation
    for idx, itm in enumerate(taxes):
        if not isinstance(itm, dict):
            continue
        taxable = _extract_decimal_from_obj(itm.get("taxable_amount"))
        rate = _extract_decimal_from_obj(itm.get("rate_percentage"))
        tax_amt = _extract_decimal_from_obj(itm.get("tax_amount"))
        if taxable is not None and rate is not None and tax_amt is not None:
            expected_tax = (taxable * rate) / Decimal("100")
            if abs(expected_tax - tax_amt) > Decimal("0.05"):
                issues.append(
                    ValidationIssue(
                        rule_type=ValidationRuleType.BUSINESS_RULE,
                        severity=ValidationSeverity.WARNING,
                        field_key=f"taxes[{idx}].tax_amount",
                        message=(
                            f"Tax item {idx + 1}: taxable amount {taxable} at {rate}% "
                            f"expected tax {expected_tax:.2f}, but found {tax_amt}."
                        ),
                    )
                )

    return issues


# All business-rule checks, run unconditionally per document -- each
# function internally no-ops if document_type doesn't match what it
# checks, so this list can simply be iterated in full every time.
ALL_BUSINESS_RULES = [
    validate_poi_npo_amounts,
    validate_npo_line_items,
    validate_npo_taxes,
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
