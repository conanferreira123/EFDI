# SEMANTIC INVOICE FIELD EXTRACTION — IMPLEMENTATION PLAN
# EFDI Phase: Extraction Layer Upgrade

**Date:** 2026-09-02  
**Status:** AWAITING APPROVAL — NO CODE CHANGES MAY BEGIN UNTIL EXPLICIT APPROVAL  
**Target File:** `SEMANTIC_EXTRACTION_IMPLEMENTATION_PLAN.md`  

---

## 1. Executive Summary & Objective

The primary objective of EFDI is:

```
OCR text + spatial layout + table structure
                ↓
        semantic understanding
                ↓
       reliable invoice fields
                ↓
        structured invoice data
```

The OCR and document structure layers (spatial reading-order layout, table line-item reconstruction, normalization, mathematical validation, composite quality scoring) have already been built and validated.

However, the **semantic extraction layer is the primary bottleneck**:
- It receives only a flat string (`full_text`) and a document type (`document_type`).
- It completely ignores 2D bounding boxes, spatial party regions, reconstructed table line items, and normalized numeric values.
- Its field schema is ERP-centric (expecting tokens like `Vendor Code:`, `Company Code:`) rather than standard invoice fields (`seller_name`, `buyer_name`, `line_items`, `grand_total`).
- Its extraction strategy relies solely on inline regex label-value matching, which fails on real-world invoices where labels are multiline, implicit, or formatted as `Seller:` / `Client:` / `Date of issue:`.

This plan outlines a phased, non-destructive path to transition EFDI from naive text-label matching to a **Spatial & Structural Hybrid Extraction Engine**.

---

## 2. Actual Code Inspection & Verification

Direct inspection of all relevant modules in `backend/app/` revealed the following verified facts:

### A. Extraction Layer
1. **`backend/app/extraction/base.py`**:
   - Defines `ExtractedField(value, confidence, matched_text)` and `ExtractionResultData(document_type, fields, engine_name)`.
   - `ExtractionEngine.extract(text: str, document_type: str)` is strictly 1D text-based.
2. **`backend/app/extraction/rule_based.py`**:
   - Active default runtime engine (`RuleBasedExtractor`).
   - Dispatches to `TYPE_EXTRACTORS` and merges `COMMON_FIELDS`.
3. **`backend/app/extraction/primitives.py`**:
   - `extract_by_labels()` searches `KNOWN_LABELS` (83 predefined stop-boundary labels).
   - Captures text until 2+ spaces, newline, or next known label.
   - `normalize_date()` parses ISO and day-first dates; `normalize_amount()` strips currency symbols.
4. **`backend/app/extraction/type_extractors.py`**:
   - Contains hardcoded label lists per document type (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA).
   - Lacks common real-world invoice labels such as `"Seller"`, `"Client"`, `"Date of issue"`, `"GSTIN"`, `"Tax Id"`.
5. **`backend/app/extraction/field_schemas.py`**:
   - 15 `COMMON_FIELDS` + per-type fields.
   - Completely missing `seller_name`, `buyer_name`, `seller_address`, `buyer_address`, `seller_tax_id`, `buyer_tax_id`, `grand_total`, `subtotal`, and line-item structures.
6. **`backend/app/extraction/llm_extractor.py` & `llm_schema.py`**:
   - LLM fallback exists but is inactive without `OPENAI_API_KEY`.
7. **`backend/app/extraction/rag_diagnostic.py`**:
   - Uses `DocumentChunk` and pgvector embeddings to reconcile arithmetic mismatches (`net + tax = total`), but only after initial extraction.

### B. Upstream OCR & Structural Layers
1. **`backend/app/ocr/easyocr_engine.py`**:
   - EasyOCR 1.7.2 with `add_margin=0.0`. Preserves 2D bounding boxes in `OCRTextBlock`.
2. **`backend/app/ocr/layout.py`**:
   - `order_blocks_spatially()` segments blocks into Top Metadata, Party Region (Left=Seller, Right=Buyer split at 50% width), and Table Body.
3. **`backend/app/ocr/table_reconstruction.py`**:
   - `TableReconstructor` geometrically clusters table cells into `StructuredLineItem` objects with columns `[description, quantity, unit, unit_price, net_amount, vat_rate, gross_amount]`.
4. **`backend/app/ocr/normalization.py`**:
   - `normalize_table_data()` converts table text into typed floats and standardized units while preserving raw strings.
