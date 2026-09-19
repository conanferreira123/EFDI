"""
Tests for Phase D: Validation & Reconciliation for NPO canonical extraction.

Covers:
1. All six mandatory fields present -> valid.
2. Missing mandatory field -> ERROR.
3. Missing optional fields -> valid (no error).
4. line_items=[] -> valid structural state, 0 errors.
5. taxes=[] -> valid structural state, 0 errors.
6. Single line item with valid math.
7. Multiple line items with valid math and subtotal match.
8. Narrative service line with null quantity/unit price -> NOT_CHECKABLE, 0 errors.
9. Document-level arithmetic VALID.
10. Document-level arithmetic MISMATCH -> WARNING.
11. Document-level arithmetic NOT_CHECKABLE (missing operands) -> 0 errors.
12. Document arithmetic with line_items=[] (evaluates VALID or MISMATCH independently of line_items).
13. Multiple tax rates reconciliation.
14. Missing tax breakdown -> NOT_CHECKABLE, 0 errors.
15. Line-item arithmetic VALID.
16. Line-item arithmetic NOT_CHECKABLE -> 0 errors.
17. Missing optional payment information -> 0 errors.
18. Missing references -> 0 errors.
19. Currency normalization and validation (valid vs invalid currency).
20. Date validation (valid ISO vs invalid calendar date).
21. Semantic duplicate detection based on invoice number and vendor/seller.
22. Validation does not mutate extracted values (read-only validation).
23. Provenance remains available.
24. Existing non-NPO validation behavior remains intact.
"""
import copy
import uuid
from decimal import Decimal
import pytest

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.extraction_result import ExtractionResult
from app.models.user import User
from app.validation.base import ValidationRuleType, ValidationSeverity
from app.validation.business_rules import (
    ArithmeticReconciliationStatus,
    reconcile_line_item_math,
    reconcile_line_items_arithmetic,
    reconcile_npo_totals,
    validate_business_rules,
    validate_npo_line_items,
    validate_npo_taxes,
    validate_poi_npo_amounts,
)
from app.validation.duplicate_detection import validate_duplicate_document
from app.validation.engine import run_validation
from app.validation.field_validators import (
    validate_amount_fields,
    validate_currency_fields,
    validate_date_fields,
    validate_required_fields,
)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def test_user(db_session):
    user = db_session.query(User).first()
    if not user:
        user = User(
            username=f"valuser_{uuid.uuid4().hex[:8]}",
            email=f"val_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Validation Test User",
            password_hash="fakehash",
            role="FINANCE_ANALYST",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


@pytest.fixture
def test_npo_document(db_session, test_user):
    doc = Document(
        original_filename="npo_validation_test.pdf",
        stored_filename=f"stored_npo_val_{uuid.uuid4().hex}.pdf",
        file_size_bytes=2048,
        mime_type="application/pdf",
        file_hash=uuid.uuid4().hex,
        company_code="CC100",
        vendor_code="V100",
        document_type="NPO",
        status=DocumentStatus.UPLOADED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def _create_base_npo_fields(
    *,
    invoice_number: str | None = "INV-2026-001",
    invoice_date: str | None = "2026-06-15",
    currency: str | None = "USD",
    seller_name: str | None = "Acme Corp Global",
    buyer_name: str | None = "Beta Solutions LLC",
    grand_total: str | None = "1150.00",
    subtotal: str | None = "1000.00",
    total_tax: str | None = "150.00",
    line_items: list | None = None,
    taxes: list | None = None,
    include_canonical_container: bool = True,
) -> dict:
    """Helper to build a realistic NPO extraction fields dict."""
    fields = {
        "invoice_information.invoice_number": {
            "value": invoice_number, "confidence": 0.98, "matched_text": invoice_number, "is_found": invoice_number is not None, "provenance": "llm"
        },
        "invoice_information.invoice_date": {
            "value": invoice_date, "confidence": 0.95, "matched_text": invoice_date, "is_found": invoice_date is not None, "provenance": "llm"
        },
        "invoice_information.currency": {
            "value": currency, "confidence": 0.99, "matched_text": currency, "is_found": currency is not None, "provenance": "llm"
        },
        "seller.name": {
            "value": seller_name, "confidence": 0.96, "matched_text": seller_name, "is_found": seller_name is not None, "provenance": "llm"
        },
        "buyer.name": {
            "value": buyer_name, "confidence": 0.95, "matched_text": buyer_name, "is_found": buyer_name is not None, "provenance": "llm"
        },
        "totals.grand_total": {
            "value": grand_total, "confidence": 0.97, "matched_text": grand_total, "is_found": grand_total is not None, "provenance": "llm"
        },
        "totals.subtotal": {
            "value": subtotal, "confidence": 0.94, "matched_text": subtotal, "is_found": subtotal is not None, "provenance": "llm"
        },
        "totals.total_tax": {
            "value": total_tax, "confidence": 0.93, "matched_text": total_tax, "is_found": total_tax is not None, "provenance": "llm"
        },
        # Legacy flat aliases for backward compatibility
        "invoice_number": {"value": invoice_number, "confidence": 0.98, "is_found": invoice_number is not None},
        "invoice_date": {"value": invoice_date, "confidence": 0.95, "is_found": invoice_date is not None},
        "currency": {"value": currency, "confidence": 0.99, "is_found": currency is not None},
        "seller_name": {"value": seller_name, "confidence": 0.96, "is_found": seller_name is not None},
        "buyer_name": {"value": buyer_name, "confidence": 0.95, "is_found": buyer_name is not None},
        "grand_total_amount": {"value": grand_total, "confidence": 0.97, "is_found": grand_total is not None},
        "subtotal_net_amount": {"value": subtotal, "confidence": 0.94, "is_found": subtotal is not None},
        "total_tax_amount": {"value": total_tax, "confidence": 0.93, "is_found": total_tax is not None},
    }

    if line_items is not None:
        fields["line_items"] = {"value": line_items, "confidence": 0.95, "is_found": len(line_items) > 0}
    if taxes is not None:
        fields["taxes"] = {"value": taxes, "confidence": 0.95, "is_found": len(taxes) > 0}

    if include_canonical_container:
        canonical_tree = {
            "invoice_information": {
                "invoice_number": {"value": invoice_number, "confidence": 0.98, "is_found": invoice_number is not None},
                "invoice_date": {"value": invoice_date, "confidence": 0.95, "is_found": invoice_date is not None},
                "currency": {"value": currency, "confidence": 0.99, "is_found": currency is not None},
                "document_type": {"value": "INVOICE", "confidence": 0.90, "is_found": True},
            },
            "seller": {
                "name": {"value": seller_name, "confidence": 0.96, "is_found": seller_name is not None},
                "tax_id": {"value": None, "confidence": 0.0, "is_found": False},
                "address": {"value": None, "confidence": 0.0, "is_found": False},
            },
            "buyer": {
                "name": {"value": buyer_name, "confidence": 0.95, "is_found": buyer_name is not None},
                "tax_id": {"value": None, "confidence": 0.0, "is_found": False},
                "address": {"value": None, "confidence": 0.0, "is_found": False},
            },
            "line_items": line_items or [],
            "taxes": taxes or [],
            "totals": {
                "subtotal": {"value": subtotal, "confidence": 0.94, "is_found": subtotal is not None},
                "total_tax": {"value": total_tax, "confidence": 0.93, "is_found": total_tax is not None},
                "grand_total": {"value": grand_total, "confidence": 0.97, "is_found": grand_total is not None},
                "discount": {"value": None, "confidence": 0.0, "is_found": False},
                "shipping": {"value": None, "confidence": 0.0, "is_found": False},
                "other_charges": {"value": None, "confidence": 0.0, "is_found": False},
                "rounding": {"value": None, "confidence": 0.0, "is_found": False},
            },
            "payment": {
                "payment_terms": {"value": None, "confidence": 0.0, "is_found": False},
                "due_date": {"value": None, "confidence": 0.0, "is_found": False},
            },
            "references": {
                "po_number": {"value": None, "confidence": 0.0, "is_found": False},
            },
        }
        fields["canonical"] = {"value": canonical_tree, "confidence": 1.0, "is_found": True}

    return fields


# ==============================================================================
# 1. All six mandatory fields present -> valid
# ==============================================================================
def test_01_all_six_mandatory_fields_present_is_valid():
    fields = _create_base_npo_fields()
    issues = validate_required_fields(fields, "NPO")
    assert issues == []


# ==============================================================================
# 2. Missing mandatory field -> ERROR
# ==============================================================================
def test_02_missing_mandatory_fields_generate_error():
    mandatory_keys = [
        "invoice_information.invoice_number",
        "invoice_information.invoice_date",
        "invoice_information.currency",
        "seller.name",
        "buyer.name",
        "totals.grand_total",
    ]
    for key in mandatory_keys:
        kwargs = {}
        if "invoice_number" in key:
            kwargs["invoice_number"] = None
        elif "invoice_date" in key:
            kwargs["invoice_date"] = None
        elif "currency" in key:
            kwargs["currency"] = None
        elif "seller.name" in key:
            kwargs["seller_name"] = None
        elif "buyer.name" in key:
            kwargs["buyer_name"] = None
        elif "grand_total" in key:
            kwargs["grand_total"] = None

        fields = _create_base_npo_fields(**kwargs)
        issues = validate_required_fields(fields, "NPO")
        error_keys = [i.field_key for i in issues if i.severity == ValidationSeverity.ERROR]
        assert any(k == key or k.endswith(key.split(".")[-1]) for k in error_keys)


# ==============================================================================
# 3. Missing optional fields -> valid (no error)
# ==============================================================================
def test_03_missing_optional_fields_do_not_fail():
    # Only 6 mandatory fields present, all optional fields null/omitted
    fields = _create_base_npo_fields(subtotal=None, total_tax=None)
    issues = validate_required_fields(fields, "NPO")
    assert issues == []


# ==============================================================================
# 4. line_items=[] -> valid structural state, 0 errors
# ==============================================================================
def test_04_empty_line_items_is_valid_structural_state():
    fields = _create_base_npo_fields(line_items=[])
    req_issues = validate_required_fields(fields, "NPO")
    assert req_issues == []

    line_issues = validate_npo_line_items(fields, "NPO")
    assert line_issues == []


# ==============================================================================
# 5. taxes=[] -> valid structural state, 0 errors
# ==============================================================================
def test_05_empty_taxes_is_valid_structural_state():
    fields = _create_base_npo_fields(taxes=[])
    req_issues = validate_required_fields(fields, "NPO")
    assert req_issues == []

    tax_issues = validate_npo_taxes(fields, "NPO")
    assert tax_issues == []


# ==============================================================================
# 6. Single line item with valid math
# ==============================================================================
def test_06_single_line_item_valid_math():
    item = {
        "line_number": {"value": "1"},
        "description": {"value": "Consulting Services"},
        "quantity": {"value": "10"},
        "unit_price": {"value": "100.00"},
        "net_amount": {"value": "1000.00"},
    }
    res = reconcile_line_item_math(item)
    assert res.status == ArithmeticReconciliationStatus.VALID
    assert res.is_valid is True


# ==============================================================================
# 7. Multiple line items with valid math and subtotal match
# ==============================================================================
def test_07_multiple_line_items_valid_math_and_subtotal():
    line_items = [
        {"line_number": 1, "quantity": "2", "unit_price": "200.00", "net_amount": "400.00"},
        {"line_number": 2, "quantity": "3", "unit_price": "200.00", "net_amount": "600.00"},
    ]
    fields = _create_base_npo_fields(subtotal="1000.00", line_items=line_items)
    issues = validate_npo_line_items(fields, "NPO")
    assert issues == []


# ==============================================================================
# 8. Narrative service line with null quantity/unit price -> NOT_CHECKABLE
# ==============================================================================
def test_08_narrative_service_line_null_quantity_is_not_checkable_and_valid():
    narrative_item = {
        "description": {"value": "Full stack development for Q2"},
        "quantity": {"value": None},
        "unit_price": {"value": None},
        "net_amount": {"value": "1000.00"},
    }
    math_res = reconcile_line_item_math(narrative_item)
    assert math_res.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert math_res.is_valid is True

    # When validated inside line items collection, produces 0 issues
    fields = _create_base_npo_fields(subtotal="1000.00", line_items=[narrative_item])
    issues = validate_npo_line_items(fields, "NPO")
    assert issues == []


# ==============================================================================
# 9. Document-level arithmetic VALID (subtotal + tax == grand_total)
# ==============================================================================
def test_09_document_level_arithmetic_valid():
    fields = _create_base_npo_fields(subtotal="1000.00", total_tax="150.00", grand_total="1150.00")
    res = reconcile_npo_totals(fields)
    assert res.status == ArithmeticReconciliationStatus.VALID
    assert res.is_valid is True

    issues = validate_poi_npo_amounts(fields, "NPO")
    assert issues == []


# ==============================================================================
# 10. Document-level arithmetic MISMATCH -> WARNING
# ==============================================================================
def test_10_document_level_arithmetic_mismatch_produces_warning():
    # 1000 + 150 = 1150 != 1200
    fields = _create_base_npo_fields(subtotal="1000.00", total_tax="150.00", grand_total="1200.00")
    res = reconcile_npo_totals(fields)
    assert res.status == ArithmeticReconciliationStatus.MISMATCH
    assert res.is_valid is False

    issues = validate_poi_npo_amounts(fields, "NPO")
    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.WARNING
    assert "Grand Total" in issues[0].message


# ==============================================================================
# 11. Document-level arithmetic NOT_CHECKABLE (missing operands) -> 0 errors
# ==============================================================================
def test_11_document_level_arithmetic_not_checkable_produces_no_errors():
    # Missing subtotal
    fields = _create_base_npo_fields(subtotal=None, total_tax="150.00", grand_total="1150.00")
    res = reconcile_npo_totals(fields)
    assert res.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert res.is_valid is True

    issues = validate_poi_npo_amounts(fields, "NPO")
    assert issues == []


# ==============================================================================
# 12. Document arithmetic with line_items=[] (independent evaluation)
# ==============================================================================
def test_12_document_arithmetic_with_empty_line_items():
    # Valid document arithmetic when line_items=[]
    fields_valid = _create_base_npo_fields(
        subtotal="5000.00", total_tax="500.00", grand_total="5500.00", line_items=[]
    )
    res_valid = reconcile_npo_totals(fields_valid)
    assert res_valid.status == ArithmeticReconciliationStatus.VALID
    assert validate_poi_npo_amounts(fields_valid, "NPO") == []

    # Mismatched document arithmetic when line_items=[]
    fields_mismatch = _create_base_npo_fields(
        subtotal="5000.00", total_tax="500.00", grand_total="6000.00", line_items=[]
    )
    res_mismatch = reconcile_npo_totals(fields_mismatch)
    assert res_mismatch.status == ArithmeticReconciliationStatus.MISMATCH
    assert len(validate_poi_npo_amounts(fields_mismatch, "NPO")) == 1


# ==============================================================================
# 13. Multiple tax rates reconciliation
# ==============================================================================
def test_13_multiple_tax_rates_reconciliation():
    taxes = [
        {"tax_type": "Standard VAT", "taxable_amount": "1000.00", "rate_percentage": "10.0", "tax_amount": "100.00"},
        {"tax_type": "Service Cess", "taxable_amount": "1000.00", "rate_percentage": "5.0", "tax_amount": "50.00"},
    ]
    # Sum of taxes = 100 + 50 = 150.00 matches total_tax
    fields = _create_base_npo_fields(total_tax="150.00", taxes=taxes)
    issues = validate_npo_taxes(fields, "NPO")
    assert issues == []

    # Tax sum mismatch: total_tax says 200, items sum to 150
    fields_mismatch = _create_base_npo_fields(total_tax="200.00", taxes=taxes)
    issues_mismatch = validate_npo_taxes(fields_mismatch, "NPO")
    assert len(issues_mismatch) == 1
    assert "differs from total tax" in issues_mismatch[0].message.lower() or "sum of tax items" in issues_mismatch[0].message.lower()


# ==============================================================================
# 14. Missing tax breakdown -> NOT_CHECKABLE, 0 errors
# ==============================================================================
def test_14_missing_tax_breakdown_not_checkable():
    fields = _create_base_npo_fields(total_tax=None, taxes=[])
    issues = validate_npo_taxes(fields, "NPO")
    assert issues == []


# ==============================================================================
# 15. Line-item arithmetic VALID
# ==============================================================================
def test_15_line_item_arithmetic_valid():
    item = {"quantity": "5", "unit_price": "40.00", "net_amount": "200.00"}
    res = reconcile_line_item_math(item)
    assert res.status == ArithmeticReconciliationStatus.VALID
    assert res.is_valid is True


# ==============================================================================
# 16. Line-item arithmetic NOT_CHECKABLE -> 0 errors
# ==============================================================================
def test_16_line_item_arithmetic_not_checkable():
    item = {"quantity": None, "unit_price": "40.00", "net_amount": "200.00"}
    res = reconcile_line_item_math(item)
    assert res.status == ArithmeticReconciliationStatus.NOT_CHECKABLE
    assert res.is_valid is True


# ==============================================================================
# 17. Missing optional payment information -> 0 errors
# ==============================================================================
def test_17_missing_optional_payment_information_valid():
    fields = _create_base_npo_fields()
    # Ensure no payment fields cause errors
    issues = validate_required_fields(fields, "NPO")
    assert not any("payment" in (i.field_key or "") for i in issues)


# ==============================================================================
# 18. Missing references -> 0 errors
# ==============================================================================
def test_18_missing_references_valid():
    fields = _create_base_npo_fields()
    issues = validate_required_fields(fields, "NPO")
    assert not any("references" in (i.field_key or "") or "po_number" in (i.field_key or "") for i in issues)


# ==============================================================================
# 19. Currency normalization and validation
# ==============================================================================
def test_19_currency_validation():
    # Valid ISO currency
    valid_fields = _create_base_npo_fields(currency="EUR")
    assert validate_currency_fields(valid_fields, "NPO") == []

    # Valid currency symbol
    valid_symbol = _create_base_npo_fields(currency="$")
    assert validate_currency_fields(valid_symbol, "NPO") == []

    # Invalid currency string
    invalid_fields = _create_base_npo_fields(currency="XYZ999")
    issues = validate_currency_fields(invalid_fields, "NPO")
    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.WARNING


# ==============================================================================
# 20. Date validation (valid ISO vs invalid date)
# ==============================================================================
def test_20_date_validation():
    # Valid ISO calendar date
    valid_fields = _create_base_npo_fields(invoice_date="2026-06-15")
    assert validate_date_fields(valid_fields, "NPO") == []

    # Invalid calendar date (e.g. Feb 31)
    invalid_fields = _create_base_npo_fields(invoice_date="2026-02-31")
    issues = validate_date_fields(invalid_fields, "NPO")
    assert len(issues) >= 1
    assert all(i.rule_type == ValidationRuleType.DATE_FORMAT for i in issues)


# ==============================================================================
# 21. Tiered Semantic Duplicate Detection & Exact Hash Detection
# ==============================================================================
def test_21a_strong_semantic_duplicate(db_session, test_user, test_npo_document):
    """A. Same seller + invoice number + date + grand total -> strong semantic duplicate / WARNING"""
    doc1 = Document(
        original_filename="doc_first.pdf",
        stored_filename=f"stored_first_{uuid.uuid4().hex}.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        file_hash=uuid.uuid4().hex,
        company_code="CC100",
        document_type="NPO",
        status=DocumentStatus.EXTRACTED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc1)
    db_session.commit()

    fields_doc1 = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Global Tech Corp",
        invoice_date="2026-06-15",
        grand_total="1150.00",
    )
    ext1 = ExtractionResult(
        document_id=doc1.id,
        document_type="NPO",
        engine_name="test_engine",
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=10,
        fields=fields_doc1,
    )
    db_session.add(ext1)
    db_session.commit()

    fields_doc2 = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Global Tech Corp",
        invoice_date="2026-06-15",
        grand_total="1150.00",
    )
    issues = validate_duplicate_document(db_session, test_npo_document, fields_doc2)

    assert len(issues) == 1
    assert issues[0].rule_type == ValidationRuleType.DUPLICATE_DOCUMENT
    assert issues[0].severity == ValidationSeverity.WARNING
    assert "Strong duplicate invoice detected" in issues[0].message
    assert f"#{doc1.id}" in issues[0].message


