"""
Comprehensive unit tests for NPO Mandatory Field and Collection Semantics.

Verifies the two review findings:
Issue 1: Mandatory Field Semantics (minimal processability core of 6 fields vs optional null fields)
Issue 2: line_items[] and taxes[] zero-or-many semantics and nullable leaf fields

Covers all 12 required scenarios:
1. All mandatory core fields present -> valid
2. Missing seller.tax_id -> does not fail mandatory validation
3. Missing buyer.tax_id -> does not fail mandatory validation
4. Missing subtotal -> does not fail mandatory validation
5. Missing total_tax -> does not fail mandatory validation
6. line_items = [] -> valid with respect to mandatory-field validation
7. taxes = [] -> valid with respect to mandatory-field validation
8. Narrative service line with nullable quantity/unit_price -> valid
9. Multiple line items with some nullable attributes -> valid
10. Arithmetic reconciliation with insufficient data -> not checkable, not invalid
11. Missing invoice_number -> mandatory-field validation issue
12. Missing grand_total -> mandatory-field validation issue
"""
from decimal import Decimal
import pytest

from app.extraction.field_schemas import (
    NPO_CANONICAL_SCHEMA,
    NPO_MANDATORY_CORE_PATHS,
    NPO_IMPORTANT_OPTIONAL_PATHS,
)
from app.extraction.llm_schema import (
    LLMFieldItem,
    NPOExtractionPayload,
    NPOLineItemPayload,
    NPOTaxItemPayload,
    NPOInvoiceInformationPayload,
    NPOSellerPayload,
    NPOBuyerPayload,
    NPOTotalsPayload,
)
from app.validation.base import ValidationRuleType, ValidationSeverity
from app.validation.mandatory_fields import get_mandatory_fields, is_field_mandatory
from app.validation.field_validators import (
    validate_required_fields,
    validate_amount_fields,
    validate_date_fields,
)
from app.validation.business_rules import (
    ArithmeticReconciliationStatus,
    reconcile_npo_totals,
    reconcile_line_items_arithmetic,
    reconcile_line_item_math,
    validate_business_rules,
    validate_poi_npo_amounts,
)


def _base_valid_npo_flat_fields() -> dict:
    """Return minimally complete valid flat fields for NPO."""
    return {
        "invoice_number": {"value": "INV-2026-001"},
        "invoice_date": {"value": "2026-06-15"},
        "currency": {"value": "USD"},
        "seller_name": {"value": "Global Tech Services LLC"},
        "buyer_name": {"value": "Acme Enterprises Corp"},
        "grand_total_amount": {"value": "5000.00"},
    }


def _base_valid_npo_canonical_fields() -> dict:
    """Return minimally complete valid canonical dot-path fields for NPO."""
    return {
        "invoice_information.invoice_number": {"value": "INV-2026-001"},
        "invoice_information.invoice_date": {"value": "2026-06-15"},
        "invoice_information.currency": {"value": "USD"},
        "seller.name": {"value": "Global Tech Services LLC"},
        "buyer.name": {"value": "Acme Enterprises Corp"},
        "totals.grand_total": {"value": "5000.00"},
    }


# =====================================================================
# 1. All mandatory core fields present -> valid
# =====================================================================

def test_1_all_mandatory_core_fields_present_flat_is_valid():
    """Requirement 1: Invoice with all 6 core mandatory fields (flat) passes validation."""
    fields = _base_valid_npo_flat_fields()
    issues = validate_required_fields(fields, "NPO")
    assert issues == [], f"Expected 0 issues for complete mandatory core, got {issues}"


def test_1_all_mandatory_core_fields_present_canonical_is_valid():
    """Requirement 1 (canonical): Invoice with all 6 core mandatory fields (canonical) passes validation."""
    fields = _base_valid_npo_canonical_fields()
    issues = validate_required_fields(fields, "NPO")
    assert issues == [], f"Expected 0 issues for complete canonical core, got {issues}"


# =====================================================================
# 2. Missing seller.tax_id -> does not fail mandatory validation
# =====================================================================

