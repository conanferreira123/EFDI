"""
Docling OCR & Document Parsing Engine implementation for EFDI.

Directly processes PDF and image documents via Docling's DocumentConverter,
leveraging native PDF parsing, OCR, layout analysis, and TableFormer table
structure recognition to produce canonical structured Markdown (with clean
pipe-delimited tables) and layout detections.

Bypasses EFDI-side PDF rasterization and adaptive preprocessing.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from app.core.config import settings
from app.core.exceptions import FileProcessingException
from app.ocr.base import OCREngine, OCRPageResult, OCRResult as OCRResultData, OCRTextBlock

logger = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_cached_converter = None


class DoclingEngine(OCREngine):
    name = "docling"

    def __init__(
        self,
        *,
        do_ocr: bool = True,
        do_table_structure: bool = True,
        do_cell_matching: bool = True,
    ):
        self.do_ocr = do_ocr
        self.do_table_structure = do_table_structure
        self.do_cell_matching = do_cell_matching

    def _get_converter(self):
        global _cached_converter
        if _cached_converter is not None:
            return _cached_converter

        with _engine_lock:
            if _cached_converter is None:
                try:
                    from docling.document_converter import DocumentConverter, PdfFormatOption
                    from docling.datamodel.base_models import InputFormat
                    from docling.datamodel.pipeline_options import PdfPipelineOptions
                except ImportError as exc:
                    raise FileProcessingException(
                        "Docling is not installed in this environment"
                    ) from exc

                logger.info(
                    "Loading Docling DocumentConverter (do_ocr=%s, do_table_structure=%s, do_cell_matching=%s)...",
                    self.do_ocr,
                    self.do_table_structure,
                    self.do_cell_matching,
                )
                try:
                    pipeline_options = PdfPipelineOptions()
                    pipeline_options.do_ocr = self.do_ocr
                    pipeline_options.do_table_structure = self.do_table_structure
                    pipeline_options.table_structure_options.do_cell_matching = self.do_cell_matching

                    _cached_converter = DocumentConverter(
                        format_options={
                            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                        }
                    )
                except Exception as exc:
                    raise FileProcessingException(
                        f"Failed to initialize Docling engine: {exc}"
                    ) from exc
                logger.info("Docling DocumentConverter loaded successfully.")

        return _cached_converter

    def extract_from_file(self, file_path: Union[str, Path]) -> OCRResultData:
        """
        Process a document file (PDF or image) directly using Docling.
        Directly submits the file to Docling's DocumentConverter, letting internal
        parsers and TableFormer handle rendering, layout, and table recognition.
        """
        converter = self._get_converter()
        path_obj = Path(file_path).resolve()
        file_str = str(path_obj)

        if not path_obj.exists():
            raise FileProcessingException(f"Document file not found: {file_str}")

        t0 = time.perf_counter()
        try:
            conv_result = converter.convert(path_obj)
        except Exception as exc:
            logger.exception("Docling conversion failed for %s", file_str)
            raise FileProcessingException(f"Docling conversion failed: {exc}") from exc
        t_conv = time.perf_counter() - t0

        doc = conv_result.document
        if doc is None:
            return OCRResultData(engine_name=self.name)

        result_data = OCRResultData(engine_name=self.name)
        page_dict: Dict[int, Any] = getattr(doc, "pages", {})
        num_pages = len(page_dict) if page_dict else 1

        # Multi-page markdown aggregation
        t_md_start = time.perf_counter()
        page_markdowns: List[str] = []
        is_multi_page = num_pages > 1

        if is_multi_page:
            for page_idx in range(1, num_pages + 1):
                try:
                    page_md = doc.export_to_markdown(page_no=page_idx, traverse_pictures=True).strip()
                except Exception as md_err:
                    logger.warning("Could not export markdown for page %s: %s", page_idx, md_err)
                    page_md = ""
                page_markdowns.append(f"=== PAGE {page_idx} ===\n{page_md}")
            full_markdown = "\n\n".join(page_markdowns).strip()
        else:
            try:
                full_markdown = doc.export_to_markdown(traverse_pictures=True).strip()
            except Exception as md_err:
                logger.warning("Could not export markdown: %s", md_err)
                full_markdown = ""
            page_markdowns.append(full_markdown)

        t_md = time.perf_counter() - t_md_start

        # Layout blocks & visual provenance extraction
        # Adapts Docling bounding boxes into EFDI's standard OCRTextBlock & raw_blocks format
        page_blocks: Dict[int, List[OCRTextBlock]] = {p: [] for p in range(1, num_pages + 1)}

        try:
            for item, _level in doc.iterate_items():
                text = getattr(item, "text", "")
                if not text or not text.strip():
                    continue

                prov_list = getattr(item, "prov", [])
                if not prov_list:
                    continue

                for prov in prov_list:
                    p_no = getattr(prov, "page_no", 1)
                    bbox = getattr(prov, "bbox", None)
                    if p_no not in page_blocks:
                        page_blocks[p_no] = []

                    polygon: List[List[float]] = []
                    if bbox is not None:
                        # Convert bbox to top-left origin coordinates if page height is available
                        page_obj = page_dict.get(p_no)
                        page_h = getattr(page_obj.size, "height", 1400.0) if (page_obj and hasattr(page_obj, "size")) else 1400.0
                        
                        if hasattr(bbox, "to_top_left_origin"):
                            try:
                                tl_bbox = bbox.to_top_left_origin(page_h)
                                x0, y0, x1, y1 = float(tl_bbox.l), float(tl_bbox.t), float(tl_bbox.r), float(tl_bbox.b)
                            except Exception:
                                x0, y0, x1, y1 = float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)
                        else:
                            x0, y0, x1, y1 = float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)

                        polygon = [
                            [x0, y0],
                            [x1, y0],
                            [x1, y1],
                            [x0, y1],
                        ]

                    page_blocks[p_no].append(
                        OCRTextBlock(
                            text=text.strip(),
                            confidence=0.98,
                            bounding_box=polygon,
                        )
                    )
        except Exception as prov_err:
            logger.warning("Error extracting provenance/blocks from Docling: %s", prov_err)

        # Assemble OCRPageResult objects
        for p_idx in range(1, num_pages + 1):
            p_blocks = page_blocks.get(p_idx, [])
            p_md = page_markdowns[p_idx - 1] if p_idx <= len(page_markdowns) else ""
            page_result = OCRPageResult(page_number=p_idx, blocks=p_blocks, custom_full_text=p_md)
            result_data.pages.append(page_result)

        result_data.custom_full_text = full_markdown
        result_data.docling_document = doc
        logger.info(
            "Docling completed for %s: pages=%s, conv_time=%.2fs, md_time=%.2fs",
            file_str,
            num_pages,
            t_conv,
            t_md,
        )
        return result_data

    def extract_text_blocks(self, image: np.ndarray) -> list[OCRTextBlock]:
        """
        Fallback implementation for in-memory image array input.
        Saves temporarily to run through DocumentConverter.
        """
        import tempfile
        import cv2

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            cv2.imwrite(str(tmp_path), image)
            res = self.extract_from_file(tmp_path)
            if res.pages and res.pages[0].blocks:
                return res.pages[0].blocks
            return []
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def is_available(self) -> tuple[bool, str]:
        try:
            import docling  # noqa: F401
            from docling.document_converter import DocumentConverter  # noqa: F401
        except ImportError:
            return False, "docling package is not installed"

        if _cached_converter is not None:
            return True, "Docling engine already loaded"

        return True, "Docling engine ready (first run will initialize models)"