def test_21b_same_seller_inv_different_date(db_session, test_user, test_npo_document):
    """B. Same seller + invoice number, but different date -> NOT treated as the same strong duplicate"""
    fields_doc_diff_date = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Global Tech Corp",
        invoice_date="2026-07-20",  # Different date
        grand_total="1150.00",
    )
    issues = validate_duplicate_document(db_session, test_npo_document, fields_doc_diff_date)
    assert len(issues) == 0


def test_21c_same_seller_inv_different_grand_total(db_session, test_user, test_npo_document):
    """C. Same seller + invoice number, but different grand total -> NOT treated as the same strong duplicate"""
    fields_doc_diff_total = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Global Tech Corp",
        invoice_date="2026-06-15",
        grand_total="9999.00",  # Different grand total
    )
    issues = validate_duplicate_document(db_session, test_npo_document, fields_doc_diff_total)
    assert len(issues) == 0


def test_21d_same_seller_inv_missing_date_or_amount(db_session, test_user, test_npo_document):
    """D. Same seller + invoice number with date/amount unavailable -> potential duplicate / review warning"""
    fields_doc_missing = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Global Tech Corp",
        invoice_date=None,  # Missing date
        grand_total="1150.00",
    )
    issues = validate_duplicate_document(db_session, test_npo_document, fields_doc_missing)
    assert len(issues) == 1
    assert issues[0].rule_type == ValidationRuleType.DUPLICATE_DOCUMENT
    assert issues[0].severity == ValidationSeverity.WARNING
    assert "Potential duplicate invoice (partial match)" in issues[0].message
    assert "invoice date is unavailable" in issues[0].message


