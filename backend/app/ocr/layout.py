"""
Document spatial layout analysis and reading-order reconstruction.

Downstream layout component that operates on OCR text blocks and their
bounding-box coordinates (format-independent: works on PDF and image inputs).

Key responsibilities:
1. Segment the page into logical spatial regions:
   - Top metadata header (e.g. Invoice No, Date of issue)
   - Multi-column party information (e.g. Seller column on left, Buyer/Client column on right)
   - Body & table section (line items, descriptions, amounts)
   - Bottom summary & totals
2. Reorder blocks within each column/band to produce a coherent, non-interleaved
   reading order for `full_text` while preserving `raw_blocks` evidence intact.
"""
from typing import List, Tuple
from app.ocr.base import OCRTextBlock


def _get_bbox_bounds(bbox: List[List[float]]) -> Tuple[float, float, float, float, float, float]:
    """
    Extract (min_x, min_y, max_x, max_y, center_x, center_y) from polygon coordinates.
    """
    xs = [pt[0] for pt in bbox]
    ys = [pt[1] for pt in bbox]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    return min_x, min_y, max_x, max_y, center_x, center_y


def order_blocks_spatially(
    blocks: List[OCRTextBlock],
    page_width: float | None = None,
    page_height: float | None = None,
) -> List[OCRTextBlock]:
    """
    Reorders a list of OCRTextBlock items spatially to resolve multi-column
    interleaving (such as two-column Seller vs Client header sections) and
    reconstruct a natural top-to-bottom, column-by-column reading order.

    Does NOT modify the input blocks or their coordinates.
    """
    if not blocks:
        return []

    if len(blocks) == 1:
        return list(blocks)

    # Compute bounding box statistics for all blocks
    enriched = []
    all_xs = []
    all_ys = []

    for block in blocks:
        if not block.bounding_box or len(block.bounding_box) < 4:
            # Fallback if bounding box is malformed
            min_x, min_y, max_x, max_y, cx, cy = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        else:
            min_x, min_y, max_x, max_y, cx, cy = _get_bbox_bounds(block.bounding_box)
            all_xs.extend([min_x, max_x])
            all_ys.extend([min_y, max_y])

        enriched.append({
            "block": block,
            "text": block.text or "",
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "cx": cx,
            "cy": cy,
        })

    # Estimate page dimensions if not provided
    eff_page_width = page_width if (page_width and page_width > 0) else (max(all_xs) if all_xs else 1000.0)
    eff_page_height = page_height if (page_height and page_height > 0) else (max(all_ys) if all_ys else 1000.0)

    # Detect table/body start boundary dynamically
    table_keywords = ["ITEMS", "ITEM", "DESCRIPTION", "NO.", "NO_", "SL NO", "QTY", "QUANTITY", "NET PRICE", "NET WORTH"]
    table_y_start = eff_page_height
    for eb in enriched:
        t_upper = eb["text"].upper()
        if any(kw in t_upper for kw in table_keywords):
            # Table headers must be below the top 15% of the page
            if eb["min_y"] > eff_page_height * 0.15:
                table_y_start = min(table_y_start, eb["min_y"])

    # Detect party region start boundary (Seller / Client markers)
    party_keywords = ["seller", "client", "buyer", "bill to", "vendor", "from", "sold by", "ship to", "customer"]
    top_meta_end_y = eff_page_height * 0.12  # Default boundary
    for eb in enriched:
        if eb["cy"] < table_y_start:
            if any(pk in eb["text"].lower() for pk in party_keywords):
                top_meta_end_y = min(top_meta_end_y, eb["min_y"])

    # Segment blocks into three vertical bands:
    # 1. Top Metadata (Invoice No, Date, Title)
    # 2. Party Information (Two-column: Seller on Left, Client on Right)
    # 3. Body & Table (Line Items, Summaries, Footers)
    top_blocks = []
    party_blocks = []
    body_blocks = []

    for eb in enriched:
        if eb["max_y"] <= top_meta_end_y:
            top_blocks.append(eb)
        elif eb["min_y"] < table_y_start:
            party_blocks.append(eb)
        else:
            body_blocks.append(eb)

    # 1. Order Top Metadata: Line-by-line (Y-band grouping, left-to-right)
    def line_sort_key(item: dict, y_tolerance: float = 15.0) -> Tuple[int, float]:
        return (int(round(item["cy"] / y_tolerance)), item["min_x"])

    top_sorted = sorted(top_blocks, key=lambda x: line_sort_key(x, 15.0))

    # 2. Order Party Information: Split into Left (Seller) and Right (Buyer) columns
    if party_blocks:
        mid_x = eff_page_width * 0.50
        left_party = [b for b in party_blocks if b["cx"] < mid_x]
        right_party = [b for b in party_blocks if b["cx"] >= mid_x]

        # Sort Left Column top-to-bottom (Y then X)
        left_party_sorted = sorted(left_party, key=lambda x: (x["min_y"], x["min_x"]))
        # Sort Right Column top-to-bottom (Y then X)
        right_party_sorted = sorted(right_party, key=lambda x: (x["min_y"], x["min_x"]))

        party_sorted = left_party_sorted + right_party_sorted
    else:
        party_sorted = []

    # 3. Order Body & Table section: Line/row grouping (Y-band grouping, left-to-right)
    body_sorted = sorted(body_blocks, key=lambda x: line_sort_key(x, 12.0))

    final_ordered_enriched = top_sorted + party_sorted + body_sorted
    return [eb["block"] for eb in final_ordered_enriched]
