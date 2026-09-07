"""
Document classification engine abstraction.

Mirrors app/ocr/base.py's pattern: an abstract interface so the
classification *strategy* (rule-based now, ML-based later) is a
pluggable implementation detail, not something baked into routers or
services. The spec calls for "Rule-based initially, ML-ready
architecture later" -- this interface is what makes that swap possible
without touching the API layer.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models.document_enums import DocumentType


@dataclass
class ClassificationSignal:
    """
    A single piece of evidence that contributed to the classification
    decision -- e.g. a matched keyword or regex pattern. Stored for
    transparency/audit: a finance team should be able to see *why* a
    document was classified a certain way, not just the final label.
    """

    matched_text: str
    rule_description: str
    weight: float


@dataclass
class ClassificationResultData:
    """In-memory result of running a classifier against document text."""

    document_type: DocumentType
    confidence: float  # 0.0 - 1.0
    signals: list[ClassificationSignal] = field(default_factory=list)
    engine_name: str = ""

    #: Per-type raw scores before normalization, useful for debugging
    #: borderline classifications (e.g. INVOICE: 0.62, PURCHASE_ORDER: 0.58).
    scores_by_type: dict[str, float] = field(default_factory=dict)


class ClassificationEngine(ABC):
    """
    Abstract base for document classification strategies.

    Implementations receive the document's extracted text (typically
    OCRResult.full_text) and must return a ClassificationResultData
    naming the single best-matching DocumentType, or UNKNOWN if no
    type scores above the engine's confidence floor.
    """

    name: str = "base"

    @abstractmethod
    def classify(self, text: str) -> ClassificationResultData:
        raise NotImplementedError
