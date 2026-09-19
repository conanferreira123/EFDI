# Phase A Implementation Report: Backend Canonical Schema & Pydantic Definitions

**Status:** Completed & Verified  
**Date:** 2026-09-14  

---

### 1. Files Changed

| File Path | Nature of Change |
| :--- | :--- |
| `backend/app/extraction/field_schemas.py` | **Updated:** Defined canonical hierarchical schema structures for NPO, schema path descriptors, mandatory/optional/system path categorization, and bidirectional path mapping helpers while preserving existing legacy flat schemas. |
| `backend/app/extraction/llm_schema.py` | **Updated:** Created canonical Pydantic models for NPO (`NPOExtractionPayload`, `NPOLineItemPayload`, `NPOTaxItemPayload`, and section submodels) with strict null/missing field validators, while preserving `build_dynamic_extraction_model()` for non-NPO types. |
| `backend/tests/test_npo_canonical_schema.py` | **New File:** Dedicated unit test suite testing schema definitions, path categorization, bidirectional mapping, Pydantic validation, null-preservation rules, multi-item & multi-tax handling, and dispatch helpers. |

---

### 2. Detailed Summary of Changes Made

1. **Canonical Hierarchical NPO Schema (`field_schemas.py`):**
   - Implemented `HierarchicalFieldDef` and `CanonicalSectionDef` data structures.
   - Defined `NPO_CANONICAL_SCHEMA` containing all 9 canonical sections:
     - `invoice_information` (`invoice_number`, `invoice_date`, `currency`, `document_type`)
     - `seller` (`name`, `tax_id`, `address`)
     - `buyer` (`name`, `tax_id`, `address`)
     - `line_items[]` (array: `description`, `quantity`, `uom`, `unit_price`, `net_amount`, `tax_rate`, `tax_amount`, `gross_amount`)
     - `taxes[]` (array: `tax_type`, `tax_rate`, `taxable_amount`, `tax_amount`)
     - `totals` (`subtotal`, `total_tax`, `grand_total`, `discount`, `shipping`, `other_charges`, `rounding`)
     - `payment` (`payment_terms`, `due_date`, `payment_method`, `bank_account`, `iban`, `swift_bic`, `remittance_reference`)
     - `references` (`po_number`, `contract_number`, `delivery_note_number`, `order_number`, `other_reference`)
     - `metadata` (system: `document_id`, `company_code`, `vendor_code`, `gl_account`, `cost_center`, `profit_center`, `department`, `project_code`, `internal_order`, `processing_status`, `validation_status`, `approval_status`)
   - Defined disjoint categorization path sets:
     - `NPO_MANDATORY_CORE_PATHS` (13 core document paths)
     - `NPO_IMPORTANT_OPTIONAL_PATHS` (16 optional paths)
     - `NPO_SYSTEM_METADATA_PATHS` (12 system metadata paths)
   - Implemented `is_hierarchical_schema(doc_type)` helper.
   - Implemented bidirectional mapping helpers `map_npo_flat_to_canonical()` and `map_npo_canonical_to_flat()` ensuring seamless interop with legacy keys.

2. **Canonical Pydantic Models (`llm_schema.py`):**
   - Enhanced `LLMFieldItem` / `ExtractedValue` with a strict `model_validator` enforcing the core rule:
     - If `value` is `None` or blank whitespace: `value=None`, `confidence=0.0`, `is_found=False`, `source_quote=None`.
     - If `value` is present: `is_found=True`, retaining verbatim `source_quote` and confidence.
   - Defined typed section payload models:
     - `NPOInvoiceInformationPayload`
     - `NPOSellerPayload`
     - `NPOBuyerPayload`
     - `NPOLineItemPayload` (allows `quantity=None`, `unit_price=None` without hallucination)
     - `NPOTaxItemPayload`
     - `NPOTotalsPayload`
     - `NPOPaymentPayload`
     - `NPOReferencesPayload`
   - Defined root `NPOExtractionPayload` with:
     - `to_canonical_dict()`: transforms nested Pydantic instance into the canonical nested dictionary structure.
     - `flatten_to_paths()`: flattens the hierarchy into dot-delimited path keys (`"invoice_information.invoice_number"`, `"line_items.0.net_amount"`, etc.).
     - `flatten_to_legacy_dict()`: projects canonical values to legacy flat keys for backward compatibility.
   - Retained `build_dynamic_extraction_model()` for non-NPO types (`POI`, `IMA`, `MSI`, `JER`, etc.).
   - Implemented `get_extraction_model(document_type, hierarchical=True)` dispatching `NPOExtractionPayload` for NPO and dynamic models for other types.

---

### 3. Requirements Satisfied

- **Schema-required vs. Document-present Separation:** Mandatory schema definitions in `field_schemas.py` do not force artificial defaults on `LLMFieldItem`. Missing fields default to `None` with `confidence=0.0` and `is_found=False`.
- **Format-Agnostic Line-Item Semantics:** `line_items[]` is an array of `NPOLineItemPayload` instances that cleanly supports:
  - Tabular multi-item invoices.
  - Narrative/service invoices with `description` and `net_amount` but `quantity=None` and `unit_price=None`.
  - Zero-line-item invoices (`line_items: []`).
