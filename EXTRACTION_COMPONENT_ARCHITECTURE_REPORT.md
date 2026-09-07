# EFDI — Deep Extraction Component Architecture & Runtime Analysis

**Date:** 2026-09-02  
**Investigation Mode:** READ-ONLY ARCHITECTURAL AUDIT  
**Status:** COMPLETED  
**Implementation State:** NOT IMPLEMENTED (Read-Only)  

---

## 1. Executive Summary

This report presents a code-level, read-only architectural investigation of the Extraction Subsystem in the Enterprise Financial Document Intelligence (EFDI) platform. Every claim, data boundary, and runtime trace in this document has been verified against the active codebase located in `C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI`.

### Core Findings:
1. **The Default Extractor is `RuleBasedExtractor`:** Configured via `settings.EXTRACTION_DEFAULT_ENGINE = "rule_based"`. It executes purely deterministic regex pattern matching over flattened text.
2. **Severe Data Disconnect at Extraction Boundary:** While the upstream OCR subsystem computes 2D spatial layouts (`layout.py`), bounding-box coordinates (`raw_blocks`), geometric line-item tables (`table_reconstruction.py`), and normalized floats/dates (`normalization.py`), **none of this structured or spatial data is passed into the extraction engine**. `ExtractionService` passes only two parameters: `ocr_result.full_text` (a 1D string) and `classification_result.predicted_type` (a string code).
3. **ERP-Centric Field Schemas:** Field definitions in `field_schemas.py` reflect internal ERP document taxonomy (e.g., `vendor_code`, `company_code`, `fiscal_year`) rather than commercial invoice entities (`seller_name`, `buyer_name`, `seller_address`, `seller_tax_id`, `grand_total`, `line_items`).
4. **Why Real Invoices Fail (e.g., `invoice_51109301.pdf` extracting only 1 of 25 fields):** Real-world invoices format headers as `"Seller:"`, `"Client:"`, `"Date of issue:"`, and present multi-column line items. The rule-based extractor looks strictly for inline labels like `"Vendor Name:"`, `"Invoice Date:"`, and completely discards upstream reconstructed table line items.
5. **Existing `LLMBasedExtractor` Status:** A dynamic Pydantic LLM extractor with RAG diagnostic reconciliation exists in `llm_extractor.py` and `rag_diagnostic.py`. However, it is **inactive by default** and automatically falls back to `RuleBasedExtractor` whenever `OPENAI_API_KEY` is not configured.

---

## 2. Extraction Component Inventory

The complete extraction subsystem spans the following backend modules:

| Module / Path | Primary Class / Functions | Architectural Role |
|---|---|---|
| `backend/app/extraction/base.py` | `ExtractedField`, `ExtractionResultData`, `ExtractionEngine` | Abstract base contracts and in-memory data representations. |
| `backend/app/extraction/factory.py` | `get_extraction_engine()`, `SUPPORTED_EXTRACTORS` | Singleton engine factory dispatching `"rule_based"`, `"llm_based"`, `"llm_rag"`. |
| `backend/app/extraction/rule_based.py` | `RuleBasedExtractor` | Default runtime engine dispatching to per-type extractor functions. |
| `backend/app/extraction/type_extractors.py` | `extract_common_fields()`, `extract_poi_fields()`, `extract_npo_fields()`, `extract_msi_fields()`, etc. | Per-document-type dictionary builders invoking regex extraction primitives. |
| `backend/app/extraction/field_schemas.py` | `FieldDef`, `COMMON_FIELDS`, `DOCUMENT_TYPE_FIELDS`, `get_full_field_schema()` | Single source of truth for schema definitions across 9 financial document types. |
| `backend/app/extraction/primitives.py` | `extract_by_labels()`, `extract_date_field()`, `extract_amount_field()`, `normalize_date()`, `normalize_amount()` | Regex pattern construction, stop-boundary enforcement, and primitive normalization. |
| `backend/app/extraction/llm_extractor.py` | `LLMBasedExtractor` | Structured JSON extraction via OpenAI chat completion API with rule-based fallback. |
| `backend/app/extraction/llm_schema.py` | `LLMFieldItem`, `build_dynamic_extraction_model()` | Runtime Pydantic model generator creating typed extraction schemas dynamically. |
| `backend/app/extraction/rag_diagnostic.py` | `RAGDiagnosticService` | Secondary audit pass using `DocumentChunk` pgvector embeddings to reconcile arithmetic. |
| `backend/app/services/extraction_service.py` | `ExtractionService` | Workflow orchestrator coordinating OCR retrieval, classification, engine execution, DB persistence, and status updates. |
| `backend/app/repositories/extraction_result_repository.py` | `ExtractionResultRepository` | Data access layer for `extraction_results` PostgreSQL table. |
| `backend/app/models/extraction_result.py` | `ExtractionResult` | SQLAlchemy ORM model storing extracted fields as JSONB. |
| `backend/app/schemas/extraction.py` | `ExtractedFieldSchema`, `ExtractionResultResponse`, `ExtractRequest`, `FieldUpdateRequest` | Pydantic API request/response serialization contracts. |
| `backend/app/routers/extraction.py` | `extract_document_fields()`, `get_latest_extraction()`, `update_extracted_field()`, `export_extraction_fields()` | FastAPI REST endpoints for extraction execution, retrieval, manual correction, and file export. |

---

## 3. Actual Runtime Call Chain

The complete end-to-end execution chain from HTTP request to frontend rendering:

```
1. HTTP Client (Browser / API)
   │ POST /api/v1/extraction/documents/{id}/extract
   │ Payload: {"engine": null}
   ▼
2. FastAPI Router: backend/app/routers/extraction.py
   Function: extract_document_fields(document_id, payload, db, current_user)
   │ - Validates user permissions via DocumentService.get_for_user()
   ▼
3. Service Layer: backend/app/services/extraction_service.py
   Function: ExtractionService.extract(document, engine_name=None)
   │ - Step 3a: OCRResultRepository.get_latest_for_document(doc_id) -> fetches OCRResult
   │ - Step 3b: ClassificationResultRepository.get_latest_for_document(doc_id) -> fetches ClassificationResult
   │ - Step 3c: Resolves engine: engine_name or settings.EXTRACTION_DEFAULT_ENGINE ("rule_based")
   ▼
4. Factory Layer: backend/app/extraction/factory.py
   Function: get_extraction_engine("rule_based")
   │ - Instantiates or retrieves singleton RuleBasedExtractor()
   ▼
5. Extraction Engine: backend/app/extraction/rule_based.py
   Function: RuleBasedExtractor.extract(text=ocr_result.full_text, document_type=classification_result.predicted_type)
   │ - Resolves type function from TYPE_EXTRACTORS (e.g., extract_npo_fields)
   │ - Calls extract_common_fields(text)
   │ - Calls type_extractor_fn(text)
   ▼
6. Type Extractor: backend/app/extraction/type_extractors.py
   Function: extract_npo_fields(text)
   │ - Dispatches each field key to primitives (e.g. extract_by_labels, extract_date_field, extract_amount_field)
   ▼
7. Primitives: backend/app/extraction/primitives.py
   Function: extract_by_labels(text, labels)
   │ - Compiles regex with KNOWN_LABELS boundary
   │ - Searches text, strips prefixes, calculates label-index confidence
   │ - Returns ExtractedField(value, confidence, matched_text)
   ▼
8. Engine Merging & Aggregation: backend/app/extraction/base.py
   Class: ExtractionResultData
   │ - Aggregates dictionary of fields
   │ - Computes overall_confidence, fields_found_count, fields_total_count
   ▼
9. Persistence Layer: backend/app/repositories/extraction_result_repository.py
   Function: ExtractionResultRepository.create(...)
   │ - Writes new row to extraction_results table with JSONB fields payload
   │ - DocumentRepository.update_status(document, "EXTRACTED")
   │ - AuditService.log(AuditAction.EXTRACTION_RUN)
   ▼
10. API Serialization: backend/app/schemas/extraction.py
    Class: ExtractionResultResponse
    │ - Serializes SQLAlchemy model into JSON response (status 201 Created)
    ▼
11. Frontend Client: frontend/src/services/pipeline.ts -> extractionApi.getLatest(id)
    Component: frontend/src/pages/DocumentDetailPage.tsx -> <TabsContent value="extraction">
    Component: frontend/src/components/extraction-fields.tsx -> <ExtractionFields />
    │ - Renders table of field names, values, and ConfidenceBar meters
```

---

## 4. Extraction Engine Selection

### Configuration Source:
Defined in `backend/app/core/config.py`:
```python
EXTRACTION_DEFAULT_ENGINE: str = "rule_based"
EXTRACTION_LLM_MODEL: str = "gpt-4o-mini"
OPENAI_API_KEY: str | None = None
OPENAI_API_BASE: str | None = None
```

### Factory Selection Logic (`backend/app/extraction/factory.py`):
```python
SUPPORTED_EXTRACTORS = ("rule_based", "llm_based", "llm_rag")

def get_extraction_engine(engine_name: str = "rule_based") -> ExtractionEngine:
    if engine_name not in SUPPORTED_EXTRACTORS:
        raise ValidationFailedException(f"Unknown extraction engine '{engine_name}'.")
    ...
```

### Runtime Behaviors:
1. **Default Request (No Engine Specified):**
   - Router receives `payload.engine = None`.
   - `ExtractionService` falls back to `settings.EXTRACTION_DEFAULT_ENGINE` (`"rule_based"`).
   - Factory returns `RuleBasedExtractor`.
2. **Explicit Override (`engine="llm_based"`):**
   - Factory returns `LLMBasedExtractor`.
   - If `OPENAI_API_KEY` is not set in `.env`, `LLMBasedExtractor.extract()` logs a warning and **automatically falls back to `RuleBasedExtractor`**, setting `engine_name="llm_based"`.
3. **Explicit Override (`engine="llm_rag"`):**
   - Factory returns `LLMBasedExtractor`.
   - After extraction, `ExtractionService` invokes `RAGDiagnosticService.diagnose_and_refine()` using vector embeddings.

---

## 5. Existing RuleBasedExtractor Architecture

### Class Definition:
- **Module:** `backend/app/extraction/rule_based.py`
- **Class:** `RuleBasedExtractor(ExtractionEngine)`
- **Signature:** `extract(self, text: str, document_type: str) -> ExtractionResultData`

### Step-by-Step Execution Logic:
1. **Schema Check:** Looks up `TYPE_EXTRACTORS.get(document_type)`. If document type is unknown or has no extractor registered, returns an empty `ExtractionResultData`.
2. **Empty Text Handling:** If `text` is blank, instantiates every field in `COMMON_FIELDS + DOCUMENT_TYPE_FIELDS[type]` with `value=None` and `confidence=0.0`.
3. **Common Field Extraction:** Calls `extract_common_fields(text)`.
4. **Type-Specific Extraction:** Calls `type_extractor_fn(text)` (e.g., `extract_poi_fields(text)`).
5. **Aggregation:** Merges all extracted field dictionaries into `result.fields`.

### Key Limitations:
- It has no awareness of line breaks, layout hierarchy, or 2D positioning.
- If two identical labels exist (e.g., a "Tax Id" for seller and a "Tax Id" for buyer), it always matches the first occurrence in the text.
- Over-capture is mitigated only by fixed stop-boundary keywords.

---

## 6. Field Schema Architecture

The single source of truth for all extraction schemas is `backend/app/extraction/field_schemas.py`.

### Schema Summary Table:

