# EFDI Implementation Plan: Replacing the Current OCR Pipeline with PaddleOCR-VL-1.6 (REVISED & APPROVED)

---

## 1. Executive Summary

This document presents the **approved, revised architectural and implementation plan** for replacing the current Optical Character Recognition (OCR) pipeline in **EFDI (Enterprise Financial Document Intelligence)** with **PaddleOCR-VL-1.6**.

### 1.1 Context & Core Motivation
The current EFDI OCR pipeline was designed around EasyOCR's limited text-spotting capabilities, requiring extensive custom document-processing layers:
1. PyMuPDF-based PDF page rasterization.
2. Adaptive image preprocessing (denoising, contrast enhancement, Hough deskewing) via OpenCV.
3. Raw word/line detection via EasyOCR.
4. Heuristic spatial layout segmentation (header metadata, party columns, body, summary).
5. Heuristic 2D bounding-box table reconstruction (`TableReconstructor`) using keyword dictionaries and vertical overlap clustering.
6. Heuristic normalization and arithmetic validation.
7. Persistence into the PostgreSQL `ocr_results` table.

This multi-stage heuristic pipeline has critical operational flaws:
- **Semantic Bleed / Misclassification:** The 2D bounding-box table reconstructor uses heuristic vertical intervals and keyword triggers (`SUMMARY_KEYWORDS`). In invoices containing tax breakdown schedules (CGST, SGST, IGST, VAT tables), tax information is frequently captured as fake line items or appended to item descriptions.
- **Table Structure Fragility:** Borderless tables, multi-line descriptions, and split numeric tokens experience column drift and misaligned cells.
- **High Latency:** Running serial image transformations, isolated text recognition, and complex geometric clustering takes 1.2s to 3.5s per page on CPU.

### 1.2 The Final Approved Architecture
The migration supersedes all previous recommendations:
- **OLD PATH:**
  $$\text{PDF} \rightarrow \text{Rasterization} \rightarrow \text{Preprocessing} \rightarrow \text{EasyOCR} \rightarrow \text{Spatial Ordering} \rightarrow \text{Manual Table Reconstruction} \rightarrow \text{Normalization} \rightarrow \text{Validation} \rightarrow \text{DB / RAG}$$
- **FINAL TARGET PATH:**
  $$\text{PDF} \rightarrow \text{PaddleOCR-VL-1.6} \rightarrow \text{Business Validation} \rightarrow \text{DB / RAG}$$

**PaddleOCR-VL-1.6** is a 0.9B-parameter Vision-Language Model (VLM) specialized for end-to-end document parsing (96.33% accuracy on OmniDocBench v1.6). PaddleOCR-VL directly receives the PDF, handles rendering internally (via its native `PDFReader` backed by `pypdfium2`), performs multimodal visual layout perception, reading-order reconstruction, and table structure parsing, and outputs clean structured Markdown.

### 1.3 Key Architectural Decisions
1. **Direct PDF Input:** PaddleOCR-VL runs directly on the PDF. EFDI-side PyMuPDF rasterization, adaptive preprocessing, spatial ordering, and the 2D bounding-box `TableReconstructor` are **completely removed** from the primary OCR pipeline.
2. **Zero Database Schema Changes:**
   - **NO** Alembic migrations.
   - **NO** new columns (`model_version`, `table_data`, `layout_data`, etc.).
   - The existing `ocr_results` table schema remains 100% unchanged.
   - `OCRResult.full_text` remains the sole canonical representation persisted.
3. **Extraction Architecture (Runtime Table Parser):**
   - The new extraction path:
     $$\text{PaddleOCR-VL} \rightarrow \text{full\_text (Markdown)} \rightarrow \text{Markdown Table Parser} \rightarrow \text{Runtime Structured table\_data} \rightarrow \text{Extraction}$$
   - `table_data` is an **in-memory/runtime-only** structure. It is **never** persisted in the database.
   - The parser parses the structured Markdown table produced natively by PaddleOCR-VL; it does **not** reconstruct tables from coordinates, tokens, or bounding boxes.
4. **Backward Compatibility:**
   - Existing EasyOCR records in the database remain processable via legacy extraction code (branching on `engine_name`).
   - The legacy path exists only for backward compatibility and is not part of the new PaddleOCR-VL pipeline.
5. **RAG Pipeline Unchanged:**
   - The existing RAG pipeline continues consuming `OCRResult.full_text`.
   - Markdown tables remain formatted inside `full_text` for dense vector indexing and full-text search.
   - Zero RAG architectural changes.

---

## 2. Final OCR Pipeline Architecture

