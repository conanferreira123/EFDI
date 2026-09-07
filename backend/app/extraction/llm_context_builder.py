"""
LLM Context Builder for Structured Data Extraction.

Compiles rich, structured prompt contexts from ExtractionContext (including
primary OCR full text, reconstructed markdown tables, spatial party layouts,
and OCR quality indicators) to optimize LLM comprehension and extraction accuracy.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.extraction.base import ExtractionContext
from app.extraction.field_schemas import FieldDef, get_full_field_schema


class LLMContextBuilder:
    """
    Builds system and user prompts for LLMBasedExtractor using the full
    richness of ExtractionContext without discarding OCR spatial/table structures.
    """

    @classmethod
    def format_table_as_markdown(cls, table_data: Optional[Dict[str, Any]]) -> Optional[str]:
        """Convert reconstructed table data into a clean Markdown table."""
        if not table_data:
            return None

        line_items = table_data.get("line_items") or []
        if not line_items:
            return None

        headers = ["Item #", "Description", "Qty", "Unit", "Unit Price", "Net Amount", "Tax %", "Gross Amount"]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]

        for item in line_items:
            row = [
                str(item.get("item_number") or ""),
                str(item.get("description") or "").replace("|", "-"),
                str(item.get("quantity") or ""),
                str(item.get("unit") or ""),
                str(item.get("unit_price") or ""),
                str(item.get("net_amount") or ""),
                str(item.get("vat_rate") or ""),
                str(item.get("gross_amount") or ""),
            ]
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    @classmethod
    def format_party_layout(cls, raw_blocks: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """
        Segment raw OCR blocks into Left (Seller/Vendor) and Right (Buyer/Client)
        party columns to resolve multi-column alignment ambiguities.
        """
        if not raw_blocks:
            return None

        first_page = raw_blocks[0] if raw_blocks else {}
        blocks = first_page.get("blocks") or []
        pw = float(first_page.get("page_width", 1000.0))
        ph = float(first_page.get("page_height", 1400.0))

        if not blocks:
            return None

        mid_x = pw * 0.50
        left_texts = []
        right_texts = []

        for b in blocks:
            text = (b.get("text") or "").strip()
            bbox = b.get("bounding_box") or []
            if not text or len(bbox) < 4:
                continue

            xs = [pt[0] for pt in bbox]
            ys = [pt[1] for pt in bbox]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0

            # Only analyze header and party band (top 40% of document)
            if cy < ph * 0.45:
                if cx < mid_x:
                    left_texts.append(text)
                else:
                    right_texts.append(text)

        if not left_texts and not right_texts:
            return None

        party_lines = []
        if left_texts:
            party_lines.append(f"**Left Section (Vendor / Seller / Header):**\n" + "\n".join(left_texts[:10]))
        if right_texts:
            party_lines.append(f"**Right Section (Customer / Buyer / Summary):**\n" + "\n".join(right_texts[:10]))

        return "\n\n".join(party_lines)

    @classmethod
    def build_system_prompt(cls, document_type: str) -> str:
        """Construct deterministic domain instruction prompt."""
        schema_fields = get_full_field_schema(document_type)
        field_descriptions = "\n".join(
            f"- {f.key} ({f.label}): expected type '{f.field_type}'"
            for f in schema_fields
        )

        return (
            f"You are an enterprise financial document intelligence extractor.\n"
            f"Extract all schema fields for document type '{document_type}' from the provided OCR evidence.\n\n"
            f"TARGET SCHEMA FIELDS:\n{field_descriptions}\n\n"
            f"EXTRACTION GUIDELINES:\n"
            f"1. Extract the exact value for each field if present in the document.\n"
            f"2. For every extracted field, provide a confidence score (0.0 to 1.0) and the exact verbatim snippet (source_quote) as proof.\n"
            f"3. If a field is NOT mentioned or cannot be determined from the document, return null for 'value', 0.0 for 'confidence', and null for 'source_quote'.\n"
            f"4. Dates must be normalized to ISO format (YYYY-MM-DD) if unambiguous.\n"
            f"5. Currency amounts must be normalized as plain numeric strings with decimals (e.g. '12500.00') without currency symbols or thousands commas.\n"
            f"6. Maintain strict fidelity to the document evidence without hallucinating values."
        )

    @classmethod
    def build_user_prompt(cls, context: ExtractionContext) -> str:
        """Compile complete multi-modal OCR evidence prompt for the LLM."""
        sections = []

        # 1. Primary Document Text
        sections.append(f"=== PRIMARY DOCUMENT OCR TEXT ===\n\"\"\"\n{context.full_text}\n\"\"\"")

        # 2. Party & Spatial Layout
        party_layout = cls.format_party_layout(context.raw_blocks)
        if party_layout:
            sections.append(f"=== SPATIAL PARTY & HEADER LAYOUT ===\n{party_layout}")

        # 3. Reconstructed Table Data
        table_md = cls.format_table_as_markdown(context.table_data)
        if table_md:
            sections.append(f"=== RECONSTRUCTED LINE ITEMS TABLE ===\n{table_md}")

        # 4. OCR Quality & Confidence Indicator
        if context.ocr_quality:
            overall_q = context.ocr_quality.get("overall_score")
            conf_score = context.ocr_quality.get("confidence_score")
            sections.append(
                f"=== OCR QUALITY SIGNALS ===\n"
                f"Overall Score: {overall_q}, Confidence: {conf_score}"
            )

        return "\n\n".join(sections)
