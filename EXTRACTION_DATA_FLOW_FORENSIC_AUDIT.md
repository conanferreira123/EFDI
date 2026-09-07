# EFDI — Forensic Audit of Current Extraction Architecture & Data Flow

**Auditor:** Antigravity (Advanced Agentic Assistant)  
**Project Root:** `C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI`  
**Execution Mode:** READ-ONLY Forensic Code Audit (Zero modifications to code, database, schemas, or files)

---

## PART 1 — MAP THE CURRENT EXTRACTION ARCHITECTURE

### Architecture Component Map

The EFDI extraction subsystem conforms to a Clean Architecture model with distinct layer separation:

```
[ HTTP Request ]
       │
       ▼
[ Router Layer ]
  backend/app/routers/extraction.py
       │
       ▼
[ Service Layer ]
  backend/app/services/extraction_service.py
       │
       ├─► [ Data Access / Repositories ]
       │     ├── OCRResultRepository (app/repositories/ocr_result_repository.py)
       │     ├── ClassificationResultRepository (app/repositories/classification_result_repository.py)
       │     ├── DocumentRepository (app/repositories/document_repository.py)
       │     └── ExtractionResultRepository (app/repositories/extraction_result_repository.py)
       │
       ├─► [ Engine Factory ]
       │     backend/app/extraction/factory.py (get_extraction_engine)
       │
       ▼
[ Engine Layer ]
  backend/app/extraction/base.py (ExtractionEngine interface)
       │
       ├──► RuleBasedExtractor (backend/app/extraction/rule_based.py)
       │      ├── Common Fields: extract_common_fields (app/extraction/type_extractors.py)
       │      ├── Per-Type Rules: TYPE_EXTRACTORS (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA)
       │      └── Primitives: extract_by_labels, extract_date_field, extract_amount_field (app/extraction/primitives.py)
       │
       └──► LLMBasedExtractor (backend/app/extraction/llm_extractor.py)
              ├── Dynamic Pydantic Schema: build_dynamic_extraction_model (app/extraction/llm_schema.py)
              ├── Field Definitions: FieldDef, COMMON_FIELDS, DOCUMENT_TYPE_FIELDS (app/extraction/field_schemas.py)
              └── Fallback: RuleBasedExtractor (used if OPENAI_API_KEY is missing or API fails)
       │
       ▼
[ Post-Extraction Diagnostic ]
  backend/app/extraction/rag_diagnostic.py (RAGDiagnosticService)
       │
       ▼
[ Persistence Layer ]
  backend/app/models/extraction_result.py (ExtractionResult table)
       │
       ▼
[ Downstream Validation Layer ]
  backend/app/services/validation_service.py -> app/validation/engine.py -> app/models/validation_result.py
```

### Component Details Table

| Component | File Path | Class / Function | Responsibility | Input | Output | Caller | Downstream Dependency |
|---|---|---|---|---|---|---|---|
| **Router** | `app/routers/extraction.py` | `extract_document_fields` | HTTP POST endpoint (`/api/v1/extraction/documents/{id}/extract`) | `document_id: int`, `ExtractRequest` | `ExtractionResultResponse` | Client / Web UI | `DocumentService`, `ExtractionService`, `AuditService` |
| **Service** | `app/services/extraction_service.py` | `ExtractionService.extract` | Orchestrates extraction flow, fetches OCR & classification, invokes engine, saves result, updates document status | `document: Document`, `engine_name: str \| None` | `ExtractionResult` | `app/routers/extraction.py` | `OCRResultRepository`, `ClassificationResultRepository`, `get_extraction_engine`, `ExtractionResultRepository`, `DocumentRepository` |
| **Factory** | `app/extraction/factory.py` | `get_extraction_engine` | Returns singleton engine instance (`rule_based`, `llm_based`, `llm_rag`) | `engine_name: str` | `ExtractionEngine` | `ExtractionService` | `RuleBasedExtractor`, `LLMBasedExtractor` |
| **Interface** | `app/extraction/base.py` | `ExtractionEngine.extract` | Abstract base method contract | `text: str`, `document_type: str` | `ExtractionResultData` | `ExtractionService` | `RuleBasedExtractor`, `LLMBasedExtractor` |
| **Rule Extractor** | `app/extraction/rule_based.py` | `RuleBasedExtractor.extract` | Dispatches to per-document-type extractors + common field extractors | `text: str`, `document_type: str` | `ExtractionResultData` | `ExtractionService` | `app/extraction/type_extractors.py` |
| **Type Rules** | `app/extraction/type_extractors.py` | `extract_poi_fields`, etc. | Executes label-based pattern matching per document type | `text: str` | `dict[str, ExtractedField]` | `RuleBasedExtractor` | `app/extraction/primitives.py` |
| **Primitives** | `app/extraction/primitives.py` | `extract_by_labels`, `normalize_date`, `normalize_amount` | Regex token capture and data normalization | `text: str`, `labels: list[str]` | `ExtractedField`, `str \| None` | `app/extraction/type_extractors.py` | Python `re`, `datetime` |
| **LLM Extractor** | `app/extraction/llm_extractor.py` | `LLMBasedExtractor.extract` | Builds dynamic schema, creates prompt, invokes OpenAI API, normalizes response | `text: str`, `document_type: str` | `ExtractionResultData` | `ExtractionService` | `app/extraction/llm_schema.py`, `app/extraction/field_schemas.py` |
| **RAG Diagnostic** | `app/extraction/rag_diagnostic.py` | `RAGDiagnosticService.diagnose_and_refine` | Post-extraction check on arithmetic balance / confidence triggers | `document_id: int`, `ExtractionResultData`, `page_count` | `ExtractionResultData` | `ExtractionService` | `app/models/document_chunk.py` |
| **Repository** | `app/repositories/extraction_result_repository.py` | `ExtractionResultRepository.create` | Persists extraction result row | `document_id`, `document_type`, `fields: dict`, etc. | `ExtractionResult` | `ExtractionService` | SQLAlchemy Session |
| **Model** | `app/models/extraction_result.py` | `ExtractionResult` | ORM table definition for `extraction_results` | DB row data | `ExtractionResult` | SQLAlchemy ORM | `documents` table |

