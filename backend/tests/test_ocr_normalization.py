"""
Unit tests for non-destructive OCR normalization layer (Phase 3).
"""
import pytest
from app.ocr.normalization import (
    normalize_whitespace,
    normalize_unit,
    parse_numeric,
    parse_percentage,
    parse_date,
    normalize_line_item,
    normalize_table_data,
    NormalizedLineItem
)
from app.ocr.table_reconstruction import StructuredLineItem


def test_normalize_whitespace():
    assert normalize_whitespace("  hello   world  \t ") == "hello world"
    assert normalize_whitespace(None) == ""
    assert normalize_whitespace("") == ""


def test_normalize_unit():
    assert normalize_unit("pCs") == "pcs"
    assert normalize_unit("PCS") == "pcs"
    assert normalize_unit("PIECES") == "pcs"
    assert normalize_unit("kg") == "kg"
    assert normalize_unit("hours") == "hours"
    assert normalize_unit("box") == "box"
    assert normalize_unit(None) is None


def test_parse_numeric():
    assert parse_numeric("1,234.56") == 1234.56
    assert parse_numeric("74,120.00") == 74120.00
    assert parse_numeric("667.080.00") == 667080.00  # Multi-dot OCR error handled
    assert parse_numeric("9.00") == 9.00
    assert parse_numeric("INR 1,676,976.00") == 1676976.00
    assert parse_numeric("10%") == 10.0
    assert parse_numeric(None) is None
    assert parse_numeric("N/A") is None


def test_parse_percentage():
    assert parse_percentage("10%") == 0.10
    assert parse_percentage("18 %") == 0.18
    assert parse_percentage("5") == 0.05
    assert parse_percentage(None) is None


def test_parse_date():
    assert parse_date("03/07/2023") == "2023-07-03"
    assert parse_date("2023-07-03") == "2023-07-03"
    assert parse_date("03-07-2023") == "2023-07-03"
    assert parse_date("03.07.2023") == "2023-07-03"
    assert parse_date(None) is None


def test_normalize_line_item_preserves_raw_evidence():
    structured = StructuredLineItem(
        item_number="1.",
        description="Garmin Fenix 7 Solar Multisport GPS",
        quantity="9.00",
        unit="pcs",
        unit_price="74,120.00",
        net_amount="667.080.00",
        vat_rate="10%",
        gross_amount="733.788.00",
        confidence=0.875,
        raw_blocks=[{"text": "Garmin Fenix", "confidence": 0.9}]
    )

    norm = normalize_line_item(structured)

    # Normalized fields
    assert norm.normalized_item_number == 1
    assert norm.normalized_description == "Garmin Fenix 7 Solar Multisport GPS"
    assert norm.normalized_quantity == 9.0
    assert norm.normalized_unit == "pcs"
    assert norm.normalized_unit_price == 74120.0
    assert norm.normalized_net_amount == 667080.0
    assert norm.normalized_vat_rate == 0.10
    assert norm.normalized_gross_amount == 733788.0

    # Raw evidence must be preserved identically
    assert norm.raw_item_number == "1."
    assert norm.raw_unit_price == "74,120.00"
    assert norm.raw_net_amount == "667.080.00"
    assert norm.raw_vat_rate == "10%"
    assert norm.confidence == 0.875
    assert len(norm.raw_blocks) == 1
