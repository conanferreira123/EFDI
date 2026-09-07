"""LLM-based structured data extraction engine.

Uses dynamic Pydantic schema validation and LLM structured outputs to extract
financial document fields with grounded source citations, followed by deterministic
date and amount normalization.
"""
import json
import logging
import ssl
import urllib.request
import urllib.error
from typing import Any, Optional

from app.core.config import settings
from app.extraction.base import (
    ExtractedField,
    ExtractionContext,
    ExtractionEngine,
    ExtractionResultData,
)
from app.extraction.field_schemas import FieldDef, get_full_field_schema
from app.extraction.llm_schema import LLMFieldItem, build_dynamic_extraction_model
from app.extraction.primitives import normalize_amount, normalize_date
from app.extraction.rule_based import RuleBasedExtractor

logger = logging.getLogger(__name__)


class LLMBasedExtractor(ExtractionEngine):
    name = "llm_based"

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        provider: str | None = None,
    ):
        self.provider = provider or getattr(settings, "LLM_PROVIDER", "mistral")
        self.model_name = model_name or settings.EXTRACTION_LLM_MODEL
        self.api_key = api_key or settings.MISTRAL_API_KEY
        self.api_base = api_base or settings.MISTRAL_API_BASE or "https://api.mistral.ai/v1"
        self._fallback_rule_extractor = RuleBasedExtractor()

        logger.info(
            "LLM extractor initialized: provider=%s model=%s api_base=%s api_key_configured=%s",
            self.provider,
            self.model_name,
            self.api_base,
            bool(self.api_key),
        )

    def _call_llm_api(self, system_prompt: str, user_prompt: str, json_schema: dict) -> dict[str, Any]:
        """Invoke Mistral Chat Completion endpoint requesting structured JSON."""
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY is not configured for LLMBasedExtractor.")

        url = f"{self.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "financial_document_extraction",
                    "strict": False,
                    "schema": json_schema,
                },
            },
            "temperature": 0.0,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            ssl_ctx = ssl.create_default_context()
            resp_cm = urllib.request.urlopen(req, timeout=45, context=ssl_ctx)
        except (urllib.error.URLError, ssl.SSLCertVerificationError):
            ssl_ctx = ssl._create_unverified_context()
            resp_cm = urllib.request.urlopen(req, timeout=45, context=ssl_ctx)

        with resp_cm as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

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
        schema_fields: list[FieldDef] = get_full_field_schema(doc_type)

        if not schema_fields:
            logger.info("No field schema found for document_type='%s'", doc_type)
            return result

        if not doc_text or not doc_text.strip():
            for f in schema_fields:
                result.fields[f.key] = ExtractedField(value=None, confidence=0.0, matched_text=None)
            return result

        DynamicModel = build_dynamic_extraction_model(doc_type)

        # If no API key is provided, log warning and use rule-based extraction
        # while wrapping results in the LLM-compatible format.
        if not self.api_key:
            logger.warning(
                "MISTRAL_API_KEY not configured. Falling back to rule-based extractor for type=%s.",
                doc_type,
            )
            rule_result = self._fallback_rule_extractor.extract(ctx)
            rule_result.engine_name = self.name
            return rule_result

        from app.extraction.llm_context_builder import LLMContextBuilder

        system_prompt = LLMContextBuilder.build_system_prompt(doc_type)
        user_prompt = LLMContextBuilder.build_user_prompt(ctx)

        try:
            raw_response = self._call_llm_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=DynamicModel.model_json_schema(),
            )
            parsed_data = DynamicModel.model_validate(raw_response)
        except Exception as exc:
            logger.error("LLM extraction failed: %s. Falling back to rule-based extractor.", exc)
            fallback = self._fallback_rule_extractor.extract(ctx)
            fallback.engine_name = self.name
            return fallback

        # Populate result fields with normalization
        for f in schema_fields:
            field_item: Optional[LLMFieldItem] = getattr(parsed_data, f.key, None)
            if field_item and field_item.value:
                raw_val = str(field_item.value).strip()
                normalized_val = raw_val

                if f.field_type == "date":
                    normalized_val = normalize_date(raw_val) or raw_val
                elif f.field_type == "amount":
                    normalized_val = normalize_amount(raw_val) or raw_val

                confidence = max(0.1, min(1.0, field_item.confidence if field_item.confidence > 0 else 0.85))
                result.fields[f.key] = ExtractedField(
                    value=normalized_val,
                    confidence=round(confidence, 2),
                    matched_text=field_item.source_quote or raw_val,
                )
            else:
                result.fields[f.key] = ExtractedField(value=None, confidence=0.0, matched_text=None)

        return result

