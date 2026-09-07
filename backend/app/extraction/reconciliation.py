"""
Deterministic Reconciliation Engine for Hybrid Data Extraction.

Compares and reconciles the independent outputs of RuleBasedExtractor and
LLMBasedExtractor against the same ExtractionContext:
1. Detects AGREEMENT when both extractors agree on field values.
2. Applies deterministic domain resolution rules for format/table-verifiable discrepancies.
3. Preserves UNRESOLVED_CONFLICT with full provenance and competing values,
   preventing silent overwrites or arbitrary precedence.
"""
from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional

from app.extraction.base import ExtractedField, ExtractionContext, ExtractionResultData
from app.extraction.field_schemas import DOCUMENT_TYPE_FIELDS, FieldDef, get_full_field_schema
from app.extraction.parallel_orchestrator import DualExtractionResult
from app.extraction.primitives import normalize_amount, normalize_date
from app.extraction.table_helpers import extract_amount_from_table

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """
    Field-level deterministic reconciliation of Rule-Based and LLM-Based extractions.
    """

    @classmethod
    def are_values_equivalent(cls, val_a: Optional[str], val_b: Optional[str], field_type: str) -> bool:
        """Check if two extracted values represent the same underlying data."""
        if val_a is None and val_b is None:
            return True
        if val_a is None or val_b is None:
            return False

        str_a = str(val_a).strip()
        str_b = str(val_b).strip()

        if str_a.lower() == str_b.lower():
            return True

        if field_type == "date":
            norm_a = normalize_date(str_a)
            norm_b = normalize_date(str_b)
            if norm_a and norm_b and norm_a == norm_b:
                return True

        if field_type == "amount":
            norm_a = normalize_amount(str_a)
            norm_b = normalize_amount(str_b)
            if norm_a and norm_b and norm_a == norm_b:
                return True

        return False

    @classmethod
    def reconcile(
        cls,
        dual_result: DualExtractionResult,
        context: ExtractionContext,
    ) -> ExtractionResultData:
        """
        Reconcile Rule and LLM outputs field-by-field and construct a consolidated
        ExtractionResultData with exact field provenance.
        """
        doc_type = context.document_type
        if doc_type == "UNKNOWN" or doc_type not in DOCUMENT_TYPE_FIELDS:
            logger.info("No extraction schema registered for document_type=%s; returning empty result.", doc_type)
            return ExtractionResultData(document_type=doc_type, engine_name="hybrid", fields={})

        doc_id = getattr(context, "document_id", None) or "N/A"
        schema: list[FieldDef] = get_full_field_schema(doc_type)
        rule_result = dual_result.rule_result
        llm_result = dual_result.llm_result

        logger.info(
            "\n" + "=" * 60 +
            "\nRECONCILIATION START" +
            "\n" + "=" * 60 +
            "\ndocument_id: %s" +
            "\ndocument_type: %s" +
            "\nengine: hybrid" +
            "\nfield_count: %d" +
            "\nrule_engine_status: %s" +
            "\nllm_engine_status: %s" +
            "\n" + "=" * 60,
            doc_id,
            doc_type,
            len(schema),
            "OK" if rule_result is not None else f"FAILED ({dual_result.rule_error})",
            "OK" if llm_result is not None else f"FAILED ({dual_result.llm_error})",
        )

        reconciled_fields: Dict[str, ExtractedField] = {}
        summary_rows = []

        for f in schema:
            key = f.key
            rule_f = rule_result.fields.get(key) if rule_result else None
            llm_f = llm_result.fields.get(key) if llm_result else None

            rule_has_val = rule_f is not None and rule_f.is_found and rule_f.value is not None
            llm_has_val = llm_f is not None and llm_f.is_found and llm_f.value is not None

            # CASE 1: Both Extractors Found a Value
            if rule_has_val and llm_has_val:
                rule_val = str(rule_f.value).strip()
                llm_val = str(llm_f.value).strip()

                norm_r = normalize_date(rule_val) if f.field_type == "date" else (normalize_amount(rule_val) if f.field_type == "amount" else rule_val)
                norm_l = normalize_date(llm_val) if f.field_type == "date" else (normalize_amount(llm_val) if f.field_type == "amount" else llm_val)

                # Log Reconciliation Input
                logger.info(
                    "\n============================================================"
                    "\nRECONCILIATION INPUT"
                    "\n============================================================"
                    "\nDocument ID: %s"
                    "\nField: %s"
                    "\n"
                    "\nRULE-BASED"
                    "\n  value: %s"
                    "\n  confidence: %.2f"
                    "\n  provenance: rule_based"
                    "\n"
                    "\nLLM-BASED"
                    "\n  value: %s"
                    "\n  confidence: %.2f"
                    "\n  provenance: llm"
                    "\n"
                    "\nNORMALIZED"
                    "\n  rule_based: %s"
                    "\n  llm: %s"
                    "\n============================================================",
                    doc_id, key, rule_val, rule_f.confidence, llm_val, llm_f.confidence, norm_r, norm_l,
                )

                # A. Complete Agreement
                if cls.are_values_equivalent(rule_val, llm_val, f.field_type):
                    canonical_val = rule_val
                    if f.field_type == "date":
                        canonical_val = normalize_date(rule_val) or normalize_date(llm_val) or rule_val
                    elif f.field_type == "amount":
                        canonical_val = normalize_amount(rule_val) or normalize_amount(llm_val) or rule_val

                    boosted_conf = min(1.0, max(rule_f.confidence, llm_f.confidence) + 0.05)
                    final_f = ExtractedField(
                        value=canonical_val,
                        confidence=round(boosted_conf, 2),
                        matched_text=llm_f.matched_text or rule_f.matched_text,
                        provenance="agreed",
                        conflict_value=None,
                    )
                    reconciled_fields[key] = final_f

                    logger.info(
                        "\n============================================================"
                        "\nRECONCILIATION RESULT"
                        "\n============================================================"
                        "\nDocument ID: %s"
                        "\nField: %s"
                        "\n"
                        "\nFINAL"
                        "\n  value: %s"
                        "\n  confidence: %.2f"
                        "\n  provenance: agreed"
                        "\n  conflict_value: null"
                        "\n"
                        "\nDECISION"
                        "\n  BOTH ENGINES AGREED"
                        "\n============================================================",
                        doc_id, key, final_f.value, final_f.confidence,
                    )
                    summary_rows.append((key, rule_val, llm_val, final_f.value, final_f.provenance))
                    continue

                # B. Disagreement / Conflict Resolution Attempts
                resolved_field = cls._try_resolve_conflict(f, rule_f, llm_f, context)
                if resolved_field is not None:
                    reconciled_fields[key] = resolved_field
                    decision_str = (
                        "TABLE-VERIFIED RECONCILIATION" if resolved_field.provenance == "reconciled_table_verified"
                        else f"DATE RECONCILIATION ({resolved_field.provenance.upper()})"
                    )

                    logger.info(
                        "\n============================================================"
                        "\nRECONCILIATION RESULT"
                        "\n============================================================"
                        "\nDocument ID: %s"
                        "\nField: %s"
                        "\n"
                        "\nFINAL"
                        "\n  value: %s"
                        "\n  confidence: %.2f"
                        "\n  provenance: %s"
                        "\n  conflict_value: %s"
                        "\n"
                        "\nDECISION"
                        "\n  %s"
                        "\n============================================================",
                        doc_id, key, resolved_field.value, resolved_field.confidence,
                        resolved_field.provenance, resolved_field.conflict_value, decision_str,
                    )
                    summary_rows.append((key, rule_val, llm_val, resolved_field.value, resolved_field.provenance))
                    continue

                # C. Unresolved Conflict (Preserve competing values without silent overwrite)
                if llm_f.confidence >= rule_f.confidence:
                    primary_val = llm_val
                    competing_val = rule_val
                    match_quote = llm_f.matched_text or llm_val
                else:
                    primary_val = rule_val
                    competing_val = llm_val
                    match_quote = rule_f.matched_text or rule_val

                conflict_conf = min(rule_f.confidence, llm_f.confidence)
                final_f = ExtractedField(
                    value=primary_val,
                    confidence=round(max(0.20, conflict_conf), 2),
                    matched_text=match_quote,
                    provenance="unresolved_conflict",
                    conflict_value=competing_val,
                )
                reconciled_fields[key] = final_f

                logger.warning(
                    "\n============================================================"
                    "\nRECONCILIATION RESULT"
                    "\n============================================================"
                    "\nDocument ID: %s"
                    "\nField: %s"
                    "\n"
                    "\nFINAL"
                    "\n  value: %s"
                    "\n  confidence: %.2f"
                    "\n  provenance: unresolved_conflict"
                    "\n  conflict_value: %s"
                    "\n"
                    "\nDECISION"
                    "\n  UNRESOLVED CONFLICT"
                    "\n============================================================",
                    doc_id, key, final_f.value, final_f.confidence, final_f.conflict_value,
                )
                summary_rows.append((key, rule_val, llm_val, final_f.value, final_f.provenance))
                continue

            # CASE 2: Only Rule-Based Found a Value
            if rule_has_val and not llm_has_val:
                final_f = ExtractedField(
                    value=rule_f.value,
                    confidence=rule_f.confidence,
                    matched_text=rule_f.matched_text,
                    provenance="rule_based",
                    conflict_value=None,
                )
                reconciled_fields[key] = final_f
                logger.info(
                    "\n============================================================"
                    "\nRECONCILIATION RESULT"
                    "\n============================================================"
                    "\nDocument ID: %s"
                    "\nField: %s"
                    "\n"
                    "\nFINAL"
                    "\n  value: %s"
                    "\n  confidence: %.2f"
                    "\n  provenance: rule_based"
                    "\n  conflict_value: null"
                    "\n"
                    "\nDECISION"
                    "\n  RULE-BASED RESULT ACCEPTED"
                    "\n============================================================",
                    doc_id, key, final_f.value, final_f.confidence,
                )
                summary_rows.append((key, str(rule_f.value), "-", str(final_f.value), final_f.provenance))
                continue

            # CASE 3: Only LLM Found a Value
            if llm_has_val and not rule_has_val:
                final_f = ExtractedField(
                    value=llm_f.value,
                    confidence=llm_f.confidence,
                    matched_text=llm_f.matched_text,
                    provenance="llm",
                    conflict_value=None,
                )
                reconciled_fields[key] = final_f
                logger.info(
                    "\n============================================================"
                    "\nRECONCILIATION RESULT"
                    "\n============================================================"
                    "\nDocument ID: %s"
                    "\nField: %s"
                    "\n"
                    "\nFINAL"
                    "\n  value: %s"
                    "\n  confidence: %.2f"
                    "\n  provenance: llm"
                    "\n  conflict_value: null"
                    "\n"
                    "\nDECISION"
                    "\n  LLM-BASED RESULT ACCEPTED"
                    "\n============================================================",
                    doc_id, key, final_f.value, final_f.confidence,
                )
                summary_rows.append((key, "-", str(llm_f.value), str(final_f.value), final_f.provenance))
                continue

            # CASE 4: Neither Found a Value
            final_f = ExtractedField(
                value=None,
                confidence=0.0,
                matched_text=None,
                provenance="not_found",
                conflict_value=None,
            )
            reconciled_fields[key] = final_f
            summary_rows.append((key, "-", "-", "-", final_f.provenance))

        # Document-Level Summary Counts
        agreed_cnt = sum(1 for f in reconciled_fields.values() if f.provenance == "agreed")
        rule_cnt = sum(1 for f in reconciled_fields.values() if f.provenance == "rule_based")
        llm_cnt = sum(1 for f in reconciled_fields.values() if f.provenance == "llm")
        reconciled_cnt = sum(1 for f in reconciled_fields.values() if f.provenance and f.provenance.startswith("reconciled_"))
        unresolved_cnt = sum(1 for f in reconciled_fields.values() if f.provenance == "unresolved_conflict")
        not_found_cnt = sum(1 for f in reconciled_fields.values() if f.provenance == "not_found")

        # Compact Final Summary Table
        table_lines = [
            f"{'Field':<24} {'RULE-BASED':<20} {'LLM-BASED':<20} {'FINAL':<20}",
            "-" * 88,
        ]
        for k, r_val, l_val, fin_val, _ in summary_rows:
            r_str = (r_val[:17] + "...") if len(r_val) > 20 else r_val
            l_str = (l_val[:17] + "...") if len(l_val) > 20 else l_val
            fin_str = (fin_val[:17] + "...") if len(fin_val) > 20 else fin_val
            table_lines.append(f"{k:<24} {r_str:<20} {l_str:<20} {fin_str:<20}")

        prov_lines = [
            f"{'Field':<24} {'PROVENANCE':<24}",
            "-" * 50,
        ]
        for k, _, _, _, prov in summary_rows:
            prov_lines.append(f"{k:<24} {prov:<24}")

        logger.info(
            "\n" + "=" * 60 +
            "\nRECONCILIATION COMPLETE" +
            "\n" + "=" * 60 +
            "\ndocument_id: %s" +
            "\n\nagreed_fields: %d" +
            "\nrule_based_fields: %d" +
            "\nllm_fields: %d" +
            "\nreconciled_fields: %d" +
            "\nunresolved_conflicts: %d" +
            "\nnot_found_fields: %d" +
            "\n" + "=" * 60 +
            "\nHYBRID EXTRACTION -- FINAL DECISIONS" +
            "\n" + "=" * 60 +
            "\nDocument ID: %s" +
            "\nDocument Type: %s\n" +
            "\n%s" +
            "\n" + "=" * 60 +
            "\nFINAL PROVENANCE" +
            "\n" + "=" * 60 +
            "\n%s" +
            "\n" + "=" * 60,
            doc_id, agreed_cnt, rule_cnt, llm_cnt, reconciled_cnt, unresolved_cnt, not_found_cnt,
            doc_id, doc_type,
            "\n".join(table_lines),
            "\n".join(prov_lines),
        )

        return ExtractionResultData(
            document_type=doc_type,
            fields=reconciled_fields,
            engine_name="hybrid",
        )

    @classmethod
    def _try_resolve_conflict(
        cls,
        field_def: FieldDef,
        rule_f: ExtractedField,
        llm_f: ExtractedField,
        context: ExtractionContext,
    ) -> Optional[ExtractedField]:
        """Attempt deterministic resolution of conflicting field values."""
        # 1. Date Format Validation Rule
        if field_def.field_type == "date":
            rule_iso = normalize_date(rule_f.value)
            llm_iso = normalize_date(llm_f.value)
            if rule_iso and not llm_iso:
                return ExtractedField(
                    value=rule_iso,
                    confidence=rule_f.confidence,
                    matched_text=rule_f.matched_text,
                    provenance="reconciled_rule_date",
                    conflict_value=llm_f.value,
                )
            if llm_iso and not rule_iso:
                return ExtractedField(
                    value=llm_iso,
                    confidence=llm_f.confidence,
                    matched_text=llm_f.matched_text,
                    provenance="reconciled_llm_date",
                    conflict_value=rule_f.value,
                )

        # 2. Table Amount Verification Rule
        if field_def.field_type == "amount" and context.table_data:
            table_cand = extract_amount_from_table(context.table_data, field_def.key)
            if table_cand and table_cand.is_found and table_cand.value:
                norm_table = normalize_amount(table_cand.value)
                norm_rule = normalize_amount(rule_f.value)
                norm_llm = normalize_amount(llm_f.value)

                if norm_rule == norm_table and norm_llm != norm_table:
                    return ExtractedField(
                        value=norm_rule,
                        confidence=0.88,
                        matched_text=rule_f.matched_text or "Table Verified",
                        provenance="reconciled_table_verified",
                        conflict_value=llm_f.value,
                    )
                if norm_llm == norm_table and norm_rule != norm_table:
                    return ExtractedField(
                        value=norm_llm,
                        confidence=0.88,
                        matched_text=llm_f.matched_text or "Table Verified",
                        provenance="reconciled_table_verified",
                        conflict_value=rule_f.value,
                    )

        return None
