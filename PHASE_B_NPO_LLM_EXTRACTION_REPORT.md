# PHASE B — NPO LLM EXTRACTION IMPLEMENTATION REPORT

## 1. Executive Summary

Phase B of the EFDI NPO Invoice Extraction project has been completed successfully. This phase operationalizes the canonical semantic nested schema developed in Phase A within the LLM extraction layer. The extractor now extracts non-tabular, tabular, narrative, multi-tax, and multi-line item invoices directly into the target canonical nested hierarchy (`invoice_information`, `seller`, `buyer`, `line_items[]`, `taxes[]`, `totals`, `payment`, `references`) in a format-agnostic manner.

All 6 mandatory core processing requirements (`invoice_information.invoice_number`, `invoice_information.invoice_date`, `invoice_information.currency`, `seller.name`, `buyer.name`, `totals.grand_total`) are explicitly enforced by instructions and prompts, with optional fields strictly retained as `null` when not explicitly present in the document. Zero-or-many semantics for `line_items: []` and `taxes: []` are fully honored, with no default `quantity=1` or `unit_price=net_amount` assumptions. Deterministic value normalization (dates, monetary amounts, percentages, and currencies) occurs transparently without losing verbatim provenance quotes or field-level confidence scores. Backward compatibility is completely preserved through dual canonical and flat key exposure.

All 20 required Phase B test scenarios pass with 100% success rate, along with existing schema, mandatory semantics, rule-based, and reconciliation test suites.

---

## 2. Files Changed

1. **`backend/app/extraction/primitives.py`**
   - Added `normalize_currency(raw_value: str | None) -> str | None` supporting standard currency symbols (`$`, `€`, `£`, `₹`, `¥`, `₩`), abbreviations (`Rs`, `Rs.`, `Rp`), and ISO-4217 alphabetic codes (`USD`, `EUR`, `GBP`, `INR`, `CAD`, etc.).

2. **`backend/app/extraction/field_schemas.py`**
   - Added `convert_flat_npo_to_hierarchical_dict(flat_dict: dict) -> dict` helper function to reliably convert any flat legacy dictionary into the canonical nested hierarchy.

3. **`backend/app/extraction/llm_schema.py`**
   - Added `@model_validator(mode="before") pre_validate` on `LLMFieldItem` to accept raw primitives (`str`, `int`, `float`), `None`, or structured dicts gracefully.
   - Added `normalize_values(self)` method to `NPOExtractionPayload` to deterministically normalize dates (`YYYY-MM-DD`), monetary amounts, percentages, and currencies across `invoice_information`, `totals`, `payment`, `line_items`, and `taxes`.
   - Connected `normalize_values()` to execute automatically in `to_canonical_dict()` and `flatten_to_paths()`.

4. **`backend/app/extraction/llm_context_builder.py`**
   - Updated `build_system_prompt()` to accept `hierarchical: bool = False`.
   - When extracting NPO invoices hierarchically, generates a comprehensive 13-point instruction system prompt specifying canonical nested JSON structure, 6 mandatory core fields, zero-or-many collections, nullable line-item leaves, anti-hallucination rules, verbatim source quotes, and format-agnostic reasoning.

5. **`backend/app/extraction/llm_extractor.py`**
   - Updated `extract()` to detect when extracting `NPO_INVOICE` with hierarchical schema enabled.
   - Dispatched `get_extraction_model(doc_type, hierarchical=True)` returning `NPOExtractionPayload`.
   - Implemented `_populate_npo_results()` to populate canonical dot-paths, collections (`line_items` and `taxes`), root `canonical` dictionary, and legacy flat keys.
   - Implemented `_populate_flat_results()` preserving untouched extraction for legacy/non-NPO document types.
   - Implemented `_enrich_npo_hierarchical()` to enrich rule-based fallbacks with canonical dot-paths, reconstructed table line items, and nested canonical structure.

6. **`backend/tests/test_npo_llm_extraction.py`** [NEW]
   - Created comprehensive test suite implementing all 20 required Phase B test scenarios.

---

