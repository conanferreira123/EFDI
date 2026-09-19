# Architectural Discovery & Design Plan: Conversational RAG Subsystem for EFDI

**Document:** RAG Plan  
**Role:** Principal Enterprise Architect, Backend Architect & AI Integration Strategist  
**Target System:** Enterprise Financial Document Intelligence (EFDI) Backend (`backend/app/`)  
**Status:** ARCHITECTURAL DESIGN & INTEGRATION PLAN — ANALYSIS ONLY (ZERO CODE MUTATIONS)

---

## 1. Executive Summary & Strategic Vision

The Enterprise Financial Document Intelligence (EFDI) platform automates accounts payable (AP) and record-to-report (R2R) workflows through a deterministic pipeline: document upload, OCR layout reconstruction, document classification, field extraction (heuristic and LLM-assisted), validation rule enforcement, and an audit-trailed approval state machine.

This document defines the architectural design and integration plan for introducing a **dual-tiered Conversational AI capability** into EFDI:

1. **Level 1 — Document-Level Conversational Assistant:** An interactive copilot bound to a single document (`document_id = X`). It answers questions regarding payment terms, early payment discounts, delivery contingencies, freight clauses, dispute conditions, and un-modeled contractual annotations.
2. **Level 2 — Global / Cross-Document Intelligence Assistant:** A portfolio-wide conversational analyst operating across the authorized document corpus. It dynamically chooses between relational database querying (SQL) for deterministic aggregates and hybrid vector/keyword retrieval (RAG) for unstructured inquiries, coordinating both for compound questions (e.g., *"How much did we spend with ACME Supplies, and what early settlement discount terms appear in their invoices?"*).

### Core Architectural Principles
* **Separation of Search Paradigms:** Relational queries (counts, sums, status filters, date bounds) must execute via deterministic SQL. Unstructured queries (penalties, terms, delivery clauses) execute via Hybrid RAG.
* **Canonical OCR as the Single Source of Truth:** RAG ingestion attaches to the canonical, layout-structured text (`OCRResult.full_text`) produced after OCR table and layout reconstruction, **not** to the extracted key-value schema (`ExtractionResult`). This guarantees access to 100% of the unstructured textual surface.
* **Zero Disruption to Core Pipeline:** Ingestion into the vector store occurs asynchronously via decoupled background tasks; failure or latency in vector indexing never blocks the core document workflow (`UPLOADED → OCR_COMPLETED → EXTRACTED → VALIDATED`).

---

## 2. Discovery of the Current EFDI Architecture

Every integration point must fit the real codebase. Below is the ground-truth technical audit of the document lifecycle in `backend/app/`.

```text
[Frontend / Client]
       │
       ▼ HTTP Multipart
[routers/documents.py]
       │
       ▼ (Passes raw bytes, filename, mime_type)
[services/document_service.py] ──► [utils/file_storage.py] (Saves to uploads/, SHA-256)
       │
       ▼ (Creates Document entity)
[repositories/document_repository.py] ──► [PostgreSQL: documents] (Status: UPLOADED)
       │
       ▼ HTTP POST /ocr/documents/{id}/run
[routers/ocr.py] ──► [services/ocr_service.py]
       │
       ├──► [ocr/preprocessing.py] (PyMuPDF fitz rasterization to BGR arrays)
       ├──► [ocr/adaptive_preprocessing.py] (CLAHE contrast, Hough deskew)
       ├──► [ocr/easyocr_engine.py] (Bounding boxes, confidence, text blocks)
       ├──► [ocr/table_reconstruction.py] (Row/column grid clustering)
       └──► [ocr/layout.py] (Spatial reading order, section banding, Markdown tables)
       │
       ▼ (Persists full_text, raw_blocks)
[repositories/ocr_result_repository.py] ──► [PostgreSQL: ocr_results]
[repositories/document_repository.py]   ──► [PostgreSQL: documents] (Status: OCR_COMPLETED)
       │
       ▼ HTTP POST /classification/documents/{id}/classify
[routers/classification.py] ──► [services/classification_service.py]
       │
       ├──► [classification/rule_based.py] (Regex/keyword scoring & PO/NPO disambiguation)
       └──► [repositories/classification_result_repository.py] ──► [PostgreSQL: classification_results]
       └──► Direct Session Mutation: document.document_type = 'POI' (Status remains OCR_COMPLETED)
       │
       ▼ HTTP POST /extraction/documents/{id}/extract
[routers/extraction.py] ──► [services/extraction_service.py]
       │
       ├──► [extraction/parallel_orchestrator.py] (ThreadPoolExecutor: RuleBased + LLMBased)
       ├──► [extraction/reconciliation.py] (ReconciliationEngine confidence matrix)
       └──► [repositories/extraction_result_repository.py] ──► [PostgreSQL: extraction_results]
       └──► [repositories/document_repository.py] ──► [PostgreSQL: documents] (Status: EXTRACTED)
       │
       ▼ HTTP POST /validation/documents/{id}/validate
[routers/validation.py] ──► [services/validation_service.py]
       │
       ├──► [validation/engine.py :: run_validation()]
       │       ├── [field_validators.py] (ISO dates, numeric formats, VAT IDs)
       │       ├── [business_rules.py] (Net + Tax == Gross, Debits == Credits)
       │       └── [duplicate_detection.py] (File hash + raw cross-document SQL)
       │
       ▼ (Persists validation report)
[repositories/validation_result_repository.py] ──► [PostgreSQL: validation_results]
       │
       ▼ Conditional Status Update:
       ├── If error_count == 0 ──► status = VALIDATED (Eligible for approval workflow)
       └── If error_count > 0  ──► status remains EXTRACTED (Requires human correction)
```

