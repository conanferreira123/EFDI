"""
Structured Document Intermediate Representation for EFDI OCR Pipeline.

Defines in-memory structured document models (StructuredDocumentPage,
DocumentElement) that bridge raw OCR block detections, spatial layout analysis,
and reconstructed table/normalization representations before full_text generation.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional
from app.ocr.base import OCRTextBlock


@dataclass
class StructuredDocumentPage:
    """
    Intermediate structured representation of a single document page.
    Preserves logical document zones (header, parties, line-item table,
    summary totals, footer) with full provenance to original OCRTextBlock evidence.
    """
    page_number: int
    header_blocks: List[OCRTextBlock] = field(default_factory=list)
    party_left_blocks: List[OCRTextBlock] = field(default_factory=list)
    party_right_blocks: List[OCRTextBlock] = field(default_factory=list)
    table: Optional[Any] = None  # ReconstructedTable instance
    summary_blocks: List[OCRTextBlock] = field(default_factory=list)
    footer_blocks: List[OCRTextBlock] = field(default_factory=list)
    other_blocks: List[OCRTextBlock] = field(default_factory=list)

    @property
    def has_table(self) -> bool:
        return bool(self.table and getattr(self.table, "line_items", None))

    @property
    def total_blocks_count(self) -> int:
        table_blocks = sum(len(getattr(item, "raw_blocks", [])) for item in getattr(self.table, "line_items", [])) if self.has_table else 0
        return (
            len(self.header_blocks)
            + len(self.party_left_blocks)
            + len(self.party_right_blocks)
            + table_blocks
            + len(self.summary_blocks)
            + len(self.footer_blocks)
            + len(self.other_blocks)
        )
