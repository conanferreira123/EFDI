# PHASE 1 — EXTRACTION CONTEXT & CONTRACT IMPLEMENTATION REPORT

**Date:** September 6, 2026  
**Status:** COMPLETED — PENDING REVIEW & AUTHORIZATION  
**Phase:** Hybrid Extraction Pipeline — Phase 1  

---

## 1. Phase 1 Objective

The objective of Phase 1 is strictly architectural plumbing:
- Introduce `ExtractionContext` as an explicit, in-memory data contract between upstream services/OCR results and extraction engines.
- Propagate `full_text`, `document_type`, `raw_blocks`, and safely derived OCR metadata (`table_data`, `normalized_data`, `ocr_validation`, `ocr_quality`) into the extraction layer.
- Update `ExtractionEngine`, `RuleBasedExtractor`, `LLMBasedExtractor`, and `ExtractionService` without altering extraction intelligence, rules, spatial algorithms, prompts, or persistence schemas.
- Ensure 100% backward compatibility for existing callers and test suites using `extract(text, document_type)`.

---

## 2. Files Modified

1. `backend/app/extraction/base.py`
   - Added `ExtractionContext` dataclass.
   - Updated `ExtractionEngine.extract(...)` abstract method signature to support `ExtractionContext` and legacy arguments.
2. `backend/app/extraction/rule_based.py`
   - Updated `RuleBasedExtractor.extract(...)` to resolve `ExtractionContext` while preserving rule-based regex extraction mechanics.
3. `backend/app/extraction/llm_extractor.py`
   - Updated `LLMBasedExtractor.extract(...)` to resolve `ExtractionContext` while preserving structured LLM schema extraction and fallback mechanics.
4. `backend/app/services/extraction_service.py`
   - Updated `ExtractionService.extract(...)` to construct `ExtractionContext` with `full_text`, `document_type`, `raw_blocks`, and safely computed OCR helper outputs (`table_data`, `normalized_data`, `ocr_validation`, `ocr_quality`), then pass `context` to `engine.extract(context)`.

---

## 3. Files Added

1. `backend/tests/test_extraction_context.py`
   - Dedicated unit and integration tests verifying `ExtractionContext` instantiation, defaults, propagation of `full_text` and `raw_blocks`, legacy backward-compatibility paths, keyword-argument invocations, and `ExtractionService` orchestration.
2. `PHASE_1_EXTRACTION_CONTEXT_IMPLEMENTATION_REPORT.md` (this report).

---

## 4. Exact ExtractionContext Definition

Located in `backend/app/extraction/base.py`:

```python
@dataclass
class ExtractionContext:
    """
    Context passed to extraction engines containing the primary textual document
    representation and optional OCR-derived layout/structural metadata.
    """

    full_text: str
    document_type: str
    raw_blocks: list[dict] = field(default_factory=list)
    table_data: dict | None = None
    normalized_data: dict | None = None
    ocr_validation: dict | None = None
    ocr_quality: dict | None = None
```

- `full_text` is required.
- `document_type` is required.
- `raw_blocks` defaults safely to an empty list (`list[dict]`).
- `table_data`, `normalized_data`, `ocr_validation`, and `ocr_quality` default safely to `None`.

---

## 5. Exact Data-Flow Before Phase 1

```
OCRService
    |
    v
OCRResult (DB: full_text, raw_blocks, ...)
    |
    +---> ClassificationService ---> ClassificationResult (DB: predicted_type)
    |
    +---> ExtractionService.extract(document)
            |
            |-- ocr_result.full_text (only full_text passed!)
            |-- classification_result.predicted_type
            v
          engine.extract(text, document_type)
            |
            v
          ExtractionResultData
```
*Note: Before Phase 1, `raw_blocks`, `table_data`, `normalized_data`, and OCR validation/quality were completely lost before reaching the extraction engines.*

---

## 6. Exact Data-Flow After Phase 1

```
OCRResult (DB)                       ClassificationResult (DB)
    |                                            |
    |-- full_text                                |-- predicted_type (document_type)
    |-- raw_blocks                               |
    |-- (reconstruct_table)                      |
    |-- (normalize_table_data)                   |
    |-- (validate_ocr_output)                    |
    |-- (calculate_quality_score)                |
    \                     _______________________/
     \                   /
      v                 v
         ExtractionContext
          - full_text
          - document_type
          - raw_blocks
          - table_data
          - normalized_data
          - ocr_validation
          - ocr_quality
                |
                v
         ExtractionEngine.extract(context)
                |
       +--------+--------+
       |                 |
       v                 v
RuleBasedExtractor  LLMBasedExtractor
       |                 |
       +--------+--------+
                |
                v
      ExtractionResultData
```