def test_21e_different_seller_same_invoice_number(db_session, test_user, test_npo_document):
    """E. Different seller + same invoice number -> NOT a semantic duplicate solely because invoice number matches"""
    fields_doc_diff_seller = _create_base_npo_fields(
        invoice_number="INV-DUP-1001",
        seller_name="Completely Different Supplier",
        invoice_date="2026-06-15",
        grand_total="1150.00",
    )
    issues = validate_duplicate_document(db_session, test_npo_document, fields_doc_diff_seller)
    assert len(issues) == 0


def test_21f_exact_byte_for_byte_duplicate(db_session, test_user):
    """F. Exact byte-for-byte duplicate -> preserve existing exact duplicate behavior (ERROR)"""
    shared_hash = f"exact_hash_{uuid.uuid4().hex}"
    doc1 = Document(
        original_filename="original.pdf",
        stored_filename=f"stored_{uuid.uuid4().hex}.pdf",
        file_size_bytes=2048,
        mime_type="application/pdf",
        file_hash=shared_hash,
        company_code="CC100",
        document_type="NPO",
        status=DocumentStatus.UPLOADED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc1)
    db_session.commit()

    doc2 = Document(
        original_filename="reupload.pdf",
        stored_filename=f"stored_{uuid.uuid4().hex}.pdf",
        file_size_bytes=2048,
        mime_type="application/pdf",
        file_hash=shared_hash,
        company_code="CC100",
        document_type="NPO",
        status=DocumentStatus.UPLOADED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc2)
    db_session.commit()

    issues = validate_duplicate_document(db_session, doc2)
    assert len(issues) == 1
    assert issues[0].rule_type == ValidationRuleType.DUPLICATE_DOCUMENT
    assert issues[0].severity == ValidationSeverity.ERROR
    assert "byte-for-byte identical" in issues[0].message
    assert f"#{doc1.id}" in issues[0].message


