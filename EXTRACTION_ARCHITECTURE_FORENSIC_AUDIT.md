# EFDI Extraction Architecture Forensic Audit Report

**Date:** September 5, 2026  
**Auditor:** Antigravity (Advanced Agentic Assistant)  
**Project Root:** `C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI`  
**Status:** Complete Forensic Audit (Audit-Only — No Code/Schema/Configuration Modifications Performed)

---

## 1. Executive Summary

A forensic architecture audit was conducted on the data extraction subsystem of the EFDI (Enterprise Financial Document Intelligence) application. 

### Key Audit Findings:
1. **Current Extraction Contract:** The extraction subsystem operates on a strictly **text-only** input contract: `ExtractionEngine.extract(text: str, document_type: str) -> ExtractionResultData`. It receives `ocr_results.full_text` and the document's classified `document_type`.
2. **Current `raw_blocks` Status:** `raw_blocks` are produced upstream during OCR execution by `OCRService.run_ocr` and persisted as `JSONB` in the PostgreSQL table `ocr_results`. However, `raw_blocks` are **never passed downstream** to `ExtractionService` or `ExtractionEngine`.
3. **Existing Upstream Layout & Table Processing:** The OCR layer already contains downstream spatial layout modules (`app.ocr.layout.order_blocks_spatially` and `app.ocr.table_reconstruction.reconstruct_table`). These transform `raw_blocks` into spatial reading orders and structured line items for OCR validation/quality scoring, but their structured outputs are not routed to `ExtractionService`.
4. **Current Extraction Implementation:** The active rule-based extraction engine (`RuleBasedExtractor`) uses 1D regular expressions, linear label-boundary lookups (`_VALUE_CAPTURE`), and regex normalizers (`normalize_date`, `normalize_amount`). It operates on 9 financial document types (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA) plus common header fields.
5. **Architectural Gap & Potential of `raw_blocks`:** The 1D text extraction model struggles with multi-column alignment (e.g. side-by-side Buyer vs. Seller party headers), tabular line-item association, summary/totals vs. line-item amount collisions, and multi-line descriptions. Providing structural/bounding-box information (`raw_blocks` or intermediate table/layout structures) directly addresses these 2D spatial ambiguities.
6. **Minimum Architectural Change:** Enabling `raw_blocks` in extraction requires **zero database schema changes** and **zero OCR changes**. The minimum change is updating `ExtractionEngine.extract(text: str, document_type: str, raw_blocks: list[dict] | None = None)` and passing `ocr_result.raw_blocks` from `ExtractionService.extract()`.

---

## 2. Current Extraction Architecture

The extraction subsystem is organized into distinct layers conforming to EFDI's Clean Architecture standards:

```
FastAPI Router (/api/v1/extraction)
           │
           ▼
   ExtractionService
           │
           ├─► OCRResultRepository (fetches latest OCRResult)
           ├─► ClassificationResultRepository (fetches latest ClassificationResult)
           │
           ▼
ExtractionEngineFactory (get_extraction_engine)
           │
           ├─► RuleBasedExtractor (default engine)
           │         ├─► TypeExtractors (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA)
           │         ├─► CommonFieldExtractor
           │         └─► Primitives (extract_by_labels, extract_date_field, extract_amount_field)
           │
           ├─► LLMBasedExtractor (llm_based engine)
           │         ├─► Dynamic Pydantic Schemas (LLMFieldItem)
           │         └─► OpenAI-compatible Structured Outputs JSON Schema
           │
           └─► RAGDiagnosticService (post-extraction reconciliation for arithmetic/confidence triggers)
           │
           ▼
ExtractionResultRepository (persists ExtractionResult in extraction_results table)
           │
           ▼
DocumentRepository (advances Document.status to EXTRACTED)
```

### Component Breakdown:
- **Router (`backend/app/routers/extraction.py`)**: Exposes REST endpoints:
  - `POST /api/v1/extraction/documents/{id}/extract` (triggers extraction)
  - `GET /api/v1/extraction/documents/{id}/result` (retrieves latest result)
  - `GET /api/v1/extraction/documents/{id}/results` (retrieves version history)
  - `PATCH /api/v1/extraction/documents/{id}/fields/{field_key}` (manual human corrections)
  - `GET /api/v1/extraction/documents/{id}/export` (JSON, CSV, Excel serializers)
- **Service Layer (`backend/app/services/extraction_service.py`)**:
  - Validates prerequisites (`OCRResult` and `ClassificationResult` must exist).
  - Retrieves `ocr_result.full_text` and `classification_result.predicted_type`.
  - Instantiates the engine via factory and executes `engine.extract(text, document_type)`.
  - Optionally runs `RAGDiagnosticService.diagnose_and_refine()` for LLM engines.
  - Formats the field payload and persists `ExtractionResult`.
  - Updates `Document.status` to `EXTRACTED`.
- **Engine Layer (`backend/app/extraction/base.py`, `rule_based.py`, `llm_extractor.py`)**:
  - `ExtractionEngine`: Abstract base class declaring `extract(text: str, document_type: str) -> ExtractionResultData`.
  - `RuleBasedExtractor`: Concrete rule-based engine.
  - `LLMBasedExtractor`: Concrete LLM structured output engine with fallback to `RuleBasedExtractor`.
