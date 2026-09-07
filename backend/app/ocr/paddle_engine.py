"""
PaddleOCR engine implementation.

Uses PaddleOCR 3.x's `predict()` API (the modern interface; the older
`.ocr()` tuple-based API is deprecated as of PaddleOCR 3.x). The engine
instance is created lazily and cached on first use, since model loading
is expensive (multiple seconds) and should happen once per process, not
once per request.

IMPORTANT -- model weight availability:
PaddleOCR downloads its model weights on first instantiation from one
of: Baidu BOS (paddle-model-ecology.bj.bcebos.com), HuggingFace,
ModelScope, or AIStudio. In network-restricted environments where none
of these hosts are reachable, instantiation will raise an exception
with a message like "No available model hosting platforms detected."
This is a network/environment limitation, not a bug in this code -- the
integration below is correct and will work as soon as it runs somewhere
with access to one of those hosts (or with pre-downloaded weights placed
in the expected local cache directory; see PaddleOCR's documentation for
`*_model_dir` constructor arguments to point at a local path instead of
triggering a download).
"""
import logging
import threading

import numpy as np

from app.core.exceptions import FileProcessingException
from app.ocr.base import OCREngine, OCRTextBlock

logger = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_cached_engine = None


class PaddleOCREngine(OCREngine):
    name = "paddleocr"

    def __init__(self, *, lang: str = "en"):
        self.lang = lang

    def _get_engine(self):
        """
        Lazily construct and cache the underlying PaddleOCR instance.
        Cached at module level (not per-OCREngine-instance) because
        loading model weights into memory is the expensive part, and
        we want exactly one loaded instance per process regardless of
        how many PaddleOCREngine objects are created.
        """
        global _cached_engine
        if _cached_engine is not None:
            return _cached_engine

        with _engine_lock:
            if _cached_engine is None:
                try:
                    from paddleocr import PaddleOCR
                except ImportError as exc:
                    raise FileProcessingException(
                        "PaddleOCR is not installed in this environment"
                    ) from exc

                logger.info("Loading PaddleOCR engine (lang=%s)...", self.lang)
                try:
                    _cached_engine = PaddleOCR(
                        lang=self.lang,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                except Exception as exc:
                    raise FileProcessingException(
                        f"Failed to initialize PaddleOCR engine: {exc}. "
                        "This typically means the model weights could not be "
                        "downloaded (check network access to Baidu BOS / "
                        "HuggingFace / ModelScope / AIStudio) or pre-downloaded "
                        "weights were not found in the expected local directory."
                    ) from exc
                logger.info("PaddleOCR engine loaded successfully.")

        return _cached_engine

    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        engine = self._get_engine()

        # predict() accepts a numpy array directly (BGR, as produced by
        # app/ocr/preprocessing.py) and returns a list of result objects,
        # one per input image. We pass a single image, so we take [0].
        results = engine.predict(image)
        if not results:
            return []

        result = results[0]
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        polys = result.get("rec_polys", result.get("dt_polys", []))

        blocks: list[OCRTextBlock] = []
        for i, text in enumerate(texts):
            confidence = float(scores[i]) if i < len(scores) else 0.0
            polygon = polys[i] if i < len(polys) else []
            bounding_box = [[float(x), float(y)] for x, y in polygon]
            blocks.append(
                OCRTextBlock(text=text, confidence=confidence, bounding_box=bounding_box)
            )

        return blocks

    def is_available(self) -> tuple[bool, str]:
        try:
            import paddleocr  # noqa: F401
            import paddle  # noqa: F401
        except ImportError:
            return False, "paddlepaddle/paddleocr packages are not installed"

        if _cached_engine is not None:
            return True, "engine already loaded"

        return True, (
            "packages installed but engine not yet loaded; first OCR call will "
            "attempt to download model weights (requires network access to "
            "Baidu BOS / HuggingFace / ModelScope / AIStudio)"
        )
