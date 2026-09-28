# EFDI Implementation Report: Docling OCR Engine Replacement

**Document Status:** Complete & Verified Implementation Report  
**Target Codebase:** Enterprise Financial Document Intelligence (EFDI) — Backend  
**Date:** 2026-09-27  
**Scope:** Narrow OCR Engine Replacement: PaddleOCR-VL-1.6 $\longrightarrow$ Docling  

---

## 1. Executive Summary

This report documents the completed implementation-level replacement of **PaddleOCR-VL-1.6** with **Docling** as the primary optical character recognition and document structure engine in **EFDI (Enterprise Financial Document Intelligence)**.

### Target Architecture:
$$\text{PDF} \longrightarrow \text{Docling} \longrightarrow \text{Schema Normalization \& Validation} \longrightarrow \text{DB / RAG}$$

### Core Achievements:
1. **Narrow Engine Replacement:** The migration was executed strictly within the existing OCR abstraction layer. No database migrations were created, no database schemas were modified, and no architectural changes were made to downstream Extraction or RAG systems.
2. **Direct PDF Ingestion:** Docling directly receives PDF files from disk via [`DoclingEngine.extract_from_file()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py#L71), eliminating EFDI-side PyMuPDF rasterization and OpenCV preprocessing from the active path.
3. **Table Structure Recognition:** Docling's native layout model and TableFormer capability parse complex financial tables into standard pipe-delimited Markdown tables without invoking the legacy 2D geometric `TableReconstructor`.
4. **Zero Semantic Leakage:** Tax breakdown schedules (CGST, SGST, IGST, VAT totals) are cleanly distinguished from line-item tables and do not contaminate item descriptions.
5. **Canonical Text Contract Preserved:** `OCRResult.full_text` remains the canonical persisted representation. Markdown tables, reading order, and multi-page delimiters (`=== PAGE {n} ===`) are preserved.
6. **Full Backward Compatibility:** Historical EasyOCR records and PaddleOCR records remain fully compatible.

---

## 2. Previous vs. New Execution Paths

### Previous Execution Path (PaddleOCR-VL-1.6):
```
PDF / Image
  ↓
OCRService.run_ocr()
  ↓
app/ocr/paddle_vl_engine.py (PaddleOCRVLEngine)
  ↓
PaddleOCRVL.predict() [0.9B VLM]
  ↓
In-Memory parse_markdown_table()
  ↓
In-Memory normalize_table_data() & validate_ocr_output()
  ↓
Persistence: OCRResult (full_text = Paddle Markdown)
  ↓
Downstream: Extraction (in-memory parse) & RAG Ingestion (StructureAwareChunker)
```

### New Active Execution Path (Docling):
```
PDF / Image
  ↓
OCRService.run_ocr()
  ↓
app/ocr/docling_engine.py (DoclingEngine)
  │  ├── Native PDF Parsing & Rendering
  │  ├── RapidOCR / EasyOCR text spotting (where needed)
  │  ├── Document Layout Analysis (Heron)
  │  └── TableFormer / Table Structure Recognition
  ↓
Canonical Markdown Export (with page boundaries & pipe tables)
  ↓
In-Memory parse_markdown_table()
  ↓
In-Memory normalize_table_data() & validate_ocr_output()
  ↓
Persistence: OCRResult (full_text = Docling Markdown, raw_blocks = Docling bboxes)
  ↓
Downstream: Extraction (in-memory parse) & RAG Ingestion (StructureAwareChunker)
```

---

## 3. Files Changed

| File Path | Description of Changes |
| :--- | :--- |
| [`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py) | Registered `DoclingEngine` in `PRODUCTION_ENGINES = ("docling", "easyocr")`. Moved `paddleocr-vl-1.6` to `LEGACY_ENGINES`. Added singleton caching for `"docling"`. |
| [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py) | Updated default configuration `OCR_DEFAULT_ENGINE: str = "docling"`. |
| [`backend/.env`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/.env) | Updated environment variable `OCR_DEFAULT_ENGINE=docling`. |
| [`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py) | Updated engine dispatch check to include `"docling"` (`if engine_name in ("docling", "paddleocr-vl-1.6") or hasattr(engine, "extract_from_file"):`). Set preprocessing strategy to `DOCLING_NATIVE`. |
| [`backend/app/services/extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py) | Updated runtime extraction context builder check to `if ocr_result.engine_name in ("docling", "paddleocr-vl-1.6"):`, enabling seamless in-memory Markdown table parsing for Docling results. |
| [`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py) | Updated `_to_response()` to recognize `docling` when constructing transient API response fields (`table_data`, `normalized_data`, `validation_results`, `quality_score`). |
| [`backend/requirements-ocr.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements-ocr.txt) | Added `docling==2.130.0` as the primary production engine dependency. Deprecated PaddleOCR entries. |
| [`backend/tests/test_phase4_ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_phase4_ocr.py) | Updated factory status test assertions to verify that `"docling"` is present, is a production engine, and is the default engine. |
| [`backend/tests/test_paddleocr_vl_pipeline.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_paddleocr_vl_pipeline.py) | Updated assertions to verify `paddleocr-vl-1.6` is preserved as a supported legacy engine (`is_production_engine: False`). |

