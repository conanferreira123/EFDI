"""
Stub OCR engine.

THIS IS NOT A REAL OCR ENGINE. It exists solely to exercise every other
part of the OCR pipeline (preprocessing, multi-page orchestration,
persistence, API responses) in environments where PaddleOCR's and
EasyOCR's model weights cannot be downloaded (e.g. network-restricted
sandboxes/CI).

It deterministically reports a single fixed-confidence text block per
image based on the image's pixel statistics, so identical input always
produces identical output (test-repeatability) without requiring any
model weights or network access.

This engine must never be selected as the default in any real
deployment -- see app/ocr/factory.py for how engine selection works and
why "stub" is excluded from the production-facing engine list.
"""
import hashlib

import numpy as np

from app.ocr.base import OCREngine, OCRTextBlock


class StubOCREngine(OCREngine):
    name = "stub"

    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        h, w = image.shape[:2]
        # Derive a short, deterministic "recognized text" string from the
        # image content itself (its hash), so different input images
        # produce different (but stable, repeatable) stub output -- useful
        # for asserting "the pipeline ran on THIS image" in tests.
        digest = hashlib.sha256(image.tobytes()).hexdigest()[:12]

        return [
            OCRTextBlock(
                text=f"[STUB OCR OUTPUT - no real text extraction - digest:{digest}]",
                confidence=0.42,
                bounding_box=[[0, 0], [w, 0], [w, h], [0, h]],
            )
        ]

    def is_available(self) -> tuple[bool, str]:
        return True, "stub engine: always available, produces placeholder output only"