- **Conditional Tax Semantics:** `taxes[]` array natively accepts multiple tax rates or remains empty (`taxes: []`) when no tax breakdown is present.
- **No Hallucination Enforcement:** Strict validator guarantees that unextracted fields are represented as clean `null` rather than fabricated values.
- **Zero Regressions on Existing Types:** All flat schemas and dynamic Pydantic schema generators remain 100% operational for `POI`, `IMA`, `MSI`, `PSI`, `JER`, `BKA`, `DPR`, and `LCA`.

---

### 4. Tests Executed & Results

1. **Phase A Test Suite:** `backend/tests/test_npo_canonical_schema.py`
   - `test_is_hierarchical_schema` **PASSED**
   - `test_npo_canonical_schema_structure` **PASSED**
   - `test_npo_path_categorization_disjoint` **PASSED**
   - `test_npo_mapping_helpers` **PASSED**
   - `test_legacy_full_field_schema_intact` **PASSED**
   - `test_llm_field_item_missing_value_rule` **PASSED**
   - `test_npo_extraction_payload_empty_structure` **PASSED**
   - `test_npo_extraction_payload_with_multi_items_and_taxes` **PASSED**
   - `test_get_extraction_model_dispatch` **PASSED**  
   *Result:* **9 passed in 0.25s (100% pass rate)**

2. **Existing LLM & Extraction Regression Suites:**
   - `backend/tests/test_hybrid_llm_extraction.py` (6 tests) **PASSED**
   - `backend/tests/test_phase5_llm_extraction.py` (6 tests) **PASSED**
   - `backend/tests/test_phase6_extraction.py` (19 tests) **PASSED**  
   *Result:* **31 passed, zero regressions**

---

---

### 7. Semantic Corrections (Mandatory Field Core & Zero-or-Many Semantics)

Following review of the initial implementation, two critical semantic corrections were applied:

1. **Mandatory Field Semantics Refined to Minimally Processable Core:**
   - **Before:** 13 fields were marked as mandatory (`invoice_information.document_type`, `seller.tax_id`, `seller.address`, `buyer.tax_id`, `buyer.address`, `totals.subtotal`, `totals.total_tax`, etc.), and `MANDATORY_FIELDS["NPO"]` contained `vendor_code`.
   - **After:** Only the 6 minimally processable core fields are mandatory:
     - `invoice_information.invoice_number` (`invoice_number`)
     - `invoice_information.invoice_date` (`invoice_date`)
     - `invoice_information.currency` (`currency`)
     - `seller.name` (`seller_name`)
     - `buyer.name` (`buyer_name`)
     - `totals.grand_total` (`grand_total_amount`)
   - `seller.tax_id`, `seller.address`, `buyer.tax_id`, `buyer.address`, `totals.subtotal`, `totals.total_tax`, `taxes.*`, `payment.*`, `references.*`, and `line_items.*` are non-mandatory and remain `null` when missing. Missing optional information does NOT fail mandatory field validation.

2. **`line_items[]` & `taxes[]` Zero-or-Many Collection Semantics:**
   - `line_items: []` is valid (e.g., narrative service invoices, global charges, non-tabular invoices) and produces zero validation errors.
   - Line-item leaf fields (`description`, `quantity`, `uom`, `unit_price`, `net_amount`, `tax_rate`, `tax_amount`, `gross_amount`) are nullable. No synthetic inferences (`quantity=1` or `unit_price=net_amount`) are permitted unless explicitly stated in the document.
   - `taxes: []` is valid. Absence of explicit tax breakdown does not invalidate the invoice.

3. **Arithmetic Reconciliation Architecture (Document-Level vs. Line-Item Separation):**
   - **Document-Level Reconciliation is Independent of `line_items[]`:**
     - An empty `line_items = []` collection makes *only* line-item-level reconciliation unavailable; it does NOT automatically prevent document-level reconciliation.
     - When document totals (`subtotal`, `total_tax`, `grand_total`, plus any applicable discounts, shipping, other charges, or rounding) are available, document-level reconciliation executes regardless of whether `line_items` is empty:
       - If `subtotal + total_tax == grand_total` balances (within tolerance), status is `VALID` (`is_valid=True`), producing 0 validation issues.
       - If document totals fail to balance, status is `MISMATCH` (`is_valid=False`), producing a review `WARNING`.
     - If required document-level values are missing or null (e.g., `subtotal` or `total_tax` is unavailable), document-level reconciliation is classified as `NOT_CHECKABLE` (`is_valid=True`), producing 0 validation issues ("missing information is not invalid information").
   - **Line-Item-Level Reconciliation:**
     - When `line_items = []` or any line item lacks explicit `net_amount`, line-item-level reconciliation (`sum(item.net_amount) == subtotal`) is classified as `NOT_CHECKABLE` (`is_valid=True`).
     - Line items are skipped cleanly without impairing the validity of document totals.

4. **Test Verification:**
   - Added and enhanced `backend/tests/test_npo_mandatory_semantics.py` with 18 comprehensive test cases explicitly covering:
     - `line_items = []` with valid document totals (`5000 + 500 == 5500`) -> document-level reconciliation `VALID` (`test_10a`)
     - `line_items = []` with mismatched document totals (`5000 + 500 != 6000`) -> document-level reconciliation `MISMATCH` with `WARNING` (`test_10b`)
     - Insufficient document-level totals -> document-level reconciliation `NOT_CHECKABLE` (`test_10c`)
     - Document totals with discounts, shipping, charges, and rounding -> `VALID` (`test_10d`)
   - All 88 unit and regression tests pass with zero regressions.