### Component-by-Component Lifecycle Audit

| Stage | Exact Code Location | Injected Dependencies | Key Inputs | Outputs / Persistence |
| :--- | :--- | :--- | :--- | :--- |
| **1. Upload** | `routers/documents.py:L48`<br>`services/document_service.py:L35`<br>`repositories/document_repository.py:L48` | `db: Session = Depends(get_db)`<br>`current_user: User = Depends(get_current_user)` | `file: UploadFile`<br>HTTP multipart stream | `uploads/<uuid>.pdf` on disk<br>`Document` row in `documents`<br>`status = 'UPLOADED'`, `document_type = 'UNKNOWN'` |
| **2. OCR** | `routers/ocr.py:L87`<br>`services/ocr_service.py:L52`<br>`ocr/layout.py:L306`<br>`repositories/ocr_result_repository.py:L17` | `db: Session = Depends(get_db)`<br>`current_user: User = Depends(get_current_user)` | `document_id: int`<br>`payload: OCRRunRequest`<br>`(engine="easyocr")` | `OCRResult` row in `ocr_results`<br>`full_text` (Markdown/sections)<br>`raw_blocks` (JSONB bounding boxes)<br>`documents.status = 'OCR_COMPLETED'` |
| **3. Classification** | `routers/classification.py:L33`<br>`services/classification_service.py:L26`<br>`classification/rule_based.py:L58` | `db: Session = Depends(get_db)`<br>`current_user: User = Depends(get_current_user)` | `document_id: int`<br>`payload: ClassifyRequest` | `ClassificationResult` in DB<br>`documents.document_type = 'POI'`<br>*(Note: `status` remains `OCR_COMPLETED`)* |
| **4. Extraction** | `routers/extraction.py:L34`<br>`services/extraction_service.py:L40`<br>`extraction/parallel_orchestrator.py:L60` | `db: Session = Depends(get_db)`<br>`current_user: User = Depends(get_current_user)` | `document_id: int`<br>`payload: ExtractRequest`<br>`(engine="hybrid")` | `ExtractionResult` in DB (`fields` JSONB)<br>`documents.status = 'EXTRACTED'` |
| **5. Validation** | `routers/validation.py:L27`<br>`services/validation_service.py:L35`<br>`validation/engine.py:L39` | `db: Session = Depends(get_db)`<br>`current_user: User = Depends(get_current_user)` | `document_id: int`<br>`payload: ValidateRequest` | `ValidationResult` in DB (`issues` JSONB)<br>If `error_count == 0`: `status = 'VALIDATED'`<br>If `error_count > 0`: `status = 'EXTRACTED'` |

---

## 3. Critical RAG Integration Point: The Document Representation

### Why `OCRResult.full_text` Must Be the Primary Source
The deterministic extraction schema (`app/extraction/field_schemas.py`) captures only predefined accounting fields: `invoice_number`, `invoice_date`, `due_date`, `net_amount`, `tax_amount`, `grand_total_amount`, and `vendor_name`.

However, the questions targeted by the Conversational Assistant depend on **unstructured textual clauses** that are intentionally excluded from the extraction schema:
* *"Does this invoice mention an early payment discount (e.g., 2% 10 Net 30)?"*
* *"What delivery incoterms (FOB, CIF, DDP) are specified?"*
* *"Are there late payment penalty interest rates defined in the footer?"*
* *"What dispute resolution or freight liability terms are cited?"*

If RAG indexed `ExtractionResult.fields`, none of these clauses would exist in the embedding space. **`OCRResult.full_text` is the sole canonical representation that contains 100% of the document's textual surface.**

### Code Verification of Canonical `full_text`
In `app/ocr/layout.py:L306-L377`, function `generate_structured_full_text(pages)` constructs a clean, layout-aware string representation. It handles spatial reading orders, separates multi-column party information, formats tabular data as GitHub Flavored Markdown, and marks page boundaries:

```text
=== PAGE 1 ===
=== HEADER & METADATA ===
TAX INVOICE
Invoice No: INV-9021
Date: 2024-03-15

=== PARTIES ===
--- SELLER COLUMN ---
ACME Industrial Supplies Ltd.
VAT ID: GB123456789
12 Oxford Street, London

--- BUYER COLUMN ---
Global Manufacturing Corp
Client ID: GMC-880
45 Factory Lane, Manchester

=== LINE ITEMS ===
| Item | Description | Qty | Unit Price | Total |
| --- | --- | --- | --- | --- |
| 1 | Hydraulic Pump Valve A1 | 10 | 100.00 | 1000.00 |
| 2 | High Pressure Seal Kit | 2 | 50.00 | 100.00 |

=== TOTALS & SUMMARY ===
Net Worth: 1100.00
VAT (20%): 220.00
Gross Total: 1320.00

Payment Terms: 2% discount if paid within 10 days; Net 30 days.
Late payments subject to 1.5% monthly interest penalty.
Goods delivered under Incoterms 2020: DAP Manchester.
```