---

## 7. How full_text Reaches ExtractionContext

In `ExtractionService.extract(document)`:
1. `ocr_result = self.ocr_repo.get_latest_for_document(document.id)`
2. `ocr_result.full_text` is passed directly to `ExtractionContext(full_text=ocr_result.full_text, ...)`
3. `ExtractionContext.full_text` is passed into `engine.extract(context)`
4. The extraction engine extracts fields using `ctx.full_text`.

---

## 8. How raw_blocks Reaches ExtractionContext

In `ExtractionService.extract(document)`:
1. `ocr_result.raw_blocks` (stored as JSONB in PostgreSQL `ocr_results`) is retrieved.
2. `raw_blocks = ocr_result.raw_blocks or []` is assigned.
3. `ExtractionContext(..., raw_blocks=raw_blocks, ...)` receives the unaltered raw blocks list.
4. Downstream extractors now have access to `context.raw_blocks`.

---

## 9. How table_data Is Populated

In `ExtractionService.extract(document)`:
1. If `raw_blocks` exists and has elements, page 1 blocks are passed to the existing OCR helper:
   ```python
   all_page_blocks = raw_blocks[0].get("blocks", []) if raw_blocks else []
   pw = float(raw_blocks[0].get("page_width", 1000.0))
   ph = float(raw_blocks[0].get("page_height", 1400.0))
   table_obj = reconstruct_table(all_page_blocks, page_width=pw, page_height=ph)
   table_data = table_obj.to_dict()
   ```
2. If `raw_blocks` is missing/empty, `table_data` remains `None`.

---

## 10. How normalized_data Is Populated

In `ExtractionService.extract(document)`:
1. Reconstructed `table_data` is passed to `normalize_table_data(table_data)`.
2. The normalized items are formatted into a dictionary:
   ```python
   normalized_items = normalize_table_data(table_data)
   normalized_data = {"line_items": [item.to_dict() for item in normalized_items]}
   ```
3. If table reconstruction was not run or `raw_blocks` is empty, `normalized_data` remains `None`.

---

## 11. How OCR Validation Is Populated

In `ExtractionService.extract(document)`:
1. `validate_ocr_output(normalized_items, raw_full_text=ocr_result.full_text)` is called.
2. The resulting `OCRValidationResult` is converted via `.to_dict()` and stored in `ocr_validation`.
3. If `raw_blocks` is empty, `ocr_validation` remains `None`.

---

## 12. How OCR Quality Is Populated

In `ExtractionService.extract(document)`:
1. `calculate_quality_score(avg_confidence=avg_conf, full_text=ocr_result.full_text, table_data=table_data, validation_result=val_res)` is called.
2. The resulting `OCRQualityScore` is converted via `.to_dict()` and stored in `ocr_quality`.
3. If `raw_blocks` is empty, `ocr_quality` remains `None`.

---

## 13. Whether Any Existing OCR Functions Were Changed

**NO.**  
Zero lines of code in `backend/app/ocr/*` were modified. All helper functions (`reconstruct_table`, `normalize_table_data`, `validate_ocr_output`, `calculate_quality_score`) were reused exactly as implemented.

---

## 14. RuleBasedExtractor Changes

- Modified `RuleBasedExtractor.extract()` to accept either `ExtractionContext` or legacy `(text, document_type)` arguments.
- It extracts fields using `ctx.full_text` and `ctx.document_type`.
- **Zero changes** to regex extraction patterns, logic, field schemas, or spatial reasoning in Phase 1.

---

## 15. LLMBasedExtractor Changes

- Modified `LLMBasedExtractor.extract()` to accept either `ExtractionContext` or legacy `(text, document_type)` arguments.
- It supplies `ctx.full_text` into prompt construction and passes `ctx` to fallback rule extractor if API keys are missing or API calls fail.
- **Zero changes** to LLM prompts, schemas, or LLM extraction strategies in Phase 1.

---

## 16. ExtractionService Changes

- Constructs `ExtractionContext` with `ocr_result.full_text`, `document_type`, `ocr_result.raw_blocks`, and safely derived OCR metadata.
- Calls `engine.extract(context)`.
- Leaves database extraction persistence, document status workflow, audit logging, and RAG diagnostic triggers unaltered.

