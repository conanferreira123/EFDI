# OCR → Classification → Extraction Architecture

## Overview

This document describes the **read‑only** data flow for the OCR → Classification → Extraction pipeline in the **EFDI** application.  It focuses on:
- How OCR results are persisted.
- What fields downstream services consume.
- Where the structured `raw_blocks` JSONB column is (or isn’t) used.
- The relationship between the three services and the audit subsystem.

All information is derived from the current source code (no runtime modifications or migrations were performed).

---

## 1. OCR Service (`app/services/ocr_service.py`)

| Component | Description |
|---|---|
| **Class** | `OCRService` |
| **Key Method** | `run_ocr(document: Document, engine_name: str | None = None) -> OCRResult` |
| **Inputs** | `Document` (contains `id`, `stored_filename`, `mime_type`). |
| **Processing Steps** |
| 1. Load file bytes from disk (`get_file_path`). |
| 2. Rasterize PDF or decode image. |
| 3. Adaptive preprocessing per page. |
| 4. For each page, call the selected OCR engine (`engine.extract_text_blocks`). |
| 5. **Persist raw block detections** in a list of dictionaries (`raw_blocks`). |
| 6. Assemble ordered blocks into `result_data.full_text` (spatial reading order). |
| 7. Run table reconstruction, normalization, validation, and quality scoring (uses `result_data.full_text`). |
| 8. Create an `OCRResult` row via `OCRResultRepository.create`. |
| 9. Update `Document.status` to `OCR_COMPLETED` (or `REJECTED` if no text). |
| 10. Log audit events (`OCR_STARTED`, `OCR_COMPLETED`, `OCR_FAILED`). |
| **Persisted Model** | `OCRResult` (`app/models/ocr_result.py`) |
| **Columns persisted** | - `document_id` (FK)  
- `engine_name`  
- `page_count`  
- `full_text` (**Text**)  
- `average_confidence`  
- `raw_blocks` (**JSONB**) – list of per‑page block dictionaries with text, confidence, bounding box.  
- `processing_time_ms` |
| **Primary consumer** | Classification and Extraction services (via `full_text`). |

**Key Point:** The OCR service **stores both** `full_text` **and** `raw_blocks`.  `raw_blocks` is intended for audit/debugging and is **not used** by the downstream classification or extraction logic in the current code.

---

## 2. Classification Service (`app/services/classification_service.py`)

| Component | Description |
|---|---|
| **Class** | `ClassificationService` |
| **Key Method** | `classify(document: Document, engine_name: str | None = None)` |
| **Workflow** |
| 1. Retrieve the **latest** OCR result for the document: `self.ocr_repo.get_latest_for_document(document.id)`.
| 2. **Validate** that an OCR result exists; otherwise raise `ValidationFailedException`.
| 3. Resolve the classification engine (`get_classification_engine`).
| 4. **Pass only** `ocr_result.full_text` to the engine: `engine.classify(ocr_result.full_text)`.
| 5. Persist a `ClassificationResult` row via `ClassificationResultRepository.create` (stores predicted type, confidence, engine name, signals, scores).
| 6. Update `Document.document_type` to the predicted type and commit.
| 7. Log an informational message.
| **Persisted Model** | `ClassificationResult` (`app/models/classification_result.py`). |
| **Columns persisted** | `document_id`, `predicted_type`, `confidence`, `engine_name`, `signals` (JSON), `scores_by_type` (JSON). |
| **Raw OCR data usage** | **None** – the service consumes only the `full_text` string.

---

## 3. Extraction Service (`app/services/extraction_service.py`)

| Component | Description |
|---|---|
| **Class** | `ExtractionService` |
| **Key Method** | `extract(document: Document, engine_name: str | None = None)` |
| **Workflow** |
| 1. Retrieve the **latest** OCR result (`self.ocr_repo.get_latest_for_document`).
| 2. Retrieve the **latest** Classification result (`self.classification_repo.get_latest_for_document`).
| 3. Validate both exist; raise `ValidationFailedException` if missing.
| 4. Determine `document_type` from the classification result.
| 5. Resolve the extraction engine (`get_extraction_engine`).
| 6. **Pass only** `ocr_result.full_text` and `document_type` to the engine: `engine.extract(ocr_result.full_text, document_type)`.
| 7. (Optional) Run RAG diagnostic for LLM‑based engines – still uses the **full text** payload.
| 8. Build `fields_payload` (value, confidence, matched_text, is_found) from the engine’s `result_data`.
| 9. Persist an `ExtractionResult` via `ExtractionResultRepository.create` (stores document_id, document_type, engine_name, fields JSONB, confidence metrics).
| 10. Update `Document.status` to `EXTRACTED`.
| 11. Log extraction completion.
| **Persisted Model** | `ExtractionResult` (`app/models/extraction_result.py`). |
| **Columns persisted** | `document_id`, `document_type`, `engine_name`, `fields` (JSONB), `overall_confidence`, `fields_found_count`, `fields_total_count`. |
| **Raw OCR data usage** | **None** – the service only consumes `full_text`.

---

## 4. Summary of Data Flow

```mermaid
flowchart TD
    Document -->|run_ocr| OCRService --> OCRResult[OCRResult (full_text, raw_blocks)]
    OCRResult -->|latest| ClassificationService --> ClassificationResult
    OCRResult -->|latest| ExtractionService --> ExtractionResult
    ClassificationResult -->|latest| ExtractionService
    OCRResult -->|audit only| raw_blocks[raw_blocks (JSONB)]
    classDef audit fill:#f9f,stroke:#333,stroke-width:2px;
    raw_blocks:::audit;
```

- **OCRResult** is the sole source of OCR data for downstream services.
- **`full_text`** is the only field accessed by **Classification** and **Extraction**.
- **`raw_blocks`** is stored for **audit / debugging** purposes but is **not consumed** by the current classification or extraction engines.
- The pipeline is strictly linear: OCR → Classification → Extraction, each step persisting its own result and advancing the `Document` status.

---

## 5. Implications & Recommendations

1. **Current Limitation:** Extraction engines that operate on `full_text` must parse the entire document string to locate individual fields.  This can be slower and less robust than using pre‑segmented block data.
2. **Potential Enhancement:** Future classification or extraction engines could be refactored to accept the structured `raw_blocks` JSONB payload, enabling:
   - Faster block‑level searching.
   - Direct access to bounding‑box coordinates for layout‑aware extraction.
   - Reduced reliance on text‑only heuristics.
3. **Audit Value:** The preservation of `raw_blocks` already provides a rich audit trail.  Developers can query this column for forensic analysis without impacting the existing workflow.

---

## 6. References
- `app/services/ocr_service.py` – lines 52‑155 (OCR execution and persistence).
- `app/services/classification_service.py` – lines 27‑55 (classification flow).
- `app/services/extraction_service.py` – lines 35‑55 (extraction flow).
- `app/models/ocr_result.py` – definition of `full_text` and `raw_blocks` columns.

---

*This report is generated automatically based on a read‑only inspection of the source code. No code or database changes were performed.*