def test_2_missing_seller_tax_id_does_not_fail():
    """Requirement 2: seller.tax_id / seller_tax_id is optional and does not cause mandatory failure."""
    assert is_field_mandatory("NPO", "seller.tax_id") is False
    assert is_field_mandatory("NPO", "seller_tax_id") is False

    fields = _base_valid_npo_canonical_fields()
    fields["seller.tax_id"] = {"value": None}
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["seller_tax_id"] = {"value": None}
    assert validate_required_fields(flat, "NPO") == []


# =====================================================================
# 3. Missing buyer.tax_id -> does not fail mandatory validation
# =====================================================================

def test_3_missing_buyer_tax_id_does_not_fail():
    """Requirement 3: buyer.tax_id / buyer_tax_id is optional and does not cause mandatory failure."""
    assert is_field_mandatory("NPO", "buyer.tax_id") is False
    assert is_field_mandatory("NPO", "buyer_tax_id") is False

    fields = _base_valid_npo_canonical_fields()
    fields["buyer.tax_id"] = {"value": None}
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["buyer_tax_id"] = {"value": None}
    assert validate_required_fields(flat, "NPO") == []


# =====================================================================
# 4. Missing subtotal -> does not fail mandatory validation
# =====================================================================

def test_4_missing_subtotal_does_not_fail():
    """Requirement 4: totals.subtotal / subtotal_net_amount is optional and does not cause mandatory failure."""
    assert is_field_mandatory("NPO", "totals.subtotal") is False
    assert is_field_mandatory("NPO", "subtotal_net_amount") is False

    fields = _base_valid_npo_canonical_fields()
    fields["totals.subtotal"] = {"value": None}
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["subtotal_net_amount"] = {"value": None}
    assert validate_required_fields(flat, "NPO") == []


# =====================================================================
# 5. Missing total_tax -> does not fail mandatory validation
# =====================================================================

def test_5_missing_total_tax_does_not_fail():
    """Requirement 5: totals.total_tax / total_tax_amount is optional and does not cause mandatory failure."""
    assert is_field_mandatory("NPO", "totals.total_tax") is False
    assert is_field_mandatory("NPO", "total_tax_amount") is False

    fields = _base_valid_npo_canonical_fields()
    fields["totals.total_tax"] = {"value": None}
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["total_tax_amount"] = {"value": None}
    assert validate_required_fields(flat, "NPO") == []


# =====================================================================
# 6. line_items = [] -> valid with respect to mandatory-field validation
# =====================================================================

def test_6_empty_line_items_is_valid():
    """Requirement 6: line_items=[] represents a valid zero-or-many collection."""
    fields = _base_valid_npo_canonical_fields()
    fields["line_items"] = []
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Verify Pydantic payload natively defaults to []
    payload = NPOExtractionPayload(
        invoice_information=NPOInvoiceInformationPayload(
            invoice_number=LLMFieldItem(value="INV-2026-001"),
            invoice_date=LLMFieldItem(value="2026-06-15"),
            currency=LLMFieldItem(value="USD"),
        ),
        seller=NPOSellerPayload(name=LLMFieldItem(value="Seller Inc")),
        buyer=NPOBuyerPayload(name=LLMFieldItem(value="Buyer Inc")),
        totals=NPOTotalsPayload(grand_total=LLMFieldItem(value="5000.00")),
        line_items=[],
    )
    assert payload.line_items == []
    canonical_dict = payload.to_canonical_dict()
    assert canonical_dict["line_items"] == []


# =====================================================================
# 7. taxes = [] -> valid with respect to mandatory-field validation
# =====================================================================

def test_7_empty_taxes_is_valid():
    """Requirement 7: taxes=[] represents a valid zero-or-many collection."""
    fields = _base_valid_npo_canonical_fields()
    fields["taxes"] = []
    issues = validate_required_fields(fields, "NPO")
    assert issues == []

    # Verify Pydantic payload natively defaults to []
    payload = NPOExtractionPayload(
        invoice_information=NPOInvoiceInformationPayload(
            invoice_number=LLMFieldItem(value="INV-2026-001"),
            invoice_date=LLMFieldItem(value="2026-06-15"),
            currency=LLMFieldItem(value="USD"),
        ),
        seller=NPOSellerPayload(name=LLMFieldItem(value="Seller Inc")),
        buyer=NPOBuyerPayload(name=LLMFieldItem(value="Buyer Inc")),
        totals=NPOTotalsPayload(grand_total=LLMFieldItem(value="5000.00")),
        taxes=[],
    )
    assert payload.taxes == []
    canonical_dict = payload.to_canonical_dict()
    assert canonical_dict["taxes"] == []


