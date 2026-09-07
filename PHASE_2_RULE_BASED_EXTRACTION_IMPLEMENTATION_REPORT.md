# PHASE 2 — RULE-BASED EXTRACTION IMPLEMENTATION REPORT

**Date:** September 6, 2026  
**Status:** COMPLETED — PENDING REVIEW & AUTHORIZATION  
**Phase:** Hybrid Extraction Pipeline — Phase 2  

---

## 1. Phase 2 Objective

The objective of Phase 2 is to improve the deterministic `RuleBasedExtractor` by selectively and conservatively utilizing structured `ExtractionContext` evidence (`raw_blocks` and `table_data`) where it provides genuine extraction value that flattened `full_text` alone cannot reliably provide.

Key principles enforced throughout Phase 2:
- `full_text` remains the primary textual extraction source.
- `raw_blocks` spatial queries provide deterministic secondary fallback/refinement when text regex captures are missing or weak due to multi-block layout splits.
- `table_data` provides deterministic calculations for summary amounts (net amount, gross amount, tax amount) when text summary lines are missing or ambiguous.
- 100% graceful fallback to pure text regex when structured OCR evidence is absent.
- No database changes, no OCR changes, no LLM prompt redesigns, no RAG, and no reconciliation.

---

## 2. Initial Field-by-Field Audit

A comprehensive read-only audit across all 9 supported document types identified the following characteristics:
- **Common Fields:** Metadata fields (e.g. `company_code`, `document_id`, `document_date`) often appear in header bands where labels and values are separated into distinct OCR blocks.
- **Invoice / AP Fields (POI, NPO, DPR, IMA):** Vendor names, PO numbers, and invoice numbers frequently appear as two-box pairs (label in box A, value in box B to the right or below). Net, tax, and gross amounts often appear in structured summary tables.
- **R2R Fields (MSI, PSI, JER, BKA, LCA):** Account numbers, bank names, LC numbers, and advice dates similarly follow key-value box layouts.
- **Strictly Text Fields:** Fields representing categories, free-form text, or internal status (`document_category`, `fiscal_year`, `processing_status`, `validation_status`, `payment_terms`, `purpose`, `country`) are naturally inline and do not benefit from spatial heuristics.

---

## 3. Complete Field Strategy Matrix