---

## PART 2 — TRACE THE OCR OUTPUT

### A. Trace of `full_text`
1. **Creation Point:** `backend/app/ocr/base.py` (`OCRPageResult.full_text` and `OCRResult.full_text`).
2. **Responsible Component:** In `OCRService.run_ocr` (`backend/app/services/ocr_service.py`, lines 94–118):
   - Engine produces `raw_extracted_blocks: list[OCRTextBlock]`.
   - `ordered_blocks = order_blocks_spatially(raw_extracted_blocks, page_width=page_w, page_height=page_h)` (`app/ocr/layout.py`).
   - Blocks are segmented into 3 vertical bands (Top Metadata, 2-Column Party Information [Seller left, Buyer right], and Body/Table).
   - `OCRPageResult(page_number=page_number, blocks=ordered_blocks)`.
   - `OCRPageResult.full_text` is evaluated as `"\n".join(block.text for block in self.blocks)`.
   - `OCRResultData.full_text` concatenates pages: `"\n\n".join(page.full_text for page in self.pages)`.
3. **Transformations Applied:** Spatial reading-order sorting only (multiline concatenation).
4. **Final Python Type:** `str` (UTF-8).
5. **Persistence Path:** Passed to `OCRResultRepository.create(full_text=result_data.full_text)` -> stored in column `ocr_results.full_text` (`Text` column in PostgreSQL).

### B. Trace of `raw_blocks`
1. **Creation Point:** `backend/app/services/ocr_service.py` (lines 98–110).
2. **Responsible Component:** `OCRService.run_ocr` inside the per-page loop iterating over `preprocessed_pages`.
3. **Exact Python Data Structure Produced:**
```python
[
    {
        "page_number": 1,
        "page_width": 1240.0,
        "page_height": 1754.0,
        "blocks": [
            {
                "text": "TAX INVOICE",
                "confidence": 0.985,
                "bounding_box": [
                    [450.0, 50.0],
                    [790.0, 50.0],
                    [790.0, 95.0],
                    [450.0, 95.0]
                ]
            }
        ]
    }
]
```
4. **Structural Properties Confirmed from Code:**
   - **Page-level structure:** `dict` with keys `"page_number"` (`int`), `"page_width"` (`float`), `"page_height"` (`float`), and `"blocks"` (`list[dict]`).
   - **Block-level structure:** `dict` with keys `"text"` (`str`), `"confidence"` (`float`), and `"bounding_box"` (`list[list[float]]`).
   - **Bounding box:** 4-vertex polygon coordinate array `[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]` representing pixel coordinates on the preprocessed page image.
   - **Ordering in `raw_blocks`:** Unordered engine-native output (preserved verbatim as emitted by OCR engine before spatial sorting).

---

## PART 3 — TRACE DATABASE PERSISTENCE

### Database Column Types (`app/models/ocr_result.py` lines 31–40):
- `full_text`: `Mapped[str] = mapped_column(Text, nullable=False, default="")` (PostgreSQL type `TEXT`).
- `raw_blocks`: `Mapped[list] = mapped_column(JSONB, nullable=False, default=list)` (PostgreSQL type `JSONB`).

### Persistence & Retrieval Mechanics:
1. **Write (OCR → PostgreSQL):**
   - Object passed to repository: Plain Python `list[dict]`.
   - SQLAlchemy `JSONB` type handler natively handles JSON serialization using `json.dumps()` during the SQL `INSERT` statement generation. No manual `json.dumps()` is called in application code.
2. **Read (PostgreSQL → Application):**
   - When `OCRResultRepository.get_latest_for_document(document_id)` executes `select(OCRResult)...`, psycopg2 / asyncpg and SQLAlchemy's `JSONB` type processor deserialize the database JSON binary data directly into a **standard Python `list` of `dict` objects**.
3. **No Intermediate Custom Class:** The deserialized object is a standard built-in Python `list` (e.g. `[{"page_number": 1, ...}]`). It is **NOT** automatically instantiated into `OCRTextBlock` or `OCRPageResult` instances upon retrieval from the database.

---

## PART 4 — JSONB VS APPLICATION-LEVEL PARSING

A critical architectural distinction exists between **storage serialization** and **application-level structural parsing**:

```
[ PostgreSQL JSONB ]
        │
        │ (SQLAlchemy deserializes JSON bytes)
        ▼
[ Python list[dict] in memory ]
        │
        ├──► Does an explicit application parser exist here for extraction?
        │    ──► NO.
        │
        └──► Does a serializer to convert list[dict] into LLM context exist?
             ──► NO.
```

### Forensic Code Search Results:
- **`model_validate`:** Used only on API request/response schemas and inside `LLMBasedExtractor` to validate the OpenAI JSON output (`DynamicModel.model_validate(raw_response)`). Never used on `raw_blocks`.
- **`json.loads` / `json.dumps`:** Used for API export formatting (`GET /documents/{id}/export`), OpenAI API payloads, and audit logging. Never used for parsing `raw_blocks`.
- **Custom Block Parsers / Formatters:** None exist in `backend/app/extraction/` or `backend/app/services/`.

---

## PART 5 — COMPLETE raw_blocks FUNCTION INVENTORY