- **Factory (`backend/app/extraction/factory.py`)**: Singleton registry supporting `"rule_based"`, `"llm_based"`, and `"llm_rag"`.
- **Field Definitions (`backend/app/extraction/field_schemas.py`)**: Static declarative registry defining 15 `COMMON_FIELDS` and per-type fields for all 9 document types.
- **Extraction Primitives (`backend/app/extraction/primitives.py`)**: Core label matching, stop-boundary detection (`KNOWN_LABELS`), date parser/normalizer, and amount normalizer.
- **Persistence Layer (`backend/app/models/extraction_result.py`, `app/repositories/extraction_result_repository.py`)**: Append-only PostgreSQL persistence using `JSONB` for `fields`.

---

## 3. Actual End-to-End Data Flow

The concrete end-to-end data flow verified from source code is:

```
1. Document Upload
   POST /api/v1/documents/upload ──► Document (status: PENDING)

2. OCR Processing
   POST /api/v1/ocr/documents/{id}/run
     │
     ├─► OCRService.run_ocr()
     │     ├─► AdaptivePreprocessor.process()
     │     ├─► Engine.extract_text_blocks() ──► raw_extracted_blocks (OCRTextBlock)
     │     ├─► Appends to raw_blocks JSON dict: [ {page_number, page_width, page_height, blocks:[{text, confidence, bounding_box}]} ]
     │     ├─► order_blocks_spatially(raw_extracted_blocks) ──► ordered_blocks
     │     ├─► OCRResultData.full_text = "\n\n".join(pages.full_text)
     │     ├─► reconstruct_table(raw_blocks) ──► table_obj (used for quality scoring)
     │     └─► OCRResultRepository.create(...)
     │           └── Persists to table `ocr_results` (including full_text & raw_blocks JSONB)
     └─► Document.status = OCR_COMPLETED

3. Classification
   POST /api/v1/classification/documents/{id}/classify
     │
     ├─► ClassificationService.classify()
     │     ├─► Reads ocr_result.full_text
     │     ├─► ClassificationEngine.classify(full_text) ──► ClassificationResultData
     │     ├─► ClassificationResultRepository.create(...)
     │     └─► Document.document_type = predicted_type
     └─► Document.status = CLASSIFIED

4. Field Extraction
   POST /api/v1/extraction/documents/{id}/extract
     │
     ├─► ExtractionService.extract(document, engine_name)
     │     ├─► OCRResultRepository.get_latest_for_document(document.id) ──► ocr_result
     │     ├─► ClassificationResultRepository.get_latest_for_document(document.id) ──► classification_result
     │     ├─► document_type = classification_result.predicted_type
     │     ├─► engine = get_extraction_engine(engine_name)
     │     ├─► result_data = engine.extract(ocr_result.full_text, document_type)  <── [TEXT-ONLY CONTRACT]
     │     │     ├─► RuleBasedExtractor:
     │     │     │     ├─► extract_common_fields(text)
     │     │     │     └─► TYPE_EXTRACTORS[document_type](text)
     │     │     └─► Primitives: extract_by_labels(), extract_date_field(), extract_amount_field()
     │     ├─► ExtractionResultRepository.create(document_id, document_type, engine_name, fields, ...)
     │     │     └── Persists to table `extraction_results`
     │     └─► DocumentRepository.update_status(document, "EXTRACTED")
     └─► ExtractionResultResponse

5. Validation (Downstream)
   POST /api/v1/validation/documents/{id}/validate
     │
     ├─► ValidationService.validate()
     │     ├─► ExtractionResultRepository.get_latest_for_document(document.id)
     │     ├─► run_validation(db, document, extraction_result.document_type, extraction_result.fields)
     │     └─► ValidationResultRepository.create(...)
     └─► If valid: Document.status = VALIDATED
```

---

## 4. Current Extraction Input Contract

### Exact Inputs Received by Extraction Components:

| Input Item | Currently Received by Extraction? | Originating Component | Storage Location | Retrieval Point | Consuming Extraction Component |
|---|---|---|---|---|---|
| `full_text` | **YES** | `OCRService.run_ocr` | `ocr_results.full_text` | `ExtractionService.extract()` | `ExtractionEngine.extract()`, `primitives.py` |
| `document_type` | **YES** | `ClassificationService.classify` | `classification_results.predicted_type` | `ExtractionService.extract()` | `ExtractionEngine.extract()`, `RuleBasedExtractor` |
| `raw_blocks` | **NO** | `OCRService.run_ocr` | `ocr_results.raw_blocks` (`JSONB`) | *Not retrieved by ExtractionService* | *None* |
| `classification result` (full object) | **NO** (only `predicted_type` string) | `ClassificationService` | `classification_results` table | `ExtractionService.extract()` | Unused beyond string extraction |
| `OCR confidence` | **NO** (at extraction time) | `OCRService` | `ocr_results.average_confidence` | *Not passed to engine* | Injected later into schema |
| `page information` (count / dims) | **NO** (only in RAG diagnostic for LLMs) | `OCRService` | `ocr_results.page_count` | `ExtractionService` (for RAG) | `RAGDiagnosticService` |
| `table information` | **NO** | `OCRService` | Memory-only in OCRService | *Not persisted / Not passed* | *None* |
| `reconstructed tables` | **NO** | `app.ocr.table_reconstruction` | Memory-only in OCRService | *Not persisted / Not passed* | *None* |
| `normalized OCR output` | **NO** | `app.ocr.normalization` | Memory-only in OCRService | *Not persisted / Not passed* | *None* |
| `document metadata` | **NO** (only `document.id`) | Upload payload / DB | `documents` table | `ExtractionService.extract()` | Router access control |