`OCRResult.full_text` preserves the exact layout needed for semantic search, while `OCRResult.raw_blocks` retains bounding box coordinates needed for spatial citation overlays.

---

## 4. Lifecycle Integration & Ingestion Orchestration

### When Ingestion Triggers
Ingestion attaches **immediately upon completion of OCR**, when `Document.status` transitions to `OCR_COMPLETED` inside `app/services/ocr_service.py:L177`.

```text
[OCR Execution Finished]
          │
          ├──► Persistence: ocr_results table
          ├──► Status Update: documents.status = 'OCR_COMPLETED'
          │
          ├─────────────────────────────────────────┐
          │ (Main Processing Thread)                │ (Decoupled Background Execution)
          ▼                                         ▼
[Classification & Extraction Pipelines]     [RAG Ingestion Subsystem]
  - ClassificationService                     - Structure-Aware Chunking
  - ExtractionService                         - Embedding Generation (384-dim)
  - ValidationService                         - TSVector Keyword Generation
                                              - Transactional DB Write:
                                                document_chunks table
```

### Architectural Decision: Asynchronous Background Ingestion
RAG chunking and vector embedding generation (running 5 to 15 text chunks through a transformer model) takes between 200ms and 1500ms depending on CPU/GPU availability.

**RAG ingestion MUST NOT execute synchronously in the OCR request thread.**
* **Mechanism:** In FastAPI, utilize `BackgroundTasks` passed from the router (`app/routers/ocr.py`) or an event hook in `OCRService`.
* **Failure Isolation:** If embedding generation encounters a transient failure (e.g., PyTorch out-of-memory or model timeout), the document **must still successfully reach `OCR_COMPLETED`**. Vector indexing is an auxiliary capability; it must never abort core financial document intake.
* **Metadata Synchronization:** If RAG ingestion runs at `OCR_COMPLETED`, the document's `document_type`, `vendor_code`, and `validation_status` may still be `UNKNOWN` or `None`. A lightweight metadata synchronization step updates chunk metadata once extraction and validation complete.

---

## 5. RAG Document Source Analysis

Inspection of `app/ocr/layout.py` and `app/models/ocr_result.py` confirms the structural characteristics of `OCRResult.full_text`:

1. **Page Boundaries:** Explicitly delineated by `=== PAGE {page_number} ===` strings for multi-page documents (`is_multi_page = len(pages) > 1`).
2. **Section Headings:** Pre-delimited with markdown/text headers:
   * `=== HEADER & METADATA ===`
   * `=== PARTIES ===` (with sub-tags `--- SELLER COLUMN ---` and `--- BUYER COLUMN ---`)
   * `=== LINE ITEMS ===` (formatted as standard markdown tables)
   * `=== TOTALS & SUMMARY ===`
   * Trailing text blocks capture footer notes, payment conditions, bank account details, and legal disclaimers.
3. **Table Structure:** Tabular records are structured via `format_reconstructed_table_markdown(table)`, resolving cell boundaries, headers, descriptions, quantities, and line totals into markdown rows.
4. **Source Coordinate Provenance:** While `full_text` holds the reading text, the database model `OCRResult` concurrently preserves `raw_blocks: Mapped[dict] = mapped_column(JSONB)`. Each block contains:
   ```json
   {
     "text": "Payment Terms: 2% discount if paid within 10 days",
     "confidence": 0.96,
     "bounding_box": [[120.0, 850.0], [450.0, 850.0], [450.0, 875.0], [120.0, 875.0]]
   }
   ```
   **Architectural Conclusion:** There is zero need to re-rasterize or reprocess the PDF with PyMuPDF for RAG. The canonical text in `OCRResult.full_text` provides semantic boundaries for chunking, and `raw_blocks` allows chunk text to be mapped back to 2D bounding boxes for UI citation highlighting.

---

## 6. Hybrid Retrieval Architecture (Vector + BM25 + RRF + Reranker)

To eliminate hallucinations and retrieve both semantic concepts (*"early settlement incentives"*) and exact alphanumeric tokens (*"INV-9021"*, *"GB123456789"*), EFDI implements a hybrid retrieval pipeline.

```text
                                User Query
                                    │
                                    ▼
                      ┌───────────────────────────┐
                      │  Query Analysis & Normal. │
                      └─────────────┬─────────────┘
                                    │
             ┌──────────────────────┴──────────────────────┐
             │                                             │
             ▼                                             ▼
   ┌────────────────────┐                        ┌────────────────────┐
   │ Vector Retrieval   │                        │ Sparse BM25 / FTS  │
   │ pgvector (<=>)     │                        │ PostgreSQL tsvector│
   │ Top-30 Candidates  │                        │ Top-30 Candidates  │
   └─────────┬──────────┘                        └─────────┬──────────┘
             │                                             │
             └──────────────────────┬──────────────────────┘
                                    │
                                    ▼
                      ┌───────────────────────────┐
                      │  Reciprocal Rank Fusion   │
                      │  (RRF Merge: k=60)        │
                      └─────────────┬─────────────┘
                                    │ Top-25 Merged Chunks
                                    ▼
                      ┌───────────────────────────┐
                      │  Cross-Encoder Reranker   │
                      │  (ms-marco-MiniLM-L-6-v2) │
                      └─────────────┬─────────────┘
                                    │ Top-5 High-Relevance Chunks
                                    ▼
                      ┌───────────────────────────┐
                      │  Context Construction     │
                      │  + Strict Grounding Prompt│
                      └─────────────┬─────────────┘
                                    │
                                    ▼
                      ┌───────────────────────────┐
                      │  LLM Synthesis (Mistral)  │
                      └─────────────┬─────────────┘
                                    │
                                    ▼
                         Grounded Answer + Citations
```

