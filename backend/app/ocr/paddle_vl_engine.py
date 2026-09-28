"""
PaddleOCR-VL-1.6 Engine implementation for EFDI.

Directly processes PDF and image documents via PaddleOCR-VL-1.6, producing
canonical structured Markdown (with clean Markdown tables) and layout detections.
Bypasses EFDI-side PDF rasterization and adaptive preprocessing.
"""
import logging
import threading
from pathlib import Path
from typing import Any, List, Optional, Union
import numpy as np

from app.core.config import settings
from app.core.exceptions import FileProcessingException
from app.ocr.base import OCREngine, OCRPageResult, OCRResult as OCRResultData, OCRTextBlock

logger = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_cached_engine = None


class PaddleOCRVLEngine(OCREngine):
    name = "paddleocr-vl-1.6"

    def __init__(self, *, pipeline_version: str = "v1.6", device: Optional[str] = None):
        self.pipeline_version = pipeline_version
        self.device = device or getattr(settings, "PADDLE_VL_DEVICE", "cpu")

    def _get_engine(self):
        global _cached_engine
        if _cached_engine is not None:
            return _cached_engine

        with _engine_lock:
            if _cached_engine is None:
                try:
                    from paddleocr import PaddleOCRVL
                except ImportError as exc:
                    raise FileProcessingException(
                        "PaddleOCR / PaddleOCRVL is not installed in this environment"
                    ) from exc

                logger.info(
                    "Loading PaddleOCR-VL engine (pipeline_version=%s, device=%s)...",
                    self.pipeline_version,
                    self.device,
                )
                try:
                    _cached_engine = PaddleOCRVL(
                        pipeline_version=self.pipeline_version,
                        device=self.device,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                    )
                except Exception as exc:
                    raise FileProcessingException(
                        f"Failed to initialize PaddleOCR-VL engine: {exc}"
                    ) from exc
                logger.info("PaddleOCR-VL engine loaded successfully.")

        return _cached_engine

    def extract_from_file(self, file_path: Union[str, Path]) -> OCRResultData:
        """
        Process a document file (PDF or image) directly using PaddleOCR-VL.
        Directly submits the file to PaddleOCR-VL, letting internal PDFReader handle
        rendering without EFDI-side PyMuPDF rasterization.
        """
        engine = self._get_engine()
        file_str = str(file_path)

        try:
            results = engine.predict(file_str)
        except Exception as exc:
            logger.exception("PaddleOCR-VL inference failed for %s", file_str)
            raise FileProcessingException(f"PaddleOCR-VL inference failed: {exc}") from exc

        if not results:
            return OCRResultData(engine_name=self.name)

        result_data = OCRResultData(engine_name=self.name)
        page_markdowns: List[str] = []
        is_multi_page = len(results) > 1

        for page_idx, res in enumerate(results, start=1):
            # Extract native markdown representation
            page_md = ""
            if hasattr(res, "markdown") and isinstance(res.markdown, dict):
                page_md = res.markdown.get("markdown", "")
            elif hasattr(res, "_to_markdown"):
                try:
                    md_dict = res._to_markdown(pretty=False)
                    page_md = md_dict.get("markdown", "") if isinstance(md_dict, dict) else str(md_dict)
                except Exception as md_err:
                    logger.warning("Could not extract markdown via _to_markdown: %s", md_err)

            if not page_md and hasattr(res, "str") and isinstance(res.str, dict):
                page_md = res.str.get("res", "")

            # Extract layout element blocks for raw_blocks & visual provenance
            blocks: List[OCRTextBlock] = []
            parsing_res_list = res.get("parsing_res_list", []) if isinstance(res, dict) else getattr(res, "get", lambda k, d=None: [])("parsing_res_list", [])

            for b in parsing_res_list:
                content = getattr(b, "content", "") if hasattr(b, "content") else b.get("block_content", "")
                bbox_raw = getattr(b, "bbox", []) if hasattr(b, "bbox") else b.get("block_bbox", [])
                
                # Convert bbox [x0, y0, x1, y1] to 4-point polygon [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                polygon: List[List[float]] = []
                if len(bbox_raw) == 4:
                    x0, y0, x1, y1 = [float(v) for v in bbox_raw]
                    polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

                if content:
                    blocks.append(
                        OCRTextBlock(
                            text=content,
                            confidence=0.98,
                            bounding_box=polygon,
                        )
                    )

            page_result = OCRPageResult(page_number=page_idx, blocks=blocks, custom_full_text=page_md)
            result_data.pages.append(page_result)

            if is_multi_page:
                page_markdowns.append(f"=== PAGE {page_idx} ===\n{page_md.strip()}")
            else:
                page_markdowns.append(page_md.strip())

        # Set canonical full_text as the joined Markdown document
        result_data.custom_full_text = "\n\n".join(page_markdowns).strip()
        return result_data

    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        """
        Fallback implementation of abstract OCREngine method for in-memory images.
        """
        engine = self._get_engine()
        results = engine.predict(image)
        if not results:
            return []

        blocks: list[OCRTextBlock] = []
        res = results[0]
        parsing_res_list = res.get("parsing_res_list", []) if isinstance(res, dict) else getattr(res, "get", lambda k, d=None: [])("parsing_res_list", [])

        for b in parsing_res_list:
            content = getattr(b, "content", "") if hasattr(b, "content") else b.get("block_content", "")
            bbox_raw = getattr(b, "bbox", []) if hasattr(b, "bbox") else b.get("block_bbox", [])
            polygon: List[List[float]] = []
            if len(bbox_raw) == 4:
                x0, y0, x1, y1 = [float(v) for v in bbox_raw]
                polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

            if content:
                blocks.append(
                    OCRTextBlock(
                        text=content,
                        confidence=0.98,
                        bounding_box=polygon,
                    )
                )

        return blocks

    def is_available(self) -> tuple[bool, str]:
        try:
            import paddleocr  # noqa: F401
            import paddle  # noqa: F401
            from paddleocr import PaddleOCRVL  # noqa: F401
        except ImportError:
            return False, "paddleocr / paddlepaddle packages are not installed"

        if _cached_engine is not None:
            return True, "engine already loaded"

        return True, "PaddleOCR-VL-1.6 engine ready (first run will initialize model weights)"