| Document Type | Field Key | Field Label | Data Type | Extraction Primitive | Status / Comment |
|---|---|---|---|---|---|
| **COMMON (All)** | `document_id` | Document ID | `code` | `extract_by_labels` | Searches `"Document ID"`, `"Doc ID"`, `"DOCID"` |
| | `document_type` | Document Type | `code` | Populated by Service | From classification result |
| | `document_category` | Document Category | `code` | `extract_by_labels` | Derived from AP/R2R mapping |
| | `company_code` | Company Code | `code` | `extract_by_labels` | Searches `"Company Code"`, `"COCODE"` |
| | `company_name` | Company Name | `text` | `extract_by_labels` | Searches `"Company Name"` |
| | `fiscal_year` | Fiscal Year | `code` | `extract_by_labels` | Searches `"Fiscal Year"`, `"FY"` |
| | `location_code` | Location Code | `code` | `extract_by_labels` | Searches `"Location Code"`, `"LOC CODE"` |
| | `vertical_code` | Vertical Code | `code` | `extract_by_labels` | Searches `"Vertical Code"` |
| | `document_source` | Document Source | `text` | `extract_by_labels` | Searches `"Document Source"`, `"Doc Source"` |
| | `barcode` | Barcode | `code` | `extract_by_labels` | Searches `"Barcode"`, `"Bar Code"` |
| | `currency` | Currency | `code` | `extract_by_labels` | Searches `"Currency"` |
| | `document_date` | Document Date | `date` | `extract_date_field` | Searches `"Document Date"`, `"Doc Date"` |
| | `ocr_confidence_score`| OCR Confidence Score | `amount` | Populated by Service | From OCR average confidence |
| | `processing_status` | Processing Status | `text` | `extract_by_labels` | Searches `"Processing Status"` |
| | `validation_status` | Validation Status | `text` | `extract_by_labels` | Searches `"Validation Status"` |
| **POI (PO Invoice)** | `vendor_code` | Vendor Code | `code` | `extract_by_labels` | Searches `"Vendor Code"` |
| | `vendor_name` | Vendor Name | `text` | `extract_by_labels` | Searches `"Vendor Name"`, `"Vendor"` |
| | `po_number` | PO Number | `code` | `extract_by_labels` | Searches `"PO Number"`, `"PO No"` |
| | `grn_number` | GRN Number | `code` | `extract_by_labels` | Searches `"GRN Number"`, `"GRN"` |
| | `srn_number` | SRN Number | `code` | `extract_by_labels` | Searches `"SRN Number"`, `"SRN"` |
| | `invoice_number` | Invoice Number | `code` | `extract_by_labels` | Searches `"Invoice Number"`, `"Invoice No"` |
| | `invoice_date` | Invoice Date | `date` | `extract_date_field` | Searches `"Invoice Date"` |
| | `invoice_amount` | Invoice Amount | `amount` | `extract_amount_field` | Searches `"Invoice Amount"`, `"Total Amount"` |
| | `tax_amount` | Tax Amount | `amount` | `extract_amount_field` | Searches `"Tax Amount"`, `"GST Amount"` |
| | `net_amount` | Net Amount | `amount` | `extract_amount_field` | Searches `"Net Amount"` |
| | `payment_terms` | Payment Terms | `text` | `extract_by_labels` | Searches `"Payment Terms"` |
| **NPO (Non-PO)** | `vendor_code` | Vendor Code | `code` | `extract_by_labels` | Searches `"Vendor Code"` |
| | `vendor_name` | Vendor Name | `text` | `extract_by_labels` | Searches `"Vendor Name"`, `"Vendor"` |
| | `invoice_number` | Invoice Number | `code` | `extract_by_labels` | Searches `"Invoice Number"`, `"Invoice No"` |
| | `invoice_date` | Invoice Date | `date` | `extract_date_field` | Searches `"Invoice Date"` |
| | `invoice_amount` | Invoice Amount | `amount` | `extract_amount_field` | Searches `"Invoice Amount"`, `"Amount Due"` |
| | `expense_category` | Expense Category | `text` | `extract_by_labels` | Searches `"Expense Category"` |
| | `cost_center` | Cost Center | `code` | `extract_by_labels` | Searches `"Cost Center"` |
| | `department` | Department | `text` | `extract_by_labels` | Searches `"Department"` |
| | `tax_amount` | Tax Amount | `amount` | `extract_amount_field` | Searches `"Tax Amount"` |
| | `net_amount` | Net Amount | `amount` | `extract_amount_field` | Searches `"Net Amount"` |
| **MSI (Sales Inv)** | `customer_code` | Customer Code | `code` | `extract_by_labels` | Searches `"Customer Code"` |
| | `customer_name` | Customer Name | `text` | `extract_by_labels` | Searches `"Customer Name"`, `"Bill To"` |
| | `sales_invoice_number`| Sales Invoice No | `code` | `extract_by_labels` | Searches `"Sales Invoice Number"`, `"Invoice #"`|
| | `due_date` | Due Date | `date` | `extract_date_field` | Searches `"Due Date"` |

### Comparison: Current ERP Fields vs. Standard Commercial Invoice Fields

