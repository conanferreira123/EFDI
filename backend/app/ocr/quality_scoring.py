"""
Multi-dimensional Document Quality Scoring Engine for OCR.

Clearly separates raw character-level OCR recognition confidence from
overall structural document quality, field completeness, and mathematical consistency.
"""
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class OCRQualityBreakdown:
    """Detailed score breakdown across document dimensions."""
    overall_quality_score: float         # Composite score [0.0 - 1.0]
    ocr_confidence_score: float          # Raw EasyOCR average confidence [0.0 - 1.0]
    structural_layout_score: float       # Column, header, and spatial organization score [0.0 - 1.0]
    mathematical_validation_score: float # Arithmetic consistency score [0.0 - 1.0]
    field_completeness_score: float      # Core field presence score [0.0 - 1.0]

    quality_grade: str                   # 'EXCELLENT', 'GOOD', 'FAIR', 'POOR'
    quality_notes: List[str]             # Explanatory breakdown notes

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OCRQualityScorer:
    """
    Computes an objective, multi-factor quality score for OCR documents.
    """

    def __init__(
        self,
        weight_confidence: float = 0.35,
        weight_structural: float = 0.25,
        weight_validation: float = 0.25,
        weight_completeness: float = 0.15,
    ):
        self.w_conf = weight_confidence
        self.w_struct = weight_structural
        self.w_val = weight_validation
        self.w_comp = weight_completeness

    def score(
        self,
        avg_confidence: float,
        full_text: str,
        table_data: Optional[Dict[str, Any]] = None,
        validation_result: Optional[Any] = None,
    ) -> OCRQualityBreakdown:
        notes: List[str] = []

        # 1. OCR Confidence Score
        conf_score = max(0.0, min(1.0, float(avg_confidence or 0.0)))
        if conf_score >= 0.85:
            notes.append(f"High OCR character recognition confidence ({conf_score:.2%})")
        elif conf_score >= 0.70:
            notes.append(f"Moderate OCR character recognition confidence ({conf_score:.2%})")
        else:
            notes.append(f"Low OCR character recognition confidence ({conf_score:.2%})")

        # 2. Structural Layout Score
        struct_score = 0.0
        if full_text and len(full_text.strip()) > 50:
            struct_score += 0.30  # Substantial text extracted

        # Check column organization
        if "Seller:" in full_text and "Client:" in full_text:
            struct_score += 0.30  # Parties segregated
            notes.append("Party columns cleanly segregated")

        # Check table structure
        if table_data:
            line_items = table_data.get("line_items", [])
            headers = table_data.get("headers", [])
            if len(headers) >= 4:
                struct_score += 0.20  # Comprehensive table headers detected
            if len(line_items) > 0:
                struct_score += 0.20  # Structured line items reconstructed
                notes.append(f"{len(line_items)} table line item(s) reconstructed")
        struct_score = min(1.0, struct_score)

        # 3. Mathematical Validation Score
        val_score = 1.0
        if validation_result:
            if hasattr(validation_result, "flags"):
                flags = validation_result.flags
                if flags:
                    passed = sum(1 for f in flags if getattr(f, "is_valid", False))
                    val_score = passed / len(flags)
                    if val_score == 1.0:
                        notes.append("All mathematical and field validations passed")
                    else:
                        notes.append(f"Validation pass rate: {passed}/{len(flags)} rules ({val_score:.1%})")
            elif isinstance(validation_result, dict):
                flags = validation_result.get("flags", [])
                if flags:
                    passed = sum(1 for f in flags if f.get("is_valid", False))
                    val_score = passed / len(flags)
        val_score = min(1.0, max(0.0, val_score))

        # 4. Field Completeness Score
        comp_points = 0.0
        text_up = (full_text or "").upper()
        if any(kw in text_up for kw in ["INVOICE NO", "INVOICE #", "INV-", "INVOICE NUMBER"]):
            comp_points += 0.25
        if any(kw in text_up for kw in ["DATE", "DATE OF ISSUE", "INVOICE DATE"]):
            comp_points += 0.25
        if any(kw in text_up for kw in ["SELLER", "VENDOR", "SUPPLIER", "FROM:"]):
            comp_points += 0.25
        if any(kw in text_up for kw in ["CLIENT", "BUYER", "BILL TO", "CUSTOMER"]):
            comp_points += 0.25
        comp_score = min(1.0, comp_points)

        # 5. Composite Score
        overall = (
            (self.w_conf * conf_score) +
            (self.w_struct * struct_score) +
            (self.w_val * val_score) +
            (self.w_comp * comp_score)
        )
        overall = round(max(0.0, min(1.0, overall)), 4)

        if overall >= 0.85:
            grade = "EXCELLENT"
        elif overall >= 0.70:
            grade = "GOOD"
        elif overall >= 0.50:
            grade = "FAIR"
        else:
            grade = "POOR"

        return OCRQualityBreakdown(
            overall_quality_score=overall,
            ocr_confidence_score=round(conf_score, 4),
            structural_layout_score=round(struct_score, 4),
            mathematical_validation_score=round(val_score, 4),
            field_completeness_score=round(comp_score, 4),
            quality_grade=grade,
            quality_notes=notes,
        )


def calculate_quality_score(
    avg_confidence: float,
    full_text: str,
    table_data: Optional[Dict[str, Any]] = None,
    validation_result: Optional[Any] = None,
) -> OCRQualityBreakdown:
    """Helper to compute OCR quality score."""
    scorer = OCRQualityScorer()
    return scorer.score(
        avg_confidence=avg_confidence,
        full_text=full_text,
        table_data=table_data,
        validation_result=validation_result,
    )