| Document Type | Field | Existing Strategy | Phase 2 Strategy | Primary Source | Secondary Source | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Common** | `document_id` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block label-value separation in header |
| **Common** | `document_category` | TEXT | TEXT | `full_text` | None | Categorical taxonomy lookup |
| **Common** | `company_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header block separation |
| **Common** | `company_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header party block proximity |
| **Common** | `fiscal_year` | TEXT | TEXT | `full_text` | None | Highly distinctive inline regex (FY\d{4}) |
| **Common** | `location_code` | TEXT | TEXT | `full_text` | None | Direct code label capture |
| **Common** | `vertical_code` | TEXT | TEXT | `full_text` | None | Direct code label capture |
| **Common** | `document_source` | TEXT | TEXT | `full_text` | None | Direct text label capture |
| **Common** | `barcode` | TEXT | TEXT | `full_text` | None | Direct barcode string capture |
| **Common** | `currency` | TEXT | TEXT | `full_text` | None | Direct 3-letter currency code capture |
| **Common** | `document_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block date box adjacent to label |
| **Common** | `ocr_confidence_score` | SYSTEM | SYSTEM | OCR result | None | Directly populated by service |
| **Common** | `processing_status` | TEXT | TEXT | `full_text` | None | Fixed system/document status string |
| **Common** | `validation_status` | TEXT | TEXT | `full_text` | None | Fixed system/document status string |
| **POI** | `vendor_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block party box alignment |
| **POI** | `vendor_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header/party block neighbor |
| **POI** | `po_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right/below adjacent block value |
| **POI** | `grn_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right/below adjacent block value |
| **POI** | `srn_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right/below adjacent block value |
| **POI** | `invoice_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right/below adjacent block value |
| **POI** | `invoice_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block date box adjacent to label |
| **POI** | `invoice_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Summary table line calculation fallback |
| **POI** | `tax_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Summary table line calculation fallback |
| **POI** | `net_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Summary table line calculation fallback |
| **POI** | `payment_terms` | TEXT | TEXT | `full_text` | None | Inline sentence/clause |
| **NPO** | `vendor_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block party box alignment |
| **NPO** | `vendor_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header/party block neighbor |
| **NPO** | `invoice_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right/below adjacent block value |
| **NPO** | `invoice_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Multi-block date box adjacent to label |
| **NPO** | `invoice_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Summary table line calculation fallback |
| **NPO** | `expense_category` | TEXT | TEXT | `full_text` | None | Inline category description |
| **NPO** | `cost_center` | TEXT | TEXT | `full_text` | None | Direct code capture |
| **NPO** | `department` | TEXT | TEXT | `full_text` | None | Direct text label capture |
| **NPO** | `tax_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Table summary line fallback |
| **NPO** | `net_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Table summary line fallback |
| **DPR** | `request_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header label-value box separation |
| **DPR** | `request_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **DPR** | `vendor_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Party block separation |
| **DPR** | `vendor_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Party block separation |
| **DPR** | `po_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Right-side block neighbor |
| **DPR** | `requested_amount`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Amount box neighbor |
| **DPR** | `advance_percentage` | TEXT | TEXT | `full_text` | None | Inline percentage token |
| **DPR** | `purpose` | TEXT | TEXT | `full_text` | None | Multi-word narrative text |
| **DPR** | `approval_status` | TEXT | TEXT | `full_text` | None | Status keyword |
| **IMA** | `employee_id` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form box label-value separation |
| **IMA** | `employee_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form box label-value separation |
| **IMA** | `claim_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form box label-value separation |
| **IMA** | `claim_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **IMA** | `travel_start_date`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **IMA** | `travel_end_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **IMA** | `expense_category` | TEXT | TEXT | `full_text` | None | Inline category keyword |
| **IMA** | `claim_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form amount box neighbor |
| **IMA** | `approved_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form amount box neighbor |
| **IMA** | `manager_approval_status` | TEXT | TEXT | `full_text` | None | Status keyword |
| **MSI** | `customer_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Party box neighbor |
| **MSI** | `customer_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Party box neighbor |
| **MSI** | `sales_invoice_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header box neighbor |
| **MSI** | `sales_invoice_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Header box date neighbor |
| **MSI** | `invoice_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Table line item gross total |
| **MSI** | `tax_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Table line item tax total |
| **MSI** | `net_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` / `table_data` | Table line item net total |
| **MSI** | `due_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **MSI** | `payment_terms` | TEXT | TEXT | `full_text` | None | Inline sentence/clause |
| **PSI** | `pis_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip header box neighbor |
| **PSI** | `pis_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip date box neighbor |
| **PSI** | `customer_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip party box neighbor |
| **PSI** | `customer_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip party box neighbor |
| **PSI** | `bank_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Bank header box neighbor |
| **PSI** | `deposit_amount`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip amount box neighbor |
| **PSI** | `deposit_reference_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip reference box neighbor |
| **PSI** | `deposit_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Slip date box neighbor |
| **PSI** | `reconciliation_status` | TEXT | TEXT | `full_text` | None | Status keyword |
| **JER** | `journal_entry_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Voucher header box neighbor |
| **JER** | `posting_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **JER** | `gl_account_code` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Table/form grid box neighbor |
| **JER** | `gl_account_description` | TEXT | TEXT | `full_text` | None | Multi-word account narrative |
| **JER** | `debit_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Grid column amount |
| **JER** | `credit_amount`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Grid column amount |
| **JER** | `cost_center` | TEXT | TEXT | `full_text` | None | Direct code capture |
| **JER** | `profit_center`| TEXT | TEXT | `full_text` | None | Direct code capture |
| **JER** | `reference_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Form box neighbor |
| **JER** | `approval_status` | TEXT | TEXT | `full_text` | None | Status keyword |
| **BKA** | `advice_number`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice header box neighbor |
| **BKA** | `advice_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice date box neighbor |
| **BKA** | `bank_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice header box neighbor |
| **BKA** | `account_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice account box neighbor |
| **BKA** | `transaction_reference` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice reference box neighbor |
| **BKA** | `transaction_type` | TEXT | TEXT | `full_text` | None | Credit/Debit keyword |
| **BKA** | `transaction_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice amount box neighbor |
| **BKA** | `value_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Advice date box neighbor |
| **BKA** | `reconciliation_status` | TEXT | TEXT | `full_text` | None | Status keyword |
| **LCA** | `lc_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | LC header box neighbor |
| **LCA** | `issue_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **LCA** | `expiry_date` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Date box neighbor |
| **LCA** | `issuing_bank`| TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Bank header box neighbor |
| **LCA** | `beneficiary_name` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Party box neighbor |
| **LCA** | `lc_amount` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | LC amount box neighbor |
| **LCA** | `shipment_reference` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | LC reference box neighbor |
| **LCA** | `trade_reference_number` | TEXT | HYBRID | `full_text` | `raw_blocks` (spatial) | Trade reference box neighbor |
| **LCA** | `country` | TEXT | TEXT | `full_text` | None | Country name lookup |
| **LCA** | `approval_status` | TEXT | TEXT | `full_text` | None | Status keyword |

---

