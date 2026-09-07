# PHASE 5 — DETERMINISTIC RECONCILIATION & PROVENANCE TRACKING IMPLEMENTATION REPORT

## 1. Executive Summary

Phase 5 of the EFDI Hybrid Extraction Pipeline has been successfully implemented and verified.

Building upon the foundations of Phase 1 (`ExtractionContext`), Phase 2 (Deterministic Layout/Table Enhancements in `RuleBasedExtractor`), Phase 3 (`LLMContextBuilder` and Structured Prompts in `LLMBasedExtractor`), and Phase 4 (`ParallelExtractionOrchestrator` & `DualExtractionResult`), Phase 5 introduces a deterministic, rule-governed **`ReconciliationEngine`**.

The engine resolves competing field extractions from `RuleBasedExtractor` and `LLMBasedExtractor` without silent overwrites, tracks field-level provenance, boosts confidence when both engines agree, applies verifiable date and table reconciliation rules, and preserves conflicting values for auditability.

---

## 2. Key Objectives & Accomplishments

| Objective | Status | Implementation Details |
| :--- | :--- | :--- |
| **Deterministic Reconciliation Layer** | Completed | Implemented `ReconciliationEngine` in `backend/app/extraction/reconciliation.py`. |
| **Field Provenance Taxonomy** | Completed | Extended `ExtractedField` with `provenance` and `conflict_value` attributes. |
| **Equivalence Checking** | Completed | Created normalization comparison for text, ISO dates, and numeric amounts. |
| **Verifiable Discrepancy Resolution** | Completed | Deterministic date resolution (prefer valid ISO formats) & table total verification against `ExtractionContext.tables`. |
| **Conflict Preservation** | Completed | Unresolvable conflicts retain primary value while preserving alternative in `conflict_value` with `"unresolved_conflict"` provenance. |
| **Zero-Migration JSONB Persistence** | Completed | Stored `provenance` and `conflict_value` inside the existing JSONB `fields` map in `ExtractionService`. |
| **Verification & Zero Regressions** | Completed | 71 extraction tests passed; all 264 backend unit/integration tests passed (100% pass rate). |

---

## 3. Architecture & Data Flow

```
                  ┌──────────────────────┐
                  │  ExtractionContext   │
                  └──────────┬───────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
┌───────────────────────┐         ┌───────────────────────┐
│  RuleBasedExtractor   │         │   LLMBasedExtractor   │
└───────────┬───────────┘         └───────────┬───────────┘
            │                                 │
            └────────────────┬────────────────┘
                             ▼
                 ┌───────────────────────┐
                 │ DualExtractionResult  │
                 └───────────┬───────────┘
                             ▼
                 ┌───────────────────────┐
                 │ ReconciliationEngine  │
                 └───────────┬───────────┘
                             │
     ┌───────────────────────┼────────────────────────┐
     ▼                       ▼                        ▼
[Agreement]          [Verifiable Res]            [Conflict]
provenance: "agreed"  provenance: "reconciled_*"  provenance: "unresolved_conflict"
boost confidence      table/date verification    preserves conflict_value
                             │
                             ▼
                 ┌───────────────────────┐
                 │    ExtractionResult   │
                 │ (Final Hybrid Output) │
                 └───────────────────────┘
```

---

## 4. Provenance Taxonomy & Resolution Rules

| Outcome / Provenance | Condition | Confidence Behavior | Result Value |
| :--- | :--- | :--- | :--- |
| `agreed` | Both Rule and LLM produce equivalent values (exact or normalized). | $\min(1.0, \text{rule\_conf} + 0.05)$ | Rule value (normalized). |
| `rule_based` | Only Rule found a value; LLM returned `None`. | Rule confidence. | Rule value. |
| `llm` | Only LLM found a value; Rule returned `None`. | LLM confidence. | LLM value. |
| `not_found` | Neither extractor extracted a value. | 0.0 | `None`. |
| `reconciled_rule_date` | Date field conflict where Rule produced standard ISO (`YYYY-MM-DD`) and LLM did not. | Rule confidence. | Rule value. |
| `reconciled_llm_date` | Date field conflict where LLM produced standard ISO (`YYYY-MM-DD`) and Rule did not. | LLM confidence. | LLM value. |
| `reconciled_table_verified` | Amount conflict where one candidate matches table total / sum calculation from `ExtractionContext.tables`. | Boosted to 0.95. | Verified candidate. |
| `unresolved_conflict` | Conflicting values with no deterministic tie-breaker. | $\min(\text{rule\_conf}, \text{llm\_conf}) \times 0.8$ | Rule value (primary) & LLM value preserved in `conflict_value`. |

---

## 5. File Modifications & Additions

### 1. `backend/app/extraction/base.py`
- Added optional fields `provenance: str | None = None` and `conflict_value: str | None = None` to `ExtractedField`.

### 2. `backend/app/extraction/reconciliation.py` (New Module)
- Implemented `ReconciliationEngine` with:
  - `are_values_equivalent(val1, val2, field_key)`
  - `is_valid_iso_date(val)`
  - `verify_amount_against_tables(rule_val, llm_val, tables)`
  - `reconcile_field(key, rule_field, llm_field, ctx)`
  - `reconcile(dual_result, ctx)`

### 3. `backend/app/extraction/parallel_orchestrator.py`
- Integrated `ReconciliationEngine.reconcile(dual_result, ctx)` into `HybridExtractor.extract()`.

### 4. `backend/app/services/extraction_service.py`
- Updated `fields_payload` serialization in `extract_document()` to include `provenance` and `conflict_value` for each field inside the JSONB payload:
  ```python
  fields_payload[k] = {
      "value": field_data.value,
      "confidence": field_data.confidence,
      "bounding_box": field_data.bounding_box,
      "provenance": field_data.provenance,
      "conflict_value": field_data.conflict_value,
  }
  ```

### 5. `backend/tests/test_phase5_reconciliation.py` (New Test Suite)
- Tested 10 comprehensive scenarios:
  - Exact string agreement with confidence boost
  - Normalized date agreement (`01/15/2024` vs `2024-01-15`)
  - Normalized amount agreement (`$1,250.00` vs `1250.00`)
  - Single extractor resolution (`rule_based` vs `llm`)
  - Deterministic date ISO format resolution
  - Table-based amount reconciliation
  - Unresolved conflict preservation and confidence penalty
  - HybridExtractor end-to-end reconciliation

---

## 6. Test Verification Results

### Focused Test Run
```bash
python -m pytest tests/test_phase5_reconciliation.py tests/test_phase4_parallel_execution.py tests/test_phase3_llm_enhancements.py tests/test_phase2_rule_enhancements.py tests/test_extraction_context.py tests/test_phase6_extraction.py tests/test_hybrid_llm_extraction.py -v
```
- **Result:** 71 passed, 0 failed in 19.32s.

### Full Regression Suite Run
```bash
python -m pytest -q
```
- **Result:** 264 passed, 0 failed in 384.25s (100% pass rate).

---

## 7. Next Steps (Phase 6)

Phase 5 is complete and fully tested. We are ready to proceed with Phase 6 upon explicit approval:
- **Phase 6:** Extraction evaluation metrics, benchmark dataset validation, and threshold tuning across all 9 document types.
