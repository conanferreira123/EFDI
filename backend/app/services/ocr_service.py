"""
OCR service: orchestrates the end-to-end OCR pipeline for a document.

Flow: load file bytes from disk -> rasterize (PDF) or decode (image) ->
preprocess each page -> run the selected OCR engine -> aggregate into
an OCRResult -> persist -> advance Document.status to OCR_COMPLETED.
"""
# pyrefly: ignore [missing-import]
from app.models.system_setting import SystemSetting
from sqlalchemy.orm import Session


def get_default_ocr_engine(db) -> str:
    """Retrieve the globally configured OCR engine name.
    If not set, fall back to settings.OCR_DEFAULT_ENGINE.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "default_ocr_engine").first()
    return setting.value if setting else settings.OCR_DEFAULT_ENGINE
import logging
import time

from app.core.config import settings
from app.core.exceptions import FileProcessingException
from app.models.document import Document
from app.models.document_enums import DocumentStatus, AuditAction
from app.models.ocr_result import OCRResult
from app.ocr.adaptive_preprocessing import AdaptivePreprocessor
from app.ocr.base import OCRPageResult, OCRResult as OCRResultData
from app.ocr.factory import get_ocr_engine
from app.ocr.layout import build_structured_page, generate_structured_full_text, order_blocks_spatially
from app.ocr.normalization import normalize_table_data
from app.ocr.preprocessing import load_image_bytes, preprocess_for_ocr, rasterize_pdf
from app.ocr.quality_scoring import calculate_quality_score
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.validation import validate_ocr_output
from app.repositories.document_repository import DocumentRepository
from app.repositories.ocr_result_repository import OCRResultRepository
from app.utils.file_storage import get_file_path

# Import audit service for logging OCR lifecycle events
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class OCRService:
    def __init__(self, db: Session):
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.ocr_repo = OCRResultRepository(db)

    def run_ocr(self, document: Document, *, engine_name: str | None = None) -> OCRResult:
        engine_name = engine_name or settings.OCR_DEFAULT_ENGINE
        # Log OCR start event
        audit_service = AuditService(self.db)
        audit_service.log(
            action=AuditAction.OCR_STARTED,
            user_id=None,
            document_id=document.id,
            details={"engine": engine_name},
        )
        try:
            engine = get_ocr_engine(engine_name)

            file_path = get_file_path(document.stored_filename)
            if not file_path.exists():
                raise FileProcessingException(
                    f"Document file not found on disk: {document.stored_filename}"
                )

            with open(file_path, "rb") as f:
                file_bytes = f.read()

            start_time = time.monotonic()

            if engine_name in ("docling", "paddleocr-vl-1.6") or hasattr(engine, "extract_from_file"):
                # Docling / Modern File-Level Target Architecture:
                # PDF -> Docling -> Business Validation -> DB / RAG
                # Direct file path input: no EFDI-side PyMuPDF rasterization, no OpenCV preprocessing
                from app.ocr.markdown_table_parser import parse_markdown_table

                result_data = engine.extract_from_file(file_path)
                strategy = "DOCLING_NATIVE" if engine_name == "docling" else "PADDLEOCR_VL_NATIVE"
                preprocessing_decisions = [{"strategy_name": strategy}]

                raw_blocks = [
                    {
                        "page_number": p.page_number,
                        "page_width": 1000.0,
                        "page_height": 1400.0,
                        "blocks": [
                            {
                                "text": block.text,
                                "confidence": block.confidence,
                                "bounding_box": block.bounding_box,
                            }
                            for block in p.blocks
                        ],
                    }
                    for p in result_data.pages
                ]

                # Business validation on native Markdown table output (runtime in-memory)
                table_dict = parse_markdown_table(result_data.full_text)
                normalized_items = normalize_table_data(table_dict)
                validation_res = validate_ocr_output(normalized_items, raw_full_text=result_data.full_text)
                quality_breakdown = calculate_quality_score(
                    avg_confidence=result_data.average_confidence,
                    full_text=result_data.full_text,
                    table_data=table_dict,
                    validation_result=validation_res,
                )
                table_items_count = len(table_dict.get("line_items", []))
            else:
                # Legacy EasyOCR pipeline:
                # PDF -> Rasterize -> Preprocess -> EasyOCR -> Spatial Order -> Table Reconstruction -> Normalization -> Validation
                preprocessing_decisions = []
                if document.mime_type == "application/pdf":
                    pages = rasterize_pdf(file_bytes)
                    preprocessed_pages = []
                    for p in pages:
                        proc_img, decision = AdaptivePreprocessor.process(p)
                        preprocessed_pages.append(proc_img)
                        preprocessing_decisions.append(decision.to_dict())
                else:
                    image = load_image_bytes(file_bytes)
                    proc_img, decision = AdaptivePreprocessor.process(image)
                    preprocessed_pages = [proc_img]
                    preprocessing_decisions.append(decision.to_dict())

                result_data = OCRResultData(engine_name=engine.name)
                raw_blocks = []
                structured_pages = []

                for page_number, page_image in enumerate(preprocessed_pages, start=1):
                    raw_extracted_blocks = engine.extract_text_blocks(page_image)
                    page_h, page_w = page_image.shape[:2]

                    # Preserve 100% original raw OCR detections for auditing / debugging
                    raw_blocks.append({
                        "page_number": page_number,
                        "page_width": page_w,
                        "page_height": page_h,
                        "blocks": [
                            {
                                "text": block.text,
                                "confidence": block.confidence,
                                "bounding_box": block.bounding_box,
                            }
                            for block in raw_extracted_blocks
                        ],
                    })

                    # Reconstruct table and build structured page intermediate representation
                    table_obj = reconstruct_table(
                        raw_extracted_blocks, page_width=page_w, page_height=page_h
                    )
                    structured_page = build_structured_page(
                        raw_extracted_blocks,
                        table=table_obj,
                        page_width=page_w,
                        page_height=page_h,
                        page_number=page_number,
                    )
                    structured_pages.append(structured_page)

                    ordered_blocks = order_blocks_spatially(
                        raw_extracted_blocks, page_width=page_w, page_height=page_h
                    )
                    result_data.pages.append(
                        OCRPageResult(page_number=page_number, blocks=ordered_blocks)
                    )

                # Generate structured full_text from structured document representation
                if getattr(settings, "ENABLE_STRUCTURED_FULL_TEXT", True):
                    structured_full_text = generate_structured_full_text(structured_pages)
                    result_data.custom_full_text = structured_full_text

                # Downstream Roadmap Processing: Table -> Normalization -> Validation -> Quality
                all_page_blocks = raw_blocks[0].get("blocks", []) if raw_blocks else []
                pw = raw_blocks[0].get("page_width", 1000.0) if raw_blocks else 1000.0
                ph = raw_blocks[0].get("page_height", 1400.0) if raw_blocks else 1400.0

                table_obj = reconstruct_table(all_page_blocks, page_width=pw, page_height=ph)
                table_dict = table_obj.to_dict()
                normalized_items = normalize_table_data(table_dict)
                validation_res = validate_ocr_output(normalized_items, raw_full_text=result_data.full_text)
                quality_breakdown = calculate_quality_score(
                    avg_confidence=result_data.average_confidence,
                    full_text=result_data.full_text,
                    table_data=table_dict,
                    validation_result=validation_res,
                )
                table_items_count = len(table_obj.line_items)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            # Determine final document status based on OCR output
            if not result_data.full_text.strip():
                # No text extracted – mark as REJECTED
                final_status = DocumentStatus.REJECTED.value
                audit_action = AuditAction.DOCUMENT_REJECTED
            else:
                final_status = DocumentStatus.OCR_COMPLETED.value
                audit_action = None

            # Persist the OCRResult
            ocr_result = self.ocr_repo.create(
                document_id=document.id,
                engine_name=result_data.engine_name,
                page_count=result_data.page_count,
                full_text=result_data.full_text,
                average_confidence=result_data.average_confidence,
                raw_blocks=raw_blocks,
                processing_time_ms=elapsed_ms,
            )

            # Update document status accordingly
            self.document_repo.update_status(document, final_status)

            # Trigger non-blocking RAG ingestion hook after successful OCR_COMPLETED
            if final_status == DocumentStatus.OCR_COMPLETED.value:
                try:
                    from app.services.rag_ingestion_service import get_rag_ingestion_service

                    get_rag_ingestion_service().ingest_document_async(document.id)
                except Exception as rag_err:
                    logger.warning(
                        "Failed to trigger async RAG ingestion for document %s: %s",
                        document.id,
                        rag_err,
                    )

            # Log enriched OCR completed event
            audit_service.log(
                action=AuditAction.OCR_COMPLETED,
                user_id=None,
                document_id=document.id,
                details={
                    "engine": engine_name,
                    "status": final_status,
                    "table_items_count": table_items_count,
                    "quality_score": quality_breakdown.overall_quality_score,
                    "quality_grade": quality_breakdown.quality_grade,
                    "validation_passed": validation_res.is_valid,
                    "preprocessing_strategy": preprocessing_decisions[0].get("strategy_name") if preprocessing_decisions else "STANDARD",
                },
            )

            # Log rejection if applicable
            if audit_action:
                audit_service.log(
                    action=audit_action,
                    user_id=None,
                    document_id=document.id,
                    details={"reason": "OCR extracted no text"},
                )

            logger.info(
                "OCR completed: document_id=%s engine=%s pages=%s avg_confidence=%.2f time_ms=%s status=%s",
                document.id,
                engine.name,
                result_data.page_count,
                result_data.average_confidence,
                elapsed_ms,
                final_status,
            )

            return ocr_result
        except Exception as exc:
            # Log OCR failure
            audit_service.log(
                action=AuditAction.OCR_FAILED,
                user_id=None,
                document_id=document.id,
                details={"engine": engine_name, "error": str(exc)},
            )
            logger.exception("OCR failed for document %s", document.id)
            raise

    def get_latest_result(self, document_id: int) -> OCRResult | None:
        return self.ocr_repo.get_latest_for_document(document_id)

    def list_results(self, document_id: int) -> list[OCRResult]:
        return self.ocr_repo.list_for_document(document_id)
