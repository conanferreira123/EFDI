"""
Extraction engine factory. Mirrors app/ocr/factory.py and
app/classification/factory.py.
"""
from app.core.exceptions import ValidationFailedException
from app.extraction.base import ExtractionEngine
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.parallel_orchestrator import HybridExtractor
from app.extraction.rule_based import RuleBasedExtractor

SUPPORTED_EXTRACTORS = ("rule_based", "llm_based", "llm_rag", "hybrid")

_singletons: dict[str, ExtractionEngine] = {}


def get_extraction_engine(engine_name: str = "rule_based") -> ExtractionEngine:
    if engine_name not in SUPPORTED_EXTRACTORS:
        raise ValidationFailedException(
            f"Unknown extraction engine '{engine_name}'. "
            f"Supported engines: {list(SUPPORTED_EXTRACTORS)}"
        )

    if engine_name not in _singletons:
        if engine_name == "rule_based":
            _singletons[engine_name] = RuleBasedExtractor()
        elif engine_name in ("llm_based", "llm_rag"):
            _singletons[engine_name] = LLMBasedExtractor()
        elif engine_name == "hybrid":
            _singletons[engine_name] = HybridExtractor()

    return _singletons[engine_name]