```
┌──────────────────────────────────────┬──────────────────────────────────────┐
│ Current Schema Fields (ERP-Centric)  │ Standard Commercial Invoice Fields   │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ company_code, company_name           │ seller_name                          │
│ vertical_code, location_code         │ seller_address (street, city, zip)   │
│ fiscal_year                          │ seller_tax_id / GSTIN / VAT ID       │
│ barcode                              │ seller_iban / bank_account           │
│ vendor_code, vendor_name             │ buyer_name                           │
│ customer_code (MSI only)             │ buyer_address                        │
│ cost_center, department (NPO only)   │ buyer_tax_id                         │
│ expense_category                     │ line_items (description, qty, price) │
│ document_source                      │ subtotal, tax_total, grand_total     │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## 7. Extraction Primitives Deep Dive

**Module:** `backend/app/extraction/primitives.py`

### 1. Regex Pattern Construction (`_VALUE_CAPTURE`)
The core value capture pattern is defined as:
```python
_VALUE_CAPTURE = (
    r"(?:\s*\([^)\n]{0,30}\))?"  # Optional parenthetical e.g. "(GST)"
    r"[:\-=]?\s*([^\n]*?)"        # Separator followed by non-greedy value
    r"(?=\s{2,}|\n|\s*(?:" + _NEXT_LABEL_BOUNDARY + r")\s*[:\-](?:\s|$)|$)"
)
```

Where `_NEXT_LABEL_BOUNDARY` is a regular expression constructed from **83 `KNOWN_LABELS`** sorted longest-first:
```python
KNOWN_LABELS = [
    "Deposit Reference Number", "Manager Approval Status", "Purchase Order Number",
    "Invoice Number", "Vendor Name", "Bill To", "Tax Amount", "Invoice No", ...
]
```

### 2. Label Matching Execution (`extract_by_labels`)
- **Input:** `text: str`, `labels: list[str]`, `max_value_length: int = 80`.
- **Search:** Iterates through `labels` sequentially. For each label, executes `re.search(r"\b" + re.escape(label) + r"\b" + _VALUE_CAPTURE, text, re.IGNORECASE)`.
- **Confidence Formula:**
  $$\text{confidence} = \max(0.30, 0.90 - (\text{label\_index} \times 0.10) - \text{penalty})$$
  *(Penalty of 0.20 is applied if extracted string length > 80 characters).*
- **Missing Label Behavior:** Returns `ExtractedField(value=None, confidence=0.0, matched_text=None)`.

### 3. Date Extraction (`extract_date_field` & `normalize_date`)
- Normalizes ordinal suffixes (`"21st"` -> `"21"`).
- Attempts matching against 14 formats: `%d-%m-%Y`, `%d/%m/%Y`, `%d.%m.%Y`, `%Y-%m-%d`, `%Y/%m/%d`, `%d %B %Y`, `%d-%b-%Y`, etc.
- Output: Standardized ISO string `YYYY-MM-DD`. If date parsing fails, returns raw string with confidence penalized by 0.4x.

### 4. Amount Extraction (`extract_amount_field` & `normalize_amount`)
- Strips currency tokens, spaces, and commas (`"Rs. 25,000.50"` -> `"25000.50"`).
- Validates string via `float()`. If invalid, reduces confidence by 0.4x.

### 5. Multiline Limitation
Because `_VALUE_CAPTURE` explicitly terminates at `\n`, any invoice where the label is on line 1 and the value is on line 2 (such as `"Date of issue:\n03/07/2023"`) fails to capture the value, resulting in `value=None`.

---

## 8. Classification to Extraction Flow

```
[ Uploaded Document ] ──► [ ClassificationService ] ──► [ ClassificationResult ]
                                                                 │
                                                       predicted_type = "NPO"
                                                                 │
                                                                 ▼
                                                    [ ExtractionService ]
                                                                 │
                                                     schema = SCHEMAS["NPO"]
                                                                 │
                                                                 ▼
                                                  [ extract_npo_fields(text) ]
```

### Critical Findings:
1. **Hard Coupling:** `ExtractionService` requires a completed `ClassificationResult`. If classification has not been run, extraction raises `ValidationFailedException("Run classification first")`.
2. **Impact of Classification Errors:** If a PO Invoice (`POI`) is misclassified as Non-PO (`NPO`):
   - The extractor runs `extract_npo_fields()`.
   - Fields specific to POI (`po_number`, `grn_number`, `srn_number`, `payment_terms`) are **never attempted**.
   - Fields specific to NPO (`cost_center`, `expense_category`, `department`) are attempted and return `null`.
3. **Classification Confidence is Discarded:** The numerical confidence (e.g., 0.24) is not passed to the extraction engine. The extractor treats all classifications with equal certainty.
4. **Manual Classification Correction:** When a user corrects a document classification in the UI (e.g. from NPO to POI), the DB records `predicted_type = "POI"` and sets `confidence = 1.0`. A subsequent extraction run immediately uses the corrected schema.

---

## 9. OCR to Extraction Data Boundary (Information Loss)

The following matrix documents every data element produced by the OCR and structural analysis pipeline versus what actually reaches the extraction service:

| Data Element | Produced by OCR? | Produced by Layout? | Produced by Table Recon? | Passed to ExtractionService? | Reaches Extractor Engine? |
|---|---|---|---|---|---|
| **Raw Text Characters** | YES (`OCRTextBlock.text`) | YES | YES | YES (`ocr_result.full_text`) | **YES** |
| **Character Coordinates (BBoxes)** | YES (`bounding_box`) | YES | YES | NO (Stored in DB only) | **NO (LOST)** |
| **Per-Block OCR Confidence** | YES (`confidence`) | YES | YES | NO (Stored in DB only) | **NO (LOST)** |
| **Page Dimensions (W, H)** | YES (`raw_blocks[0]`) | YES | YES | NO (Stored in DB only) | **NO (LOST)** |
| **Spatial Column Bands (Left/Right)** | NO | YES (`order_blocks_spatially`) | NO | NO (Consolidated to text) | **NO (LOST)** |
| **Reading Order Sequence** | NO | YES | NO | YES (Implicit in `full_text`) | **YES** |
| **Table Header Columns** | NO | NO | YES (`headers`) | NO (Discarded in OCRService) | **NO (LOST)** |
| **Structured Line Items** | NO | NO | YES (`line_items`) | NO (Discarded in OCRService) | **NO (LOST)** |
| **Normalized Quantities & Prices** | NO | NO | YES (`NormalizedLineItem`) | NO (Discarded in OCRService) | **NO (LOST)** |
| **Arithmetic Validation Flags** | NO | NO | YES (`validation_res`) | NO (Used for scoring only) | **NO (LOST)** |
| **Composite Quality Score** | NO | NO | YES (`quality_score`) | NO (Logged to audit only) | **NO (LOST)** |

---

## 10. Spatial Data Analysis

Spatial coordinates are generated by `EasyOCREngine` as 4-point polygon arrays:
```json
{"text": "TechVision Distributors Pvt Ltd", "confidence": 0.91, "bounding_box": [[92, 196], [420, 196], [420, 224], [92, 224]]}
```

### Where Spatial Information Disappears:
In `backend/app/ocr/base.py` (Line 34–35):
```python
class OCRPageResult:
    page_number: int
    blocks: list[OCRTextBlock] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(block.text for block in self.blocks)  # <-- Bounding boxes stripped here