| File | Function / Class | Uses `raw_blocks`? | Reads Only? | Transforms? | Output | Called by Extraction? | Production? | Classification Category |
|---|---|---|---|---|---|---|---|---|
| `app/models/ocr_result.py` | `OCRResult` | YES | N/A | NO | Model class | NO | YES | 1. Storage/access only |
| `app/repositories/ocr_result_repository.py` | `create` | YES | NO (writes) | NO | `OCRResult` | NO | YES | 1. Storage/access only |
| `app/repositories/ocr_result_repository.py` | `get_latest_for_document` | YES | YES | NO | `OCRResult` | YES (Loads object, ignores field) | YES | 1. Storage/access only |
| `app/services/ocr_service.py` | `OCRService.run_ocr` | YES | NO (creates) | Builds list | `OCRResult` | NO | YES | 1. Storage/access only |
| `app/ocr/layout.py` | `order_blocks_spatially` | NO (Takes `list[OCRTextBlock]`) | YES | YES (reorders) | `list[OCRTextBlock]` | NO | YES | 4. Spatial/layout processing |
| `app/ocr/table_reconstruction.py` | `TableReconstructor.reconstruct` | YES (Takes `blocks` dict/obj) | YES | YES (groups rows/cols) | `ReconstructedTable` | NO | YES | 5. Table reconstruction |
| `app/ocr/table_reconstruction.py` | `reconstruct_table` | YES | YES | YES | `ReconstructedTable` | NO | YES | 5. Table reconstruction |
| `app/ocr/normalization.py` | `normalize_table_data` | Indirect (Reads table dict) | YES | YES (types values) | `list[NormalizedLineItem]` | NO | YES | 6. Normalization |
| `app/ocr/normalization.py` | `normalize_line_item` | Indirect | YES | YES | `NormalizedLineItem` | NO | YES | 6. Normalization |
| `app/ocr/validation.py` | `validate_ocr_output` | NO | YES | Checks arithmetic | `OCRValidationResult` | NO | YES | 10. Other (OCR validation) |
| `app/ocr/quality_scoring.py` | `calculate_quality_score` | NO | YES | Computes grade | `QualityBreakdown` | NO | YES | 10. Other (OCR QA) |
| `app/routers/ocr.py` | `_to_response` | YES (`raw_blocks[0]`) | YES | Runs table recon on fly | `OCRResultResponse` | NO | YES | 2. Serialization |
| `app/schemas/ocr.py` | `OCRResultResponse` | YES | YES | Exposed as untyped list | Pydantic model | NO | YES | 2. Serialization |
| `app/services/extraction_service.py` | `ExtractionService.extract` | NO (Ignores field) | NO | NO | `ExtractionResult` | Target service | YES | 1. Storage/access only |
| `app/extraction/base.py` | `ExtractionEngine.extract` | NO | NO | NO | `ExtractionResultData` | Target interface | YES | 8. Semantic extraction |
| `app/extraction/rule_based.py` | `RuleBasedExtractor.extract` | NO | NO | NO | `ExtractionResultData` | Target engine | YES | 8. Semantic extraction |
| `app/extraction/llm_extractor.py` | `LLMBasedExtractor.extract` | NO | NO | NO | `ExtractionResultData` | Target engine | YES | 8. Semantic extraction & 9. LLM Context |

---

## PART 6 — DETERMINE WHETHER A RAW_BLOCKS PARSER EXISTS

### Explicit Forensic Answer:
**A dedicated general-purpose `raw_blocks` parser DOES NOT EXIST in the production codebase.**

Specifically:
- **`raw_blocks → ordered blocks`:** Handled upstream on `OCRTextBlock` objects inside `app/ocr/layout.py`, but the output is flattened to `full_text` before persistence.
- **`raw_blocks → rows / columns`:** Partially exists in `app/ocr/table_reconstruction.py` (`TableReconstructor`), but operates only on page 0 line items and is completely isolated within the OCR module.
- **`raw_blocks → key/value relationships`:** **DOES NOT EXIST.**
- **`raw_blocks → structured document context`:** **DOES NOT EXIST.**
- **`raw_blocks → readable text (layout-aware)`:** **DOES NOT EXIST.**
- **`raw_blocks → LLM context`:** **DOES NOT EXIST.**

---

## PART 7 — INSPECT EXISTING LAYOUT PROCESSING

Located in `backend/app/ocr/layout.py`:
- **Function:** `order_blocks_spatially(blocks: List[OCRTextBlock], page_width: float, page_height: float) -> List[OCRTextBlock]`
- **Input:** Receives in-memory `OCRTextBlock` instances directly from OCR engine inference.
- **Does it receive `raw_blocks`?** No, it receives `list[OCRTextBlock]` before `raw_blocks` is assembled.
- **Operations Performed:**
  - Computes bounding box centers `cx, cy` and boundaries `min_x, max_x, min_y, max_y`.
  - Dynamically detects the table header boundary (`table_y_start`) and party boundary (`top_meta_end_y`).
  - Groups blocks into:
    1. Top Metadata (Y-band sorting).
    2. Party Information (Split vertically at `page_width * 0.5`: left column Seller, right column Buyer).
    3. Body & Table (Y-band row sorting).
- **Output:** Returns a 1D reordered list of `OCRTextBlock`.
- **Is output persisted?** Its text contents are concatenated into `OCRResult.full_text`. The spatial band metadata is discarded.
- **Is it called by extraction?** **No.**

---

## PART 8 — INSPECT TABLE RECONSTRUCTION

Located in `backend/app/ocr/table_reconstruction.py`:
- **Class / Function:** `TableReconstructor.reconstruct()` / `reconstruct_table(blocks, page_width, page_height)`
- **Input:** Accepts list of block dicts or `OCRTextBlock` instances for a single page.
- **Output:** `ReconstructedTable` dataclass containing:
  - `headers: list[str]`
  - `columns: dict[str, dict[str, float]]` (horizontal intervals `x_min`, `x_max`)
  - `line_items: list[StructuredLineItem]` (`item_number`, `description`, `quantity`, `unit`, `unit_price`, `net_amount`, `vat_rate`, `gross_amount`, `confidence`, `raw_blocks`)