---

## 4. Files Added

| File Path | Description |
| :--- | :--- |
| [`backend/app/ocr/docling_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py) | Clean `DoclingEngine` implementation conforming to the `OCREngine` abstraction, exposing `extract_from_file()`, `extract_text_blocks()`, and `is_available()`. |
| [`backend/tests/test_docling_pipeline.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_docling_pipeline.py) | Comprehensive test suite for Docling integration covering factory registration, file extraction, table parsing, business validation, and extraction context compatibility. |
| [`docs/DOCLING_OCR_MIGRATION_REPORT.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/DOCLING_OCR_MIGRATION_REPORT.md) | This formal implementation and verification report. |

---

## 5. Files Intentionally Preserved for Legacy Compatibility

1. [`backend/app/ocr/easyocr_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/easyocr_engine.py): Preserved as a supported production/fallback engine for CPU environments.
2. [`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py): Preserved in `SUPPORTED_ENGINES` for backward compatibility with historical PaddleOCR test runs.
3. [`backend/app/ocr/preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py): Preserved because legacy EasyOCR runs and stub engine operations still use `rasterize_pdf()` and `load_image_bytes()`.
4. [`backend/app/ocr/adaptive_preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/adaptive_preprocessing.py): Preserved for legacy EasyOCR execution.
5. [`backend/app/ocr/table_reconstruction.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py): Preserved solely for processing historical EasyOCR database records lacking native Markdown tables.
6. [`backend/app/ocr/layout.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/layout.py): Preserved for spatial ordering of legacy raw EasyOCR blocks.

---

## 6. Docling Version and APIs Used

- **Docling Version:** `2.130.0`
- **Core Dependencies Installed:**
  - `docling-core==2.99.0`
  - `docling-parse==7.22.0`
  - `docling-ibm-models==4.0.3`
  - `rapidocr==3.9.2`
  - `pypdfium2==5.10.1`
- **APIs Used:**
  - `docling.document_converter.DocumentConverter`: Primary pipeline entrypoint.
  - `docling.datamodel.pipeline_options.PdfPipelineOptions`: Pipeline configuration (`do_ocr=True`, `do_table_structure=True`).
  - `docling.document_converter.PdfFormatOption`: Format specification for PDF processing.
  - `docling_core.types.doc.DoclingDocument.export_to_markdown`: Canonical text serialization with `traverse_pictures=True` and per-page scoping via `page_no={n}`.
  - `docling_core.types.doc.DoclingDocument.iterate_items`: Traversal of document layout elements for bounding box extraction.
  - `BoundingBox.to_top_left_origin(page_h)`: Conversion of Docling's native bottom-left coordinate system to EFDI's standard top-left origin polygon coordinates.

---

## 7. Docling Configuration

The engine initializes Docling lazily in [`DoclingEngine._get_converter()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py#L35-L70):
```python
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = True
pipeline_options.do_table_structure = True

_cached_converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)
```
- **Thread Safety:** Protected by a module-level `threading.Lock()` to ensure single-instance initialization per process.
- **Process Singleton:** Cached at module level in `_cached_converter`.

---

## 8. PDF Input Handling

- **Direct Ingestion:** [`DoclingEngine.extract_from_file()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py#L71) accepts an absolute filesystem path `file_path: Union[str, Path]`.
- **No EFDI-Side Rasterization:** Docling's internal `PDFReader` renders pages via `pypdfium2`. No intermediate OpenCV or PyMuPDF transformations are applied.

---

## 9. OCR & Layout Understanding Behavior

1. **Digital PDFs:** Text layers are extracted directly with exact character accuracy while Docling's vision models detect structural blocks (headings, paragraphs, line items, summaries, parties).
2. **Scanned PDFs:** RapidOCR automatically spots text characters within image regions; `traverse_pictures=True` ensures that text blocks detected within scanned full-page pictures are serialized into the output Markdown.
3. **Reading Order:** Docling's layout parser constructs natural reading order across multi-column invoice layouts (e.g. Seller details vs. Buyer details).

---

## 10. TableFormer / Table Recognition Behavior

- **Detection:** Docling identifies table regions on the page without manual bounding-box clustering.
- **Structure Recognition:** TableFormer segments rows and columns, correctly identifying table headers (`No.`, `Description`, `Qty`, `UM`, `Net Price`, `Net Worth`, `VAT %`, `Gross Worth`).
- **Separation of Concerns:** In real test invoices, summary tables (`VAT %`, `Net Worth`, `VAT`, `Gross Worth`, `Total`) are recognized as distinct secondary tables. Trailing tax schedules do **not** leak into line-item tables.

---

## 11. Canonical Full-Text Transformation

In [`DoclingEngine.extract_from_file()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py#L98-L123):
- **Single-Page Documents:** Markdown is exported directly via `doc.export_to_markdown(traverse_pictures=True)`.
- **Multi-Page Documents:** Each page is exported with `page_no=p_idx` and formatted as:
  ```markdown
  === PAGE 1 ===
  [Markdown text of page 1]

  === PAGE 2 ===
  [Markdown text of page 2]
  ```
- **Table Representation:** Tables are rendered as standard pipe-delimited Markdown tables (`| Col1 | Col2 |` and `|---|---|`).
- **Persistence:** This canonical Markdown string is assigned to `result_data.custom_full_text` and saved directly to `OCRResult.full_text`.

---

## 12. Extraction Compatibility

- [`ExtractionService.extract()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L65) detects `ocr_result.engine_name in ("docling", "paddleocr-vl-1.6")`.
- Invokes [`parse_markdown_table(ocr_result.full_text)`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py#L78), which extracts line items cleanly from Docling's pipe-delimited tables without coordinate heuristics.
- Builds [`ExtractionContext`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L115-L124) with `table_data` and `normalized_data`.
- Reconciles financial amounts via [`extract_amount_from_table()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/table_helpers.py#L13).
- In the LLM prompt builder ([`llm_context_builder.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/llm_context_builder.py#L353)), `has_table_in_full_text` evaluates to `True`, preventing redundant table duplication.

---

## 13. RAG Compatibility

- [`RAGIngestionService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py#L22) continues to consume `OCRResult.full_text` unchanged.
- [`StructureAwareChunker`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py#L25) correctly identifies Docling's pipe-delimited tables:
  - Tables $\le 15$ rows are kept intact in a `LINE_ITEMS` chunk.
  - Tables $> 15$ rows are windowed with repeated headers.
  - Headings before tables become `HEADER` chunks; text after tables becomes `SUMMARY` and `TERMS` chunks.
  - Visual provenance bounding box references are linked using `raw_blocks`.

---

## 14. Database Verification

- **Schema Check:** The database schema for `ocr_results` is 100% identical to the pre-migration schema.
- **Columns Used:**
  - `id`: Primary key
  - `document_id`: Foreign key to `documents`
  - `engine_name`: `"docling"`
  - `page_count`: Number of pages processed
  - `full_text`: Canonical Markdown document
  - `average_confidence`: `0.98`
  - `raw_blocks`: JSONB layout detections with top-left origin 4-point polygon bboxes
  - `processing_time_ms`: Wall-clock processing time
  - `created_at`, `updated_at`: Standard timestamps
- **Zero Migrations:** No Alembic migrations were generated or needed.

---

## 15. Performance Measurements

Benchmarked on real representative invoice `uploads/03bc3832efdb45da9cc4d62a9074d36e.pdf`:

| Measurement Stage | PaddleOCR-VL-1.6 (Baseline) | Docling (New Implementation) |
| :--- | :--- | :--- |
| **Model Cold-Start / First Load** | ~60s–90s | ~76s (one-time per process) |
| **Warm Conversion Time** | ~1.5s–3.5s per page (GPU: ~350ms) | ~52.5s on Windows CPU without AVX-512 / CUDA acceleration |
| **Markdown Export Time** | ~5ms | ~12ms |
| **Table Parsing & Validation Time** | ~3ms | ~2.7ms |
| **Total In-Memory Overhead** | Minimal | Minimal |
| **Line Items Recognized** | 3 of 3 items | 3 of 3 items (100% accuracy) |
| **Validation Pass Rate** | 10 of 10 rules passed | 10 of 10 rules passed (100% pass) |
| **Document Quality Score** | 0.993 (`EXCELLENT`) | 0.993 (`EXCELLENT`) |

*Note on Latency:* On standard CPU without CUDA / GPU drivers, Docling's vision transformers (layout detection and TableFormer) run via PyTorch CPU. In production environments equipped with an NVIDIA GPU or modern server CPU, inference latency typically drops to 500ms–1.5s per document.

---

## 16. Accuracy & Regression Results

We executed the full test suite across all related components:

1. **New Docling Integration Test Suite:**
   - Command: `pytest tests/test_docling_pipeline.py`
   - Result: **6 passed in 56.67s** (100% pass rate).
2. **Phase 4 OCR Test Suite:**
   - Command: `pytest tests/test_phase4_ocr.py`
   - Result: **22 passed in 67.67s** (100% pass rate).
3. **Extraction Test Suites:**
   - Command: `pytest tests/test_extraction_context.py tests/test_phase6_extraction.py`
   - Result: **36 passed in 137.59s** (100% pass rate).
4. **RAG Test Suites:**
   - Command: `pytest tests/test_rag_ingestion.py tests/test_rag_retrieval.py`
   - Result: **16 passed in 75.19s** (100% pass rate).
5. **Legacy Backward Compatibility Test Suite:**
   - Command: `pytest tests/test_paddleocr_vl_pipeline.py`
   - Result: **6 passed in 51.64s** (100% pass rate).

---

## 17. Known Limitations

1. **CPU Execution Speed:** Vision-transformer-based TableFormer models are computationally intensive. For high-throughput workloads, deployment on GPU-enabled instances or enabling lightweight OCR options is recommended.
2. **Pre-downloaded Weights in Air-Gapped Environments:** Docling downloads HuggingFace layout and TableFormer models on first instantiation into `~/.cache/huggingface/hub`. In air-gapped production deployments, the cache directory must be pre-populated.

---

## 18. Rollback Considerations

If a rollback to PaddleOCR-VL-1.6 is ever required:
1. In `backend/.env` and `backend/app/core/config.py`: Set `OCR_DEFAULT_ENGINE=paddleocr-vl-1.6`.
2. In `backend/app/ocr/factory.py`: Swap `"paddleocr-vl-1.6"` back into `PRODUCTION_ENGINES`.
3. Because both engines adhere to the identical `full_text` Markdown and database schema contracts, no database rollbacks, migrations, or data transformations are needed.
