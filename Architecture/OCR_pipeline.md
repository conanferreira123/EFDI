# OCR Pipeline — Current Architecture and Data Flow

---

## 1. Executive Summary

The Optical Character Recognition (OCR) pipeline in the Enterprise Financial Document Intelligence (EFDI) system converts uploaded financial documents (PDFs, PNGs, and JPEGs) into structured, machine-readable text and spatial bounding-box representations.

Key aspects of the current implementation:
1. **Triggering Model:** OCR does not run automatically on upload. It is an explicit, on-demand step triggered via `POST /api/v1/ocr/documents/{document_id}/run`.
2. **Engine Selection:** The primary production engine is **EasyOCR** (`app/ocr/easyocr_engine.py`), backed by PyTorch and CRAFT text detection. A fallback `StubOCREngine` exists for test environments. PaddleOCR is deliberately excluded from execution due to native crashes in CPU/ARM environments.
3. **Multi-Page Handling:** Multi-page PDFs are rasterized to individual page images (200 DPI BGR arrays) using PyMuPDF (`fitz`). Each page undergoes automated image quality analysis and adaptive preprocessing (deskewing, CLAHE contrast enhancement) before being processed independently by the OCR engine.
4. **Spatial Layout & Structured Full Text:** Raw bounding boxes from CRAFT are analyzed by a spatial layout engine (`app/ocr/layout.py`) that organizes text into semantic sections (Top Header, 2-Column Party Information, Line Items Table, and Summary/Totals). This produces an enriched `structured_full_text` stored as `full_text`.
5. **Table Reconstruction & Normalization:** A 2D geometric analyzer (`app/ocr/table_reconstruction.py`) clusters line items into columns (`description`, `quantity`, `unit_price`, `net_amount`, `gross_amount`, `vat_rate`), and a normalization layer (`app/ocr/normalization.py`) parses numbers, dates, and units.
6. **Persistence Asymmetry:** Raw OCR detections (`raw_blocks`) and the synthesized `full_text` are persisted in PostgreSQL (`ocr_results` table). However, **table reconstruction, normalization, and quality scores are NOT stored in dedicated database columns**; they are ephemeral structures recomputed on-the-fly when requested by the API or downstream extraction.
7. **Downstream Handoff:** Classification consumes **only `full_text`** (as a flat string). Extraction consumes an `ExtractionContext` built from `full_text`, `raw_blocks`, and table structures re-extracted on-the-fly from the first page (`raw_blocks[0]`).

---

## 2. Current OCR Architecture

```
[ Uploaded Document on Disk ] (uploads/<stored_filename>)
             │
             ▼
[ POST /api/v1/ocr/documents/{id}/run ] (app/routers/ocr.py)
             │
             ▼
[ OCRService.run_ocr ] (app/services/ocr_service.py)
             │
             ├──────────────────────────────────────────────────────┐
             ▼ (PDF)                                                ▼ (PNG/JPG)
  [ rasterize_pdf (PyMuPDF) ]                            [ load_image_bytes (PIL/cv2) ]
  DPI=200, BGR np.ndarray                                BGR np.ndarray
             │                                                      │
             └──────────────────────────┬───────────────────────────┘
                                        │
                                        ▼  list of page images
                        ┌───────────────────────────────┐
                        │   AdaptivePreprocessor        │
                        │   - Skew estimation (Hough)   │
                        │   - CLAHE contrast adjustment │
                        │   - Clean digital pass-thru   │
                        └───────────────┬───────────────┘
                                        │ preprocessed page images
                                        ▼
                        ┌───────────────────────────────┐
                        │   EasyOCREngine               │
                        │   (Reader.readtext,           │
                        │    detail=1, add_margin=0.10) │
                        └───────────────┬───────────────┘
                                        │ list[OCRTextBlock] per page
                                        ▼
             ┌──────────────────────────────────────────────────────┐
             │ FOR EACH PAGE (page_number=1..N):                    │
             │                                                      │
             │ 1. Assemble raw_blocks dict (text, conf, bbox)       │
             │ 2. reconstruct_table (2D geometric column intervals) │
             │ 3. build_structured_page (Header, Parties, Table)    │
             │ 4. order_blocks_spatially (reading order sort)       │
             └──────────────────────────┬───────────────────────────┘
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │ generate_structured_full_text │
                        │ Creates markdown-formatted    │
                        │ full_text with sections       │
                        └───────────────┬───────────────┘
                                        │
                                        ▼
       ┌─────────────────────────────────────────────────────────────────┐
       │ EPHEMERAL DERIVED PROCESSING (Calculated on raw_blocks[0] only) │
       │ 1. reconstruct_table(raw_blocks[0])                             │
       │ 2. normalize_table_data(table_dict)                             │
       │ 3. validate_ocr_output(normalized_items, full_text)             │
       │ 4. calculate_quality_score(conf, full_text, table, validation)  │
       └────────────────────────────────┬────────────────────────────────┘
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │ OCRResultRepository.create    │
                        │ Persists to table:            │
                        │   - full_text                 │
                        │   - raw_blocks (JSONB)        │
                        │   - average_confidence        │
                        │   - page_count                │
                        │   - processing_time_ms        │
                        └───────────────┬───────────────┘
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼                                                     ▼
 [ Classification Handoff ]                               [ Extraction Handoff ]
 ClassificationService.classify                          ExtractionService.extract
 Receives: ONLY ocr_result.full_text                     Receives: ocr_result.full_text,
                                                                   ocr_result.raw_blocks,
                                                                   recomputed table_data
```