### A. Vector Retrieval Subsystem
* **Storage Foundation:** PostgreSQL with `pgvector`. Alembic migration `018069fabf68` has already enabled `CREATE EXTENSION IF NOT EXISTS vector;` and defined the `document_chunks` table.
* **Vector Dimension:** Fixed at **384 dimensions** in the existing schema: `embedding: Mapped[list[float]] = mapped_column(Vector(384))`.
* **Target Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` or `BAAI/bge-small-en-v1.5`. Both produce dense 384-dimensional embeddings, run efficiently on CPU, and match the column specification.
* **Distance Metric:** Cosine Distance (`<=>` operator in pgvector).
* **Indexing Recommendation:** For production scale (>10,000 chunks), add an **HNSW (Hierarchical Navigable Small World)** index:
  ```sql
  CREATE INDEX ix_document_chunks_embedding_hnsw 
  ON document_chunks USING hnsw (embedding vector_cosine_ops) 
  WITH (m = 16, ef_construction = 64);
  ```

### B. Sparse Keyword Retrieval Subsystem
* **PostgreSQL-Native Full-Text Search:** Rather than deploying an external search engine (Elasticsearch/Typesense) which introduces distributed operational overhead, EFDI leverages PostgreSQL's native `tsvector` and `tsquery` engine.
* **Implementation Pattern:** Add a generated or indexed column `tsv_content` to `document_chunks`:
  ```sql
  ALTER TABLE document_chunks ADD COLUMN tsv_content tsvector 
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
  CREATE INDEX ix_document_chunks_tsv ON document_chunks USING gin(tsv_content);
  ```
* **Ranking Algorithm:** Use `ts_rank_cd(tsv_content, websearch_to_tsquery('english', query))` (cover density ranking, which closely approximates BM25 term proximity and frequency).

### C. Reciprocal Rank Fusion (RRF)
RRF combines ranked lists from disparate retrieval systems without requiring score normalization across different scales:
$$\text{RRF\_Score}(d \in D) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
Where $k = 60$ (standard smoothing constant), $M = \{\text{Vector}, \text{BM25}\}$, and $r_m(d)$ is the 1-based rank of chunk $d$ in system $m$.
* **Execution Boundary:** Pure Python logic inside the retrieval service layer (`app/services/rag_service.py`), receiving Top-30 vector results and Top-30 BM25 results, outputting the Top-25 unified candidates.

### D. Cross-Encoder Reranker
* **Model Selection:** `cross-encoder/ms-marco-MiniLM-L-6-v2` or `BAAI/bge-reranker-base`.
* **Execution Boundary:** Service-level inference module (`app/rag/reranker.py`).
* **Input:** Top-25 candidate chunk contents paired with the raw user query: `[(query, chunk_1), (query, chunk_2), ...]`.
* **Output:** Top-5 reranked chunks with calibrated logit relevance scores. Chunks with scores below a noise threshold (e.g. logit < -2.5) are discarded to prevent hallucination.

### E. LLM Synthesis & Strict Grounding
* **Provider:** Leverages EFDI's existing Mistral infrastructure (`app/core/config.py:L70`, `settings.MISTRAL_API_KEY`).
* **Prompt Isolation:** Strict financial grounding prompt:
  > *"You are the EFDI Financial Document Assistant. Answer the user query using ONLY the provided document context chunks. If the context does not explicitly mention the requested information, state clearly that the document does not specify it. Do not infer terms not stated. Every factual statement must cite its source chunk ID."*

---

## 7. Structure-Aware Chunking Architecture

Arbitrary character/token chunking (e.g. 500 characters with 50 character overlap) damages financial documents by splitting tables mid-row or separating payment penalty clauses from their parent terms. EFDI uses **structure-aware semantic chunking**.

```text
Canonical OCR Full Text
           │
           ├── Split on "=== PAGE {n} ===" ──► Page Awareness
           │
           ├── Split on Section Headers:
           │     ├── "=== HEADER & METADATA ===" ──► Chunk 1: Header Metadata (Type: HEADER)
           │     ├── "=== PARTIES ==="           ──► Chunk 2: Seller/Buyer Profile (Type: PARTIES)
           │     ├── "=== LINE ITEMS ==="        ──► Chunk 3..N: Table Chunks (Type: LINE_ITEMS)
           │     │     └── If rows <= 15: Single Chunk
           │     │     └── If rows > 15: Sliding Table Window with Header Row preserved
           │     ├── "=== TOTALS & SUMMARY ==="  ──► Chunk K: Financial Summary (Type: SUMMARY)
           │     └── Footer / Unstructured Text  ──► Chunk K+1: Terms & Notes (Type: TERMS)
           │
           └── Emit to document_chunks Table:
                 (document_id, page_number, chunk_type, content, embedding, metadata_json)