## 4. Fields Intentionally Left TEXT-Only

The following 18 fields remain purely text-based because layout analysis adds unnecessary ambiguity or provides no tangible benefit over regex:
1. `document_category`
2. `fiscal_year`
3. `location_code`
4. `vertical_code`
5. `document_source`
6. `barcode`
7. `currency`
8. `processing_status`
9. `validation_status`
10. `payment_terms`
11. `expense_category`
12. `cost_center`
13. `department`
14. `purpose`
15. `advance_percentage`
16. `manager_approval_status`
17. `reconciliation_status`
18. `approval_status`

---

## 5. Fields Changed to HYBRID

65 fields across all 9 document types now operate under the HYBRID strategy:
- `full_text` regex runs first.
- If text regex yields a confident match ($\ge 0.70$), it is retained.
- If text regex is not found or yields unparseable values, deterministic spatial queries across `raw_blocks` are executed.

---

## 6. Fields Changed to LAYOUT

None are purely LAYOUT-only. In accordance with Section 5 ("Full text remains primary"), all layout-enhanced fields operate under the HYBRID strategy with full text as the primary candidate generator.

---

## 7. Fields Using TABLE

The following 6 fields selectively utilize `table_data` calculations when text and spatial extraction do not find a summary amount:
1. POI `net_amount`
2. POI `tax_amount`
3. POI `invoice_amount`
4. NPO `net_amount`
5. NPO `tax_amount`
6. NPO `invoice_amount`
7. MSI `net_amount`
8. MSI `tax_amount`
9. MSI `invoice_amount`

---

## 8. Exact Files Modified

1. `backend/app/extraction/primitives.py`
   - Added `extract_field_hybrid`, `extract_date_hybrid`, `extract_amount_hybrid`.
2. `backend/app/extraction/type_extractors.py`
   - Updated all per-type extractors to accept optional `raw_blocks` and `table_data`, dispatching to hybrid primitives.
3. `backend/app/extraction/rule_based.py`
   - Updated `RuleBasedExtractor.extract()` to forward `ctx.raw_blocks` and `ctx.table_data`.

---

## 9. Exact Files Added

1. `backend/app/extraction/layout_helpers.py`
   - Deterministic spatial 2D proximity extraction for right-adjacent and below-adjacent OCR blocks.
2. `backend/app/extraction/table_helpers.py`
   - Deterministic summary amount calculations from reconstructed table line items.
3. `backend/tests/test_phase2_rule_enhancements.py`
   - Unit and integration tests for spatial extraction, table extraction, and fallbacks.
4. `PHASE_2_RULE_BASED_EXTRACTION_IMPLEMENTATION_REPORT.md` (this document).

---

## 10. Exact Deterministic Algorithms Introduced

### A. Spatial 2D Neighbor Proximity Query
1. Locate OCR block matching target label via `\b{label}\b`.
2. If block has value trailing separator, return value directly.
3. If block contains only label:
   - **Right neighbor:** $0 \le (min\_x_{val} - max\_x_{lbl}) \le 450\text{px}$, $|cy_{val} - cy_{lbl}| \le \max(18.0, 0.65 \times h_{lbl})$. Sort by horizontal distance.
   - **Below neighbor:** $0 \le (min\_y_{val} - max\_y_{lbl}) \le 85\text{px}$, $|min\_x_{val} - min\_x_{lbl}| \le 60\text{px}$ or $|cx_{val} - cx_{lbl}| \le 100\text{px}$. Sort by vertical distance.
4. Filter out candidates matching any `KNOWN_LABEL`.
5. Normalize value according to field type (`date`, `amount`, `code`, `text`).

### B. Table Line-Item Summary Calculations
1. `net_amount`: $\sum \text{net\_amount}_i$ if all line items have valid numeric net amounts.
2. `invoice_amount`: $\sum \text{gross\_amount}_i$ if all line items have valid gross amounts.
3. `tax_amount`: $\text{total\_gross} - \text{total\_net}$ if $\text{total\_gross} \ge \text{total\_net}$.

---

## 11. Existing OCR Utilities Reused

- `backend/app/ocr/table_reconstruction.py` (`reconstruct_table`, `ReconstructedTable`, `StructuredLineItem`)
- `backend/app/ocr/normalization.py` (`normalize_table_data`, `NormalizedLineItem`)
- `backend/app/ocr/layout.py` bounding-box definitions and coordinate structures.

---

## 12. New Extraction Helpers

- `backend/app/extraction/layout_helpers.py`: `extract_field_spatially()`, `_get_block_bounds()`, `_is_known_label()`, `_normalize_by_type()`
- `backend/app/extraction/table_helpers.py`: `extract_amount_from_table()`

---

## 13. RuleBasedExtractor Changes