```

And in `backend/app/services/extraction_service.py` (Line 54):
```python
result_data = engine.extract(ocr_result.full_text, document_type)  # <-- Flat string passed
```

The extractor receives only the 1D flattened string. All X, Y coordinates, bounding boxes, and column relationships are completely inaccessible to `RuleBasedExtractor`.

---

## 11. Table Reconstruction to Extraction Disconnect

### Upstream Execution in `OCRService.run_ocr()` (`backend/app/services/ocr_service.py`):
```python
# Lines 127-136:
table_dict = reconstruct_table(raw_blocks[0]["blocks"], page_width, page_height).to_dict()
normalized_items = normalize_table_data(table_dict)
validation_res = validate_ocr_output(normalized_items, full_text)
quality_breakdown = calculate_quality_score(avg_conf, full_text, table_dict, validation_res)
```

### The Disconnect:
1. `table_dict` and `normalized_items` are local variables inside `OCRService.run_ocr()`.
2. They are used solely as arguments to `calculate_quality_score()`.
3. They are **never written to the database** and **never returned to the caller**.
4. When `ExtractionService` executes later, it loads only `ocr_result.full_text` and `ocr_result.raw_blocks`.
5. `ExtractionEngine` has no parameter or schema for table data.

**Conclusion:** Table reconstruction is executed during OCR, produces valid `StructuredLineItem` objects, and is then immediately discarded.

---

## 12. Existing LLMBasedExtractor Deep Dive

**Module:** `backend/app/extraction/llm_extractor.py`

### Configuration & Initialization:
- **Class:** `LLMBasedExtractor(ExtractionEngine)`
- **Default Model:** `"gpt-4o-mini"` (via `settings.EXTRACTION_LLM_MODEL`)
- **API Endpoint:** OpenAI-compatible `/chat/completions` (via `urllib.request`)
- **Fallback Instance:** `self._fallback_rule_extractor = RuleBasedExtractor()`

### Dynamic Schema Generation (`llm_schema.py`):
Generates runtime Pydantic models from `FieldDef` objects:
```python
class LLMFieldItem(BaseModel):
    value: Optional[str] = None
    confidence: float = 0.85
    source_quote: Optional[str] = None
```

### Prompt Construction:
- **System Prompt:** Instructs the LLM to extract fields for the given `document_type` and provide verbatim `source_quote` snippets.
- **User Prompt:**
  ```
  DOCUMENT OCR TEXT:
  \"\"\"
  {text}
  \"\"\"
  ```

### What the LLM Extractor Receives vs. Does NOT Receive:
- **Receives:** `full_text` (flat string), `document_type` (string).
- **Does NOT Receive:** `raw_blocks`, bounding boxes, table structures, page dimensions, normalized data, or image pixels.

### Failure & Fallback Behavior:
1. If `OPENAI_API_KEY` is missing: Logs warning and invokes `RuleBasedExtractor.extract(text, document_type)`.
2. If API call times out (>45s) or JSON schema fails: Catches exception, logs error, and invokes `RuleBasedExtractor.extract(text, document_type)`.

---

## 13. Extraction Result Architecture & Database Persistence

### Database Schema (`backend/app/models/extraction_result.py`):
```python
class ExtractionResult(Base, TimestampMixin):
    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(30), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fields_found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

### JSONB `fields` Payload Structure:
```json
{
  "invoice_number": {
    "value": "51109301",
    "confidence": 0.9,
    "matched_text": "Invoice no: 51109301",
    "is_found": true,
    "manually_entered": false
  },
  "vendor_name": {
    "value": null,
    "confidence": 0.0,
    "matched_text": null,
    "is_found": false,
    "manually_entered": false
  }
}
```

---

## 14. API Contract & Frontend Consumption

### REST Endpoints (`backend/app/routers/extraction.py`):
- `POST /api/v1/extraction/documents/{id}/extract` — Run extraction (body: `{"engine": "rule_based" | "llm_based" | "llm_rag"}`).
- `GET /api/v1/extraction/documents/{id}/result` — Fetch latest result.
- `GET /api/v1/extraction/documents/{id}/results` — Fetch history.
- `PATCH /api/v1/extraction/documents/{id}/fields/{field_key}` — Manual correction (`{"value": "New Val"}`).
- `GET /api/v1/extraction/documents/{id}/export?format=json|csv|excel` — File export.

### Frontend Rendering (`frontend/src/components/extraction-fields.tsx`):
- Iterates over `Object.entries(fields)`.
- If `field.value` is `null`, renders `"Not found"` in italic grey.
- Renders `ConfidenceBar` using `field.confidence`.
- Offers inline editing pencil icon allowing manual overrides via `PATCH`.

---

## 15. Error Handling Architecture

| Failure Scenario | Exception / Handler | System Behavior |
|---|---|---|
| Document has no OCR | `ValidationFailedException` | HTTP 400: "Cannot extract fields from a document with no OCR result." |
| Document has no Classification | `ValidationFailedException` | HTTP 400: "Cannot extract fields from a document with no classification result." |
| Unknown Extraction Engine | `ValidationFailedException` | HTTP 400: "Unknown extraction engine 'xxx'." |
| Document Not Found | `NotFoundException` | HTTP 404: "Document not found." |
| Missing `OPENAI_API_KEY` | Caught in `LLMBasedExtractor` | Logs warning; falls back to `RuleBasedExtractor`. |
| LLM Network / Timeout Failure | Caught in `LLMBasedExtractor` | Logs error; falls back to `RuleBasedExtractor`. |
| Unparseable Date / Amount String | Caught in `primitives.py` | Retains raw string; penalizes confidence by 0.4x. |
| Unrecognized Label | Regex non-match | Sets `value=None`, `confidence=0.0`, `is_found=False`. |