- **Key Characteristics:**
  - Bounding boxes used: **Yes** (clustering tolerance `y_tolerance = 16.0px`).
  - Confidence preserved: **Yes** (averages confidence across constituent cell blocks).
  - Multiline descriptions merged: **Yes** (continuation lines lacking numeric data are appended to `current_item.description`).
- **Caller Chain:**
  ```
  OCRService.run_ocr()
     ↓
  reconstruct_table(raw_blocks[0]["blocks"])
     ↓
  table_obj.to_dict()
     ↓
  calculate_quality_score(...) & AuditService.log(...)
  ```
- **Does Extraction consume this output?** **NO.** `ExtractionService` has zero references to `TableReconstructor` or `reconstruct_table`.

---

## PART 9 — TRACE full_text INTO EXTRACTION

```
1. OCR Inference
   app/services/ocr_service.py (L94-118)
   └── order_blocks_spatially() -> OCRPageResult.full_text -> OCRResultData.full_text
       Input: list[OCRTextBlock] | Output: str

2. Database Persistence
   app/repositories/ocr_result_repository.py (L40-56)
   └── OCRResultRepository.create(full_text=result_data.full_text)
       Input: str | Output: DB Row (ocr_results.full_text)

3. Database Retrieval
   app/services/extraction_service.py (L36)
   └── ocr_result = self.ocr_repo.get_latest_for_document(document.id)
       Output: ocr_result.full_text (exact same str)

4. Service to Engine Dispatch
   app/services/extraction_service.py (L54)
   └── result_data = engine.extract(ocr_result.full_text, document_type)
       Input: text: str, document_type: str

5. Engine Execution
   app/extraction/rule_based.py (L24) / app/extraction/llm_extractor.py (L75)
   └── extract(text, document_type)
       Input: text: str | Output: ExtractionResultData

6. Result Persistence
   app/repositories/extraction_result_repository.py (L34-57)
   └── ExtractionResultRepository.create(document_id, document_type, fields, ...)
```

**Answer:** Extraction receives the **exact verbatim `full_text` string** that was constructed during OCR and persisted to PostgreSQL. No intermediate transformations are applied between DB read and engine input.

---

## PART 10 — TRACE raw_blocks INTO EXTRACTION

```
1. OCR Inference & Block Extraction
   app/services/ocr_service.py (L94)
   └── raw_extracted_blocks = engine.extract_text_blocks(page_image)
       RAW_BLOCKS = YES (list[OCRTextBlock])

2. raw_blocks In-Memory Assembly
   app/services/ocr_service.py (L98-110)
   └── raw_blocks.append({"page_number": ..., "blocks": [...]})
       RAW_BLOCKS = YES (list[dict])

3. Database Persistence
   app/repositories/ocr_result_repository.py (L51)
   └── OCRResultRepository.create(..., raw_blocks=raw_blocks, ...)
       RAW_BLOCKS = YES (Stored in PostgreSQL ocr_results.raw_blocks as JSONB)

4. Database Retrieval
   app/services/extraction_service.py (L36)
   └── ocr_result = self.ocr_repo.get_latest_for_document(document.id)
       RAW_BLOCKS = YES (Loaded in Python memory as ocr_result.raw_blocks)

5. Extraction Invocator
   app/services/extraction_service.py (L54)
   └── result_data = engine.extract(ocr_result.full_text, document_type)
       RAW_BLOCKS = NO (DATA FLOW TERMINATES HERE)

6. ExtractionEngine Base Interface
   app/extraction/base.py (L70)
   └── extract(self, text: str, document_type: str)
       RAW_BLOCKS = NO

7. RuleBasedExtractor
   app/extraction/rule_based.py (L24)
   └── extract(self, text: str, document_type: str)
       RAW_BLOCKS = NO

8. LLMBasedExtractor
   app/extraction/llm_extractor.py (L75)
   └── extract(self, text: str, document_type: str)
       RAW_BLOCKS = NO
```

**Explicit Finding:** `raw_blocks` is loaded from the database into the `ocr_result` model instance in memory at line 36 of `extraction_service.py`, but **is never passed to `engine.extract()`**. The data flow stops entirely at `extraction_service.py:54`.

---

## PART 11 — INSPECT ExtractionService

Inspecting `backend/app/services/extraction_service.py` (lines 35–62):

```python
def extract(self, document: Document, *, engine_name: str | None = None):
    ocr_result = self.ocr_repo.get_latest_for_document(document.id)
    if not ocr_result:
        raise ValidationFailedException("Cannot extract fields from a document with no OCR result.")

    classification_result = self.classification_repo.get_latest_for_document(document.id)
    if not classification_result:
        raise ValidationFailedException("Cannot extract fields from a document with no classification result.")

    document_type = classification_result.predicted_type
    chosen_engine = engine_name or getattr(settings, "EXTRACTION_DEFAULT_ENGINE", "rule_based")

    engine = get_extraction_engine(chosen_engine)
    result_data = engine.extract(ocr_result.full_text, document_type)  # <--- ONLY full_text and document_type PASSED

    if chosen_engine in ("llm_rag", "llm_based"):
        page_count = ocr_result.page_count or 1
        result_data = self.rag_diagnostic.diagnose_and_refine(
            document.id, result_data, page_count=page_count
        )
    ...
```

- **Retrieved from DB:** `ocr_result` (including `full_text`, `raw_blocks`, `page_count`, `average_confidence`) and `classification_result` (including `predicted_type`).
- **Passed to Engine:** `ocr_result.full_text` (`str`) and `document_type` (`str`).
- **Status of `raw_blocks`:** Present on the `ocr_result` object in memory, but completely ignored and not passed into `engine.extract()`.

---

## PART 12 — INSPECT ExtractionEngine INTERFACE

Inspecting `backend/app/extraction/base.py` (lines 57–71):

