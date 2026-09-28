"""
Extraction service: orchestrates running field extraction against the
latest OCR text for the document's latest classified type, persisting
the result, and advancing Document.status to EXTRACTED.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundException, ValidationFailedException
from app.extraction.base import ExtractedField, ExtractionContext
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

        if ocr_result.engine_name in ("docling", "paddleocr-vl-1.6"):
            try:
                from app.ocr.markdown_table_parser import parse_markdown_table

                table_data = parse_markdown_table(ocr_result.full_text)
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
                logger.warning("Could not compute derived OCR structures from Markdown table for context: %s", exc)
        elif raw_blocks:
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

        # Populate authoritative system metadata fields from document/application records
        result_data.fields["document_id"] = ExtractedField(
            value=str(document.id) if document.id is not None else None,
            confidence=1.0 if document.id is not None else 0.0,
            matched_text=None,
            provenance="system",
        )
        result_data.fields["processing_status"] = ExtractedField(
            value=DocumentStatus.EXTRACTED.value,
            confidence=1.0,
            matched_text=None,
            provenance="system",
        )
        result_data.fields["validation_status"] = ExtractedField(
            value=document.validation_status or "PENDING",
            confidence=1.0 if document.validation_status else 0.0,
            matched_text=None,
            provenance="system",
        )
        result_data.fields["company_code"] = ExtractedField(
            value=document.company_code,
            confidence=1.0 if document.company_code else 0.0,
            matched_text=None,
            provenance="system",
        )

        full_schema_keys = {f.key for f in get_full_field_schema(document_type)}
        if "vendor_code" in full_schema_keys:
            result_data.fields["vendor_code"] = ExtractedField(
                value=document.vendor_code,
                confidence=1.0 if document.vendor_code else 0.0,
                matched_text=None,
                provenance="system",
            )
        if "customer_code" in full_schema_keys:
            result_data.fields["customer_code"] = ExtractedField(
                value=getattr(document, "customer_code", None),
                confidence=1.0 if getattr(document, "customer_code", None) else 0.0,
                matched_text=None,
                provenance="system",
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

        # Synchronize extraction results to normalized relational business tables
        try:
            from app.services.invoice_persistence_service import InvoicePersistenceService
            persistence_svc = InvoicePersistenceService(self.db)
            persistence_svc.sync_from_extraction(document.id, extraction_result.id)
        except Exception as exc:
            logger.warning("Could not synchronize business data for document %d: %s", document.id, exc)

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

        is_npo = extraction_result.document_type == "NPO"
        if field_key not in extraction_result.fields:
            if is_npo:
                from app.extraction.field_schemas import (
                    NPO_IMPORTANT_OPTIONAL_PATHS,
                    NPO_MANDATORY_CORE_PATHS,
                    NPO_SYSTEM_METADATA_PATHS,
                )
                valid_npo_paths = NPO_MANDATORY_CORE_PATHS | NPO_IMPORTANT_OPTIONAL_PATHS | NPO_SYSTEM_METADATA_PATHS
                if field_key not in valid_npo_paths:
                    raise ValidationFailedException(
                        f"Field '{field_key}' is not part of this document's extraction schema."
                    )
            else:
                raise ValidationFailedException(
                    f"Field '{field_key}' is not part of this document's extraction schema."
                )

        schema = get_full_field_schema(extraction_result.document_type)
        field_def = next((f for f in schema if f.key == field_key), None)
        normalized_value = value
        if value:
            # Check type from schema or infer from dot-path leaf
            is_date = (field_def and field_def.field_type == "date") or "date" in field_key
            is_amount = (field_def and field_def.field_type == "amount") or any(
                term in field_key for term in ("total", "amount", "price", "subtotal", "tax_rate")
            )
            if is_date:
                normalized_value = normalize_date(value) or value
            elif is_amount:
                normalized_value = normalize_amount(value) or value

        updated = self.extraction_repo.update_field(extraction_result, field_key, normalized_value)
        logger.info(
            "Field manually corrected: document_id=%s field=%s", document_id, field_key
        )
        try:
            from app.services.invoice_persistence_service import InvoicePersistenceService
            persistence_svc = InvoicePersistenceService(self.db)
            persistence_svc.sync_from_extraction(document_id, extraction_result.id)
        except Exception as exc:
            logger.warning("Could not re-synchronize business data after correction for document %d: %s", document_id, exc)
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
            # Skip internal raw container keys in flat export rows unless individually requested
            if key in ("canonical", "_canonical"):
                continue

            val = field_data.get("value")
            if isinstance(val, (list, dict)):
                import json
                val = json.dumps(val)

            rows.append({
                "key": key,
                "label": label_by_key.get(key, key),
                "value": val,
                "confidence": field_data.get("confidence"),
                "is_found": field_data.get("is_found", False),
            })

        # Sort to match the schema's declared display order (dict
        # iteration order on `fields` isn't guaranteed to match it,
        # since fields are stored as a plain JSONB dict).
        schema_order = {field_def.key: i for i, field_def in enumerate(schema)}
        rows.sort(key=lambda r: schema_order.get(r["key"], len(schema_order)))

        return rows