### 2.1 Target Pipeline Flow
```
[Uploaded Document File] (PDF / Image)
       │
       ▼
[app/services/ocr_service.py: OCRService.run_ocr()]
       │
       ├─► [app/ocr/paddle_vl_engine.py: PaddleOCRVLEngine]
       │     │
       │     │ (Submits PDF directly to PaddleOCR-VL;
       │     │  Internal PDFReader renders pages;
       │     │  Multimodal VLM performs layout, OCR, and table parsing)
       │     │
       │     ▼
       │   Native Markdown Output (with clean Markdown tables, headings, and reading order)
       │
       ├─► [Business Validation] (app/ocr/validation.py)
       │     (Checks arithmetic consistency on parsed values without altering OCR text)
       │
       ├─► [Persistence: OCRResult]
       │     - full_text = Canonical Markdown document representation
       │     - engine_name = "paddleocr-vl-1.6"
       │     - average_confidence = Token recognition confidence
       │     - raw_blocks = Block-level layout detections
       │
       ├─► Document.status = OCR_COMPLETED
       ├─► AuditAction.OCR_COMPLETED
       │
       └─► [RAG Ingestion] (app/services/rag_ingestion_service.py)
             (Consumes canonical OCRResult.full_text -> StructureAwareChunker -> Embeddings)
```

### 2.2 Components Removed from the Primary Path
The following EasyOCR-era components are **removed** from the primary PaddleOCR-VL OCR path:
1. **PyMuPDF Rasterization (`preprocessing.py: rasterize_pdf`):** PaddleOCR-VL handles PDF loading directly via its internal `PDFReader`.
2. **Adaptive Image Preprocessing (`adaptive_preprocessing.py`):** Denoising, contrast enhancement, and Hough deskewing are unnecessary; PaddleOCR-VL is robust to skew, illumination, and noise.
3. **EasyOCR Engine (`easyocr_engine.py`):** Deprecated as default production engine; preserved only for legacy test execution.
4. **Spatial Ordering (`layout.py: order_blocks_spatially`):** Redundant; PaddleOCR-VL outputs text in natural reading order.
5. **Geometric Table Reconstruction (`table_reconstruction.py: TableReconstructor`):** Direct root cause of tax/GST leakage into line items. Replaced by a lightweight Markdown table parser for extraction.
6. **Synthetic Headings (`layout.py: generate_structured_full_text`):** No synthetic section markers are injected.

---

## 3. PaddleOCR-VL Output & Canonical Full-Text Contract

### 3.1 Source of Truth: `OCRResult.full_text`
PaddleOCR-VL's native Markdown output is the sole source for the new OCR representation. It is persisted directly into `OCRResult.full_text`.

### 3.2 Preservation of Markdown Tables
Markdown tables produced by PaddleOCR-VL are preserved verbatim inside `full_text`:

```markdown
=== PAGE 1 ===
Acme Industrial Supply Ltd.
100 Industrial Parkway, Sector 4
Tax ID: US987654321

Bill To:
Global Logistics Corp
450 Enterprise Way, Suite 200

Invoice Number: INV-2026-0891
Invoice Date: 2026-06-15
Currency: USD

| # | Description | Qty | Unit | Unit Price | Net Amount | Tax % | Gross Amount |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | High Performance Ball Bearings | 50 | pcs | 45.00 | 2250.00 | 10% | 2475.00 |
| 2 | Heavy Duty Hydraulic Seal Kit | 10 | set | 120.00 | 1200.00 | 10% | 1320.00 |
| 3 | Precision Calibrated Pressure Gauge | 2 | pcs | 350.00 | 700.00 | 10% | 770.00 |

Subtotal: 4150.00
Tax (10%): 415.00
Grand Total: 4565.00

Payment Terms: Net 30 Days
```

This representation is never flattened into coordinate-based spatial text.

---

## 4. Database Contract (Strictly Unchanged)

### 4.1 Zero Schema Modifications
The existing `ocr_results` database schema is approved and **MUST NOT BE CHANGED**:
- **NO** `model_version` column.
- **NO** `table_data` column.
- **NO** `layout_data` column.
- **NO** normalized child tables (`ocr_blocks`, `ocr_tables`, `ocr_cells`).
- **NO** Alembic migrations.

### 4.2 Existing Schema Mapping

| Field | Type | How It Is Populated by PaddleOCR-VL |
|---|---|---|
| `id` | `Integer` | Auto-increment PK |
| `document_id` | `Integer` | FK to `documents.id` |
| `engine_name` | `String(30)` | Set to `"paddleocr-vl-1.6"` |
| `page_count` | `Integer` | Total pages returned by PaddleOCR-VL |
| `full_text` | `Text` | Native structured Markdown from PaddleOCR-VL |
| `average_confidence` | `Float` | Average token recognition confidence from model |
| `raw_blocks` | `JSONB` | Page and block-level layout elements (`[{"page_number": 1, "blocks": [...]}]`) |
| `processing_time_ms` | `Integer` | Total inference and validation time in ms |
| `created_at` / `updated_at` | `DateTime` | Auto timestamps |