```python
class ExtractionEngine(ABC):
    name: str = "base"

    @abstractmethod
    def extract(self, text: str, document_type: str) -> ExtractionResultData:
        raise NotImplementedError
```

### Signature Verification Across Implementations:
1. `RuleBasedExtractor.extract(self, text: str, document_type: str) -> ExtractionResultData` (`app/extraction/rule_based.py:24`) -> **Matches exact signature.**
2. `LLMBasedExtractor.extract(self, text: str, document_type: str) -> ExtractionResultData` (`app/extraction/llm_extractor.py:75`) -> **Matches exact signature.**

---

## PART 13 — INSPECT RuleBasedExtractor

Inspecting `backend/app/extraction/rule_based.py`, `type_extractors.py`, and `primitives.py`:
- **Input Received:** Only `text: str` and `document_type: str`.
- **Operation:**
  - Looks up document type extractor in `TYPE_EXTRACTORS: dict[str, Callable]`.
  - Runs `extract_common_fields(text)`.
  - Runs `extract_poi_fields(text)`, `extract_bka_fields(text)`, etc.
  - Pattern matching uses `extract_by_labels()` with regex `_VALUE_CAPTURE` stopping at `KNOWN_LABELS` boundaries or newlines.
  - Normalization uses `normalize_date()` (16 date regexes) and `normalize_amount()` (comma stripping & float parsing).
- **Geometric / Layout Awareness:** **ZERO.** No bounding boxes, no coordinates, no spatial proximity, no column intervals, and no table structures are used. It is a strictly 1D sequential regex engine.

---

## PART 14 — INSPECT LLMBasedExtractor

Inspecting `backend/app/extraction/llm_extractor.py`:

1. **Method Signature:** `extract(self, text: str, document_type: str) -> ExtractionResultData`
2. **Arguments Received:** `text` (`str`), `document_type` (`str`).
3. **Prompt Construction:**
   ```python
   system_prompt = (
       f"You are an enterprise financial document extraction model.\n"
       f"Extract all schema fields for document type '{document_type}' from the provided OCR text.\n"
       f"For every field found, provide the extracted value, a confidence score between 0.0 and 1.0, "
       f"and the exact verbatim text snippet (source_quote) from the document as proof.\n"
       f"If a field is not present in the document text, return null for its value."
   )
   user_prompt = f"DOCUMENT OCR TEXT:\n\"\"\"\n{text}\n\"\"\""
   ```
4. **Data Sent to LLM:** `system_prompt`, `user_prompt` (with raw text), and dynamic JSON Schema derived from Pydantic `FieldDef` models.
5. **Presence of Structural Data:**
   - `full_text` sent: **YES**
   - `raw_blocks` sent: **NO**
   - `document_type` sent: **YES**
   - `bounding_boxes` sent: **NO**
   - `reconstructed_tables` sent: **NO**
   - `layout information` sent: **NO**
6. **Structured Output Enforcement:** Uses OpenAI Structured Outputs via `"response_format": {"type": "json_schema", "json_schema": {...}}`.
7. **Validation:** Validated via `DynamicModel.model_validate(raw_response)` followed by deterministic date/amount normalization.
8. **Factory Path:** Registered in `app/extraction/factory.py` under names `"llm_based"` and `"llm_rag"`. (Default engine remains `"rule_based"`).

---

## PART 15 — WHAT THE LLM WOULD RECEIVE TODAY

| Data Field | Available in `OCRResult`? | Retrieved by `ExtractionService`? | Passed to Extractor? | Passed to LLM? | Forensic Evidence / Rationale |
|---|---|---|---|---|---|
| `full_text` | **YES** | **YES** | **YES** | **YES** | Injected directly into `user_prompt` in `llm_extractor.py:109` |
| `raw_blocks` | **YES** | **YES** | **NO** | **NO** | Discarded at `extraction_service.py:54` |
| `document_type` | **YES** (via Classification) | **YES** | **YES** | **YES** | Injected into `system_prompt` and used to build JSON schema |
| `classification result` | **YES** | **YES** (only `predicted_type`) | **NO** | **NO** | Confidence & signals discarded |
| `OCR confidence` | **YES** | **NO** | **NO** | **NO** | Not passed to extractor |
| `page metadata` | **YES** | **YES** (page count) | **NO** | **NO** | Used only in RAG diagnostic trigger check |
| `bounding boxes` | **YES** (inside `raw_blocks`) | **YES** | **NO** | **NO** | Discarded before engine call |
| `reconstructed tables` | **NO** (memory-only in OCR) | **NO** | **NO** | **NO** | Not persisted or queried |
| `normalized OCR data` | **NO** (memory-only in OCR) | **NO** | **NO** | **NO** | Not persisted or queried |
| `document metadata` | **YES** | **YES** (document ID) | **NO** | **NO** | Used only for DB record association |

---

## PART 16 — IS raw_blocks ALREADY "READABLE"?

| Representation Level | Currently Exists? | Where in Codebase? | Exact Implementation / Description |
|---|---|---|---|
| **PostgreSQL JSONB** | **YES** | `ocr_results.raw_blocks` | Stored as binary JSONB in PostgreSQL |
| **Python dict/list** | **YES** | `app/services/ocr_service.py:98` | In-memory `list[dict]` deserialized by SQLAlchemy |
| **OCR block objects** | **YES** | `app/ocr/base.py:18` | `OCRTextBlock(text, confidence, bounding_box)` |
| **Ordered blocks** | **YES** | `app/ocr/layout.py:33` | 1D sorted `list[OCRTextBlock]` (layout bands discarded) |
| **Plain readable text** | **YES** | `app/ocr/base.py:52` | `OCRResult.full_text` string |
| **Structured layout** | **NO** | N/A | No structured multi-band layout representation exists |
| **Reconstructed table** | **YES (OCR only)** | `app/ocr/table_reconstruction.py:34` | `ReconstructedTable` dataclass (line items for page 0) |
| **LLM-ready context** | **NO** | N/A | No layout serializer or prompt adapter exists |

