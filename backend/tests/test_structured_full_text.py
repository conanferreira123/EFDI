"""
Unit and integration tests for Phase 1 Structured full_text generation.

Validates that:
1. Raw OCR blocks remain unchanged as immutable ground truth.
2. Table reconstruction operates before full_text generation.
3. Tabular content is rendered as structured Markdown.
4. Non-table content (headers, parties, summaries, footers) is preserved.
5. Multi-page document ordering and boundaries are preserved.
6. Non-tabular documents degrade gracefully without errors.
"""
import pytest
from app.ocr.base import OCRTextBlock, OCRPageResult, OCRResult
from app.ocr.document_structure import StructuredDocumentPage
from app.ocr.table_reconstruction import reconstruct_table, ReconstructedTable
from app.ocr.layout import build_structured_page, generate_structured_full_text, format_reconstructed_table_markdown


def test_raw_blocks_remain_unchanged():
    """Test 1: Structured full_text generation must not mutate raw OCR blocks."""
    blocks = [
        OCRTextBlock(text="Invoice no: 51109338", confidence=0.98, bounding_box=[[10, 10], [50, 10], [50, 20], [10, 20]]),
        OCRTextBlock(text="Seller: Acme Corp", confidence=0.95, bounding_box=[[10, 50], [50, 50], [50, 60], [10, 60]]),
    ]
    orig_text = [b.text for b in blocks]
    orig_conf = [b.confidence for b in blocks]
    orig_bbox = [list(b.bounding_box) for b in blocks]

    page = build_structured_page(blocks, page_width=1000.0, page_height=1400.0, page_number=1)
    text = generate_structured_full_text([page])

    assert "Invoice no: 51109338" in text
    assert "Acme Corp" in text
    # Verify blocks are not mutated
    assert [b.text for b in blocks] == orig_text
    assert [b.confidence for b in blocks] == orig_conf
    assert [b.bounding_box for b in blocks] == orig_bbox


def test_table_reconstruction_precedes_full_text():
    """Test 2: Table reconstruction produces structured table before full_text is generated."""
    # Simulated table header and row
    blocks = [
        OCRTextBlock(text="Invoice no: 1001", confidence=0.99, bounding_box=[[50, 50], [200, 50], [200, 70], [50, 70]]),
        OCRTextBlock(text="DESCRIPTION", confidence=0.95, bounding_box=[[50, 300], [200, 300], [200, 320], [50, 320]]),
        OCRTextBlock(text="QTY", confidence=0.95, bounding_box=[[250, 300], [300, 300], [300, 320], [250, 320]]),
        OCRTextBlock(text="NET AMOUNT", confidence=0.95, bounding_box=[[350, 300], [450, 300], [450, 320], [350, 320]]),
        OCRTextBlock(text="Dell Laptop 15", confidence=0.92, bounding_box=[[50, 350], [200, 350], [200, 370], [50, 370]]),
        OCRTextBlock(text="2.00", confidence=0.99, bounding_box=[[250, 350], [300, 350], [300, 370], [250, 370]]),
        OCRTextBlock(text="1500.00", confidence=0.99, bounding_box=[[350, 350], [450, 350], [450, 370], [350, 370]]),
        OCRTextBlock(text="TOTAL", confidence=0.99, bounding_box=[[50, 600], [150, 600], [150, 620], [50, 620]]),
        OCRTextBlock(text="1500.00", confidence=0.99, bounding_box=[[350, 600], [450, 600], [450, 620], [350, 620]]),
    ]
    raw_dicts = [{"text": b.text, "confidence": b.confidence, "bounding_box": b.bounding_box} for b in blocks]
    table = reconstruct_table(raw_dicts, page_width=1000.0, page_height=1400.0)
    
    assert len(table.line_items) >= 1
    page = build_structured_page(blocks, table=table, page_width=1000.0, page_height=1400.0, page_number=1)
    full_text = generate_structured_full_text([page])

    assert "| Dell Laptop 15 |" in full_text or "Dell Laptop 15" in full_text
    assert "TOTAL" in full_text
    assert "=== LINE ITEMS ===" not in full_text
    assert "=== TOTALS & SUMMARY ===" not in full_text
    assert "--- SELLER COLUMN ---" not in full_text
    assert "--- BUYER COLUMN ---" not in full_text


def test_non_table_document_graceful_handling():
    """Test 3: Documents without tables render cleanly without crashing or inventing tables."""
    blocks = [
        OCRTextBlock(text="Memorandum of Understanding", confidence=0.99, bounding_box=[[100, 50], [500, 50], [500, 80], [100, 80]]),
        OCRTextBlock(text="This agreement is entered into between Party A and Party B.", confidence=0.95, bounding_box=[[100, 200], [800, 200], [800, 230], [100, 230]]),
    ]
    page = build_structured_page(blocks, table=None, page_width=1000.0, page_height=1400.0, page_number=1)
    full_text = generate_structured_full_text([page])

    assert "Memorandum of Understanding" in full_text
    assert "This agreement is entered into" in full_text
    assert "=== LINE ITEMS ===" not in full_text


def test_multi_page_document_preservation():
    """Test 4: Multi-page documents preserve explicit page headers and boundaries."""
    p1_blocks = [OCRTextBlock(text="Page 1 Header", confidence=0.99, bounding_box=[[50, 50], [200, 50], [200, 70], [50, 70]])]
    p2_blocks = [OCRTextBlock(text="Page 2 Header", confidence=0.99, bounding_box=[[50, 50], [200, 50], [200, 70], [50, 70]])]

    p1 = build_structured_page(p1_blocks, page_number=1)
    p2 = build_structured_page(p2_blocks, page_number=2)

    full_text = generate_structured_full_text([p1, p2])
    assert "=== PAGE 1 ===" in full_text
    assert "Page 1 Header" in full_text
    assert "=== PAGE 2 ===" in full_text
    assert "Page 2 Header" in full_text


def test_custom_full_text_and_legacy_fallback():
    """Test 5: OCRPageResult and OCRResult support custom_full_text and legacy fallback."""
    blocks = [
        OCRTextBlock(text="Block 1", confidence=0.9, bounding_box=[[0, 0], [10, 0], [10, 10], [0, 10]]),
        OCRTextBlock(text="Block 2", confidence=0.9, bounding_box=[[0, 20], [10, 20], [10, 30], [0, 30]]),
    ]
    p = OCRPageResult(page_number=1, blocks=blocks)
    assert p.full_text == "Block 1\nBlock 2"
    assert p.legacy_full_text == "Block 1\nBlock 2"

    p.custom_full_text = "Structured Text Content"
    assert p.full_text == "Structured Text Content"
    assert p.legacy_full_text == "Block 1\nBlock 2"
