"""
Unit tests for Phase 3: Table Reconstruction Quality.
Tests structural correctness, non-overlapping column intervals, cell assignment,
split token stitching, multiline descriptions, and raw evidence provenance.
"""
import pytest
from app.ocr.base import OCRTextBlock
from app.ocr.table_reconstruction import (
    TableReconstructor,
    StructuredLineItem,
    ReconstructedTable,
    reconstruct_table,
)


def _make_block(text: str, x0: float, y0: float, x1: float, y1: float, conf: float = 0.95) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        confidence=conf,
        bounding_box=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    )


def test_adjacent_vat_and_gross_columns_remain_separate():
    """
    Test A: Verify that adjacent VAT (1090) and Gross (689,70) columns
    are cleanly assigned to their respective columns and NOT merged.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 400, 320),
        _make_block("Qty", 420, 300, 480, 320),
        _make_block("Net price", 500, 300, 600, 320),
        _make_block("Net worth", 620, 300, 720, 320),
        _make_block("VAT [%]", 740, 300, 820, 320),
        _make_block("Gross worth", 840, 300, 960, 320),
    ]

    # Row with raw OCR producing "1090" in VAT column and "689,70" in Gross column
    row1 = [
        _make_block("Dell Optiplex Computer", 100, 350, 400, 370),
        _make_block("3,00", 420, 350, 480, 370),
        _make_block("209,00", 500, 350, 600, 370),
        _make_block("627,00", 620, 350, 720, 370),
        _make_block("1090", 740, 350, 820, 370),
        _make_block("689,70", 840, 350, 960, 370),
    ]

    result = reconstruct_table(headers + row1, page_w, page_h)

    assert len(result.line_items) == 1
    item = result.line_items[0]
    assert item.description == "Dell Optiplex Computer"
    assert item.quantity == "3,00"
    assert item.unit_price == "209,00"
    assert item.net_amount == "627,00"
    # VAT column must contain exactly the raw OCR string "1090" without merging with gross amount
    assert item.vat_rate == "1090"
    # Gross amount must contain "689,70" and NOT "1090 689,70"
    assert item.gross_amount == "689,70"


def test_split_numeric_token_stitching():
    """
    Test B: Verify that split European number tokens (e.g. '1' + '394,67' -> '1 394,67')
    in the same column cell are stitched cleanly with space preservation.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 450, 320),
        _make_block("Net Amount", 500, 300, 700, 320),
        _make_block("Gross Amount", 750, 300, 950, 320),
    ]

    # Row where Net Amount is split into "1" and "394,67" within the Net Amount column (500-700)
    row = [
        _make_block("Gaming PC Tower", 100, 350, 450, 370),
        _make_block("1", 520, 350, 540, 370),
        _make_block("394,67", 550, 350, 680, 370),
        _make_block("1", 770, 350, 790, 370),
        _make_block("534,14", 800, 350, 930, 370),
    ]

    result = reconstruct_table(headers + row, page_w, page_h)

    assert len(result.line_items) == 1
    item = result.line_items[0]
    assert item.description == "Gaming PC Tower"
    assert item.net_amount == "1 394,67"
    assert item.gross_amount == "1 534,14"


def test_multiline_description_retention():
    """
    Test C: Verify that secondary and tertiary description lines
    remain inside the description column and do not spill into adjacent columns.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 500, 320),
        _make_block("Qty", 520, 300, 600, 320),
        _make_block("Amount", 700, 300, 900, 320),
    ]

    # Primary line with numeric values
    line1 = [
        _make_block("Custom Build Dell Optiplex 9020", 100, 350, 500, 370),
        _make_block("5.00", 520, 350, 600, 370),
        _make_block("1 109,95", 700, 350, 900, 370),
    ]
    # Continuation lines for item 1
    line2 = [_make_block("MT i5-4570 20GHz Desktop", 100, 375, 450, 395)]
    line3 = [_make_block("Computer PC Windows 10 Pro", 100, 400, 480, 420)]

    result = reconstruct_table(headers + line1 + line2 + line3, page_w, page_h)

    assert len(result.line_items) == 1
    item = result.line_items[0]
    expected_desc = "Custom Build Dell Optiplex 9020 MT i5-4570 20GHz Desktop Computer PC Windows 10 Pro"
    assert item.description == expected_desc
    assert item.quantity == "5.00"
    assert item.net_amount == "1 109,95"


def test_row_clustering_with_vertical_jitter():
    """
    Test D: Verify that vertical coordinate jitter within the same row
    does not cause the row to be split into multiple line items.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 500, 320),
        _make_block("Qty", 520, 300, 600, 320),
        _make_block("Price", 650, 300, 780, 320),
        _make_block("Total", 800, 300, 950, 320),
    ]

    # Blocks on the same row with varying Y coordinates (Y ranges 345 to 362)
    row_jitter = [
        _make_block("HP LaserJet Pro Printer", 100, 345, 500, 368),
        _make_block("1.00", 520, 352, 600, 370),
        _make_block("15,000.00", 650, 348, 780, 366),
        _make_block("15,000.00", 800, 355, 950, 372),
    ]

    result = reconstruct_table(headers + row_jitter, page_w, page_h)
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "HP LaserJet Pro Printer"
    assert result.line_items[0].quantity == "1.00"
    assert result.line_items[0].unit_price == "15,000.00"
    assert result.line_items[0].gross_amount == "15,000.00"


def test_header_and_totals_exclusion():
    """
    Test E & F: Verify that table header tokens and summary totals
    are strictly excluded from the line_items list.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("ITEMS", 100, 280, 200, 300),
        _make_block("Description", 100, 305, 450, 325),
        _make_block("Qty", 500, 305, 550, 325),
        _make_block("Amount", 600, 305, 750, 325),
    ]

    item1 = [
        _make_block("Office Desk Chair", 100, 360, 450, 380),
        _make_block("2", 500, 360, 550, 380),
        _make_block("500.00", 600, 360, 750, 380),
    ]

    totals = [
        _make_block("SUMMARY", 100, 450, 250, 470),
        _make_block("Subtotal", 100, 480, 250, 500),
        _make_block("500.00", 600, 480, 750, 500),
        _make_block("Grand Total", 100, 510, 250, 530),
        _make_block("500.00", 600, 510, 750, 530),
    ]

    result = reconstruct_table(headers + item1 + totals, page_w, page_h)

    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Office Desk Chair"
    assert result.summary_blocks_count >= 1
    # Check that summary keywords were not ingested as line items
    for it in result.line_items:
        assert "SUMMARY" not in it.description
        assert "Grand Total" not in it.description


def test_raw_ocr_evidence_provenance_preserved():
    """
    Test I: Verify that raw OCR blocks are preserved in StructuredLineItem.raw_blocks
    with polygon coordinates and confidence scores intact.
    """
    page_w = 1000.0
    page_h = 1400.0

    headers = [
        _make_block("Description", 100, 300, 500, 320),
        _make_block("Amount", 600, 300, 800, 320),
    ]
    raw_desc = _make_block("Server Maintenance", 100, 350, 500, 370, conf=0.98)
    raw_amt = _make_block("25,000.00", 600, 350, 800, 370, conf=0.99)

    result = reconstruct_table(headers + [raw_desc, raw_amt], page_w, page_h)

    assert len(result.line_items) == 1
    item = result.line_items[0]
    assert len(item.raw_blocks) == 2
    assert any(b["text"] == "Server Maintenance" for b in item.raw_blocks)
    assert any(b["text"] == "25,000.00" for b in item.raw_blocks)
    # Verify raw bounding box exists
    assert "bounding_box" in item.raw_blocks[0]