5. **`backend/app/services/ocr_service.py`**:
   - Computes table reconstruction and normalization, but discards them as local variables after validation/scoring. Only `raw_blocks` (JSONB) and `full_text` (Text) are persisted in `ocr_results`.

---

## 3. End-to-End Extraction Flow Trace

```
[ PDF Document ]
       │
       ▼
[ rasterize_pdf (200 DPI) ] ──► [ AdaptivePreprocessor ] ──► [ EasyOCR Engine (add_margin=0.0) ]
                                                                       │
                                                                       ▼
                                                          [ raw_blocks with bboxes ]
                                                                       │
                                 ┌─────────────────────────────────────┴─────────────────────────────────────┐
                                 ▼                                                                           ▼
                     [ layout.py spatial order ]                                            [ table_reconstruction.py ]
                                 │                                                                           │
                                 ▼                                                                           ▼
                     [ full_text generation ]                                                    [ ReconstructedTable ]
                                 │                                                                           │
                                 ▼                                                                           ▼
                     [ DB: ocr_results.full_text ]                                              [ normalization.py ]
                                 │                                                                           │
                                 ▼                                                                           ▼
                     [ ClassificationService ]                                                [ validation.py & scoring ]
                                 │                                                                           │
                                 ▼                                                                           ▼
                   [ ClassificationResult (NPO) ]                                               [ DISCARDED (Local vars) ]
                                 │
                                 ▼
                     [ ExtractionService.extract ] ◄── Only receives full_text + doc_type!
                                 │
                                 ▼
                     [ RuleBasedExtractor ] ──► Searches flat text with regex label matching
                                 │
                                 ▼
                     [ ExtractionResult: 1/25 fields found ]
                                 │
                                 ▼
                     [ API: GET /extraction/result ] ──► [ Frontend: Extraction Tab ]
```

---

## 4. Real Invoice Case Study: `invoice_51109301.pdf`

Tracing the actual benchmark invoice `invoice_51109301.pdf` through the current pipeline reveals exactly why extraction fails:

### Actual OCR Output Present in Document
```
Invoice no: 51109301
Date of issue:
03/07/2023
Seller:
TechVision Distributors Pvt Ltd
Plot 14, MIDC Industrial Area; Andheri East
Mumbai; Maharashtra 400093
Tax Id: 27AABCT1234F1Z5
GSTIN: 2ZAABCT1234F1ZS
Client:
Raj Electronics Pvt Ltd
42 MG Road
Bengaluru, Karnataka 560001
Tax Id: 901-95-4704
ITEMS
Garmin Fenix 7 Solar Multisport GPS | 9.00 pcs | 74,120.00 | 667,080.00 | 10% | 733,788.00
Apple Watch Series 9 GPS 45mm       | 8.00 pcs | 52,083.00 | 416,664.00 | 10% | 458,330.40
Xiaomi 14 Pro 512GB White           | 8.00 pcs | 74,154.00 | 593,232.00 | 10% | 652,555.20
SUMMARY
Total INR 1,844,673.60
```

### Upstream vs. Extraction Layer Result

| Field | In Raw OCR? | In Table Recon? | Searched Label in Extractor | Extracted Result | Reason for Failure |
|---|---|---|---|---|---|
| `invoice_number` | YES ("Invoice no: 51109301") | N/A | `["Invoice Number", "Invoice No"]` | **51109301** (0.90) | **MATCHED** (Label alias existed) |
| `invoice_date` | YES ("03/07/2023") | N/A | `["Invoice Date"]` | `null` (0.00) | Document has `"Date of issue:"` on newline |
| `vendor_name` | YES ("TechVision Distributors...") | N/A | `["Vendor Name", "Vendor"]` | `null` (0.00) | Document has `"Seller:"` |
| `buyer_name` | YES ("Raj Electronics...") | N/A | Not in NPO schema | `null` (0.00) | Schema lacks buyer field; doc has `"Client:"` |
| `seller_tax_id` | YES ("27AABCT1234F1Z5") | N/A | Not in NPO schema | `null` (0.00) | Schema lacks Tax ID / GSTIN |
| `line_items` | YES (3 items reconstructed) | YES (3 items) | Not passed to extractor | `null` (0.00) | Extractor receives 0 table data |
| `grand_total` | YES ("1,844,673.60") | In summary | `["Invoice Amount", "Amount Due"]` | `null` (0.00) | Summary labeled as `"Total"` |