---

## PART 17 — DOES JSONB NEED "PARSING"?

1. **JSONB to Python:** **Already handled.** SQLAlchemy automatically deserializes PostgreSQL JSONB into a native Python `list[dict]`. No manual `json.loads()` is needed.
2. **Direct Pass to LLM:** If `raw_blocks` (the raw Python `list[dict]`) were directly serialized to JSON via `json.dumps()` and injected into an LLM prompt, it would technically be valid JSON, but it would contain massive token overhead (thousands of raw pixel coordinates `[[450.0, 50.0], ...]`).
3. **Application Transformation Requirement:** The current codebase **does not require a JSON parser**, but **does require a Layout-to-Context Adapter** to condense coordinate arrays into concise, structured representations (e.g., Markdown tables, spatial reading bands, or header-value groupings) to avoid prompt bloat and coordinate hallucination.

---

## PART 18 — INSPECT LLM PROMPT BUILDING

### Search across all prompt-building logic in the repository:
- `backend/app/extraction/llm_extractor.py` (lines 101–110): System prompt + `DOCUMENT OCR TEXT:\n"""\n{text}\n"""`.
- `backend/app/extraction/rag_diagnostic.py` (lines 116–120): Uses `DocumentChunk.content` (plain text string chunks) for post-extraction reconciliation.

**Forensic Finding:** **No existing production raw_blocks → LLM context transformation was found.**

---

## PART 19 — TEST COVERAGE

| Test Suite File | Tests Count | `raw_blocks` Exercised? | Real or Synthetic? | Notes / Gaps |
|---|---|---|---|---|
| `tests/test_phase6_extraction.py` | 22 tests | **NO** | N/A | Helper `_inject_ocr_text()` explicitly injects `raw_blocks=[]`. All tests use synthetic text strings. |
| `tests/test_hybrid_llm_extraction.py` | 5 tests | **NO** | Mocks | Tests mock `_call_llm_api` with sample JSON dictionaries. No layout data tested. |
| `tests/test_ocr_table_reconstruction.py` | 7 tests | **YES** | Synthetic `OCRTextBlock` | Tests `TableReconstructor` bounding-box clustering in isolation. |
| `tests/test_ocr_normalization.py` | 8 tests | **YES** | Synthetic `StructuredLineItem` | Tests line-item float/date normalizers in isolation. |
| `tests/test_phase5_classification.py` | 22 tests | **NO** | N/A | Classification tests inject `raw_blocks=[]`. |

---

## PART 20 — CHECK FOR EXPERIMENTAL / DELETED / UNUSED CODE

1. **Classification `raw_blocks` Experiment:** Confirmed completely cleaned up. All classification paths (`ClassificationService`, `RuleBasedClassifier`) consume strictly `full_text`.
2. **Stranded OCR Modules:** `TableReconstructor` (`app/ocr/table_reconstruction.py`) and `normalize_table_data` (`app/ocr/normalization.py`) are fully functional and tested, but are currently isolated within the OCR lifecycle and unused by extraction.

---

## PART 21 — ACTUAL DATA-FLOW DIAGRAMS

### DIAGRAM A — `full_text` Data Flow (Active Production Path)

```
+--------------------------------------------------------------------+
|                         Uploaded Document                          |
+--------------------------------------------------------------------+
                                  │
                                  ▼
+--------------------------------------------------------------------+
| OCRService.run_ocr() [backend/app/services/ocr_service.py]         |
| 1. engine.extract_text_blocks() -> raw_extracted_blocks            |
| 2. order_blocks_spatially()     -> ordered_blocks                  |
| 3. OCRPageResult.full_text      -> "\n".join(b.text)               |
| 4. OCRResultData.full_text      -> "\n\n".join(p.full_text)        |
+--------------------------------------------------------------------+
                                  │
                                  ▼ (full_text: str)
+--------------------------------------------------------------------+
| OCRResultRepository.create() [app/repositories/ocr_result_repo.py] |
| Persists to PostgreSQL table `ocr_results`, column `full_text`     |
+--------------------------------------------------------------------+
                                  │
                                  ▼ (full_text: str)
+--------------------------------------------------------------------+
| ExtractionService.extract() [app/services/extraction_service.py]   |
| 1. ocr_result = ocr_repo.get_latest_for_document(id)               |
| 2. text = ocr_result.full_text                                     |
+--------------------------------------------------------------------+
                                  │
                                  ▼ (text: str)
+--------------------------------------------------------------------+
| ExtractionEngine.extract() [backend/app/extraction/base.py]        |
+--------------------------------------------------------------------+
              │                                      │
              ▼ (text: str)                          ▼ (text: str)
+-------------------------------+      +-------------------------------+
| RuleBasedExtractor            |      | LLMBasedExtractor             |
| [app/extraction/rule_based.py]|      | [app/extraction/llm_extractor]|
| - extract_by_labels(text)     |      | - prompt: """{text}"""        |
| - normalize_date / amount     |      | - _call_llm_api(...)          |
+-------------------------------+      +-------------------------------+
              │                                      │
              └───────────────────┬──────────────────┘
                                  ▼ (ExtractionResultData)
+--------------------------------------------------------------------+
| ExtractionResultRepository.create() -> `extraction_results` (DB)   |
+--------------------------------------------------------------------+
```

### DIAGRAM B — `raw_blocks` Data Flow (Current Disconnect)

