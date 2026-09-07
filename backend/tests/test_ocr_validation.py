"""
Unit tests for explicit OCR validation engine (Phase 3).
"""
import pytest
from app.ocr.normalization import NormalizedLineItem
from app.ocr.validation import (
    OCRValidator,
    ValidationSeverity,
    validate_ocr_output,
    DocumentValidationResult
)


def test_line_item_math_validation_success():
    item = NormalizedLineItem(
        normalized_description="Widget Pro",
        normalized_quantity=2.0,
        normalized_unit_price=50.0,
        normalized_net_amount=100.0,
        normalized_vat_rate=0.10,
        normalized_gross_amount=110.0,
    )
    validator = OCRValidator()
    flags = validator.validate_line_item(item, item_idx=1)

    assert all(f.is_valid for f in flags)
    assert len(flags) == 2  # Qty*Price check + Net+VAT check


def test_line_item_math_validation_mismatch_flags_warning():
    # Intentionally unbalanced math: 2 * 50 = 100, but net is reported as 150
    item = NormalizedLineItem(
        normalized_description="Widget Pro",
        normalized_quantity=2.0,
        normalized_unit_price=50.0,
        normalized_net_amount=150.0,  # Mismatch!
        normalized_vat_rate=0.10,
        normalized_gross_amount=165.0,
    )
    validator = OCRValidator()
    flags = validator.validate_line_item(item, item_idx=1)

    qty_price_flag = next(f for f in flags if "MATH_QTY_PRICE" in f.rule_id)
    assert not qty_price_flag.is_valid
    assert qty_price_flag.severity == ValidationSeverity.WARNING
    assert qty_price_flag.expected_value == 100.0
    assert qty_price_flag.actual_value == 150.0


def test_document_validation_totals_and_headers():
    item1 = NormalizedLineItem(
        normalized_description="Item 1",
        normalized_quantity=1.0,
        normalized_unit_price=100.0,
        normalized_net_amount=100.0,
        normalized_vat_rate=0.10,
        normalized_gross_amount=110.0,
    )
    item2 = NormalizedLineItem(
        normalized_description="Item 2",
        normalized_quantity=2.0,
        normalized_unit_price=200.0,
        normalized_net_amount=400.0,
        normalized_vat_rate=0.10,
        normalized_gross_amount=440.0,
    )

    full_text = "Invoice no: 12345\nDate of issue: 01/01/2024\nSeller: Acme Ltd\nClient: Global Corp"
    summary_data = {
        "subtotal": 500.0,
        "vat_total": 50.0,
        "grand_total": 550.0,
    }

    res = validate_ocr_output([item1, item2], raw_full_text=full_text, summary_data=summary_data)
    assert res.is_valid
    assert res.failed_rules_count == 0
    assert res.passed_rules_count >= 8
