# EFDI — Current Architecture and Extraction Status Report

**Date:** 2026-09-02
**Project root:** C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI

---

## 1. Executive Summary

### What is EFDI today?
EFDI is a **partially integrated document-intelligence platform**. It has a functional OCR pipeline with recently improved spatial awareness, a working document classification system, and the structural scaffolding for extraction — but the semantic extraction layer is **underdeveloped relative to the system primary objective**.

### Final Answer
> **EFDI is currently a partially integrated document-intelligence system.** The OCR and structural analysis layers are functional. The extraction layer exists architecturally but is semantically incomplete: it performs label-keyword matching against flattened text, ignores spatial coordinates and table structure, and uses an ERP-centric field schema that does not match the standard invoice fields visible in real invoices from the dataset.

---

## 2. End-to-End Architecture

### Flow

`
USER → FRONTEND → API → DocumentService → FileStorage + DB
                        OCRService → AdaptivePreprocessor → EasyOCREngine
                                   → order_blocks_spatially (layout.py)
                                   → reconstruct_table (table_reconstruction.py)
                                   → normalize_table_data (normalization.py)
                                   → validate_ocr_output (validation.py)
                                   → calculate_quality_score (quality_scoring.py)
                                   → OCRResult persisted in DB
                        ClassificationService → RuleBasedClassifier(full_text) → ClassificationResult
                        ExtractionService → RuleBasedExtractor(full_text, document_type) → ExtractionResult
                   → API → FRONTEND
`

### Stage Summary Table

