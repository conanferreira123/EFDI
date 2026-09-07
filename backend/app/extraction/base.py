"""
Data extraction engine abstraction.

Mirrors app/ocr/base.py and app/classification/base.py: an abstract
interface so the extraction *strategy* (rule-based now, ML/LLM-based
later) is pluggable without touching routers or services.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractedField:
    """
    A single extracted field's value plus how confident the extractor
    is in that value, and exactly what text it matched against (so a
    human reviewer can verify it against the source document).

    `value` is None when the field could not be found in the OCR text
    -- extractors never fabricate values. `is_found` distinguishes
    "found but empty string" (rare) from "not found at all" (common
    and expected) for fields a reviewer will need to fill in manually.
    """

    value: str | None
    confidence: float  # 0.0 - 1.0; 0.0 when value is None
    matched_text: str | None = None  # the raw text the pattern matched, for audit
    provenance: str | None = None  # "agreed", "rule_based", "llm", "reconciled", "unresolved_conflict"
    conflict_value: str | None = None  # competing value if a conflict was detected

    @property
    def is_found(self) -> bool:
        return self.value is not None



@dataclass
class ExtractionResultData:
    """In-memory result of running an extractor against document text."""

    document_type: str
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    engine_name: str = ""

    @property
    def overall_confidence(self) -> float:
        """Average confidence across all fields that were actually found."""
        found = [f.confidence for f in self.fields.values() if f.is_found]
        return sum(found) / len(found) if found else 0.0

    @property
    def fields_found_count(self) -> int:
        return sum(1 for f in self.fields.values() if f.is_found)

    @property
    def fields_total_count(self) -> int:
        return len(self.fields)


@dataclass
class ExtractionContext:
    """
    Context passed to extraction engines containing the primary textual document
    representation and optional OCR-derived layout/structural metadata.
    """

    full_text: str
    document_type: str
    raw_blocks: list[dict] = field(default_factory=list)
    table_data: dict | None = None
    normalized_data: dict | None = None
    ocr_validation: dict | None = None
    ocr_quality: dict | None = None
    document_id: int | None = None


class ExtractionEngine(ABC):
    """
    Abstract base for data extraction strategies.

    Implementations receive an ExtractionContext (or legacy text + document_type)
    and return an ExtractionResultData populating every field defined in that
    type's schema.
    """

    name: str = "base"

    @abstractmethod
    def extract(
        self,
        context_or_text: ExtractionContext | str | None = None,
        document_type: str | None = None,
        *,
        context: ExtractionContext | None = None,
        text: str | None = None,
    ) -> ExtractionResultData:
        raise NotImplementedError

