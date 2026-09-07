"""
OCR engine factory.

Centralizes engine selection so routers/services never import a
specific engine class directly. The active engine is chosen by name
(from request input or app config), making it a runtime/deployment
choice rather than something baked into the code.

"stub" is intentionally excluded from PRODUCTION_ENGINES: it produces
placeholder, non-real output and exists only to let the rest of the
pipeline be exercised in environments where real OCR model weights
aren't reachable (see app/ocr/stub_engine.py). It remains selectable
via SUPPORTED_ENGINES for exactly that purpose, but the API layer
labels it clearly so nobody mistakes stub output for real extraction.
"""
from app.core.exceptions import ValidationFailedException
from app.ocr.base import OCREngine
from app.ocr.easyocr_engine import EasyOCREngine
from app.ocr.paddle_engine import PaddleOCREngine
from app.ocr.stub_engine import StubOCREngine

# PaddleOCR is deliberately excluded from the selectable engine set.
# Instantiating/running it on this deployment's ARM64 hardware
# segfaults the whole Python process (a native crash, not a catchable
# exception) -- confirmed via tests/test_phase4_ocr.py -- which would
# take down the entire backend worker, not just the one request, if
# a caller specified engine="paddleocr". EasyOCR is the supported
# replacement (see the OCR engine migration history). The class
# still exists (app/ocr/paddle_engine.py) for a possible future
# x86_64 deployment, but it must not be reachable from this API.
PRODUCTION_ENGINES = ("easyocr",)
SUPPORTED_ENGINES = PRODUCTION_ENGINES + ("stub",)

_singletons: dict[str, OCREngine] = {}


def get_ocr_engine(engine_name: str) -> OCREngine:
    """
    Return an OCREngine instance for the given name. Engines are cached
    as singletons (one instance per engine name per process) since the
    PaddleOCR/EasyOCR implementations already do their own model-level
    caching internally -- this just avoids re-constructing the thin
    wrapper object on every call.
    """
    if engine_name not in SUPPORTED_ENGINES:
        raise ValidationFailedException(
            f"Unknown OCR engine '{engine_name}'. Supported engines: {list(SUPPORTED_ENGINES)}"
        )

    if engine_name not in _singletons:
        if engine_name == "paddleocr":
            _singletons[engine_name] = PaddleOCREngine()
        elif engine_name == "easyocr":
            _singletons[engine_name] = EasyOCREngine()
        elif engine_name == "stub":
            _singletons[engine_name] = StubOCREngine()

    return _singletons[engine_name]


def get_engine_status() -> dict[str, dict]:
    """
    Report availability of every supported engine without running
    actual inference. Used by the /ocr/engines endpoint so the frontend
    can show which engines are realistically usable in the current
    deployment.
    """
    status = {}
    for engine_name in SUPPORTED_ENGINES:
        engine = get_ocr_engine(engine_name)
        available, reason = engine.is_available()
        status[engine_name] = {
            "available": available,
            "reason": reason,
            "is_production_engine": engine_name in PRODUCTION_ENGINES,
        }
    return status
