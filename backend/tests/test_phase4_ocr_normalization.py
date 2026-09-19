"""
Unit tests for Phase 4: OCR / Normalization Quality.
Covers European number parsing, evidence-based VAT/percentage normalization,
ambiguous OCR glyph resolution, monetary differentiation, and raw provenance preservation.
"""
import pytest
from app.ocr.normalization import (
    parse_numeric,
    parse_percentage,
    interpret_vat_rate,
    normalize_line_item,
    normalize_table_data,
    NormalizedLineItem,
)
from app.ocr.table_reconstruction import StructuredLineItem


def test_european_number_with_space():
    """Test A: European number with space thousand separator ('1 394,67' -> 1394.67)."""
    assert parse_numeric("1 394,67") == 1394.67
    assert parse_numeric("1 109,95") == 1109.95
    assert parse_numeric("1 534,14") == 1534.14


def test_large_european_numbers():
    """Test B & C: Large European numbers ('5 640,17' -> 5640.17 and '6 204,19' -> 6204.19)."""
    assert parse_numeric("5 640,17") == 5640.17
    assert parse_numeric("$ 5 640,17") == 5640.17
    assert parse_numeric("6 204,19") == 6204.19
    assert parse_numeric("$ 6 204,19") == 6204.19


def test_european_decimal_comma():
    """Test D: European numbers with decimal comma ('689,70' -> 689.70, '3,00' -> 3.00, ',00' -> 0.0)."""
    assert parse_numeric("689,70") == 689.70
    assert parse_numeric("209,00") == 209.00
    assert parse_numeric("3,00") == 3.00
    assert parse_numeric(",00") == 0.00
    assert parse_numeric("1.394,67") == 1394.67


def test_percentage_normalization():
    """Test E & F: Standard percentage formats ('10%', '10 %', '10,0%', '18%')."""
    assert parse_percentage("10%") == 0.10
    assert parse_percentage("10 %") == 0.10
    assert parse_percentage("10,0%") == 0.10
    assert parse_percentage("18%") == 0.18
    assert parse_percentage("0%") == 0.00

    rate, interp, ev, conf = interpret_vat_rate("10%")
    assert rate == 0.10
    assert interp == "10%"
    assert conf == 1.0

    rate, interp, ev, conf = interpret_vat_rate("10 %")
    assert rate == 0.10
    assert interp == "10%"

    rate, interp, ev, conf = interpret_vat_rate("18%")
    assert rate == 0.18
    assert interp == "18%"

    rate, interp, ev, conf = interpret_vat_rate("0%")
    assert rate == 0.00
    assert interp == "0%"


def test_vat_ocr_ambiguity_preserves_raw_value():
    """
    Test G: When raw OCR is '1090' in VAT column, raw value remains '1090'
    and normalized interpretation is stored in distinct fields.
    """
    raw_item = StructuredLineItem(
        item_number="1",
        description="Fast Dell Desktop Computer",
        quantity="3,00",
        unit="each",
        unit_price="209,00",
        net_amount="627,00",
        vat_rate="1090",
        gross_amount="689,70",
    )

    norm_item = normalize_line_item(raw_item)

    # Raw OCR string must be 100% preserved
    assert norm_item.raw_vat_rate == "1090"
    # Reconciled normalized float
    assert norm_item.normalized_vat_rate == 0.10
    assert norm_item.vat_interpretation == "10%"
    assert norm_item.vat_normalization_confidence >= 0.95
    assert norm_item.vat_normalization_evidence is not None
    assert norm_item.vat_normalization_evidence["source"] == "financial_reconciliation"


def test_do_not_blindly_convert_1090_without_evidence():
    """
    Test H: An isolated '1090' without Net and Gross reconciliation evidence
    must NOT be converted to 10% (retains None for normalized value).
    """
    # Case with no Net / Gross amounts provided
    rate, interp, ev, conf = interpret_vat_rate("1090", net_amount=None, gross_amount=None)
    assert rate is None
    assert interp is None
    assert parse_percentage("1090") is None

    # Case where Net and Gross do NOT match a 10% rate (e.g. Net=500, Gross=500 -> 0% rate)
    rate, interp, ev, conf = interpret_vat_rate("1090", net_amount=500.0, gross_amount=500.0)
    assert rate is None
    assert interp is None
    assert parse_percentage("1090", net_amount=500.0, gross_amount=500.0) is None


def test_financially_supported_vat_interpretation():
    """
    Test I: Net = 627.00, Raw VAT = '1090', Gross = 689.70 satisfies
    mathematical reconciliation: 689.70 / 627.00 = 1.10 -> 10%.
    """
    assert parse_percentage("1090", net_amount=627.0, gross_amount=689.70) == 0.10
    rate, interp, ev, conf = interpret_vat_rate("1090", net_amount=627.0, gross_amount=689.70)
    assert rate == 0.10
    assert interp == "10%"
    assert conf >= 0.95
    assert ev["calculated_implied_rate"] == 0.10


def test_legitimate_monetary_1090_in_amount_column():
    """
    Test J: Verify that '1090' in a monetary column (Net Amount) parses to 1090.0
    and is NOT treated as a percentage.
    """
    raw_item = StructuredLineItem(
        description="Office Service",
        net_amount="1090",
        gross_amount="1090",
    )
    norm_item = normalize_line_item(raw_item)
    assert norm_item.raw_net_amount == "1090"
    assert norm_item.normalized_net_amount == 1090.0
    assert norm_item.raw_gross_amount == "1090"
    assert norm_item.normalized_gross_amount == 1090.0


def test_raw_evidence_provenance_intact():
    """
    Test K: Verify that normalization does not modify original OCR block bounding boxes,
    confidences, or raw text tokens.
    """
    raw_blocks = [
        {"text": "1090", "confidence": 0.85, "bounding_box": [[1550, 750], [1630, 750], [1630, 770], [1550, 770]]}
    ]
    raw_item = StructuredLineItem(
        description="Dell Desktop",
        net_amount="627,00",
        vat_rate="1090",
        gross_amount="689,70",
        raw_blocks=raw_blocks,
    )
    norm_item = normalize_line_item(raw_item)
    assert len(norm_item.raw_blocks) == 1
    assert norm_item.raw_blocks[0]["text"] == "1090"
    assert norm_item.raw_blocks[0]["confidence"] == 0.85
    assert norm_item.raw_blocks[0]["bounding_box"] == [[1550, 750], [1630, 750], [1630, 770], [1550, 770]]