# =====================================================================
# 8. Narrative service line with nullable quantity/unit_price -> valid
# =====================================================================

def test_8_narrative_service_line_nullable_quantity_and_unit_price():
    """Requirement 8: A line item with narrative service and null quantity/unit_price is valid."""
    narrative_item = NPOLineItemPayload(
        description=LLMFieldItem(value="Professional consulting services for Q2"),
        quantity=None,    # Explicitly null: do NOT infer quantity=1
        uom=None,         # Explicitly null
        unit_price=None,  # Explicitly null: do NOT infer unit_price=5000.00
        net_amount=LLMFieldItem(value="5000.00"),
        tax_rate=LLMFieldItem(value="10.0"),
        tax_amount=LLMFieldItem(value="500.00"),
        gross_amount=LLMFieldItem(value="5500.00"),
    )

    payload = NPOExtractionPayload(
        invoice_information=NPOInvoiceInformationPayload(
            invoice_number=LLMFieldItem(value="INV-2026-001"),
            invoice_date=LLMFieldItem(value="2026-06-15"),
            currency=LLMFieldItem(value="USD"),
        ),
        seller=NPOSellerPayload(name=LLMFieldItem(value="Advisory Partners LLC")),
        buyer=NPOBuyerPayload(name=LLMFieldItem(value="Enterprise Corp")),
        totals=NPOTotalsPayload(grand_total=LLMFieldItem(value="5500.00")),
        line_items=[narrative_item],
    )

    canonical = payload.to_canonical_dict()
    assert len(canonical["line_items"]) == 1
    assert canonical["line_items"][0]["description"]["value"] == "Professional consulting services for Q2"
    assert canonical["line_items"][0]["quantity"]["value"] is None
    assert canonical["line_items"][0]["unit_price"]["value"] is None
    assert canonical["line_items"][0]["net_amount"]["value"] == "5000.00"

    # Line item math reconciliation handles null quantity/price as NOT_CHECKABLE, not invalid
    math_res = reconcile_line_item_math({
        "quantity": None,
        "unit_price": None,
        "net_amount": "5000.00",
    })
    assert math_res.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert math_res.is_valid is True

    # Required field validator doesn't fail on narrative line
    fields = _base_valid_npo_canonical_fields()
    fields["line_items"] = [canonical["line_items"][0]]
    assert validate_required_fields(fields, "NPO") == []
    assert validate_amount_fields(fields, "NPO") == []


# =====================================================================
# 9. Multiple line items with some nullable attributes -> valid
# =====================================================================

def test_9_multiple_line_items_some_nullable_attributes():
    """Requirement 9: Multiple line items where some have null quantity/price or tax are valid."""
    items = [
        NPOLineItemPayload(
            description=LLMFieldItem(value="Hardware workstation"),
            quantity=LLMFieldItem(value="2"),
            unit_price=LLMFieldItem(value="1500.00"),
            net_amount=LLMFieldItem(value="3000.00"),
        ),
        NPOLineItemPayload(
            description=LLMFieldItem(value="Onsite deployment labor"),
            quantity=None,  # Null quantity
            unit_price=None,  # Null unit price
            net_amount=LLMFieldItem(value="800.00"),
        ),
        NPOLineItemPayload(
            description=LLMFieldItem(value="Global freight allowance"),
            quantity=None,
            unit_price=None,
            net_amount=LLMFieldItem(value="200.00"),
            tax_rate=None,  # Null tax
        ),
    ]

    payload = NPOExtractionPayload(
        invoice_information=NPOInvoiceInformationPayload(
            invoice_number=LLMFieldItem(value="INV-2026-002"),
            invoice_date=LLMFieldItem(value="2026-06-15"),
            currency=LLMFieldItem(value="USD"),
        ),
        seller=NPOSellerPayload(name=LLMFieldItem(value="Supplier LLC")),
        buyer=NPOBuyerPayload(name=LLMFieldItem(value="Client Inc")),
        totals=NPOTotalsPayload(grand_total=LLMFieldItem(value="4000.00")),
        line_items=items,
    )

    canonical = payload.to_canonical_dict()
    assert len(canonical["line_items"]) == 3
    assert canonical["line_items"][0]["quantity"]["value"] == "2"
    assert canonical["line_items"][1]["quantity"]["value"] is None
    assert canonical["line_items"][2]["tax_rate"]["value"] is None

    fields = payload.flatten_to_paths()
    fields["line_items"] = canonical["line_items"]
    assert validate_required_fields(fields, "NPO") == []
    assert validate_amount_fields(fields, "NPO") == []


