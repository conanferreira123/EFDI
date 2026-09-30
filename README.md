# Enterprise Financial Document Intelligence (EFDI)

> An enterprise-grade financial document automation, validation, and conversational intelligence platform for **Accounts Payable (AP)** and **Record-to-Report (R2R)** operations. EFDI transforms manual document processing into an intelligent, auditable workflow using layout-aware OCR (Docling), automated classification, hybrid LLM/rule extraction, deterministic reconciliation, business validation, approval governance, and dual-mode conversational AI (scoped Document Assistant and portfolio-wide Global ReAct Assistant).

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Document Processing Pipeline](#document-processing-pipeline)
  - [Document Ingestion](#document-ingestion)
  - [OCR Pipeline — Docling](#ocr-pipeline--docling)
  - [Document Classification](#document-classification)
  - [Intelligent Data Extraction & Reconciliation](#intelligent-data-extraction--reconciliation)
  - [Business Rule Validation](#business-rule-validation)
  - [Workflow Management & Approval Lifecycle](#workflow-management--approval-lifecycle)
- [RAG Architecture](#rag-architecture)
  - [Chunking & Indexing Pipeline](#chunking--indexing-pipeline)
  - [Hybrid Dense/Sparse Retrieval & Neural Reranking](#hybrid-densesparse-retrieval--neural-reranking)
- [Chatbot Architecture](#chatbot-architecture)
  - [Document-Level Chatbot](#document-level-chatbot)
  - [Global-Level Chatbot](#global-level-chatbot)
- [Security and Access Control](#security-and-access-control)
  - [Authentication & Role-Based Access Control (RBAC)](#authentication--role-based-access-control-rbac)
  - [AST-Level SQL Security & Tenant Isolation](#ast-level-sql-security--tenant-isolation)
  - [Response Guardrails & Prompt Protection](#response-guardrails--prompt-protection)
- [Database Architecture](#database-architecture)
- [API Architecture](#api-architecture)
- [End-to-End Workflow](#end-to-end-workflow)
- [Setup & Running the Application](#setup--running-the-application)
  - [Prerequisites](#prerequisites)
  - [Docker Compose Deployment](#docker-compose-deployment)
  - [Local Development Setup](#local-development-setup)
- [Architectural Findings & Implementation Notes](#architectural-findings--implementation-notes)

---

## Overview

Modern corporate finance teams manage high volumes of invoices, purchase orders, receipts, utility bills, and payment advices. These documents feature heterogeneous layouts, localized tax conventions (e.g., GST, VAT, sales tax), multi-page itemized tables, and complex contractual payment clauses. 

EFDI resolves operational bottlenecks by providing:
1. **Layout-Preserving Document Ingestion:** Native vector PDF stream extraction and neural table recognition powered by IBM's Docling and TableFormer.
2. **Hybrid Extraction with Deterministic Reconciliation:** Dual execution of rule-based regex and Mistral AI LLM extraction, reconciled field-by-field against table grounding and format validity without hallucinated defaults.
3. **Normalized Relational Business Schema:** Automatic projection of unstructured documents into queryable first-class relational entities (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`).
4. **Document-Level Conversational Copilot:** Scoped question-answering with structure-aware chunk retrieval and verifiable page-level citations.
5. **Portfolio-Wide Financial Intelligence Agent:** Multi-hop ReAct agent dynamically orchestrating AST-governed Text-to-SQL, corpus semantic search, and deterministic `Decimal` financial arithmetic.
6. **Defense-in-Depth Governance:** AST-based SQL query rewriting via `sqlglot` for tenant data isolation, strict table/column allowlists, output sanitization, and immutable audit logging.

---

## System Architecture

The following diagram illustrates the complete EFDI system architecture across the client SPA, API gateway, application tier, AI/ML inference layer, and data persistence tier.

```mermaid
flowchart TD
    subgraph Client["Client Tier (Frontend SPA)"]
        User(["Finance User / Auditor / Admin"])
        ReactApp["React 19 + TypeScript SPA (Vite)"]
        Pages["Pages: Documents, Detail, Upload, Global Chat, Audit, Users"]
        APIClients["Typed API Clients (Axios)"]
        User --> ReactApp
        ReactApp --> Pages
        Pages --> APIClients
    end

    subgraph Gateway["Network & Reverse Proxy"]
        Nginx["Nginx Reverse Proxy (:80)"]
        APIClients -->|HTTP / JSON| Nginx
    end

    subgraph BackendApp["Application Tier (FastAPI Backend)"]
        FastAPI["FastAPI Application (:8000)"]
        Nginx -->|Proxy Pass /api/v1| FastAPI
        
        subgraph Middleware["Middleware & Security"]
            CORS["CORS Middleware"]
            AuthMiddleware["JWT Bearer Authentication & RBAC"]
            ExceptionHandlers["Global Exception Handlers (EFDIException)"]
        end

        subgraph Routers["API Routers (/api/v1)"]
            R_Auth["auth / users"]
            R_Docs["documents (upload, intake)"]
            R_OCR["ocr"]
            R_Class["classification"]
            R_Extract["extraction"]
            R_Valid["validation"]
            R_Work["workflow"]
            R_Audit["audit"]
            R_Chat["chat (document-level)"]
            R_GChat["global_chat (corpus-level)"]
        end

        FastAPI --> Middleware
        Middleware --> Routers

        subgraph CoreServices["Domain Services & Pipelines"]
            S_Doc["DocumentService (SHA-256 deduplication)"]
            S_OCR["OCRService (Docling / EasyOCR / PaddleOCR)"]
            S_Class["ClassificationService (Rule & ML)"]
            S_Extract["ExtractionService (Hybrid Orchestrator)"]
            S_Invoice["InvoicePersistenceService (Relational Sync)"]
            S_Valid["ValidationService (Math & Rules)"]
            S_Work["WorkflowService (Approval Lifecycle)"]
            S_Audit["AuditService (Immutable Logging)"]
            S_RAGIngest["RAGIngestionService (Async Worker)"]
            S_Chat["ChatService (Document Assistant)"]
            S_Global["GlobalReActAgent (Portfolio Assistant)"]
        end

        Routers --> CoreServices
    end

    subgraph AIEngines["AI / ML Infrastructure Layer"]
        DoclingConverter["IBM Docling DocumentConverter (TableFormer)"]
        MistralAPI["Mistral AI API (mistral-small-2603)"]
        LocalEmbed["SentenceTransformers (all-MiniLM-L6-v2)"]
        LocalRerank["Cross-Encoder (ms-marco-MiniLM-L-6-v2)"]
        AST_SQL["sqlglot AST Engine (SQL Parsing & Tenant Injection)"]
        CalcEngine["FinancialCalculator (Decimal AST Arithmetic)"]
        
        S_OCR -.-> DoclingConverter
        S_Extract -.-> MistralAPI
        S_Global -.-> MistralAPI
        S_Global -.-> AST_SQL
        S_Global -.-> CalcEngine
        S_Chat -.-> CalcEngine
        S_RAGIngest -.-> LocalEmbed
        S_Chat -.-> LocalEmbed
        S_Chat -.-> LocalRerank
        S_Global -.-> LocalEmbed
        S_Global -.-> LocalRerank
    end

    subgraph DataTier["Data & Persistence Tier (PostgreSQL 16)"]
        DB[(PostgreSQL 16)]
        
        subgraph RelationalTables["Relational Business & System Tables"]
            T_Users["users, system_settings"]
            T_Docs["documents, audit_logs, workflow_history"]
            T_Results["ocr_results, classification_results, extraction_results, validation_results"]
            T_Business["invoices, vendors, vendor_aliases, invoice_line_items, payment_obligations, invoice_payments"]
            T_Chat["chat_sessions, chat_messages"]
        end

        subgraph VectorStore["Vector & Full-Text Store"]
            T_Chunks["document_chunks (pgvector 384-dim, tsvector FTS)"]
        end

        DB --- RelationalTables
        DB --- VectorStore
        CoreServices --> DB
    end

    subgraph Storage["File System Storage"]
        UploadDir[("uploads/ (UUID Stored Files)")]
        IntakeDir[("intake/ (Staging Intake Folder)")]
        ModelCache[("Model Cache Volume")]
        S_Doc --> UploadDir
        S_Doc --> IntakeDir
        LocalEmbed --> ModelCache
        LocalRerank --> ModelCache
    end
```

---

## Technology Stack

### Frontend
- **Framework & Core:** React 19, TypeScript 5, Vite
- **Styling & UI:** Tailwind CSS, Radix UI primitives, Lucide React icons
- **State & Routing:** React Router v6 (`createBrowserRouter`), Context API (`AuthContext`, `ThemeContext`, `ToastContext`)
- **HTTP Client:** Axios with centralized error handling and JWT bearer interceptor
- **Rendering:** `react-markdown` with `remark-gfm` for rendering tables and citations

### Backend
- **Framework:** FastAPI (Python 3.12)
- **ASGI & Production Servers:** Uvicorn, Gunicorn
- **Configuration & Validation:** Pydantic v2, `pydantic-settings`
- **Database ORM & Migrations:** SQLAlchemy 2.0, Alembic
- **Security & Hashing:** Passlib with Bcrypt, PyJWT (HS256)

### AI, Machine Learning & OCR
- **Document Conversion & OCR:** IBM Docling (`docling` DocumentConverter with TableFormer neural network architecture), with legacy fallback support for EasyOCR, PaddleOCR, and Stub engine
- **LLM Provider:** Mistral AI (`mistral-small-2603`) via Chat Completion endpoint with `json_schema` strict structured outputs
- **Agent Framework:** LangChain core message abstraction (`SystemMessage`, `HumanMessage`, `AIMessage`, `ToolMessage`) orchestrated in custom iterative ReAct loops
- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors)
- **Neural Reranking:** `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **SQL Security & AST Parsing:** `sqlglot` for syntax verification, dialect translation, and AST manipulation
- **Arithmetic Engine:** Python standard library `ast` with `decimal.Decimal` (`ROUND_HALF_UP`)

### Data & Persistence
- **Primary Database:** PostgreSQL 16
- **Vector Search Extension:** `pgvector` (`vector(384)` with cosine distance operator `<=>`)
- **Lexical Search:** PostgreSQL Native Full-Text Search (`tsvector`, `to_tsquery('english', ...)`)
- **File Storage:** Local secure disk storage (`uploads/` for permanent storage, `intake/` for folder scans)

### Infrastructure & Deployment
- **Containerization:** Docker, Docker Compose
- **Web Server:** Nginx (reverse proxy and static asset server)
- **Volume Management:** Named volumes for PostgreSQL data, file uploads, logs, and ML model weights cache

---

## Repository Structure

```text
EFDI/
├── backend/
│   ├── alembic/                         # Database schema migrations
│   │   ├── versions/                    # Versioned migration scripts
│   │   └── env.py                       # Alembic environment runner
│   ├── app/
│   │   ├── audit/                       # Audit logging utilities
│   │   ├── classification/              # Rule-based and ML document classifiers
│   │   ├── core/                        # Centralized settings, exceptions, logging, security
│   │   ├── database/                    # SQLAlchemy engine, session management, base model
│   │   ├── extraction/                  # Parallel orchestrator, LLM & rule extractors, reconciliation
│   │   ├── models/                      # SQLAlchemy ORM database models (documents, invoices, chunks, chat)
│   │   ├── ocr/                         # Docling engine, TableFormer, preprocessing, quality scoring
│   │   ├── rag/                         # Embeddings, chunking, reranker, ReAct agents, tools, guardrails
│   │   │   ├── tools/                   # DatabaseQueryTool, DocumentRAGTool, FinancialCalculatorTool
│   │   │   ├── chunking.py              # StructureAwareChunker & DoclingNativeChunker
│   │   │   ├── document_agent.py        # Scoped Document ReAct Agent
│   │   │   ├── global_agent.py          # Portfolio-wide Global ReAct Agent
│   │   │   └── response_guardrails.py   # Output sanitization and prompt protection
│   │   ├── repositories/                # Database repository abstraction layer
│   │   ├── routers/                     # FastAPI endpoint definitions (/api/v1/*)
│   │   ├── schemas/                     # Pydantic request/response schemas
│   │   ├── services/                    # Business service layer (OCR, Extraction, RAG, Chat, Text-to-SQL)
│   │   └── utils/                       # File storage, clock, temporal prompt helpers
│   ├── tests/                           # 460 automated test cases across 38 suites
│   ├── Dockerfile                       # Backend container definition
│   ├── requirements.txt                 # Core backend dependencies
│   └── requirements-ocr.txt             # Optional heavy OCR/ML dependencies
├── frontend/
│   ├── src/
│   │   ├── components/                  # UI components (DocumentChat, StatusBadge, Tables, Modals)
│   │   ├── context/                     # AuthContext, ThemeContext
│   │   ├── hooks/                       # Custom React hooks (useDocumentPipeline, useApiErrorToast)
│   │   ├── layouts/                     # AppShell navigation layout
│   │   ├── lib/                         # Formatting utilities, Axios API client
│   │   ├── pages/                       # DocumentsList, DocumentDetail, Upload, GlobalChat, Audit, Users
│   │   ├── services/                    # Frontend API integration services
│   │   └── types/                       # TypeScript domain interfaces and enums
│   ├── Dockerfile                       # Multi-stage frontend container build
│   └── package.json                     # Frontend dependencies and build scripts
├── docs/                                # Technical specifications, evidence inventories, report updates
├── docker-compose.yml                   # Multi-container orchestration definition
├── .env.example                         # Environment template documentation
└── README.md                            # Authoritative repository documentation
```

---

## Document Processing Pipeline

The EFDI document processing pipeline advances documents through a deterministic state machine:
`UPLOADED` $\to$ `OCR_COMPLETED` $\to$ `EXTRACTED` $\to$ `VALIDATED` $\to$ `PENDING_APPROVAL` $\to$ `APPROVED` (or `REJECTED`).

```text
[Document Upload] ──> [Docling OCR] ──> [Classification] ──> [Hybrid Extraction & Reconciliation] ──> [Business Validation] ──> [Approval Workflow]
                             │                                             │
                             ▼                                             ▼
                 [Async RAG Ingestion]                       [Relational Invoices Projection]
```

### Document Ingestion
1. **Intake Channels:** Single or batch upload via multipart form (`POST /api/v1/documents/upload`) or folder-based staging scan (`POST /api/v1/documents/bulk-intake`).
2. **Integrity & Storage:** Generates a SHA-256 cryptographic checksum to detect duplicate uploads. Stores the file with a UUID-based filename in `uploads/` to prevent directory traversal and filename collisions.
3. **Tracking Record:** Initializes a row in `documents` with status `UPLOADED`, capturing MIME type, file size, original filename, and uploading user ID.

---

### OCR Pipeline — Docling

EFDI utilizes **IBM Docling** as its primary OCR and document reconstruction engine (`app/ocr/docling_engine.py`). For vector PDFs and images, Docling processes files directly from disk, bypassing lossy rasterization and ad-hoc OpenCV preprocessing.

```mermaid
flowchart TD
    StartUpload(["Uploaded File on Disk (uploads/{stored_filename})"]) --> TriggerOCR["POST /api/v1/ocr/documents/{id}/run"]
    TriggerOCR --> SvcInit["OCRService.run_ocr(document, engine_name='docling')"]
    
    subgraph AuditStart["Pre-Execution Audit"]
        Audit1["AuditService.log(action=OCR_STARTED, details={engine: 'docling'})"]
    end
    SvcInit --> AuditStart
    
    subgraph EngineSelection["Engine Routing"]
        CheckEngine{"engine_name in ('docling', 'paddleocr-vl-1.6')?"}
        SvcInit --> CheckEngine
        CheckEngine -->|Yes: Direct File Path| DoclingBranch["engine.extract_from_file(file_path)"]
        CheckEngine -->|No: Legacy / Fallback| LegacyBranch["Rasterize PDF -> OpenCV CLAHE/Deskew -> EasyOCR"]
    end

    subgraph DoclingInternal["Docling DocumentConverter Pipeline"]
        DoclingBranch --> InitConverter["_get_converter(): DocumentConverter(PdfFormatOption)"]
        InitConverter --> PipelineOpts["PdfPipelineOptions: do_ocr=True, do_table_structure=True, do_cell_matching=True"]
        PipelineOpts --> NativeConvert["converter.convert(file_path)"]
        
        subgraph DoclingCore["Internal Docling Processing"]
            NativeConvert --> PDFParse["Native Vector PDF Stream Parsing & OCR Reader"]
            PDFParse --> LayoutEngine["Layout Analysis (Headings, Paragraphs, Margins)"]
            LayoutEngine --> TableFormer["TableFormer Neural Table Structure Recognition"]
            TableFormer --> CellMatch["Grid & Cell Matching (Row/Col Spans)"]
        end

        CellMatch --> ExportMD["doc.export_to_markdown(traverse_pictures=True)"]
        CellMatch --> ExtractProv["doc.iterate_items() -> Visual Provenance & Bounding Boxes"]
    end

    subgraph MultiPageAgg["Multi-Page Aggregation"]
        ExportMD --> PageSplit["Page Delimited Markdown (=== PAGE X ===)"]
        ExtractProv --> BoxAdapt["Adapt Bounding Boxes into EFDI OCRTextBlock & raw_blocks"]
    end

    subgraph InMemValidation["In-Memory Post-OCR Quality & Validation"]
        PageSplit --> ParseTable["parse_markdown_table(full_text) -> Structured Line Items"]
        ParseTable --> NormTable["normalize_table_data(table_dict)"]
        NormTable --> ValidateOCR["validate_ocr_output(normalized_items, raw_full_text)"]
        ValidateOCR --> QualScore["calculate_quality_score() -> Overall Quality Score & Grade (A-D)"]
    end

    subgraph Persistence["Persistence & Status Transition"]
        QualScore --> SaveResult["OCRResultRepository.create()"]
        BoxAdapt --> SaveResult
        SaveResult --> UpdateStatus["DocumentRepository.update_status(document, 'OCR_COMPLETED')"]
    end

    subgraph AsyncHook["Asynchronous Non-Blocking RAG Ingestion"]
        UpdateStatus --> TriggerRAG["get_rag_ingestion_service().ingest_document_async(document.id, docling_doc)"]
        TriggerRAG -.->|Daemon Thread| RAGWorker["RAGIngestionService.ingest_document() -> DoclingNativeChunker"]
    end

    subgraph AuditDone["Post-Execution Audit"]
        UpdateStatus --> Audit2["AuditService.log(action=OCR_COMPLETED, details={status, quality_score, quality_grade, table_items_count})"]
    end
```

**Docling Key Capabilities:**
- **TableFormer Recognition:** Recovers complex multi-line, borderless, and merged financial tables as clean pipe-delimited Markdown tables.
- **Visual Provenance:** Maps text bounding boxes to page geometry to preserve exact visual coordinates for audit inspection.
- **Quality Scoring:** Evaluates OCR output confidence, structural completeness, and numeric sanity, assigning quality scores (0–100) and grades (A to D).
- **Asynchronous Ingestion Trigger:** Upon reaching `OCR_COMPLETED`, asynchronously hands the native `DoclingDocument` object to `RAGIngestionService` to index chunks into pgvector without blocking HTTP response latency.

---

### Document Classification
- **Endpoint:** `POST /api/v1/classification/documents/{id}/classify`
- **Engines:** `RuleBasedClassifier` (default keyword and structural signal evaluator) and `MLClassifier` (scikit-learn architecture ready for offline training).
- **Taxonomy:** Supports standard financial document types: Non-PO Invoice (`NPO`), PO-based Invoice (`POI`), Itemized Medical/Expense Claim (`IMA`), Receipt (`REC`), Bank Statement (`BST`), Credit Note (`CRN`), Debit Note (`DBN`), Purchase Order (`PO`), and Payment Advice (`ADV`).
- **Human Correction:** Enables users to override misclassified types via `POST /api/v1/classification/documents/{id}/correct`. Updating the type immediately retargets downstream extraction to use the corrected schema.

---

### Intelligent Data Extraction & Reconciliation

EFDI employs a **Hybrid Extraction and Deterministic Reconciliation Engine** (`app/extraction/parallel_orchestrator.py` and `app/extraction/reconciliation.py`).

```mermaid
flowchart TD
    TriggerExtract(["POST /api/v1/extraction/documents/{id}/extract"]) --> CheckPreReq["Check Prerequisites: OCRResult & ClassificationResult exist"]
    
    subgraph ContextAssembly["ExtractionContext Construction"]
        CheckPreReq --> BuildCtx["Build in-memory ExtractionContext"]
        BuildCtx --> CollectData["Collect: full_text, document_type, raw_blocks, table_data (Markdown tables), normalized_data, ocr_validation, ocr_quality"]
    end

    subgraph FactoryDispatch["Engine Dispatcher"]
        CollectData --> GetEngine{"get_extraction_engine(engine_name='hybrid')"}
        GetEngine -->|'hybrid'| HybridEngine["HybridExtractor"]
        GetEngine -->|'llm_based'| LLMEngine["LLMBasedExtractor"]
        GetEngine -->|'rule_based'| RuleEngine["RuleBasedExtractor"]
    end

    subgraph ParallelOrchestrator["Parallel Extraction Orchestrator (ThreadPoolExecutor)"]
        HybridEngine --> ThreadPool["ParallelExtractionOrchestrator.run_parallel(context)"]
        
        subgraph WorkerRule["Thread 1: Rule-Based Extractor"]
            ThreadPool --> ExecRule["RuleBasedExtractor.extract(context)"]
            ExecRule --> RegexMatch["Deterministic Regex Patterns"]
            RegexMatch --> SpatialAnchors["Spatial Layout Anchors & Proximity Clustering"]
            SpatialAnchors --> RuleOutput["ExtractionResultData (Rule Candidate Fields)"]
        end

        subgraph WorkerLLM["Thread 2: LLM-Based Extractor"]
            ThreadPool --> ExecLLM["LLMBasedExtractor.extract(context)"]
            ExecLLM --> BuildPrompt["llm_context_builder.build_llm_prompt(context)"]
            BuildPrompt --> BuildSchema["Build Dynamic Pydantic JSON Schema (NPOExtractionPayload)"]
            BuildSchema --> CallMistral["Mistral AI API (/chat/completions, model=mistral-small-2603, temperature=0.0)"]
            CallMistral --> ParseJSON["Parse Structured Output JSON"]
            ParseJSON --> PrimitivesNorm["Deterministic Date (YYYY-MM-DD) & Amount (Decimal) Normalizers"]
            PrimitivesNorm --> LLMOutput["ExtractionResultData (LLM Candidate Fields)"]
        end
    end

    WorkerRule --> DualRes["DualExtractionResult(rule_result, llm_result)"]
    WorkerLLM --> DualRes

    subgraph Reconciliation["Deterministic Reconciliation Engine"]
        DualRes --> ReconcileEngine["ReconciliationEngine.reconcile(dual_result, context)"]
        
        subgraph FieldLoop["Field-by-Field Domain Reconciliation"]
            ReconcileEngine --> CheckEquiv{"are_values_equivalent(rule_val, llm_val)?"}
            CheckEquiv -->|Equivalent: String / Date / Amount| BoostConf["AGREEMENT: Boost confidence (0.95 - 1.0), provenance='both_agree'"]
            CheckEquiv -->|Discrepancy: Values Differ| ResolveDiscrepancy{"Domain Discrepancy Rules"}
            
            ResolveDiscrepancy -->|Table Grounded| PickTable["Candidate matches table line items -> Select table-grounded value"]
            ResolveDiscrepancy -->|Valid Date Format| PickDate["Candidate matches strict ISO calendar date -> Select valid date"]
            ResolveDiscrepancy -->|Confidence Differential| PickHighConf["High confidence gap -> Select higher scoring candidate"]
            ResolveDiscrepancy -->|Unresolvable| KeepConflict["Tag UNRESOLVED_CONFLICT: Retain both values in audit payload without silent overwrite"]
        end
    end

    subgraph PersistenceLayer["Multi-Layer Persistence"]
        BoostConf --> ReconciledData["Consolidated ExtractionResultData"]
        PickTable --> ReconciledData
        PickDate --> ReconciledData
        PickHighConf --> ReconciledData
        KeepConflict --> ReconciledData

        ReconciledData --> InjectMeta["Inject System Metadata: document_id, company_code, validation_status"]
        InjectMeta --> SaveRaw["ExtractionResultRepository.create() -> Save to extraction_results (JSONB fields)"]
        SaveRaw --> AdvanceStatus["DocumentRepository.update_status(document, 'EXTRACTED')"]
        
        subgraph RelationalSync["InvoicePersistenceService.sync_from_extraction()"]
            AdvanceStatus --> SyncRelational["Synchronize into First-Class Relational Business Tables"]
            SyncRelational --> SyncVendor["Resolve or Insert into 'vendors' & 'vendor_aliases'"]
            SyncRelational --> SyncInvoice["Create or Update 'invoices' (source_extraction_result_id)"]
            SyncRelational --> SyncItems["Replace 'invoice_line_items' (line_number, qty, unit_price, amount)"]
            SyncRelational --> SyncObligation["Create or Update 'payment_obligations' (due_date, amount, status)"]
        end
    end
```

**Reconciliation Engine Rules:**
1. **Equivalence Detection:** Normalizes numbers (`$1,250.00` $\to$ `1250.00`) and dates (`12/04/2026` $\to$ `2026-04-12`) before comparison.
2. **Agreement Boost:** If both engines agree, confidence is boosted to 0.95–1.0 with provenance `both_agree`.
3. **Table Grounding:** If total amounts conflict, candidate values are validated against the sum of parsed table line items.
4. **No Hallucinated Defaults:** Missing values remain explicitly `None` rather than falling back to fictitious placeholders.
5. **Relational Synchronization:** Raw extractions are mirrored into queryable relational entities (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`) via `InvoicePersistenceService`.

---

### Business Rule Validation
- **Endpoint:** `POST /api/v1/validation/documents/{id}/validate`
- **Validation Rules:**
  - **Mandatory Fields:** Ensures mandatory fields exist for the document taxonomy.
  - **Mathematical Integrity:** Reconciles line item subtotal, tax amount, and discount against grand total:
    $$\text{Subtotal} + \text{Tax} - \text{Discount} = \text{Grand Total} \quad (\pm 0.05 \text{ rounding tolerance})$$
  - **Line Items Arithmetic:** Verifies that $\text{Quantity} \times \text{Unit Price} = \text{Amount}$ per line item.
  - **Duplicate Invoice Detection:** Checks whether the same vendor and invoice number already exist in the database.
- **Outcome:** Validated documents transition to `VALIDATED`. Discrepancies are flagged as structured validation issues without blocking manual review.

---

### Workflow Management & Approval Lifecycle
- **Endpoint:** `POST /api/v1/workflow/documents/{id}/transition`
- **State Machine:**
  - `SUBMIT`: Advances a `VALIDATED` document to `PENDING_APPROVAL`.
  - `APPROVE`: Authorized Finance Managers or Admins transition the document to `APPROVED`.
  - `REJECT`: Rejects the document with required audit reasoning to `REJECTED`.
- **Audit Trail:** Every status change is captured in `workflow_history` and `audit_logs` with timestamps and user IDs.

---

## RAG Architecture

EFDI implements a dual-mode Retrieval-Augmented Generation subsystem backed by PostgreSQL 16, `pgvector`, and local neural rerankers.

### Chunking & Indexing Pipeline
- **Chunkers:** 
  - `DoclingNativeChunker`: Leverages Docling's structural document tree, producing discrete chunks for document headers, itemized table blocks, narrative summaries, and contractual payment clauses.
  - `StructureAwareChunker`: Legacy spatial bounding-box chunker for raw text blocks.
- **Dense Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` produces 384-dimensional dense vectors stored in `document_chunks.embedding`.
- **Lexical Indexing:** Generated PostgreSQL `tsvector` column (`tsv_content`) indexed via GIN for native BM25-style full-text search.
- **Idempotency:** When OCR re-runs, existing chunks for the document ID are deleted and re-indexed.

### Hybrid Dense/Sparse Retrieval & Neural Reranking
When a user submits a query to either conversational assistant, EFDI executes a **5-stage hybrid retrieval pipeline**:

```text
User Query
   │
   ├──> [Dense Retrieval]  : pgvector Cosine Distance (<=>) ───────────> Top-30 Chunks
   │
   └──> [Sparse Retrieval] : PostgreSQL FTS (to_tsvector @@ to_tsquery) ──> Top-30 Chunks
                                  │
                                  ▼
                   [Reciprocal Rank Fusion (RRF, k=60)]
                                  │
                                  ▼
                        Top-25 Fused Candidates
                                  │
                                  ▼
             [Cross-Encoder Reranker (ms-marco-MiniLM-L-6-v2)]
                                  │
                                  ▼
                      Top-5 Grounded Chunks with Page Provenance
```

---

## Chatbot Architecture

EFDI provides two distinct conversational copilots, cleanly separated by scope and security boundaries:
1. **Document-Level Chatbot:** Scoped strictly to a single document without database/SQL tool exposure.
2. **Global-Level Chatbot:** Operates portfolio-wide with Text-to-SQL, multi-document semantic search, and exact financial arithmetic.

---

### Document-Level Chatbot

Mounted directly inside the Document Detail view under the **"Ask AI"** tab (`POST /api/v1/chat/documents/{documentId}/messages`).

```mermaid
flowchart TD
    UserQuery(["User Question in 'Ask AI' Tab (Document Detail Page)"]) --> PostMsg["POST /api/v1/chat/documents/{documentId}/messages"]
    
    subgraph AuthAndSession["Authorization & Session Setup"]
        PostMsg --> AuthCheck["DocumentService.get_for_user(document_id, user) -> Validate Access"]
        AuthCheck --> GetSession["ChatHistoryRepository.get_or_create_document_session(user_id, document_id)"]
        GetSession --> LoadHistory["Fetch Bounded Sliding Window History (limit=10)"]
        LoadHistory --> LoadState["Fetch Session State (active_document_id, pending_offer)"]
        LoadState --> SaveUserMsg["Persist Incoming User Message (role='user')"]
    end

    subgraph ContextResolution["Conversational Context Resolution"]
        SaveUserMsg --> Resolver["ConversationContextResolver.resolve(query, history, session_state)"]
        Resolver --> CheckAction{"Resolution Action"}
        CheckAction -->|Negative Confirmation| AckNeg["Return polite acknowledgement & update pending_offer=None"]
        CheckAction -->|Ambiguous Reference| AskClarify["Return clarification request without executing tools"]
        CheckAction -->|Normal Question / Summary| ResolveQuery["Produce Contextualized Query (effective_query)"]
    end

    subgraph OCRGuard["OCR Readiness Precondition Check"]
        ResolveQuery --> CheckOCR{"Is document OCR completed?"}
        CheckOCR -->|No & Content Query| ReturnOCRError["Return: 'OCR has not been run for this document yet. Please run OCR first.'"]
        CheckOCR -->|Yes or Pure Standalone Math| AgentHandoff["Invoke DocumentReActAgent.run()"]
    end

    subgraph AgentLoop["DocumentReActAgent (LangChain Scoped ReAct Loop)"]
        AgentHandoff --> InitAgent["Initialize Agent with DOCUMENT_REACT_SYSTEM_PROMPT"]
        InitAgent --> PromptDirectives["Prompt: Scoped to single document_id | NO Database/SQL tool | 5-Section AP Summary only on explicit intent"]
        PromptDirectives --> LLMReason["Agent LLM Reasoning (Mistral AI)"]
        
        subgraph ToolSelection["Available Scoped Domain Tools"]
            LLMReason --> ChooseTool{"Agent Tool Selection"}
            
            subgraph ToolRAG["DocumentRAGTool"]
                ChooseTool -->|document_rag_tool| ExecRAG["RAGService.retrieve_for_document(document_id, query)"]
                ExecRAG --> DenseSearch["Dense Vector Search: EmbeddingService (MiniLM-L6-v2) -> pgvector cosine distance on document_chunks (top 30)"]
                ExecRAG --> SparseSearch["Sparse Lexical Search: PostgreSQL FTS (to_tsvector @@ to_tsquery) on document_chunks (top 30)"]
                DenseSearch --> RRF["Reciprocal Rank Fusion (k=60) -> Top 25 Candidates"]
                SparseSearch --> RRF
                RRF --> Reranker["Neural Reranker: Cross-Encoder (ms-marco-MiniLM-L-6-v2) -> Top 5 Scored Chunks"]
                Reranker --> RAGObs["Tool Observation: Grounded text snippets with [Page X, Section Y] provenance"]
            end

            subgraph ToolCalc["FinancialCalculatorTool"]
                ChooseTool -->|financial_calculator_tool| ExecCalc["FinancialCalculator"]
                ExecCalc --> ASTMath["Safe AST Expression Evaluation: Decimal precision arithmetic (ROUND_HALF_UP)"]
                ExecCalc --> ASTDiscount["Discount Window Calculator: Gross * (Pct/100) & Net Payable"]
                ExecCalc --> ASTDate["Calendar Deadline Calculator: base_date + timedelta(days)"]
                ASTMath --> CalcObs["Tool Observation: Exact formatted currency & date calculation strings"]
                ASTDiscount --> CalcObs
                ASTDate --> CalcObs
            end
        end

        RAGObs --> LLMReason
        CalcObs --> LLMReason
        LLMReason --> LoopControl{"Sufficient Information Gathered or Max Iterations?"}
        LoopControl -->|No| LLMReason
        LoopControl -->|Yes| SynthesizeFinal["Synthesize Final Answer with Verifiable Page Citations"]
    end

    subgraph GuardrailsAndOutput["Safety Guardrails & Output Processing"]
        SynthesizeFinal --> ApplyGuardrails["response_guardrails: Sanitize Internal State, Tokens, and System Prompts"]
        ApplyGuardrails --> ExtractCitations["Extract Page Provenance Citations from Chunks"]
        ExtractCitations --> UpdateSessionState["Update Session State: extract_pending_offer, append verified_facts"]
        UpdateSessionState --> PersistAssistantMsg["ChatHistoryRepository.add_message(role='assistant', content, tool_calls, citations)"]
        PersistAssistantMsg --> ReturnResponse(["Return JSON Response to Client"])
    end
```

**Key Features:**
- **Strict Isolation:** The agent is completely unaware of and has no access to `DatabaseQueryTool`.
- **OCR Precondition Check:** Inquiries about document content are rejected if OCR has not run yet. Pure standalone math expressions (e.g., `Calculate 150000 * 0.98`) are allowed without OCR.
- **Accounts Payable (AP) Summary Directive:** Produces an operational 5-section invoice summary (`Invoice Overview`, `Payment Details`, `Amount Breakdown`, `Items / Services`, `AP Attention`) **only** when explicitly requested (e.g. *"Summarize this invoice"*). For normal specific inquiries (e.g. *"What is the invoice date?"*), the agent answers directly without prepending the summary structure.

---

### Global-Level Chatbot

Available at the top navigation route `/chat` (`POST /api/v1/chat/corpus/messages`), enabling finance managers, analysts, and auditors to query the enterprise portfolio.

```mermaid
flowchart TD
    UserQuery(["User Question in Global Chat (/chat)"]) --> PostCorpus["POST /api/v1/chat/corpus/messages"]
    
    subgraph GlobalAuthSession["Authentication & Global Session Setup"]
        PostCorpus --> JWTAuth["get_current_user: Validate JWT Bearer & Resolve User Role"]
        JWTAuth --> GetGlobalSession["ChatHistoryRepository.get_or_create_global_session(user_id)"]
        GetGlobalSession --> FetchGlobalHistory["Fetch Bounded Sliding Window History (limit=10)"]
        FetchGlobalHistory --> FetchGlobalState["Fetch Global Session State (pending_offer, verified_facts)"]
        FetchGlobalState --> SaveGlobalUserMsg["Persist Incoming User Message (role='user')"]
    end

    subgraph GlobalContextResolution["Conversational Context Resolution"]
        SaveGlobalUserMsg --> GlobalResolver["ConversationContextResolver.resolve(query, history, session_state)"]
        GlobalResolver --> GlobalActionCheck{"Action Type"}
        GlobalActionCheck -->|Negative Confirmation| GlobalAckNeg["Return polite acknowledgement & reset pending_offer"]
        GlobalActionCheck -->|Ambiguous Reference| GlobalClarify["Return clarification request without executing tools"]
        GlobalActionCheck -->|Proceed| GlobalEffectiveQuery["Contextualized Global Query (effective_query)"]
    end

    subgraph GlobalAgentLoop["GlobalReActAgent (LangChain Portfolio ReAct Loop, Max Iterations=5)"]
        GlobalEffectiveQuery --> InitGlobalAgent["Initialize GlobalReActAgent with GLOBAL_REACT_SYSTEM_PROMPT"]
        InitGlobalAgent --> GlobalGuidelines["Guidelines: Cross-document reasoning | Multi-currency safety (never sum cross-currency) | Bounded loop"]
        GlobalGuidelines --> AgentThought["Agent LLM Reasoning (Mistral AI)"]
        
        subgraph GlobalTools["Specialized Enterprise Domain Tools"]
            AgentThought --> DeduplicateCall{"_is_duplicate_call(tool_name, tool_args)?"}
            DeduplicateCall -->|Duplicate Call Detected| LoopBreak["Abort redundant execution -> Synthesize answer from available evidence"]
            DeduplicateCall -->|New Call| SelectGlobalTool{"Select Tool"}

            subgraph ToolDB["1. DatabaseQueryTool (Text-to-SQL)"]
                SelectGlobalTool -->|database_query_tool| TextToSQL["TextToSQLService.execute_query()"]
                TextToSQL --> GenerateSQL["Mistral AI proposes SQL query over relational schema"]
                GenerateSQL --> ASTParser["sqlglot AST Parser & Semantic Validation"]
                
                subgraph SecurityPerimeter["AST Security & Authorization Perimeter"]
                    ASTParser --> SelectOnlyCheck{"Is query SELECT-only? (No DDL/DML/INSERT/UPDATE)"}
                    SelectOnlyCheck -->|Violation| RefuseSQL["Raise AuthorizationException / Reject unsafe query"]
                    SelectOnlyCheck -->|Pass| TableCheck{"Are tables in ROLE_ALLOWED_TABLES?"}
                    TableCheck -->|Violation| RefuseSQL
                    TableCheck -->|Pass: Analyst / Manager / Auditor / Admin| ColumnCheck{"Are columns in ALLOWED_COLUMNS?"}
                    ColumnCheck -->|password_hash detected| RefuseSQL
                    ColumnCheck -->|Pass| InjectTenant{"User Role == FINANCE_ANALYST?"}
                    InjectTenant -->|Yes| ASTInject["AST Rewriter: Programmatically inject 'uploaded_by = user.id' predicate"]
                    InjectTenant -->|No: Manager/Auditor/Admin| InjectLimit["Inject 'LIMIT 100' ceiling"]
                    ASTInject --> InjectLimit
                end

                InjectLimit --> ExecReadOnly["Execute in Read-Only DB Transaction with 5-Second Statement Timeout"]
                ExecReadOnly --> DBResults["Tool Observation: Structured records (counts, spend, vendors, invoices)"]
            end

            subgraph ToolGlobalRAG["2. DocumentRAGTool (Portfolio Semantic Search)"]
                SelectGlobalTool -->|document_rag_tool| ExecGlobalRAG["RAGService.retrieve_global()"]
                ExecGlobalRAG --> ScopeFilter["Pre-retrieval SQL Scope Check: Restrict to authorized document IDs"]
                ScopeFilter --> MetaFilter["Apply Metadata Pre-Filters: vendor_id, document_type, section"]
                MetaFilter --> HybridSearch["Hybrid Search: pgvector dense (MiniLM-L6-v2) + PostgreSQL FTS -> RRF (k=60)"]
                HybridSearch --> GlobalRerank["Neural Reranker: Cross-Encoder (ms-marco-MiniLM-L-6-v2) -> Top Scored Chunks"]
                GlobalRerank --> GlobalRAGObs["Tool Observation: Contractual clauses, Incoterms, penalty terms, OCR text"]
            end

            subgraph ToolGlobalCalc["3. FinancialCalculatorTool (Deterministic Math)"]
                SelectGlobalTool -->|financial_calculator_tool| ExecGlobalCalc["FinancialCalculator"]
                ExecGlobalCalc --> MathEval["Deterministic Decimal precision arithmetic (ROUND_HALF_UP)"]
                ExecGlobalCalc --> DiscountEval["Discount projection & Net settlement calculation"]
                ExecGlobalCalc --> DateEval["Calendar deadline offsets"]
                MathEval --> GlobalCalcObs["Tool Observation: Exact numeric calculations and payment deadlines"]
                DiscountEval --> GlobalCalcObs
                DateEval --> GlobalCalcObs
            end
        end

        DBResults --> AgentThought
        GlobalRAGObs --> AgentThought
        GlobalCalcObs --> AgentThought
        LoopBreak --> SynthesizeGlobalFinal
        
        AgentThought --> CheckDone{"Sufficient Information or Iterations == 5?"}
        CheckDone -->|No| AgentThought
        CheckDone -->|Yes| SynthesizeGlobalFinal["Synthesize Unified Response across Database, RAG & Calculation Evidence"]
    end

    subgraph GlobalGuardrailsAndSave["Safety Guardrails & Multi-Provenance Persistence"]
        SynthesizeGlobalFinal --> GlobalGuardrails["response_guardrails: Filter System Prompts, Credentials, and Table Schemas"]
        GlobalGuardrails --> BuildProvenance["Format relational_provenance, calculation_provenance, citations, tool_calls"]
        BuildProvenance --> UpdateGlobalSession["Update Global Session State (pending_offer, verified_facts)"]
        UpdateGlobalSession --> SaveGlobalAssistant["ChatHistoryRepository.add_message(role='assistant', content, tool_calls, citations)"]
        SaveGlobalAssistant --> ReturnGlobalResponse(["Return GlobalChatMessageResponse to Client"])
    end
```

**Key Features:**
- **Dynamic Tool Coordination:** Orchestrates multi-step reasoning across database aggregations (Text-to-SQL), semantic policy/clause lookups (Document RAG), and exact calculations (Financial Calculator).
- **Execution Loop Protection:** Capped at `MAX_ITERATIONS = 5`. The `_is_duplicate_call` helper detects repeating arguments and prevents infinite tool execution loops.
- **Global Timeout Budget:** Enforces a 30-second global request timeout to safeguard ASGI worker availability.
- **Multi-Currency Safety:** The system prompt explicitly forbids summing or ranking monetary figures across heterogeneous currency codes without conversion, enforcing currency grouping.

---

## Security and Access Control

### Authentication & Role-Based Access Control (RBAC)
- **JWT Authentication:** OAuth2 Bearer tokens signed with HS256 (`SECRET_KEY`).
- **Role Hierarchy:**
  - `FINANCE_ANALYST`: Can upload, run OCR, extract, and validate documents. Scoped strictly to documents uploaded by their user ID in Global Chat (`uploaded_by = user.id`).
  - `FINANCE_MANAGER`: Full document oversight; can approve or reject workflow transitions; portfolio-wide visibility.
  - `AUDITOR`: Read-only access across all documents, workflow histories, and immutable audit logs.
  - `ADMIN`: Complete system access, user administration (`/api/v1/users`), and configuration management.

### AST-Level SQL Security & Tenant Isolation
The `TextToSQLService` (`app/services/text_to_sql_service.py`) protects the database against SQL injection, privilege escalation, and data exfiltration:
1. **SELECT-Only Enforcement:** Uses `sqlglot` to parse the proposed SQL query into an Abstract Syntax Tree (AST). Rejects any query containing DDL or DML statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, etc.).
2. **Table & Column Allowlists:** Queries are restricted to pre-approved tables. Sensitive fields (`users.password_hash`) are strictly excluded.
3. **Programmatic AST Tenant Rewriting:** When a `FINANCE_ANALYST` issues a natural language query, the AST rewriter traverses the query tree and programmatically injects `uploaded_by = user.id` predicates into table join conditions, preventing unauthorized data access.
4. **Execution Boundaries:** Enforces read-only database connections, a 5-second PostgreSQL statement timeout (`SET statement_timeout = 5000`), and a hard `LIMIT 100` result ceiling.

### Response Guardrails & Prompt Protection
- **Prompt Isolation:** `response_guardrails.py` sanitizes assistant outputs, stripping any accidental leaks of system instructions, internal table schemas, or database credentials.
- **State Query Refusal:** Refuses user attempts to probe agent internal states or bypass security policies.

---

## Database Architecture

EFDI runs on **PostgreSQL 16** with the `pgvector` extension. The schema is organized into four logical clusters:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL 16 Database                          │
├────────────────────────┬───────────────────────┬───────────────────────┤
│ Relational Entities    │ Processing Results    │ AI & Vector Storage   │
├────────────────────────┼───────────────────────┼───────────────────────┤
│ • users                │ • ocr_results         │ • document_chunks     │
│ • documents            │ • classification_res  │   (embedding: Vector) │
│ • invoices             │ • extraction_results  │   (tsv: TSVECTOR)     │
│ • vendors              │ • validation_results  ├───────────────────────┤
│ • vendor_aliases       │ • workflow_history    │ Conversational State  │
│ • invoice_line_items   │ • audit_logs          ├───────────────────────┤
│ • payment_obligations  │                       │ • chat_sessions       │
│ • invoice_payments     │                       │ • chat_messages       │
└────────────────────────┴───────────────────────┴───────────────────────┘
```

1. **Document Management:**
   - `documents`: Authoritative tracking record (`status`, `mime_type`, `sha256_hash`, `stored_filename`, `uploaded_by`).
   - `audit_logs`: Append-only immutable log of every action, status change, and user activity.
   - `workflow_history`: State machine audit trail for `SUBMIT`, `APPROVE`, and `REJECT` actions.
2. **Normalized Financial Projections:**
   - `invoices`: 1:1 projection of extracted invoice data (`invoice_number`, `invoice_date`, `currency`, `subtotal_amount`, `tax_amount`, `grand_total_amount`, `source_extraction_result_id`).
   - `vendors` & `vendor_aliases`: Master vendor entity and naming variations.
   - `invoice_line_items`: 1:N normalized item rows (`description`, `quantity`, `unit_price`, `amount`, `line_number`).
   - `payment_obligations`: Tracks due dates, payment statuses, and early payment discount terms.
   - `invoice_payments`: Settlement logs (deliberately isolated from extraction).
3. **Vector & Full-Text Search:**
   - `document_chunks`: Stores semantic text blocks. Contains `embedding` (`vector(384)`) indexed via HNSW/IVFFlat and `tsv_content` (`tsvector`) indexed via GIN.
4. **Chat & Session State:**
   - `chat_sessions`: Tracks `session_type` (`DOCUMENT` vs `GLOBAL`), user associations, and `state_json` (pending conversational offers, verified facts).
   - `chat_messages`: Turn history storing user queries, assistant responses, structured `tool_calls` JSON, and `citations` JSON.

---

## API Architecture

The FastAPI backend exposes versioned endpoints under `/api/v1`:

| Router Prefix | Primary Endpoints | Description |
| :--- | :--- | :--- |
| `/auth` | `POST /login`, `POST /refresh`, `GET /me` | JWT login, token rotation, and current user profile |
| `/users` | `GET /`, `POST /`, `PATCH /{id}/role` | Admin-only user management and role assignment |
| `/documents` | `POST /upload`, `POST /bulk-intake`, `GET /`, `GET /{id}` | File intake, deduplication, search, and download |
| `/ocr` | `POST /documents/{id}/run`, `GET /documents/{id}/result` | Trigger Docling OCR, view full text and bounding boxes |
| `/classification` | `POST /documents/{id}/classify`, `POST /documents/{id}/correct` | Run document classification and human correction |
| `/extraction` | `POST /documents/{id}/extract`, `PATCH /documents/{id}/fields/{key}` | Hybrid extraction, reconciliation, and field corrections |
| `/validation` | `POST /documents/{id}/validate`, `GET /documents/{id}/result` | Run mathematical and business rule consistency checks |
| `/workflow` | `POST /documents/{id}/transition`, `GET /documents/{id}/history` | State machine transitions (`SUBMIT`, `APPROVE`, `REJECT`) |
| `/audit` | `GET /logs`, `GET /documents/{id}/logs` | Query append-only audit trail with filtering |
| `/chat` | `POST /documents/{id}/messages`, `GET /documents/{id}/history` | Scoped Document Assistant conversational endpoint |
| `/chat/corpus` | `POST /messages`, `GET /history`, `DELETE /history` | Global Portfolio Multi-Tool Assistant conversational endpoint |

---

## End-to-End Workflow

```text
1. INGESTION
   User uploads invoice (PDF/image) ──> SHA-256 deduplication ──> Save UUID file to uploads/ ──> Document status = UPLOADED

2. OCR (DOCLING)
   POST /ocr/documents/{id}/run ──> Docling converts file ──> TableFormer parses tables ──> Status = OCR_COMPLETED
   └──> Non-blocking trigger: RAGIngestionService chunks and embeds document into pgvector

3. CLASSIFICATION
   POST /classification/documents/{id}/classify ──> Rule/ML engine evaluates signals ──> document_type set (e.g. NPO)

4. HYBRID EXTRACTION & RECONCILIATION
   POST /extraction/documents/{id}/extract ──> Parallel execution:
   ├── Thread 1: RuleBasedExtractor (regex + spatial heuristics)
   └── Thread 2: LLMBasedExtractor (Mistral AI structured JSON schema)
   ReconciliationEngine reconciles candidates ──> Status = EXTRACTED
   └──> Syncs relational entities into invoices, vendors, invoice_line_items, payment_obligations

5. BUSINESS VALIDATION
   POST /validation/documents/{id}/validate ──> Math check: Subtotal + Tax - Discount == Grand Total
   └──> Zero discrepancies: Status = VALIDATED (Errors flagged for review)

6. WORKFLOW APPROVAL
   Analyst triggers SUBMIT ──> Status = PENDING_APPROVAL
   Manager triggers APPROVE ──> Status = APPROVED

7. CONVERSATIONAL INTELLIGENCE
   • Scoped: Analyst opens "Ask AI" tab ──> Queries payment terms with page citations
   • Global: Manager visits /chat ──> Queries spend totals (SQL) + penalty clauses (RAG) + discount (Calculator)
```

---

## Setup & Running the Application

### Prerequisites
- Docker Engine $\ge 24.0$ and Docker Compose v2
- Node.js $\ge 18$ and npm (for standalone frontend development)
- Python 3.12 (for standalone backend development)
- PostgreSQL 16 with `pgvector` extension

---

### Docker Compose Deployment

1. **Clone the repository and prepare environment variables:**
   ```bash
   cp .env.example .env
   ```
2. **Configure mandatory settings in `.env`:**
   - Set `SECRET_KEY` to a random 64-character hex string (`openssl rand -hex 32`).
   - Set `MISTRAL_API_KEY` to your Mistral AI API key.
   - Adjust `POSTGRES_PASSWORD` and `DATABASE_URL`.
3. **Build and start services:**
   ```bash
   docker compose up --build -d
   ```
4. **Access the application:**
   - **Frontend Web UI:** `http://localhost` (or `${FRONTEND_PORT:-80}`)
   - **Interactive API Documentation (Swagger):** `http://localhost:8000/api/docs`
   - **Health Check Probe:** `http://localhost:8000/health`
5. **Initial Setup:**
   - Navigate to `http://localhost/register` and create your administrative account.

---

### Local Development Setup

#### 1. Database Setup
Ensure PostgreSQL 16 is running locally with the `pgvector` extension enabled:
```sql
CREATE DATABASE efdi;
\c efdi
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 2. Backend Setup
```bash
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Launch backend development server
uvicorn app.main:app --reload --port 8000
```

#### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The frontend Vite development server will start at `http://localhost:5173`.

---

## Architectural Findings & Implementation Notes

During the codebase audit, the following architectural implementations and design patterns were verified:

1. **Direct File Handoff for Docling:** In `app/services/ocr_service.py`, files processed via Docling are passed directly by filesystem path to `engine.extract_from_file(file_path)`. This bypasses PyMuPDF rasterization and OpenCV preprocessing, delegating layout detection, OCR, and table structure recovery entirely to Docling's native vector parser and TableFormer model.
2. **In-Memory Post-OCR Table Analysis:** Following Docling Markdown export, `parse_markdown_table` extracts structured line items in-memory to compute OCR quality metrics, validation scores, and table counts for the audit log without altering Docling's raw output.
3. **Fault-Isolated Hybrid Extraction:** In `app/extraction/parallel_orchestrator.py`, a `ThreadPoolExecutor(max_workers=2)` runs `RuleBasedExtractor` and `LLMBasedExtractor` concurrently with exception trapping. If the LLM API fails or times out, the rule extractor's results are preserved, preventing extraction pipeline halts.
4. **Relational Synchronization Separation:** Extraction results are persisted in `extraction_results` as canonical JSONB fields. In parallel, `InvoicePersistenceService` syncs these into normalized relational tables (`invoices`, `vendors`, `invoice_line_items`, `payment_obligations`) to support safe Text-to-SQL querying. `invoice_payments` is deliberately excluded from invoice extraction to prevent premature payment logging.
5. **AST Tenant Scoping via `sqlglot`:** In `app/services/text_to_sql_service.py`, tenant isolation for `FINANCE_ANALYST` users is enforced by rewriting the AST. The system programmatically injects `uploaded_by = user.id` into table joins rather than relying on prompt compliance.
6. **Pre-Warmed Neural Models:** In `app/main.py`, the FastAPI lifespan context manager warms the `SentenceTransformers` embedding model and `CrossEncoder` reranker at startup. This eliminates a cold-start latency spike on the user's first conversational query.
7. **In-Process Daemon Threading for RAG Ingestion:** `RAGIngestionService.ingest_document_async` runs via an in-process daemon thread with an independent database session context (`get_db_context()`), keeping document OCR response times fast without requiring an external task broker.
