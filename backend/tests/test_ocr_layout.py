"""
Unit tests for OCR spatial layout analysis and reading order reconstruction (Phase 1).
"""
import pytest
from app.ocr.base import OCRTextBlock
from app.ocr.layout import order_blocks_spatially, _get_bbox_bounds
from app.ocr.easyocr_engine import EasyOCREngine
import inspect


def test_easyocr_engine_uses_add_margin_zero():
    """Verify that EasyOCREngine explicitly uses configured add_margin in its readtext call."""
    source = inspect.getsource(EasyOCREngine.extract_text_blocks)
    assert "add_margin=" in source, "EasyOCREngine must specify add_margin in readtext"


def test_get_bbox_bounds():
    """Test extracting min/max/center coordinates from polygon."""
    bbox = [[100.0, 200.0], [300.0, 200.0], [300.0, 250.0], [100.0, 250.0]]
    min_x, min_y, max_x, max_y, cx, cy = _get_bbox_bounds(bbox)
    assert min_x == 100.0
    assert max_x == 300.0
    assert min_y == 200.0
    assert max_y == 250.0
    assert cx == 200.0
    assert cy == 225.0


def test_order_blocks_empty_and_single():
    """Test empty list and single block edge cases."""
    assert order_blocks_spatially([]) == []
    
    single = OCRTextBlock(text="Single", confidence=0.99, bounding_box=[[10, 10], [50, 10], [50, 20], [10, 20]])
    assert order_blocks_spatially([single]) == [single]


def test_order_blocks_separates_seller_and_buyer_columns():
    """
    Test that side-by-side Seller and Buyer blocks sharing the same vertical Y-bands
    are properly separated into Seller-first, Buyer-second rather than interleaved.
    """
    page_w = 1000.0
    page_h = 1400.0

    # Top metadata
    b_inv = OCRTextBlock(text="Invoice no: 12345", confidence=0.99, bounding_box=[[50, 50], [250, 50], [250, 70], [50, 70]])
    b_date = OCRTextBlock(text="Date: 01/01/2024", confidence=0.99, bounding_box=[[50, 80], [200, 80], [200, 100], [50, 100]])

    # Left Column: Seller (X: 50..400)
    b_seller_hdr = OCRTextBlock(text="Seller:", confidence=0.95, bounding_box=[[50, 150], [120, 150], [120, 170], [50, 170]])
    b_seller_name = OCRTextBlock(text="Acme Supplies Ltd", confidence=0.95, bounding_box=[[50, 180], [300, 180], [300, 200], [50, 200]])
    b_seller_addr = OCRTextBlock(text="100 Factory Lane", confidence=0.95, bounding_box=[[50, 210], [280, 210], [280, 230], [50, 230]])

    # Right Column: Buyer / Client (X: 550..900) - same Y coordinates as Seller!
    b_buyer_hdr = OCRTextBlock(text="Client:", confidence=0.95, bounding_box=[[550, 150], [620, 150], [620, 170], [550, 170]])
    b_buyer_name = OCRTextBlock(text="Global Retail Corp", confidence=0.95, bounding_box=[[550, 180], [800, 180], [800, 200], [550, 200]])
    b_buyer_addr = OCRTextBlock(text="500 Market St", confidence=0.95, bounding_box=[[550, 210], [750, 210], [750, 230], [550, 230]])

    # Table section below
    b_items_hdr = OCRTextBlock(text="ITEMS", confidence=0.99, bounding_box=[[50, 350], [120, 350], [120, 370], [50, 370]])
    b_item1 = OCRTextBlock(text="Widget Pro", confidence=0.95, bounding_box=[[50, 400], [200, 400], [200, 420], [50, 420]])

    # Input: interleaved/random order
    input_blocks = [
        b_inv, b_seller_hdr, b_buyer_hdr, b_date,
        b_buyer_name, b_seller_name, b_items_hdr,
        b_seller_addr, b_buyer_addr, b_item1
    ]

    ordered = order_blocks_spatially(input_blocks, page_width=page_w, page_height=page_h)
    ordered_texts = [b.text for b in ordered]

    # Verify top metadata comes first
    assert ordered_texts[0] == "Invoice no: 12345"
    assert ordered_texts[1] == "Date: 01/01/2024"

    # Verify all Seller blocks come together BEFORE any Buyer blocks
    seller_idx = [ordered_texts.index("Seller:"), ordered_texts.index("Acme Supplies Ltd"), ordered_texts.index("100 Factory Lane")]
    buyer_idx = [ordered_texts.index("Client:"), ordered_texts.index("Global Retail Corp"), ordered_texts.index("500 Market St")]

    assert seller_idx == [2, 3, 4], f"Seller blocks should be consecutive at [2,3,4], got {seller_idx}"
    assert buyer_idx == [5, 6, 7], f"Buyer blocks should be consecutive at [5,6,7], got {buyer_idx}"

    # Verify table comes after parties
    assert ordered_texts.index("ITEMS") == 8
    assert ordered_texts.index("Widget Pro") == 9


def test_order_blocks_boundary_edge_case():
    """Test blocks near column boundary without splitting single lines unexpectedly."""
    page_w = 1000.0
    page_h = 1000.0
    
    # Left block spanning across near boundary
    b1 = OCRTextBlock(text="Seller: Left Co", confidence=0.9, bounding_box=[[100, 150], [480, 150], [480, 170], [100, 170]])
    # Right block starting just past midpoint
    b2 = OCRTextBlock(text="Client: Right Co", confidence=0.9, bounding_box=[[520, 150], [900, 150], [900, 170], [520, 170]])

    ordered = order_blocks_spatially([b2, b1], page_width=page_w, page_height=page_h)
    assert ordered[0].text == "Seller: Left Co"
    assert ordered[1].text == "Client: Right Co"
