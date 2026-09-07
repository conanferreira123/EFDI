"""
Unit tests for 2D Bounding-Box Table Reconstruction Engine (Phase 2).
"""
import pytest
from app.ocr.base import OCRTextBlock
from app.ocr.table_reconstruction import (
    TableReconstructor,
    StructuredLineItem,
    ReconstructedTable,
    reconstruct_table
)


def _make_block(text: str, x0: float, y0: float, x1: float, y1: float, conf: float = 0.95) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        confidence=conf,
        bounding_box=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    )


def test_empty_and_no_header_blocks():
    """Test empty block list and documents without table headers."""
    assert reconstruct_table([]).line_items == []

    # Blocks without table headers
    random_blocks = [
        _make_block("Hello World", 50, 50, 200, 70),
        _make_block("Another line", 50, 80, 200, 100),
    ]
    res = reconstruct_table(random_blocks, 1000, 1400)
    assert res.line_items == []
    assert res.headers == []


def test_table_region_and_column_detection():
    """Test detecting table headers and deriving column boundaries."""
    page_w = 1000.0
    page_h = 1400.0

    # Header blocks at Y ~ 300
    headers = [
        _make_block("Description", 100, 300, 400, 320),
        _make_block("Qty", 450, 300, 500, 320),
        _make_block("Unit", 520, 300, 570, 320),
        _make_block("Unit Price", 600, 300, 700, 320),
        _make_block("Net Amount", 720, 300, 820, 320),
        _make_block("VAT %", 840, 300, 900, 320),
        _make_block("Gross Amount", 910, 300, 990, 320),
    ]

    # Row 1 at Y ~ 350
    row1 = [
        _make_block("Logitech MX Master 3S Mouse", 100, 350, 400, 370),
        _make_block("2.00", 450, 350, 500, 370),
        _make_block("pcs", 520, 350, 570, 370),
        _make_block("5,000.00", 600, 350, 700, 370),
        _make_block("10,000.00", 720, 350, 820, 370),
        _make_block("18%", 840, 350, 900, 370),
        _make_block("11,800.00", 910, 350, 990, 370),
    ]

    # Summary row at Y ~ 500
    summary = [
        _make_block("Total", 100, 500, 200, 520),
        _make_block("11,800.00", 910, 500, 990, 520),
    ]

    all_blocks = headers + row1 + summary
    result = reconstruct_table(all_blocks, page_w, page_h)

    assert "description" in result.headers
    assert "quantity" in result.headers
    assert "unit_price" in result.headers
    assert "net_amount" in result.headers
    assert "gross_amount" in result.headers
    assert len(result.line_items) == 1

    item = result.line_items[0]
    assert item.description == "Logitech MX Master 3S Mouse"
    assert item.quantity == "2.00"
    assert item.unit == "pcs"
    assert item.unit_price == "5,000.00"
    assert item.net_amount == "10,000.00"
    assert item.vat_rate == "18%"
    assert item.gross_amount == "11,800.00"


def test_multiline_description_merging():
    """Test that secondary description lines under the same item are merged cleanly."""
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 450, 320),
        _make_block("Qty", 500, 300, 550, 320),
        _make_block("Price", 600, 300, 700, 320),
        _make_block("Amount", 750, 300, 850, 320),
    ]

    # Item 1: 2-line description (Primary at Y=350, Continuation at Y=375)
    item1_line1 = [
        _make_block("Apple MacBook Air M2", 100, 350, 450, 370),
        _make_block("1.00", 500, 350, 550, 370),
        _make_block("99,000.00", 600, 350, 700, 370),
        _make_block("99,000.00", 750, 350, 850, 370),
    ]
    item1_line2 = [
        _make_block("16GB RAM 512GB SSD Space Gray", 100, 375, 450, 395),
    ]

    # Item 2: 1-line description at Y=415
    item2 = [
        _make_block("Magic Mouse USB-C", 100, 415, 450, 435),
        _make_block("2.00", 500, 415, 550, 435),
        _make_block("8,000.00", 600, 415, 700, 435),
        _make_block("16,000.00", 750, 415, 850, 435),
    ]

    result = reconstruct_table(headers + item1_line1 + item1_line2 + item2, page_w, page_h)

    assert len(result.line_items) == 2
    assert result.line_items[0].description == "Apple MacBook Air M2 16GB RAM 512GB SSD Space Gray"
    assert result.line_items[0].quantity == "1.00"
    assert result.line_items[1].description == "Magic Mouse USB-C"
    assert result.line_items[1].quantity == "2.00"


def test_totals_excluded_from_line_items():
    """Test that summary/totals rows are strictly excluded from line items."""
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 450, 320),
        _make_block("Qty", 500, 300, 550, 320),
        _make_block("Amount", 600, 300, 700, 320),
    ]
    item1 = [
        _make_block("Keyboard", 100, 350, 450, 370),
        _make_block("1.00", 500, 350, 550, 370),
        _make_block("1,000.00", 600, 350, 700, 370),
    ]
    summary_total = [
        _make_block("Grand Total", 100, 450, 250, 470),
        _make_block("1,000.00", 600, 450, 700, 470),
    ]

    result = reconstruct_table(headers + item1 + summary_total, page_w, page_h)

    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Keyboard"
    assert result.summary_blocks_count >= 1


def test_missing_optional_columns_handled_gracefully():
    """Test table with only Description and Net Amount (missing VAT, Unit, Item No)."""
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Particulars", 100, 300, 500, 320),
        _make_block("Amount", 600, 300, 800, 320),
    ]
    item1 = [
        _make_block("Consulting Services", 100, 350, 500, 370),
        _make_block("50,000.00", 600, 350, 800, 370),
    ]

    result = reconstruct_table(headers + item1, page_w, page_h)
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Consulting Services"
    assert result.line_items[0].net_amount == "50,000.00"
    assert result.line_items[0].quantity is None
    assert result.line_items[0].unit is None