---

## 17. Factory / API Compatibility

- `backend/app/extraction/factory.py` remains 100% compatible and continues returning `ExtractionEngine` singletons (`RuleBasedExtractor`, `LLMBasedExtractor`).
- `backend/app/routers/extraction.py` routes (`POST /extraction/documents/{id}/extract`, `PATCH .../fields/{key}`, `GET .../export`) remain fully functional and unchanged.

---

## 18. Backward Compatibility Mechanism

`ExtractionEngine` and all implementations use dynamic argument resolution:
```python
def extract(
    self,
    context_or_text: ExtractionContext | str | None = None,
    document_type: str | None = None,
    *,
    context: ExtractionContext | None = None,
    text: str | None = None,
) -> ExtractionResultData:
    if context is not None:
        ctx = context
    elif isinstance(context_or_text, ExtractionContext):
        ctx = context_or_text
    else:
        resolved_text = text if text is not None else (context_or_text or "")
        resolved_type = document_type or "UNKNOWN"
        ctx = ExtractionContext(full_text=resolved_text, document_type=resolved_type)
```
This guarantees complete compatibility with:
1. `engine.extract(context)`
2. `engine.extract(text, document_type)`
3. `engine.extract(context=context)`
4. `engine.extract(text=text, document_type=document_type)`

---

## 19. Database Changes

**NONE.**  
- No PostgreSQL migrations created or executed.
- No columns or tables added or altered.
- `ExtractionContext` is an in-memory transport object and is not persisted.

---

## 20. Tests Executed

Targeted and regression test suites executed via pytest:
1. `backend/tests/test_extraction_context.py` (9 tests)
2. `backend/tests/test_phase6_extraction.py` (27 tests)
3. `backend/tests/test_hybrid_llm_extraction.py` (6 tests)
4. Full backend baseline test suite (226 tests)

---

## 21. Test Results

All targeted tests passed:
- `test_extraction_context_instantiation_minimal`: **PASSED**
- `test_extraction_context_instantiation_full`: **PASSED**
- `test_rule_based_extractor_with_context`: **PASSED**
- `test_rule_based_extractor_legacy_signature`: **PASSED**
- `test_rule_based_extractor_keyword_args`: **PASSED**
- `test_llm_based_extractor_with_context_mocked`: **PASSED**
- `test_llm_based_extractor_legacy_signature_mocked`: **PASSED**
- `test_llm_based_extractor_fallback_with_context`: **PASSED**
- `test_extraction_service_builds_and_passes_context`: **PASSED**
- All 27 existing `test_phase6_extraction.py` tests: **PASSED**
- All 6 existing `test_hybrid_llm_extraction.py` tests: **PASSED**

**Summary:** 42/42 targeted extraction tests passed in 13.81s.

---

## 22. Regression Results

Full test suite baseline verification: **226 passed, 0 failed**.  
No regressions detected across OCR, Classification, Extraction, Validation, Workflow, Audit, or API routers.

---

## 23. Known Limitations

- **Multi-page Table Reconstruction:** In accordance with the Phase 0 forensic audit and Phase 1 constraints, `TableReconstructor` operates on `raw_blocks[0]["blocks"]` (page 1). Multi-page table reconstruction is not expanded in Phase 1.
- **Extractor Intelligence:** `RuleBasedExtractor` and `LLMBasedExtractor` currently use `context.full_text` for extraction; consumption of `context.raw_blocks` and `context.table_data` for field extraction logic will occur in subsequent phases.

---

## 24. Explicit Confirmation

- **NO Phase 2 functionality** (Rule-based enhancements, spatial heuristics, layout regex) was implemented.
- **NO Phase 3 functionality** (`LLMContextBuilder`, prompt restructuring) was implemented.
- **NO Phase 4 functionality** (Parallel extractor orchestration) was implemented.
- **NO Phase 5 functionality** (`ReconciliationEngine`, conflict resolution) was implemented.
- **NO Phase 6 functionality** (Hybrid evaluation suite) was implemented.
- **NO RAG changes** were introduced.

---

## 25. Recommendation for Phase 2

Proceed to **Phase 2 — Rule-Based Extraction Enhancements**, where `RuleBasedExtractor` can be enhanced to consume `context.raw_blocks` and `context.table_data` for spatial bounding-box proximity queries and layout-aware field resolution without breaking deterministic rule guarantees.