# =====================================================================
# 10. Arithmetic reconciliation: Document-level vs Line-item separation
# =====================================================================

def test_10a_empty_line_items_with_valid_document_totals_is_valid():
    """
    Requirement 10a: line_items=[] with valid document totals -> document-level reconciliation VALID.
    An empty line_items collection must NOT prevent document-level arithmetic reconciliation.
    Example: subtotal = 5000, total_tax = 500, grand_total = 5500, line_items = [].
    """
    fields = {
        "totals.grand_total": {"value": "5500.00"},
        "totals.subtotal": {"value": "5000.00"},
        "totals.total_tax": {"value": "500.00"},
        "line_items": [],
    }

    # Document-level reconciliation validates accurately
    doc_res = reconcile_npo_totals(fields)
    assert doc_res.status == ArithmeticReconciliationStatus.VALID
    assert doc_res.is_valid is True
    assert "subtotal (5000.00) + tax (500.00) == grand_total (5500.00)" in doc_res.message

    # Business rule validation returns 0 issues
    issues = validate_poi_npo_amounts(fields, "NPO")
    assert issues == []

    # Line-item-level reconciliation is separately classified as NOT_CHECKABLE
    item_res = reconcile_line_items_arithmetic(fields)
    assert item_res.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert item_res.is_valid is True


def test_10b_empty_line_items_with_mismatched_document_totals_is_mismatch():
    """
    Requirement 10b: line_items=[] with mismatched document totals -> document-level reconciliation MISMATCH.
    Demonstrates that line_items=[] does NOT mask or prevent detecting an arithmetic error in document totals.
    Example: subtotal = 5000, total_tax = 500, grand_total = 6000 (expected 5500), line_items = [].
    """
    fields = {
        "totals.grand_total": {"value": "6000.00"},
        "totals.subtotal": {"value": "5000.00"},
        "totals.total_tax": {"value": "500.00"},
        "line_items": [],
    }

    # Document-level reconciliation flags the arithmetic mismatch
    doc_res = reconcile_npo_totals(fields)
    assert doc_res.status == ArithmeticReconciliationStatus.MISMATCH
    assert doc_res.is_valid is False
    assert doc_res.difference == Decimal("500.00")

    # Business rule validation surfaces a WARNING issue for review
    issues = validate_poi_npo_amounts(fields, "NPO")
    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.WARNING
    assert issues[0].rule_type == ValidationRuleType.BUSINESS_RULE
    assert "expected grand_total=5500.00" in issues[0].message


def test_10c_insufficient_document_level_totals_is_not_checkable():
    """
    Requirement 10c: Insufficient document-level totals -> document-level reconciliation NOT_CHECKABLE.
    Missing information is NOT invalid information.
    """
    # Case 1: subtotal and total_tax are None
    fields_missing_both = {
        "totals.grand_total": {"value": "5000.00"},
        "totals.subtotal": {"value": None},
        "totals.total_tax": {"value": None},
        "line_items": [],
    }
    res_1 = reconcile_npo_totals(fields_missing_both)
    assert res_1.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert res_1.is_valid is True
    assert "not checkable" in res_1.message.lower()
    assert validate_poi_npo_amounts(fields_missing_both, "NPO") == []

    # Case 2: only subtotal is present, total_tax is None
    fields_missing_tax = {
        "totals.grand_total": {"value": "5000.00"},
        "totals.subtotal": {"value": "4500.00"},
        "totals.total_tax": {"value": None},
    }
    res_2 = reconcile_npo_totals(fields_missing_tax)
    assert res_2.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert res_2.is_valid is True
    assert validate_poi_npo_amounts(fields_missing_tax, "NPO") == []

    # Case 3: only grand_total is missing
    fields_missing_total = {
        "totals.grand_total": {"value": None},
        "totals.subtotal": {"value": "4500.00"},
        "totals.total_tax": {"value": "500.00"},
    }
    res_3 = reconcile_npo_totals(fields_missing_total)
    assert res_3.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert res_3.is_valid is True
    assert validate_poi_npo_amounts(fields_missing_total, "NPO") == []