---

## 5. `raw_blocks` Architecture

### 1. Creation Point:
`raw_blocks` is created inside `OCRService.run_ocr` (`backend/app/services/ocr_service.py`, lines 91–111):
```python
raw_blocks = []
for page_number, page_image in enumerate(preprocessed_pages, start=1):
    raw_extracted_blocks = engine.extract_text_blocks(page_image)
    page_h, page_w = page_image.shape[:2]
    raw_blocks.append({
        "page_number": page_number,
        "page_width": page_w,
        "page_height": page_h,
        "blocks": [
            {
                "text": block.text,
                "confidence": block.confidence,
                "bounding_box": block.bounding_box,
            }
            for block in raw_extracted_blocks
        ],
    })
```

### 2. OCR Engine Block Generation:
- Each engine (`EasyOCREngine`, `PaddleOCREngine`) implements `extract_text_blocks(image: np.ndarray) -> list[OCRTextBlock]`.
- Each `OCRTextBlock` (`backend/app/ocr/base.py`) has:
  - `text: str`
  - `confidence: float`
  - `bounding_box: list[list[float]]` (quadrilateral polygon: `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`)

### 3. Exact Structure of `raw_blocks`:
```json
[
  {
    "page_number": 1,
    "page_width": 1240.0,
    "page_height": 1754.0,
    "blocks": [
      {
        "text": "TAX INVOICE",
        "confidence": 0.985,
        "bounding_box": [[450.0, 50.0], [790.0, 50.0], [790.0, 95.0], [450.0, 95.0]]
      },
      {
        "text": "Invoice Number: INV-2026-001",
        "confidence": 0.942,
        "bounding_box": [[100.0, 120.0], [380.0, 120.0], [380.0, 145.0], [100.0, 145.0]]
      }
    ]
  }
]
```

### 4. Storage and Persistence:
- Persisted in PostgreSQL table `ocr_results`, column `raw_blocks` typed as `JSONB`, non-nullable, defaulting to `[]`.
- Model: `OCRResult` in `backend/app/models/ocr_result.py`.

### 5. Downstream Availability:
- `raw_blocks` is fully persisted and can be loaded anytime via `OCRResultRepository.get_latest_for_document(document_id).raw_blocks`.
- It is currently **not** passed anywhere downstream outside the OCR validation/quality service.

---

## 6. Existing OCR Layout & Table Processing

The repository already contains two sophisticated structural processing modules in `backend/app/ocr/`:

### A. Spatial Layout Analysis (`backend/app/ocr/layout.py`)
- **Function:** `order_blocks_spatially(blocks: list[OCRTextBlock], page_width, page_height) -> list[OCRTextBlock]`
- **Capabilities:**
  1. Segments blocks into 3 vertical bands:
     - **Top Metadata** (Invoice No, Date, Header)
     - **Party Information** (Two-column layout: Seller column on Left `cx < mid_x`, Buyer/Client column on Right `cx >= mid_x`)
     - **Body & Table Section** (Line items, summaries, footers)
  2. Resolves multi-column line interleaving before generating `full_text`.

### B. Table Reconstruction Engine (`backend/app/ocr/table_reconstruction.py`)
- **Class / Function:** `TableReconstructor`, `reconstruct_table(blocks, page_width, page_height) -> ReconstructedTable`
- **Capabilities:**
  1. **Header Detection:** Detects column headers using keyword lexicon (`item_number`, `description`, `quantity`, `unit`, `unit_price`, `net_amount`, `vat_rate`, `gross_amount`).
  2. **Column Interval Derivation:** Computes `x_min` and `x_max` horizontal boundaries for each column.
  3. **Table Region Bounding:** Finds table start `header_bottom_y` and table end (via `SUMMARY_KEYWORDS` such as `TOTAL`, `SUBTOTAL`, `GRAND TOTAL`).
  4. **Row Line Clustering:** Groups body blocks into horizontal row bands using a vertical tolerance window (`y_tolerance = 16.0px`).
  5. **Multiline Description Merging:** Groups multiline wrapped item descriptions into their parent line item.
  6. **Data Output:** Produces `ReconstructedTable` containing `StructuredLineItem` objects (`item_number`, `description`, `quantity`, `unit_price`, `net_amount`, `gross_amount`, `raw_blocks`).

### Answer to Question:
> *"Is there already an intermediate representation that extraction could use instead of directly processing raw OCR blocks?"*

**YES (FACT).** `backend/app/ocr/table_reconstruction.py` already defines:
- `ReconstructedTable`
- `StructuredLineItem`
- `TableReconstructor.reconstruct()`

And `backend/app/ocr/normalization.py` provides:
- `normalize_table_data(table_dict)`

Extraction can directly consume `ReconstructedTable` and `StructuredLineItem` objects for tabular and line-item extraction without having to re-implement geometric table parsing from scratch.

---

## 7. Current Extraction Rules Inventory

The rule-based extraction system (`app.extraction.rule_based`, `app.extraction.type_extractors`, `app.extraction.primitives`) operates as follows:

### Common Fields (All 9 Document Types):
| Field Key | Field Label | Type | Extraction Rule / Method | Labels Searched | Normalization / Validation |
|---|---|---|---|---|---|
| `document_id` | Document ID | code | `extract_by_labels` | `"Document ID"`, `"Doc ID"`, `"DOCID"` | Length cap (80 chars) |
| `document_category` | Document Category | code | `extract_by_labels` | `"Document Category"` | Length cap |
| `company_code` | Company Code | code | `extract_by_labels` | `"Company Code"`, `"COCODE"`, `"CO CODE"` | Length cap |
| `company_name` | Company Name | text | `extract_by_labels` | `"Company Name"` | Length cap |
| `fiscal_year` | Fiscal Year | code | `extract_by_labels` | `"Fiscal Year"`, `"FY"` | Length cap |
| `location_code` | Location Code | code | `extract_by_labels` | `"Location Code"`, `"LOC CODE"` | Length cap |
| `vertical_code` | Vertical Code | code | `extract_by_labels` | `"Vertical Code"` | Length cap |
| `document_source` | Document Source | text | `extract_by_labels` | `"Document Source"`, `"Doc Source"` | Length cap |
| `barcode` | Barcode | code | `extract_by_labels` | `"Barcode"`, `"Bar Code"` | Length cap |
| `currency` | Currency | code | `extract_by_labels` | `"Currency"` | Length cap |
| `document_date` | Document Date | date | `extract_date_field` | `"Document Date"`, `"Doc Date"` | `normalize_date` -> `YYYY-MM-DD` |
| `processing_status`| Processing Status| text | `extract_by_labels` | `"Processing Status"` | Length cap |
| `validation_status`| Validation Status| text | `extract_by_labels` | `"Validation Status"` | Length cap |

### Document Type-Specific Extraction Rules:

#### 1. POI (Purchase Order Invoice — AP)
- `vendor_code`: `extract_by_labels` (`["Vendor Code"]`)
- `vendor_name`: `extract_by_labels` (`["Vendor Name", "Vendor"]`)
- `po_number`: `extract_by_labels` (`["PO Number", "Purchase Order Number", "PO No"]`)
- `grn_number`: `extract_by_labels` (`["GRN Number", "GRN No", "GRN"]`)
- `srn_number`: `extract_by_labels` (`["SRN Number", "SRN No", "SRN"]`)
- `invoice_number`: `extract_by_labels` (`["Invoice Number", "Invoice No"]`)
- `invoice_date`: `extract_date_field` (`["Invoice Date"]`)
- `invoice_amount`: `extract_amount_field` (`["Invoice Amount", "Total Amount"]`)
- `tax_amount`: `extract_amount_field` (`["Tax Amount", "GST Amount", "Tax"]`)
- `net_amount`: `extract_amount_field` (`["Net Amount"]`)
- `payment_terms`: `extract_by_labels` (`["Payment Terms"]`)

#### 2. NPO (Non-PO Invoice — AP)
- `vendor_code`, `vendor_name`, `invoice_number`, `invoice_date`, `tax_amount`, `net_amount`: Same primitives.
- `invoice_amount`: `extract_amount_field` (`["Invoice Amount", "Amount Due", "Total Amount"]`)
- `expense_category`: `extract_by_labels` (`["Expense Category"]`)
- `cost_center`: `extract_by_labels` (`["Cost Center", "Cost Centre"]`)
- `department`: `extract_by_labels` (`["Department"]`)

#### 3. DPR (Down Payment Request — AP)
- `request_number`: `extract_by_labels` (`["Request Number", "DPR Number", "Request No"]`)
- `request_date`: `extract_date_field` (`["Request Date"]`)
- `vendor_code`, `vendor_name`, `po_number`: Same primitives.
- `requested_amount`: `extract_amount_field` (`["Requested Amount"]`)
- `advance_percentage`: `extract_by_labels` (`["Advance Percentage", "Advance %"]`)
- `purpose`: `extract_by_labels` (`["Purpose"]`)
- `approval_status`: `extract_by_labels` (`["Approval Status"]`)

#### 4. IMA (Inter-Company Travel / Expense Claim — AP)
- `employee_id`: `extract_by_labels` (`["Employee ID", "Employee Code"]`)
- `employee_name`: `extract_by_labels` (`["Employee Name", "Employee"]`)
- `claim_number`: `extract_by_labels` (`["Claim Number", "Claim No"]`)
- `claim_date`, `travel_start_date`, `travel_end_date`: `extract_date_field`
- `expense_category`: `extract_by_labels` (`["Expense Category"]`)
- `claim_amount`: `extract_amount_field` (`["Claim Amount", "Reimbursement Amount"]`)
- `approved_amount`: `extract_amount_field` (`["Approved Amount"]`)
- `manager_approval_status`: `extract_by_labels` (`["Manager Approval Status", "Approval Status"]`)