| Stage | Module | Maturity | Known Limitation |
|-------|--------|----------|-----------------|
| Upload | document_service.py | FUNCTIONAL | — |
| OCR | easyocr_engine.py | FUNCTIONAL | CPU only; English only |
| Spatial layout | layout.py | FUNCTIONAL | Fixed 50% midpoint column split |
| Table reconstruction | table_reconstruction.py | FUNCTIONAL | Page 1 only; not persisted |
| Normalization | normalization.py | FUNCTIONAL | Table line items only |
| Validation | validation.py | FUNCTIONAL | Math only — not ground-truth accuracy |
| Quality scoring | quality_scoring.py | FUNCTIONAL | Internal metric only |
| Classification | classification_service.py | PARTIAL | Rule-based; ML untrained |
| **Field extraction** | **extraction_service.py** | **PARTIAL** | **Ignores spatial + table data** |
| API | routers/*.py | FUNCTIONAL | — |
| Frontend | React pages | FUNCTIONAL | Shows only what extractor finds |

---

## 3. OCR Layer

**Engine:** EasyOCR 1.7.2
**Language:** English only
**DPI:** 200
**GPU:** Disabled (cpu)
**Key improvement:** add_margin=0.0 (eliminates 3_ and pCs artifacts)

### Raw block structure (persisted in ocr_results.raw_blocks):
`json
{
   page_number: 1,
  page_width: 1654,
  page_height: 2339,
  blocks: [
    {text: INVOICE, confidence: 0.97, bounding_box: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}
  ]
}
`

### Changes vs original:
| Item | Original | Current |
|------|----------|---------|
| add_margin | Default (0.1) | 0.0 — eliminates expansion artifacts |
| Reading order | Naive EasyOCR order | Spatial column decomposition |
| raw_blocks | Not persisted | Always persisted, never overwritten |

---

## 4. Spatial Layout Layer

**Module:** backend/app/ocr/layout.py — order_blocks_spatially()

Splits page into three vertical bands:
1. Top metadata (Invoice No, Date — above party region)
2. Party information (Seller left / Buyer right at X = 50% page width)
3. Body/table section

**What this SOLVES:** Prevents column interleaving in full_text.

**What this DOES NOT solve:**
- Spatial ordering makes full_text more coherent, but ALL bounding-box coordinates are lost when blocks are joined into a newline-separated string.
- The extractor never receives region membership (seller vs buyer) — it only receives the flat string.
- Spatial ordering of ACME CORP before GLOBAL BUYERS does not tell the extractor that ACME CORP = seller_name.

---

## 5. Table Reconstruction

**Module:** backend/app/ocr/table_reconstruction.py

Detects table header keywords, derives column X-intervals, clusters rows by Y-center proximity (16px tolerance), assembles StructuredLineItem objects.

### Output structure:
`
ReconstructedTable(
    headers=[description, quantity, unit_price, net_amount, vat_rate, gross_amount],
    line_items=[
        StructuredLineItem(
            description=Product Alpha,
            quantity=10,
            unit_price=50.00,
            net_amount=500.00,
            vat_rate=10%,
            gross_amount=550.00,
            confidence=0.93
        )
    ]
)
`

**CRITICAL FINDING:** Table reconstruction is computed in ocr_service.py but:
- Is NOT persisted as a queryable DB entity
- Is NOT passed to ExtractionService
- Is NOT consumed by RuleBasedExtractor
- Exists only as a local variable used for quality scoring and audit logging

The structured line items that table reconstruction correctly identifies are NEVER used for extraction.

---

## 6. Normalization

**Module:** backend/app/ocr/normalization.py

Handles: European vs US numeric formats, OCR punctuation artifacts (52.,083.00), percentage parsing (10% → 0.10), date normalization (15/06/2026 → 2026-06-15), unit normalization (pCs → pcs).

**Raw values always preserved alongside normalized values** — architecturally correct.

**Scope:** Only covers table line items. Does NOT normalize header fields extracted from full_text.

---

## 7. Validation

**Module:** backend/app/ocr/validation.py

Rules: ITEM math (qty × price ≈ net), document totals (subtotal + vat ≈ grand), required keyword presence.

> IMPORTANT: Internal mathematical validation does NOT prove OCR correctness.
> If OCR misreads 250.00 as 260.00 and quantity is 10, net_amount=2600 is internally consistent.
> Validation is a sanity/consistency layer, NOT ground-truth accuracy measurement.

---

## 8. Quality Scoring

**Module:** backend/app/ocr/quality_scoring.py

Formula:
`
overall = 0.35 × ocr_confidence + 0.25 × structural_score + 0.25 × math_validation + 0.15 × field_completeness
`

**What it measures:** Internal structural quality.
**What it does NOT measure:** Whether extracted field values are correct.

> OCR confidence ≠ extraction accuracy ≠ ground-truth accuracy.
> A document scoring EXCELLENT (0.90) can still produce 1 of 23 fields found in extraction.

---

## 9. Classification

**Module:** backend/app/classification/ — RuleBasedClassifier (default), MLClassifier (available but untrained)

9 types: POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA

### Manual correction (24% → 100%) analysis:
Confirmed from classification_result_repository.py:
`python
def correct_type(self, result, corrected_type):
    result.predicted_type = corrected_type
    result.confidence = 1.0  # ← hardcoded on manual correction
    # engine_name/signals/scores_by_type left unchanged (historical record)
`

**This behavior is WORKING AS DESIGNED.** confidence=1.0 represents human certainty.
The display distinction (Classification source: Manually corrected vs model percentage) is a frontend UX concern, not a backend bug.

### Classification → Extraction link:
ExtractionService reads document_type from ClassificationResult and passes it to the extractor.
This determines which field schema is used. A wrong classification means the wrong schema and near-zero field population.

---

## 10. Extraction Layer — Primary Focus

### Which implementation runs at runtime?
**DEFAULT: RuleBasedExtractor** (EXTRACTION_DEFAULT_ENGINE = rule_based in config.py)

### LLMBasedExtractor status:
Available but NOT active unless:
1. Explicitly requested via engine=llm_based in API call
2. OPENAI_API_KEY is configured
Without an API key, falls back to RuleBasedExtractor.

### What input does the extractor receive?

| Input | Received? | Evidence |
|-------|-----------|---------|
| full_text (flat string) | YES | extraction_service.py L54 |
| document_type (string) | YES | extraction_service.py L50 |
| raw_blocks (bounding boxes) | NO | Not passed |
| table_data (line items) | NO | Computed in ocr_service but not stored/passed |
| normalized_items | NO | Same — computed, not persisted |
| validation_result | NO | Used only for quality scoring |
| spatial region metadata | NO | Lost when blocks become full_text |

**ExtractionEngine.extract(text: str, document_type: str) → ExtractionResultData**

The interface accepts only a flat string and a type code.

### How label matching works (primitives.py):
1. Builds regex: \bLabel\b[:\-=]?\s*([^\n]*?)(?=\s{2,}|\n|next_label|$)
2. Uses 83 KNOWN_LABELS as stop-boundaries to prevent over-capture
3. Confidence: 0.9 for first label in list, -0.1 per additional fallback
4. Date fields: normalized to ISO (YYYY-MM-DD)
5. Amount fields: stripped of currency symbols and thousands separators

---

## 11. Current Extracted Fields

### Common Fields (all 9 document types):
document_id, document_type, document_category, company_code, company_name, fiscal_year, location_code, vertical_code, document_source, barcode, currency, document_date, ocr_confidence_score, processing_status, validation_status

### NPO (Non-PO Invoice) specific fields:
vendor_code, vendor_name, invoice_number, invoice_date, invoice_amount, expense_category, cost_center, department, tax_amount, net_amount

### POI (PO Invoice) specific fields:
vendor_code, vendor_name, po_number, grn_number, srn_number, invoice_number, invoice_date, invoice_amount, tax_amount, net_amount, payment_terms

### Standard invoice fields NOT in any schema:

| Standard field | In schema? | Extractor? |
|----------------|-----------|-----------|
| seller_name | NO | NO |
| seller_address | NO | NO |
| seller_tax_id | NO | NO |
| seller_iban | NO | NO |
| buyer_name | NO | NO (customer_name exists in MSI only) |
| buyer_address | NO | NO |
| buyer_tax_id | NO | NO |
| line_item.description | NO | NO (table only) |
| line_item.quantity | NO | NO (table only) |
| line_item.unit | NO | NO (table only) |
| line_item.unit_price | NO | NO (table only) |
| line_item.gross_amount | NO | NO (table only) |
| subtotal | NO | NO |
| tax_total | NO | NO |
| grand_total | NO | NO |
| due_date | MSI only | MSI only |

---

## 12. Invoice Trace (invoice_51109301.pdf → NPO classification)

| Stage | Data available | Data lost | Module |
|-------|----------------|-----------|--------|
| Raw OCR | text + confidence + bounding boxes | Nothing | easyocr_engine.py |
| Spatial OCR | Reordered blocks, still with bboxes | Nothing | layout.py |
| full_text generation | Ordered text string | ALL bounding-box coordinates | ocr/base.py |
| Table reconstruction | Structured line items | Nothing | table_reconstruction.py |
| Normalization | Typed numeric values | Nothing | normalization.py |
| **Extraction input** | **full_text + document_type ONLY** | **Table data, bboxes, normalized items** | extraction_service.py |
| Extraction logic | Only label-matched fields | All fields without expected ERP labels | rule_based.py |
| API response | fields_found_count=1, rest null | — | extraction.py |
| Frontend | 1 of 25 fields found | — | extraction-fields.tsx |

### Why 1 of 25 fields found:

The invoice header says FROM: not Vendor Name:. The extractor searches for \bVendor Name\b — not found.
The invoice number uses Invoice No: format — this IS in the label list, so invoice_number IS found.
All other fields return null because the real-world invoice does not use ERP label format.

---

## 13. Extraction Failure Analysis

**Root cause: Option C — OCR contains the information but semantic extraction does not recognize it.**

- A (OCR missing data): FALSE — OCR text contains vendor names, dates, amounts
- B (layout loses data): FALSE for most fields — full_text contains the text in correct order
- C (extraction does not recognize it): TRUE — extractor searches for ERP labels absent from real invoices
- D (normalization loses it): FALSE — normalization is correct when extraction finds a value
- E (API does not return it): FALSE — API returns exactly what the extractor produces
- F (frontend does not display it): FALSE — frontend displays all API fields

**Additional contributing factor:** The field schema itself is ERP-centric. Even if the extractor parsed FROM: Vendor Corp Sdn Bhd, there is no seller_name field in the NPO schema. vendor_name requires the exact label Vendor Name or Vendor.

---

## 14. Extraction Architecture Assessment

### Confirmed coupling issues:
1. ocr_service.py orchestrates OCR → layout → table → normalization → validation → quality in one method. Table data is computed but never stored.
2. ExtractionEngine.extract(text, document_type) interface is too narrow — designed for text-only extraction.
3. Table reconstruction output is not persisted as a queryable entity.

### Missing abstractions:
- No DocumentRepresentation object carrying full_text + raw_blocks + table_data through the pipeline
- No spatial extraction primitive (only label-text-based primitives exist)
- No line-item extraction primitive consuming table_data.line_items

---

## 15. Desired Extraction Architecture (without implementation)

`
raw_blocks (bbox + text + confidence)
    + full_text (spatial ordering applied)
    + table_data (reconstructed line items)
    + normalized_items
    + document_type
            ↓
    INVOICE FIELD EXTRACTOR
            ↓
    structured invoice object
`

**Step 1 — Schema expansion:** Add seller_name, seller_address, buyer_name, buyer_address, subtotal, tax_total, grand_total, and line-item fields to NPO/POI/MSI schemas.

**Step 2 — ExtractionContext:** Define ExtractionContext(full_text, raw_blocks, table_data, normalized_items) dataclass. Modify or overload ExtractionEngine.extract() to accept it.

**Step 3 — Table-based line item extractor:** Consume context.table_data.line_items directly. Map StructuredLineItem fields to extraction schema keys.

**Step 4 — Spatial header extractor:** Use context.raw_blocks bounding boxes. Identify seller region (left-column blocks above table start). Extract seller name from first significant text block in seller region. Same for buyer (right column).

**Step 5 — Persist table_data:** Add table_data JSONB column to ocr_results. Store table_dict during ocr_service.run_ocr(). ExtractionService fetches ocr_result.table_data and builds ExtractionContext.

**Step 6 — Hybrid extractor:** Precedence: label-matching → spatial → table → null. Higher-confidence value wins on conflict.

---

## 16. Rule-Based vs Spatial Extraction

**Current:** Label-keyword matching — works for ERP-formatted docs with Label: Value pattern, fails for real-world invoices.

**Recommended: Hybrid approach:**
1. Label-keyword matching (keep) — for explicitly labeled fields
2. Spatial/proximity extraction (add) — for seller/buyer from positional regions (already computed in layout.py)
3. Table-output integration (add) — line items from table_data.line_items (already computed, just not connected)
4. Pattern-based extraction (targeted) — for structured codes (GST, IBAN)
5. LLM extraction (conditional) — only when rule-based + spatial fails minimum field count threshold

> Do NOT default to LLM. The spatial and table data already computed is sufficient to dramatically improve extraction without any ML model.

---

## 17. Benchmark Status

### OCR benchmarks: EXIST
- 10-invoice baseline established
- 10-invoice improved benchmark after add_margin=0.0 and spatial ordering
- Documented in OCR_PIPELINE_IMPROVEMENT_REPORT.md

### Extraction benchmarks: DO NOT EXIST
- No extraction accuracy benchmark against verified ground truth
- fields_found_count / fields_total_count is an internal metric (pattern match count)
- overall_confidence is the average confidence of pattern matches — NOT semantic accuracy
- quality_score is an internal structural metric — NOT extraction accuracy

> OCR confidence ≠ extraction accuracy ≠ ground-truth accuracy.
> These three must never be conflated.

---

## 18. Test Coverage

| Component | Test file | Tests semantic extraction? |
|-----------|----------|--------------------------|
| OCR layout | test_ocr_layout.py | NO — tests ordering |
| Table reconstruction | test_ocr_table_reconstruction.py | PARTIALLY — geometric only |
| Normalization | test_ocr_normalization.py | NO — tests parsing |
| Validation | test_ocr_validation.py | NO — tests math rules |
| Classification | test_phase5_classification.py | NO — tests type assignment |
| Extraction | test_phase6_extraction.py | PARTIALLY — synthetic ERP text only |

### Critical finding on test_phase6_extraction.py:
Tests use synthetic perfectly-formatted text:
`
Invoice Number: INV-2026-001
Vendor Name: Acme Corporation
`
These tests verify that extract_by_labels() finds values in ERP-formatted text.
They do NOT test extraction from real-world invoice OCR output where labels may be absent.
A passing test suite does NOT prove that seller_name, buyer_name, line-item extraction, or any field works on the actual invoice dataset.

---

## 19. Architectural Strengths

1. Raw evidence preservation — raw_blocks persisted verbatim, never overwritten
2. Pluggable engine abstractions — OCR, Classification, Extraction all have abstract interfaces + factories
3. Non-destructive normalization — raw and normalized values both stored
4. Classification drives extraction schema — semantically correct design
5. Manual correction with training data capture — both classification and field corrections recorded
6. Spatial layout infrastructure exists — raw blocks with bboxes persisted; spatial data is available
7. Table reconstruction is working — it just needs to be connected to extraction

---

## 20. Architectural Weaknesses

### CRITICAL
1. Extraction ignores all spatial data — extractor receives only (full_text, document_type)
2. Table data not persisted as queryable entity — computed as local variable, discarded
3. Field schema uses ERP terminology — seller_name, buyer_name, line items absent from schema

### HIGH
4. Label matching requires explicit labels — fails on real invoices with positional fields
5. No extraction accuracy measurement exists
6. Wrong classification → completely wrong schema → near-zero field population

### MEDIUM
7. Table reconstruction only processes page 1
8. Spatial column split fixed at 50% page width

---

## 21. System Maturity Matrix

| Component | Status | Main Gap |
|-----------|--------|----------|
| Document ingestion | FUNCTIONAL | — |
| OCR (EasyOCR) | FUNCTIONAL | English only; CPU only |
| Spatial layout | FUNCTIONAL | Fixed 50% midpoint heuristic |
| Table reconstruction | FUNCTIONAL | Not persisted; page 1 only |
| Normalization | FUNCTIONAL | Table only; not header fields |
| Validation | FUNCTIONAL | Cannot prove OCR accuracy |
| Quality scoring | FUNCTIONAL | Not correlated with extraction accuracy |
| Classification | PARTIAL | No verified accuracy on real invoices |
| Field extraction | PARTIAL | Missing spatial + table integration; wrong schema |
| API | FUNCTIONAL | — |
| Frontend | FUNCTIONAL | Shows only what extractor finds |
| Testing | PARTIAL | No real-invoice extraction tests |

---

## 22. Priority Gap Analysis

| Priority | Gap | Impact |
|----------|-----|--------|
| CRITICAL | Extraction ignores table reconstruction output | Line items never extracted |
| CRITICAL | Extraction ignores spatial region data | Seller/buyer never extracted from real invoices |
| CRITICAL | Field schema missing standard invoice fields | seller_name, buyer_name, addresses, totals absent |
| HIGH | No extraction accuracy measurement | Cannot know if improvements work |
| HIGH | Label matching fails on unlabeled positional fields | Most real invoice fields missed |
| MEDIUM | Table data not persisted as queryable entity | Cannot re-use across pipeline stages |
| MEDIUM | Classification accuracy unverified on real invoices | Wrong type → wrong schema |

---

## 23. Recommended Next Development Phase

**Phase: Semantic Invoice Field Extraction**

1. Persist table_data in ocr_results (DB migration — add table_data JSONB column)
2. Expand field schema with seller_name, seller_address, buyer_name, buyer_address, subtotal, tax_total, grand_total, line-item fields
3. Create ExtractionContext(full_text, raw_blocks, table_data, normalized_items)
4. Create spatial extraction primitive using left_party/right_party blocks from layout.py logic
5. Create table extraction primitive mapping StructuredLineItem → ExtractionResult fields
6. Create hybrid extractor: label-match → spatial → table → null (highest confidence wins)
7. Create ground-truth fixture set for 10+ real invoices and measure accuracy per field

---

## 24. Extraction Quality Measurement

### Required: verified ground-truth dataset (manually verified field values for 10–20 invoices)

| Metric | Formula |
|--------|---------|
| Field presence recall | found_fields / total_schema_fields |
| Field value accuracy | correct_values / found_fields |
| Numeric accuracy | abs(extracted - true) / true < 1% |
| Date accuracy | Exact match on ISO date |
| Line-item F1 | Precision × Recall on matched rows |

---

## 25. Final Assessment

### What is working well?
- Complete OCR pipeline from PDF to raw blocks and full_text
- Spatial reading-order reconstruction
- Table reconstruction identifying line items geometrically
- Non-destructive normalization
- Extraction infrastructure (interface, factory, schema, persistence)
- Manual correction workflow

### What has genuinely improved vs original?
- add_margin=0.0 eliminated 3_ artifact and pCs noise
- Spatial layout ordering produces coherent full_text instead of interleaved columns
- Table reconstruction produces structured line items (unavailable before)
- Normalization handles European formats, percentages, multiple date formats
- Adaptive preprocessing selects optimal image enhancement per document

### What remains incomplete?
- Semantic field extraction from real-world invoices
- Standard invoice field schema (seller_name, buyer_name, line items)
- Integration of table reconstruction into extraction
- Integration of spatial data into extraction
- Extraction accuracy measurement against verified ground truth

### What is the current bottleneck?
**The extraction layer.** Specifically:
1. ExtractionEngine.extract(text, document_type) discards all spatial and structural data
2. The field schema does not include standard invoice terminology
3. Label-matching requires explicit Label: Value text patterns absent from most real invoices

### What should NOT be changed?
- raw_blocks persistence (audit foundation)
- Non-destructive normalization approach
- Abstract engine interfaces
- Table reconstruction logic (working; just needs to be connected)
- Spatial layout logic (working; just needs to produce structured metadata)

### What should be developed next?
> We have already improved OCR and document structure. Now we need to build the semantic extraction layer that consumes the structural data already computed.

1. Persist table_data in ocr_results
2. Expand field schema to standard invoice fields
3. Create spatial extraction primitive using existing bbox data
4. Create table extraction primitive consuming existing table_data
5. Measure extraction accuracy against verified ground-truth fixtures

---

## Evidence Sources

| Finding | Source file |
|---------|------------|
| Extractor receives only full_text + document_type | extraction_service.py L54 |
| Table data not passed to extractor | ocr_service.py L127-136 |
| Extractor interface signature | extraction/base.py L70 |
| Field schema (ERP-centric) | extraction/field_schemas.py |
| Label patterns used | extraction/type_extractors.py, primitives.py |
| add_margin=0.0 confirmation | easyocr_engine.py L99 |
| Spatial ordering code | ocr/layout.py L33-139 |
| Table reconstruction code | ocr/table_reconstruction.py |
| Classification drives extraction type | extraction_service.py L50-54 |
| Manual correction sets confidence=1.0 | classification_result_repository.py L67-68 |
| Tests use synthetic ERP text | test_phase6_extraction.py L32-59 |
| Quality score formula | quality_scoring.py L116-122 |
