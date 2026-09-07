"""
Spatial 2D layout extraction helpers for RuleBasedExtractor.

Provides deterministic bounding-box proximity queries to locate field values
adjacent to labels (right-side or immediately below) when raw OCR blocks
are available.
"""
import re
from typing import Any, List, Optional, Tuple

from app.extraction.base import ExtractedField
from app.extraction.primitives import (
    KNOWN_LABELS,
    normalize_amount,
    normalize_date,
)


def _get_block_bounds(bbox: List[List[float]]) -> Tuple[float, float, float, float, float, float, float, float]:
    """
    Extract (min_x, min_y, max_x, max_y, cx, cy, width, height) from bounding box.
    """
    xs = [pt[0] for pt in bbox]
    ys = [pt[1] for pt in bbox]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    w = max_x - min_x
    h = max_y - min_y
    return min_x, min_y, max_x, max_y, cx, cy, w, h


def _is_known_label(text: str) -> bool:
    """Check if the text consists predominantly of a known schema label."""
    cleaned = text.strip().rstrip(":-=").strip()
    return cleaned.lower() in {lbl.lower() for lbl in KNOWN_LABELS}


def extract_field_spatially(
    raw_blocks: List[dict] | None,
    labels: List[str],
    *,
    field_type: str = "text",
    max_value_length: int = 80,
) -> ExtractedField:
    """
    Search raw OCR blocks for label occurrences and extract value from
    the same block or deterministically adjacent neighbor blocks (right/below).

    Deterministic proximity rules:
    1. Same-block value: label followed by value separator in the same block.
    2. Right-adjacent neighbor: horizontally aligned within Y-tolerance and
       within horizontal gap threshold (X distance <= 450px).
    3. Below-adjacent neighbor: vertically aligned below label within X-tolerance
       and vertical gap threshold (Y distance <= 80px).
    """
    if not raw_blocks:
        return ExtractedField(value=None, confidence=0.0)

    for page in raw_blocks:
        blocks_data = page.get("blocks", [])
        if not blocks_data:
            continue

        # Parse and enrich block geometries
        parsed_blocks = []
        for b in blocks_data:
            text = (b.get("text") or "").strip()
            bbox = b.get("bounding_box") or []
            if not text or len(bbox) < 4:
                continue
            min_x, min_y, max_x, max_y, cx, cy, w, h = _get_block_bounds(bbox)
            parsed_blocks.append({
                "text": text,
                "confidence": float(b.get("confidence", 0.9)),
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "cx": cx,
                "cy": cy,
                "w": w,
                "h": h,
            })

        if not parsed_blocks:
            continue

        # Try labels in declared priority order
        for priority_idx, label in enumerate(labels):
            label_pattern = re.compile(r"\b" + re.escape(label) + r"\b", re.IGNORECASE)

            for lbl_block in parsed_blocks:
                match = label_pattern.search(lbl_block["text"])
                if not match:
                    continue

                # 1. Check if the value is in the same block after the label
                after_label = lbl_block["text"][match.end():].strip()
                if after_label:
                    cleaned_val = after_label.lstrip(":-=").strip()
                    if cleaned_val and not _is_known_label(cleaned_val):
                        norm_val = _normalize_by_type(cleaned_val, field_type)
                        if norm_val:
                            base_conf = max(0.5, 0.90 - (priority_idx * 0.05))
                            return ExtractedField(
                                value=norm_val[:max_value_length],
                                confidence=round(base_conf, 2),
                                matched_text=lbl_block["text"],
                            )

                # 2. Search for Right-Adjacent Neighbor Block
                right_candidates = []
                for other in parsed_blocks:
                    if other is lbl_block:
                        continue
                    # Horizontal condition: other block is to the right
                    x_gap = other["min_x"] - lbl_block["max_x"]
                    if 0 <= x_gap <= 450:
                        # Vertical alignment condition: centers within tolerance
                        y_diff = abs(other["cy"] - lbl_block["cy"])
                        y_tol = max(18.0, 0.65 * lbl_block["h"])
                        if y_diff <= y_tol:
                            right_candidates.append((x_gap, other))

                if right_candidates:
                    right_candidates.sort(key=lambda item: item[0])
                    for _, cand in right_candidates:
                        cand_text = cand["text"].lstrip(":-=").strip()
                        if cand_text and not _is_known_label(cand_text):
                            norm_val = _normalize_by_type(cand_text, field_type)
                            if norm_val:
                                base_conf = max(0.45, 0.86 - (priority_idx * 0.05))
                                return ExtractedField(
                                    value=norm_val[:max_value_length],
                                    confidence=round(base_conf, 2),
                                    matched_text=f"{label}: {cand['text']}",
                                )

                # 3. Search for Below-Adjacent Neighbor Block
                below_candidates = []
                for other in parsed_blocks:
                    if other is lbl_block:
                        continue
                    # Vertical condition: other block is below
                    y_gap = other["min_y"] - lbl_block["max_y"]
                    if 0 <= y_gap <= 85:
                        # Horizontal alignment condition: left edges or centers aligned
                        x_left_diff = abs(other["min_x"] - lbl_block["min_x"])
                        x_center_diff = abs(other["cx"] - lbl_block["cx"])
                        if x_left_diff <= 60 or x_center_diff <= 100:
                            below_candidates.append((y_gap, other))

                if below_candidates:
                    below_candidates.sort(key=lambda item: item[0])
                    for _, cand in below_candidates:
                        cand_text = cand["text"].lstrip(":-=").strip()
                        if cand_text and not _is_known_label(cand_text):
                            norm_val = _normalize_by_type(cand_text, field_type)
                            if norm_val:
                                base_conf = max(0.40, 0.80 - (priority_idx * 0.05))
                                return ExtractedField(
                                    value=norm_val[:max_value_length],
                                    confidence=round(base_conf, 2),
                                    matched_text=f"{label}\n{cand['text']}",
                                )

    return ExtractedField(value=None, confidence=0.0)


def _normalize_by_type(raw_val: str, field_type: str) -> Optional[str]:
    """Normalize extracted raw string according to field type."""
    if not raw_val:
        return None
    if field_type == "date":
        return normalize_date(raw_val)
    elif field_type == "amount":
        return normalize_amount(raw_val)
    elif field_type == "code":
        cleaned = raw_val.strip().rstrip(".,;:")
        return cleaned if cleaned else None
    return raw_val.strip()
