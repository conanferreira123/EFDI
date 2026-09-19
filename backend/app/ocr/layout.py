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
from typing import Any, List, Optional, Tuple
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


def format_reconstructed_table_markdown(table: Any) -> str:
    """Format a ReconstructedTable into a clean Markdown table string."""
    line_items = getattr(table, "line_items", []) if table else []
    if not line_items:
        return ""

    headers = ["#", "Description", "Qty", "Unit", "Unit Price", "Net Amount", "Tax %", "Gross Amount"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for idx, item in enumerate(line_items, 1):
        if isinstance(item, dict):
            num = item.get("item_number") or item.get("item_no") or str(idx)
            desc = (str(item.get("description") or "")).replace("|", "-").strip()
            qty = item.get("quantity") or ""
            unit = item.get("unit") or ""
            price = item.get("unit_price") or ""
            net = item.get("net_amount") or ""
            vat = item.get("vat_rate") or item.get("vat_percent") or ""
            gross = item.get("gross_amount") or ""
        else:
            num = getattr(item, "item_number", None) or getattr(item, "item_no", None) or str(idx)
            desc = (str(getattr(item, "description", None) or "")).replace("|", "-").strip()
            qty = getattr(item, "quantity", None) or ""
            unit = getattr(item, "unit", None) or ""
            price = getattr(item, "unit_price", None) or ""
            net = getattr(item, "net_amount", None) or ""
            vat = getattr(item, "vat_rate", None) or getattr(item, "vat_percent", None) or ""
            gross = getattr(item, "gross_amount", None) or ""
        lines.append(f"| {num} | {desc} | {qty} | {unit} | {price} | {net} | {vat} | {gross} |")

    return "\n".join(lines)


def build_structured_page(
    blocks: List[OCRTextBlock],
    table: Optional[Any] = None,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    page_number: int = 1,
) -> Any:
    """
    Builds a StructuredDocumentPage intermediate representation from raw OCR blocks
    and reconstructed table data for a single page.
    """
    from app.ocr.document_structure import StructuredDocumentPage

    if not blocks:
        return StructuredDocumentPage(page_number=page_number, table=table)

    enriched = []
    all_xs = []
    all_ys = []

    for block in blocks:
        if not block.bounding_box or len(block.bounding_box) < 4:
            min_x, min_y, max_x, max_y, cx, cy = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        else:
            min_x, min_y, max_x, max_y, cx, cy = _get_bbox_bounds(block.bounding_box)
            all_xs.extend([min_x, max_x])
            all_ys.extend([min_y, max_y])

        enriched.append({
            "block": block,
            "text": (block.text or "").strip(),
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "cx": cx,
            "cy": cy,
        })

    eff_page_width = page_width if (page_width and page_width > 0) else (max(all_xs) if all_xs else 1000.0)
    eff_page_height = page_height if (page_height and page_height > 0) else (max(all_ys) if all_ys else 1400.0)
    mid_x = eff_page_width * 0.50

    if isinstance(table, dict):
        line_items = table.get("line_items", [])
        table_region = table.get("table_region", {}) or {}
    else:
        line_items = getattr(table, "line_items", None) or []
        table_region = getattr(table, "table_region", None) or {}

    has_table = bool(line_items)
    if has_table:
        table_top_y = float(table_region.get("top", eff_page_height * 0.30) if isinstance(table_region, dict) else getattr(table_region, "top", eff_page_height * 0.30))
        table_bottom_y = float(table_region.get("bottom", eff_page_height * 0.70) if isinstance(table_region, dict) else getattr(table_region, "bottom", eff_page_height * 0.70))
    else:
        table_top_y = eff_page_height
        table_bottom_y = eff_page_height

    # Detect party start boundary in top region
    party_keywords = ["seller", "client", "buyer", "bill to", "vendor", "from", "sold by", "ship to", "customer"]
    top_meta_end_y = eff_page_height * 0.12
    for eb in enriched:
        if eb["cy"] < table_top_y:
            if any(pk in eb["text"].lower() for pk in party_keywords):
                top_meta_end_y = min(top_meta_end_y, eb["min_y"])

    summary_keywords = ["TOTAL", "SUBTOTAL", "GRAND TOTAL", "SUMMARY", "BANK DETAILS", "TERMS & CONDITIONS", "PAYMENT TERMS", "VAT", "NET WORTH", "GROSS WORTH", "GESAMTBETRAG"]

    header_blocks = []
    party_left = []
    party_right = []
    summary_blocks = []
    footer_blocks = []
    other_blocks = []

    def line_sort_key(item: dict, y_tolerance: float = 15.0) -> Tuple[int, float]:
        return (int(round(item["cy"] / y_tolerance)), item["min_x"])

    for eb in enriched:
        if not eb["text"]:
            continue

        if has_table:
            if eb["max_y"] <= top_meta_end_y:
                header_blocks.append(eb)
            elif eb["min_y"] < table_top_y:
                if eb["cx"] < mid_x:
                    party_left.append(eb)
                else:
                    party_right.append(eb)
            elif eb["y0"] if "y0" in eb else eb["min_y"] >= table_bottom_y:
                t_up = eb["text"].upper()
                if any(kw in t_up for kw in summary_keywords):
                    summary_blocks.append(eb)
                else:
                    footer_blocks.append(eb)
            # Blocks inside the table region are represented by table.line_items
        else:
            if eb["max_y"] <= top_meta_end_y:
                header_blocks.append(eb)
            elif eb["min_y"] < (eff_page_height * 0.35):
                if eb["cx"] < mid_x:
                    party_left.append(eb)
                else:
                    party_right.append(eb)
            else:
                other_blocks.append(eb)

    # Sort each section deterministically
    header_sorted = [eb["block"] for eb in sorted(header_blocks, key=lambda x: line_sort_key(x, 15.0))]
    party_left_sorted = [eb["block"] for eb in sorted(party_left, key=lambda x: (x["min_y"], x["min_x"]))]
    party_right_sorted = [eb["block"] for eb in sorted(party_right, key=lambda x: (x["min_y"], x["min_x"]))]
    summary_sorted = [eb["block"] for eb in sorted(summary_blocks, key=lambda x: line_sort_key(x, 12.0))]
    footer_sorted = [eb["block"] for eb in sorted(footer_blocks, key=lambda x: line_sort_key(x, 15.0))]
    other_sorted = [eb["block"] for eb in sorted(other_blocks, key=lambda x: line_sort_key(x, 12.0))]

    return StructuredDocumentPage(
        page_number=page_number,
        header_blocks=header_sorted,
        party_left_blocks=party_left_sorted,
        party_right_blocks=party_right_sorted,
        table=table if has_table else None,
        summary_blocks=summary_sorted,
        footer_blocks=footer_sorted,
        other_blocks=other_sorted,
    )


def generate_structured_full_text(pages: List[Any], table_format: str = "markdown") -> str:
    """
    Generates structured, clean full_text from a list of StructuredDocumentPage instances.
    Preserves headers, 2-column party sections, Markdown line items, and summary totals.
    """
    if not pages:
        return ""

    doc_sections = []
    is_multi_page = len(pages) > 1

    for page in pages:
        page_parts = []
        if is_multi_page:
            page_parts.append(f"=== PAGE {getattr(page, 'page_number', 1)} ===")

        # 1. Header & Metadata
        header_blocks = getattr(page, "header_blocks", [])
        if header_blocks:
            hdr_text = "\n".join(b.text for b in header_blocks if b.text)
            if hdr_text:
                page_parts.append(f"=== HEADER & METADATA ===\n{hdr_text}")

        # 2. Parties Section
        party_left = getattr(page, "party_left_blocks", [])
        party_right = getattr(page, "party_right_blocks", [])
        if party_left or party_right:
            party_lines = []
            if party_left:
                left_txt = "\n".join(b.text for b in party_left if b.text)
                if left_txt:
                    party_lines.append(f"--- SELLER COLUMN ---\n{left_txt}")
            if party_right:
                right_txt = "\n".join(b.text for b in party_right if b.text)
                if right_txt:
                    party_lines.append(f"--- BUYER COLUMN ---\n{right_txt}")
            if party_lines:
                page_parts.append(f"=== PARTIES ===\n" + "\n\n".join(party_lines))

        # 3. Line Items Table
        table = getattr(page, "table", None)
        if table and (getattr(table, "line_items", None) or (isinstance(table, dict) and table.get("line_items"))):
            table_md = format_reconstructed_table_markdown(table)
            if table_md:
                page_parts.append(f"=== LINE ITEMS ===\n{table_md}")

        # 4. Summary & Totals
        summary_blocks = getattr(page, "summary_blocks", [])
        if summary_blocks:
            sum_txt = "\n".join(b.text for b in summary_blocks if b.text)
            if sum_txt:
                page_parts.append(f"=== TOTALS & SUMMARY ===\n{sum_txt}")

        # 5. Footer & Notes
        footer_blocks = getattr(page, "footer_blocks", [])
        if footer_blocks:
            ftr_txt = "\n".join(b.text for b in footer_blocks if b.text)
            if ftr_txt:
                page_parts.append(ftr_txt)

        # 6. Non-table Body Blocks (for documents without tables)
        other_blocks = getattr(page, "other_blocks", [])
        if other_blocks:
            oth_txt = "\n".join(b.text for b in other_blocks if b.text)
            if oth_txt:
                page_parts.append(oth_txt)

        if page_parts:
            doc_sections.append("\n\n".join(page_parts))

    return "\n\n".join(doc_sections)