**Diagnosis:** The OCR text and upstream table reconstruction captured **100% of the invoice information**, but the extraction layer captured only **1 of 25 fields** due to rigid regex label expectations, lack of multiline handling, discarded table data, and missing schema fields.

---

## 5. Target Extraction Architecture

```
                                [ OCRResult in DB ]
                         (full_text + raw_blocks + dimensions)
                                         │
                                         ▼
                             [ ExtractionService ]
                                         │
                                         ▼
                             [ ExtractionContext ]
          ┌──────────────────────────────┼──────────────────────────────┐
          │                              │                              │
          ▼                              ▼                              ▼
 [ full_text + doc_type ]      [ raw_blocks + bboxes ]        [ table_data & normalized_items ]
          │                              │                              │
          └──────────────────────────────┼──────────────────────────────┘
                                         │
                                         ▼
                            [ HybridInvoiceExtractor ]
                                         │
       ┌─────────────────────────────────┼─────────────────────────────────┐
       ▼                                 ▼                                 ▼
1. Label Matcher                  2. Spatial Extractor             3. Table Extractor
   - Inline & Multiline              - Seller Region (Left)           - Structured line items
   - Expanded alias list             - Buyer Region (Right)           - Typed quantities & amounts
   - Stop-boundary parsing           - Positional Header              - Line item confidence
       │                                 │                                 │
       └─────────────────────────────────┼─────────────────────────────────┘
                                         │
                                         ▼
                     [ Conflict Resolution & Confidence Scorer ]
                                         │
                                         ▼
                            [ ExtractionResultData ]
                        (fields + line_items + evidence)
                                         │
                                         ▼
                        [ DB: extraction_results.fields ]
                                         │
                                         ▼
                        [ REST API & Enhanced React UI ]
```

---

## 6. ExtractionContext Specification

The `ExtractionContext` dataclass encapsulates all rich spatial, structural, and OCR evidence without requiring deep architectural rewrites:

```python
@dataclass
class ExtractionContext:
    document_id: int
    full_text: str
    document_type: str
    raw_blocks: list[dict]            # [{text, confidence, bounding_box}]
    page_width: float
    page_height: float
    table_data: dict | None           # ReconstructedTable.to_dict()
    normalized_items: list[dict]      # NormalizedLineItem dicts
    avg_ocr_confidence: float
    classification_confidence: float
    page_count: int = 1
```

### Lifecycle and Creation
- **Owner:** `ExtractionService.extract()`.
- **Construction:** Built in memory by fetching `OCRResult` and `ClassificationResult`.
- **Table Re-derivation:** If `table_data` is not in the DB, `ExtractionService` re-runs `reconstruct_table()` and `normalize_table_data()` on `raw_blocks` in <10ms, eliminating any immediate DB schema dependency.
- **Engine Extension:** `ExtractionEngine` in `base.py` adds `extract_from_context(context: ExtractionContext) -> ExtractionResultData`, with a default fallback delegating to `extract(context.full_text, context.document_type)`.

---

## 7. Target Field Schema & Compatibility

### Standard Invoice Field Mapping

| Category | Field Key | Field Label | Data Type | Schema Placement | Mapping / Aliases |
|---|---|---|---|---|---|
| **Document** | `invoice_number` | Invoice Number | `code` | COMMON | `"Invoice Number"`, `"Invoice No"`, `"Invoice #"` |
| | `invoice_date` | Invoice Date | `date` | COMMON | `"Invoice Date"`, `"Date of issue"`, `"Date"` |
| | `due_date` | Due Date | `date` | POI, NPO, MSI | `"Due Date"`, `"Payment Due"` |
| | `currency` | Currency | `code` | COMMON | `"Currency"`, `"INR"`, `"USD"`, `"EUR"` |
| **Seller** | `seller_name` | Seller Name | `text` | COMMON (New) | `"Seller"`, `"From"`, `"Vendor Name"`, Spatial Left |
| | `seller_address` | Seller Address | `text` | COMMON (New) | Spatial Left address block |
| | `seller_tax_id` | Seller Tax ID / GSTIN | `code` | COMMON (New) | `"GSTIN"`, `"Tax Id"`, Regex GST pattern |
| | `seller_iban` | Seller IBAN / Bank | `code` | COMMON (New) | `"IBAN"`, `"Bank A/C"` |
| **Buyer** | `buyer_name` | Buyer Name | `text` | COMMON (New) | `"Client"`, `"Bill To"`, `"Customer Name"`, Spatial Right |
| | `buyer_address` | Buyer Address | `text` | COMMON (New) | Spatial Right address block |
| | `buyer_tax_id` | Buyer Tax ID | `code` | COMMON (New) | `"Tax Id"` under Buyer region |
| **Totals** | `subtotal` | Subtotal / Net Amount | `amount` | POI, NPO, MSI | `"Subtotal"`, `"Net Worth"`, `"Taxable Value"` |
| | `tax_total` | Tax Total / VAT | `amount` | POI, NPO, MSI | `"Tax Amount"`, `"VAT"`, `"GST Total"` |
| | `grand_total` | Grand Total | `amount` | POI, NPO, MSI | `"Total"`, `"Gross Worth"`, `"Total Amount"` |
| | `amount_due` | Amount Due | `amount` | POI, NPO, MSI | `"Amount Due"`, `"Balance Due"` |
| **ERP Compat** | `vendor_name` | Vendor Name | `text` | POI, NPO (Retained)| Synced with `seller_name` |
| | `vendor_code` | Vendor Code | `code` | POI, NPO (Retained)| Retained for ERP integration |

