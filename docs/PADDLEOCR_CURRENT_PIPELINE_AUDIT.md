# EFDI Implementation-Level Audit: Current PaddleOCR-Based OCR Pipeline

**Document Status:** Complete Implementation Audit (Pre-Docling Migration)  
**Target Codebase:** Enterprise Financial Document Intelligence (EFDI) — Backend  
**Audit Date:** 2026-09-27  
**Scope:** Analysis only — No source code modifications, no schema changes, no package installations.

---

## 1. Executive Summary

This audit provides an implementation-level investigation of the current OCR pipeline in the EFDI codebase. EFDI currently specifies **PaddleOCR-VL-1.6** as its primary production OCR engine (`settings.OCR_DEFAULT_ENGINE = "paddleocr-vl-1.6"`). 

The target pipeline architecture:
$$\text{PDF} \longrightarrow \text{PaddleOCR-VL-1.6} \longrightarrow \text{Business Validation} \longrightarrow \text{DB / RAG}$$

Our analysis reveals:
1. **Engine Integration & File-Level Ingestion:** PaddleOCR-VL-1.6 is wrapped in [`PaddleOCRVLEngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L24-L181) and bypasses EFDI-side PyMuPDF rasterization and OpenCV preprocessing when processing files directly via [`extract_from_file()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L65-L135).
2. **Canonical Text & Table Contract:** PaddleOCR-VL outputs structured Markdown. Tables are represented natively as standard pipe-delimited Markdown tables (`| Col1 | Col2 | ... |`). This Markdown document is persisted verbatim in [`OCRResult.full_text`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py#L31).
3. **Database Contract:** The database schema for `ocr_results` is completely untouched. It contains **no** `table_data`, **no** `layout_data`, and **no** `model_version` columns. All structural and tabular data extracted by downstream services is computed **at runtime in-memory**.
4. **Extraction Decoupling:** [`ExtractionService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L31-L128) parses Markdown tables from `ocr_result.full_text` at runtime using [`parse_markdown_table()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py#L78-L191), completely bypassing the legacy 2D geometric [`TableReconstructor`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py#L63-L385).
5. **RAG Ingestion:** [`RAGIngestionService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py#L22-L136) consumes `OCRResult.full_text` via [`StructureAwareChunker`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py#L25-L566), preserving pipe-delimited Markdown tables as cohesive chunks (sliding windows if $>15$ rows) and indexing them into `pgvector`.
6. **Legacy Remnants:** EasyOCR, PyMuPDF rasterization, OpenCV adaptive preprocessing, spatial ordering, and the 2D bounding-box `TableReconstructor` remain in the codebase as fallback/backward-compatibility layers for legacy records (`engine_name == "easyocr"` or `engine_name == "stub"`). They are completely bypassed on the PaddleOCR-VL-1.6 execution path.
7. **Coupling Points:** The primary couplings to PaddleOCR-VL are hardcoded `if ocr_result.engine_name == "paddleocr-vl-1.6":` checks in [`ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L76), [`extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L65), and [`routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py#L45), alongside the dependency on `paddleocr`/`paddlepaddle` in [`requirements-ocr.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements-ocr.txt#L29-L33).

---

## 2. Current OCR Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │                      Client / API                      │
                    │         POST /ocr/documents/{document_id}/run          │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │               OCRService.run_ocr()                     │
                    │        (backend/app/services/ocr_service.py)           │
                    └───────────────────────────┬────────────────────────────┘
                                                │
               ┌────────────────────────────────┴───────────────────────────────┐
               │                                                                │
     engine == "paddleocr-vl-1.6"                                     engine in ("easyocr", "stub")
  (or hasattr(engine, "extract_from_file"))                                     │
               │                                                                ▼
               ▼                                              ┌───────────────────────────────────┐
┌──────────────────────────────────────────────┐              │ Legacy Preprocessing Pipeline:    │
│ PaddleOCRVLEngine.extract_from_file()        │              │  1. PyMuPDF rasterize_pdf()       │
│  - Directly passes disk file_path to VLM     │              │  2. AdaptivePreprocessor.process()│
│  - Internal PDFReader handles page rendering │              │  3. EasyOCR / Stub text spotting  │
│  - Generates native Markdown document text   │              │  4. order_blocks_spatially()      │
│  - Extracts layout blocks for raw_blocks     │              │  5. 2D TableReconstructor         │
└──────────────────────┬───────────────────────┘              └─────────────────┬─────────────────┘
                       │                                                        │
                       ▼                                                        ▼
┌──────────────────────────────────────────────┐              ┌───────────────────────────────────┐
│ Business Validation & Quality Scoring        │              │ Legacy Normalization & Validation │
│  - parse_markdown_table(full_text)           │              │  - reconstruct_table(raw_blocks)  │
│  - normalize_table_data(table_dict)          │              │  - normalize_table_data()         │
│  - validate_ocr_output()                     │              │  - validate_ocr_output()          │
│  - calculate_quality_score()                 │              │  - calculate_quality_score()      │
└──────────────────────┬───────────────────────┘              └─────────────────┬─────────────────┘
                       │                                                        │
                       └────────────────────────┬───────────────────────────────┘
                                                │
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │              OCRResult Persistence                     │
                    │         (backend/app/models/ocr_result.py)             │
                    │  - engine_name: "paddleocr-vl-1.6"                     │
                    │  - full_text: Markdown document (canonical)            │
                    │  - average_confidence: float (e.g., 0.98)              │
                    │  - raw_blocks: JSONB bounding boxes / layout blocks    │
                    │  - page_count: int                                     │
                    │  - processing_time_ms: int                             │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ├──────────────────────────────────────────────┐
                                                ▼                                              ▼
                    ┌──────────────────────────────────────────────┐   ┌──────────────────────────────────────────────┐
                    │         Downstream Extraction                │   │         Downstream RAG Ingestion             │
                    │   (backend/app/services/                     │   │   (backend/app/services/                     │
                    │    extraction_service.py)                    │   │    rag_ingestion_service.py)                 │
                    │  - Reads ocr_result.full_text                │   │  - Triggered via ingest_document_async()     │
                    │  - Runs parse_markdown_table() in memory     │   │  - StructureAwareChunker consumes full_text  │
                    │  - Populates ExtractionContext               │   │  - Preserves Markdown tables intact in chunks│
                    │  - Evaluates Rule-Based / LLM extractors     │   │  - Generates embeddings -> pgvector chunks   │
                    └──────────────────────────────────────────────┘   └──────────────────────────────────────────────┘
```

---

## 3. End-to-End Execution Flow

| Step | Component | File Path & Function | Input | Output | Transformations & Details | Downstream Consumers |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | OCR API Endpoint | [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py#L111-L143) `run_ocr()` | `document_id: int`, `payload: OCRRunRequest` | `OCRResultResponse` (HTTP 201) | Authenticates user; validates permission via `DocumentService.get_for_user()`; determines engine via `payload.engine or get_default_ocr_engine(db)`; triggers `OCRService.run_ocr()`; logs audit action. | API Client / Frontend |
| **2** | Default Engine Resolution | [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L13-L18) `get_default_ocr_engine()` | `db: Session` | `str` (e.g. `"paddleocr-vl-1.6"`) | Queries `SystemSetting` key `"default_ocr_engine"`; falls back to `settings.OCR_DEFAULT_ENGINE`. | `run_ocr` |
| **3** | OCR Engine Factory | [`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py#L29-L53) `get_ocr_engine()` | `engine_name: str` | `PaddleOCRVLEngine` singleton | Validates engine name against `SUPPORTED_ENGINES` (`("paddleocr-vl-1.6", "easyocr", "stub")`); returns cached singleton from `_singletons`. | `OCRService.run_ocr()` |
| **4** | Engine Model Initialization | [`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L31-L63) `_get_engine()` | N/A (module config) | `PaddleOCRVL` instance | Lazy initialization under `threading.Lock()`. Instantiates `PaddleOCRVL(pipeline_version="v1.6", device="cpu", use_doc_orientation_classify=False, use_doc_unwarping=False)`. Cached at module level `_cached_engine`. | `extract_from_file()` |
| **5** | Disk Path Resolution | [`backend/app/utils/file_storage.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L65-L73) | `document.stored_filename` | `Path` | Resolves absolute file path on disk; asserts file exists. | `OCRService.run_ocr()` |
| **6** | Document Direct Ingestion | [`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L65-L135) `extract_from_file()` | `file_path: Union[str, Path]` | `OCRResultData` (`app.ocr.base.OCRResult`) | Calls `engine.predict(str(file_path))`. PaddleOCR internal `PDFReader` renders pages; parses multimodal visual layout; produces Markdown per page. Converts layout blocks to 4-point polygon bboxes. Joins multi-page text with `=== PAGE {n} ===`. | `OCRService.run_ocr()` |
| **7** | In-Memory Markdown Table Parsing | [`backend/app/ocr/markdown_table_parser.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py#L78-L191) `parse_markdown_table()` | `result_data.full_text` | `dict` (`table_dict` with `headers`, `columns`, `line_items`, `line_items_count`) | Deterministic regex parsing of Markdown pipe-delimited table rows (`\| Col \|`). Matches headers using canonical synonym map (`ALL_SYNONYMS`). Extracts line items without spatial coordinates or clustering. | Business Validation & Audit |
| **8** | In-Memory Normalization | [`backend/app/ocr/normalization.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py#L1-L100) `normalize_table_data()` | `table_dict: dict` | `list[NormalizedLineItem]` | Normalizes quantities, prices, amounts, VAT rates, and descriptions to typed numeric and string fields. Does not mutate raw strings. | Business Validation |
| **9** | In-Memory Business Validation | [`backend/app/ocr/validation.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/validation.py#L280-L292) `validate_ocr_output()` | `line_items`, `raw_full_text` | `DocumentValidationResult` | Runs arithmetic integrity checks ($qty \times price \approx net$, $net + vat \approx gross$, $\sum net \approx subtotal$, $subtotal + vat \approx grand\_total$) and checks header token presence (invoice #, date). | Quality Scorer & Audit Log |
| **10** | Document Quality Scoring | [`backend/app/ocr/quality_scoring.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/quality_scoring.py#L27-L100) `calculate_quality_score()` | `avg_confidence`, `full_text`, `table_data`, `validation_result` | `OCRQualityBreakdown` | Computes composite score $[0.0 - 1.0]$ based on confidence (35%), structural layout (25%), validation pass rate (25%), and field completeness (15%). Assigns grade (`EXCELLENT`, `GOOD`, `FAIR`, `POOR`). | Audit Log & API Response |
| **11** | Status Evaluation & DB Persistence | [`backend/app/repositories/ocr_result_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/ocr_result_repository.py#L35-L48) `create()` | Document metadata, `full_text`, `raw_blocks`, `processing_time_ms` | `app.models.ocr_result.OCRResult` | If `full_text` is empty: sets `Document.status = REJECTED`. Otherwise sets `Document.status = OCR_COMPLETED`. Inserts row into `ocr_results` table. | Database, RAG, Extraction |
| **12** | Asynchronous RAG Ingestion Hook | [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py#L123-L136) `ingest_document_async()` | `document.id: int` | Background daemon thread | Spawns thread running `ingest_document(document.id)` with an independent DB session. Consumes `OCRResult.full_text`. Does not block HTTP response. | Vector Store (`document_chunks`) |
| **13** | Audit Event Logging | [`backend/app/services/audit_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/audit_service.py#L1) `log()` | `AuditAction.OCR_COMPLETED`, details dict | `AuditLog` row | Logs event with engine, status, table item count, quality score, validation pass, and preprocessing strategy (`PADDLEOCR_VL_NATIVE`). | Audit Trail |
| **14** | API Response Construction | [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py#L42-L95) `_to_response()` | `OCRResult` ORM instance | `OCRResultResponse` | Validates ORM fields into Pydantic schema. Because `engine_name == "paddleocr-vl-1.6"`, re-parses Markdown table in memory and attaches `table_data`, `normalized_data`, `validation_results`, and `quality_score`. | Caller / UI |

---

## 4. File / Class / Function Map

| File Path | Class / Function | Responsibility |
| :--- | :--- | :--- |
| [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py) | `run_ocr()` | Handles HTTP POST `/ocr/documents/{id}/run`, invokes `OCRService`, formats API response. |
| [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py) | `_to_response()` | Dynamically transforms `OCRResult` into `OCRResultResponse`, parsing Markdown tables into transient fields. |
| [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py) | `get_ocr_engines()` | Handles HTTP GET `/ocr/engines`, returning availability and status of all engines. |
| [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py) | `OCRService.run_ocr()` | End-to-end OCR orchestration: resolves file, delegates to engine, runs business validation, persists result, updates status, triggers RAG. |
| [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py) | `get_default_ocr_engine()` | Checks dynamic database system setting `default_ocr_engine` or returns config default. |
| [`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py) | `get_ocr_engine()` | Factory returning engine singleton based on name (`"paddleocr-vl-1.6"`, `"easyocr"`, `"stub"`). |
| [`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py) | `get_engine_status()` | Probes `is_available()` on each supported engine. |
| [`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py) | `PaddleOCRVLEngine` | Core wrapper around PaddleOCR-VL model. Implements `extract_from_file()` and `extract_text_blocks()`. |
| [`backend/app/ocr/base.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/base.py) | `OCREngine` | Abstract base class defining `extract_text_blocks()` and `is_available()`. |
| [`backend/app/ocr/base.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/base.py) | `OCRResult`, `OCRPageResult`, `OCRTextBlock` | In-memory dataclasses representing normalized OCR output structures across all engines. |
| [`backend/app/ocr/markdown_table_parser.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py) | `parse_markdown_table()` | Regex/synonym-based parser extracting structured line-item dictionaries from pipe-delimited Markdown tables. |
| [`backend/app/ocr/normalization.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py) | `normalize_table_data()` | Normalizes raw string values from table line items into structured, typed dataclasses. |
| [`backend/app/ocr/validation.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/validation.py) | `validate_ocr_output()` | Non-destructive business validation checking arithmetic consistency and document headers. |
| [`backend/app/ocr/quality_scoring.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/quality_scoring.py) | `calculate_quality_score()` | Calculates multi-factor composite document quality score and grade. |
| [`backend/app/models/ocr_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py) | `OCRResult` | SQLAlchemy ORM entity mapping to `ocr_results` table. |
| [`backend/app/repositories/ocr_result_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/ocr_result_repository.py) | `OCRResultRepository` | Data-access layer for persisting and retrieving OCR results. |
| [`backend/app/services/extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py) | `ExtractionService.extract()` | Consumes `ocr_result.full_text`, runs runtime Markdown table parsing, builds `ExtractionContext`, runs field extraction. |
| [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py) | `RAGIngestionService.ingest_document()` | Consumes `ocr_result.full_text`, executes structure-aware chunking, generates embeddings, persists chunks. |
| [`backend/app/rag/chunking.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py) | `StructureAwareChunker` | Chunks canonical document text based on Markdown table boundaries and headers. |

---

## 5. PaddleOCR Initialization

### 5.1 Initialization Site and Code
PaddleOCR-VL is initialized in [`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L31-L63):

```python
_engine_lock = threading.Lock()
_cached_engine = None

class PaddleOCRVLEngine(OCREngine):
    name = "paddleocr-vl-1.6"

    def __init__(self, *, pipeline_version: str = "v1.6", device: Optional[str] = None):
        self.pipeline_version = pipeline_version
        self.device = device or getattr(settings, "PADDLE_VL_DEVICE", "cpu")

    def _get_engine(self):
        global _cached_engine
        if _cached_engine is not None:
            return _cached_engine

        with _engine_lock:
            if _cached_engine is None:
                try:
                    from paddleocr import PaddleOCRVL
                except ImportError as exc:
                    raise FileProcessingException(
                        "PaddleOCR / PaddleOCRVL is not installed in this environment"
                    ) from exc

                logger.info(
                    "Loading PaddleOCR-VL engine (pipeline_version=%s, device=%s)...",
                    self.pipeline_version,
                    self.device,
                )
                try:
                    _cached_engine = PaddleOCRVL(
                        pipeline_version=self.pipeline_version,
                        device=self.device,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                    )
                except Exception as exc:
                    raise FileProcessingException(
                        f"Failed to initialize PaddleOCR-VL engine: {exc}"
                    ) from exc
                logger.info("PaddleOCR-VL engine loaded successfully.")

        return _cached_engine
```

### 5.2 Key Initialization Characteristics
1. **Lazy Loading:** `PaddleOCRVL` is imported and instantiated on first use, not when the FastAPI application starts.
2. **Process Singleton & Thread Safety:** A global module variable `_cached_engine` protected by `threading.Lock()` ensures that only one model instance is loaded per Python process.
3. **Model Configuration:**
   - `pipeline_version = "v1.6"` (PaddleOCR-VL 0.9B vision-language model).
   - `device = getattr(settings, "PADDLE_VL_DEVICE", "cpu")`.
   - `use_doc_orientation_classify = False` (skips extra rotation classification network).
   - `use_doc_unwarping = False` (skips 3D unwarping network).
4. **Older Engine Remnant:** There is an older [`PaddleOCREngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_engine.py#L37-L125) in `app/ocr/paddle_engine.py` using `from paddleocr import PaddleOCR; PaddleOCR(lang="en", ...)`. However, in [`factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py#L23-L24):
   ```python
   PRODUCTION_ENGINES = ("paddleocr-vl-1.6", "easyocr")
   SUPPORTED_ENGINES = PRODUCTION_ENGINES + ("stub",)
   ```
   The older `paddleocr` engine name is **not** present in `SUPPORTED_ENGINES`. Any request requesting `"paddleocr"` is rejected by `factory.py` with `ValidationFailedException`.

---

## 6. PDF Input Handling

### 6.1 Direct File Ingestion Path
In [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L76-L82):
```python
if engine_name == "paddleocr-vl-1.6" or hasattr(engine, "extract_from_file"):
    # PaddleOCR-VL target architecture:
    # PDF -> PaddleOCR-VL -> Business Validation -> DB / RAG
    # Direct file path input: no EFDI-side PyMuPDF rasterization, no OpenCV preprocessing
    result_data = engine.extract_from_file(file_path)
```

### 6.2 Comparison of Ingestion Paths
| Dimension | PaddleOCR-VL-1.6 (Current Target) | Legacy Pipeline (EasyOCR / Stub) |
| :--- | :--- | :--- |
| **Input Format** | Absolute filesystem `Path` or `str` | In-memory `file_bytes` |
| **PDF Rendering** | PaddleOCR-VL internal `PDFReader` (backed by `pypdfium2`) | EFDI-side `fitz.open(stream=pdf_bytes)` via `rasterize_pdf()` |
| **DPI / Resolution** | Internal default of PaddleOCR-VL | Explicit 200 DPI (`DEFAULT_RENDER_DPI = 200`) |
| **Preprocessing** | None on EFDI side (`PADDLEOCR_VL_NATIVE`) | `AdaptivePreprocessor.process()` (Hough deskew, Bilateral filter, CLAHE contrast, Otsu threshold) |
| **Page Iteration** | Handled internally in `engine.predict(file_str)` | Explicit Python loop over preprocessed numpy arrays in `ocr_service.py` |

---

## 7. PaddleOCR Output Contract

### 7.1 What PaddleOCR-VL Returns
When calling `engine.predict(file_str)`, PaddleOCR-VL returns a list of result objects (one per page):
1. **Markdown Text:** Extracted via:
   - `res.markdown.get("markdown")` or
   - `res._to_markdown(pretty=False).get("markdown")` or
   - `res.str.get("res")`
2. **Layout Blocks & Coordinates:** Extracted from `res.get("parsing_res_list")`. Each block provides:
   - `content` / `block_content`: Extracted text.
   - `bbox` / `block_bbox`: Bounding box coordinates $[x_0, y_0, x_1, y_1]$.
3. **Table Representation:** Tables are rendered as **Markdown tables** inside the page Markdown text:
   ```markdown
   | Item Description | Quantity | Unit Price | Amount |
   | :--- | :--- | :--- | :--- |
   | Professional Consulting | 10 | 150.00 | 1500.00 |
   ```
4. **Confidence Values:** PaddleOCR-VL's `predict()` does not return individual per-character confidence scores for VLM parsing; [`PaddleOCRVLEngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L120) synthesizes a default confidence of `0.98` for each layout block.

### 7.2 Multi-Page Concatenation Contract
In [`PaddleOCRVLEngine.extract_from_file()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L128-L134):
- If `len(results) > 1`: Each page's Markdown is prefixed with `=== PAGE {page_idx} ===\n`.
- If single page: Page content is kept without the page marker.
- Pages are joined with `\n\n`.
- This joined string is assigned to `OCRResultData.custom_full_text`.

### 7.3 Raw Blocks Contract
In [`OCRService.run_ocr()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L85-L100):
`raw_blocks` is converted into a standard EFDI JSON structure:
```json
[
  {
    "page_number": 1,
    "page_width": 1000.0,
    "page_height": 1400.0,
    "blocks": [
      {
        "text": "INVOICE",
        "confidence": 0.98,
        "bounding_box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
      }
    ]
  }
]
```

---

## 8. EFDI OCR Adapter / Post-Processing

### 8.1 In-Memory Markdown Table Parser
Implemented in [`backend/app/ocr/markdown_table_parser.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py#L78-L191).
- Detects pipe-delimited table lines starting and ending with `|`.
- Matches header names against standardized column roles via [`HEADER_COLUMN_MAP`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py#L16-L46) supporting English and German accounting terms (`item_number`, `description`, `quantity`, `unit`, `unit_price`, `net_amount`, `vat_rate`, `gross_amount`).
- Parses rows into dictionary structures.
- **Critical Feature:** Prevents semantic leakage of trailing tax breakdown schedules (CGST/SGST/VAT summary blocks) because the table parser strictly adheres to Markdown table boundary syntax.

### 8.2 Non-Destructive Normalization Layer
Implemented in [`backend/app/ocr/normalization.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py#L1-L100) via `normalize_table_data(table_dict)`:
- Maps string values to typed dataclass fields [`NormalizedLineItem`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py#L14-L48).
- Strips currency signs, parses decimal quantities and prices, computes normalized VAT percentages ($10\% \to 0.10$).
- Preserves raw values in fields prefixed with `raw_` (e.g. `raw_unit_price`).

---

## 9. Business Validation

Implemented in [`backend/app/ocr/validation.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/validation.py#L58-L292):
- **Line-Item Checks:**
  - Presence of item description (`ITEM_{i}_DESC_MISSING`).
  - Arithmetic balance: $Quantity \times UnitPrice \approx NetAmount$ (`ITEM_{i}_MATH_QTY_PRICE`).
  - Gross balance: $NetAmount \times (1 + VATRate) \approx GrossAmount$ (`ITEM_{i}_MATH_NET_VAT_GROSS`).
- **Document-Level Checks:**
  - Detection of invoice number token in `raw_full_text` (`DOC_INVOICE_NUM_PRESENT`).
  - Detection of date token in `raw_full_text` (`DOC_DATE_PRESENT`).
  - Subtotal reconciliation: $\sum NetAmounts \approx ReportedSubtotal$ (`DOC_MATH_SUM_ITEMS_SUBTOTAL`).
  - Grand total reconciliation: $Subtotal + ReportedVAT \approx GrandTotal$ (`DOC_MATH_SUBTOTAL_VAT_GRAND`).
- Configurable absolute tolerance (`1.0`) and relative tolerance (`2%`).
- Produces [`DocumentValidationResult`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/validation.py#L36-L56) (`is_valid`, flags, pass/fail counts).

---

## 10. OCRResult Persistence

### 10.1 Database Entity Contract
The database table `ocr_results` is defined in [`backend/app/models/ocr_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py#L23-L50):

| Column Name | Type | Nullable | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | No | Auto-increment PK | Primary key |
| `document_id` | `Integer` (FK to `documents.id`) | No | Index | Foreign key referencing the parent document |
| `engine_name` | `String(30)` | No | None | Stores `"paddleocr-vl-1.6"` |
| `page_count` | `Integer` | No | `0` | Number of document pages processed |
| `full_text` | `Text` | No | `""` | **The canonical Markdown document representation** |
| `average_confidence` | `Float` | No | `0.0` | Token recognition confidence score (0.0 to 1.0) |
| `raw_blocks` | `JSONB` | No | `[]` | JSON array of detected blocks with bboxes and confidence |
| `processing_time_ms` | `Integer` | Yes | `None` | Wall-clock execution time in milliseconds |
| `created_at` | `DateTime(timezone=True)` | No | `utcnow` | Creation timestamp |
| `updated_at` | `DateTime(timezone=True)` | No | `utcnow` | Last update timestamp |

### 10.2 Persistence Constraints
- **NO schema changes were made for PaddleOCR-VL.**
- `table_data` is **NEVER** stored in the database.
- `model_version` is **NEVER** stored in the database.
- `layout_data` is **NEVER** stored in the database.
- `OCRResult.full_text` is the single source of truth persisted in PostgreSQL.

---

## 11. Extraction Dependency

### 11.1 How Extraction Consumes OCR Output
In [`backend/app/services/extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L65-L125):
```python
if ocr_result.engine_name == "paddleocr-vl-1.6":
    try:
        from app.ocr.markdown_table_parser import parse_markdown_table

        table_data = parse_markdown_table(ocr_result.full_text)
        normalized_items = normalize_table_data(table_data)
        normalized_data = {"line_items": [item.to_dict() for item in normalized_items]}
        val_res = validate_ocr_output(normalized_items, raw_full_text=ocr_result.full_text)
        ocr_validation = val_res.to_dict()
        avg_conf = float(ocr_result.average_confidence) if ocr_result.average_confidence is not None else 1.0
        quality_res = calculate_quality_score(
            avg_confidence=avg_conf,
            full_text=ocr_result.full_text,
            table_data=table_data,
            validation_result=val_res,
        )
        ocr_quality = quality_res.to_dict()
    except Exception as exc:
        logger.warning("Could not compute derived OCR structures from Markdown table for context: %s", exc)
```

### 11.2 Extraction Engine Usage of Table Data
1. **Rule-Based Engine (`RuleBasedExtractionEngine`):**
   In [`backend/app/extraction/table_helpers.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/table_helpers.py#L13-L83) (`extract_amount_from_table`), the engine computes net and gross totals directly from `context.table_data["line_items"]` to reconcile against extracted scalar amounts.
2. **Reconciliation Engine:**
   In [`backend/app/extraction/reconciliation.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/reconciliation.py#L423-L437), if an amount field conflicts between rule-based and LLM extraction, it uses `extract_amount_from_table(context.table_data)` as an authoritative tie-breaker.
3. **LLM Engine (`llm_context_builder.py`):**
   In [`backend/app/extraction/llm_context_builder.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/llm_context_builder.py#L353-L356):
   Because PaddleOCR-VL puts pipe-delimited Markdown tables (`| ---`) directly into `context.full_text`, `has_table_in_full_text` evaluates to `True`. The LLM prompt directly receives the native Markdown text without duplicating the table.

---

## 12. RAG Dependency

### 12.1 Ingestion Flow
In [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py#L56-L95):
- Triggered asynchronously via `get_rag_ingestion_service().ingest_document_async(document.id)`.
- Strictly consumes **`ocr_result.full_text`** (never `ExtractionResult`).
- Passes `full_text` and `raw_blocks` to [`StructureAwareChunker.chunk_document()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py#L56-L77).

### 12.2 Structure-Aware Chunking Contract
Implemented in [`backend/app/rag/chunking.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py#L109-L400):
1. **Page Splitting:** Uses regex `^=== PAGE (\d+) ===$` to delineate pages.
2. **Table Boundary Detection:** Locates consecutive lines starting with `|` and containing `---` or multiple pipes.
3. **Table Integrity Preservation:**
   - If table rows $\le 15$: The table is kept completely intact within a single chunk of type `LINE_ITEMS` with `section = "LINE_ITEMS"`.
   - If table rows $> 15$: Slices rows into overlapping sliding windows (window size 10, step 8), repeating the table header on every chunk.
4. **Surrounding Content:** Content preceding the table becomes `HEADER` chunks; content succeeding the table becomes `SUMMARY` (totals) or `TERMS` (payment/legal terms).
5. **Bounding Box Linking:** Uses `raw_blocks` only to populate `metadata_json["bounding_box_refs"]` for visual provenance.

---

## 13. Legacy OCR Components Still Present

Every legacy component was audited against the codebase to determine its current status:

| Legacy Component | Source File | Status | Detailed Finding |
| :--- | :--- | :--- | :--- |
| **PyMuPDF Rasterization** | [`app/ocr/preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py#L29) `rasterize_pdf` | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL. Still called in `ocr_service.py:118` when `engine_name != "paddleocr-vl-1.6"` (EasyOCR/stub). |
| **PDF-to-Image Conversion** | [`app/ocr/preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py#L65) `load_image_bytes` | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL file ingestion. Still called in `ocr_service.py:125` for non-PDF image bytes under EasyOCR/stub. |
| **OpenCV Preprocessing** | [`app/ocr/preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py#L85-L160) (`deskew`, `denoise`, etc.) | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL. Still invoked if `AdaptivePreprocessor` triggers operations during EasyOCR runs. |
| **Adaptive Preprocessing** | [`app/ocr/adaptive_preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/adaptive_preprocessing.py#L108) `AdaptivePreprocessor` | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL (which logs synthetic `PADDLEOCR_VL_NATIVE`). Still active in `ocr_service.py:121`. |
| **EasyOCR Engine** | [`app/ocr/easyocr_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/easyocr_engine.py#L40) `EasyOCREngine` | **D / C** | **Still used elsewhere / legacy records:** Maintained in `factory.py:23` as a secondary production engine for CPU/torch fallback. |
| **Spatial Ordering** | [`app/ocr/layout.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/layout.py#L33) `order_blocks_spatially` | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL (natural reading order from VLM). Still called in `ocr_service.py:166` for EasyOCR. |
| **TableReconstructor** | [`app/ocr/table_reconstruction.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py#L63) `TableReconstructor` | **D / C** | **Still used elsewhere / legacy records:** Bypassed by PaddleOCR-VL. Still called in `ocr_service.py:154, 183`, `extraction_service.py:94`, and `routers/ocr.py:75` for EasyOCR. |
| **Geometric Table Reconstruction** | [`app/ocr/table_reconstruction.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py#L387) `reconstruct_table` | **D / C** | **Still used elsewhere / legacy records:** Same as `TableReconstructor`. |
| **OCR-Specific Normalization** | [`app/ocr/normalization.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py#L1-L100) `normalize_table_data` | **B** | **Still used by PaddleOCR:** Actively called by `ocr_service.py:104`, `extraction_service.py:70`, and `routers/ocr.py:52` to type-convert parsed Markdown tables. |
| **OCR-Specific Validation** | [`app/ocr/validation.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/validation.py#L280) `validate_ocr_output` | **B** | **Still used by PaddleOCR:** Actively called by `ocr_service.py:105`, `extraction_service.py:72`, and `routers/ocr.py:57` to validate mathematical balance. |
| **Bounding-Box Table Reconstruction** | `TableReconstructor._cluster_rows_by_overlap` | **D / C** | **Still used only by legacy records:** Bypassed by PaddleOCR-VL. |
| **Token Clustering** | `TableReconstructor._stitch_split_numeric_tokens` | **D / C** | **Still used only by legacy records:** Bypassed by PaddleOCR-VL. |
| **Row Clustering** | `TableReconstructor._cluster_rows_by_overlap` | **D / C** | **Still used only by legacy records:** Bypassed by PaddleOCR-VL. |
| **Column Clustering** | `TableReconstructor._derive_columns` | **D / C** | **Still used only by legacy records:** Bypassed by PaddleOCR-VL. |
| **OCR-Specific Heuristics** | `_is_subtotal_or_total_row`, `_split_numeric_tail` | **D / C** | **Still used only by legacy records:** Bypassed by PaddleOCR-VL. |

*Status Legend:*  
- **A:** Completely removed  
- **B:** Still used by PaddleOCR  
- **C:** Still used only by legacy OCR records  
- **D:** Still used elsewhere (active in non-PaddleOCR fallback branches)  
- **E:** Dead / unused code  

---

## 14. Performance / Latency Breakdown

### 14.1 Existing Timing Instrumentation
1. **Total OCR Pipeline Duration:**
   - Instrumented in [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L74-L195):
     ```python
     start_time = time.monotonic()
     ...
     elapsed_ms = int((time.monotonic() - start_time) * 1000)
     ```
   - Persisted in `ocr_results.processing_time_ms`.
   - Logged via `logger.info("OCR completed: ... time_ms=%s ...", elapsed_ms)`.
2. **RAG Embedding Duration:**
   - Instrumented in [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py#L38-L106) (`t_embed_ms` and `total_ms`).

### 14.2 Missing Timing Instrumentation (Explicitly Noted)
There is **NO** granular timing instrumentation for:
- Model initialization / first-load time.
- Engine inference execution time (`PaddleOCRVL.predict()` alone).
- PDF loading / rendering time inside PaddleOCR.
- Post-processing / Markdown table parsing time (`parse_markdown_table()`).
- Business validation time (`validate_ocr_output()`).
- Database insert / commit latency.
- Downstream extraction execution time (`ExtractionService.extract()`).

### 14.3 Latency Sources in PaddleOCR-VL
1. **Cold Start (Model Weights Loading):** Initializing PaddleOCR-VL loads the 0.9B VLM weights into memory. On CPU, first-run initialization takes 4–10 seconds.
2. **Inference Latency:** Running multimodal vision-language autoregressive decoding over high-resolution document pages on CPU takes ~1.5s–3.5s per page. On GPU (CUDA), this drops to ~200ms–500ms per page.
3. **Markdown Parsing & Validation:** Highly efficient in-memory string and regex operations (<5ms).

---

## 15. Dependencies and Configuration

### 15.1 Dependencies in Codebase
- Defined in [`backend/requirements-ocr.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements-ocr.txt#L29-L33):
  - `paddleocr==3.7.0`
  - `paddlepaddle==3.2.2`
  - `paddlex==3.7.1`
  - `pypdfium2==5.10.1`
  - `shapely==2.1.2`, `pyclipper==1.4.0`
- Excluded from base [`backend/requirements.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements.txt#L4-L16) so the core web server and tests can run with `OCR_DEFAULT_ENGINE=stub` without heavyweight ML packages.

### 15.2 Configuration Settings & Environment Variables
Defined in [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py#L60-L66):
- `OCR_DEFAULT_ENGINE: str = "paddleocr-vl-1.6"`
- `ENABLE_STRUCTURED_FULL_TEXT: bool = True`
- `PADDLE_VL_DEVICE: str = "cpu"` (referenced via `getattr(settings, "PADDLE_VL_DEVICE", "cpu")` in `paddle_vl_engine.py:29`).
- Dynamic override: Database table `system_settings` key `"default_ocr_engine"`.

---

## 16. Error Handling / Fallback Behavior

1. **Uninstalled Packages:**
   In [`PaddleOCRVLEngine._get_engine()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py#L40-L43), if `paddleocr` is not installed, it raises `FileProcessingException("PaddleOCR / PaddleOCRVL is not installed in this environment")`, resulting in an HTTP 422 Unprocessable Entity error (not an unhandled HTTP 500 crash).
2. **Missing Model Weights / Network Blocked:**
   If model weights cannot be downloaded (due to network allowlist or proxy blocks), `PaddleOCRVL()` raises an exception which is caught and wrapped in `FileProcessingException`.
3. **Empty Text Rejection:**
   In [`OCRService.run_ocr()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L198-L204), if `not result_data.full_text.strip()`, the document status is set to `DocumentStatus.REJECTED`, and an audit event `AuditAction.DOCUMENT_REJECTED` is logged.
4. **Audit on Failure:**
   If any unhandled exception occurs in `run_ocr()`, the exception is caught, logged to `AuditAction.OCR_FAILED` with the engine name and error message, and re-raised.
5. **RAG Ingestion Isolation:**
   RAG ingestion is triggered in a background daemon thread with its own independent database session (`get_db_context()`). If RAG ingestion fails, it logs a warning and leaves `DocumentStatus.OCR_COMPLETED` intact.

---

## 17. Architectural Contracts a Replacement Engine (Docling) Must Preserve

To ensure seamless drop-in replacement without destabilizing downstream components, **Docling must preserve the following contracts**:

1. **File-Level Extraction Interface:**
   The engine must implement `extract_from_file(self, file_path: Union[str, Path]) -> OCRResultData` taking an absolute path to a PDF or image file on disk.
2. **Canonical Markdown `full_text` Contract:**
   - `result_data.custom_full_text` must contain the complete document text in **clean Markdown**.
   - Multi-page documents must separate pages using `=== PAGE {page_number} ===`.
   - Tables must be formatted as **standard Markdown pipe-delimited tables** (`| Col1 | Col2 | ... |` and `|---|---|`).
3. **Database Schema Immutability:**
   - **Zero database schema modifications.**
   - No new columns on `ocr_results` (no `table_data`, `layout_data`, or `model_version`).
   - Persist solely into existing fields: `document_id`, `engine_name`, `page_count`, `full_text`, `average_confidence`, `raw_blocks`, `processing_time_ms`.
4. **Visual Provenance (`raw_blocks`):**
   - Provide a list of page dictionaries containing `blocks` with text and 4-point polygon `bounding_box` coordinates (`[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]`).
   - Needed by RAG `StructureAwareChunker._find_bbox_refs()` and frontend document overlays.
5. **Downstream Extraction In-Memory Contract:**
   - `ExtractionService` relies on parsing `ocr_result.full_text` into `table_data` and `normalized_data`.
   - The Markdown table format emitted by Docling must be compatible with `parse_markdown_table()` or provide equivalent line item dictionaries (`item_number`, `description`, `quantity`, `unit`, `unit_price`, `net_amount`, `vat_rate`, `gross_amount`).
6. **RAG Chunking Contract:**
   - `StructureAwareChunker` expects Markdown tables to detect line-item sections and maintain row integrity (up to 15 rows intact).
7. **Readiness Probe Contract:**
   - Implement `is_available() -> tuple[bool, str]` for the `/ocr/engines` endpoint.
8. **Lifecycle & Audit Contract:**
   - Advance `Document.status` to `OCR_COMPLETED` if text exists, or `REJECTED` if empty.
   - Fire non-blocking RAG ingestion `get_rag_ingestion_service().ingest_document_async(document.id)`.

---

## 18. Potential Docling Integration Points

When the replacement phase begins, the integration points are clear and localized:

1. **Engine Implementation:**
   Create [`backend/app/ocr/docling_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py) inheriting from `OCREngine` and implementing:
   - `extract_from_file(file_path: Union[str, Path]) -> OCRResultData`
   - Invokes Docling's `DocumentConverter` to convert the PDF directly.
   - Exports native Markdown via Docling's document representation.
   - Exports table bounding boxes and text blocks into `raw_blocks`.
2. **Factory Registration:**
   In [`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py):
   - Register `"docling"` in `PRODUCTION_ENGINES` and `SUPPORTED_ENGINES`.
   - Update `get_ocr_engine()` singleton dispatch.
3. **OCR Service Engine Dispatch:**
   In [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py#L76):
   - Change check to include Docling or generalize to:
     ```python
     if hasattr(engine, "extract_from_file"):
         result_data = engine.extract_from_file(file_path)
     ```
4. **Extraction Context Dispatch:**
   In [`backend/app/services/extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L65) and [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py#L45):
   - Enable `parse_markdown_table()` for `ocr_result.engine_name in ("docling", "paddleocr-vl-1.6")`.
5. **Configuration Defaults:**
   In [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py#L64):
   - Update `OCR_DEFAULT_ENGINE: str = "docling"`.

---

## 19. Unknowns / Items Requiring Verification

Before implementing Docling, the following questions must be verified:

1. **Docling Dependency Footprint & C-Extensions:**
   - Docling relies on PyTorch / torchvision / huggingface transformers and `docling-core`.
   - We must verify whether Docling's dependencies conflict with existing pinned versions in [`backend/requirements.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements.txt) (specifically NumPy 2.x, Pillow 12.x, PyDantic 2.x).
2. **Model Weight Download Policy:**
   - Does Docling require downloading HuggingFace model weights on first run, and are those endpoints reachable in the deployment environment?
3. **Docling Markdown Table Syntax:**
   - Does Docling output GitHub-Flavored Markdown (GFM) tables with pipe separators (`|---|`), and how does it represent complex nested or borderless financial tables?
4. **Bounding Box Coordinate Space:**
   - Does Docling export normalized coordinates $[0, 1]$ or pixel dimensions $[0, W] \times [0, H]$? EFDI's `raw_blocks` expects pixel coordinates or page-scale coordinates ($1000 \times 1400$).
5. **Memory and CPU Performance:**
   - Docling inference latency on multi-page PDFs in CPU-only environments must be benchmarked against PaddleOCR-VL-1.6.