```

### Chunk Sizing and Structure Specifications

| Chunk Type | Source Boundary in `full_text` | Target Token Budget | Context Preservation Strategy |
| :--- | :--- | :--- | :--- |
| `HEADER` | `=== HEADER & METADATA ===` | 100 – 250 tokens | Retains document title, invoice number, issue date, tax reference. |
| `PARTIES` | `=== PARTIES ===` | 150 – 300 tokens | Combines Seller Column and Buyer Column to answer queries regarding counterparty identity, addresses, and tax identifiers. |
| `LINE_ITEMS` | `=== LINE ITEMS ===` (Markdown Table) | 250 – 600 tokens | If table contains $\le 15$ rows, keep intact. If $> 15$ rows, chunk by 10-row slices, prepending the markdown table header row to every slice. |
| `SUMMARY` | `=== TOTALS & SUMMARY ===` | 150 – 300 tokens | Captures Net, VAT/Tax, Gross Totals, Currency, Discount rates, Remittance instructions. |
| `TERMS` | Trailing text / Footer | 100 – 350 tokens | Captures Incoterms, early payment discount schedules, late payment interest, return policies, freight notes. |

---

## 8. Metadata Architecture: Document-Level vs. Global RAG

Metadata enables strict database-level filtering before embeddings or keyword indices are traversed.

```text
                        ┌──────────────────────────────────────────────┐
                        │              METADATA STORAGE                │
                        └──────────────────────┬───────────────────────┘
                                               │
               ┌───────────────────────────────┴───────────────────────────────┐
               ▼                                                               ▼
┌───────────────────────────────┐                             ┌────────────────────────────────┐
│   Relational Columns          │                             │   Chunk JSONB Metadata         │
│   (PostgreSQL Core Tables)    │                             │   (document_chunks.metadata)   │
├───────────────────────────────┤                             ├────────────────────────────────┤
│ documents.id                  │                             │ chunk_index: int               │
│ documents.uploaded_by         │◄── Joined During ───────────┤ section: str                   │
│ documents.document_type       │    Pre-Retrieval            │ page_number: int               │
│ documents.status              │    Filtering                │ has_table: bool                │
│ documents.company_code        │                             │ bounding_box_refs: list        │
│ documents.vendor_code         │                             │ line_range: [int, int]         │
└───────────────────────────────┘                             └────────────────────────────────┘
```

### Comprehensive Metadata Classification Matrix

| Metadata Field | Availability in Code | Classification | Storage Location | Document RAG Role | Global RAG Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `document_id` | `Document.id` | **REQUIRED NOW** | `document_chunks.document_id` (FK) | Primary filter (`= X`) | Relational join filter |
| `page_number` | Detected in `layout.py` | **REQUIRED NOW** | `document_chunks.page_number` | Citation provenance | Citation provenance |
| `chunk_type` | In `DocumentChunk` model | **REQUIRED NOW** | `document_chunks.chunk_type` | Filter by section | Filter by section |
| `chunk_index` | Generated during chunking | **REQUIRED NOW** | `metadata_json['chunk_index']` | Context ordering | Context ordering |
| `uploaded_by` | `Document.uploaded_by` | **REQUIRED NOW** | Relational `documents` table | N/A (Checked via session) | **Critical Authorization Filter** |
| `document_type`| `Document.document_type` | **REQUIRED NOW** | Relational `documents` table | Context enrichment | Pre-retrieval scope filter |
| `status` | `Document.status` | **REQUIRED NOW** | Relational `documents` table | Informational | Status filtering (e.g. `VALIDATED`) |
| `company_code` | `Document.company_code` | **REQUIRED NOW** | Relational `documents` table | Filter/Citation | Tenant/Company scope filter |
| `vendor_code` | `Document.vendor_code` | **REQUIRED NOW** | Relational `documents` table | Context enrichment | Multi-vendor spending filter |
| `vendor_name` | `ExtractionResult.fields` | **USEFUL LATER** | `metadata_json['vendor_name']` | Citation label | Natural language search filter |
| `invoice_date` | `ExtractionResult.fields` | **REMAIN IN RELATIONAL** | Relational extraction tables | N/A (Relational check) | Date-range arithmetic |
| `due_date` | `ExtractionResult.fields` | **REMAIN IN RELATIONAL** | Relational extraction tables | N/A (Relational check) | Near-due SQL query filter |
| `grand_total` | `ExtractionResult.fields` | **REMAIN IN RELATIONAL** | Relational extraction tables | N/A (Relational check) | Aggregation/Sum SQL tool |
| `file_hash` | `Document.file_hash` | **NOT NECESSARY** | Relational `documents` table | Not relevant to RAG | Duplicate checking only |

### Extensibility Analysis: Safely Adding Metadata Later
* **Zero Disruption via JSONB:** The `document_chunks.metadata_json` column is already defined as `JSONB` in the database. New attributes (e.g., `tax_rate`, `payment_method`, `detected_language`) can be appended to the JSONB payload without modifying database schemas or running Alembic DDL migrations.
* **Embedding Invariance:** Metadata is stored alongside chunks, not baked into the embedding vector string. Adding metadata never forces re-embedding of historical document chunks.

---

## 9. Scoping Mechanics: Document-Level RAG vs. Global RAG

The system handles two fundamentally distinct query scopes:

```text
A. DOCUMENT SCOPE QUERY
   User on /documents/42 asks: "What are the payment terms?"
   │
   ▼ Hard Relational Enforcement
   SELECT * FROM document_chunks 
   WHERE document_id = 42 
   ORDER BY embedding <=> query_vector LIMIT 5;
   (Zero possibility of data leakage outside Document 42)