---

## 3. OCR Entry Point

### Initiation
- **API Endpoint:** `POST /api/v1/ocr/documents/{document_id}/run`
- **File:** [`backend/app/routers/ocr.py:88-119`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/ocr.py#L88-L119)
- **Function:** `run_ocr(document_id, payload, db, current_user)`
- **Authentication & RBAC:** Protected by `get_current_user`. Scoped via `DocumentService.get_for_user(document_id, current_user)` (Analysts can only run OCR on their own uploads; Managers/Auditors/Admins can run on any document).
- **Request Payload:** `OCRRunRequest(engine: str | None = None)`

### Call Chain
1. `app/routers/ocr.py:run_ocr()`:
   - Resolves target engine: `payload.engine or get_default_ocr_engine(db)` (checks `system_settings` table for `default_ocr_engine`, falling back to `settings.OCR_DEFAULT_ENGINE = "easyocr"`).
   - Calls `OCRService(db).run_ocr(document, engine_name=engine_name)`.
2. `app/services/ocr_service.py:OCRService.run_ocr()`:
   - Emits `AuditAction.OCR_STARTED` log to `audit_logs`.
   - Obtains engine instance via `app/ocr/factory.py:get_ocr_engine(engine_name)`.
   - Resolves disk path: `app/utils/file_storage.py:get_file_path(document.stored_filename)`.
   - Reads raw bytes from disk.
   - Executes rasterization/preprocessing -> text block extraction -> spatial layout -> table reconstruction -> validation -> persistence -> status update.
   - Emits `AuditAction.OCR_COMPLETED` log.
   - Returns persisted `OCRResult` ORM instance.
3. `app/routers/ocr.py:_to_response(ocr_result)`:
   - Reconstructs table, normalizes items, computes validation and quality score on-the-fly for `raw_blocks[0]`.
   - Returns HTTP 201 with `OCRResultResponse`.

---

## 4. Input to OCR

### Document Storage & Identification
- Documents are uploaded via `POST /api/v1/documents/upload` or `POST /api/v1/documents/upload/bulk`.
- Files are saved on the filesystem under `uploads/<uuid>.<ext>` (`settings.UPLOAD_DIR`).
- The database record in `documents` stores:
  - `stored_filename`: string UUID path (e.g. `2dbb7754f9a04a37b1207e4d8e5223ab.pdf`)
  - `original_filename`: human filename provided at upload
  - `mime_type`: MIME string (`application/pdf`, `image/png`, `image/jpeg`)
  - `file_hash`: SHA-256 hex digest
  - `file_size_bytes`: integer file size

### What the OCR Service Reads
- `OCRService.run_ocr()` receives only the `Document` ORM instance.
- It opens `uploads/<stored_filename>` directly in binary read mode (`with open(file_path, "rb") as f: file_bytes = f.read()`).

### Supported Formats & Size Limits
- Defined in [`backend/app/utils/file_storage.py:12-22`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/utils/file_storage.py#L12-L22):
  - `.pdf` -> `application/pdf`
  - `.png` -> `image/png`
  - `.jpg`, `.jpeg` -> `image/jpeg`
- Maximum file size: `settings.MAX_UPLOAD_SIZE_MB = 25` (26,214,400 bytes).

---

## 5. Document / Page Processing

### PDF Rasterization
- **Module:** [`backend/app/ocr/preprocessing.py:29-67`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py#L29-L67)
- **Library:** PyMuPDF (`fitz`).
- **Function:** `rasterize_pdf(pdf_bytes: bytes, dpi: int = 200) -> list[np.ndarray]`
- **Processing Steps:**
  1. Opens PDF stream: `fitz.open(stream=pdf_bytes, filetype="pdf")`.
  2. Checks encryption: if `doc.is_encrypted`, raises `FileProcessingException("PDF is password-protected...")`.
  3. Calculates scaling matrix: `zoom = dpi / 72.0` (at 200 DPI, zoom ≈ 2.7778).
  4. Renders each page to a pixmap: `page.get_pixmap(matrix=matrix, alpha=False)`.
  5. Converts pixel buffer to RGB NumPy array: `np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(h, w, n)`.
  6. Converts color space: `cv2.cvtColor(image, cv2.COLOR_RGB2BGR)`.
  7. Returns list of BGR NumPy arrays, one per page.

### Image Ingestion
- **Module:** [`backend/app/ocr/preprocessing.py:69-83`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py#L69-L83)
- **Library:** Pillow (`PIL.Image`) and OpenCV (`cv2`).
- **Function:** `load_image_bytes(image_bytes: bytes) -> np.ndarray`
- Decodes image bytes via PIL (to handle orientation and EXIF headers safely), converts to RGB array, then converts to OpenCV BGR format.

### Adaptive Preprocessing
- **Module:** [`backend/app/ocr/adaptive_preprocessing.py:108-162`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/adaptive_preprocessing.py#L108-L162)
- **Class:** `AdaptivePreprocessor.process(image) -> (processed_image, decision)`
- Every page (PDF or image) passes through this analyzer:
  - `ImageQualityAnalyzer.analyze(image)` extracts:
    - `mean_brightness`: mean grayscale value (0–255)
    - `contrast_std`: standard deviation of pixel intensities
    - `sharpness_laplacian`: variance of Laplacian filter (higher = sharper)
    - `estimated_skew_angle`: median angle of text lines detected via Canny edges and probabilistic Hough transform (`HoughLinesP`)
  - **Decision Logic:**
    1. *Clean digital vector render:* If `sharpness > 200.0`, `contrast > 45.0`, and `abs(skew) < 0.5°` -> Strategy: `PASS_THROUGH_CLEAN_DIGITAL`. Returns image untouched.
    2. *Deskew:* If `abs(skew) > 0.8°` -> rotates image by `-estimated_skew_angle` using affine transform (`cv2.warpAffine`).
    3. *Contrast enhancement:* If `contrast_std < 35.0` -> applies CLAHE (Contrast Limited Adaptive Histogram Equalization, `clipLimit=2.0`, `tileGridSize=(8, 8)`) to the L-channel in LAB color space.

---

## 6. OCR Engine

### Active Engine: EasyOCR
- **Module:** [`backend/app/ocr/easyocr_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/easyocr_engine.py)
- **Class:** `EasyOCREngine(OCREngine)`
- **Engine Name:** `"easyocr"`
- **Language List:** Default `["en"]`
- **GPU Usage:** Configurable (`gpu=False` by default in service). Includes automated PyTorch CUDA check: if GPU is requested but `torch.cuda.is_available()` is false, automatically falls back to CPU without throwing an exception.
- **Singleton Caching:** Reader instance is lazily initialized and protected by a `threading.Lock()` (`_cached_reader`), ensuring model weights are loaded into memory only once per Python process.

### Inference Execution
- **Method:** `EasyOCREngine.extract_text_blocks(image: np.ndarray) -> list[OCRTextBlock]`
- **Call:** `reader.readtext(image, detail=1, add_margin=0.10)`
  - `detail=1`: Returns full details: `(bounding_box, text, confidence)`.
  - `add_margin=0.10`: Adds 10% padding around CRAFT bounding boxes to prevent character clipping on edges (especially currency symbols and leading digits).
- **Transformation:**
  - `bbox` corner points `[[x1,y1], [x2,y2], [x3,y3], [x4,y4]]` are converted to standard Python floats.
  - Text is cast to string and confidence to float.
  - Returns `list[OCRTextBlock]`.

### Alternative Engines
- **`StubOCREngine` (`app/ocr/stub_engine.py`):** Produces deterministic synthetic financial text blocks for unit tests.
- **`PaddleOCREngine` (`app/ocr/paddle_engine.py`):** Excluded from selectable engines (`app/ocr/factory.py:22-32`) due to segmentation faults with native libraries on ARM64/CPU environments.

---

## 7. Raw OCR Output

### In-Memory Representation
Defined in [`backend/app/ocr/base.py:18-24`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/base.py#L18-L24):
```python
@dataclass
class OCRTextBlock:
    text: str
    confidence: float                  # 0.0 to 1.0
    bounding_box: list[list[float]]    # 4-point polygon: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
```

### JSON Structure in `raw_blocks`
In `OCRService.run_ocr()`, per-page blocks are wrapped into a dictionary and appended to `raw_blocks`:
```json
[
  {
    "page_number": 1,
    "page_width": 1700,
    "page_height": 2200,
    "blocks": [
      {
        "text": "TAX INVOICE",
        "confidence": 0.9924,
        "bounding_box": [
          [650.0, 85.0],
          [1050.0, 85.0],
          [1050.0, 125.0],
          [650.0, 125.0]
        ]
      },
      {
        "text": "Invoice Number: INV-2026-001",
        "confidence": 0.9781,
        "bounding_box": [
          [120.0, 180.0],
          [480.0, 180.0],
          [480.0, 210.0],
          [120.0, 210.0]
        ]
      }
    ]
  }
]
```

---

## 8. OCR Normalization

### Module & Purpose
- **Module:** [`backend/app/ocr/normalization.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/normalization.py)
- **Principle:** Strict separation between raw data and normalized data. Raw OCR strings and bounding boxes are **never overwritten or mutated**.

### Normalization Operations
1. **Whitespace Normalization (`normalize_whitespace`):** Replaces non-breaking spaces (`\u00a0`, `\u202f`) with standard spaces and collapses multiple consecutive spaces.
2. **Numeric Parsing (`parse_numeric`):**
   - Handles US/UK format: `1,234.50` -> `1234.50`
   - Handles European format: `1.234,50` -> `1234.50`
   - Handles space-delimited thousands: `1 394,67` -> `1394.67`
   - Strips currency symbols (`$`, `€`, `£`, `₹`, `Rs.`)
   - Repairs punctuation anomalies: `52.,083.00` -> `52083.00`
3. **Unit Normalization (`normalize_unit`):** Standardizes unit strings (`PCS`, `Pieces`, `Stk`, `EA` -> `pcs`).
4. **Date Parsing (`parse_date_to_iso`):** Tests 9 standard date formats (`%d/%m/%Y`, `%Y-%m-%d`, `%d.%m.%Y`, etc.) and outputs standard ISO `YYYY-MM-DD`.
5. **VAT Rate Normalization & Interpretation (`interpret_vat_rate`):**
   - Parses percentage strings (`10%`, `19.0%`).
   - If OCR text is ambiguous (e.g. `1090`), checks if net amount and gross amount satisfy `(gross - net) / net ≈ 0.10`, resolving `1090` to `10%` with verified arithmetic evidence.

### Data Structure
Each line item produces a `NormalizedLineItem`:
```python
NormalizedLineItem(
    raw_item_number="1",       normalized_item_number=1,
    raw_description="Laptop",  normalized_description="Laptop",
    raw_quantity="2.00",       normalized_quantity=2.0,
    raw_unit_price="1,500.00", normalized_unit_price=1500.0,
    raw_net_amount="3,000.00", normalized_net_amount=3000.0,
    raw_vat_rate="10%",        normalized_vat_rate=0.10,
    vat_interpretation="10%",
    raw_gross_amount="3,300.00", normalized_gross_amount=3300.0,
    confidence=0.98,
    raw_blocks=[...]
)
```

---

## 9. Table Reconstruction

### Module & Geometry Analyzer
- **Module:** [`backend/app/ocr/table_reconstruction.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py)
- **Class:** `TableReconstructor(blocks, page_width, page_height)`
- **Function:** `reconstruct_table(blocks, page_width, page_height) -> ReconstructedTable`

### Step-by-Step Table Reconstruction Flow
1. **Header Detection:**
   - Scans blocks below the top 5% of the page against predefined multi-lingual header keywords across 8 columns:
     - `item_number`: `"NO."`, `"SL NO"`, `"POS"`, `"ARTICLE"`, `"ITEM"`
     - `description`: `"DESCRIPTION"`, `"PARTICULARS"`, `"BEZEICHNUNG"`, `"DETAILS"`
     - `quantity`: `"QTY"`, `"QUANTITY"`, `"MENGE"`
     - `unit`: `"UNIT"`, `"UOM"`, `"EINHEIT"`
     - `unit_price`: `"UNIT PRICE"`, `"RATE"`, `"PREIS"`, `"NETTO-PREIS"`
     - `net_amount`: `"NET WORTH"`, `"NET AMOUNT"`, `"BETRAG"`, `"NETTOBETRAG"`
     - `vat_rate`: `"VAT %"`, `"TAX %"`, `"MWST"`, `"MWST%"`
     - `gross_amount`: `"GROSS WORTH"`, `"GROSS AMOUNT"`, `"TOTAL AMOUNT"`, `"BRUTTOBETRAG"`
   - Clusters candidates into a horizontal header band (within 40px vertical tolerance).
   - **Gating Rule:** Requires at least **2 distinct recognized column headers** to qualify as a table. If fewer than 2 headers are found, returns an empty table.
2. **Column Interval Derivation:**
   - For each detected column, computes horizontal bounds `[x_min, x_max]`.
   - Boundaries are established using inter-column gutters (midpoints between adjacent column bounding boxes) to prevent overlapping columns.
3. **Table Boundary Detection:**
   - Identifies bottom Y-limit using summary keywords: `TOTAL`, `SUBTOTAL`, `GRAND TOTAL`, `GESAMTBETRAG`, `BANK DETAILS`, `PAYMENT TERMS`.
4. **Row Line Clustering:**
   - Filters body blocks strictly between header bottom and summary top.
   - Clusters blocks into row lines using vertical overlap (`y_overlap > 0.3 * line_h` or center distance `|cy - avg_cy| <= max(14, line_h * 0.65)`).
5. **Cell Assignment & Multiline Merging:**
   - Assigns each text block in a row line to the column with maximum horizontal overlap and center containment.
   - Detects whether a line starts a new line item (contains numeric amounts or an item number) or is a continuation description.
   - Multiline continuation lines are automatically appended to `current_item.description`.
6. **Output:** `ReconstructedTable` containing `line_items: list[StructuredLineItem]`.

---

## 10. OCR Quality / Metadata

EFDI computes multi-dimensional quality metrics to avoid conflating character recognition certainty with overall document quality.

### Components
1. **Average Character Confidence:**
   - Generated by EasyOCR per block; averaged across all blocks on all pages.
   - Stored in `ocr_results.average_confidence`.
2. **Mathematical Validation (`app/ocr/validation.py`):**
   - Evaluates arithmetic integrity of normalized line items:
     - Rule 1: `quantity * unit_price == net_amount` (within 1.0 abs or 2% rel tolerance)
     - Rule 2: `net_amount * (1 + vat_rate) == gross_amount`
     - Rule 3: `sum(net_amount) == subtotal`
     - Rule 4: `sum(gross_amount) == grand_total`
   - Produces `DocumentValidationResult` with passed/failed flags and severity (`INFO`, `WARNING`, `ERROR`).
3. **Composite Quality Scoring (`app/ocr/quality_scoring.py`):**
   - Weighted composite formula:
     $$\text{Score} = 0.35 \times \text{Confidence} + 0.25 \times \text{Structural} + 0.25 \times \text{Validation} + 0.15 \times \text{Completeness}$$
   - Produces `quality_grade` (`EXCELLENT` $\ge 0.85$, `GOOD` $\ge 0.70$, `FAIR` $\ge 0.50$, `POOR` $< 0.50$) and explanatory notes.

---

## 11. OCR Result Object

### In-Memory Assembly
In `OCRService.run_ocr()`, the final result is assembled in two representations:
1. `OCRResultData` (`app/ocr/base.py`):
   - Holds list of `OCRPageResult` instances with spatially ordered blocks.
   - `custom_full_text`: Holds the output of `generate_structured_full_text(structured_pages)`.
2. `OCRResult` ORM Instance (`app/models/ocr_result.py`):
   - Created via `OCRResultRepository.create()`.
   - Snapshots `full_text`, `raw_blocks`, `average_confidence`, `page_count`, and `processing_time_ms`.

---

## 12. Database Persistence

### Schema Details
- **Table Name:** `ocr_results`
- **Model:** [`backend/app/models/ocr_result.py:23-51`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py#L23-L51)
- **Relationship:** `Document.ocr_results` (One-to-Many, `lazy="select"`, ordered by `created_at DESC`).
- **Append-Only Policy:** Re-running OCR creates a **new row** in `ocr_results`; previous runs are preserved for historical auditability.

### Column Mapping Table

| Column Name | SQL Type | Nullable | Content Description | Raw vs Derived |
|---|---|---|---|---|
| `id` | `INTEGER` (PK) | No | Auto-increment primary key | System |
| `document_id` | `INTEGER` (FK) | No | Foreign key referencing `documents.id` (Indexed) | System |
| `engine_name` | `VARCHAR(30)` | No | Name of OCR engine used (`"easyocr"`, `"stub"`) | Raw Config |
| `page_count` | `INTEGER` | No | Total number of pages processed | Derived |
| `full_text` | `TEXT` | No | Full extracted text (structured markdown if enabled) | **Derived** |
| `average_confidence` | `FLOAT` | No | Mean character confidence across all blocks | **Derived** |
| `raw_blocks` | `JSONB` | No | Full list of per-page raw text, bounding boxes, confidences | **Raw OCR** |
| `processing_time_ms` | `INTEGER` | Yes | Total pipeline execution time in milliseconds | Derived |
| `created_at` | `TIMESTAMP` | No | Creation timestamp (UTC) | System |
| `updated_at` | `TIMESTAMP` | No | Last update timestamp (UTC) | System |

### Crucial Persistence Finding
**`table_data`, `normalized_data`, `validation_results`, and `quality_score` are NOT persisted in PostgreSQL columns.**
They are emitted to `AuditService` log details at OCR completion, but any downstream API consumer or extraction component must re-generate them from `raw_blocks`.

---

## 13. Data Passed to Classification

- **Handoff Location:** [`backend/app/services/classification_service.py:26-36`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/classification_service.py#L26-L36)
- **Code:**
  ```python
  ocr_result = self.ocr_repo.get_latest_for_document(document.id)
  engine = get_classification_engine(engine_name or "rule_based")
  result_data = engine.classify(ocr_result.full_text)
  ```
- **What Classification Receives:** **ONLY `ocr_result.full_text`** (a single Python string).
- **What Classification DOES NOT Receive:**
  - No `raw_blocks`
  - No bounding boxes or coordinate data
  - No confidence scores
  - No page counts or page boundaries
  - No table structures or line items

---

## 14. Data Passed to Extraction

- **Handoff Location:** [`backend/app/services/extraction_service.py:40-104`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L40-L104)
- **What Extraction Receives (`ExtractionContext`):**
  - `full_text`: `ocr_result.full_text`
  - `document_type`: from latest `classification_result.predicted_type`
  - `raw_blocks`: `ocr_result.raw_blocks`
  - `table_data`: **Re-computed dynamically** from `raw_blocks[0]` via `reconstruct_table()`
  - `normalized_data`: **Re-computed dynamically** from `table_data` via `normalize_table_data()`
  - `ocr_validation`: **Re-computed dynamically** via `validate_ocr_output()`
  - `ocr_quality`: **Re-computed dynamically** via `calculate_quality_score()`
  - `document_id`: `document.id`

### How LLM Extraction Uses It
In [`backend/app/extraction/llm_context_builder.py:278-306`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/llm_context_builder.py#L278-L306):
- Primary text is wrapped under `=== PRIMARY DOCUMENT OCR TEXT ===`.
- `table_data` is converted to a clean Markdown grid under `=== RECONSTRUCTED LINE ITEMS TABLE ===`.
- `raw_blocks[0]` is segmented into Left and Right columns under `=== SPATIAL PARTY & HEADER LAYOUT ===`.
- Quality signals are appended under `=== OCR QUALITY SIGNALS ===`.

---

## 15. Complete Data Flow

```
+-----------------------------------------------------------------------------------+
| 1. FILE UPLOAD & DISK STORAGE                                                     |
| Client uploads file -> saved to uploads/<uuid>.<ext> -> documents row created     |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 2. OCR RUN TRIGGER                                                                |
| POST /api/v1/ocr/documents/{id}/run -> OCRService.run_ocr()                       |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 3. RASTERIZATION & DECODING                                                       |
| PDF: rasterize_pdf (PyMuPDF, 200 DPI) -> list of BGR NumPy arrays                 |
| Image: load_image_bytes (PIL + OpenCV) -> single BGR NumPy array                  |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 4. ADAPTIVE PREPROCESSING                                                         |
| Measure brightness, contrast, sharpness, skew -> Apply Deskew and CLAHE if needed |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 5. EASYOCR ENGINE INFERENCE                                                       |
| EasyOCR Reader.readtext(image, detail=1, add_margin=0.10)                         |
| Returns list of OCRTextBlock(text, confidence, bounding_box)                     |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 6. SPATIAL STRUCTURING & TABLE RECONSTRUCTION                                     |
| Per Page:                                                                         |
|   - raw_blocks.append({page_number, page_w, page_h, blocks: [...]})               |
|   - table_obj = reconstruct_table(blocks, page_w, page_h)                         |
|   - structured_page = build_structured_page(blocks, table, ...)                   |
|   - ordered_blocks = order_blocks_spatially(blocks)                               |
| All Pages:                                                                        |
|   - full_text = generate_structured_full_text(structured_pages)                   |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 7. EPHEMERAL VALIDATION & QUALITY (First Page raw_blocks[0] only)                 |
| normalize_table_data -> validate_ocr_output -> calculate_quality_score            |
| (Logged to AuditAction.OCR_COMPLETED details)                                     |
+-----------------------------------------------------------------------------------+
                                          │
                                          ▼
+-----------------------------------------------------------------------------------+
| 8. DATABASE COMMIT                                                                |
| Insert into ocr_results (document_id, engine_name, page_count, full_text,         |
|                          average_confidence, raw_blocks, processing_time_ms)      |
| Update documents.status = 'OCR_COMPLETED' (or 'REJECTED' if full_text is empty)   |
+-----------------------------------------------------------------------------------+
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   ▼                                             ▼
+------------------------------------+       +------------------------------------+
| 9. CLASSIFICATION HANDOFF          |       | 10. EXTRACTION HANDOFF             |
| Input: ocr_result.full_text string |       | Input: ExtractionContext           |
| Action: Keyword / token scoring    |       |   - full_text                      |
| Output: predicted_type saved to DB |       |   - raw_blocks                     |
+------------------------------------+       |   - recomputed table_data          |
                                             |   - recomputed normalized_data     |
                                             | Action: Rule/LLM/Hybrid extraction |
                                             | Output: extraction_results saved   |
+------------------------------------+       +------------------------------------+
```

---

## 16. Data Transformation Table

| Stage | Input | Operation | Output | Persisted? |
|---|---|---|---|---|
| **1. File Ingestion** | Upload HTTP multipart file | `DocumentService.upload()` writes bytes to disk | File at `uploads/<uuid>.<ext>`, `Document` row | **Yes** (`documents`) |
| **2. Rasterization** | PDF bytes / Image bytes | PyMuPDF `get_pixmap` (200 DPI) or PIL decode | `list[np.ndarray]` (BGR images) | No (in-memory) |
| **3. Preprocessing** | Raw page image | `AdaptivePreprocessor`: Skew Hough check + CLAHE | Cleaned BGR `np.ndarray`, `decision` | No (decision in audit log) |
| **4. Recognition** | Cleaned BGR image | `EasyOCREngine.extract_text_blocks()` (CRAFT+CRNN) | `list[OCRTextBlock]` (text, conf, bbox) | No (in-memory) |
| **5. Raw JSON Assembly** | `list[OCRTextBlock]`, page dimensions | Formats dictionary with page number, dims, blocks | `raw_blocks` (`list[dict]`) | **Yes** (`ocr_results.raw_blocks`) |
| **6. Table Reconstruction** | `list[OCRTextBlock]` | `TableReconstructor.reconstruct()` column analysis | `ReconstructedTable` (`line_items`) | No (ephemeral) |
| **7. Spatial Ordering** | `list[OCRTextBlock]` | `order_blocks_spatially()` vertical band sort | Sorted `list[OCRTextBlock]` | No (in-memory) |
| **8. Structured Page** | Ordered blocks, ReconstructedTable | `build_structured_page()` section allocation | `StructuredDocumentPage` | No (in-memory) |
| **9. Full Text Generation**| `list[StructuredDocumentPage]` | `generate_structured_full_text()` | `full_text` Markdown string | **Yes** (`ocr_results.full_text`) |
| **10. Normalization** | `ReconstructedTable` (page 0) | `normalize_table_data()` numeric/date parsing | `list[NormalizedLineItem]` | No (ephemeral) |
| **11. Validation** | `list[NormalizedLineItem]`, `full_text` | `validate_ocr_output()` arithmetic checks | `DocumentValidationResult` | No (ephemeral) |
| **12. Quality Scoring** | Confidence, `full_text`, table, validation | `calculate_quality_score()` multi-factor score | `OCRQualityBreakdown` | No (audit details only) |
| **13. Persistence** | `full_text`, `raw_blocks`, metrics | `OCRResultRepository.create()` | `OCRResult` ORM entity | **Yes** (`ocr_results`) |
| **14. Classification** | `ocr_result.full_text` | `ClassificationService.classify()` regex scoring | `ClassificationResult` row | **Yes** (`classification_results`) |
| **15. Extraction** | `ocr_result.full_text`, `raw_blocks` | `ExtractionService.extract()` builds context | `ExtractionResult` row | **Yes** (`extraction_results`) |

---

## 17. Raw vs Derived Data

### Raw Data (Direct from OCR Engine / Document)
- **`raw_blocks`:** Exact text strings returned by the CRNN model, exact floating-point polygon coordinates `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]` returned by the CRAFT detector, and character certainty confidence (0.0–1.0).
- **Page Dimensions:** Exact pixel width and height of the rasterized page.
- **Engine Name:** Identifies the software model generating the raw text.

### Derived Data (Synthesized / Reconstructed by EFDI)
- **`full_text`:** When `ENABLE_STRUCTURED_FULL_TEXT = True`, this is **not** raw OCR text. It is a synthesized document containing synthetic markdown headers (`=== HEADER & METADATA ===`, `=== PARTIES ===`, `=== LINE ITEMS ===`), a Markdown table grid, and column labels (`--- SELLER COLUMN ---`).
- **`average_confidence`:** Arithmetic mean of block confidences.
- **`ReconstructedTable` & `line_items`:** Groupings inferred by geometric clustering heuristics.
- **`NormalizedLineItem`:** Cleaned strings, parsed floating-point decimals, ISO dates, and interpreted VAT rates.
- **`DocumentValidationResult` & `OCRQualityBreakdown`:** Mathematical balance flags and overall quality score.

---

## 18. Error Handling

1. **PDF Rendering Failures:**
   - Password-protected PDF -> Caught in `rasterize_pdf()`; raises `FileProcessingException("PDF is password-protected and cannot be processed")`.
   - Corrupted/invalid PDF -> Caught in `rasterize_pdf()`; raises `FileProcessingException("Could not open PDF for OCR: ...")`.
   - Empty PDF (0 pages) -> Raises `FileProcessingException("PDF contains no pages")`.
2. **Missing Files on Disk:**
   - If file does not exist at `uploads/<stored_filename>`, raises `FileProcessingException("Document file not found on disk: ...")`.
3. **Empty Text Detection (Blank Page / Unreadable Image):**
   - If `result_data.full_text.strip()` is empty:
     - Document status is updated to `DocumentStatus.REJECTED`.
     - An audit log is written with `AuditAction.DOCUMENT_REJECTED` and reason `"OCR extracted no text"`.
     - The `OCRResult` is still saved to the database with `full_text = ""`.
     - Does not crash or raise an unhandled exception.
4. **OCR Engine Crashes:**
   - Any exception during OCR extraction is caught in `OCRService.run_ocr()` lines 215–224:
     - Emits `AuditAction.OCR_FAILED` with error message.
     - Logs `logger.exception("OCR failed for document %s", document.id)`.
     - Re-raises the exception to return an HTTP error to the caller.
5. **Table Reconstruction & Normalization Failures:**
   - Wrapped in broad `try...except` blocks in `ExtractionService` (lines 65–90) and `_to_response` (lines 45–70). If geometric clustering or numeric parsing fails on malformed input, it logs a warning and falls back to un-augmented text without crashing the request.

---

## 19. Performance / Observability

### Current Measurements
- **Total Execution Time:** Measured via `time.monotonic()` around the entire rasterization + preprocessing + inference + structuring loop. Saved in `ocr_results.processing_time_ms` and logged to stdout.
- **Audit Trails:** Comprehensive lifecycle auditing via `AuditService`:
  - `AuditAction.OCR_STARTED`
  - `AuditAction.OCR_COMPLETED` (records engine, table items count, quality score, validation status, preprocessing strategy)
  - `AuditAction.OCR_FAILED` (records error string)
  - `AuditAction.DOCUMENT_REJECTED` (if text is blank)

### Missing Measurements
- No isolated sub-millisecond breakdown stored for:
  - PDF rasterization time
  - Adaptive preprocessing time
  - Pure neural network inference time (CRAFT vs CRNN)
  - Table reconstruction time

---

## 20. Testing

### Existing Test Coverage
- **`backend/tests/test_phase4_ocr.py` (352 lines):** Tests end-to-end OCR routes, PDF rasterization DPI scaling, preprocessing deskewing, persistence, RBAC scoping, and status transitions using `StubOCREngine`.
- **`backend/tests/test_structured_full_text.py` (109 lines):** Validates that raw blocks are not mutated, table reconstruction precedes text generation, Markdown tables are formatted properly, and non-table documents degrade gracefully.
- **`backend/tests/test_ocr_table_reconstruction.py`:** Unit-tests 2D geometric column alignment, row clustering, multiline continuation, and European table layouts.
- **`backend/tests/test_ocr_normalization.py`:** Tests US/European numeric parsing, date formats, unit conversions, and VAT rate inference.
- **`backend/tests/test_ocr_adaptive_preprocessing.py`:** Tests skew estimation, Laplacian sharpness, and pass-through on clean digital renders.
- **`backend/tests/test_ocr_validation.py`:** Tests arithmetic validation rules on line items.
- **`backend/tests/test_ocr_quality_scoring.py`:** Tests multi-dimensional quality scoring calculations.

### Test Coverage Gaps
- **Real Model Weights in CI:** Tests run with `StubOCREngine` or pre-captured mock blocks; tests do not exercise live EasyOCR model inference in automated CI due to network and GPU constraints.
- **Multi-page Table Reconstruction:** No automated test asserts table reconstruction across multi-page PDF documents.

---

## 21. Architectural Assessment

### Strengths
1. **Immutable Ground Truth:** `ocr_results.raw_blocks` preserves exact EasyOCR bounding boxes, confidence, and text verbatim. No downstream normalization or structuring ever alters this raw evidence.
2. **Adaptive Preprocessing:** Clean born-digital PDFs bypass heavy image filters, preventing interpolation blur, while noisy scans receive automated skew correction and CLAHE contrast adjustment.
3. **Structured Prompt Synthesis:** Converting raw bounding boxes into Markdown tables and distinct Party columns significantly improves extraction accuracy when fed into Large Language Models.
4. **Defensive Rejection:** Documents with zero readable text are rejected immediately with an explicit audit trail, preventing downstream modules from processing empty records.

### Potential Issues & Bottlenecks
1. **Single-Page Table Reconstruction Flaw:** In `OCRService.run_ocr()` (line 141), `ExtractionService.extract()` (line 67), and `ocr.py:_to_response()` (line 46), table reconstruction explicitly accesses only `raw_blocks[0]`. Line items on page 2 or tables that span multiple pages are **completely omitted from structured table extraction**.
2. **Redundant On-The-Fly Table Reconstruction:** Because `table_data` and `normalized_data` are not persisted in database columns, the computationally expensive geometric clustering algorithm is run repeatedly: once in `run_ocr()`, once in `_to_response()`, and once in `ExtractionService.extract()`.
3. **Synthetic full_text Pollution:** Injecting synthetic markers (`=== HEADER & METADATA ===`, `=== LINE ITEMS ===`, `| Item # | Description |`) into `ocr_results.full_text` risks breaking naive regex extractors that expect standard raw invoice text, while simultaneously being the only text passed to `ClassificationService`.
4. **Hardcoded Engine Exclusion:** PaddleOCR remains in the repository but is hardcoded as unselectable because of native crashes on ARM64/CPU architectures.

---

## 22. Simplified Explanation

Think of the OCR pipeline as an automated document scanner with an intelligent clerk:

1. **Getting the Page:** You give the clerk a PDF or image. If it is a PDF, the system converts every page into a crisp 200 DPI picture.
2. **Cleaning the Picture:** An analyzer checks if the picture is crooked or faded. If it is a clean digital PDF, it leaves it alone. If it is tilted, it straightens it; if it is washed out, it boosts the contrast.
3. **Reading the Words (EasyOCR):** An AI model looks at the picture, draws boxes around every line of text, reads the words, and assigns a confidence score to each box.
4. **Understanding the Page Layout:** The clerk arranges the boxes:
   - Identifies the top header (Invoice Number, Date).
   - Identifies who sold it (left column) and who bought it (right column).
   - Identifies the table grid, lines up the columns (Quantity, Price, Total), and merges descriptions that spill across multiple lines.
5. **Assembling the Output:**
   - Keeps the 100% original, untouched boxes and coordinates in a filing cabinet (`raw_blocks` in PostgreSQL).
   - Writes a clean, structured summary with a Markdown table (`full_text`).
   - Checks if the arithmetic adds up ($Qty \times Price = Total$) to calculate a quality score.
6. **Passing It Forward:**
   - Passes the text to the Classifier to figure out what type of document it is.
   - Passes the text, the boxes, and the table to the Extraction engine to pull out specific business fields.

---

## 23. Key Findings

1. **On-Demand Execution:** Uploading a document only stores the raw file and creates a DB row; OCR must be explicitly started via `POST /ocr/documents/{id}/run`.
2. **EasyOCR is the Only Active Production Engine:** Configured in `app/ocr/easyocr_engine.py` with `detail=1` and `add_margin=0.10`. PaddleOCR is disabled due to native crashes.
3. **Raw Evidence is 100% Preserved:** In `ocr_results.raw_blocks`, all OCR detections, bounding boxes, and confidence scores are saved as an immutable JSONB array.
4. **`full_text` is Structurally Re-Engineered:** When `ENABLE_STRUCTURED_FULL_TEXT` is enabled, `full_text` contains synthetic section tags (`=== PARTIES ===`, `=== LINE ITEMS ===`) and Markdown tables, rather than a raw dump of text.
5. **Derived Structures are NOT Persisted:** `table_data`, `normalized_data`, `validation_results`, and `quality_score` are not stored in PostgreSQL columns; they are computed on-the-fly and discarded after each request.
6. **Severe Multi-Page Table Blindspot:** Downstream extraction and API serialization only run table reconstruction on `raw_blocks[0]`. Line items on subsequent pages are ignored.
7. **Classification is 1D String Only:** `ClassificationService` receives only `ocr_result.full_text` and has zero awareness of bounding boxes, tables, or confidence scores.
8. **Extraction Uses Enriched Context:** `ExtractionService` re-extracts tables and party columns from `raw_blocks[0]` to build `ExtractionContext` for Rule, LLM, and Hybrid engines.
9. **Zero-Text Rejection Safeguard:** If OCR extracts no text, the document is automatically set to `status="REJECTED"` with an audit log reason, preventing wasted downstream processing.
10. **Append-Only History:** Running OCR multiple times on the same document creates new rows in `ocr_results`, maintaining a complete audit trail without overwriting previous runs.

---

### Verification of Read-Only Constraint
- **No existing source code files were modified.**
- **No test files were modified.**
- **No configuration files were modified.**
- **No database schemas, migrations, or data were modified.**
- **No packages were installed.**
- **The only file created is `OCR_pipeline.md`.**