---

## 5. Extraction Architecture

### 5.1 Runtime-Only Table Parser Flow
The extraction pipeline consumes PaddleOCR-VL output via an in-memory transformation:

```
[PaddleOCR-VL OCRResult]
       │
       ▼ (Reads OCRResult.full_text)
[app/ocr/markdown_table_parser.py: parse_markdown_table()]
       │
       ▼ (In-Memory Transformation: Pure String Parsing)
Runtime structured table_data = {
    "headers": ["Description", "Qty", "Unit Price", "Tax %", "Gross Amount"],
    "line_items": [
        {
            "description": "High Performance Ball Bearings",
            "quantity": "50",
            "unit_price": "45.00",
            "net_amount": "2250.00",
            "vat_rate": "10%",
            "gross_amount": "2475.00"
        },
        ...
    ]
}
       │
       ▼ (Injected into ExtractionContext)
[app/services/extraction_service.py: ExtractionService.extract()]
       │
       ▼
[app/extraction/llm_context_builder.py] -> Field Extraction via LLM
```

### 5.2 Critical Invariant: No Coordinate-Based Table Reconstruction
The Markdown table parser:
- Parses pipe-delimited Markdown strings (`| Header 1 | Header 2 |`).
- Maps column header names to canonical keys (`Description`, `Qty`, `Net Amount`).
- Does **NOT** inspect bounding boxes, x/y coordinates, spatial intervals, or row clusters.
- `table_data` is discarded after extraction and is **never** written to the database.

---

## 6. Backward Compatibility for Legacy EasyOCR Records

### 6.1 Coexistence Strategy
Existing documents processed with `easyocr` or `stub` remain in `ocr_results` and can be extracted without re-running OCR:

```python
# In app/services/extraction_service.py:
if ocr_result.engine_name == "paddleocr-vl-1.6":
    # New Path: parse structured Markdown table from full_text
    table_dict = parse_markdown_table(ocr_result.full_text)
else:
    # Legacy Path: preserve legacy reconstruction only for old records
    table_obj = reconstruct_table(all_page_blocks, page_width=pw, page_height=ph)
    table_dict = table_obj.to_dict()
```

- Distinguishes paths using the existing `ocr_result.engine_name` field.
- Requires zero database changes.
- Prevents breaking historical records while ensuring new records use the clean Markdown path.

---

## 7. RAG Ingestion Pipeline

### 7.1 Canonical Flow
```
OCRResult.full_text (Markdown)
       │
       ▼
[app/services/rag_ingestion_service.py]
       │
       ▼
[app/rag/chunking.py: StructureAwareChunker]
       │
       ├─► Detects Markdown table boundaries (| --- |)
       ├─► Generates LINE_ITEMS chunk (tables <= 15 rows intact; > 15 rows sliding window)
       ├─► Generates HEADER chunk for pre-table text
       └─► Generates SUMMARY chunk for post-table totals
       │
       ▼
Embeddings & Vector Store Persistence (document_chunks table)
```

- **NO** changes to RAG database tables.
- **NO** changes to hybrid search, RRF rank fusion, or cross-encoder reranking.
- RAG retrieves higher quality chunks because table structure and tax summaries are cleanly separated.

---

## 8. Business Validation vs. OCR Understanding

### 8.1 Separation of Responsibilities
- **PaddleOCR-VL:** Responsible for visual document understanding, OCR transcription, reading order, and table structure parsing.
- **EFDI Business Validation:** Responsible for application-specific arithmetic checks:
  1. $\text{Quantity} \times \text{Unit Price} \approx \text{Net Amount}$
  2. $\sum \text{Net Amounts} \approx \text{Subtotal}$
  3. $\text{Subtotal} + \text{Total Tax} \approx \text{Grand Total}$
- Obsolete OCR preprocessing heuristics (such as guessing corrupted `%` glyphs from numbers like `'1090'`) are removed from the new path.

---

## 9. PaddleOCR-VL API & PDF Support Verification