#### 5. MSI (Manual / Sales Invoice — R2R)
- `customer_code`: `extract_by_labels` (`["Customer Code"]`)
- `customer_name`: `extract_by_labels` (`["Customer Name", "Customer", "Bill To"]`)
- `sales_invoice_number`: `extract_by_labels` (`["Sales Invoice Number", "MSI Invoice Number", "Invoice Number", "Invoice #", "Invoice"]`)
- `sales_invoice_date`, `due_date`: `extract_date_field`
- `invoice_amount`: `extract_amount_field` (`["Invoice Amount", "MSI Invoice Amount", "Total"]`)
- `tax_amount`, `net_amount` (`"Net Amount"`, `"Subtotal"`), `payment_terms`

#### 6. PSI (Payment / Pay-In Slip — R2R)
- `pis_number`: `extract_by_labels` (`["PIS Number", "Pay In Slip Number"]`)
- `pis_date`, `deposit_date`: `extract_date_field`
- `customer_code`, `customer_name`, `bank_name`, `deposit_reference_number`, `reconciliation_status`
- `deposit_amount`: `extract_amount_field` (`["Deposit Amount", "PIS Deposit Amount"]`)

#### 7. JER (Journal Entry Request — R2R)
- `journal_entry_number`: `extract_by_labels` (`["Journal Entry Number", "JE Number", "JE No"]`)
- `posting_date`: `extract_date_field`
- `gl_account_code`, `gl_account_description`, `cost_center`, `profit_center`, `reference_number`, `approval_status`
- `debit_amount`: `extract_amount_field` (`["Debit Amount", "Debit"]`)
- `credit_amount`: `extract_amount_field` (`["Credit Amount", "Credit"]`)

#### 8. BKA (Bank Advice — R2R)
- `advice_number`, `bank_name`, `account_number`, `transaction_reference`, `transaction_type`, `reconciliation_status`
- `advice_date`, `value_date`: `extract_date_field`
- `transaction_amount`: `extract_amount_field` (`["Transaction Amount", "Advice Amount"]`)

#### 9. LCA (Letter of Credit Application — R2R)
- `lc_number`, `issuing_bank`, `beneficiary_name`, `shipment_reference`, `trade_reference_number`, `country`, `approval_status`
- `issue_date`, `expiry_date`: `extract_date_field`
- `lc_amount`: `extract_amount_field` (`["LC Amount"]`)

### Execution Pipeline for an Individual Field:
```
Field Declaration (e.g. invoice_date)
  │
  ▼
Rule Selection: extract_date_field(text, ["Invoice Date"])
  │
  ▼
Label Search: Iterate labels in priority order with _VALUE_CAPTURE regex
  │
  ▼
Candidate Extraction: Non-greedy text capture stopping at 2+ spaces, \n, or KNOWN_LABELS boundary
  │
  ▼
Normalization: normalize_date(candidate) -> parses 16 date formats into "YYYY-MM-DD"
  │
  ▼
Confidence Assignment: Base confidence (0.9 - 0.1 * label_idx), reduced if unparseable or over-length
  │
  ▼
Output: ExtractedField(value="2026-06-15", confidence=0.9, matched_text="Invoice Date: 15-06-2026")
```

---

## 8. Current Extraction Weaknesses Analysis

| Problem / Failure Mode | Could `raw_blocks` help? | Why? |
|---|---|---|
| **Multi-Column Party Confusion (Seller vs. Buyer)** | **Yes** | In 1D text, "Sold By" and "Bill To" blocks on the same horizontal band get merged or interleaved. 2D bounding boxes separate left column (Seller) from right column (Buyer). |
| **Line-Item Table Extraction** | **Yes** | 1D text cannot associate line-item descriptions with their unit price and quantity across columns. 2D column intervals and row clustering reconstruct table grids. |
| **Totals vs. Line-Item Amount Collision** | **Yes** | A label like "Total" or bare numbers often match line-item totals instead of the summary total at the bottom of the page. Bounding-box Y-coordinates identify summary sections (bottom 25%). |
| **Tax vs. Net vs. Gross Ambiguity** | **Yes** | Tax breakout tables (CGST/SGST/IGST) in 2D columns are impossible to map sequentially in 1D text. |
| **Multi-line Address & Description Values** | **Yes** | 1D regex stops at newlines. 2D spatial clustering identifies wrapped continuation lines directly beneath the anchor block. |
| **Nearby Unrelated Tokens Captures** | **Yes** | When spaces between columns are small, 1D regex overcaptures adjacent columns. Bounding boxes enforce horizontal width limits. |
| **Duplicate Labels Across Document Bands** | **Yes** | Header date vs. line item date vs. footer remittance date can be disambiguated by page coordinate regions (Header band: top 15%, Summary band: bottom 20%). |
| **Ambiguous Labels (e.g. "Total" vs "Subtotal")** | **Partially** | Text boundaries handle exact word tokens, but spatial position confirms whether it belongs to the line items or summary box. |
| **Multiple Dates (Invoice Date vs PO Date vs Due Date)** | **Partially** | Spatial proximity between the specific label block and candidate date block clarifies association over sequential string distance. |
| **Poor OCR Engine Transcription Errors / Typos** | **No** | Requires fuzzy matching, spell correction, or character normalization, not spatial coordinates. |
| **Semantic Terminology Inconsistencies** | **No** | If a document uses "Remittance Voucher" instead of "Pay-in Slip", spatial layout does not resolve the semantic meaning without vocabulary mapping or LLM assistance. |

---

## 9. Potential Capabilities of `raw_blocks` for Extraction

