"""
EasyOCR engine implementation.

Uses EasyOCR's `Reader.readtext(image, detail=1)` API, which returns a
list of (bounding_box, text, confidence) tuples. The Reader instance is
created lazily and cached at module level, since loading model weights
is expensive and should happen once per process.

IMPORTANT -- dependency availability:
EasyOCR requires PyTorch. In this environment, the only `torch` wheel
reachable via the configured network allowlist is the CUDA-linked
PyPI build, which fails at import time on a machine without NVIDIA
drivers/libraries (it dynamically links against libcudart.so /
libcublasLt.so even when gpu=False is requested at runtime). The
CPU-only wheels are distributed exclusively from
download.pytorch.org, which is not on this environment's allowlist.

This is an environment/network limitation, not a bug in the integration
below -- on any machine with either (a) a CPU-only torch wheel
installed from download.pytorch.org, or (b) an NVIDIA GPU + drivers
present, `pip install easyocr` followed by this code will work
correctly. Model weights are downloaded from Jaided AI's model server
on first Reader() instantiation (or can be pre-placed in
~/.EasyOCR/model/ to skip the download).
"""
import logging
import threading

import numpy as np

from app.core.exceptions import FileProcessingException
from app.ocr.base import OCREngine, OCRTextBlock

logger = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_cached_reader = None


class EasyOCREngine(OCREngine):
    name = "easyocr"

    def __init__(self, *, lang_list: list[str] | None = None, gpu: bool = False):
        self.lang_list = lang_list or ["en"]
        self.gpu = gpu

    def _get_reader(self):
        global _cached_reader
        if _cached_reader is not None:
            return _cached_reader

        with _engine_lock:
            if _cached_reader is None:
                try:
                    import easyocr
                except ImportError as exc:
                    raise FileProcessingException(
                        "EasyOCR is not installed in this environment"
                    ) from exc

                # Graceful CUDA check and CPU fallback
                use_gpu = self.gpu
                if use_gpu:
                    try:
                        import torch
                        if not torch.cuda.is_available():
                            logger.warning("GPU requested for EasyOCR, but CUDA is not available in PyTorch. Falling back to CPU.")
                            use_gpu = False
                    except Exception:
                        use_gpu = False

                logger.info("Loading EasyOCR engine (langs=%s, gpu=%s)...", self.lang_list, use_gpu)
                try:
                    _cached_reader = easyocr.Reader(self.lang_list, gpu=use_gpu)
                except Exception as exc:
                    if use_gpu:
                        logger.warning("GPU initialization failed (%s); attempting fallback to CPU.", exc)
                        try:
                            _cached_reader = easyocr.Reader(self.lang_list, gpu=False)
                        except Exception as fallback_exc:
                            raise FileProcessingException(
                                f"Failed to initialize EasyOCR engine: {fallback_exc}."
                            ) from fallback_exc
                    else:
                        raise FileProcessingException(
                            f"Failed to initialize EasyOCR engine: {exc}."
                        ) from exc
                logger.info("EasyOCR engine loaded successfully.")

        return _cached_reader

    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        reader = self._get_reader()

        # detail=1 returns [(bbox, text, confidence), ...]. bbox is a
        # list of 4 [x, y] corner points (already in the polygon format
        # our OCRTextBlock expects). add_margin=0.0 prevents bounding box
        # expansion that introduces underline/period artifacts.
        results = reader.readtext(image, detail=1, add_margin=0.0)

        blocks: list[OCRTextBlock] = []
        for bbox, text, confidence in results:
            bounding_box = [[float(x), float(y)] for x, y in bbox]
            blocks.append(
                OCRTextBlock(text=text, confidence=float(confidence), bounding_box=bounding_box)
            )

        return blocks

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
        except ImportError as exc:
            return False, f"torch is not importable: {exc}"
        except OSError as exc:
            return False, f"torch failed to load native libraries: {exc}"

        try:
            import easyocr  # noqa: F401
        except ImportError:
            return False, "easyocr package is not installed"

        if _cached_reader is not None:
            return True, "engine already loaded"

        return True, "packages installed but engine not yet loaded"