def test_10d_document_totals_with_charges_discounts_and_rounding():
    """Requirement 10d: Document-level reconciliation incorporates discount/shipping/charges/rounding."""
    fields = {
        "totals.grand_total": {"value": "5395.00"},
        "totals.subtotal": {"value": "5000.00"},
        "totals.total_tax": {"value": "500.00"},
        "totals.discount": {"value": "200.00"},
        "totals.shipping": {"value": "100.00"},
        "totals.other_charges": {"value": "0.00"},
        "totals.rounding": {"value": "-5.00"},
        "line_items": [],
    }
    # 5000 + 500 - 200 + 100 + 0 - 5 = 5395
    doc_res = reconcile_npo_totals(fields)
    assert doc_res.status == ArithmeticReconciliationStatus.VALID
    assert doc_res.is_valid is True
    assert validate_poi_npo_amounts(fields, "NPO") == []



# =====================================================================
# 11. Missing invoice_number -> mandatory-field validation issue
# =====================================================================

def test_11_missing_invoice_number_generates_error():
    """Requirement 11: Missing invoice_number is a true mandatory failure."""
    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["invoice_number"] = {"value": None}
    issues_flat = validate_required_fields(flat, "NPO")
    assert len(issues_flat) == 1
    assert issues_flat[0].field_key == "invoice_number"
    assert issues_flat[0].severity == ValidationSeverity.ERROR
    assert issues_flat[0].rule_type == ValidationRuleType.REQUIRED_FIELD

    # Canonical representation
    canonical = _base_valid_npo_canonical_fields()
    canonical["invoice_information.invoice_number"] = {"value": None}
    issues_canon = validate_required_fields(canonical, "NPO")
    assert len(issues_canon) == 1
    assert issues_canon[0].field_key == "invoice_information.invoice_number"
    assert issues_canon[0].severity == ValidationSeverity.ERROR


# =====================================================================
# 12. Missing grand_total -> mandatory-field validation issue
# =====================================================================

def test_12_missing_grand_total_generates_error():
    """Requirement 12: Missing grand_total is a true mandatory failure."""
    # Flat representation
    flat = _base_valid_npo_flat_fields()
    flat["grand_total_amount"] = {"value": None}
    issues_flat = validate_required_fields(flat, "NPO")
    assert len(issues_flat) == 1
    assert issues_flat[0].field_key == "grand_total_amount"
    assert issues_flat[0].severity == ValidationSeverity.ERROR

    # Canonical representation
    canonical = _base_valid_npo_canonical_fields()
    canonical["totals.grand_total"] = {"value": None}
    issues_canon = validate_required_fields(canonical, "NPO")
    assert len(issues_canon) == 1
    assert issues_canon[0].field_key == "totals.grand_total"
    assert issues_canon[0].severity == ValidationSeverity.ERROR


# =====================================================================
# Additional: Missing other mandatory fields (seller.name, buyer.name, currency, invoice_date)
# =====================================================================

def test_other_mandatory_core_failures():
    """Verify that seller.name, buyer.name, currency, and invoice_date also generate errors when missing."""
    for field_key in ("seller_name", "buyer_name", "currency", "invoice_date"):
        fields = _base_valid_npo_flat_fields()
        fields[field_key] = {"value": None}
        issues = validate_required_fields(fields, "NPO")
        assert any(i.field_key == field_key for i in issues), f"Expected missing issue for {field_key}"


def test_optional_fields_do_not_fail_when_absent():
    """Verify that no optional field generates an error when absent."""
    optional_keys = [
        "seller_tax_id",
        "seller_address",
        "buyer_tax_id",
        "buyer_address",
        "subtotal_net_amount",
        "total_tax_amount",
        "tax_rate",
        "payment_terms",
        "due_date",
        "po_number",
        "contract_number",
        "vendor_code",
    ]
    for opt_key in optional_keys:
        fields = _base_valid_npo_flat_fields()
        fields[opt_key] = {"value": None}
        issues = validate_required_fields(fields, "NPO")
        assert issues == [], f"Optional field '{opt_key}' caused false mandatory failure!"