## 3. Current → New LLM Extraction Flow

```
[Document Ingestion / Classification: NPO_INVOICE]
                        │
                        ▼
[Context Builder: Normalized OCR text + Reconstructed Table Evidence + Metadata]
                        │
                        ▼
         Is Document Type NPO_INVOICE?
             /                     \
          YES                       NO
           │                         │
           ▼                         ▼
[Hierarchical System Prompt]   [Legacy Flat Prompt]
           │                         │
[NPOExtractionPayload Schema]  [Dynamic Flat Schema]
           │                         │
           ▼                         ▼
  [LLM Structured Output]    [LLM Flat Key Output]
           │                         │
           ▼                         ▼
[NPOExtractionPayload]         [Flat Dictionary]
   - Pre-validation                  │
   - normalize_values()              │
     (dates, amounts, %)             │
           │                         │
           ▼                         ▼
[Populate ExtractionResultData] [Populate Flat Fields]
   ├── Canonical Dot-Paths
   ├── line_items[] (with leaf provenance)
   ├── taxes[] (with leaf provenance)
   ├── root "canonical" dict
   └── Legacy Flat Aliases (for backward compatibility)
                        │
                        ▼
[Validation Engine / Business Rules / Arithmetic Reconciliation]
```

---

## 4. NPO LLM Schema Changes

The LLM extraction schema (`NPOExtractionPayload`) is composed of structured `LLMFieldItem` objects preserving provenance:

- `invoice_information`: `invoice_number`, `invoice_date`, `currency`, `document_type`
- `seller`: `name`, `tax_id`, `address`
- `buyer`: `name`, `tax_id`, `address`
- `line_items[]`: list of `NPOLineItemPayload` (`description`, `quantity`, `uom`, `unit_price`, `net_amount`, `tax_rate`, `tax_amount`, `gross_amount`)
- `taxes[]`: list of `NPOTaxItemPayload` (`tax_type`, `tax_rate`, `taxable_amount`, `tax_amount`)
- `totals`: `subtotal`, `total_tax`, `grand_total`, `discount`, `shipping`, `other_charges`, `rounding`
- `payment`: `payment_terms`, `due_date`, `payment_method`, `bank_account`, `iban`, `swift_bic`, `remittance_reference`
- `references`: `po_number`, `contract_number`, `delivery_note_number`, `order_number`, `other_reference`

Each scalar field utilizes `LLMFieldItem`:
```json
{
  "value": "INV-2026-001",
  "confidence": 0.95,
  "source_quote": "Invoice Number: INV-2026-001",
  "is_found": true
}
```
If not found:
```json
{
  "value": null,
  "confidence": 0.0,
  "source_quote": null,
  "is_found": false
}
```

---

## 5. Prompt Changes

The hierarchical system prompt explicitly instructs the LLM:
1. **Target Structure**: Output valid JSON matching `NPOExtractionPayload`.
2. **Mandatory Processing Core**: Identify `invoice_information.invoice_number`, `invoice_information.invoice_date`, `invoice_information.currency`, `seller.name`, `buyer.name`, and `totals.grand_total`.
3. **Optional Information**: Return `value: null, is_found: false, confidence: 0.0, source_quote: null` when absent.
4. **Zero-or-Many Collections**: Return `line_items: []` and `taxes: []` when not present.
5. **No Artificial Defaults**: Do NOT invent `quantity = 1` or `unit_price = net_amount` unless explicitly stated in the document context.
6. **Provenance Requirement**: Provide verbatim `source_quote` matching document text for every extracted field.
7. **Anti-Hallucination**: Extract strictly supported facts; do not guess bank accounts, tax IDs, or PO numbers.

---

## 6. Context Builder Changes

The context builder (`LLMContextBuilder`) was enhanced:
- Added `hierarchical: bool` parameter to `build_system_prompt()`.
- Reuses existing normalized OCR lines, reading order, reconstructed tables, and document metadata without altering the OCR pipeline.
- Supplies reconstructed OCR table evidence as supporting evidence, not as a restriction on line-item extraction.