### Backward Compatibility Strategy
1. **Additive Schema:** No existing field keys are deleted or modified in `field_schemas.py`.
2. **Dual-Population:** When `seller_name` is extracted, `vendor_name` is also populated with identical value and confidence to prevent breaking existing downstream ERP integrations.
3. **Dynamic Frontend:** The UI dynamically renders all fields returned in `ExtractionResult.fields`, so new fields appear automatically.

---

## 8. Spatial Extraction Engine

**Module:** `backend/app/extraction/spatial_extractor.py`

### Mechanism
1. **Region Detection:** Reuses boundary logic from `layout.py`:
   - Page upper 40% height is partitioned at X = 50% width.
   - Left Region: Scanned for seller anchor tokens (`"seller"`, `"from"`, `"vendor"`).
   - Right Region: Scanned for buyer anchor tokens (`"client"`, `"bill to"`, `"buyer"`, `"customer"`).
2. **Positional Name Extraction:**
   - Evaluates text blocks immediately below the anchor.
   - Filters out postal codes, phone numbers, email addresses, and tax IDs.
   - First non-address, non-numeric block is assigned as party name (`confidence = 0.65 - 0.85`).
3. **Address Clustering:**
   - Subsequent lines in the column bounding box are concatenated as `seller_address` / `buyer_address`.
4. **Safety & Fallback:**
   - If no party anchor is found or bounding boxes overlap mid-center, spatial extraction safely returns `None` and defers to label or pattern matching.

---

## 9. Table-to-Extraction Integration

**Module:** `backend/app/extraction/table_extractor.py`

### Mechanism
- Directly takes `context.normalized_items` (from `normalize_table_data`).
- Maps each line item to the structured representation:
  ```python
  {
      "item_number": item.normalized_item_number,
      "description": item.normalized_description,
      "quantity": item.normalized_quantity,
      "unit": item.normalized_unit,
      "unit_price": item.normalized_unit_price,
      "net_amount": item.normalized_net_amount,
      "tax_rate": item.normalized_vat_rate,
      "gross_amount": item.normalized_gross_amount,
      "confidence": item.confidence,
      "raw_text": item.raw_description
  }
  ```
- **Storage Strategy:** Structured line items are attached to `ExtractionResultData.line_items` and persisted in `extraction_results.fields["_line_items"]` as JSON.
- **Arithmetic Summary Reconciliation:** Line item net sums are cross-validated against extracted `subtotal` and `grand_total`.

---

## 10. Hybrid Extraction Strategy & Precedence

For each target field in the schema, candidate values are evaluated in order:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Candidate Evaluation Cascade                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Explicit Label Match (Inline)       ──► Conf: 0.85 - 0.90               │
│  2. Multiline Label Match (Header\nVal) ──► Conf: 0.75 - 0.85               │
│  3. Spatial Proximity / Region Match    ──► Conf: 0.65 - 0.80               │
│  4. Table / Summary Cell Extraction     ──► Conf: 0.80 - 0.95               │
│  5. Strict Regex Pattern (GSTIN, IBAN)  ──► Conf: 0.70 - 0.85               │
│  6. Diagnostic Fallback / Reconciliation──► Conf: 0.60 - 0.70               │
│  7. Unmatched Default                   ──► Value: null, Conf: 0.0          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Traceability & Evidence
Every extracted field populates:
- `value`: Normalized scalar string.
- `confidence`: Calibrated float (0.0 to 1.0).
- `matched_text`: Exact OCR text snippet.
- `source`: Extraction strategy tag (`"label_match"`, `"multiline_label"`, `"spatial"`, `"table"`, `"pattern"`, `"manual"`).