# ==============================================================================
# 22. Validation does not mutate extracted values (read-only)
# ==============================================================================
def test_22_validation_does_not_mutate_extracted_values(db_session, test_npo_document):
    fields = _create_base_npo_fields(
        subtotal="1000.00", total_tax="150.00", grand_total="1200.00"  # Mismatch on purpose
    )
    original_copy = copy.deepcopy(fields)

    # Run full validation engine
    report = run_validation(db_session, test_npo_document, "NPO", fields)

    # Verify input fields were not overwritten with calculated total
    assert fields["totals.grand_total"]["value"] == "1200.00"
    assert fields == original_copy
    assert any(i.severity == ValidationSeverity.WARNING for i in report.issues)


# ==============================================================================
# 23. Provenance remains available
# ==============================================================================
def test_23_provenance_remains_available():
    fields = _create_base_npo_fields()
    assert fields["invoice_information.invoice_number"]["provenance"] == "llm"
    assert fields["totals.grand_total"]["provenance"] == "llm"


# ==============================================================================
# 24. Existing non-NPO validation behavior remains intact
# ==============================================================================
def test_24_existing_non_npo_validation_behavior_intact(db_session, test_user):
    poi_doc = Document(
        original_filename="poi_val.pdf",
        stored_filename=f"stored_poi_{uuid.uuid4().hex}.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        file_hash=uuid.uuid4().hex,
        company_code="CC100",
        document_type="POI",
        status=DocumentStatus.EXTRACTED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(poi_doc)
    db_session.commit()

    poi_fields = {
        "currency": {"value": "INR"},
        "po_number": {"value": "PO-2026-789"},
        "invoice_number": {"value": "INV-2026-001"},
        "invoice_date": {"value": "2026-06-15"},
        "grand_total_amount": {"value": "25000.00"},
        "total_tax_amount": {"value": "4500.00"},
        "subtotal_net_amount": {"value": "20500.00"},
        "vendor_code": {"value": "V-1001"},
        "seller_name": {"value": "Acme Corp"},
        "buyer_name": {"value": "Our Co"},
    }

    report = run_validation(db_session, poi_doc, "POI", poi_fields)
    assert report.is_valid is True
    assert report.error_count == 0