B. GLOBAL SCOPE QUERY
   User on /chat asks: "Which invoices mention late delivery penalties?"
   │
   ▼ User Role Check: current_user.role == 'FINANCE_ANALYST' (id = 3)
   │
   ▼ In-Retrieval Authorization Enforcement (Pre-Filter via JOIN)
   SELECT dc.* FROM document_chunks dc
   JOIN documents d ON dc.document_id = d.id
   WHERE d.is_deleted = false
     AND d.uploaded_by = 3  <--- IN-RETRIEVAL CONFINEMENT
   ORDER BY dc.embedding <=> query_vector LIMIT 20;
```

### The In-Retrieval Confinement Rule
**Post-retrieval filtering in application code is strictly prohibited.**
If a global vector search performs `SELECT * FROM document_chunks ORDER BY embedding <=> query_vector LIMIT 20` across the entire database, and the application code subsequently strips out chunks belonging to other users, two severe failures occur:
1. **Security Vulnerability:** Embeddings and content from unauthorized documents are loaded into application process memory and execution logs.
2. **Recall Starvation:** If the Top-20 retrieved chunks all belong to unauthorized documents, the analyst receives zero results even though relevant authorized documents exist lower in the rank list.

**Architectural Law:** In global retrieval, authorization filters (`d.uploaded_by = current_user.id`, `d.company_code IN (...)`) must be pushed down into the PostgreSQL `JOIN` clause before distance ordering.

---

## 10. Authorization & Security Analysis

A rigorous inspection of EFDI's access control implementation in `app/core/dependencies.py` and `app/services/document_service.py` establishes the real permission matrix:

```python
# Code Evidence from app/services/document_service.py:L169-L174
if current_user.role == UserRole.FINANCE_ANALYST.value and document.uploaded_by != current_user.id:
    raise AuthorizationException("You may only access documents you uploaded")
```

| Role | Single Document Access | Document Search Scope | Workflow Approval | System Audit Access |
| :--- | :--- | :--- | :--- | :--- |
| `FINANCE_ANALYST` | **Restricted:** Only uploads where `uploaded_by == user.id` | **Strictly Scoped:** `uploaded_by` forced to `user.id` | Can request approval; cannot approve/reject | Denied |
| `FINANCE_MANAGER` | **Global:** Can view any document | **Global:** Searches all documents across all uploaders | Can approve & reject documents | Denied |
| `AUDITOR` | **Global:** Can view any document | **Global:** Searches all documents across all uploaders | Can approve & reject documents | **Allowed:** Can view full audit logs |
| `ADMIN` | **Global:** Full platform access | **Global:** Searches all documents across all uploaders | Can approve & reject documents | **Allowed:** Full platform access |

### Security Evaluation for Conversational AI

#### Level 1: Document-Level Chatbot Access
* **Architecture Policy:** Inherits exact document-level visibility via `DocumentService.get_for_user(document_id, current_user)`.
* **Resolution:** If a user can view the document in the UI, they can converse with that document's Level 1 chatbot. An analyst querying a document they uploaded will succeed; querying another analyst's document will return an immediate `403 Forbidden`.

#### Level 2: Global Cross-Document Chatbot Access (Open Decision Analysis)
There are two viable architectural policies for the Global Chatbot:

* **Policy Alternative A (Strict Least-Privilege Confinement):**
  * Allow all four roles to use the Global Chatbot, but dynamically inject authorization boundaries into the SQL / Vector retrieval clauses:
    * For `FINANCE_ANALYST`: Query automatically appends `AND documents.uploaded_by = :current_user_id`.
    * For `FINANCE_MANAGER`, `AUDITOR`, `ADMIN`: Query scans across all documents.
  * *Implication:* Analysts can ask cross-document questions about their own portfolio (*"Which of my uploaded invoices have discount terms?"*), maintaining consistency with `DocumentService.search()`.

* **Policy Alternative B (Role-Gated Global AI):**
  * Restrict the Global Chatbot endpoint entirely to `require_roles(UserRole.FINANCE_MANAGER, UserRole.ADMIN, UserRole.AUDITOR)`.
  * Return `403 Forbidden` to `FINANCE_ANALYST`.
  * *Implication:* Eliminates the risk of subtle prompt-injection attacks where an analyst attempts to bypass SQL/vector filters through adversarial jailbreaking.

> [!IMPORTANT]
> **Open Business & Security Decision:**  
> Whether `FINANCE_ANALYST` should have scoped access to the Global Chatbot (Policy A) or be barred entirely from cross-document conversational AI (Policy B) is a business risk decision. The technical architecture supports Policy A (in-retrieval SQL/JOIN confinement), which can be restricted to Policy B via FastAPI's `require_manager_or_admin` dependency if enterprise security mandates.

---

## 11. Tool-Based Conversational Agent Architecture

The Conversational AI operates as an **autonomous agent equipped with structured tools**. When a user asks a question, the LLM selects the correct tool based on intent:

```text
                                User Prompt
                                     │
                                     ▼
                       ┌───────────────────────────┐
                       │   Agent Router / Planner  │
                       │   (LLM Function Calling)  │
                       └─────────────┬─────────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
                 ▼ Intent: Metrics   ▼ Intent: Compute   ▼ Intent: Semantic
           ┌───────────┐       ┌───────────┐       ┌───────────┐
           │ Database  │       │ Financial │       │ Hybrid    │
           │ Query     │       │ Calculator│       │ Document  │
           │ Tool      │       │ Tool      │       │ RAG Tool  │
           └─────┬─────┘       └─────┬─────┘       └─────┬─────┘
                 │                   │                   │
                 ▼                   ▼                   ▼
           PostgreSQL SQL      Deterministic       Vector + BM25
           (Counts, Sums,      Date Arithmetic     + RRF + Cross
            Status Filters)    & Variance Math     Encoder Chunks
                 │                   │                   │
                 └───────────────────┼───────────────────┘
                                     │
                                     ▼
                       ┌───────────────────────────┐
                       │  Consolidated Answer &    │
                       │  Structured Citations     │
                       └───────────────────────────┘
