"""
Unit tests for OCR quality scoring engine (Phase 3).
"""
import pytest
from app.ocr.quality_scoring import calculate_quality_score, OCRQualityScorer


def test_quality_score_excellent_document():
    full_text = "Invoice no: 51109301\nDate of issue: 03/07/2023\nSeller:\nAcme Ltd\nClient:\nBuyer Corp"
    table_data = {
        "headers": ["description", "quantity", "unit_price", "net_amount"],
        "line_items": [{"description": "Item 1", "quantity": "1.00"}],
    }
    validation_res = {
        "flags": [{"is_valid": True}, {"is_valid": True}, {"is_valid": True}]
    }

    breakdown = calculate_quality_score(
        avg_confidence=0.88,
        full_text=full_text,
        table_data=table_data,
        validation_result=validation_res,
    )

    assert breakdown.overall_quality_score >= 0.85
    assert breakdown.quality_grade == "EXCELLENT"
    assert breakdown.ocr_confidence_score == 0.88
    assert breakdown.structural_layout_score == 1.0


def test_quality_score_separates_ocr_confidence_from_structural_quality():
    # Low confidence OCR (e.g. 0.60), but perfect structure
    full_text = "Invoice no: 123\nDate: 01/01/2024\nSeller: A\nClient: B"
    table_data = {
        "headers": ["description", "quantity", "unit_price", "net_amount"],
        "line_items": [{"description": "Item 1"}],
    }
    validation_res = {"flags": [{"is_valid": True}]}

    breakdown = calculate_quality_score(
        avg_confidence=0.60,
        full_text=full_text,
        table_data=table_data,
        validation_result=validation_res,
    )

    # OCR confidence remains 0.60, but overall score reflects structure + validation
    assert breakdown.ocr_confidence_score == 0.60
    assert breakdown.overall_quality_score > breakdown.ocr_confidence_score
