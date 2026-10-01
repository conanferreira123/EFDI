# EFDI Project Handover / User Manual

---

## 1. Introduction

### 1.1 Project Overview
The **Enterprise Financial Document Intelligence (EFDI)** system is a comprehensive, production-grade automation, validation, and conversational intelligence platform specifically designed for **Accounts Payable (AP)** and **Record-to-Report (R2R)** business functions. EFDI ingests complex financial documents—including PO-based vendor invoices, non-PO invoices, employee expense reimbursement claims, sales invoices, pay-in slips, journal entries, and bank documentation—and processes them through a multi-stage intelligent pipeline. 

The platform bridges the gap between unstructured document pixels/PDF streams and structured enterprise general ledgers by integrating layout-aware Optical Character Recognition (Docling TableFormer and EasyOCR CRAFT), automated taxonomic classification, parallel hybrid extraction (combining deterministic rules and Large Language Models), deterministic field reconciliation, business rule validation, strict approval workflow governance, immutable audit tracking, and dual-mode conversational AI (a document-scoped assistant and a portfolio-wide ReAct agent).

### 1.2 Purpose
In standard corporate accounting, accounts payable teams face high operational friction when processing financial documents. Common challenges include:
- Heterogeneous document structures across global vendors with varying tax conventions (e.g., GST, VAT, US Sales Tax).
- Multilingual and multi-page itemized line tables where columns wrap, merge, or lack visible grid borders.
- Extraction errors from OCR noise, leading digits being clipped, or synthetic document anomalies.
- Regulatory requirements for complete provenance and audit trails for financial figures.
- Cross-currency risks, where multi-currency invoices cannot be naively summed without proper foreign exchange handling.
- Need for immediate operational question-answering (e.g., identifying discount windows, penalties, or matching purchase order clauses) without manual document review.

EFDI addresses these challenges by automating document ingestion, data extraction, validation, and conversational reporting within an auditable, role-governed framework.

### 1.3 Key Capabilities
- **Document Ingestion & File Deduplication:** Multipart single upload, bulk batch upload, and administrator-governed local folder staging scan, backed by SHA-256 byte-level deduplication.
- **Layout-Preserving Neural OCR:** Primary engine using IBM's Docling with TableFormer neural structure recognition to produce clean, pipe-delimited Markdown tables and native vector chunking; secondary computer-vision fallback using PyMuPDF rasterization (200 DPI), Hough deskewing, CLAHE contrast enhancement, and CRAFT text detection.
- **Taxonomic Classification:** High-precision keyword and token signal scoring categorizing documents into the enterprise AP/R2R taxonomy (`POI`, `NPO`, `IMA`, `MSI`, `PSI`, `JER`, `BKA`), with human-in-the-loop correction capabilities.
- **Parallel Hybrid Extraction & Reconciliation:** Simultaneous execution of regex anchor-based extractors and Mistral AI LLM structured schema extractors via a multi-threaded orchestrator, followed by a deterministic reconciliation layer that evaluates arithmetic evidence, resolves conflicts, and tags explicit field provenance (`hybrid_agreement`, `rule_based`, `llm`, `unresolved_conflict`).
- **Normalized Relational Business Projection:** Automatic persistence of extracted entities into first-class relational tables (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`), enabling standard SQL aggregations without JSON parsing overhead.
- **Business Rule Validation:** Cross-field balance equations ($Subtotal + Tax = Grand Total$, $\sum LineTotals = Subtotal$) and mandatory field checks that govern workflow progression.
- **Four-Eye Approval Workflow:** Formal state machine enforcing separation of duties where Finance Analysts cannot approve their own submissions; approvals and rejections are restricted to Managers, Auditors, and Admins.
- **Scoped Document AI Copilot:** Conversational assistant embedded in the document detail view, isolated strictly to the active document (`document_id`), utilizing hybrid vector and full-text search with page citations and deterministic decimal arithmetic.
- **Portfolio-Wide Global AI Agent:** ReAct reasoning agent coordinating Text-to-SQL, corpus-wide RAG, and financial calculation tools, safeguarded by `sqlglot` AST security validation, tenant isolation injection, and multi-currency safety rules.
- **Comprehensive Audit Trail:** Immutable logging of every system, pipeline, workflow, and authentication event.

### 1.4 Technology Stack

| Layer | Technologies & Libraries | Key Components / Version |
|---|---|---|
| **Frontend Application** | React 18, TypeScript, Vite, TailwindCSS, React Router v6, Lucide Icons | [`frontend/src/App.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/App.tsx), AppShell layout, Tabbed Document Detail, Ask AI view |
| **Backend API Gateway** | Python 3.11+, FastAPI, Pydantic v2, Pydantic Settings, Uvicorn | [`backend/app/main.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/main.py), REST API under `/api/v1` prefix |
| **Database & ORM** | PostgreSQL 16, SQLAlchemy 2.0 (Mapped/Declarative), Alembic | pgvector extension (384-d vector embeddings), tsvector (PostgreSQL FTS), 18 relational tables |
| **Primary OCR & Table Parsing** | Docling (`docling`), TableFormer neural model, Docling Core | [`backend/app/ocr/docling_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py), Markdown table parser |
| **Secondary / Fallback OCR** | PyMuPDF (`fitz`), OpenCV (`cv2`), EasyOCR (PyTorch CRAFT + CRNN) | [`backend/app/ocr/easyocr_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/easyocr_engine.py), Adaptive preprocessor |
| **LLM Inference** | Mistral AI API (`mistral-small-2603`), Python `urllib` / `ChatMistralAI` | Extraction structured outputs (`json_schema`), Agent reasoning, Text-to-SQL generation |
| **Conversational AI & Agents** | LangChain Core, LangChain Community, Tool-Calling ReAct Loop | [`backend/app/rag/document_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py), [`backend/app/rag/global_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py) |
| **RAG Embeddings & Reranking** | HuggingFace Sentence-Transformers, Cross-Encoders | `all-MiniLM-L6-v2` (384 dimensions), `ms-marco-MiniLM-L-6-v2` Cross-Encoder reranker |
| **SQL Parsing & AST Security** | `sqlglot` | AST validation, table/column allowlists, automated tenant predicate injection |
| **Security & Cryptography** | `python-jose` (JWT), `passlib` (BCrypt password hashing) | Bearer token authentication, Role-Based Access Control (`UserRole`) |
| **Filesystem Storage** | Local filesystem | `uploads/` directory for uploaded documents, `intake/` for staging ingestion |

### 1.5 High-Level System Flow
```
User / Client (React SPA)
       │
       ▼
API Gateway (FastAPI /api/v1) ──[ JWT Authentication & RBAC ]
       │
       ├─► 1. Ingestion: DocumentService ──► Disk Storage & documents Table
       │
       ├─► 2. OCR: OCRService ──► Docling / EasyOCR ──► ocr_results Table
       │        └─► (Async Hook) RAGIngestionService ──► document_chunks (pgvector)
       │
       ├─► 3. Classification: ClassificationService ──► classification_results Table
       │
       ├─► 4. Extraction: ExtractionService (Hybrid Parallel: Rule + Mistral LLM)
       │        ├─► ReconciliationEngine ──► extraction_results Table
       │        └─► InvoicePersistenceService ──► invoices, vendors, line_items, obligations
       │
       ├─► 5. Validation: ValidationService ──► validation_results Table (Advances to VALIDATED)
       │
       ├─► 6. Approval Workflow: WorkflowService ──► PENDING_APPROVAL ──► APPROVED / REJECTED
       │
       └─► 7. Conversational AI:
                ├─► Document Chat: Scoped RAG + Financial Calculator (No SQL)
                └─► Global Chat: Text-to-SQL (AST-Guarded) + Global RAG + Calculator
```

---

## 2. Previous System

Evidence of the system's prior architecture is preserved in the repository commit history (commits `86ab973` through `e475567`), the initial Alembic migration scripts (`4cf4fda96099` through `bfd7768c6be6`), and legacy comments within [`backend/README.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/README.md).