---

## 7. Semantic / Format-Agnostic Behavior

Extraction operates on semantic role rather than fixed coordinate anchors or vendor-specific labels:
- **Invoice Number**: Recognizes `Invoice #`, `Bill No.`, `Doc Reference`, `Billing ID`, `Factura Nº`, `Rechnung Nr.`.
- **Seller/Buyer**: Distinguishes vendor from customer by relationship semantics (`From:`, `Billed By:`, header branding vs. `Bill To:`, `Client:`, `Recipient:`).
- **Line Items**: Supports multi-line tabular layouts, single line items, narrative service descriptions ("Software consulting services for Q1 - $15,000.00"), and zero-item fee notices.

---

## 8. Line-Item Handling

- **Zero-or-Many**: An invoice with no line items produces `line_items: []` without triggering extraction errors.
- **Narrative Services**: Service summaries without quantity or unit price extract `description` and `net_amount` while preserving `quantity: null` and `unit_price: null`.
- **Leaf-Level Provenance**: Every attribute of every line item carries its own `confidence`, `source_quote`, and `is_found` metadata.
- **Reconstructed Table Evidence**: Available tables are parsed into semantic line items while maintaining the flexibility to extract line items from non-tabular body text.

---

## 9. Tax Handling

- **Zero-or-Many**: Invoices with zero tax breakdown return `taxes: []`.
- **Multi-Tax Rates**: Handles multiple tax entries (e.g., GST 5% + PST 7%, or VAT 10% + VAT 20%) as distinct items in `taxes[]`.
- **Independent from Line Items**: Line-item level taxes and summary-level taxes are preserved independently.

---

## 10. Null / Missing-Value Handling

- Optional fields evaluate cleanly to `None`/`null`.
- Missing optional seller tax ID, buyer tax ID, subtotal, total tax, payment details, and references do not cause validation failures or extraction aborts.
- Only the 6 mandatory core fields trigger validation errors if absent or unextractable.

---

## 11. Anti-Hallucination Measures

1. **System Prompt Directives**: Strict instructions forbidding inference of standard defaults (no default bank details, no guessing missing digits).
2. **Nullable Schema Structure**: Pydantic schema explicitly permits `None` for all values, removing LLM pressure to generate dummy strings.
3. **Verbatim Quote Tracking**: Extracted fields must be supported by an exact verbatim `source_quote` from the document text.

---

## 12. Confidence and Provenance Handling

- Every field extracted by LLM receives `provenance="llm"` and an estimated confidence score (defaulting to 0.90+ for clear textual evidence, scaled down for ambiguous or low-confidence matches).
- Leaf items in `line_items[]` and `taxes[]` retain their own field-level provenance and quotes.
- Downstream auditing can trace every extracted value directly to its source quote in the raw OCR output.

---

## 13. Hybrid Extraction Interaction

- Deterministic rule-based extraction (`RuleBasedExtractor`) remains active as a fast pre-pass and fallback.
- In `_enrich_npo_hierarchical()`, rule-extracted fields are mapped into canonical dot-paths.
- If reconstructed OCR tables are present, they are mapped into canonical `line_items` with `provenance="table_reconstruction"`.
- LLM extraction operates as the semantic engine, enriching or refining rule-based extractions when enabled.

---

## 14. Test Cases

A dedicated test suite (`backend/tests/test_npo_llm_extraction.py`) was created implementing the 20 required test scenarios:

1. `test_01_standard_tabular_npo_invoice`: Multi-column invoice with header, line items, taxes, totals.
2. `test_02_multiple_line_items`: 3+ items with distinct quantities, UOMs, unit prices, net amounts.
3. `test_03_single_line_item`: Single line item extraction.
4. `test_04_zero_line_items`: Pure document-level totals with `line_items: []`.
5. `test_05_narrative_service_invoice`: Consulting service with `quantity: null` and `unit_price: null`.
6. `test_06_missing_quantity`: Item with description and net amount, but no quantity.
7. `test_07_missing_unit_price`: Item with quantity and total, but no unit price.
8. `test_08_missing_tax_information`: Invoice with no tax breakdown returning `taxes: []`.
9. `test_09_multiple_tax_rates`: Document with two separate VAT rates (e.g. 10% and 20%).
10. `test_10_missing_optional_seller_information`: Missing seller tax ID and address.
11. `test_11_missing_optional_buyer_information`: Missing buyer tax ID and address.
12. `test_12_missing_payment_information`: Missing bank account, IBAN, and payment terms.
13. `test_13_missing_references`: Missing PO number, contract number, and order number.
14. `test_14_different_invoice_terminology`: Parsing "Bill No", "Customer", "Amount Due".
15. `test_15_different_layout_ordering`: Totals at the top, seller info at footer.
16. `test_16_no_hallucinated_values`: Verifying unmentioned fields evaluate strictly to `null`.
17. `test_17_existing_regression_invoice`: Testing against existing standard mock invoice.
18. `test_18_nested_output_structure`: Verifying complete canonical dictionary hierarchy.
19. `test_19_mandatory_core_extraction`: Verifying all 6 mandatory core fields are present and valid.
20. `test_20_confidence_provenance_preservation`: Verifying `source_quote`, `confidence`, and `provenance`.

---

## 15. Test Results

Execution of `pytest backend/tests/test_npo_llm_extraction.py -v`:
- **Total Tests**: 20
- **Passed**: 20 (100%)
- **Failed**: 0
- **Duration**: 0.74s

---

## 16. Regression Results

All existing test suites were executed to verify backward compatibility and zero regression:

1. **Canonical Schema & Mandatory Semantics**:
   `pytest backend/tests/test_npo_canonical_schema.py backend/tests/test_npo_mandatory_semantics.py backend/tests/test_hybrid_llm_extraction.py -v`
   - **Passed**: 33 / 33 (100%)

2. **Phase 2, 3, 5 LLM & Reconciliation Suites**:
   `pytest backend/tests/test_phase5_llm_extraction.py backend/tests/test_phase5_reconciliation.py backend/tests/test_phase2_rule_enhancements.py backend/tests/test_phase3_llm_enhancements.py -v`
   - **Passed**: 29 / 29 (100%)

3. **Phase 6 & 7 Extraction & Validation Suites**:
   - Both test suites completed with 0 regressions.
   - Non-NPO document types (`POI`, etc.) continue using flat extraction schemas without interference.

---

## 17. Backward Compatibility

- **Flat Key Aliases**: `_populate_npo_results()` automatically maps canonical dot-paths back to legacy flat keys (`invoice_number`, `seller_name`, `buyer_name`, `grand_total_amount`, etc.) within `ExtractionResultData.fields`.
- **Legacy Extraction Paths**: Non-NPO extraction models and workflows continue calling `_populate_flat_results()` unmodified.
- **Conversion Utility**: `convert_flat_npo_to_hierarchical_dict()` is available to convert any legacy flat payload into the canonical nested representation.

---

## 18. Known Limitations

1. **Real-world OCR Artifacts**: Poor scan quality, tilted scans, or heavy OCR character recognition errors (e.g., `8` vs `B`) rely on upstream OCR engine accuracy.
2. **Ambiguous Currency Symbols**: Standard symbols like `$` are normalized to `USD`, but in domestic contexts could represent `CAD`, `AUD`, or `NZD` unless context clarifies.
3. **Complex Narrative Multi-Page Text**: Extra-long invoices spanning 5+ pages with dense narrative text require chunked context window handling in future production scale-up.

---

## 19. Remaining Risks

- **LLM Rate Limits / Latency**: Real-world external LLM providers (e.g. Gemini, OpenAI) may introduce variable latency or rate limits during peak invoice processing batches.
- **Prompt Drift**: If external model foundational versions change, prompt alignment should be periodically benchmarked using the 20-scenario test suite.

---

## Final Gate Verification

Phase B is complete. No changes were made to persistence schemas, API endpoints, or the frontend UI. All execution is halted at the Phase B gate pending explicit user approval.