| Extraction Capability | Current Status | Feasibility with `raw_blocks` | Implementation Path |
|---|---|---|---|
| **Label / Value Proximity Association** | Not supported (1D string search only) | **High** | Search for nearest text block within horizontal right-ray `[x1, y0, x_page, y1]` or vertical below-ray `[x0, y1, x1, y_page]`. |
| **Multi-Column Column Separation** | Partially supported in OCR layout | **High** | Separate left column (`x < 0.5 * W`) from right column (`x >= 0.5 * W`). |
| **Header vs Body vs Footer Partitioning** | Partially supported in OCR layout | **High** | Partition page by relative Y-coordinates (`Y < 0.15` header, `Y > 0.80` summary). |
| **Tabular Line-Item Extraction** | Reconstructed in OCR layer, unused in extraction | **High** | Pass `ReconstructedTable` directly to extract structured items. |
| **Multi-line Field Merging** | Implemented in `TableReconstructor` for table lines only | **High** | Group vertically adjacent blocks with matching left alignment `abs(b1.x0 - b2.x0) < delta`. |
| **Duplicate Label Disambiguation** | Not supported | **High** | Disambiguate by relative bounding-box region (e.g. invoice header vs line table vs payment slip footer). |

---

## 10. `extraction_results` Persistence Architecture

The persistence model is implemented in `backend/app/models/extraction_result.py` and `backend/app/repositories/extraction_result_repository.py`:

### Table: `extraction_results`
```sql
CREATE TABLE extraction_results (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_type VARCHAR(30) NOT NULL,
    engine_name VARCHAR(30) NOT NULL,
    fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    overall_confidence FLOAT NOT NULL DEFAULT 0.0,
    fields_found_count INTEGER NOT NULL DEFAULT 0,
    fields_total_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_extraction_results_document_id ON extraction_results(document_id);
```

### JSON Structure of `fields`:
```json
{
  "invoice_number": {
    "value": "INV-2026-001",
    "confidence": 0.9,
    "matched_text": "Invoice Number: INV-2026-001",
    "is_found": true,
    "manually_entered": false
  },
  "invoice_date": {
    "value": "2026-06-15",
    "confidence": 0.9,
    "matched_text": "Invoice Date: 15-06-2026",
    "is_found": true,
    "manually_entered": false
  },
  "srn_number": {
    "value": null,
    "confidence": 0.0,
    "matched_text": null,
    "is_found": false,
    "manually_entered": false
  }
}
```

### Ownership & Relationship Model:
- **Append-Only History:** Re-extracting a document creates a new `ExtractionResult` record rather than overwriting.
- **Workflow State:** `ExtractionService.extract()` transitions `Document.status` to `EXTRACTED`.
- **Validation Linkage:** Downstream `ValidationService.validate()` queries `ExtractionResultRepository.get_latest_for_document(document_id)` and validates `extraction_result.fields`. If valid, `Document.status` advances to `VALIDATED`.
- **Manual Correction Tracking:** `PATCH /extraction/documents/{id}/fields/{field_key}` updates `fields[field_key].manually_entered = true` and `confidence = 1.0`, simultaneously recording a `TrainingExample` in `training_examples`.

---

## 11. Extraction Test Coverage Analysis

### Test Files Inspected:
1. `backend/tests/test_phase6_extraction.py` (22 unit & integration tests)
2. `backend/tests/test_hybrid_llm_extraction.py` (5 unit & integration tests)

### Coverage Breakdown:
- **Document Types Covered:** All 9 document types (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA) and `UNKNOWN` are covered for field schemas and rule extraction.
- **OCR Input Format in Tests:**
  - Tests inject synthetic plain text strings (e.g. `REALISTIC_POI_TEXT`, `REALISTIC_BKA_TEXT`).
  - `_inject_ocr_text()` passes `raw_blocks=[]`.
- **Gaps Identified:**
  - **Zero tests** currently supply or test real `raw_blocks` in extraction.
  - **Zero tests** evaluate multi-column coordinate layouts or table reconstruction during extraction.
  - **Zero tests** evaluate real multi-page OCR bounding box inputs in extraction.
  - Tests only verify 1D regex parsing on pre-formatted text lines.

---

## 12. Minimum Architectural Change for `full_text + raw_blocks`

To enable extraction to consume `raw_blocks` alongside `full_text`, the exact minimum change required is:

### 1. Interface Update (`backend/app/extraction/base.py`)
```python
class ExtractionEngine(ABC):
    @abstractmethod
    def extract(
        self,
        text: str,
        document_type: str,
        raw_blocks: list[dict] | None = None,
    ) -> ExtractionResultData:
        raise NotImplementedError
```

### 2. Service Layer Update (`backend/app/services/extraction_service.py`)
In `ExtractionService.extract()` (line 54):
```python
# Pass ocr_result.raw_blocks to the engine
result_data = engine.extract(
    ocr_result.full_text,
    document_type,
    raw_blocks=ocr_result.raw_blocks,
)
```

### 3. Engine Dispatch Updates
- `RuleBasedExtractor.extract(self, text: str, document_type: str, raw_blocks: list[dict] | None = None)` accepts the parameter (defaulting to `None` for backward compatibility).
- `LLMBasedExtractor.extract(...)` accepts `raw_blocks` as optional context.