---

## 16. Test Architecture Audit

Inspection of test suites in `backend/tests/`:

| Test File | Test Targets | Uses Real Invoices? | Coverage Summary |
|---|---|---|---|
| `test_phase6_extraction.py` | `RuleBasedExtractor`, `field_schemas`, `primitives` | **NO (Synthetic Only)** | Tests synthetic label-value strings (e.g. `"Invoice Number: INV-2026-001"`). Proves regex matches ideal strings; does not test real invoice layouts. |
| `test_hybrid_llm_extraction.py` | `LLMBasedExtractor`, `RAGDiagnosticService`, `llm_schema` | **NO (Mocked Only)** | Verifies dynamic Pydantic schema generation, normalizers, and mock LLM JSON payloads. |
| `test_ocr_layout.py` | `order_blocks_spatially` | NO | Verifies block sorting and party splitting. |
| `test_ocr_table_reconstruction.py`| `TableReconstructor` | NO | Verifies geometric column clustering on synthetic blocks. |

**Critical Test Gap:** There are **zero tests** that assert end-to-end extraction accuracy against real invoices from the dataset (`Batch 1/invoices`).

---

## 17. Real Invoice Trace: `invoice_51109301.pdf`

Detailed trace of `invoice_51109301.pdf` (Classified as `NPO`):

### 1. OCR Output:
Recognizes 60 blocks, 87.08% average confidence. All invoice text, vendor names, line items, and totals are present.

### 2. Upstream Table Reconstruction:
Successfully reconstructs 3 line items:
- Garmin Fenix 7 Solar GPS (Qty 9, Price 74,120.00, Net 667,080.00)
- Apple Watch Series 9 GPS 45mm (Qty 8, Price 52,083.00, Net 416,664.00)
- Xiaomi 14 Pro 512GB White (Qty 8, Price 74,154.00, Net 593,232.00)

### 3. What Extraction Receives:
`ocr_result.full_text` and `document_type="NPO"`.

### 4. Field-by-Field Extraction Result:

| Schema Field | Target in Document | Search Label / Regex | Extraction Result | Root Cause of Failure |
|---|---|---|---|---|
| `invoice_number` | `"51109301"` | `"Invoice Number"`, `"Invoice No"` | **`"51109301"` (0.90)** | **SUCCESS** (matched `"Invoice no:"`) |
| `invoice_date` | `"03/07/2023"` | `"Invoice Date"` | `null` (0.00) | Document has `"Date of issue:\n03/07/2023"` |
| `vendor_name` | `"TechVision Distributors..."` | `"Vendor Name"`, `"Vendor"` | `null` (0.00) | Document has `"Seller:\nTechVision..."` |
| `vendor_code` | Not present | `"Vendor Code"` | `null` (0.00) | No vendor code on document |
| `company_name` | Not present | `"Company Name"` | `null` (0.00) | No company name label |
| `currency` | `"INR"` | `"Currency"` | `null` (0.00) | Currency present as prefix without `"Currency:"` label |
| `net_amount` | `"1,676,976.00"` | `"Net Amount"` | `null` (0.00) | Document labels summary as `"Net Worth"` |
| `tax_amount` | `"167,697.60"` | `"Tax Amount"`, `"GST Amount"` | `null` (0.00) | Document labels summary as `"VAT"` |
| `invoice_amount` | `"1,844,673.60"` | `"Invoice Amount"`, `"Amount Due"` | `null` (0.00) | Document labels total as `"Total"` |
| `seller_name` | `"TechVision Distributors..."` | N/A | `N/A` | Field missing from NPO schema |
| `buyer_name` | `"Raj Electronics..."` | N/A | `N/A` | Field missing from NPO schema |
| `line_items` | 3 line items | N/A | `N/A` | Discarded before extraction |

**Final Outcome:** **1 of 25 fields found** (`invoice_number`).

---

## 18. Confidence Semantics

The system contains 6 distinct confidence concepts that must not be conflated:

```
1. OCR Confidence
   - Origin: EasyOCR neural network character recognition.
   - Range: 0.0 to 1.0 (Average 0.87 on benchmark).
   - Meaning: Visual legibility of character glyphs.

2. Classification Confidence
   - Origin: RuleBasedClassifier keyword signal scoring.
   - Range: 0.0 to 1.0 (e.g. 0.24 on NPO).
   - Meaning: Certainty in document category.

3. Extraction Field Confidence
   - Origin: Label match position (0.90 for 1st alias, -0.10 per fallback).
   - Range: 0.30 to 0.90 (0.0 when null).
   - Meaning: Regex pattern match specificity.

4. Document Overall Quality Score
   - Origin: Weighted formula (0.35 OCR + 0.25 Layout + 0.25 Math + 0.15 Fields).
   - Range: 0.0 to 1.0 (e.g. 0.95 "EXCELLENT").
   - Meaning: Composite structural health.

5. Human Verification Confidence
   - Origin: Manual analyst correction via UI.
   - Value: Fixed 1.0.
   - Meaning: Verified by human reviewer.

6. Ground-Truth Accuracy
   - Origin: Independent exact match against verified ground truth JSON.
   - Meaning: True real-world correctness.
```

---

## 19. Current Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       FRONTEND (React)                                      │
│                DocumentDetailPage ──► TabsContent (Extraction) ──► ExtractionFields         │
└──────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                               │ HTTP GET / POST
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                      API ROUTERS & SERVICES                                 │
│  routers/extraction.py ──► ExtractionService.extract(doc)                                   │
└───────┬──────────────────────────────────────┬──────────────────────────────────────────────┘
        │                                      │
        ▼ Reads                                ▼ Calls