```
+--------------------------------------------------------------------+
|                         Uploaded Document                          |
+--------------------------------------------------------------------+
                                  │
                                  ▼
+--------------------------------------------------------------------+
| OCRService.run_ocr() [backend/app/services/ocr_service.py]         |
| 1. engine.extract_text_blocks() -> raw_extracted_blocks            |
| 2. Builds Python list[dict]:                                       |
|    [ {page_number, page_width, page_height, blocks:[...]} ]        |
+--------------------------------------------------------------------+
                                  │
                                  ▼ (list[dict])
+--------------------------------------------------------------------+
| OCRResultRepository.create() [app/repositories/ocr_result_repo.py] |
| Persists to PostgreSQL table `ocr_results`, column `raw_blocks`    |
| (Type: JSONB)                                                      |
+--------------------------------------------------------------------+
                                  │
                                  ▼ (SQLAlchemy deserializes to list[dict])
+--------------------------------------------------------------------+
| ExtractionService.extract() [app/services/extraction_service.py]   |
| ocr_result = ocr_repo.get_latest_for_document(id)                  |
| -> ocr_result.raw_blocks is in memory                              |
+--------------------------------------------------------------------+
                                  │
                                  ├───► [ STOP: raw_blocks DISCARDED ]
                                  │     (Never passed to engine.extract)
                                  ▼
+--------------------------------------------------------------------+
| ExtractionEngine / RuleBasedExtractor / LLMBasedExtractor          |
| (Receives NO raw_blocks)                                           |
+--------------------------------------------------------------------+
```

---

## PART 22 — FUNCTION / CALL-GRAPH VIEW

```
OCR Pipeline Call Graph:
─────────────────────────
OCRService.run_ocr(document, engine_name)
  ├── engine.extract_text_blocks(page_image)               [Paddle/EasyOCR]
  ├── order_blocks_spatially(raw_extracted_blocks)         [app/ocr/layout.py]
  ├── reconstruct_table(raw_blocks[0]["blocks"])           [app/ocr/table_reconstruction.py]
  │     └── TableReconstructor.reconstruct()
  ├── normalize_table_data(table_dict)                     [app/ocr/normalization.py]
  ├── validate_ocr_output(normalized_items, full_text)     [app/ocr/validation.py]
  ├── calculate_quality_score(...)                         [app/ocr/quality_scoring.py]
  └── OCRResultRepository.create(full_text, raw_blocks)    [app/repositories/ocr_result_repo.py]
        └── INSERT into `ocr_results` (full_text: TEXT, raw_blocks: JSONB)

Extraction Pipeline Call Graph:
───────────────────────────────
router.extract_document_fields(document_id)                [app/routers/extraction.py]
  └── ExtractionService.extract(document, engine_name)     [app/services/extraction_service.py]
        ├── OCRResultRepository.get_latest_for_document()  --> loads full_text AND raw_blocks
        ├── ClassificationResultRepository.get_latest...() --> loads predicted_type
        ├── get_extraction_engine(chosen_engine)           [app/extraction/factory.py]
        │
        ├── RuleBasedExtractor.extract(full_text, doc_type)[app/extraction/rule_based.py]
        │     ├── extract_common_fields(full_text)         [app/extraction/type_extractors.py]
        │     │     └── extract_by_labels(full_text)       [app/extraction/primitives.py]
        │     └── TYPE_EXTRACTORS[doc_type](full_text)
        │
        ├── LLMBasedExtractor.extract(full_text, doc_type) [app/extraction/llm_extractor.py]
        │     ├── build_dynamic_extraction_model(doc_type) [app/extraction/llm_schema.py]
        │     ├── _call_llm_api(system_prompt, user_prompt)[LLM API POST request]
        │     └── DynamicModel.model_validate(raw_response)
        │
        ├── RAGDiagnosticService.diagnose_and_refine(...)  [app/extraction/rag_diagnostic.py]
        │     └── DocumentChunk SELECT (plain text chunks)
        │
        ├── ExtractionResultRepository.create(...)         [app/repositories/extraction_result_repo.py]
        │     └── INSERT into `extraction_results` (fields: JSONB)
        │
        └── DocumentRepository.update_status("EXTRACTED")  [app/repositories/document_repo.py]
```

---

## PART 23 — CRITICAL FINAL QUESTIONS (Q1 – Q22)

### Q1: Where exactly is `full_text` created?
**Answer:** In `backend/app/ocr/base.py` (line 53 via `OCRResult.full_text` property), joining page texts produced by `order_blocks_spatially()` inside `OCRService.run_ocr` (`backend/app/services/ocr_service.py:116`).

### Q2: Where exactly is `raw_blocks` created?
**Answer:** In `backend/app/services/ocr_service.py` (lines 98–110), inside the page loop of `OCRService.run_ocr`.

### Q3: What is the exact Python structure of raw_blocks?
**Answer:** A Python `list[dict]` where each element is:
`{"page_number": int, "page_width": float, "page_height": float, "blocks": [{"text": str, "confidence": float, "bounding_box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]}]}`.

### Q4: Where exactly is raw_blocks persisted?
**Answer:** In PostgreSQL table `ocr_results`, column `raw_blocks` via `OCRResultRepository.create()` (`backend/app/repositories/ocr_result_repository.py:51`).

### Q5: What database type is used for raw_blocks?
**Answer:** PostgreSQL `JSONB` (`Mapped[list] = mapped_column(JSONB, nullable=False, default=list)` in `backend/app/models/ocr_result.py:40`).

### Q6: When raw_blocks is read from PostgreSQL, what Python object does the application receive?
**Answer:** A standard native Python `list[dict]`, automatically deserialized by SQLAlchemy.

### Q7: Is there an explicit JSONB → Python parser?
**Answer:** **No.** SQLAlchemy/psycopg2 handles deserialization automatically. No custom application deserializer is invoked.

### Q8: Is there an explicit raw_blocks parser?
**Answer:** **No.** There is no general-purpose parser that converts multi-page `raw_blocks` into document-level structured extraction context.

### Q9: Is there an existing function that transforms raw_blocks into another structured representation?
**Answer:** **Yes (in OCR layer only).** `app.ocr.table_reconstruction.TableReconstructor.reconstruct()` converts single-page blocks into `ReconstructedTable` and `StructuredLineItem` objects.