### 9.1 Technical Verification Findings
- **Package:** `paddleocr` 3.7.0, `paddlepaddle` 3.2.2, `paddlex` 3.7.1.
- **Pipeline Class:** `from paddleocr import PaddleOCRVL`.
- **Pipeline Version:** `pipeline_version="v1.6"` maps to `"PaddleOCR-VL-1.6"`.
- **Direct PDF Input:** Verified in `paddlex.inference.utils.io.readers.PDFReader`. PaddleX natively loads and renders PDFs via `pypdfium2`.
- **Inference Call:** `results = pipeline.predict(file_path)` accepts a PDF path directly.
- **Output Structure:** `results` is a list of `PaddleOCRVLResult` page objects.
- **Markdown Access:** `res.markdown` or `res._to_markdown(pretty=False)` returns the structured Markdown page string containing Markdown tables.
- **Block Layout:** `res["parsing_res_list"]` contains detected blocks with labels (`table`, `paragraph`, `header`, `footer`) and bounding boxes.

---

## 10. File-by-File Implementation Plan

### 10.1 New Files
1. **[`backend/app/ocr/paddle_vl_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_vl_engine.py):**
   - Implements `PaddleOCRVLEngine(OCREngine)`.
   - Manages lazy thread-safe singleton loading of `PaddleOCRVL(pipeline_version="v1.6")`.
   - Submits PDF or image file path directly to `pipeline.predict()`.
   - Returns structured `OCRResultData` with canonical Markdown `full_text` and layout detections.
2. **[`backend/app/ocr/markdown_table_parser.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py):**
   - Implements `parse_markdown_table(text: str) -> dict`.
   - Pure string-based Markdown table parser that produces in-memory `table_data` for extraction without geometric heuristics.
3. **[`backend/tests/test_paddleocr_vl_pipeline.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_paddleocr_vl_pipeline.py):**
   - Unit and integration tests for `PaddleOCRVLEngine`, `markdown_table_parser`, direct PDF intake, and tax non-leakage.

### 10.2 Modified Files
1. **[`backend/app/ocr/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/factory.py):**
   - Register `"paddleocr-vl-1.6"` as a production engine in `PRODUCTION_ENGINES` and `SUPPORTED_ENGINES`.
   - Wire `get_ocr_engine("paddleocr-vl-1.6")` to `PaddleOCRVLEngine`.
2. **[`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py):**
   - Set `OCR_DEFAULT_ENGINE = "paddleocr-vl-1.6"`.
   - Add optional `PADDLE_VL_DEVICE = "cpu"` and `PADDLE_VL_MODEL_DIR = None`.
3. **[`backend/app/services/ocr_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/ocr_service.py):**
   - For `paddleocr-vl-1.6`: pass the document file path directly to `engine.extract_document(file_path)`.
   - Bypass PyMuPDF rasterization, adaptive preprocessing, spatial ordering, and legacy table reconstruction.
   - Run business validation on parsed table data and persist canonical `full_text`.
4. **[`backend/app/services/extraction_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py):**
   - For `paddleocr-vl-1.6` results: call `parse_markdown_table(ocr_result.full_text)` to build runtime in-memory `table_data`.
   - For legacy results: fall back to legacy `reconstruct_table()`.
   - `table_data` remains purely in memory.
5. **[`backend/app/routers/ocr.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py):**
   - Update `_to_response` to parse table data from Markdown `full_text` for `paddleocr-vl-1.6` rather than running legacy geometric reconstruction.

### 10.3 Unchanged Files
- **NO** database migrations (`backend/alembic/versions/*`).
- **NO** model changes (`backend/app/models/ocr_result.py`).
- **NO** RAG changes (`backend/app/services/rag_ingestion_service.py`, `backend/app/services/rag_service.py`).
- **NO** extraction schema changes (`backend/app/extraction/field_schemas.py`).

---

## 11. Acceptance Criteria Checklist

| Requirement | Implementation Validation |
|---|---|
| 1. Direct PDF Input | Submits PDF file path directly to PaddleOCR-VL without EFDI PyMuPDF rasterization. |
| 2. Removal of Legacy OCR Path | PyMuPDF, OpenCV preprocessing, spatial reordering, and geometric table reconstruction are bypassed for all new OCR runs. |
| 3. Markdown Structure in `full_text` | `OCRResult.full_text` contains native Markdown with pipe-delimited table syntax (`\| --- \|`). |
| 4. Zero Database Schema Changes | Zero Alembic migrations created; no columns added to `ocr_results`. |
| 5. Runtime-Only Table Data | `table_data` is parsed in-memory during extraction and never written to the DB. |
| 6. Legacy Compatibility | Existing EasyOCR records continue to be processed through the legacy extraction path. |
| 7. RAG Pipeline Continuity | `StructureAwareChunker` chunks Markdown tables into `LINE_ITEMS` and totals into `SUMMARY`. |
| 8. Zero Tax Leakage | Tax schedules (CGST/SGST/VAT) are never captured as line items. |
