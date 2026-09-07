"""
Downstream 2D Bounding-Box Table Reconstruction Engine.

Transforms raw OCR blocks into structured invoice line items using
spatial relationships (column alignment, horizontal intervals, row clustering,
and multi-line description continuation).

Format-independent and robust to layout variations.
Does NOT mutate or overwrite original raw OCR evidence.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StructuredLineItem:
    """A single structured line-item reconstructed from table cells."""
    item_number: Optional[str] = None
    description: str = ""
    quantity: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Optional[str] = None
    net_amount: Optional[str] = None
    vat_rate: Optional[str] = None
    gross_amount: Optional[str] = None
    confidence: float = 1.0
    raw_blocks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReconstructedTable:
    """The structured representation of an invoice table."""
    headers: List[str] = field(default_factory=list)
    columns: Dict[str, Dict[str, float]] = field(default_factory=dict)
    line_items: List[StructuredLineItem] = field(default_factory=list)
    line_items_count: int = 0
    table_region: Dict[str, float] = field(default_factory=dict)
    summary_blocks_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headers": self.headers,
            "columns": self.columns,
            "line_items": [item.to_dict() for item in self.line_items],
            "line_items_count": len(self.line_items),
            "table_region": self.table_region,
            "summary_blocks_count": self.summary_blocks_count,
        }


def _get_bbox_bounds(bbox: List[List[float]]) -> Tuple[float, float, float, float, float, float]:
    """Extract (min_x, min_y, max_x, max_y, center_x, center_y)."""
    xs = [pt[0] for pt in bbox]
    ys = [pt[1] for pt in bbox]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return min_x, min_y, max_x, max_y, (min_x + max_x) / 2.0, (min_y + max_y) / 2.0


class TableReconstructor:
    """
    Downstream 2D geometric analyzer that detects table headers, derives
    column intervals, clusters rows by vertical alignment, and merges
    multiline descriptions.
    """

    HEADER_KEYWORDS = {
        "item_number": ["NO.", "NO_", "NO", "SL NO", "ITEM NO", "SR NO", "POS", "ITEM"],
        "description": ["DESCRIPTION", "ITEM DESCRIPTION", "PARTICULARS", "PRODUCT"],
        "quantity": ["QTY", "QUANTITY", "MENGE"],
        "unit": ["UM", "UNIT", "UOM", "EINHEIT"],
        "unit_price": ["NET PRICE", "UNIT PRICE", "PRICE", "RATE", "PREIS"],
        "net_amount": ["NET WORTH", "NET AMOUNT", "AMOUNT", "TAXABLE VALUE", "BETRAG"],
        "vat_rate": ["VAT %", "VAT%", "TAX %", "TAX%", "GST %", "GST%", "MWST"],
        "gross_amount": ["GROSS WORTH", "GROSS AMOUNT", "GROSS", "TOTAL AMOUNT", "GESAMT"]
    }

    SUMMARY_KEYWORDS = [
        "TOTAL", "SUBTOTAL", "GRAND TOTAL", "SUMMARY", "BANK DETAILS",
        "TERMS & CONDITIONS", "PAYMENT TERMS", "NOTES", "THANK YOU", "GESAMTBETRAG"
    ]

    def __init__(
        self,
        blocks: List[Any],
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
    ):
        self.raw_blocks = blocks or []
        self.page_width = page_width or 1000.0
        self.page_height = page_height or 1400.0

    def reconstruct(self) -> ReconstructedTable:
        if not self.raw_blocks:
            return ReconstructedTable()

        enriched = []
        for b in self.raw_blocks:
            # Handle both dict and OCRTextBlock instances
            if hasattr(b, "bounding_box"):
                bbox = b.bounding_box or [[0, 0], [0, 0], [0, 0], [0, 0]]
                text = (b.text or "").strip()
                conf = getattr(b, "confidence", 1.0)
                raw_dict = {"text": text, "confidence": conf, "bounding_box": bbox}
            else:
                bbox = b.get("bounding_box", [[0, 0], [0, 0], [0, 0], [0, 0]])
                text = b.get("text", "").strip()
                conf = b.get("confidence", 1.0)
                raw_dict = b

            x0, y0, x1, y1, cx, cy = _get_bbox_bounds(bbox)
            enriched.append({
                "raw": raw_dict,
                "text": text,
                "confidence": float(conf),
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "cx": cx, "cy": cy,
                "w": x1 - x0, "h": y1 - y0
            })

        # 1. Detect Table Header Region
        all_header_kws = []
        for col_name, kws in self.HEADER_KEYWORDS.items():
            for kw in kws:
                all_header_kws.append((kw, col_name))
        all_header_kws.sort(key=lambda x: len(x[0]), reverse=True)

        header_candidates = []
        for eb in enriched:
            # Header must be below the top 15% of the page
            if eb["y0"] > self.page_height * 0.15:
                text_up = eb["text"].upper()
                for kw, col_name in all_header_kws:
                    if kw == text_up or text_up.startswith(kw + " ") or text_up.endswith(" " + kw) or (" " + kw + " ") in text_up:
                        header_candidates.append((col_name, eb))
                        break
                    elif kw == text_up or (len(kw) >= 4 and (text_up.startswith(kw) or text_up.endswith(kw))):
                        header_candidates.append((col_name, eb))
                        break

        if not header_candidates:
            return ReconstructedTable()

        # Cluster candidate header blocks into the primary table header band
        # Find the band with the highest number of unique column headers
        header_candidates.sort(key=lambda x: x[1]["cy"])
        best_band = []
        for seed in header_candidates:
            band = [
                (col, eb) for col, eb in header_candidates
                if abs(eb["cy"] - seed[1]["cy"]) <= 35.0
            ]
            unique_cols = len(set(col for col, _ in band))
            if unique_cols > len(set(col for col, _ in best_band)):
                best_band = band

        if not best_band:
            return ReconstructedTable()

        header_top_y = min(eb["y0"] for _, eb in best_band)
        header_bottom_y = max(eb["y1"] for _, eb in best_band) + 30.0

        # 2. Derive Column Horizontal Intervals dynamically
        cols_by_name = {}
        for col_name, eb in best_band:
            if col_name not in cols_by_name:
                cols_by_name[col_name] = eb

        sorted_cols = sorted(cols_by_name.items(), key=lambda x: x[1]["cx"])
        columns = {}
        for i, (col_name, eb) in enumerate(sorted_cols):
            prev_cx = sorted_cols[i - 1][1]["cx"] if i > 0 else 0.0
            next_eb = sorted_cols[i + 1][1] if i < len(sorted_cols) - 1 else None

            # For description column, expand right boundary up to next column's left edge
            x_min = (prev_cx + eb["cx"]) / 2.0 if i > 0 else 0.0
            if col_name == "description" and next_eb:
                x_max = next_eb["x0"] - 5.0
            else:
                x_max = (eb["cx"] + next_eb["cx"]) / 2.0 if next_eb else self.page_width

            columns[col_name] = {
                "x_min": round(x_min, 1),
                "x_max": round(x_max, 1),
                "header_text": eb["text"],
                "cx": round(eb["cx"], 1)
            }

        # 3. Detect End of Table (Summary / Totals / Footer section)
        table_end_y = self.page_height * 0.95
        summary_blocks = []
        for eb in enriched:
            if eb["y0"] >= header_bottom_y:
                text_up = eb["text"].upper()
                if any(kw == text_up or text_up.startswith(kw) for kw in self.SUMMARY_KEYWORDS):
                    if eb["y0"] < table_end_y:
                        table_end_y = eb["y0"]
                        summary_blocks.append(eb)

        # 4. Extract Body Blocks strictly within table boundaries
        body_blocks = [
            eb for eb in enriched
            if eb["y0"] >= header_bottom_y and eb["y1"] <= (table_end_y + 5)
            and eb["text"] != ""
        ]

        if not body_blocks:
            return ReconstructedTable(
                headers=list(columns.keys()),
                columns=columns,
                line_items=[],
                table_region={"top": header_top_y, "bottom": table_end_y},
                summary_blocks_count=len(summary_blocks)
            )

        # 5. Cluster Body Blocks into Row Lines
        body_blocks.sort(key=lambda x: (x["cy"], x["x0"]))
        row_lines = []
        curr_line = []
        curr_y = None
        y_tolerance = 16.0

        for b in body_blocks:
            if curr_y is None:
                curr_y = b["cy"]
                curr_line.append(b)
            elif abs(b["cy"] - curr_y) <= y_tolerance:
                curr_line.append(b)
                curr_y = sum(x["cy"] for x in curr_line) / len(curr_line)
            else:
                row_lines.append(curr_line)
                curr_line = [b]
                curr_y = b["cy"]
        if curr_line:
            row_lines.append(curr_line)

        # 6. Assemble Structured Line Items with Multiline Description Merging
        line_items = []
        current_item: Optional[StructuredLineItem] = None

        for line in row_lines:
            cells = {}
            for b in line:
                for col_name, col_info in columns.items():
                    if col_info["x_min"] <= b["cx"] <= col_info["x_max"]:
                        if col_name in cells:
                            cells[col_name]["text"] += " " + b["text"]
                            cells[col_name]["confidences"].append(b["confidence"])
                            cells[col_name]["blocks"].append(b["raw"])
                        else:
                            cells[col_name] = {
                                "text": b["text"],
                                "confidences": [b["confidence"]],
                                "blocks": [b["raw"]],
                                "y0": b["y0"], "y1": b["y1"], "cx": b["cx"]
                            }
                        break

            # A line starts a new line item if it contains numeric fields (qty, price, net, gross) or an item number
            has_numeric_data = any(k in cells for k in ["quantity", "unit_price", "net_amount", "gross_amount"])
            has_item_num = "item_number" in cells and any(c.isdigit() for c in cells["item_number"]["text"])

            if has_numeric_data or has_item_num:
                if current_item:
                    line_items.append(current_item)

                desc = cells.get("description", {}).get("text", "")
                all_confs = [c for cell in cells.values() for c in cell["confidences"]]
                avg_conf = sum(all_confs) / len(all_confs) if all_confs else 1.0

                current_item = StructuredLineItem(
                    item_number=cells.get("item_number", {}).get("text"),
                    description=desc,
                    quantity=cells.get("quantity", {}).get("text"),
                    unit=cells.get("unit", {}).get("text"),
                    unit_price=cells.get("unit_price", {}).get("text"),
                    net_amount=cells.get("net_amount", {}).get("text"),
                    vat_rate=cells.get("vat_rate", {}).get("text"),
                    gross_amount=cells.get("gross_amount", {}).get("text"),
                    confidence=round(avg_conf, 4),
                    raw_blocks=[b for cell in cells.values() for b in cell["blocks"]]
                )
            else:
                # Multiline description continuation line
                desc_extra = cells.get("description", {}).get("text", "")
                if not desc_extra:
                    desc_extra = " ".join(b["text"] for b in line)

                if current_item and desc_extra:
                    current_item.description = (current_item.description + " " + desc_extra).strip()
                    for b in line:
                        current_item.raw_blocks.append(b["raw"])

        if current_item:
            line_items.append(current_item)

        return ReconstructedTable(
            headers=list(columns.keys()),
            columns=columns,
            line_items=line_items,
            line_items_count=len(line_items),
            table_region={"top": header_top_y, "bottom": table_end_y},
            summary_blocks_count=len(summary_blocks)
        )


def reconstruct_table(
    blocks: List[Any],
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
) -> ReconstructedTable:
    """Convenience helper to reconstruct a table from raw OCR blocks."""
    reconstructor = TableReconstructor(blocks, page_width=page_width, page_height=page_height)
    return reconstructor.reconstruct()