┌───────────────────────────────┐      ┌──────────────────────────────────────────────────────┐
│       DATABASE (PostgreSQL)   │      │                  EXTRACTION FACTORY                  │
│  ocr_results                  │      │  get_extraction_engine("rule_based")                 │
│    - full_text (USED)         │      └──────────────────────────┬───────────────────────────┘
│    - raw_blocks (IGNORED)     │                                 │
│  classification_results       │                                 ▼
│    - predicted_type (USED)    │      ┌──────────────────────────────────────────────────────┐
│    - confidence (IGNORED)     │      │                 RuleBasedExtractor                   │
└───────────────────────────────┘      │  extract(full_text, document_type)                   │
                                       └──────────┬───────────────────────────────┬───────────┘
                                                  │                               │
                                                  ▼                               ▼
                                       ┌──────────────────────┐       ┌───────────────────────┐
                                       │ extract_common_fields│       │  extract_npo_fields   │
                                       └──────────┬───────────┘       └───────────┬───────────┘
                                                  │                               │
                                                  └───────────────┬───────────────┘
                                                                  │
                                                                  ▼
                                       ┌──────────────────────────────────────────────────────┐
                                       │                 primitives.py                        │
                                       │  extract_by_labels(text, KNOWN_LABELS)               │
                                       │  normalize_date(), normalize_amount()                │
                                       └──────────────────────────┬───────────────────────────┘
                                                                  │
                                                                  ▼
                                       ┌──────────────────────────────────────────────────────┐
                                       │                 ExtractionResultData                 │
                                       │  fields: {invoice_number: 51109301, vendor_name: null}│
                                       └──────────────────────────┬───────────────────────────┘
                                                                  │
                                                                  ▼ Persists
                                       ┌──────────────────────────────────────────────────────┐
                                       │      DB: extraction_results table (JSONB)            │
                                       └──────────────────────────────────────────────────────┘
```

---

## 20. How EFDI Extraction Works — Simple Explanation

Imagine you are handed an invoice on paper. It looks like this:

```
From:
Acme Supplies Ltd
123 Market Street

To:
Global Retailers Inc

Invoice No: INV-9901
Date of issue: 15/08/2024

ITEMS:
Widget A | 10 pcs | $50.00 | $500.00
Widget B |  2 pcs | $25.00 |  $50.00