### 2.1 Previous OCR Pipeline
- **Engine Architecture:** The original OCR pipeline relied exclusively on **EasyOCR** backed by PyMuPDF rasterization at 200 DPI (`zoom = 2.7778`) and OpenCV adaptive preprocessing.
- **Execution Flow:** Every document page was rasterized into an uncompressed NumPy image array, analyzed for skew via probabilistic Hough transforms (`cv2.HoughLinesP`), adjusted for contrast via CLAHE, and passed through CRAFT detection and CRNN character recognition.
- **Table Detection:** Table structure was derived solely through post-hoc 2D geometric clustering heuristics ([`app/ocr/table_reconstruction.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/table_reconstruction.py)). It scanned for horizontal column header bands (e.g., "DESCRIPTION", "UNIT PRICE") and clustered numeric cells using coordinate intervals.
- **Multi-Page Table Limitation:** In the previous implementation, table reconstruction was performed exclusively on the first page (`raw_blocks[0]`), resulting in data loss for multi-page tables.
- **Alternative Engines:** A PaddleOCR engine implementation existed in the repository ([`app/ocr/paddle_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/paddle_engine.py)) but was disabled due to native C++ crashes on non-x86/ARM environments.

### 2.2 Previous Classification Pipeline
- **Mechanism:** Implemented as a regex-based token matcher ([`app/classification/rule_based.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/classification/rule_based.py)).
- **Input:** Consumed exclusively the synthesized `ocr_result.full_text` string.
- **Scoring:** Matched predefined document type keywords (e.g., "PURCHASE ORDER", "CREDIT NOTE", "REIMBURSEMENT") with fixed weights.
- **Limitation:** Had zero spatial or bounding-box awareness; could be misled if header words appeared in line item descriptions.

### 2.3 Previous Extraction Pipeline
- **Engine Architecture:** Relied primarily on [`RuleBasedExtractor`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/rule_based.py), utilizing rigid regular expression anchors and coordinate bounding boxes.
- **Initial LLM Integration:** A basic LLM extraction track was introduced using local Ollama or basic completion calls, but it lacked robust structured output enforcement and schema synchronization.
- **Persistence:** Extracted fields were serialized exclusively as an untyped JSON blob stored in `extraction_results.fields`. Relational tables for invoices and line items did not exist in the initial database revisions.

### 2.4 Previous Validation Pipeline
- **Engine:** Evaluated basic rule presence against extracted fields (e.g., checking if invoice number was present).
- **Execution:** Ran arithmetic cross-checks via [`app/validation/engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/validation/engine.py) directly on values parsed from `extraction_results.fields`.

### 2.5 Previous Workflow
- **State Model:** Maintained document states: `UPLOADED`, `OCR_COMPLETED`, `EXTRACTED`, `VALIDATED`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`.
- **Enforcement:** Enforced in Python via [`app/workflow/state_machine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/workflow/state_machine.py), with review events captured in `workflow_history`.

### 2.6 Previous Database Architecture
The initial database schema (Alembic revisions `4cf4fda96099` to `bfd7768c6be6`) consisted of only 10 base tables:
1. `users`
2. `documents`
3. `ocr_results`
4. `classification_results`
5. `extraction_results`
6. `validation_results`
7. `workflow_history`
8. `audit_logs`
9. `training_examples`
10. `system_settings`

At this stage, there were no relational financial tables (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`), no vector extension or chunk tables (`document_chunks`), and no conversational AI chat tables (`chat_sessions`, `chat_messages`).

---

## 3. Modifications Over the Previous System

### 3.1 OCR Pipeline Modification
- **Previous Behavior:** EasyOCR rasterized all documents to 200 DPI images, preprocessed them with OpenCV filters, ran CRAFT detection, and inferred tables through 2D bounding-box geometric intervals on page 1 only.
- **Current Behavior:** [`DoclingEngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py) is the default production engine (`settings.OCR_DEFAULT_ENGINE = "docling"`). It directly ingests native PDF/image paths into IBM's Docling `DocumentConverter`, utilizing TableFormer neural models to detect table structures and cell matching natively, generating canonical Markdown with pipe-delimited tables across all document pages. EasyOCR remains as a CV fallback track.
- **What Changed:** Introduced `DoclingEngine`, `parse_markdown_table()`, dual-track branching in `OCRService.run_ocr()`, and an async RAG trigger hook upon OCR completion.
- **Why It Changed:** EasyOCR suffered from high compute overhead, memory spikes during PDF rasterization, font clipping on leading digits, and table reconstruction failures on multi-page documents. Docling provides vector PDF extraction and multi-page table accuracy.
- **Impact:** Extraction quality improved on multi-page invoices; processing latency decreased on vector PDFs; multi-page line items are preserved in canonical Markdown tables.