### Required vs. Optional Changes Summary:
- **Required:**
  - Update `ExtractionEngine.extract()` signature.
  - Update `ExtractionService.extract()` to pass `ocr_result.raw_blocks`.
  - Update existing test stubs/mocks to accept the optional parameter.
- **Not Required (Zero Changes Needed):**
  - **Database schema:** `ocr_results.raw_blocks` is already `JSONB` in the database.
  - **OCR engines:** OCR already produces and stores `raw_blocks`.
  - **Classification subsystem:** Classification remains 100% untouched (`full_text` only).
  - **API endpoints:** REST request/response contracts remain unchanged.

---

## 13. Critical Evaluation & Risks of `raw_blocks` in Extraction

| Advantage | Disadvantage / Risk | Mitigation Strategy |
|---|---|---|
| **2D Spatial Disambiguation:** Resolves side-by-side columns (Seller vs Buyer). | **OCR Bounding-Box Noise:** Skewed documents or varying DPI can jitter coordinates. | Normalize coordinates to relative `[0.0, 1.0]` page percentages. |
| **Grid Line-Item Extraction:** Directly enables structured row/column parsing. | **Engine Dependency:** EasyOCR vs. PaddleOCR bounding box formats may differ. | `OCRTextBlock` standardizes all boxes to 4-point polygon `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`. |
| **Section Filtering:** Eliminates header/summary collisions. | **Multi-page Coordinate Splitting:** Blocks must be partitioned per `page_number`. | Ensure layout and table reconstructors operate per page index. |
| **Zero Database Overhead:** `raw_blocks` is already stored in DB. | **Overfitting to Fixed Templates:** Hardcoding exact pixel coordinates fails across vendors. | Use relative spatial relations (left-of, below, band clustering) rather than absolute pixel coordinates. |

---

## 14. Architecture Principle: No Global Text/Layout Weighting

Global numeric weighting (e.g. $0.6 \times \text{text} + 0.4 \times \text{layout}$) was rejected in classification and is **strictly prohibited in extraction**. 

Extraction is field-specific and structural:
- An **Invoice Number** is a single token found via label proximity (Y-band + right-ray search).
- A **Line-Item Table** is a 2D geometric grid parsed via column intervals and row clustering.
- An **Invoice Date** is parsed via regex candidate matching filtered by spatial page region.

Different fields require specific evidence mechanisms, not global scalar weighting formulas.

---

## 15. Classification Subsystem Isolation Confirmation

The classification subsystem remains completely text-based and isolated:
$$\text{OCR} \xrightarrow{\text{full\_text}} \text{Classification} \xrightarrow{\text{predicted\_type}} \text{classification\_results}$$

Extraction is investigated as:
$$\text{OCR} \xrightarrow{\text{full\_text} + \text{raw\_blocks}} \text{Extraction} \xrightarrow{\text{fields}} \text{extraction\_results}$$

No changes to classification will occur.

---

## 16. Explicit Answers to Questions A–Q

### A. What is the current extraction architecture?
**FACT:** Clean Architecture consisting of:
- `app/routers/extraction.py` (FastAPI router)
- `app/services/extraction_service.py` (Orchestrator)
- `app/extraction/factory.py` (Factory supporting `rule_based`, `llm_based`, `llm_rag`)
- `app/extraction/base.py` (`ExtractionEngine` interface)
- `app/extraction/rule_based.py` (`RuleBasedExtractor`)
- `app/extraction/type_extractors.py` (Per-type rule extractors for 9 document types)
- `app/extraction/primitives.py` (Label boundary regex and normalizers)
- `app/extraction/field_schemas.py` (Declarative schema definitions)
- `app/repositories/extraction_result_repository.py` & `app/models/extraction_result.py` (PostgreSQL `JSONB` persistence).

### B. What exactly does extraction receive today?
**FACT:** Extraction currently receives **ONLY `text: str` (`ocr_results.full_text`)** and **`document_type: str`**. It receives zero structural, bounding box, or tabular information.

### C. Where is `raw_blocks` created?
**FACT:** In `OCRService.run_ocr` (`backend/app/services/ocr_service.py`, lines 91–111) by calling `engine.extract_text_blocks(page_image)`.

### D. What exactly does `raw_blocks` contain?
**FACT:** A list of page dictionaries:
```python
[
  {
    "page_number": int,
    "page_width": float,
    "page_height": float,
    "blocks": [
      {
        "text": str,
        "confidence": float,
        "bounding_box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
      }
    ]
  }
]
```

### E. Is `raw_blocks` currently persisted?
**FACT:** **YES.** It is stored in the `ocr_results` PostgreSQL table in the `raw_blocks` column typed as `JSONB`.

### F. Does extraction currently have access to `raw_blocks`?
**FACT:** **NO.** `ExtractionService.extract()` loads `ocr_result` from `OCRResultRepository`, but only passes `ocr_result.full_text` to `engine.extract()`.

### G. What existing OCR/layout/table processing can extraction reuse?
**FACT:** Extraction can directly reuse:
1. `app.ocr.layout.order_blocks_spatially` (spatial band decomposition & column ordering)
2. `app.ocr.table_reconstruction.TableReconstructor` & `reconstruct_table` (reconstructs headers, columns, line-items, and multiline descriptions)
3. `app.ocr.normalization.normalize_table_data` (cleans amount and unit fields)