---

## 11. Classification-to-Extraction Coupling

- **Soft Routing:** If classification confidence is ≥ 0.50, the specific schema (e.g. `POI`, `NPO`, `MSI`) is used.
- **Resilience Fallback:** If classification confidence is < 0.50 or type is `UNKNOWN`, the extractor always attempts the standard universal invoice schema (`invoice_number`, `invoice_date`, `seller_name`, `buyer_name`, `grand_total`, `line_items`).
- **No Hard Failures:** Document processing will never abort due to ambiguous classification.

---

## 12. Database Architecture Decision

### Decision: NO immediate database migration required for Phase 1–6.

### Justification:
1. `ocr_results.raw_blocks` is already persisted as JSONB and contains all coordinates and text.
2. `extraction_results.fields` is already JSONB, supporting arbitrary new key-value pairs (`seller_name`, `buyer_name`, `_line_items`, `source`).
3. Re-running `reconstruct_table()` on `raw_blocks` in memory takes <10ms.
4. **Deferred Migration:** Adding dedicated `table_data` and `line_items` JSONB columns is deferred to a future performance optimization phase once the extraction engine is fully validated.

---

## 13. Extraction Confidence vs. Quality Metrics

To prevent architectural conflation, the system enforces strict distinction across 6 metrics:

```
┌─────────────────────────┬────────────────────────────────────────────────────────┐
│ Metric                  │ What it Actually Measures                              │
├─────────────────────────┼────────────────────────────────────────────────────────┤
│ OCR Confidence          │ EasyOCR character glyph visual certainty               │
│ Classification Conf     │ Confidence in document category assignment             │
│ Quality Score           │ Composite document health (structure + math checks)    │
│ Extraction Confidence   │ Evidence strength for an individual field extraction   │
│ Human Verification      │ 1.0 confidence flag indicating analyst manual review   │
│ Ground-Truth Accuracy   │ Exact mathematical match against verified ground truth │
└─────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 14. 8-Phase Implementation Plan

### Phase 1: Pipeline Plumbing & ExtractionContext
- **Objective:** Create `ExtractionContext` and update `ExtractionService` and `base.py` without modifying output behavior.
- **Files Created:** `backend/app/extraction/context.py`.
- **Files Modified:** `backend/app/extraction/base.py`, `backend/app/services/extraction_service.py`.
- **Testing:** Unit tests verifying context generation from `raw_blocks` and backward delegation to `extract()`.

### Phase 2: Label Expansion & Multiline Primitives
- **Objective:** Support newline-separated values and real-world aliases (`"Seller"`, `"Date of issue"`, `"Client"`, `"GSTIN"`).
- **Files Modified:** `backend/app/extraction/primitives.py`, `backend/app/extraction/type_extractors.py`.
- **Testing:** Unit tests on multiline invoice snippets.

### Phase 3: Schema Expansion (Standard Invoice Fields)
- **Objective:** Add standard fields (`seller_name`, `buyer_name`, `seller_tax_id`, `grand_total`, `subtotal`) to `field_schemas.py` and `COMMON_FIELDS`.
- **Files Modified:** `backend/app/extraction/field_schemas.py`, `backend/app/extraction/type_extractors.py`.
- **Testing:** Schema stability tests; verify old field keys are unaffected.

### Phase 4: Table-to-Extraction Integration
- **Objective:** Wire `reconstruct_table` and `normalize_table_data` output into `ExtractionResultData.line_items`.
- **Files Modified:** `backend/app/extraction/base.py`, `backend/app/services/extraction_service.py`, `backend/app/schemas/extraction.py`.
- **Testing:** Verify 3 line items correctly extracted for `invoice_51109301.pdf`.

### Phase 5: Spatial Header & Party Extractor
- **Objective:** Implement bounding-box region extraction for seller and buyer entities.
- **Files Created:** `backend/app/extraction/spatial_extractor.py`.
- **Testing:** Bounding-box test fixtures with left/right party layout.

### Phase 6: Hybrid Orchestrator & Evidence Traceability
- **Objective:** Combine all extractors in `HybridInvoiceExtractor` with precedence, confidence scoring, and source tagging.
- **Files Created:** `backend/app/extraction/hybrid_extractor.py`.
- **Files Modified:** `backend/app/extraction/factory.py`, `backend/app/schemas/extraction.py`.
- **Testing:** Comprehensive unit tests comparing `rule_based` vs `hybrid`.

### Phase 7: Real-Invoice Test Suite
- **Objective:** Create integration tests asserting extraction on real OCR results (`Batch 1/ocr_final_10_results.json`).
- **Files Created:** `backend/tests/test_real_invoice_extraction.py`, `backend/tests/fixtures/ocr_context_helpers.py`.
- **Testing:** Run pytest suite across 10 benchmark documents.

### Phase 8: Ground-Truth Completion & Benchmark
- **Objective:** Complete UNCLEAR fields in `ground_truth.json` and run automated accuracy benchmarking.
- **Files Created:** `backend/scripts/run_extraction_benchmark.py`.
- **Files Modified:** `Batch 1/ground_truth.json`.
- **Testing:** Generate benchmark accuracy report (Recall, Precision, F1).

---

## 15. Measurable Acceptance Criteria

1. **Zero Regression:** All existing 19 test suites in `backend/tests/` continue to pass.
2. **Invoice Number Recall:** 100% on benchmark dataset (maintained).
3. **Invoice Date Recall:** ≥ 80% on benchmark dataset (improved from 0%).
4. **Seller Name Recall:** ≥ 90% on benchmark dataset (improved from 0%).
5. **Seller Tax ID (GSTIN) Recall:** ≥ 85% on benchmark dataset (improved from 0%).
6. **Buyer Name Recall:** ≥ 70% on benchmark dataset (improved from 0%).
7. **Line Item Extraction:** 100% of line items from reconstructed tables populate in extraction results.
8. **Evidence Retention:** 100% of extracted non-null fields provide `source` and `matched_text`.
9. **Raw OCR Integrity:** `ocr_results.raw_blocks` remains immutable and unmodified.

---

## 16. Risks & Mitigations

| Risk | Severity | Mitigation Strategy |
|---|---|---|
| **Homogeneous Dataset (TechVision vendor)** | High | Test against diverse invoice structures; enforce strict label/spatial confidence gating. |
| **50% Column Split Failure** | Medium | Require party anchor tokens before activating spatial extraction; fallback to label search. |
| **Multiline Regex Overcapture** | Medium | Limit multiline capture to single line; enforce character length cap (80 chars). |
| **Ground Truth Gaps** | High | Complete manual verification of `ground_truth.json` before Phase 8 benchmark. |

---

## 17. What Must NOT Be Changed

1. `ocr_results.raw_blocks` storage schema and immutability.
2. `EasyOCREngine` parameterization (`add_margin=0.0`, 200 DPI).
3. `order_blocks_spatially()` layout algorithm in `layout.py`.
4. `TableReconstructor` core geometric clustering logic.
5. `normalize_table_data()` numeric and date normalization routines.
6. Existing ERP field keys in `field_schemas.py`.
7. Existing authentication, RBAC, and audit log pipelines.

---

## 18. Final Summary & Confirmation

### Plan Summary
- **Plan File Path:** `C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\SEMANTIC_EXTRACTION_IMPLEMENTATION_PLAN.md`
- **Current Extraction Bottleneck:** 1D flat string input discarding spatial bboxes and table structures, coupled with ERP-rigid label expectations.
- **Proposed Solution:** In-memory `ExtractionContext` feeding a `HybridInvoiceExtractor` that combines expanded label matching, multiline parsing, spatial party extraction, and direct table-to-line-item integration.
- **Number of Phases:** 8 logical, risk-managed phases.
- **Database Migration Required:** **NO** (all changes leverage existing JSONB columns and in-memory reconstruction).
- **API Changes Required:** **NO breaking changes** (additive optional `line_items` list and `source` tag).
- **Frontend Changes Required:** **NO breaking changes** (fields render dynamically; optional dedicated line-items table).
- **Expected Testing Approach:** Pytest unit tests, real OCR JSON fixture tests, and an automated ground-truth accuracy benchmark script.

> **Will EFDI turn OCR data into structured invoice fields after this plan?**  
> **YES.** By bridging the gap between upstream structural reconstruction (which already successfully parses line items and party blocks) and the extraction layer, EFDI will immediately extract seller names, buyer names, dates, tax IDs, totals, and structured line items directly from real invoices without requiring external ML/LLM dependencies.