Total: $550.00
```

Here is what happens inside EFDI today:

1. **The OCR Engine (The Scanner):** Reads every word and records its position on the page. It knows `"Acme Supplies Ltd"` is in the top-left, `"Global Retailers Inc"` is in the top-right, and the table has 2 rows.
2. **The Table Builder:** Reconstructs the table into 2 line items: Widget A ($500) and Widget B ($50).
3. **The Disconnect (The Shredder):** Before passing the document to the Extractor, EFDI strips away all 2D boxes and throws the reconstructed table in the trash. It squashes all text into a single long string of text.
4. **The Rule Extractor (The Word Searcher):** The Extractor is given a checklist of ERP keywords:
   - It searches for `"Vendor Name:"` -> Document says `"From:"` -> **NOT FOUND (null)**.
   - It searches for `"Invoice Date:"` -> Document says `"Date of issue:"` -> **NOT FOUND (null)**.
   - It searches for `"Invoice No:"` -> Document says `"Invoice No: INV-9901"` -> **FOUND ("INV-9901")**.
   - It searches for line items -> The schema doesn't even have a place for line items -> **NOT FOUND (null)**.
5. **The Result:** The system reports `"1 of 25 fields found"`, even though the scanner saw every single piece of information.

---

## 21. Current Architectural Strengths

1. **Pluggable Engine Architecture:** Clean abstract base classes (`ExtractionEngine`) and factory patterns (`get_extraction_engine`) allow seamless engine swapping.
2. **Raw Evidence Preservation:** `ocr_results.raw_blocks` is saved immutably as JSONB, preserving bounding boxes and character confidences for future reprocessing.
3. **Non-Destructive Normalization:** Normalizers standardize amounts and dates without discarding raw text citations (`matched_text`).
4. **Classification-Driven Schemas:** Dynamically selecting schema fields based on document type is conceptually sound.
5. **Audit Trail & Training Capture:** User manual corrections are fully logged in `audit_logs` and recorded as `TrainingExample` rows for future supervised ML training.
6. **Multi-Format Exporting:** Built-in clean exports for JSON, CSV, and Excel from a single data source.

---

## 22. Current Architectural Weaknesses

| Severity | Problem | Exact Code Location | Root Cause | Consequence |
|---|---|---|---|---|
| **CRITICAL** | Discarding Upstream Table Data | `ocr_service.py:127-136` | `reconstruct_table()` output stored in local variables only; never passed to extraction. | Line items are never extracted into structured fields. |
| **CRITICAL** | Discarding 2D Spatial Coordinates | `ocr/base.py:35`, `extraction_service.py:54` | `full_text` newline join strips bounding boxes; `ExtractionEngine.extract()` accepts only string. | Positional entities (Seller top-left, Buyer top-right) cannot be identified. |
| **CRITICAL** | ERP-Centric Field Schema | `field_schemas.py:45-178` | Schema defines ERP tokens (`company_code`, `vendor_code`) rather than commercial entities (`seller_name`, `buyer_name`). | Standard invoice fields cannot be represented or extracted. |
| **HIGH** | Rigid Inline Label Regex | `primitives.py:108-115` | `_VALUE_CAPTURE` terminates at `\n` and lacks common synonyms (`"Seller"`, `"Client"`, `"Date of issue"`). | Multiline or alternative labels return `null`. |
| **HIGH** | Lack of Real Invoice Benchmarks | `tests/test_phase6_extraction.py` | Unit tests rely exclusively on synthetic ERP strings. | System passes 100% of test suite while failing on real-world invoices. |
| **MEDIUM** | Inactive LLM Extractor | `llm_extractor.py:92-99` | Inactive without `OPENAI_API_KEY`; silently falls back to rule-based. | LLM capabilities cannot be leveraged in offline environments. |

---

## 23. Extraction Data Flow Matrix

| Component / Subsystem | Input | Output | Consumes Spatial BBoxes? | Consumes Table Line Items? | Consumes Normalized Data? | Consumes Classification? | Consumes LLM? |
|---|---|---|---|---|---|---|---|
| **`EasyOCREngine`** | Image Array | `List[OCRTextBlock]` | Produces | No | No | No | No |
| **`layout.py`** | `List[OCRTextBlock]` | Ordered `List[OCRTextBlock]` | YES | No | No | No | No |
| **`TableReconstructor`** | `raw_blocks` | `ReconstructedTable` | YES | Produces | No | No | No |
| **`normalization.py`** | `ReconstructedTable` | `List[NormalizedLineItem]` | No | YES | Produces | No | No |
| **`RuleBasedClassifier`** | `full_text` | `ClassificationResult` | No | No | No | Produces | No |
| **`ExtractionService`** | `Document` | `ExtractionResult` | **NO (Ignored)** | **NO (Ignored)** | **NO (Ignored)** | YES (`predicted_type`) | Optional |
| **`RuleBasedExtractor`** | `full_text`, `doc_type` | `ExtractionResultData` | **NO** | **NO** | **NO** | YES | No |
| **`LLMBasedExtractor`** | `full_text`, `doc_type` | `ExtractionResultData` | **NO** | **NO** | **NO** | YES | YES |
| **`RAGDiagnosticService`** | `ExtractionResultData` | Refined `ExtractionResultData` | Partial (Chunks) | No | YES (Amount math) | No | Optional |

---

## 24. Final Assessment

1. **What extraction engine runs by default?**  
   `RuleBasedExtractor` (`name="rule_based"`).
2. **What extraction engines exist?**  
   `"rule_based"`, `"llm_based"`, and `"llm_rag"`.
3. **How is the engine selected?**  
   Via request payload parameter `engine` -> `settings.EXTRACTION_DEFAULT_ENGINE` -> `factory.get_extraction_engine()`.
4. **What exact data reaches the default extractor?**  
   Only `ocr_result.full_text` (1D string) and `classification_result.predicted_type` (string).
5. **What important data does it NOT receive?**  
   Bounding boxes, spatial column classifications (Seller Left / Buyer Right), reconstructed line item tables, normalized numerical values, and mathematical validation results.
6. **Where is spatial information lost?**  
   In `OCRPageResult.full_text` (`ocr/base.py:35`) where blocks are joined into a newline string, and in `ExtractionService.extract()` (`extraction_service.py:54`) where only `full_text` is passed.
7. **Where is table information lost?**  
   In `OCRService.run_ocr()` (`ocr_service.py:127-136`) where `reconstruct_table()` is computed as a local variable and never persisted or passed downstream.
8. **What fields can the current schema represent?**  
   15 common metadata fields and ERP-specific fields (`vendor_code`, `po_number`, `grn_number`, `cost_center`, `expense_category`, `department`).
9. **What standard invoice fields cannot be represented?**  
   `seller_name`, `seller_address`, `seller_tax_id` (GSTIN/VAT), `seller_iban`, `buyer_name`, `buyer_address`, `buyer_tax_id`, `subtotal`, `grand_total`, and structured `line_items`.
10. **Why does `invoice_51109301.pdf` currently produce incomplete extraction?**  
    Because labels are multiline (`"Date of issue:\n03/07/2023"`), synonyms are missing (`"Seller:"` instead of `"Vendor Name:"`), table line items are discarded, and schema fields for seller/buyer do not exist.
11. **What role does classification play?**  
    It acts as a hard filter determining which schema and type-extractor function is invoked.
12. **What role does the existing `LLMBasedExtractor` play?**  
    It provides an alternative dynamic Pydantic extraction path using OpenAI JSON schemas, but is inactive without an API key and receives only flat text.
13. **Is the LLM currently default?**  
    **NO.** `RuleBasedExtractor` is the default.
14. **What does the current test suite actually prove?**  
    It proves regex syntax matches synthetic, perfectly formatted label-value strings. It does not prove accuracy on real commercial invoices.
15. **What are the top 5 extraction architecture problems?**  
    1. Table reconstruction output is discarded.  
    2. Spatial bounding boxes are stripped.  
    3. Schemas lack commercial invoice entities.  
    4. Regex primitives fail on multiline labels.  
    5. Zero real-document test coverage.

---

## 25. Evidence & Source Locations

| Fact / Finding | Source File & Line Number |
|---|---|
| Default engine setting (`"rule_based"`) | `backend/app/core/config.py:68` |
| Factory singleton dispatch | `backend/app/extraction/factory.py:15-28` |
| Bounding boxes stripped into `full_text` | `backend/app/ocr/base.py:34-35` |
| Table reconstruction discarded as local var | `backend/app/services/ocr_service.py:127-136` |
| Extraction service passing only flat text | `backend/app/services/extraction_service.py:54` |
| 83 Known stop-labels array | `backend/app/extraction/primitives.py:38-83` |
| Value capture regex definition | `backend/app/extraction/primitives.py:99-116` |
| NPO label definitions missing `"Seller"` | `backend/app/extraction/type_extractors.py:62-74` |
| Schema definitions | `backend/app/extraction/field_schemas.py:45-178` |
| LLM fallback to rule-based when API key missing | `backend/app/extraction/llm_extractor.py:92-99` |
| RAG Diagnostic arithmetic reconciliation | `backend/app/extraction/rag_diagnostic.py:35-64` |
| JSONB persistence of extracted fields | `backend/app/models/extraction_result.py:35` |
| Frontend field table rendering | `frontend/src/components/extraction-fields.tsx:59-105` |
| Synthetic-only extraction test suite | `backend/tests/test_phase6_extraction.py:32-59` |

---

IMPLEMENTATION STATUS: NOT IMPLEMENTED