### 3.2 Extraction Pipeline Modification
- **Previous Behavior:** Rule-based extractor and basic LLM extractor were invoked separately as alternative options without reconciliation or structured output enforcement.
- **Current Behavior:** [`HybridExtractor`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/parallel_orchestrator.py) is the system default. It executes `RuleBasedExtractor` and `LLMBasedExtractor` concurrently using a multi-threaded orchestrator. The independent results are reconciled by [`ReconciliationEngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/reconciliation.py), which checks semantic/format equivalence, applies table evidence overrides, and records field-level provenance (`hybrid_agreement`, `rule_based`, `llm`, `unresolved_conflict`).
- **What Changed:** Added `ParallelExtractionOrchestrator`, `ReconciliationEngine`, dynamic Pydantic schema synthesis (`app/extraction/llm_schema.py`), layout context formatting (`app/extraction/llm_context_builder.py`), and Mistral JSON schema integration.
- **Why It Changed:** Rule-based regex failed on layout variations; pure LLMs occasionally hallucinated digits or omitted line items. Combining them provides deterministic verification of arithmetic data while leveraging LLM semantic understanding for party details.
- **Impact:** Eliminates silent field overrides; highlights genuine conflicts for human review; achieves high accuracy on complex financial fields.

### 3.3 RAG Integration
- **Previous Behavior:** No RAG subsystem existed. Documents could only be inspected via flat OCR text or raw bounding boxes.
- **Current Behavior:** Fully integrated semantic RAG pipeline powered by PostgreSQL `pgvector`. Automatically triggered in the background upon document OCR completion ([`RAGIngestionService.ingest_document_async`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py)). Documents are split into semantic chunks with 384-dimensional embeddings generated via `sentence-transformers/all-MiniLM-L6-v2`.
- **What Changed:** Added `document_chunks` table, HNSW vector indexing, PostgreSQL FTS `tsvector` columns, `RAGIngestionService`, and `RAGService`.
- **Why It Changed:** Enables unstructured contractual search (e.g., locating hidden penalty clauses, Incoterms, payment conditions) and powers conversational assistants.
- **Impact:** Sub-second retrieval of relevant clauses with page-level citations across large document collections.

### 3.4 Document-Level Chatbot
- **Previous Behavior:** No conversational capabilities existed for documents.
- **Current Behavior:** An interactive chat assistant embedded in the Document Detail view (`/documents/:id` $\rightarrow$ "Analyze with AI"). Governed by [`DocumentReActAgent`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py), scoped strictly to a single `document_id`. Equipped with `DocumentRAGTool` and `FinancialCalculatorTool`. **Text-to-SQL is strictly excluded.**
- **What Changed:** Added `/api/v1/chat/documents/{id}/*` endpoints, `DocumentReActAgent`, `DocumentRAGTool`, and specialized AP invoice summary prompt directives.
- **Why It Changed:** Enables finance clerks to query specific documents, calculate cash discount deadlines, and generate structured summaries without navigating multiple screens.
- **Impact:** Reduced manual review time for complex commercial invoices.

### 3.5 Global Chatbot
- **Previous Behavior:** No portfolio-wide reporting or natural-language query mechanism existed; users relied on basic document search filters.
- **Current Behavior:** A portfolio-wide conversational copilot accessible via `/chat` ("Ask AI"). Governed by [`GlobalReActAgent`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py). Orchestrates three specialized tools: `database_query_tool` (Text-to-SQL), `document_rag_tool` (unstructured search), and `financial_calculator_tool` (deterministic math).
- **What Changed:** Added `/api/v1/chat/corpus/*` endpoints, `GlobalReActAgent`, `DatabaseQueryTool`, `TextToSQLService`, and AST security validation via `sqlglot`.
- **Why It Changed:** Allows finance managers and auditors to query cross-document metrics (e.g., "Total spend with Acme in 2026", "Count of unapproved invoices") in natural language.
- **Impact:** Eliminates the need for manual SQL report generation for operational finance inquiries.

### 3.6 Database Modifications
- **Previous Behavior:** Database stored only flat document metadata, raw JSON OCR blocks, and JSON extraction dumps.
- **Current Behavior:** Database expanded to include:
  1. `document_chunks`: Stores vector embeddings (pgvector `vector(384)`), full-text search `tsvector`, and chunk metadata.
  2. `chat_sessions` & `chat_messages`: Stores multi-turn conversations, tool execution logs, structured session states, and citations.
  3. Relational business ledger: `invoices`, `vendors`, `vendor_aliases`, `invoice_line_items`, `payment_obligations`, `invoice_payments`.
  4. `document_user_activity`: Tracks user document interaction history.
- **What Changed:** Alembic migrations `018069fabf68` through `3f80e3e7b361` added 8 new tables, HNSW indexes, GIN full-text search indexes, and foreign key relationships.
- **Why It Changed:** Required to support semantic search, conversation history, and high-performance SQL analytics without querying raw JSONB fields.
- **Impact:** Enabled sub-millisecond relational queries and hybrid vector search directly within PostgreSQL.

### 3.7 Security / Authorization Modifications
- **Previous Behavior:** Basic JWT route protection and role checks on document upload and workflow approval.
- **Current Behavior:** Multi-layered defense-in-depth security:
  1. AST-based SQL Query Rewriting: `TextToSQLService` uses `sqlglot` to parse queries, rejecting non-SELECT operations, enforcing table/column allowlists, and forcibly injecting tenant filters (`uploaded_by = user.id`) and soft-delete filters (`is_deleted = false`) directly into the AST.
  2. Pre-Retrieval RAG Filtering: Vector queries enforce tenant boundaries at the SQL level before embeddings are evaluated.
  3. Strict Column Redaction: Column `users.password_hash` is explicitly excluded from the SQL allowlist.
  4. Document Scoping: Document Chat enforces document ownership and excludes the Text-to-SQL tool entirely.
- **What Changed:** Introduced `TextToSQLService` AST validation layer, `ROLE_ALLOWED_TABLES`, `ALLOWED_COLUMNS`, and `GLOBAL_CHAT_ANALYST_POLICY`.
- **Why It Changed:** Natural language Text-to-SQL poses severe data leakage and injection risks if left unconstrained.
- **Impact:** Safe natural language database queries without risk of SQL injection, cross-tenant data leaks, or credential exposure.

### 3.8 Other Relevant Modifications
- **Context Management:** Introduced [`ConversationContextResolver`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/context_resolver.py) to resolve pronouns, de-alias references, detect affirmative/negative confirmations, and ask clarifying questions before calling tools.
- **Execution Guardrails:** Introduced [`app/rag/response_guardrails.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/response_guardrails.py) to intercept execution-state probing queries, handle global request timeouts (30s), and prevent multi-currency summing anomalies.

---

## 4. Old Architecture — Component Description

### 4.1 Old OCR
- **Implementation File:** [`backend/app/ocr/easyocr_engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/easyocr_engine.py), [`backend/app/ocr/preprocessing.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/preprocessing.py)
- **Rasterization:** PyMuPDF (`fitz.open()`) converted PDF pages to RGB pixmaps at 200 DPI (`matrix = fitz.Matrix(200/72, 200/72)`), converted to BGR NumPy arrays.
- **Preprocessing:** Measured image variance of the Laplacian (sharpness) and standard deviation of grayscale intensities (contrast). Skew was computed using Canny edge detection and probabilistic Hough lines (`HoughLinesP`). Affine warp matrix straightened pages with skew $> 0.8^\circ$. Contrast Limited Adaptive Histogram Equalization (CLAHE) was applied if contrast standard deviation was $< 35.0$.
- **Detection & Recognition:** PyTorch EasyOCR reader ran with `detail=1` and `add_margin=0.10`, producing 4-corner polygon bounding boxes and confidence scores.
- **Layout & Table Ordering:** Bounding boxes were sorted into reading order bands ([`app/ocr/layout.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/layout.py)). `TableReconstructor` scanned for keywords across 8 columns, derived gutter boundaries, clustered rows by vertical center overlap, and generated Markdown text.
- **Limitations:** Only page 1 (`raw_blocks[0]`) was analyzed for structured tables; high CPU/memory consumption on multi-page rasterization.

### 4.2 Classification
- **Implementation File:** [`backend/app/classification/rule_based.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/classification/rule_based.py)
- **Engine:** `RuleBasedClassifier` scanned `ocr_result.full_text` for weighted token signals across 7 active document types:
  - `POI`: PO-based invoice ("purchase order", "po number", "order no")
  - `NPO`: Non-PO invoice ("tax invoice", "bill to", "remit to")
  - `IMA`: Employee reimbursement ("expense report", "claim form", "employee id")
  - `MSI`: Sales invoice ("customer invoice", "commercial invoice")
  - `PSI`: Pay-in slip ("deposit slip", "receipt voucher")
  - `JER`: Journal entry ("debit", "credit", "general ledger")
  - `BKA`: Bank document ("bank statement", "account balance", "iban")
- **Limitations:** Dependent on string matching; no layout or visual position weighting.

### 4.3 Old Extraction
- **Implementation File:** [`backend/app/extraction/rule_based.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/rule_based.py)
- **Regex Parsing:** Compiled regular expressions searched for common anchor terms (e.g., `(?i)invoice\s*(?:no|number|#)[:\s]*([A-Z0-9-]+)`).
- **Geometric Value Capture:** Scanned text blocks directly below or to the right of detected anchor bounding boxes.
- **Normalization:** Formatted dates to ISO `YYYY-MM-DD` and cleaned currency symbols to floating-point numbers.
- **Limitations:** Rigid anchors broke on creative vendor invoice layouts; address parsing frequently truncated multi-line company names.

### 4.4 Validation
- **Implementation File:** [`backend/app/validation/engine.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/validation/engine.py)
- **Rules Evaluated:**
  - Mandatory fields check (e.g., invoice number, date, vendor name, grand total).
  - Date syntax check (valid ISO calendar date, not in future beyond 30 days).
  - Arithmetic balance check ($Net + Tax = Gross$).
  - Line items sum check ($\sum NetAmount = Subtotal$).
- **Outcome:** Emitted `ValidationResult` with `is_valid` boolean and issues list. If zero `ERROR`-level issues existed, document status advanced to `VALIDATED`.

### 4.5 Old Database Model
The initial relational structure was limited to managing the linear lifecycle of uploaded files:
- `users` (credentials and role)
- `documents` (file metadata and status)
- `ocr_results` (raw JSON blocks and full text)
- `classification_results` (predicted type)
- `extraction_results` (JSON fields blob)
- `validation_results` (issues array)
- `workflow_history` (transition timestamps)
- `audit_logs` (event logs)

Existing architectural diagrams documenting this initial phase are cataloged in [Section 12](#12-architecture-diagram-inventory).

---

## 5. New Architecture — Component Description

### 5.1 New OCR
- **Primary Engine:** [`DoclingEngine`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/docling_engine.py) (`name = "docling"`).
- **Architecture:** Directly ingests document files (PDF, PNG, JPEG) via Docling's `DocumentConverter`.
  - Native PDF vector parsing extracts text directly from PDF digital text streams when available.
  - Neural TableFormer model recognizes complex table layouts, merged header cells, and column boundaries without relying on heuristic coordinate gutters.
  - Multi-page Markdown export (`doc.export_to_markdown()`) stitches all document pages into a continuous, structured Markdown document.
  - Structured Markdown tables are parsed into typed dictionaries via [`parse_markdown_table()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/ocr/markdown_table_parser.py).
- **Runtime Normalization:** Parses US/European decimals, ISO dates, and interprets VAT rates arithmetically.
- **Async RAG Ingestion Hook:** Automatically hands off the parsed `docling_document` to [`RAGIngestionService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py) in a background thread, triggering immediate chunking and vector indexing upon reaching `OCR_COMPLETED`.

### 5.2 New Extraction
- **Orchestration:** [`HybridExtractor`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/parallel_orchestrator.py) (`name = "hybrid"`).
- **Parallel Dispatch:** Executes `RuleBasedExtractor` and `LLMBasedExtractor` concurrently using `ThreadPoolExecutor(max_workers=2)`.
- **LLM Structured Extraction:**
  - Dynamically synthesizes Pydantic schemas ([`NPOExtractionPayload`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/llm_schema.py) for hierarchical NPO; dynamic Pydantic models for other types).
  - Constructs layout-aware prompt ([`LLMContextBuilder`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/llm_context_builder.py)) containing full OCR text, reconstructed Markdown tables, spatial Left/Right party columns, and quality metrics.
  - Calls Mistral API (`mistral-small-2603`) with `temperature=0.0` and `response_format={"type": "json_schema"}`.
- **Reconciliation Engine:**
  - Compares Rule and LLM values for semantic and format equivalence.
  - Assigns table-derived values precedence for line items and arithmetic amounts.
  - Assigns LLM values precedence for complex party names and addresses.
  - Flags irreconcilable discrepancies as `unresolved_conflict` with competing values preserved.
- **Relational Business Ledger Projection:** [`InvoicePersistenceService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py) synchronizes extracted fields to normalized relational tables: `vendors`, `invoices`, `invoice_line_items`, and `payment_obligations`.

### 5.3 Document-Level Chatbot
- **Implementation File:** [`backend/app/rag/document_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py)
- **Class:** `DocumentReActAgent`
- **Scoping:** Hard-scoped to a single `document_id`. Pre-retrieval SQL filtering forces all vector and keyword searches to match `document_id = :enforced_document_id`.
- **Preconditions:** Enforces that OCR has completed before answering document content questions.
- **Tool Access:** Limited strictly to:
  1. `document_rag_tool`: Retrieves hybrid vector + FTS chunks from this document.
  2. `financial_calculator_tool`: Computes exact decimal formulas, discounts, and payment deadlines.
- **Text-to-SQL:** **Strictly excluded.**
- **Output Directives:** Implements a specialized 5-section "Invoice Summary" format for summary requests, while enforcing concise, direct answers for specific inquiries.

### 5.4 Global Chatbot
- **Implementation File:** [`backend/app/rag/global_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py)
- **Class:** `GlobalReActAgent`
- **Scoping:** Portfolio-wide across all authorized documents.
- **Tool Access:** Coordinates three specialized tools:
  1. `database_query_tool`: Natural language to SQL query execution with AST validation.
  2. `document_rag_tool`: Semantic retrieval across all authorized documents.
  3. `financial_calculator_tool`: Deterministic arithmetic, batch discounts, and date offsets.
- **Security & Multi-Currency:** Enforces `sqlglot` AST validation, tenant ownership injection, and strict prohibition of summing monetary values across heterogeneous currencies without grouping.

### 5.5 New Database Architecture
The database schema was expanded via Alembic migrations `018069fabf68` through `3f80e3e7b361` to 18 tables:
- **Core Document:** `documents`, `document_user_activity`
- **Processing Results:** `ocr_results`, `classification_results`, `extraction_results`, `validation_results`
- **Relational Business Projection:** `invoices`, `vendors`, `vendor_aliases`, `invoice_line_items`, `payment_obligations`, `invoice_payments`
- **Governance & Audit:** `workflow_history`, `audit_logs`
- **Vector & RAG:** `document_chunks` (with pgvector HNSW index and GIN FTS index), `vendor_knowledge`
- **Conversational State:** `chat_sessions`, `chat_messages`
- **Authentication & System:** `users`, `system_settings`, `training_examples`

---

## 6. Comparative Study

### 6.1 Old vs New System

| Architectural Feature | Previous System (Phases 1–10 Initial) | Current System (Active Implementation) |
|---|---|---|
| **Default OCR Engine** | EasyOCR (CRAFT + CRNN via PyTorch) | **Docling** (DocumentConverter + TableFormer) |
| **PDF Processing Method** | PyMuPDF rasterization to 200 DPI BGR image arrays | Direct vector PDF stream extraction & neural parsing |
| **Table Recognition** | Heuristic 2D geometric intervals (Page 1 only) | Neural TableFormer cell recognition across all pages |
| **Default Extraction Engine** | Rule-Based Extractor | **Hybrid Extractor** (Parallel Rule + Mistral LLM) |
| **Extraction Reconciliation** | None (engines ran in isolation) | **Deterministic Reconciliation Engine** with provenance |
| **Financial Business Ledger** | Untyped JSON dump in `extraction_results.fields` | Normalized relational tables (`invoices`, `line_items`, etc.) |
| **Document Chat** | Not present | Scoped `DocumentReActAgent` (RAG + Calculator) |
| **Portfolio Global Chat** | Not present | Portfolio `GlobalReActAgent` (SQL + RAG + Calculator) |
| **Text-to-SQL Governance** | None | `sqlglot` AST security & forced tenant predicate injection |
| **RAG Vector Storage** | None | PostgreSQL `pgvector` (`vector(384)`) with HNSW index |
| **Database Table Count** | 10 tables | **18 tables** |

### 6.2 OCR Comparison
- **Previous:** Rasterized all PDF pages into images; applied deskewing and CLAHE contrast filters; ran CRAFT detector; sorted bounding boxes; reconstructed tables via horizontal coordinate intervals on page 1 only. Prone to character clipping and multi-page table truncation.
- **Current:** Passes document paths directly to Docling. Leverages native digital text streams and TableFormer neural network for table structure. Produces multi-page Markdown with pipe-delimited tables. EasyOCR remains as fallback. Triggers async vector indexing upon OCR completion.

### 6.3 Extraction Comparison
- **Previous:** Relied on rigid regular expression anchors and coordinate proximity. Failed on unseen invoice layouts. Basic LLM track lacked strict JSON schema enforcement.
- **Current:** `HybridExtractor` runs Rule and LLM engines concurrently via `ThreadPoolExecutor`. LLM uses dynamic Pydantic schemas and enriched layout prompts. `ReconciliationEngine` compares values, applies table evidence overrides, and records provenance. Results are synchronized to relational ledger tables.

### 6.4 Conversational AI Addition
- **Previous:** No conversational capabilities existed.
- **Current:** Dual-tier conversational system:
  1. *Document Assistant:* Scoped strictly to single document; uses hybrid vector + FTS retrieval and decimal calculator; Text-to-SQL excluded.
  2. *Global Copilot:* Multi-tool ReAct agent coordinating AST-governed Text-to-SQL, corpus RAG, and financial calculation tools.

### 6.5 Database Model Comparison
- **Previous:** Stored only document metadata, raw JSON blocks, and extraction JSON blobs across 10 tables.
- **Current:** 18 tables including normalized relational financial entities (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`), vector chunks (`document_chunks`), chat history (`chat_sessions`, `chat_messages`), and user activity tracking.

### 6.6 Security / RBAC Comparison
- **Previous:** Basic JWT endpoint protection; role checks on document upload and workflow actions.
- **Current:** Defense-in-depth security:
  - AST-level query validation using `sqlglot` enforcing SELECT-only, table allowlists, and forced tenant ownership predicates.
  - Pre-retrieval SQL filtering in vector search.
  - Password hash column explicitly redacted from SQL allowlist.
  - Document-level assistant strictly isolates retrieval to the target document.

---

## 7. Chatbot Architecture

### 7.1 Chatbot Overview
EFDI implements two distinct conversational agents to satisfy different operational workflows:
1. **Document-Level Chatbot:** Scoped strictly to one document for clause checking, terms verification, and invoice summaries.
2. **Global Corpus Chatbot:** Scoped portfolio-wide for aggregate queries, financial calculations, and cross-document analytics.

### 7.2 Document-Level Chatbot
- **API Route:** `POST /api/v1/chat/documents/{document_id}/messages`
- **Service & Agent:** [`ChatService.send_document_message()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py) dispatches to [`DocumentReActAgent`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py).
- **Tools Available:**
  1. `document_rag_tool`: Enforces `enforced_document_id = document.id`.
  2. `financial_calculator_tool`: Deterministic Decimal arithmetic.
- **Excluded Tools:** `database_query_tool` (Text-to-SQL) is **strictly excluded**.
- **OCR Precondition:** Refuses content queries if OCR has not been executed on the document.
- **Prompt Architecture:** Implements a strict 5-section "Invoice Summary" format for summary requests, and concise answers for normal questions.

### 7.3 Global Chatbot
- **API Route:** `POST /api/v1/chat/corpus/messages`
- **Router & Agent:** [`backend/app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py) dispatches to [`GlobalReActAgent`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py).
- **Tools Available:**
  1. `database_query_tool`: Relational SQL queries via `TextToSQLService`.
  2. `document_rag_tool`: Portfolio-wide hybrid RAG search via `RAGService`.
  3. `financial_calculator_tool`: Decimal arithmetic and batch discount calculations.
- **Multi-Currency Safety:** Prohibits summing monetary values across heterogeneous currencies without explicit currency grouping.

### 7.4 ReAct Architecture
Both agents implement the **ReAct (Reasoning + Acting)** pattern using LangChain tool calling:
- **Maximum Iterations:** 5 iterations (`MAX_ITERATIONS = 5`).
- **Loop Flow:**
  1. Model receives message history and system prompt.
  2. Model determines whether to invoke tools or produce final answer.
  3. Tool executions produce structured observations appended as `ToolMessage`.
  4. Loop repeats until model produces final answer or reaches iteration limit.
- **Loop Guard:** `_is_duplicate_call()` intercepts and suppresses repeated identical tool calls.
- **Timeout Management:** Enforces a global request deadline (`settings.CHAT_REQUEST_TIMEOUT_SECONDS = 30.0s`). If the deadline is reached, returns `GLOBAL_TIMEOUT_MESSAGE` gracefully.

### 7.5 Available Tools

| Tool Identifier | Tool Class | Implementation | Responsibilities | Agent Availability |
|---|---|---|---|---|
| `document_rag_tool` | `DocumentRAGTool` | [`app/rag/tools/rag_tool.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/tools/rag_tool.py) | Hybrid semantic search across document chunks with page citations | **Both** (Document Chat enforces single `document_id`) |
| `financial_calculator_tool` | `FinancialCalculatorTool` | [`app/rag/tools/calculator_tool.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/tools/calculator_tool.py) | Decimal precision math, cash discounts, batch discounts, date offsets | **Both** |
| `database_query_tool` | `DatabaseQueryTool` | [`app/rag/tools/database_tool.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/tools/database_tool.py) | Natural language to SQL query execution with AST validation | **Global Chat Only** (Excluded from Document Chat) |

### 7.6 RAG Architecture
- **Ingestion:** [`RAGIngestionService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py) chunks documents using `DoclingNativeChunker` (for Docling documents) or `StructureAwareChunker` (for EasyOCR documents). Generates 384-dimensional embeddings using `sentence-transformers/all-MiniLM-L6-v2`. Idempotently replaces old chunks in `document_chunks`.
- **Hybrid Retrieval:** [`RAGService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py) combines:
  1. *Dense Vector Search:* Top 30 chunks via pgvector cosine distance (`embedding <=> query_vector`).
  2. *Sparse Keyword Search:* Top 30 chunks via PostgreSQL full-text search (`ts_rank_cd(tsv_content, websearch_to_tsquery('english', query))`).
  3. *Reciprocal Rank Fusion (RRF):* Combines rankings using formula $Score = \sum \frac{1}{60 + rank}$, selecting top 25 candidates.
  4. *Cross-Encoder Reranking:* Reranks top 25 candidates using `cross-encoder/ms-marco-MiniLM-L-6-v2`, returning top 5 grounded chunks.

### 7.7 Database Query Architecture
- **Service:** [`TextToSQLService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py)
- **Workflow:**
  1. *Prompting:* Feeds table schemas, relationships, and temporal context to Mistral to generate candidate PostgreSQL SELECT queries.
  2. *AST Validation:* `sqlglot` parses query AST; enforces SELECT-only; checks tables against `ROLE_ALLOWED_TABLES`; checks columns against `ALLOWED_COLUMNS`; blocks dangerous functions (`pg_sleep`, `dblink`, etc.).
  3. *Predicate Injection:* Automatically appends `uploaded_by = user.id` (for Finance Analysts) and `is_deleted = false` directly into the AST WHERE clause.
  4. *Execution:* Connects via `engine.connect()`, sets `TRANSACTION READ ONLY`, sets statement timeout to 5000ms, and enforces `LIMIT 100`.

### 7.8 Financial Calculator
- **Module:** [`backend/app/rag/financial_calculator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py)
- **Class:** `FinancialCalculator`
- **Capabilities:**
  - Evaluates arithmetic expressions using Python's `decimal.Decimal` with `ROUND_HALF_UP` bankers rounding.
  - Computes cash settlement discounts: $DiscountAmount = Gross \times \frac{Percentage}{100}$, $NetPayable = Gross - DiscountAmount$.
  - Computes deadline dates by adding day offsets to ISO invoice dates.
  - Executes batch multi-invoice discount calculations with strict currency isolation.

### 7.9 Chat Persistence
- **Models:** [`ChatSession`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) and [`ChatMessage`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py)
- **Tables:** `chat_sessions` and `chat_messages`
- **Session Types:** `"DOCUMENT"` (stores `document_id`) or `"GLOBAL"` (`document_id` is NULL).
- **State JSON:** `chat_sessions.state_json` maintains structured conversation state (`active_document_id`, `pending_offer`, `verified_facts`).
- **Message Turns:** `chat_messages` stores message role (`user`, `assistant`), message text, `tool_calls` (JSONB execution logs), and `citations` (JSONB grounded sources).

---

## 8. Chatbot Authorization & RBAC

### 8.1 Authentication
- **Mechanism:** OAuth2 Password Bearer flow issuing signed JSON Web Tokens (JWT).
- **Token Claims:** Contains `sub` (username) and expiration timestamp.
- **Dependency:** [`get_current_user`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py) validates the token against `settings.SECRET_KEY` and resolves the active `User` record.

### 8.2 Document-Level Authorization
- Enforced in [`DocumentService.get_for_user(document_id, user)`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py):
  - `FINANCE_ANALYST`: Can only access documents where `uploaded_by == user.id`. Accessing another user's document raises HTTP 403.
  - `FINANCE_MANAGER`, `AUDITOR`, `ADMIN`: Can access any document.
  - Soft-deleted documents (`is_deleted == True`) are inaccessible to all roles.

### 8.3 Global Chat Authorization
- Enforced in [`app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py):
  - Configured by `settings.GLOBAL_CHAT_ANALYST_POLICY`:
    - `"scoped"` (default): Finance Analysts can use Global Chat, but queries are row-level filtered to their own uploaded documents.
    - `"forbidden"`: Finance Analysts receive HTTP 403 Forbidden.
  - Managers, Auditors, and Admins have unrestricted portfolio-wide access.

### 8.4 Role Definitions
- Defined in [`backend/app/models/roles.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/roles.py):
  - `FINANCE_ANALYST`: Operational user uploading, processing, and reviewing own invoices.
  - `FINANCE_MANAGER`: Supervisory user reviewing, approving, or rejecting documents; viewing all portfolio analytics.
  - `AUDITOR`: Compliance user inspecting audit trails, workflow histories, and system logs; approving/rejecting documents.
  - `ADMIN`: Full administrative user managing user accounts, running folder intake scans, and executing system-level queries.

### 8.5 Database Table Access Matrix

The following matrix documents the verified database table accessibility for each chatbot and role based on actual code inspection of [`TextToSQLService`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py), [`ChunkRepository`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py), and [`ChatHistoryRepository`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py):

| Database Table | Document Chatbot | Global Chatbot | FINANCE_ANALYST (Global Chat) | FINANCE_MANAGER (Global Chat) | AUDITOR (Global Chat) | ADMIN (Global Chat) | Access Path & Restrictions |
|---|---|---|---|---|---|---|---|
| **`documents`** | Accessible | Accessible | Scoped: `uploaded_by = user.id` | All non-deleted | All non-deleted | All non-deleted | Doc Chat via Service; Global Chat via SQL AST injection. |
| **`invoices`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Inaccessible to Doc Chat (No SQL tool). |
| **`invoice_line_items`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through parent invoice. |
| **`vendors`** | **Inaccessible** | Accessible | Scoped: vendors on own docs | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through parent invoice. |
| **`vendor_aliases`** | **Inaccessible** | Accessible | Scoped: vendors on own docs | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through parent invoice. |
| **`payment_obligations`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through parent invoice. |
| **`invoice_payments`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through parent invoice. |
| **`extraction_results`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through `document_id`. |
| **`classification_results`**| **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through `document_id`. |
| **`validation_results`** | **Inaccessible** | Accessible | Scoped: own documents only | All non-deleted | All non-deleted | All non-deleted | Global Chat SQL. Scoped through `document_id`. |
| **`workflow_history`** | **Inaccessible** | Accessible | **FORBIDDEN** | **FORBIDDEN** | **Accessible** | **Accessible** | Global Chat SQL. Allowed ONLY for AUDITOR and ADMIN. |
| **`users`** | **Inaccessible** | Accessible | **FORBIDDEN** | **FORBIDDEN** | **FORBIDDEN** | **Accessible** | Global Chat SQL. Allowed ONLY for ADMIN (`password_hash` redacted). |
| **`document_chunks`** | Accessible | Accessible | Scoped: `uploaded_by = user.id` | All non-deleted | All non-deleted | All non-deleted | RAG tool via `ChunkRepository`. Doc Chat enforces `document_id`. |
| **`ocr_results`** | Accessible | **Inaccessible** | Inaccessible | Inaccessible | Inaccessible | Inaccessible | Doc Chat checks status via Service. Excluded from SQL allowlist. |
| **`chat_sessions`** | Accessible | Accessible | Scoped: `user_id = user.id` | Scoped to self | Scoped to self | Scoped to self | Repository-mediated session management. |
| **`chat_messages`** | Accessible | Accessible | Scoped to user's session | Scoped to session | Scoped to session | Scoped to session | Repository-mediated message turns and citations. |
| **`document_user_activity`**| Accessible | **Inaccessible** | Inaccessible | Inaccessible | Inaccessible | Inaccessible | Doc Chat writes access log via Service. Excluded from SQL. |
| **`audit_logs`** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | Strictly excluded from all chatbot tools to protect audit integrity. |
| **`system_settings`** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | Excluded from chatbot SQL allowlists. |
| **`training_examples`** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | Excluded from chatbot SQL allowlists. |
| **`vendor_knowledge`** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | **Inaccessible** | Excluded from chatbot SQL allowlists. |

### 8.6 Document-Level Chatbot Access Summary
- **Accessible Tables (6):** `documents`, `document_chunks`, `ocr_results`, `document_user_activity`, `chat_sessions`, `chat_messages`.
- **Inaccessible Tables (15):** `invoices`, `invoice_line_items`, `vendors`, `vendor_aliases`, `payment_obligations`, `invoice_payments`, `extraction_results`, `classification_results`, `validation_results`, `workflow_history`, `users`, `audit_logs`, `system_settings`, `training_examples`, `vendor_knowledge`.
- **Architectural Rationale:** The Document-Level Assistant is designed exclusively for unstructured contractual clause verification and document summary generation using RAG. It has no SQL tool, preventing cross-document database queries.

### 8.7 Global Chatbot Access Summary
- **Accessible Tables:**
  - *Standard Business Tables (10):* `documents`, `invoices`, `invoice_line_items`, `vendors`, `vendor_aliases`, `payment_obligations`, `invoice_payments`, `extraction_results`, `classification_results`, `validation_results`.
  - *RAG & Chat Tables (3):* `document_chunks`, `chat_sessions`, `chat_messages`.
  - *Compliance Table (1):* `workflow_history` (Auditor & Admin only).
  - *User Management Table (1):* `users` (Admin only, password hash redacted).
- **Inaccessible Tables (6):** `audit_logs`, `ocr_results`, `document_user_activity`, `system_settings`, `training_examples`, `vendor_knowledge`.

### 8.8 SQL Authorization
- Implemented in [`TextToSQLService.validate_and_sanitize_sql()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py):
  1. Verifies that every table in the query appears in `ROLE_ALLOWED_TABLES[user.role]`.
  2. Verifies that every column appears in `ALLOWED_COLUMNS`.
  3. Rejects queries referencing `users.password_hash`.
  4. Injects mandatory SQL WHERE clauses into each AST SELECT node:
     - For `FINANCE_ANALYST`: `documents.uploaded_by = user.id AND documents.is_deleted = false`.
     - For other roles: `documents.is_deleted = false`.
  5. Enforces `LIMIT <= 100`.

### 8.9 RAG Authorization
- Implemented in [`ChunkRepository._apply_authorization_predicates()`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py):
  - Joins `document_chunks` with `documents`.
  - Enforces `Document.is_deleted == False`.
  - If `user.role == UserRole.FINANCE_ANALYST.value`, enforces `Document.uploaded_by == user.id`.
  - Guarantees that vector search never retrieves chunks from unauthorized documents into memory.

---

## 9. Database Architecture

### 9.1 Database Overview
EFDI utilizes PostgreSQL 16 with the `pgvector` extension enabled. The database schema contains 18 tables organized into functional domains:

```
[ users ] ──┬──► [ documents ] ──┬──► [ ocr_results ]
            │                    ├──► [ classification_results ]
            │                    ├──► [ extraction_results ] ──► [ invoices ] ──┬──► [ invoice_line_items ]
            │                    ├──► [ validation_results ]                     ├──► [ payment_obligations ]
            │                    ├──► [ workflow_history ]                       └──► [ invoice_payments ]
            │                    ├──► [ document_chunks ] (pgvector + FTS)
            │                    └──► [ document_user_activity ]
            │
            ├──► [ vendors ] ──► [ vendor_aliases ]
            │
            ├──► [ chat_sessions ] ──► [ chat_messages ]
            │
            └──► [ audit_logs ]
```

### 9.2 Core Tables
1. **`users`:** User accounts, roles, hashed passwords, and profile metadata.
   - *Key Columns:* `id`, `username`, `email`, `password_hash`, `role`, `is_active`.
   - *Relationships:* Parent to `documents`, `chat_sessions`, `workflow_history`, `audit_logs`.
2. **`documents`:** Master metadata for every ingested financial file.
   - *Key Columns:* `id`, `original_filename`, `stored_filename`, `mime_type`, `file_size_bytes`, `file_hash`, `document_type`, `status`, `validation_status`, `uploaded_by`, `is_deleted`.
   - *Relationships:* Foreign key to `users.id` (`uploaded_by`). Parent to processing result tables.

### 9.3 Processing Tables
3. **`ocr_results`:** Raw OCR detections and extracted full text.
   - *Key Columns:* `id`, `document_id`, `engine_name`, `page_count`, `full_text`, `average_confidence`, `raw_blocks` (JSONB).
   - *Characteristics:* Append-only; re-running OCR creates a new row.
4. **`classification_results`:** Document classification predictions and scoring signals.
   - *Key Columns:* `id`, `document_id`, `predicted_type`, `confidence`, `engine_name`, `signals` (JSONB), `scores_by_type` (JSONB).
5. **`extraction_results`:** Extracted financial fields, confidence scores, and provenance.
   - *Key Columns:* `id`, `document_id`, `document_type`, `engine_name`, `fields` (JSONB), `overall_confidence`, `fields_found_count`.
6. **`validation_results`:** Business rule validation reports.
   - *Key Columns:* `id`, `document_id`, `is_valid`, `error_count`, `warning_count`, `issues` (JSONB).

### 9.4 Financial Tables
7. **`invoices`:** Normalized financial header record.
   - *Key Columns:* `id`, `document_id`, `source_extraction_result_id`, `invoice_number`, `invoice_date`, `vendor_id`, `buyer_name`, `buyer_tax_id`, `currency`, `subtotal_amount`, `tax_amount`, `discount_amount`, `shipping_amount`, `grand_total_amount`, `po_number`.
8. **`vendors`:** Master vendor entities.
   - *Key Columns:* `id`, `canonical_name`, `vendor_code`, `tax_id`, `address`.
9. **`vendor_aliases`:** Alternative vendor names.
   - *Key Columns:* `id`, `vendor_id`, `alias`.
10. **`invoice_line_items`:** Itemized lines extracted from invoices.
    - *Key Columns:* `id`, `invoice_id`, `line_number`, `description`, `quantity`, `uom`, `unit_price`, `net_amount`, `tax_rate`, `tax_amount`, `gross_amount`.
11. **`payment_obligations`:** Payment terms, due dates, and settlement obligations.
    - *Key Columns:* `id`, `invoice_id`, `amount_due`, `amount_paid`, `amount_outstanding`, `currency`, `due_date`, `status`, `payment_terms`, `early_payment_deadline`, `early_payment_discount`.
12. **`invoice_payments`:** Recorded bank settlement payments.
    - *Key Columns:* `id`, `invoice_id`, `payment_date`, `amount`, `currency`, `payment_reference`, `payment_method`.

### 9.5 Workflow and Audit Tables
13. **`workflow_history`:** Approval state machine transition audit trail.
    - *Key Columns:* `id`, `document_id`, `action`, `from_status`, `to_status`, `comment`, `performed_by`.
14. **`audit_logs`:** Immutable system-wide audit event ledger.
    - *Key Columns:* `id`, `action`, `user_id`, `document_id`, `details` (JSONB), `created_at`.
15. **`document_user_activity`:** User document interaction logs.
    - *Key Columns:* `id`, `document_id`, `user_id`, `last_accessed_at`.

### 9.6 RAG Tables
16. **`document_chunks`:** Semantic document chunks and vector representations.
    - *Key Columns:* `id`, `document_id`, `page_number`, `chunk_type`, `section`, `content`, `embedding` (`vector(384)`), `tsv_content` (`tsvector`), `metadata_json` (JSONB).
    - *Indexes:* HNSW index on `embedding` using cosine distance; GIN index on `tsv_content`; B-tree index on `document_id`.
17. **`vendor_knowledge`:** Cached vendor payment term profiles.
    - *Key Columns:* `id`, `vendor_id`, `standard_payment_terms`, `bank_details_json`.

### 9.7 Chat Tables
18. **`chat_sessions`:** Conversational session metadata.
    - *Key Columns:* `id`, `user_id`, `session_type` (`"DOCUMENT"` or `"GLOBAL"`), `document_id`, `title`, `state_json` (JSONB).
19. **`chat_messages`:** Message turns, tool executions, and citations.
    - *Key Columns:* `id`, `session_id`, `role`, `content`, `tool_calls` (JSONB), `citations` (JSONB).

### 9.8 User/Auth Tables
- Covered under Section 9.2 (`users`). Auxiliary system tables include `system_settings` (key-value configuration) and `training_examples` (dataset storage).

### 9.9 Important Relationships
- `documents.id` $\leftrightarrow$ `ocr_results.document_id` (1-to-many, append-only).
- `documents.id` $\leftrightarrow$ `invoices.document_id` (1-to-1 projection).
- `invoices.id` $\leftrightarrow$ `invoice_line_items.invoice_id` (1-to-many, deterministic replacement on re-extract).
- `invoices.id` $\leftrightarrow$ `payment_obligations.invoice_id` (1-to-many).
- `vendors.id` $\leftrightarrow$ `invoices.vendor_id` (1-to-many).
- `documents.id` $\leftrightarrow$ `document_chunks.document_id` (1-to-many, cascade delete).
- `chat_sessions.id` $\leftrightarrow$ `chat_messages.session_id` (1-to-many, cascade delete).

---

## 10. APIs and System Interfaces

All endpoints are prefixed with `/api/v1` and return standard JSON error structures on failure (`{"error": str, "message": str, "details": dict}`).

| Domain | Method | Endpoint Path | Auth / Role | Description |
|---|---|---|---|---|
| **Auth** | `POST` | `/auth/login` | Public | Authenticate with username and password, returns JWT access and refresh tokens. |
| **Auth** | `POST` | `/auth/register` | Public | Register new user account with default `FINANCE_ANALYST` role. |
| **Documents** | `POST` | `/documents/upload` | Any Authenticated | Upload single file (PDF/PNG/JPG up to 25 MB). Returns `DocumentUploadResponse`. |
| **Documents** | `POST` | `/documents/upload/bulk` | Any Authenticated | Upload multiple files in single multipart request. Returns per-file outcome. |
| **Documents** | `POST` | `/documents/intake/scan-folder`| `ADMIN` Only | Scan server-side `intake/` folder and ingest all files found inside. |
| **Documents** | `GET` | `/documents` | Scoped | List documents with pagination and status filters. Analysts see own uploads only. |
| **Documents** | `GET` | `/documents/{id}` | Scoped | Fetch document metadata. Scoped to owner for Analysts. |
| **Documents** | `DELETE`| `/documents/{id}` | Admin/Manager/Owner | Soft-delete document (`is_deleted = true`). |
| **Documents** | `GET` | `/documents/{id}/download` | Scoped | Download original document bytes from disk storage. |
| **OCR** | `POST` | `/ocr/documents/{id}/run` | Scoped | Trigger OCR pipeline on document using specified or default engine. |
| **OCR** | `GET` | `/ocr/engines` | Any Authenticated | Report availability and status of supported engines (`docling`, `easyocr`). |
| **OCR** | `GET` | `/ocr/documents/{id}` | Scoped | Fetch latest OCR result, raw blocks, and on-the-fly table reconstruction. |
| **Classification**| `POST`| `/classification/documents/{id}/classify` | Scoped | Run document taxonomy classifier against latest OCR text. |
| **Classification**| `POST`| `/classification/documents/{id}/correct` | Scoped | Manually correct document type; updates both result and document entity. |
| **Extraction** | `POST` | `/extraction/documents/{id}/extract` | Scoped | Execute parallel hybrid extraction and relational sync. Advances to `EXTRACTED`. |
| **Extraction** | `PATCH`| `/extraction/documents/{id}/fields/{key}` | Scoped | Manually update single extracted field value with validation checks. |
| **Extraction** | `GET` | `/extraction/documents/{id}/export` | Scoped | Export extracted fields in JSON, CSV, or Excel format. |
| **Validation** | `POST` | `/validation/documents/{id}/validate` | Scoped | Run business validation engine. If error-free, advances status to `VALIDATED`. |
| **Workflow** | `POST` | `/workflow/documents/{id}/request-approval` | Scoped | Transition document from `VALIDATED` to `PENDING_APPROVAL`. |
| **Workflow** | `POST` | `/workflow/documents/{id}/approve` | Manager / Auditor / Admin | Transition document from `PENDING_APPROVAL` to `APPROVED`. |
| **Workflow** | `POST` | `/workflow/documents/{id}/reject` | Manager / Auditor / Admin | Transition document from `PENDING_APPROVAL` to `REJECTED` (Comment required). |
| **Document Chat**| `POST`| `/chat/documents/{id}/messages` | Scoped | Submit natural-language question scoped strictly to this document. |
| **Document Chat**| `GET` | `/chat/documents/{id}/history` | Scoped | Retrieve chronological chat message history for this document. |
| **Document Chat**| `DELETE`| `/chat/documents/{id}/history` | Scoped | Clear conversation history for this document. |
| **Global Chat** | `POST` | `/chat/corpus/messages` | Role Governed | Submit portfolio-wide natural language query to multi-tool ReAct agent. |
| **Global Chat** | `GET` | `/chat/corpus/history` | Any Authenticated | Retrieve conversation history for global assistant session. |
| **Global Chat** | `DELETE`| `/chat/corpus/history` | Any Authenticated | Clear global assistant conversation history. |
| **Audit** | `GET` | `/audit/logs` | `AUDITOR`, `ADMIN` | Query immutable audit log events with filtering by action, user, and date. |
| **Users** | `GET` | `/users` | `ADMIN` Only | List all registered users, roles, and active statuses. |
| **Users** | `PATCH`| `/users/{id}/role` | `ADMIN` Only | Update a user's role (`FINANCE_ANALYST`, `FINANCE_MANAGER`, `AUDITOR`, `ADMIN`). |

---

## 11. Operational / Handover Notes

### 11.1 Dependencies
- **Python Runtime:** Python 3.11 or 3.12.
- **Node.js Runtime:** Node.js 18+ or 20+ for the React frontend.
- **PostgreSQL Database:** PostgreSQL 16 with the `pgvector` extension installed and enabled (`CREATE EXTENSION IF NOT EXISTS vector;`).
- **Operating System Packages:**
  - Ubuntu/Debian: `libgl1-mesa-glx`, `libglib2.0-0` (required by OpenCV and PyMuPDF).
  - Windows: Visual C++ Redistributable 2015–2022.

### 11.2 Configuration
Configuration is managed via Pydantic Settings in [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py) reading from `.env`:
- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql://postgres:password@localhost:5432/EFDI`).
- `SECRET_KEY`: Minimum 32-character secret key for JWT signing. Refuses to boot with default placeholder in production.
- `OCR_DEFAULT_ENGINE`: Default engine name (`"docling"` recommended; `"easyocr"` CV fallback).
- `EXTRACTION_DEFAULT_ENGINE`: Default extraction engine (`"hybrid"` recommended).
- `LLM_PROVIDER`: Provider identifier (`"mistral"`).
- `EXTRACTION_LLM_MODEL`: Model name (`"mistral-small-2603"`).
- `MISTRAL_API_KEY`: API key for Mistral AI chat completions.
- `RAG_EMBEDDING_MODEL`: HuggingFace embedding model (`"sentence-transformers/all-MiniLM-L6-v2"`).
- `RAG_RERANKER_MODEL`: Cross-Encoder reranker (`"cross-encoder/ms-marco-MiniLM-L-6-v2"`).
- `GLOBAL_CHAT_ANALYST_POLICY`: Policy for analysts accessing global chat (`"scoped"` or `"forbidden"`).
- `CHAT_REQUEST_TIMEOUT_SECONDS`: Global timeout for chat request lifecycle (default: `30.0`).
- `INTAKE_SCAN_DIR`: Dedicated directory for administrator folder scanning (default: `"intake"`).
- `UPLOAD_DIR`: Storage directory for uploaded documents (default: `"uploads"`).

### 11.3 External Services
- **Mistral AI API:** Used for LLM field extraction, Text-to-SQL generation, and ReAct agent reasoning. Requires an active API key with access to `mistral-small-2603`.
- **HuggingFace Hub:** Downloaded once on startup: embedding model weights (`all-MiniLM-L6-v2`, ~120MB) and cross-encoder weights (`ms-marco-MiniLM-L-6-v2`, ~80MB).

### 11.4 Startup / Runtime Requirements
- **Model Warming:** [`backend/app/main.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/main.py) warms the embedding and reranker models during the FastAPI lifespan startup hook to eliminate cold-start penalties on initial requests:
  ```python
  get_embedding_service()._get_model()
  get_reranker_service()._get_model()
  ```
- **Alembic Migrations:** Must be applied prior to starting the web service:
  ```bash
  alembic upgrade head
  ```

### 11.5 Known Limitations
1. **Unimplemented Field Schemas for DPR and LCA:** Document types `DPR` (Down Payment Request) and `LCA` (Letter of Credit) classify successfully, but field extraction schemas remain documented no-ops pending client specification.
2. **EasyOCR Multi-Page Table Blindspot:** The legacy EasyOCR pipeline reconstructs tables exclusively from `raw_blocks[0]`. Line items on page 2+ are omitted when EasyOCR is used. The modern Docling track resolves this by extracting tables across all pages.
3. **No Automatic FX Currency Conversion:** The platform intentionally avoids automated foreign exchange conversions. Cross-currency monetary queries are grouped by currency.
4. **Derived OCR Structures Not Persisted in Dedicated Columns:** Table line items, normalized values, and quality score breakdowns are recomputed dynamically from `raw_blocks` or `full_text` when returning API responses.

### 11.6 Legacy Components Still Present
- `backend/app/ocr/easyocr_engine.py`: Retained as secondary production engine and CV fallback.
- `backend/app/ocr/paddle_engine.py`: Excluded from selectable engines due to native C++ crashes on ARM64/CPU environments.
- `backend/app/ocr/stub_engine.py`: Retained for unit testing without live neural weights.
- `backend/app/extraction/rule_based.py`: Retained as parallel branch in `HybridExtractor` and offline fallback.

### 11.7 Important Notes for Future Developers
- **Immutable Provenance:** Never delete or mutate `extraction_results` records when synchronizing to relational tables; `InvoicePersistenceService` updates `invoices` while maintaining foreign key reference to `source_extraction_result_id`.
- **Chat Tool Additions:** When adding tools to `GlobalReActAgent`, ensure that tools do not expose sensitive administrative actions and validate that table references are added to `ROLE_ALLOWED_TABLES`.
- **SQL Security Integrity:** Never bypass `sqlglot` AST validation in `TextToSQLService`. Any dynamic SQL execution must pass through AST parsing and predicate injection.

---

## 12. Architecture Diagram Inventory

The repository contains several architectural diagrams located across existing documentation files. These diagrams represent both the historical and current state of the system and are indexed below for inclusion in the final project handover manual:

| Diagram Title | Location | Diagram Type | System State Represented | Scope / Contents |
|---|---|---|---|---|
| **End-to-End System Architecture** | [`Architecture/EFDI_SYSTEM_ARCHITECTURE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/EFDI_SYSTEM_ARCHITECTURE.md) (Line 13) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | Complete 5-tier architecture: Client SPA, API Gateway, Processing Pipeline, Conversational AI / RAG, and PostgreSQL Persistence. |
| **Comprehensive Entity Relationship Diagram** | [`Architecture/EFDI_SYSTEM_ARCHITECTURE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/EFDI_SYSTEM_ARCHITECTURE.md) (Line 160) | Mermaid ERD (`erDiagram`) | **Current Architecture** | Relationships across all 18 database tables including core documents, relational business projections, vector chunks, and chat history. |
| **Dual-Track OCR Pipeline Architecture** | [`Architecture/OCR_PIPELINE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/OCR_pipeline.md) (Line 32) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | Dual-track OCR execution: Docling TableFormer track vs EasyOCR CRAFT track, normalization, validation, and async RAG indexing hook. |
| **Parallel Extraction & Reconciliation Pipeline** | [`Architecture/EXTRACTION_PIPELINE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/EXTRACTION_PIPELINE.md) (Line 23) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | HybridExtractor parallel thread execution, LLM schema synthesis, ReconciliationEngine conflict resolution, and relational projection sync. |
| **High-Level Conversational AI Ecosystem** | [`Architecture/CHATBOT_ARCHITECTURE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/CHATBOT_ARCHITECTURE.md) (Line 21) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | Document Chat vs Global Chat architecture, Context Resolver, LangChain ReAct loops, specialized tools, and chat persistence. |
| **Document-Level Chatbot Dedicated Architecture** | [`Architecture/DOCUMENT_LEVEL_CHATBOT_ARCHITECTURE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/DOCUMENT_LEVEL_CHATBOT_ARCHITECTURE.md) (Line 25) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | DocumentReActAgent flow, document ownership scoping, single-document RAG, decimal calculator, and accessible table boundaries. |
| **Global Multi-Tool Chatbot Architecture** | [`Architecture/GLOBAL_CHATBOT_ARCHITECTURE.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/Architecture/GLOBAL_CHATBOT_ARCHITECTURE.md) (Line 24) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | GlobalReActAgent coordination, TextToSQL AST validation, tenant predicate injection, global RAG, and role-based table access. |
| **Repository Overview Architecture Diagram** | [`README.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/README.md) (Line 60) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | High-level system overview diagram covering client, API gateway, pipeline, and storage. |
| **Extraction Reconciliation Flowchart** | [`README.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/README.md) (Line 240) | Mermaid Flowchart (`flowchart TD`) | **Current Architecture** | Detailed visual flow of rule vs LLM comparison, table overrides, and conflict tagging. |
| **Approval Workflow State Machine** | [`README.md`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/README.md) (Line 368) | Mermaid State Diagram (`stateDiagram-v2`) | **Current Architecture** | Document lifecycle states: `VALIDATED`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`. |
| **Legacy EasyOCR Pipeline Diagram** | Git history (`86ab973`) / Early design notes | ASCII Block Diagram | **Old Architecture** | Original single-engine EasyOCR rasterization, Hough deskewing, and coordinate table reconstruction. |