```

### 1. Database Query Tool (`Text-to-SQL` / Schema-Constrained ORM)
* **Intent Trigger:** Quantitative, aggregative, count, status, or date-bound inquiries across documents.
  * *"How many invoices are in status VALIDATED?"*
  * *"Show all documents uploaded by analyst Jane in August."*
  * *"What is the total sum of invoices from vendor V-1002?"*
* **Architecture:** Uses a constrained, read-only SQL generator that queries relational tables (`documents`, `extraction_results`, `validation_results`). Never uses vector similarity search for exact counts or arithmetic sums.
* **Safety Controls:** Read-only PostgreSQL transaction (`SET TRANSACTION READ ONLY;`), 5-second timeout, explicit `LIMIT 100`, and strict SQL AST validation preventing DDL/DML operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`).

### 2. Financial Calculator Tool
* **Intent Trigger:** Deterministic financial arithmetic and date math.
  * *"What is the difference between the net amount and gross amount?"*
  * *"If this invoice is due on 2024-04-15 with a 2% 10-day discount, what is the exact payment deadline and discounted total?"*
* **Architecture:** Python numerical function executing `Decimal` precision calculations (preventing floating-point errors) and `datetime` calendar logic.

### 3. Document RAG Tool (Hybrid Retrieval Engine)
* **Intent Trigger:** Semantic, textual, policy, descriptive, or unstructured contractual inquiries.
  * *"What are the freight delivery terms?"*
  * *"Does this contract mention a penalty for late payment?"*
  * *"Summarize the special instructions from the vendor."*
* **Architecture:** Executes the Hybrid Retrieval Pipeline:
  1. Dense vector retrieval over `document_chunks` using `pgvector` (`<=>`).
  2. Sparse keyword retrieval over `tsv_content` using PostgreSQL FTS (`ts_rank_cd`).
  3. Reciprocal Rank Fusion (RRF) merging.
  4. Cross-Encoder reranking (`ms-marco-MiniLM-L-6-v2`).
  5. Injection of Top-5 chunks into the context window.

### 4. Compound Tool Coordination (SQL + RAG)
For multi-part questions, the agent coordinates tools sequentially:
* **User Query:** *"How much did we spend with ACME Supplies, and what early settlement discounts do their invoices mention?"*
* **Execution Flow:**
  1. **Step 1 (Database Tool):** Queries PostgreSQL for all invoices where `vendor_name ILIKE '%ACME Supplies%'`, calculates `SUM(grand_total_amount)` and extracts the matching `document_id` list `[12, 19, 42]`.
  2. **Step 2 (RAG Tool):** Executes Hybrid Retrieval scoped to `document_id IN (12, 19, 42)` searching for *"early settlement discount terms"*.
  3. **Step 3 (Synthesis):** Combines the SQL spending aggregate with the extracted discount clauses into a single grounded answer citing both database records and document text snippets.

---

## 12. Architectural Blueprint & Target Component Layout

The blueprint below specifies how the new RAG and conversational capabilities integrate into the existing EFDI layered backend without mutating core components:

```text
═══════════════════════════════════════════════════════════════════════════════════════
                              PRESENTATION LAYER (routers/)
═══════════════════════════════════════════════════════════════════════════════════════
   Existing API Routers:                      NEW Conversational AI Routers:
   ├── documents.py (Upload/Search)           ├── [NEW] chat.py (Document-level: /chat/document/{id})
   ├── ocr.py (OCR Processing)                └── [NEW] global_chat.py (Global: /chat/corpus)
   ├── classification.py (Classifier)
   ├── extraction.py (Field Extractor)
   └── validation.py (Rules Engine)
                                      │
                                      ▼ Depends(get_current_user), Depends(get_db)
═══════════════════════════════════════════════════════════════════════════════════════
                              APPLICATION LAYER (services/)
═══════════════════════════════════════════════════════════════════════════════════════
   Existing Services:                         NEW Conversational AI Services:
   ├── document_service.py                    ├── [NEW] rag_service.py (Hybrid Retrieval & RRF)
   ├── ocr_service.py                         ├── [NEW] chat_service.py (Agent Coordination & History)
   │     │ (Background Task on OCR Done)      ├── [NEW] text_to_sql_service.py (Constrained SQL)
   │     └───────────────────────────────────►└── [NEW] rag_ingestion_service.py (Chunk & Embed)
   ├── classification_service.py
   ├── extraction_service.py
   └── validation_service.py
                                      │
                                      ▼ Calls Domain Processors & Repositories
═══════════════════════════════════════════════════════════════════════════════════════
                              DOMAIN / PROCESSING SUBSYSTEMS
═══════════════════════════════════════════════════════════════════════════════════════
   Existing Domain Packages:                  NEW RAG Processing Package (app/rag/):
   ├── ocr/ (PyMuPDF, EasyOCR, Layout)        ├── [NEW] chunking.py (Structure-aware split)
   ├── classification/ (Rule, ML)             ├── [NEW] embeddings.py (384-dim Transformer)
   ├── extraction/ (Regex, LLM, Hybrid)       ├── [NEW] reranker.py (Cross-Encoder inference)
   └── validation/ (Rules, Math, Dupes)       └── [NEW] agent_tools.py (Tool bindings & Schema)
                                      │
                                      ▼ Database CRUD
═══════════════════════════════════════════════════════════════════════════════════════
                              DATA ACCESS LAYER (repositories/)
═══════════════════════════════════════════════════════════════════════════════════════
   Existing Repositories:                     NEW RAG Repositories:
   ├── document_repository.py                 ├── [NEW] chunk_repository.py (Vector & FTS query)
   ├── ocr_result_repository.py               └── [NEW] chat_history_repository.py (Thread/Turn store)
   ├── extraction_result_repository.py
   └── validation_result_repository.py
                                      │
                                      ▼ ORM Entities
═══════════════════════════════════════════════════════════════════════════════════════
                              PERSISTENCE & INFRASTRUCTURE
═══════════════════════════════════════════════════════════════════════════════════════
   Existing SQLAlchemy Models:                NEW / Reused Models:
   ├── Document (documents)                   ├── DocumentChunk (document_chunks table - EXISTING)
   ├── OCRResult (ocr_results)                │     ├── embedding: Vector(384) [HNSW indexed]
   ├── ExtractionResult                       │     ├── tsv_content: tsvector [GIN indexed]
   └── User (users)                           │     └── metadata_json: JSONB
                                              └── [NEW] ChatMessage (chat_messages table)
                                      │
                                      ▼ SQL / pgvector
   POSTGRESQL 18 DATABASE (Relational Tables + pgvector extension + Full-Text Search)
═══════════════════════════════════════════════════════════════════════════════════════
```

---

## 13. Implementation Roadmap & Milestones

The proposed RAG integration roadmap is organized into four distinct, self-contained implementation milestones:

```text
Milestone 1: Ingestion & Storage
  ├── Structure-Aware Chunking Engine (app/rag/chunking.py)
  ├── 384-dim Embedding Service (app/rag/embeddings.py)
  ├── Chunk Repository & Ingestion Service (app/repositories/chunk_repository.py)
  └── Asynchronous Ingestion Hook upon OCR_COMPLETED (app/services/ocr_service.py)

Milestone 2: Hybrid Retrieval Subsystem
  ├── PostgreSQL tsvector Full-Text Search integration on document_chunks
  ├── Reciprocal Rank Fusion (RRF) combiner (app/services/rag_service.py)
  ├── Cross-Encoder Reranker inference module (app/rag/reranker.py)
  └── Unit & Benchmarking retrieval test suite

Milestone 3: Level 1 Document Chatbot
  ├── Document Chat API Router (app/routers/chat.py :: /chat/document/{id})
  ├── Chat Service & History Repository (app/services/chat_service.py)
  ├── Grounded Financial Prompting with Citation Spans
  └── Frontend Document Viewer Sidebar Chatbot Component

Milestone 4: Level 2 Global Agentic Chatbot
  ├── Constrained Read-Only SQL Generator (app/services/text_to_sql_service.py)
  ├── Financial Arithmetic Calculator Tool
  ├── Multi-Tool Coordination Agent Planner (app/rag/agent_tools.py)
  ├── Pre-retrieval role-scoped authorization queries (FINANCE_ANALYST isolation)
  └── Global Chat API Router (app/routers/global_chat.py :: /chat/corpus)
```

---

## 14. Architecture Review Verification Checklist

* [x] **Zero Code Changes:** No existing source files, test files, or migrations were modified or created.
* [x] **Repo-Grounded Discovery:** All imports, paths, classes, and function names match real files in `backend/app/`.
* [x] **Canonical Text Preservation:** Identified that RAG must consume `OCRResult.full_text` rather than `ExtractionResult`.
* [x] **Asynchronous Decoupling:** Proved that RAG ingestion must run asynchronously after `OCR_COMPLETED` without blocking extraction or validation.
* [x] **Hybrid Retrieval Rigor:** Designed pgvector + PostgreSQL native FTS + RRF + Cross-Encoder reranking without adding external database infrastructure.
* [x] **Security & Authorization Rigor:** Audited all 4 user roles, identified the Analyst confinement requirement, and formally flagged the global AI policy as an open decision.
* [x] **Tool-Based Agent Architecture:** Modeled Database (SQL), Financial Calculator, and RAG tools with compound query orchestration.
