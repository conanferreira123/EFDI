"""
Rule-based extraction engine.

Implements ExtractionEngine by dispatching to the appropriate per-type
extractor function (app/extraction/type_extractors.py) based on the
document's classified type, then merging in the common fields shared
by every document type.

For UNKNOWN documents (or any type without an extractor registered),
returns an empty result rather than guessing -- there is no field
schema to extract against.
"""
import logging

from app.extraction.base import (
    ExtractedField,
    ExtractionContext,
    ExtractionEngine,
    ExtractionResultData,
)
from app.extraction.type_extractors import TYPE_EXTRACTORS, extract_common_fields

logger = logging.getLogger(__name__)


class RuleBasedExtractor(ExtractionEngine):
    name = "rule_based"

    def extract(
        self,
        context_or_text: ExtractionContext | str | None = None,
        document_type: str | None = None,
        *,
        context: ExtractionContext | None = None,
        text: str | None = None,
    ) -> ExtractionResultData:
        # Resolve ExtractionContext from context or legacy text + document_type
        if context is not None:
            ctx = context
        elif isinstance(context_or_text, ExtractionContext):
            ctx = context_or_text
        else:
            resolved_text = text if text is not None else (context_or_text or "")
            resolved_type = document_type or "UNKNOWN"
            ctx = ExtractionContext(full_text=resolved_text, document_type=resolved_type)

        doc_type = ctx.document_type
        doc_text = ctx.full_text

        result = ExtractionResultData(document_type=doc_type, engine_name=self.name)

        type_extractor_fn = TYPE_EXTRACTORS.get(doc_type)
        if type_extractor_fn is None:
            logger.info(
                "No extraction schema registered for document_type=%s; returning empty result.",
                doc_type,
            )
            return result

        if not doc_text or not doc_text.strip():
            # No OCR text to extract from -- every field is legitimately
            # "not found," not an error condition.
            common_keys = list(extract_common_fields("").keys())
            type_keys = list(type_extractor_fn("").keys())
            for key in common_keys + type_keys:
                result.fields[key] = ExtractedField(value=None, confidence=0.0)
            return result

        result.fields.update(extract_common_fields(doc_text, raw_blocks=ctx.raw_blocks))
        result.fields.update(
            type_extractor_fn(
                doc_text,
                raw_blocks=ctx.raw_blocks,
                table_data=ctx.table_data,
            )
        )

        return result


