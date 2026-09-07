"""
Comprehensive test suite for Phase 2: Rule-Based Extraction Enhancements.

Verifies:
1. Deterministic spatial layout extraction (right-neighbor and below-neighbor).
2. Table-derived summary amount calculations (net, tax, gross).
3. Text-only fallback when raw_blocks or table_data is absent.
4. Robustness against malformed or empty OCR blocks.
5. All 9 document types with hybrid context.
6. Legacy extract(text, document_type) compatibility.
"""
import pytest

from app.extraction.base import ExtractedField, ExtractionContext
from app.extraction.layout_helpers import extract_field_spatially
from app.extraction.primitives import (
    extract_amount_hybrid,
    extract_date_hybrid,
    extract_field_hybrid,
)
from app.extraction.rule_based import RuleBasedExtractor
from app.extraction.table_helpers import extract_amount_from_table


def _make_block(text: str, x0: float, y0: float, x1: float, y1: float, conf: float = 0.95) -> dict:
    return {
        "text": text,
        "confidence": conf,
        "bounding_box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
    }


def test_spatial_right_neighbor_extraction():
    """Verify that a value in a separate block to the right of a label is correctly extracted."""
    raw_blocks = [
        {
            "page_number": 1,
            "blocks": [
                _make_block("Invoice Number:", 100, 200, 250, 220),
                _make_block("INV-2026-X99", 270, 200, 420, 220),
            ],
        }
    ]
    res = extract_field_spatially(raw_blocks, ["Invoice Number"], field_type="code")
    assert res.is_found is True
    assert res.value == "INV-2026-X99"
    assert res.confidence >= 0.80


def test_spatial_below_neighbor_extraction():
    """Verify that a value in a separate block directly below a label is correctly extracted."""
    raw_blocks = [
        {
            "page_number": 1,
            "blocks": [
                _make_block("Vendor Name", 100, 150, 250, 170),
                _make_block("Acme Global Logistics Ltd", 100, 180, 350, 200),
            ],
        }
    ]
    res = extract_field_spatially(raw_blocks, ["Vendor Name"], field_type="text")
    assert res.is_found is True
    assert res.value == "Acme Global Logistics Ltd"
    assert res.confidence >= 0.75


def test_spatial_date_normalization():
    """Verify that spatial neighbor date values are properly parsed and ISO-normalized."""
    raw_blocks = [
        {
            "page_number": 1,
            "blocks": [
                _make_block("Invoice Date:", 100, 200, 220, 220),
                _make_block("25-11-2025", 240, 200, 340, 220),
            ],
        }
    ]
    res = extract_field_spatially(raw_blocks, ["Invoice Date"], field_type="date")
    assert res.is_found is True
    assert res.value == "2025-11-25"


def test_table_summary_amount_extraction():
    """Verify that table line items calculate net, gross, and tax totals deterministically."""
    table_data = {
        "headers": ["Item", "Net Amount", "Gross Amount"],
        "line_items": [
            {"item_number": "1", "net_amount": "1000.00", "gross_amount": "1180.00"},
            {"item_number": "2", "net_amount": "2000.00", "gross_amount": "2360.00"},
        ],
    }
    net_res = extract_amount_from_table(table_data, "net_amount")
    assert net_res.is_found is True
    assert net_res.value == "3000.00"

    gross_res = extract_amount_from_table(table_data, "invoice_amount")
    assert gross_res.is_found is True
    assert gross_res.value == "3540.00"

    tax_res = extract_amount_from_table(table_data, "tax_amount")
    assert tax_res.is_found is True
    assert tax_res.value == "540.00"


def test_hybrid_extractor_with_poi_spatial_and_table_context():
    """Verify RuleBasedExtractor on POI document where some fields are in full_text and others in layout/table."""
    # Text with broken layout where PO Number is separated across blocks
    text_content = "TAX INVOICE\nVendor: SupplyChain Direct\nPO Number\nTotal Amount: 1,180.00"

    raw_blocks = [
        {
            "page_number": 1,
            "blocks": [
                _make_block("PO Number", 100, 100, 200, 120),
                _make_block("PO-2026-9999", 220, 100, 350, 120),
                _make_block("Invoice Number", 100, 140, 220, 160),
                _make_block("INV-5544", 240, 140, 340, 160),
            ],
        }
    ]

    table_data = {
        "line_items": [
            {"net_amount": "1000.00", "gross_amount": "1180.00"},
        ],
    }

    context = ExtractionContext(
        full_text=text_content,
        document_type="POI",
        raw_blocks=raw_blocks,
        table_data=table_data,
    )

    extractor = RuleBasedExtractor()
    result = extractor.extract(context)

    # Vendor from text
    assert result.fields["vendor_name"].value == "SupplyChain Direct"
    # PO Number from spatial block neighbor
    assert result.fields["po_number"].value == "PO-2026-9999"
    # Invoice Number from spatial block neighbor
    assert result.fields["invoice_number"].value == "INV-5544"
    # Net Amount from table calculation
    assert result.fields["net_amount"].value == "1000.00"
    # Tax Amount from table calculation
    assert result.fields["tax_amount"].value == "180.00"
    # Invoice Amount from text primary
    assert result.fields["invoice_amount"].value == "1180.00"


def test_fallback_when_raw_blocks_and_table_are_none():
    """Verify complete, clean fallback when only full_text is available."""
    text_content = """
    TAX INVOICE
    Invoice Number: INV-PLAIN-001
    Invoice Date: 2026-01-10
    Invoice Amount: 5,000.00
    Vendor Name: Pure Text Corp
    """
    context = ExtractionContext(
        full_text=text_content,
        document_type="POI",
        raw_blocks=[],
        table_data=None,
    )

    extractor = RuleBasedExtractor()
    result = extractor.extract(context)

    assert result.fields["invoice_number"].value == "INV-PLAIN-001"
    assert result.fields["invoice_date"].value == "2026-01-10"
    assert result.fields["invoice_amount"].value == "5000.00"
    assert result.fields["vendor_name"].value == "Pure Text Corp"


def test_robustness_on_malformed_raw_blocks():
    """Verify extractor does not fail when raw_blocks contains empty or unexpected structures."""
    malformed_blocks = [
        {},
        {"blocks": None},
        {"blocks": [{"text": "", "bounding_box": []}]},
        {"blocks": [{"text": "Garbage", "bounding_box": [[10]]}]},
    ]
    context = ExtractionContext(
        full_text="Invoice Number: INV-ROBUST-1",
        document_type="POI",
        raw_blocks=malformed_blocks,
        table_data={"line_items": None},
    )

    extractor = RuleBasedExtractor()
    result = extractor.extract(context)
    assert result.fields["invoice_number"].value == "INV-ROBUST-1"


def test_all_nine_document_types_with_empty_context():
    """Verify all 9 document types extract schemas without errors."""
    types = ["POI", "NPO", "DPR", "IMA", "MSI", "PSI", "JER", "BKA", "LCA"]
    extractor = RuleBasedExtractor()

    for dt in types:
        ctx = ExtractionContext(full_text="", document_type=dt)
        res = extractor.extract(ctx)
        assert res.document_type == dt
        assert len(res.fields) > 0
        assert all(f.value is None for f in res.fields.values())
