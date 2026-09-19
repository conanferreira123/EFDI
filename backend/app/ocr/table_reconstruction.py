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
    accurate non-overlapping column intervals, clusters rows by vertical overlap,
    stitches split numeric tokens, and merges multiline descriptions.
    """

    HEADER_KEYWORDS = {
        "item_number": [
            "NO.", "NO_", "NO", "SL NO", "ITEM NO", "SR NO", "POS", "POS.", "POS NO",
            "ITEM", "ARTICLE", "ART.", "SR.", "SL.", "NO#", "#"
        ],
        "description": [
            "DESCRIPTION", "ITEM DESCRIPTION", "PARTICULARS", "PRODUCT", "ITEMS",
            "DESIGNATION", "BEZEICHNUNG", "ARTIKEL", "DETAILS", "PRODUCT DESCRIPTION"
        ],
        "quantity": ["QTY", "QUANTITY", "MENGE", "ANZAHL", "QTY.", "MENGE (STK)"],
        "unit": ["UM", "UNIT", "UOM", "EINHEIT", "U/M", "MEASURE", "UNIT OF MEASURE"],
        "unit_price": [
            "NET PRICE", "UNIT PRICE", "PRICE", "RATE", "PREIS", "EINZELPREIS",
            "NETTO-PREIS", "UNIT COST", "PRICE/UNIT", "PRICE (NET)"
        ],
        "net_amount": [
            "NET WORTH", "NET AMOUNT", "AMOUNT", "TAXABLE VALUE", "BETRAG",
            "NETTOBETRAG", "NET", "TOTAL NET", "BASE AMOUNT", "NET PRICE TOTAL"
        ],
        "vat_rate": [
            "VAT [%]", "VAT[%]", "VAT %", "VAT%", "TAX %", "TAX%", "GST %", "GST%",
            "MWST", "MWST%", "MWST %", "VAT RATE", "TAX RATE", "RATE %", "MWST. %",
            "VAT", "MWST.", "TAX RATE %"
        ],
        "gross_amount": [
            "GROSS WORTH", "GROSS AMOUNT", "GROSS", "TOTAL AMOUNT", "GESAMT",
            "BRUTTOBETRAG", "BRUTTO", "TOTAL", "LINE TOTAL", "GROSS TOTAL"
        ]
    }

    SUMMARY_KEYWORDS = [
        "TOTAL", "SUBTOTAL", "GRAND TOTAL", "SUMMARY", "BANK DETAILS",
        "TERMS & CONDITIONS", "PAYMENT TERMS", "NOTES", "THANK YOU",
        "GESAMTBETRAG", "TAX TOTAL", "VAT TOTAL", "BALANCE DUE", "AMOUNT DUE"
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
            # Table headers usually appear in upper half of page (below top 5% metadata)
            if eb["y0"] > self.page_height * 0.05:
                text_up = eb["text"].upper()
                for kw, col_name in all_header_kws:
                    if (
                        kw == text_up
                        or text_up.startswith(kw + " ")
                        or text_up.endswith(" " + kw)
                        or (" " + kw + " ") in text_up
                        or (len(kw) >= 3 and (text_up.startswith(kw) or text_up.endswith(kw)))
                    ):
                        header_candidates.append((col_name, eb))
                        break

        if not header_candidates:
            return ReconstructedTable()

        # Cluster candidate header blocks into the primary table header band
        header_candidates.sort(key=lambda x: x[1]["cy"])
        best_band: List[Tuple[str, Dict[str, Any]]] = []
        for seed in header_candidates:
            band = [
                (col, eb) for col, eb in header_candidates
                if abs(eb["cy"] - seed[1]["cy"]) <= 40.0
            ]
            unique_cols = len(set(col for col, _ in band))
            if unique_cols > len(set(col for col, _ in best_band)):
                best_band = band

        # Require at least 2 distinct recognized column headers to qualify as a structured table
        if len(set(col for col, _ in best_band)) < 2:
            return ReconstructedTable()

        header_top_y = min(eb["y0"] for _, eb in best_band)
        header_bottom_y = max(eb["y1"] for _, eb in best_band) + 15.0

        # 2. Derive Precise, Non-Overlapping Column Horizontal Intervals
        cols_by_name: Dict[str, Dict[str, Any]] = {}
        for col_name, eb in best_band:
            if col_name not in cols_by_name:
                cols_by_name[col_name] = eb
            else:
                # Merge multi-token header bounding box if same column
                existing = cols_by_name[col_name]
                existing["x0"] = min(existing["x0"], eb["x0"])
                existing["x1"] = max(existing["x1"], eb["x1"])
                existing["cx"] = (existing["x0"] + existing["x1"]) / 2.0
                existing["text"] = existing["text"] + " " + eb["text"]

        sorted_cols = sorted(cols_by_name.items(), key=lambda x: x[1]["cx"])
        columns: Dict[str, Dict[str, Any]] = {}
        for i, (col_name, eb) in enumerate(sorted_cols):
            prev_eb = sorted_cols[i - 1][1] if i > 0 else None
            next_eb = sorted_cols[i + 1][1] if i < len(sorted_cols) - 1 else None

            # Calculate robust boundaries using inter-column gutters and centers
            if i == 0:
                x_min = 0.0
            else:
                # Midpoint between previous column right edge and current column left edge
                if prev_eb and prev_eb["x1"] < eb["x0"]:
                    x_min = (prev_eb["x1"] + eb["x0"]) / 2.0
                else:
                    x_min = (prev_eb["cx"] + eb["cx"]) / 2.0 if prev_eb else 0.0

            if i == len(sorted_cols) - 1:
                x_max = self.page_width
            else:
                if next_eb and eb["x1"] < next_eb["x0"]:
                    x_max = (eb["x1"] + next_eb["x0"]) / 2.0
                else:
                    x_max = (eb["cx"] + next_eb["cx"]) / 2.0 if next_eb else self.page_width

            # For description column specifically, preserve room up to next column start
            if col_name == "description" and next_eb:
                x_max = min(x_max, next_eb["x0"] - 2.0)

            columns[col_name] = {
                "x_min": round(float(x_min), 1),
                "x_max": round(float(x_max), 1),
                "header_text": eb["text"],
                "cx": round(float(eb["cx"]), 1),
                "x0": round(float(eb["x0"]), 1),
                "x1": round(float(eb["x1"]), 1),
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

        # 4. Extract Body Blocks strictly within table boundaries (excluding headers and totals)
        body_blocks = [
            eb for eb in enriched
            if eb["y0"] >= header_bottom_y and eb["y1"] <= (table_end_y + 8.0)
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

        # 5. Cluster Body Blocks into Row Lines using Vertical Overlap and Jitter Tolerance
        body_blocks.sort(key=lambda x: (x["cy"], x["x0"]))
        row_lines: List[List[Dict[str, Any]]] = []
        curr_line: List[Dict[str, Any]] = []
        curr_y_min: Optional[float] = None
        curr_y_max: Optional[float] = None

        for b in body_blocks:
            if not curr_line:
                curr_line.append(b)
                curr_y_min = b["y0"]
                curr_y_max = b["y1"]
            else:
                # Vertical overlap check with active row line
                line_h = max(curr_y_max - curr_y_min, b["h"], 10.0)
                y_overlap = min(curr_y_max, b["y1"]) - max(curr_y_min, b["y0"])
                avg_cy = sum(x["cy"] for x in curr_line) / len(curr_line)

                if y_overlap > 0.3 * line_h or abs(b["cy"] - avg_cy) <= max(14.0, line_h * 0.65):
                    curr_line.append(b)
                    curr_y_min = min(curr_y_min, b["y0"])
                    curr_y_max = max(curr_y_max, b["y1"])
                else:
                    row_lines.append(sorted(curr_line, key=lambda x: x["x0"]))
                    curr_line = [b]
                    curr_y_min = b["y0"]
                    curr_y_max = b["y1"]

        if curr_line:
            row_lines.append(sorted(curr_line, key=lambda x: x["x0"]))

        # 6. Assign Blocks to Cells and Assemble Structured Line Items
        line_items: List[StructuredLineItem] = []
        current_item: Optional[StructuredLineItem] = None

        for line in row_lines:
            cells: Dict[str, Dict[str, Any]] = {}
            for b in line:
                best_col: Optional[str] = None
                best_overlap: float = 0.0

                for col_name, col_info in columns.items():
                    # Check horizontal overlap
                    overlap_x0 = max(col_info["x_min"], b["x0"])
                    overlap_x1 = min(col_info["x_max"], b["x1"])
                    overlap = max(0.0, overlap_x1 - overlap_x0)

                    # Also evaluate center containment
                    if col_info["x_min"] <= b["cx"] <= col_info["x_max"]:
                        overlap += 10.0  # Preference for center-contained column

                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_col = col_name

                if best_col is not None and best_overlap > 0.0:
                    if best_col in cells:
                        # Number / text token stitching within the same cell
                        cells[best_col]["text"] += " " + b["text"]
                        cells[best_col]["confidences"].append(b["confidence"])
                        cells[best_col]["blocks"].append(b["raw"])
                    else:
                        cells[best_col] = {
                            "text": b["text"],
                            "confidences": [b["confidence"]],
                            "blocks": [b["raw"]],
                            "y0": b["y0"], "y1": b["y1"], "cx": b["cx"]
                        }

            # Check if this line begins a new primary line item or is a multiline continuation
            has_numeric_data = any(
                k in cells and bool(cells[k]["text"].strip())
                for k in ["quantity", "unit_price", "net_amount", "gross_amount", "vat_rate"]
            )
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
                    # If not explicitly in description column, join all text on this continuation line
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
