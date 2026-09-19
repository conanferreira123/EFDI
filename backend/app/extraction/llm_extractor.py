"""LLM-based structured data extraction engine.

Uses dynamic Pydantic schema validation and LLM structured outputs to extract
financial document fields with grounded source citations, followed by deterministic
date and amount normalization.
"""
import json
import logging
import ssl
import time
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
from app.extraction.field_schemas import (
    FieldDef,
    convert_flat_npo_to_hierarchical_dict,
    get_full_field_schema,
    is_hierarchical_schema,
    map_npo_flat_to_canonical,
)
from app.extraction.llm_schema import (
    LLMFieldItem,
    NPOExtractionPayload,
    build_dynamic_extraction_model,
    get_extraction_model,
)
from app.extraction.primitives import normalize_amount, normalize_currency, normalize_date
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
        """Invoke Mistral Chat Completion endpoint requesting structured JSON with retry support."""
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

        req_data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            try:
                ssl_ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=60, context=ssl_ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM API call attempt %d/3 failed (%s: %s). Retrying...",
                    attempt + 1,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(1.0)

        if last_exc:
            raise last_exc
        raise RuntimeError("LLM API call failed after retries.")

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

        is_hierarchical = is_hierarchical_schema(doc_type)

        if not doc_text or not doc_text.strip():
            for f in schema_fields:
                result.fields[f.key] = ExtractedField(value=None, confidence=0.0, matched_text=None)
            if is_hierarchical:
                empty_payload = NPOExtractionPayload()
                canonical_dict = empty_payload.to_canonical_dict()
                result.fields["line_items"] = ExtractedField(value=[], confidence=0.0, provenance="llm")
                result.fields["taxes"] = ExtractedField(value=[], confidence=0.0, provenance="llm")
                result.fields["canonical"] = ExtractedField(value=canonical_dict, confidence=0.0, provenance="llm")
                for path in empty_payload.flatten_to_paths():
                    result.fields[path] = ExtractedField(value=None, confidence=0.0, matched_text=None, provenance="llm")
            return result

        ExtractionModel = get_extraction_model(doc_type, hierarchical=is_hierarchical)

        # If no API key is provided, log warning and use rule-based extraction
        # while wrapping results in the LLM-compatible format.
        if not self.api_key:
            logger.warning(
                "MISTRAL_API_KEY not configured. Falling back to rule-based extractor for type=%s.",
                doc_type,
            )
            rule_result = self._fallback_rule_extractor.extract(ctx)
            rule_result.engine_name = self.name
            if is_hierarchical:
                self._enrich_npo_hierarchical(rule_result, ctx)
            return rule_result

        from app.extraction.llm_context_builder import LLMContextBuilder

        system_prompt = LLMContextBuilder.build_system_prompt(doc_type, hierarchical=is_hierarchical)
        user_prompt = LLMContextBuilder.build_user_prompt(ctx)

        try:
            raw_response = self._call_llm_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=ExtractionModel.model_json_schema(),
            )
            if is_hierarchical and isinstance(raw_response, dict):
                # If response was delivered in flat keys (e.g. from mock), convert to hierarchical
                if "invoice_information" not in raw_response and (
                    "invoice_number" in raw_response or "seller_name" in raw_response
                ):
                    raw_response = convert_flat_npo_to_hierarchical_dict(raw_response)
            parsed_data = ExtractionModel.model_validate(raw_response)
        except Exception as exc:
            logger.error("LLM extraction failed: %s. Falling back to rule-based extractor.", exc)
            fallback = self._fallback_rule_extractor.extract(ctx)
            fallback.engine_name = self.name
            if is_hierarchical:
                self._enrich_npo_hierarchical(fallback, ctx)
            return fallback

        if is_hierarchical and isinstance(parsed_data, NPOExtractionPayload):
            self._populate_npo_results(result, parsed_data, schema_fields)
        else:
            self._populate_flat_results(result, parsed_data, schema_fields)

        return result

    def _populate_npo_results(
        self,
        result: ExtractionResultData,
        parsed_data: NPOExtractionPayload,
        schema_fields: list[FieldDef],
    ) -> None:
        """Populate canonical nested, dot-path, collection, and legacy flat fields for NPO."""
        parsed_data.normalize_values()
        canonical_dict = parsed_data.to_canonical_dict()
        paths = parsed_data.flatten_to_paths()

        # 1. Populate canonical paths
        for path, item in paths.items():
            result.fields[path] = ExtractedField(
                value=item.value,
                confidence=round(item.confidence, 2),
                matched_text=item.source_quote,
                provenance=item.provenance or "llm",
                conflict_value=item.conflict_value,
            )

        # 2. Populate collections
        result.fields["line_items"] = ExtractedField(
            value=canonical_dict["line_items"],
            confidence=1.0 if canonical_dict["line_items"] else 0.0,
            provenance="llm",
        )
        result.fields["taxes"] = ExtractedField(
            value=canonical_dict["taxes"],
            confidence=1.0 if canonical_dict["taxes"] else 0.0,
            provenance="llm",
        )

        # 3. Populate root canonical payload
        result.fields["canonical"] = ExtractedField(
            value=canonical_dict,
            confidence=round(result.overall_confidence, 2) if result.fields_found_count > 0 else 0.0,
            provenance="llm",
        )

        # 4. Populate legacy flat keys for full backward compatibility
        legacy_dict = parsed_data.flatten_to_legacy_dict()
        for flat_key, item_dict in legacy_dict.items():
            result.fields[flat_key] = ExtractedField(
                value=item_dict["value"],
                confidence=item_dict["confidence"],
                matched_text=item_dict.get("matched_text"),
                provenance=item_dict.get("provenance") or "llm",
                conflict_value=item_dict.get("conflict_value"),
            )

        # 5. Ensure all flat schema fields exist
        for f in schema_fields:
            if f.key not in result.fields:
                result.fields[f.key] = ExtractedField(
                    value=None,
                    confidence=0.0,
                    matched_text=None,
                    provenance="llm",
                )

    def _populate_flat_results(
        self,
        result: ExtractionResultData,
        parsed_data: Any,
        schema_fields: list[FieldDef],
    ) -> None:
        """Populate flat fields for non-hierarchical / legacy document types."""
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
                    provenance=field_item.provenance or "llm",
                    conflict_value=field_item.conflict_value,
                )
            else:
                result.fields[f.key] = ExtractedField(value=None, confidence=0.0, matched_text=None, provenance="llm")

    def _enrich_npo_hierarchical(self, rule_result: ExtractionResultData, ctx: ExtractionContext) -> None:
        """Augment rule-based extraction results with canonical NPO paths and collections on fallback."""
        flat_snapshot = dict(rule_result.fields)
        for flat_key, f in flat_snapshot.items():
            canon_path = map_npo_flat_to_canonical(flat_key)
            if canon_path and canon_path != flat_key and canon_path not in rule_result.fields:
                rule_result.fields[canon_path] = ExtractedField(
                    value=f.value,
                    confidence=f.confidence,
                    matched_text=f.matched_text,
                    provenance=f.provenance or "rule_based",
                    conflict_value=f.conflict_value,
                )

        line_items_list = []
        if ctx.normalized_data and isinstance(ctx.normalized_data, dict):
            items = ctx.normalized_data.get("line_items") or []
            for itm in items:
                desc = itm.get("normalized_description") or itm.get("raw_description")
                qty = itm.get("normalized_quantity")
                unit = itm.get("normalized_unit")
                price = itm.get("normalized_unit_price")
                net = itm.get("normalized_net_amount")
                vat = itm.get("vat_interpretation") or itm.get("raw_vat_rate")
                line_items_list.append({
                    "description": {"value": desc, "confidence": 0.85 if desc else 0.0, "matched_text": desc, "is_found": bool(desc), "provenance": "rule_based", "conflict_value": None},
                    "quantity": {"value": str(qty) if qty is not None else None, "confidence": 0.85 if qty is not None else 0.0, "matched_text": str(qty) if qty is not None else None, "is_found": qty is not None, "provenance": "rule_based", "conflict_value": None},
                    "uom": {"value": unit, "confidence": 0.85 if unit else 0.0, "matched_text": unit, "is_found": bool(unit), "provenance": "rule_based", "conflict_value": None},
                    "unit_price": {"value": str(price) if price is not None else None, "confidence": 0.85 if price is not None else 0.0, "matched_text": str(price) if price is not None else None, "is_found": price is not None, "provenance": "rule_based", "conflict_value": None},
                    "net_amount": {"value": str(net) if net is not None else None, "confidence": 0.85 if net is not None else 0.0, "matched_text": str(net) if net is not None else None, "is_found": net is not None, "provenance": "rule_based", "conflict_value": None},
                    "tax_rate": {"value": vat, "confidence": 0.85 if vat else 0.0, "matched_text": vat, "is_found": bool(vat), "provenance": "rule_based", "conflict_value": None},
                    "tax_amount": {"value": None, "confidence": 0.0, "matched_text": None, "is_found": False, "provenance": "rule_based", "conflict_value": None},
                    "gross_amount": {"value": None, "confidence": 0.0, "matched_text": None, "is_found": False, "provenance": "rule_based", "conflict_value": None},
                })

        rule_result.fields["line_items"] = ExtractedField(
            value=line_items_list,
            confidence=1.0 if line_items_list else 0.0,
            provenance="rule_based",
        )
        rule_result.fields["taxes"] = ExtractedField(
            value=[],
            confidence=0.0,
            provenance="rule_based",
        )
        # Build canonical dict
        empty_payload = NPOExtractionPayload()
        canon_dict = empty_payload.to_canonical_dict()
        canon_dict["line_items"] = line_items_list
        for flat_k, f_item in flat_snapshot.items():
            c_path = map_npo_flat_to_canonical(flat_k)
            if "." in c_path:
                sec, field_name = c_path.split(".", 1)
                if sec in canon_dict and isinstance(canon_dict[sec], dict):
                    canon_dict[sec][field_name] = {
                        "value": f_item.value,
                        "confidence": f_item.confidence,
                        "matched_text": f_item.matched_text,
                        "is_found": f_item.is_found,
                        "provenance": f_item.provenance or "rule_based",
                        "conflict_value": f_item.conflict_value,
                    }
        rule_result.fields["canonical"] = ExtractedField(
            value=canon_dict,
            confidence=rule_result.overall_confidence,
            provenance="rule_based",
        )