### H. What are the current weaknesses of the rule-based extractor?
**FACT:**
- Inability to parse side-by-side columns (Seller vs. Buyer information).
- Inability to extract line-item tables without flattening.
- Total amount collisions between line-item totals, subtotals, tax breakouts, and final invoice amounts.
- Loss of multi-line field continuations across newlines.
- Over-capturing text from adjacent columns on compact documents.

### I. Which weaknesses could `raw_blocks` actually help solve?
**FACT:**
- Multi-column party separation (Left vs Right bounding box rays).
- Tabular line-item extraction with column-aligned cells.
- Disambiguating Header/Body/Summary sections by Y-coordinate bands.
- Multi-line description merging based on vertical bounding-box alignment.

### J. Which weaknesses would `raw_blocks` NOT solve?
**FACT:**
- Severe OCR misspellings or dropped characters.
- Semantic terminology differences (e.g. unknown synonym labels).
- Unreadable or missing text on degraded scans.

### K. What is the minimum architectural change required to pass `raw_blocks` to extraction?
**FACT:**
1. Extend `ExtractionEngine.extract(text: str, document_type: str, raw_blocks: list[dict] | None = None)`.
2. Update `ExtractionService.extract()` to pass `raw_blocks=ocr_result.raw_blocks`.

### L. Would database changes be required?
**FACT:** **NO.** The database already stores `raw_blocks` as `JSONB` in `ocr_results`.

### M. Would OCR changes be required?
**FACT:** **NO.** OCR engines already generate `raw_blocks` and store them on every OCR run.

### N. Would the extraction interface need to change?
**FACT:** **YES.** `ExtractionEngine.extract()` needs `raw_blocks: list[dict] | None = None` added as an optional argument.

### O. What extraction rules would potentially benefit from structural information?
**FACT:**
- Party headers (`vendor_name`, `customer_name`, `vendor_code`, `customer_code`).
- Summary amounts (`invoice_amount`, `net_amount`, `tax_amount`, `deposit_amount`, `debit_amount`, `credit_amount`).
- Table line items (future line-item extraction schema).
- Header reference fields (`invoice_number`, `po_number`, `invoice_date`).

### P. What are the risks of introducing `raw_blocks` into extraction?
**FACT / TECHNICAL ASSESSMENT:**
- Overfitting to rigid coordinate templates across different vendor layouts.
- Sensitivity to OCR bounding-box jitter or skewed page rotations.
- Increased logic complexity if fallback to text-only rules is not cleanly maintained.

### Q. What should be done in the next implementation phase?
**RECOMMENDATION:**
1. Update `ExtractionEngine.extract()` interface with `raw_blocks: list[dict] | None = None`.
2. In `RuleBasedExtractor`, implement relative spatial helper primitives:
   - `extract_field_spatial_proximity(raw_blocks, labels, direction="right_or_below")`
   - `extract_summary_amount(raw_blocks, labels, region="bottom_summary")`
   - `extract_party_header(raw_blocks, party_type="seller"|"buyer")`
3. Integrate `app.ocr.table_reconstruction.reconstruct_table` when line-item extraction is scheduled.
4. Add comprehensive unit tests with representative `raw_blocks` fixtures verifying exact field extraction across multi-column layouts.

---

## 17. Files Inspected

### Source Code Files Inspected:
- `backend/app/extraction/base.py`
- `backend/app/extraction/factory.py`
- `backend/app/extraction/field_schemas.py`
- `backend/app/extraction/primitives.py`
- `backend/app/extraction/rule_based.py`
- `backend/app/extraction/type_extractors.py`
- `backend/app/extraction/llm_extractor.py`
- `backend/app/extraction/llm_schema.py`
- `backend/app/extraction/rag_diagnostic.py`
- `backend/app/services/extraction_service.py`
- `backend/app/services/ocr_service.py`
- `backend/app/services/validation_service.py`
- `backend/app/routers/extraction.py`
- `backend/app/schemas/extraction.py`
- `backend/app/models/extraction_result.py`
- `backend/app/models/ocr_result.py`
- `backend/app/models/validation_result.py`
- `backend/app/repositories/extraction_result_repository.py`
- `backend/app/repositories/ocr_result_repository.py`
- `backend/app/ocr/base.py`
- `backend/app/ocr/layout.py`
- `backend/app/ocr/table_reconstruction.py`
- `backend/app/ocr/normalization.py`

### Test Files Inspected:
- `backend/tests/test_phase6_extraction.py`
- `backend/tests/test_hybrid_llm_extraction.py`

---

## 18. Final Recommendation

1. **Keep Subsystems Cleanly Separated:**
   - Classification remains strictly text-based (`full_text`).
   - Extraction is upgraded to receive `full_text` + `raw_blocks`.
2. **Reuse Existing Table & Layout Infrastructure:**
   - Rather than reinventing spatial table parsing, connect `ExtractionService` to the already existing `TableReconstructor` (`app/ocr/table_reconstruction.py`) and spatial band analyzer (`app/ocr/layout.py`).
3. **Graceful Degradation:**
   - If `raw_blocks` is `None` or empty, extractors must fall back cleanly to 1D `full_text` regex primitives.
4. **No Premature Execution:**
   - This audit completes the investigation phase. All findings are recorded and verified against active code. No changes to the codebase have been made.

---
*End of Forensic Audit Report.*