- Updated `extract()` method to pass `raw_blocks=ctx.raw_blocks` and `table_data=ctx.table_data` to `extract_common_fields()` and `type_extractor_fn()`.

---

## 14. Type Extractor Changes

- Signatures of all 9 type extractors updated to `extract_*_fields(text, raw_blocks=None, table_data=None)`.
- Replaced direct `extract_by_labels` calls with `extract_field_hybrid`, `extract_date_hybrid`, and `extract_amount_hybrid` for layout/table-eligible fields.

---

## 15. Primitive Changes

- Added `extract_field_hybrid`, `extract_date_hybrid`, and `extract_amount_hybrid` to `backend/app/extraction/primitives.py`.

---

## 16. Table-Data Usage

- Only used for `net_amount`, `tax_amount`, and `invoice_amount` when text extraction does not yield a valid value.
- Reconstructed table operates on page 1 (`raw_blocks[0]`) preserving existing behavior.

---

## 17. Normalized-Data Usage

- Consumed via normalized amount and date formatting in `table_helpers.py` and `primitives.py`.

---

## 18. Fallback Behavior

- If `raw_blocks` is empty/missing, spatial queries immediately return `ExtractedField(value=None, confidence=0.0)` and text extraction result is returned.
- If `table_data` is empty/missing, table calculations return `ExtractedField(value=None, confidence=0.0)` and text extraction result is returned.
- Complete 100% backward compatibility with text-only calls.

---

## 19. Confidence Changes

Deterministic confidence scoring rules:
- Text exact label match: $0.90 - (i \times 0.10)$
- Spatial right-adjacent neighbor match: $0.86 - (i \times 0.05)$
- Spatial below-adjacent neighbor match: $0.80 - (i \times 0.05)$
- Table-calculated line item total: $0.82$
- Table-derived tax difference: $0.80$
- No arbitrary inflation.

---

## 20. Test Suite Executed

- `tests/test_phase2_rule_enhancements.py` (8 new tests)
- `tests/test_extraction_context.py` (9 tests)
- `tests/test_phase6_extraction.py` (27 tests)
- `tests/test_hybrid_llm_extraction.py` (6 tests)
- Full backend regression suite (`pytest -q` across all 20 test modules)

---

## 21. Test Results

- Targeted Phase 2 tests: **50/50 PASSED** in 14.66s.
- Full backend regression suite: **243/243 PASSED** in 291.26s (0:04:51).

---

## 22. Before / After Extraction Evaluation

| Scenario / Document | Before Phase 2 (Text Only) | After Phase 2 (Hybrid Rule-Based) | Outcome |
| :--- | :--- | :--- | :--- |
| **Multi-block split PO Number** (`PO Number` and `PO-2026-9999` in separate blocks) | `value: None`, `confidence: 0.0` | `value: "PO-2026-9999"`, `confidence: 0.86` | **RESOLVED / IMPROVED** |
| **Multi-block split Invoice Number** (`Invoice Number` and `INV-5544` in separate blocks) | `value: None`, `confidence: 0.0` | `value: "INV-5544"`, `confidence: 0.86` | **RESOLVED / IMPROVED** |
| **Table-only Net Amount** (Net amount absent in text summary, present in line items) | `value: None`, `confidence: 0.0` | `value: "1000.00"`, `confidence: 0.82` | **RESOLVED / IMPROVED** |
| **Table-only Tax Amount** (Tax amount absent in text summary, gross/net present in items) | `value: None`, `confidence: 0.0` | `value: "180.00"`, `confidence: 0.80` | **RESOLVED / IMPROVED** |
| **Standard Inline Text Invoice** (Full text with standard colon separators) | `value: "INV-2026-001"`, `confidence: 0.90` | `value: "INV-2026-001"`, `confidence: 0.90` | **UNCHANGED / EXACT** |

---

## 23. Regressions

**ZERO regressions.** All 243 backend test assertions passed.

---

## 24. Known Limitations

- **Multi-page Table Limitation:** Table calculations operate on page 1 (`raw_blocks[0]`) as established in the Phase 0 audit and Phase 1 report.
- **Complex Floating Hand-Drawn Tables:** Hand-drawn or non-standard free-form tables without clear column intervals rely on primary text regex.

---

## 25. Explicit Confirmation

- **NO LLM changes** or prompt redesigns were made.
- **NO RAG changes** were made.
- **NO database changes** or migrations were made.
- **NO OCR subsystem changes** were made.
- **NO reconciliation engine** was implemented.
- **NO Phase 3+ functionality** was implemented.

---

## 26. Recommendation for Phase 3

Proceed to **Phase 3 — LLM Extractor Enhancements & LLMContextBuilder**, where structured document representation, spatial party sections, and table markdown can be compiled into the LLM extraction prompt.
