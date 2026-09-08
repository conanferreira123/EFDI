"""
OCR engine abstraction.

Defines the contract every OCR backend (PaddleOCR, EasyOCR, or any
future engine) must implement, plus the normalized result shape the
rest of the application works with. Routers/services never import a
specific engine directly -- they go through OCREngineFactory
(app/ocr/factory.py) so the active engine is a runtime/config choice,
not a code choice.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class OCRTextBlock:
    """A single detected text region within a page/image."""

    text: str
    confidence: float  # 0.0 - 1.0
    bounding_box: list[list[float]]  # polygon: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]


@dataclass
class OCRPageResult:
    """OCR output for a single page (or a single image, for non-PDF input)."""

    page_number: int
    blocks: list[OCRTextBlock] = field(default_factory=list)
    custom_full_text: str | None = None

    @property
    def full_text(self) -> str:
        if self.custom_full_text is not None:
            return self.custom_full_text
        return "\n".join(block.text for block in self.blocks)

    @property
    def legacy_full_text(self) -> str:
        return "\n".join(block.text for block in self.blocks)

    @property
    def average_confidence(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(b.confidence for b in self.blocks) / len(self.blocks)


@dataclass
class OCRResult:
    """OCR output for an entire document, possibly spanning multiple pages."""

    pages: list[OCRPageResult] = field(default_factory=list)
    engine_name: str = ""
    custom_full_text: str | None = None

    @property
    def full_text(self) -> str:
        if self.custom_full_text is not None:
            return self.custom_full_text
        return "\n\n".join(page.full_text for page in self.pages)

    @property
    def legacy_full_text(self) -> str:
        return "\n\n".join(page.legacy_full_text for page in self.pages)

    @property
    def average_confidence(self) -> float:
        page_confidences = [p.average_confidence for p in self.pages if p.blocks]
        if not page_confidences:
            return 0.0
        return sum(page_confidences) / len(page_confidences)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_block_count(self) -> int:
        return sum(len(p.blocks) for p in self.pages)


class OCREngine(ABC):
    """
    Abstract base class for all OCR engines.

    Implementations receive a single page already rasterized to a numpy
    array (BGR or grayscale, as produced by app/ocr/preprocessing.py)
    and must return a list of OCRTextBlock. Multi-page orchestration
    (looping over PDF pages) happens one level up, in OCRService, so
    each engine implementation only needs to handle a single image.
    """

    #: Set by subclasses; used in OCRResult.engine_name and in logs.
    name: str = "base"

    @abstractmethod
    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        """Run OCR on a single page/image and return detected text blocks."""
        raise NotImplementedError

    def is_available(self) -> tuple[bool, str]:
        """
        Cheap readiness check (e.g. are model weights present / engine
        loaded) without actually running inference. Returns
        (available, reason_if_not). Used by /ocr/engines to report
        engine health without paying the cost of a full OCR call.
        """
        return True, ""