### Q10: Is there an existing function that converts raw_blocks into readable text?
**Answer:** **Yes.** `app.ocr.layout.order_blocks_spatially()` converts blocks into a sequential reading order, which is joined into `full_text`.

### Q11: Is there an existing function that converts raw_blocks into layout-aware context?
**Answer:** **No.** No function exports spatial bands or layout tags into an extraction context.

### Q12: Is there an existing function that converts raw_blocks into an LLM-ready representation?
**Answer:** **No.** No serializer or prompt formatter exists for `raw_blocks`.

### Q13: Does ExtractionService currently retrieve raw_blocks?
**Answer:** **Yes.** It loads `ocr_result` from `OCRResultRepository`, so `ocr_result.raw_blocks` exists in memory.

### Q14: Does ExtractionService currently pass raw_blocks to the extraction engine?
**Answer:** **No.** It passes only `ocr_result.full_text` and `document_type` at `extraction_service.py:54`.

### Q15: Does RuleBasedExtractor currently receive raw_blocks?
**Answer:** **No.** It receives only `text: str` and `document_type: str`.

### Q16: Does LLMBasedExtractor currently receive raw_blocks?
**Answer:** **No.** It receives only `text: str` and `document_type: str`.

### Q17: Does the current LLM prompt contain raw_blocks?
**Answer:** **No.** The prompt contains only `DOCUMENT OCR TEXT:\n"""\n{text}\n"""`.

### Q18: Does table reconstruction consume raw_blocks?
**Answer:** **Yes.** `reconstruct_table(blocks, page_width, page_height)` consumes the raw block dictionary list.

### Q19: Does extraction consume the output of table reconstruction?
**Answer:** **No.** Extraction has zero references to table reconstruction.

### Q20: If we wanted to pass raw_blocks to the LLM TODAY, what representation would actually be available without modifying the code?
**Answer:** Only the raw Python `list[dict]` on `ocr_result.raw_blocks` (which serializes to a raw JSON string containing verbose pixel coordinate arrays).

### Q21: What existing code, if any, could be reused for preparing raw_blocks for the LLM?
**Answer:**
1. `app.ocr.table_reconstruction.TableReconstructor` (to generate clean line-item tables).
2. `app.ocr.normalization.normalize_table_data` (to format numeric and date tokens).
3. `app.ocr.layout._get_bbox_bounds` (to calculate relative coordinates).

### Q22: What functionality does NOT currently exist and would have to be implemented?
**Answer:**
1. Updating `ExtractionEngine.extract()` and `ExtractionService.extract()` to accept and pass `raw_blocks`.
2. A `LayoutContextAdapter` (e.g. `format_raw_blocks_for_llm`) to convert multi-page blocks and tables into concise Markdown/JSON prompt context.
3. Updating `LLMBasedExtractor` prompt templates to include the formatted layout context.

---

## PART 24 — FINAL VERDICT

```
CURRENT EXTRACTION ARCHITECTURE:
Clean Architecture separating routers, orchestrating service (ExtractionService),
singleton factory, and extraction engines (RuleBasedExtractor, LLMBasedExtractor),
persisting JSONB field dictionaries to the `extraction_results` PostgreSQL table.

full_text DATA FLOW:
OCR Engine -> order_blocks_spatially() -> OCRResultData.full_text ->
PostgreSQL ocr_results.full_text -> ExtractionService.extract() ->
ExtractionEngine.extract(text, doc_type) -> Extracted fields. [COMPLETE & ACTIVE]

raw_blocks DATA FLOW:
OCR Engine -> Python list[dict] -> PostgreSQL ocr_results.raw_blocks (JSONB) ->
Loaded into memory by ExtractionService -> DISCARDED AT SERVICE BOUNDARY.
Never passed to RuleBasedExtractor or LLMBasedExtractor.

JSONB HANDLING:
PostgreSQL JSONB is automatically serialized on write and deserialized to native
Python list[dict] on read by SQLAlchemy. No manual JSON parsing is required.

RAW_BLOCKS PARSER:
DOES NOT EXIST (No general document-level layout parser exists for extraction).

RAW_BLOCKS → READABLE REPRESENTATION:
PARTIAL (order_blocks_spatially flattens blocks to full_text; TableReconstructor
clusters table rows for OCR QA only).

RAW_BLOCKS → LLM REPRESENTATION:
DOES NOT EXIST (Zero prompt formatters or block-to-context adapters exist).

LLM CURRENT INPUT:
Receives ONLY plain string `full_text` wrapped in triple quotes and `document_type`.
Receives ZERO bounding boxes, coordinates, page dimensions, or table structures.

REUSABLE COMPONENTS:
- app.ocr.table_reconstruction.TableReconstructor / reconstruct_table
- app.ocr.normalization.normalize_table_data
- app.ocr.layout._get_bbox_bounds
- app.models.ocr_result.OCRResult.raw_blocks (database storage already in place)

MISSING COMPONENTS:
- ExtractionEngine interface support for optional `raw_blocks` parameter.
- ExtractionService pass-through of `ocr_result.raw_blocks`.
- RawBlocks-to-LLM Layout Adapter (Markdown table / spatial text builder).
- LLMBasedExtractor prompt template support for layout context.

MINIMUM REQUIRED ARCHITECTURAL CHANGE:
1. Update interface signature:
   ExtractionEngine.extract(self, text: str, document_type: str, raw_blocks: list[dict] | None = None)
2. Pass `raw_blocks=ocr_result.raw_blocks` in ExtractionService.extract().
3. Add a layout adapter function to serialize raw_blocks/tables into LLM prompt text.
4. Update LLMBasedExtractor to inject the layout text into the user prompt.
(ZERO database schema changes and ZERO OCR changes required).
```

---
*End of Complete Forensic Audit Report.*
