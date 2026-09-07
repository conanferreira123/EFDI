"""
Extraction service: orchestrates running field extraction against the
latest OCR text for the document's latest classified type, persisting
the result, and advancing Document.status to EXTRACTED.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundException, ValidationFailedException
from app.extraction.base import ExtractionContext
from app.extraction.factory import get_extraction_engine
from app.extraction.field_schemas import get_full_field_schema
from app.extraction.primitives import normalize_amount, normalize_date
from app.extraction.rag_diagnostic import RAGDiagnosticService
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.ocr.normalization import normalize_table_data
from app.ocr.quality_scoring import calculate_quality_score
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.validation import validate_ocr_output
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.repositories.ocr_result_repository import OCRResultRepository

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, db: Session):
        self.db = db
        self.document_repo = DocumentRepository(db)
        self.ocr_repo = OCRResultRepository(db)
        self.classification_repo = ClassificationResultRepository(db)
        self.extraction_repo = ExtractionResultRepository(db)
        self.rag_diagnostic = RAGDiagnosticService(db)

    def extract(self, document: Document, *, engine_name: str | None = None):
        ocr_result = self.ocr_repo.get_latest_for_document(document.id)
        if not ocr_result:
            raise ValidationFailedException(
                "Cannot extract fields from a document with no OCR result. "
                "Run OCR first via POST /ocr/documents/{id}/run."
            )

        classification_result = self.classification_repo.get_latest_for_document(document.id)
        if not classification_result:
            raise ValidationFailedException(
                "Cannot extract fields from a document with no classification result. "
                "Run classification first via POST /classification/documents/{id}/classify."
            )

        document_type = classification_result.predicted_type
        chosen_engine = engine_name or getattr(settings, "EXTRACTION_DEFAULT_ENGINE", "rule_based")

        # Build ExtractionContext with full_text, document_type, raw_blocks, and derived OCR structures
        raw_blocks = ocr_result.raw_blocks or []
        table_data = None
        normalized_data = None
        ocr_validation = None
        ocr_quality = None

        if raw_blocks:
            try:
                all_page_blocks = raw_blocks[0].get("blocks", []) if raw_blocks else []
                pw = float(raw_blocks[0].get("page_width", 1000.0))
                ph = float(raw_blocks[0].get("page_height", 1400.0))

                table_obj = reconstruct_table(all_page_blocks, page_width=pw, page_height=ph)
                table_data = table_obj.to_dict()
                normalized_items = normalize_table_data(table_data)
                normalized_data = {"line_items": [item.to_dict() for item in normalized_items]}
                val_res = validate_ocr_output(normalized_items, raw_full_text=ocr_result.full_text)
                ocr_validation = val_res.to_dict()
                avg_conf = (
                    float(ocr_result.average_confidence)
                    if ocr_result.average_confidence is not None
                    else 1.0
                )
                quality_res = calculate_quality_score(
                    avg_confidence=avg_conf,
                    full_text=ocr_result.full_text,
                    table_data=table_data,
                    validation_result=val_res,
                )
                ocr_quality = quality_res.to_dict()
            except Exception as exc:
                logger.warning("Could not compute derived OCR structures for context: %s", exc)

        context = ExtractionContext(
            full_text=ocr_result.full_text,
            document_type=document_type,
            raw_blocks=raw_blocks,
            table_data=table_data,
            normalized_data=normalized_data,
            ocr_validation=ocr_validation,
            ocr_quality=ocr_quality,
            document_id=document.id,
        )

        engine = get_extraction_engine(chosen_engine)
        result_data = engine.extract(context)


        # Run RAG diagnostic pass if requested or on LLM extraction with multi-page / edge cases
        if chosen_engine in ("llm_rag", "llm_based"):
            page_count = ocr_result.page_count or 1
            result_data = self.rag_diagnostic.diagnose_and_refine(
                document.id, result_data, page_count=page_count
            )

        fields_payload = {
            key: {
                "value": f.value,
                "confidence": f.confidence,
                "matched_text": f.matched_text,
                "is_found": f.is_found,
                "manually_entered": False,
                "provenance": getattr(f, "provenance", "rule_based" if result_data.engine_name == "rule_based" else "llm"),
                "conflict_value": getattr(f, "conflict_value", None),
            }
            for key, f in result_data.fields.items()
        }


        extraction_result = self.extraction_repo.create(
            document_id=document.id,
            document_type=document_type,
            engine_name=result_data.engine_name,
            fields=fields_payload,
            overall_confidence=result_data.overall_confidence,
            fields_found_count=result_data.fields_found_count,
            fields_total_count=result_data.fields_total_count,
        )

        # Extraction is what advances the workflow to EXTRACTED -- the
        # combined "classify + extract" conceptual step from the spec,
        # even though they are separate phases/code (per design decision
        # made in Phase 5).
        self.document_repo.update_status(document, DocumentStatus.EXTRACTED.value)

        logger.info(
            "Document extracted: document_id=%s type=%s fields=%s/%s confidence=%.2f",
            document.id, document_type, result_data.fields_found_count,
            result_data.fields_total_count, result_data.overall_confidence,
        )

        return extraction_result

    def get_latest_result(self, document_id: int):
        return self.extraction_repo.get_latest_for_document(document_id)

    def list_results(self, document_id: int):
        return self.extraction_repo.list_for_document(document_id)

    def update_field(self, document_id: int, field_key: str, value: str):
        extraction_result = self.extraction_repo.get_latest_for_document(document_id)
        if not extraction_result:
            raise NotFoundException("Extraction result for document", document_id)

        if field_key not in extraction_result.fields:
            raise ValidationFailedException(
                f"Field '{field_key}' is not part of this document's extraction schema."
            )

        # A manual correction must be normalized the same way automatic
        # extraction normalizes a value -- otherwise a user typing a
        # perfectly valid date like "21/03/2012" gets stored verbatim
        # and then rejected by validation, which requires ISO format
        # (validation assumes extraction already normalized it, which
        # was true for automatic extraction but not for this manual
        # path). Look up the field's declared type and apply the same
        # normalize_date/normalize_amount used during extraction; if
        # normalization fails, fall back to the raw value so the user's
        # input is never silently discarded -- validation will then
        # correctly flag it as a format error for them to fix.
        schema = get_full_field_schema(extraction_result.document_type)
        field_def = next((f for f in schema if f.key == field_key), None)
        normalized_value = value
        if field_def and value:
            if field_def.field_type == "date":
                normalized_value = normalize_date(value) or value
            elif field_def.field_type == "amount":
                normalized_value = normalize_amount(value) or value

        updated = self.extraction_repo.update_field(extraction_result, field_key, normalized_value)
        logger.info(
            "Field manually corrected: document_id=%s field=%s", document_id, field_key
        )
        return updated

    def get_export_rows(self, document_id: int) -> list[dict]:
        """
        Returns the latest extraction result's fields as a flat list of
        {key, label, value, confidence, is_found} dicts, in the same
        display order as the field schema -- this is the one shared
        data shape all three export formats (JSON/CSV/Excel) are built
        from, so adding a fourth format later only means adding a new
        serializer, not re-deriving this data again.
        """
        extraction_result = self.extraction_repo.get_latest_for_document(document_id)
        if not extraction_result:
            raise NotFoundException("Extraction result for document", document_id)

        schema = get_full_field_schema(extraction_result.document_type)
        label_by_key = {field_def.key: field_def.label for field_def in schema}

        rows = []
        for key, field_data in extraction_result.fields.items():
            rows.append({
                "key": key,
                "label": label_by_key.get(key, key),
                "value": field_data.get("value"),
                "confidence": field_data.get("confidence"),
                "is_found": field_data.get("is_found", False),
            })

        # Sort to match the schema's declared display order (dict
        # iteration order on `fields` isn't guaranteed to match it,
        # since fields are stored as a plain JSONB dict).
        schema_order = {field_def.key: i for i, field_def in enumerate(schema)}
        rows.sort(key=lambda r: schema_order.get(r["key"], len(schema_order)))

        return rows
