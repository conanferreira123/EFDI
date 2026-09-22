# EFDI Chatbot Data Model Audit

**Audit Date:** 2026-09-21  
**Auditor Roles:** Senior Database Architect, Principal Solutions Architect, AI/RAG Architect, Backend Codebase Auditor  
**Scope:** Read-Only Database and Codebase Audit for EFDI Conversational AI Redesign  
**Target Reference:** [EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd)  
**Database Engine:** PostgreSQL 16.3 on `localhost:5342` (Database: `EFDI`) with `pgvector` 0.8.0  
**Backend Framework:** FastAPI / SQLAlchemy 2.0.38 / Alembic (Migration Head: `014cab3b4e0b`)

---

## 1. Executive Summary

This forensic data model audit evaluates the existing PostgreSQL database schema, data records, backend services, repositories, and AI orchestration layer of the Enterprise Financial Document Intelligence (EFDI) platform. The primary goal is to establish the complete, evidence-grounded factual baseline required to design:
1. RAG metadata schemas and in-database filtering;
2. Relational schema context exposed to the ReAct Database / Text-to-SQL Agent;
3. Schema enhancements required to fulfill portfolio-wide and document-level financial inquiries;
4. Conversation session, state, and history persistence models.

### Key Audit Findings

1. **Unified Database Engine:** EFDI utilizes PostgreSQL 16 as a unified data store for relational models, dense semantic vectors (`Vector(384)` with HNSW cosine distance indexing), and sparse lexical search (`TSVECTOR` with GIN indexing). There is no external vector store (e.g., Chroma, Pinecone).
2. **Relational vs. Semi-Structured Partitioning:**
   - Core file lifecycle metadata lives in relational columns (`documents`, `users`).
   - Business invoice fields (invoice numbers, dates, amounts, taxes, buyer/seller identities, payment terms) live exclusively inside a single `JSONB` column: `extraction_results.fields`.
   - There are **no dedicated relational columns** for invoice amounts, dates, or vendor identities in either `documents` or `extraction_results`.
3. **Payment & Deadline Data Deficit:**
   - Relational columns for `due_date`, `payment_status`, `outstanding_amount`, `paid_amount`, and `balance_due` **do not exist**.
   - Inside `extraction_results.fields`, `due_date` is populated in **0 out of 452 (0.0%)** extraction records.
   - `payment_terms` is populated in only **37 out of 452 (8.2%)** extraction records (e.g., `"Net 30"`).
   - The system lacks deterministic NLP or rule-based logic to convert terms like `"Net 30"` into concrete calendar deadlines.
   - Questions regarding upcoming payment deadlines, urgency, or outstanding balances **cannot be answered reliably** from current structured data.
4. **Vendor Data Fragmentation:**
   - In `documents`, `vendor_code` is `NULL` in **1,107 of 1,299 (85.2%)** rows; `vendor_name` does not exist.
   - In `extraction_results.fields`, the vendor name is extracted under the key `seller_name` (or `seller.name`), **not** `vendor_name`.
   - The dedicated table `vendor_knowledge` has schema support and vector embeddings but currently contains **0 rows**.
   - Vendor names in extractions are unnormalized raw text strings (e.g., `"Kirby and Valdez Andrews"` vs. `"Acme Corp Global"`).
5. **RAG Chunk Metadata Scope:**
   - In `document_chunks`, `metadata_json` stores only structural document layout markers (`chunk_index`, `section`, `page_number`, `bounding_box_refs`, `line_range`, `table_rows_count`).
   - Chunks contain **zero business metadata** (no dates, amounts, vendor names, or document types) and **zero authorization metadata** (no `uploaded_by` or tenant markers).
   - All authorization scoping and document metadata filtering in RAG currently requires an SQL `JOIN documents ON document_chunks.document_id = documents.id`.
6. **Text-to-SQL Disconnect:**
   - `TextToSQLService` gives the LLM a prompt stating that `extraction_results.fields` contains `fields->'vendor_name'->>'value'`, which yields empty results because the extracted key is `seller_name`.
   - The LLM receives no relational context regarding dates, monetary types, or the absence of payment statuses.
   - AST validation for `FINANCE_ANALYST` forcefully injects `documents.uploaded_by = :user_id`, which fails if the query targets `users` directly.
7. **Chat Persistence State:**
   - The database already contains operational `chat_sessions` (44 rows) and `chat_messages` (80 rows) tables supporting both `DOCUMENT` and `GLOBAL` session types.
   - `chat_messages` persists `tool_calls` and `citations` as JSONB.
   - Document chat retains conversational context (last 10 messages), whereas Global chat currently executes stateless single turns.

---

## 2. Existing Database Architecture

The EFDI platform runs on a standalone PostgreSQL 16.3 instance with the `pgvector` extension enabled.

```
+-----------------------------------------------------------------------------------------------+
|                               POSTGRESQL 16.3 UNIFIED DATABASE (EFDI)                         |
|                                                                                               |
|  +---------------------------+  +---------------------------+  +---------------------------+  |
|  |     RELATIONAL ENGINE     |  |       PGVECTOR ENGINE     |  |    FULL-TEXT SEARCH (FTS) |  |
|  | - documents (1,299 rows)  |  | - document_chunks.        |  | - document_chunks.        |  |
|  | - extraction_results (452)|  |   embedding: Vector(384)  |  |   tsv_content: TSVECTOR   |  |
|  | - users (3,806 rows)      |  | - HNSW index:             |  | - GIN index:              |  |
|  | - audit_logs (4,169 rows) |  |   vector_cosine_ops       |  |   ix_document_chunks_tsv  |  |
|  | - chat_sessions (44 rows) |  | - vendor_knowledge.       |  | - English stemming &      |  |
|  | - chat_messages (80 rows) |  |   embedding: Vector(384)  |  |   websearch_to_tsquery    |  |
|  +---------------------------+  +---------------------------+  +---------------------------+  |
|                                                                                               |
|  Connection Pool: SQLAlchemy QueuePool (pool_size=10, max_overflow=20)                        |
|  Read-Only Isolation: SET TRANSACTION READ ONLY; SET LOCAL statement_timeout = '5000ms';     |
|  Migration Engine: Alembic (Version Table: alembic_version, Head: 014cab3b4e0b)               |
+-----------------------------------------------------------------------------------------------+
```

### 2.1 Database Configuration Parameters

| Parameter | Database Setting | Verified In Code / Environment |
|---|---|---|
| PostgreSQL Version | 16.3 (Debian/Windows) | `SELECT version();` |
| Connection String | `postgresql://postgres:***@localhost:5342/EFDI` | [backend/.env:L16](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/.env#L16) |
| Active Extensions | `pgvector` (0.8.0), `plpgsql` | `SELECT extname, extversion FROM pg_extension;` |
| Vector Dimension | 384 dimensions (`all-MiniLM-L6-v2`) | [backend/app/models/document_chunk.py:L26](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py#L26) |
| Vector Distance Metric | Cosine Distance (`<=>`, `vector_cosine_ops`) | [backend/app/repositories/chunk_repository.py:L68](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py#L68) |
| Vector Index Type | HNSW (`m=16, ef_construction=64`) | [alembic/versions/014cab3b4e0b_*.py:L27-L30](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/alembic/versions/014cab3b4e0b_add_hnsw_and_doc_id_indexes_on_document_.py#L27-L30) |
| Full-Text Search Config | `english` dictionary, stored `tsvector` | [backend/app/models/document_chunk.py:L32](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py#L32) |
| FTS Index Type | GIN (`ix_document_chunks_tsv`) | [alembic/versions/22cf2e444b51_*.py:L31](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/alembic/versions/22cf2e444b51_add_tsv_content_and_chat_tables.py#L31) |
| Migration Head Revision | `014cab3b4e0b` | `alembic_version` table (1 row) |

---

## 3. Complete Table Inventory

A total of **15 tables** reside in the `public` schema. All 15 were inspected directly in PostgreSQL.

| Table Name | Primary Purpose | Model Definition | Migration Reference | Live Row Count | Primary Key | Foreign Keys |
|---|---|---|---|---|---|---|
| `documents` | Core financial document lifecycle tracking, file hashes, storage locations, ownership | [document.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py) | `25865efaaa0b` | 1,299 | `id` | `uploaded_by` $\to$ `users.id` |
| `extraction_results` | Append-only store of extracted field data (stored as JSONB) and extraction confidence | [extraction_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/extraction_result.py) | `87d0535e0a9c` | 452 | `id` | `document_id` $\to$ `documents.id` |
| `document_chunks` | Semantic text chunks, 384-d dense embeddings, stored FTS tsvectors, structural layout metadata | [document_chunk.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py) | `018069fabf68`, `22cf2e444b51`, `014cab3b4e0b` | 142 | `id` | `document_id` $\to$ `documents.id` (CASCADE) |
| `users` | Authenticated platform accounts, role-based access control assignments, account status | [user.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/user.py) | `4cf4fda96099`, `2ffaeae37b7d` | 3,806 | `id` | None |
| `audit_logs` | System-wide immutable security and event audit trail | [audit_log.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/audit_log.py) | `bfd7768c6be6` | 4,169 | `id` | `user_id` $\to$ `users.id`, `document_id` $\to$ `documents.id` |
| `ocr_results` | Raw OCR extracted full-text, confidence score, and per-block bounding box JSONB | [ocr_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py) | `46222a8b1535` | 590 | `id` | `document_id` $\to$ `documents.id` |
| `chat_sessions` | Conversation sessions for Document-Level and Global AI Assistant | [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) | `22cf2e444b51` | 44 | `id` | `user_id` $\to$ `users.id` (CASCADE), `document_id` $\to$ `documents.id` (CASCADE) |
| `chat_messages` | Individual message turns, user questions, assistant responses, tool execution logs, citations | [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) | `22cf2e444b51` | 80 | `id` | `session_id` $\to$ `chat_sessions.id` (CASCADE) |
| `classification_results` | Document taxonomy classification verdicts, confidence, scoring breakdown, matched signals | [classification_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/classification_result.py) | `be1d0849d262` | 314 | `id` | `document_id` $\to$ `documents.id` |
| `validation_results` | Post-extraction validation rule outcomes, issue lists, error and warning counts | [validation_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/validation_result.py) | `5cf24992553b` | 142 | `id` | `document_id` $\to$ `documents.id` |
| `workflow_history` | Formal approval state transitions, reviewer IDs, comments, before/after status | [workflow_history.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/workflow_history.py) | `206f2a9dffa6` | 87 | `id` | `document_id` $\to$ `documents.id`, `performed_by` $\to$ `users.id` |
| `vendor_knowledge` | Vendor directory knowledge store with 384-d semantic embeddings | [vendor_knowledge.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/vendor_knowledge.py) | `018069fabf68` | 0 | `id` | None |
| `training_examples` | Human reviewer feedback logging for ML model fine-tuning | [training_example.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/training_example.py) | `b9c2ae51cb79` | 44 | `id` | `document_id` $\to$ `documents.id`, `corrected_by` $\to$ `users.id` |
| `system_setting` | Dynamic key-value configuration table (e.g. OCR engine default) | [system_setting.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/system_setting.py) | Applied via baseline scripts | 0 | `id` | None |
| `alembic_version` | Internal Alembic version tracking table | Alembic internal | N/A | 1 | `version_num` | None |

---

## 4. Detailed Schema — `documents`

### 4.1 Table Identity
- **Table Name:** `documents`
- **Purpose:** Central entity representing an ingested document. Governs file storage, lifecycle workflow status, file integrity hash, soft-delete state, and user ownership.
- **Model Definition:** [backend/app/models/document.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py)
- **Alembic Migration:** `25865efaaa0b_add_documents_table.py` (with later column additions for `company_code`, `vendor_code`, `validation_status`)

### 4.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Enum / Constraints | Generation Origin |
|---|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('documents_id_seq')` | YES | NO | YES | `documents_pkey` (btree) | `> 0` | System-generated (Sequence) |
| `original_filename` | `character varying(255)` | NO | None | NO | NO | NO | None in DB | Max length 255 | User-entered (Upload client) |
| `stored_filename` | `character varying(255)` | NO | None | NO | NO | YES | `documents_stored_filename_key` (btree) | UUIDv4 string + extension | Application-generated (UUID) |
| `document_type` | `character varying(30)` | NO | `'UNKNOWN'` | NO | NO | NO | None in DB | `DocumentType` enum values | Classification-derived |
| `status` | `character varying(30)` | NO | `'UPLOADED'` | NO | NO | NO | None in DB | `DocumentStatus` enum values | State machine / workflow |
| `company_code` | `character varying(20)` | YES | None | NO | NO | NO | None in DB | Alphanumeric code | Extraction or user-entered |
| `vendor_code` | `character varying(20)` | YES | None | NO | NO | NO | None in DB | Alphanumeric code | Extraction or user-entered |
| `validation_status` | `character varying(30)` | YES | None | NO | NO | NO | None in DB | Validation state | Validation service |
| `file_size_bytes` | `bigint` | NO | None | NO | NO | NO | None in DB | Positive integer | Application-measured file size |
| `mime_type` | `character varying(100)` | NO | None | NO | NO | NO | None in DB | MIME string | Detected by `python-magic` |
| `file_hash` | `character varying(64)` | NO | None | NO | NO | NO | None in DB | SHA-256 hex digest (64 chars) | Application-calculated (SHA-256) |
| `page_count` | `integer` | YES | None | NO | NO | NO | None in DB | Non-negative integer | OCR / PDF parser derived |
| `is_deleted` | `boolean` | NO | `false` | NO | NO | NO | None in DB | Soft-delete flag | Application-managed |
| `uploaded_by` | `integer` | NO | None | NO | YES | NO | None in DB | References `users.id` | Auth context (`current_user.id`) |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Timezone-aware timestamp | System-generated (TimestampMixin) |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Timezone-aware timestamp | System-generated (TimestampMixin) |

> [!WARNING]
> While the SQLAlchemy model defines `index=True` for `document_type`, `status`, `company_code`, `vendor_code`, `validation_status`, `file_hash`, and `uploaded_by`, live PostgreSQL inspection confirms that **only two indexes exist** on `documents`: `documents_pkey` and `documents_stored_filename_key`. Secondary btree indexes were not created during the Alembic migrations.

### 4.3 Live Sample Data & Population Statistics (1,299 Rows Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 1,299 | 0 | 0.0% | `2947`, `2948`, `4116` |
| `original_filename` | 1,299 | 0 | 0.0% | `"scan_1fb539e1.pdf"`, `"invoice_51109301.pdf"`, `"batch1-0001.pdf"` |
| `stored_filename` | 1,299 | 0 | 0.0% | `"005ffab3805f4bcaaf656a818964c5.pdf"`, `"9b0f278dc5f29b89a34a0b449b3410.png"` |
| `document_type` | 1,299 | 0 | 0.0% | `"UNKNOWN"` (957 rows), `"NPO"` (229 rows), `"POI"` (98 rows), `"MSI"` (5 rows), `"JER"` (5 rows), `"BKA"` (5 rows) |
| `status` | 1,299 | 0 | 0.0% | `"UPLOADED"` (801 rows), `"OCR_COMPLETED"` (204 rows), `"EXTRACTED"` (163 rows), `"VALIDATED"` (85 rows), `"REJECTED"` (20 rows), `"PENDING_APPROVAL"` (15 rows), `"APPROVED"` (11 rows) |
| `company_code` | 223 | 1,076 | 82.8% | `"CC100"`, `NULL` |
| `vendor_code` | 192 | 1,107 | 85.2% | `"V100"`, `NULL` |
| `validation_status` | 0 | 1,299 | 100.0% | All rows are `NULL` |
| `file_size_bytes` | 1,299 | 0 | 0.0% | `3369`, `282883`, `244` |
| `mime_type` | 1,299 | 0 | 0.0% | `"application/pdf"`, `"image/png"`, `"image/jpeg"` |
| `file_hash` | 1,299 | 0 | 0.0% | `"1512198cc7b24c8e814229ea8b97f5..."`, `"9b0f278dc5f29b89a34a0b..."` |
| `page_count` | 0 | 1,299 | 100.0% | All rows are `NULL` in `documents` (stored in `ocr_results` instead) |
| `is_deleted` | 1,299 | 0 | 0.0% | `false` (1,292 rows), `true` (7 rows) |
| `uploaded_by` | 1,299 | 0 | 0.0% | `1`, `3230`, `3309`, `3801` |
| `created_at` | 1,299 | 0 | 0.0% | `"2026-09-15T13:07:02.312373+05:30"`, `"2026-09-10T12:47:38.481008+05:30"` |

---

## 5. Detailed Schema — `extraction_results`

### 5.1 Table Identity
- **Table Name:** `extraction_results`
- **Purpose:** Stores structured field-level extraction data generated by rule-based, LLM-based, or hybrid extraction pipelines. Append-only historical table.
- **Model Definition:** [backend/app/models/extraction_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/extraction_result.py)
- **Alembic Migration:** `87d0535e0a9c_add_extraction_results_table.py`

### 5.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Description |
|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('extraction_results_id_seq')` | YES | NO | YES | `extraction_results_pkey` (btree) | Primary key sequence |
| `document_id` | `integer` | NO | None | NO | YES | NO | None in DB | References `documents.id` (NO ACTION) |
| `document_type` | `character varying(30)` | NO | None | NO | NO | NO | None in DB | Snapshotted document type at extraction time |
| `engine_name` | `character varying(30)` | NO | None | NO | NO | NO | None in DB | Extraction engine (`hybrid`, `rule_based`, `llm_based`) |
| `fields` | `jsonb` | NO | `'{}'::jsonb` | NO | NO | NO | None in DB | Dictionary of all extracted fields, confidences, provenance |
| `overall_confidence` | `double precision` | NO | `0.0` | NO | NO | NO | None in DB | Aggregate extraction confidence score (0.0 - 1.0) |
| `fields_found_count` | `integer` | NO | `0` | NO | NO | NO | None in DB | Number of fields identified with non-null values |
| `fields_total_count` | `integer` | NO | `0` | NO | NO | NO | None in DB | Total field schema count for this document type |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Creation timestamp |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Last update timestamp |

### 5.3 Live Sample Data & Population Statistics (452 Rows Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 452 | 0 | 0.0% | `754`, `755`, `1205` |
| `document_id` | 452 | 0 | 0.0% | `2964`, `3179`, `4233` (covers 439 distinct documents) |
| `document_type` | 452 | 0 | 0.0% | `"NPO"` (347 rows), `"POI"` (105 rows) |
| `engine_name` | 452 | 0 | 0.0% | `"hybrid"` (289 rows), `"rule_based"` (118 rows), `"llm_based"` (45 rows) |
| `overall_confidence` | 452 | 0 | 0.0% | `0.87`, `0.92`, `0.75` |
| `fields_found_count` | 452 | 0 | 0.0% | `4`, `16`, `34` |
| `fields_total_count` | 452 | 0 | 0.0% | `19`, `25`, `40` |

### 5.4 Internal Structure of the `fields` JSONB Column

The `fields` JSONB column stores dictionary mappings. Each field entry is an object with this exact shape:

```json
{
  "value": "INV-2026-001",
  "is_found": true,
  "confidence": 0.95,
  "provenance": "agreed",
  "matched_text": "Invoice Number: INV-2026-001",
  "conflict_value": null,
  "manually_entered": false
}
```

In addition, Phase A-F added a hierarchical `canonical` object inside `fields` for NPO documents:
- `fields->'canonical'` holds the full structured hierarchy (`invoice_information`, `seller`, `buyer`, `line_items`, `taxes`, `totals`, `payment`, `references`, `metadata`).

---

## 6. Detailed Schema — `document_chunks`

### 6.1 Table Identity
- **Table Name:** `document_chunks`
- **Purpose:** Stores semantic document chunks, 384-dimensional pgvector embeddings, and generated tsvectors for hybrid retrieval (Dense Vector + Sparse PostgreSQL FTS).
- **Model Definition:** [backend/app/models/document_chunk.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py)
- **Alembic Migrations:**
  - `018069fabf68_add_pgvector_document_chunks_and_vendor_.py` (initial table & vector column)
  - `22cf2e444b51_add_tsv_content_and_chat_tables.py` (added generated `tsv_content` & GIN index)
  - `014cab3b4e0b_add_hnsw_and_doc_id_indexes_on_document_.py` (added HNSW vector index & btree indexes)

### 6.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Description |
|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('document_chunks_id_seq')` | YES | NO | YES | `document_chunks_pkey` (btree) | Sequence primary key |
| `document_id` | `integer` | NO | None | NO | YES | NO | `ix_document_chunks_document_id` (btree) | References `documents.id` (ON DELETE CASCADE) |
| `page_number` | `integer` | YES | None | NO | NO | NO | None in DB | Document page number (1-indexed) |
| `chunk_type` | `character varying(30)` | NO | None | NO | NO | NO | `ix_document_chunks_chunk_type` (btree) | Section category (`HEADER`, `PARTIES`, `LINE_ITEMS`, `SUMMARY`, `TERMS`) |
| `content` | `text` | NO | None | NO | NO | NO | None in DB | Clean text content of the chunk |
| `embedding` | `USER-DEFINED (vector(384))` | NO | None | NO | NO | NO | `ix_document_chunks_embedding_hnsw` (`hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`) | 384-dimensional dense float vector |
| `metadata_json` | `jsonb` | YES | `'{}'::jsonb` | NO | NO | NO | None in DB | Chunk structural provenance and bounding box references |
| `tsv_content` | `tsvector` | YES | Generated Stored Column | NO | NO | NO | `ix_document_chunks_tsv` (gin) | `GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED` |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Ingestion timestamp |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Last update timestamp |

### 6.3 Live Sample Data & Population Statistics (142 Chunks Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 142 | 0 | 0.0% | `6`, `7`, `8`, `144` |
| `document_id` | 142 | 0 | 0.0% | `4116`, `4117`, `4233` (covers 123 distinct documents) |
| `page_number` | 142 | 0 | 0.0% | `1` (all current ingested test chunks are 1-page documents) |
| `chunk_type` | 142 | 0 | 0.0% | `"TERMS"` (103 rows), `"PARTIES"` (24 rows), `"HEADER"` (5 rows), `"SUMMARY"` (5 rows), `"LINE_ITEMS"` (5 rows) |
| `content` | 142 | 0 | 0.0% | See sample text structure below |
| `embedding` | 142 | 0 | 0.0% | `[0.0241, -0.0512, 0.0119, ...]` (384 floats) |
| `metadata_json` | 142 | 0 | 0.0% | `{"section": "LINE ITEMS", "has_table": true, "line_range": [1, 4], "chunk_index": 2, "page_number": 1, "table_rows_count": 2, "bounding_box_refs": []}` |
| `tsv_content` | 142 | 0 | 0.0% | `'11/07/2023':9 '51109330':5 'due':12 'invoic':3 'net':14 'term':13` |

### 6.4 Sample Chunk Content and Structural Formatting

#### Sample 1: Chunk ID 6 (Doc #4116, Chunk Type: `HEADER`, Page 1)
```
=== HEADER & METADATA ===
TAX INVOICE
Invoice No: INV-9021
Date: 2024-03-15
PO Number: PO-8812
```

#### Sample 2: Chunk ID 7 (Doc #4116, Chunk Type: `PARTIES`, Page 1)
```
=== PARTIES ===
--- SELLER COLUMN ---
ACME Industrial Supplies Ltd.
VAT ID: GB123456789
12 Oxford Street, London

--- BUYER COLUMN ---
Global Manufacturing Corp.
Tax ID: US987654321
500 Industrial Parkway, Chicago, IL
```

#### Sample 3: Chunk ID 8 (Doc #4116, Chunk Type: `LINE_ITEMS`, Page 1)
```
=== LINE ITEMS ===
| Item | Description | Qty | Unit Price | Total |
| --- | --- | --- | --- | --- |
| 1 | Hydraulic Pump Valve A1 | 10 | 100.00 | 1000.00 |
| 2 | Pressure Seal Ring Type B | 20 | 7.50 | 150.00 |
```

---

## 7. Detailed Schema — `users`

### 7.1 Table Identity
- **Table Name:** `users`
- **Purpose:** User authentication directory, credentials, and role assignments for the platform.
- **Model Definition:** [backend/app/models/user.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/user.py)
- **Alembic Migrations:** `4cf4fda96099_create_users_table_foundation_.py`, `2ffaeae37b7d_expand_user_model_email_full_name_is_.py`

### 7.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Description |
|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('users_id_seq')` | YES | NO | YES | `users_pkey` (btree) | User sequence ID |
| `username` | `character varying(50)` | NO | None | NO | NO | YES | `users_username_key` (btree) | Unique login handle |
| `email` | `character varying(120)` | NO | None | NO | NO | YES | `users_email_key` (btree) | Unique email address |
| `full_name` | `character varying(120)` | NO | None | NO | NO | NO | None in DB | Display name |
| `password_hash` | `character varying(255)` | NO | None | NO | NO | NO | None in DB | Passlib/bcrypt password hash (STRICTLY REDACTED) |
| `role` | `character varying(30)` | NO | `'FINANCE_ANALYST'` | NO | NO | NO | None in DB | Role enum (`ADMIN`, `FINANCE_MANAGER`, `FINANCE_ANALYST`, `AUDITOR`) |
| `is_active` | `boolean` | NO | `true` | NO | NO | NO | None in DB | Account active status flag |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Account creation timestamp |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Last update timestamp |

### 7.3 Live Sample Data & Population Statistics (3,806 Rows Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 3,806 | 0 | 0.0% | `1`, `2`, `3801` |
| `username` | 3,806 | 0 | 0.0% | `"admin"`, `"finance_manager_1"`, `"analyst_3801"` |
| `email` | 3,806 | 0 | 0.0% | `"admin@efdi-corp.com"`, `"analyst_3801@efdi-corp.com"` |
| `full_name` | 3,806 | 0 | 0.0% | `"System Administrator"`, `"Conan Ferreira"`, `"Jane Doe"` |
| `password_hash` | 3,806 | 0 | 0.0% | `[REDACTED bcrypt hash, length ~60 chars]` |
| `role` | 3,806 | 0 | 0.0% | See Role Distribution below |
| `is_active` | 3,806 | 0 | 0.0% | `true` (3,758 rows), `false` (48 rows) |

#### Role Distribution Across Corpus:
- `FINANCE_ANALYST`: 3,022 accounts (2,974 active)
- `FINANCE_MANAGER`: 411 accounts (411 active)
- `ADMIN`: 244 accounts (244 active)
- `AUDITOR`: 129 accounts (129 active)

---

## 8. Detailed Schema — `audit_logs`

### 8.1 Table Identity
- **Table Name:** `audit_logs`
- **Purpose:** Append-only system-wide security, operational, and user action audit trail. Distinct from `workflow_history` which handles only state machine transitions.
- **Model Definition:** [backend/app/models/audit_log.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/audit_log.py)
- **Alembic Migration:** `bfd7768c6be6_add_audit_logs_table.py`

### 8.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Description |
|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('audit_logs_id_seq')` | YES | NO | YES | `audit_logs_pkey` (btree) | Audit event primary key |
| `action` | `character varying(50)` | NO | None | NO | NO | NO | None in DB | Action enum value (`AuditAction`) |
| `user_id` | `integer` | YES | None | NO | YES | NO | None in DB | References `users.id` (NULL for failed logins) |
| `document_id` | `integer` | YES | None | NO | YES | NO | None in DB | References `documents.id` (NULL for non-doc actions) |
| `details` | `jsonb` | YES | None | NO | NO | NO | None in DB | Freeform JSON context payload |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Event timestamp |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Record update timestamp |

### 8.3 Live Sample Data & Population Statistics (4,169 Rows Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 4,169 | 0 | 0.0% | `13811`, `13812`, `14500` |
| `action` | 4,169 | 0 | 0.0% | `"DOCUMENT_UPLOADED"`, `"DOCUMENT_DELETED"`, `"OCR_RUN"`, `"CLASSIFICATION_RUN"`, `"EXTRACTION_RUN"`, `"VALIDATION_RUN"`, `"DOCUMENT_APPROVED"`, `"LOGIN_SUCCESS"`, `"LOGIN_FAILED"` |
| `user_id` | 3,345 | 824 | 19.8% | `1`, `3230`, `NULL` (unauthenticated failed logins) |
| `document_id` | 2,603 | 1,566 | 37.6% | `2947`, `4116`, `NULL` (system and login events) |
| `details` | 4,169 | 0 | 0.0% | `{"filename": "scan_1fb.pdf", "size_bytes": 3369}`, `{"reason": "Invalid password", "attempted_username": "conan"}` |

---

## 9. Detailed Schema — `ocr_results`

### 9.1 Table Identity
- **Table Name:** `ocr_results`
- **Purpose:** Stores raw optical character recognition full-text, confidence metrics, and per-block spatial coordinate JSONB. Append-only history.
- **Model Definition:** [backend/app/models/ocr_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py)
- **Alembic Migration:** `46222a8b1535_add_ocr_results_table.py`

### 9.2 Complete Column Definition

| Column Name | PostgreSQL Data Type | Nullable | Default Value | PK | FK | Unique | Indexes | Description |
|---|---|---|---|---|---|---|---|---|
| `id` | `integer` | NO | `nextval('ocr_results_id_seq')` | YES | NO | YES | `ocr_results_pkey` (btree) | Sequence primary key |
| `document_id` | `integer` | NO | None | NO | YES | NO | None in DB | References `documents.id` (NO ACTION) |
| `engine_name` | `character varying(30)` | NO | None | NO | NO | NO | None in DB | OCR engine (`easyocr`, `paddleocr`, `stub`) |
| `page_count` | `integer` | NO | `0` | NO | NO | NO | None in DB | Detected page count |
| `full_text` | `text` | NO | `''::text` | NO | NO | NO | None in DB | Complete extracted raw string |
| `average_confidence` | `double precision` | NO | `0.0` | NO | NO | NO | None in DB | Mean character/word confidence (0.0 - 1.0) |
| `raw_blocks` | `jsonb` | NO | `'[]'::jsonb` | NO | NO | NO | None in DB | List of page blocks with bounding boxes and confidences |
| `processing_time_ms` | `integer` | YES | None | NO | NO | NO | None in DB | OCR execution runtime in milliseconds |
| `created_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | OCR creation timestamp |
| `updated_at` | `timestamp with time zone` | NO | `now()` | NO | NO | NO | None in DB | Record update timestamp |

### 9.3 Live Sample Data & Population Statistics (590 Rows Examined)

| Column Name | Populated Count | NULL Count | NULL % | Representative Database Samples |
|---|---|---|---|---|
| `id` | 590 | 0 | 0.0% | `1928`, `1929`, `2001` |
| `document_id` | 590 | 0 | 0.0% | `4173`, `4184`, `4233` (covers 385 distinct documents) |
| `engine_name` | 590 | 0 | 0.0% | `"easyocr"` (345 rows), `"stub"` (180 rows), `"paddleocr"` (65 rows) |
| `page_count` | 590 | 0 | 0.0% | `1` (majority of current corpus) |
| `full_text` | 590 | 0 | 0.0% | `"TAX INVOICE\nInvoice No: 51109338\nDate: 04/13/2013\n..."` |
| `average_confidence` | 590 | 0 | 0.0% | `0.88`, `0.92`, `0.79` |
| `raw_blocks` | 590 | 0 | 0.0% | `[{"page_number": 1, "blocks": [{"text": "TAX INVOICE", "confidence": 0.98, "bounding_box": [10, 20, 100, 40]}]}]` |
| `processing_time_ms` | 590 | 0 | 0.0% | `228`, `1450`, `23763` |

---

## 10. Other Relevant Tables

### 10.1 `chat_sessions` (44 Rows)
- **Model:** [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `user_id` (`integer`, FK `users.id` ON DELETE CASCADE)
  - `session_type` (`varchar(20)`, values: `'DOCUMENT'`, `'GLOBAL'`)
  - `document_id` (`integer`, nullable, FK `documents.id` ON DELETE CASCADE)
  - `title` (`varchar(255)`, e.g. `"Document 4197 Assistant"`, `"Global Financial Assistant"`)
  - `created_at`, `updated_at` (`timestamptz`)
- **Indexes:**
  - `chat_sessions_pkey`
  - `ix_chat_sessions_user_id`
  - `ix_chat_sessions_session_type`
  - `ix_chat_sessions_document_id`
- **Data Distribution:** 24 `GLOBAL` sessions, 20 `DOCUMENT` sessions.

### 10.2 `chat_messages` (80 Rows)
- **Model:** [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `session_id` (`integer`, FK `chat_sessions.id` ON DELETE CASCADE)
  - `role` (`varchar(20)`, values: `'user'`, `'assistant'`)
  - `content` (`text`, raw conversational text)
  - `tool_calls` (`jsonb`, nullable, records executed tools, SQL executed, calculator outputs)
  - `citations` (`jsonb`, nullable, records retrieved chunk IDs, page numbers, snippets, bounding box references)
  - `created_at`, `updated_at` (`timestamptz`)
- **Indexes:**
  - `chat_messages_pkey`
  - `ix_chat_messages_session_id`

### 10.3 `classification_results` (314 Rows)
- **Model:** [classification_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/classification_result.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `document_id` (`integer`, FK `documents.id`)
  - `predicted_type` (`varchar(30)`, e.g., `'POI'`, `'NPO'`, `'JER'`)
  - `confidence` (`float`, e.g. `0.85`)
  - `engine_name` (`varchar(30)`, e.g. `'rule_based'`)
  - `signals` (`jsonb`, list of matched rules and keyword weights)
  - `scores_by_type` (`jsonb`, dictionary of score breakdowns across all document types)

### 10.4 `validation_results` (142 Rows)
- **Model:** [validation_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/validation_result.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `document_id` (`integer`, FK `documents.id`)
  - `document_type` (`varchar(30)`)
  - `engine_name` (`varchar(50)`)
  - `is_valid` (`boolean`, `true`/`false`)
  - `error_count` (`integer`), `warning_count` (`integer`)
  - `issues` (`jsonb`, list of specific validation failures, rule codes, field keys, messages)

### 10.5 `workflow_history` (87 Rows)
- **Model:** [workflow_history.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/workflow_history.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `document_id` (`integer`, FK `documents.id`)
  - `action` (`varchar(30)`, e.g. `'APPROVE'`, `'REJECT'`, `'REQUEST_APPROVAL'`)
  - `from_status` (`varchar(30)`), `to_status` (`varchar(30)`)
  - `comment` (`text`, nullable, reviewer feedback)
  - `performed_by` (`integer`, FK `users.id`)

### 10.6 `vendor_knowledge` (0 Rows)
- **Model:** [vendor_knowledge.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/vendor_knowledge.py)
- **Columns:**
  - `id` (`integer`, PK)
  - `vendor_code` (`varchar(20)`, unique index)
  - `vendor_name` (`varchar(255)`)
  - `tax_id` (`varchar(50)`, nullable)
  - `default_gl_account` (`varchar(30)`, nullable)
  - `default_cost_center` (`varchar(30)`, nullable)
  - `search_text` (`text`)
  - `embedding` (`vector(384)`)
  - `metadata_json` (`jsonb`, nullable)
- **Status:** Empty table (0 rows). Not currently populated during intake or extraction.

### 10.7 `training_examples` (44 Rows)
- **Model:** [training_example.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/training_example.py)
- **Columns:** `id`, `document_id`, `corrected_by`, `task_type`, `document_type`, `source_text`, `field_key`, `predicted_value`, `corrected_value`, `extra_context`.

### 10.8 `system_setting` (0 Rows)
- **Model:** [system_setting.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/system_setting.py)
- **Columns:** `id`, `key` (`varchar(255)`, unique), `value` (`varchar(1024)`).

---

## 11. Table Relationship Map

```mermaid
erDiagram
    users ||--o{ documents : "uploads (uploaded_by)"
    users ||--o{ audit_logs : "triggers (user_id)"
    users ||--o{ workflow_history : "performs (performed_by)"
    users ||--o{ chat_sessions : "owns (user_id)"
    users ||--o{ training_examples : "corrects (corrected_by)"

    documents ||--o{ ocr_results : "has (document_id)"
    documents ||--o{ classification_results : "has (document_id)"
    documents ||--o{ extraction_results : "has (document_id)"
    documents ||--o{ validation_results : "has (document_id)"
    documents ||--o{ workflow_history : "has (document_id)"
    documents ||--o{ document_chunks : "chunked into (document_id)"
    documents ||--o{ audit_logs : "audits (document_id)"
    documents ||--o{ chat_sessions : "associated with (document_id)"
    documents ||--o{ training_examples : "trained on (document_id)"

    chat_sessions ||--o{ chat_messages : "contains (session_id)"
```

### Relationship Enforcement Details

| Parent Table | Child Table | Parent Key | Child Key | Cardinality | Nullable? | Enforced by Postgres FK? | Delete Rule | Application Cascade Behavior |
|---|---|---|---|---|---|---|---|---|
| `users` | `documents` | `id` | `uploaded_by` | 1 : N | NO | YES | `NO ACTION` | Soft delete only; users never physically deleted |
| `users` | `audit_logs` | `id` | `user_id` | 1 : N | YES | YES | `NO ACTION` | Preserved for security history |
| `users` | `workflow_history` | `id` | `performed_by` | 1 : N | NO | YES | `NO ACTION` | Preserved for workflow history |
| `users` | `chat_sessions` | `id` | `user_id` | 1 : N | NO | YES | `CASCADE` | User deletion purges chat sessions |
| `documents` | `document_chunks` | `id` | `document_id` | 1 : N | NO | YES | `CASCADE` | Chunk repository idempotently deletes old chunks |
| `documents` | `chat_sessions` | `id` | `document_id` | 1 : N | YES | YES | `CASCADE` | Purged on document hard-delete (soft-delete preserves) |
| `documents` | `ocr_results` | `id` | `document_id` | 1 : N | NO | YES | `NO ACTION` | Append-only historical runs |
| `documents` | `classification_results`| `id`| `document_id` | 1 : N | NO | YES | `NO ACTION` | Append-only historical classifications |
| `documents` | `extraction_results` | `id` | `document_id` | 1 : N | NO | YES | `NO ACTION` | Append-only historical extractions |
| `documents` | `validation_results` | `id` | `document_id` | 1 : N | NO | YES | `NO ACTION` | Append-only validation snapshots |
| `documents` | `workflow_history` | `id` | `document_id` | 1 : N | NO | YES | `NO ACTION` | State machine transition audit trail |
| `documents` | `audit_logs` | `id` | `document_id` | 1 : N | YES | YES | `NO ACTION` | System audit trail |
| `chat_sessions` | `chat_messages` | `id` | `session_id` | 1 : N | NO | YES | `CASCADE` | Deleting session cascades to all message turns |

---

## 12. Document Data Lineage

The lifecycle of document data flows sequentially through discrete stages. Each stage is tracked in the database:

```
[1. PDF / Image Upload]
         │ (HTTP Multipart or Folder Scan)
         ▼
[2. documents Table]
    - Stored on disk under uploads/
    - Status: UPLOADED
    - Metadata: original_filename, stored_filename, file_hash, uploaded_by
         │
         ▼
[3. OCR Processing]
    - Engine: easyocr / paddleocr
    - Output: ocr_results.full_text + ocr_results.raw_blocks
    - Status: OCR_COMPLETED
         │
         ├─────────────────────────────────────────┐
         ▼                                         ▼
[4. Document Classification]             [6. RAG Ingestion Pipeline]
    - Rule-based regex signal matching       - StructureAwareChunker splits full_text
    - Output: classification_results         - Preserves sections, tables, page markers
    - Updates: documents.document_type       - Generates 384-d embeddings (MiniLM-L6)
         │                                   - Computes PostgreSQL FTS tsvector
         ▼                                   - Output: document_chunks table
[5. Field Extraction Pipeline]                     │
    - Hybrid (Rules + Mistral LLM)                 ▼
    - Consumes: ocr_results.full_text        [7. Retrieval & Chat Layer]
    - Output: extraction_results.fields JSONB   - Global ReAct Agent (SQL + RAG + Calc)
    - Status: EXTRACTED                         - Document Chat Agent (RAG + Calc)
         │                                      - Output: chat_sessions & chat_messages
         ▼
[8. Business Validation]
    - Checks required fields, formats, duplicates
    - Output: validation_results
    - Status: VALIDATED
         │
         ▼
[9. Approval Workflow]
    - Reviewer action: PENDING_APPROVAL -> APPROVED / REJECTED
    - Output: workflow_history
    - Status: APPROVED or REJECTED
```

### Data Transformations Across Transitions

| Step | Transition | Fields Transferred | Fields Transformed / Normalized | Fields Lost | Fields Derived |
|---|---|---|---|---|---|
| Upload $\to$ Document | File $\to$ `documents` | `filename`, `content` | Filename replaced with UUID in `stored_filename` | Original directory path | `file_hash` (SHA-256), `file_size_bytes`, `mime_type` |
| Document $\to$ OCR | File bytes $\to$ `ocr_results` | `document_id` | Rasterized images/PDFs converted to text | Spatial font styles, color palettes | `full_text`, `raw_blocks` (bbox coordinates), `average_confidence` |
| OCR $\to$ Classification | `full_text` $\to$ `classification_results` | `document_id`, `full_text` | Keyword pattern matching against AP/R2R taxonomy | Non-matching text | `predicted_type`, `confidence`, `scores_by_type` |
| OCR $\to$ Extraction | `full_text` $\to$ `extraction_results` | `full_text`, `document_type` | Regex patterns + LLM JSON schema extraction | Formatting whitespace, decorative text | `fields` JSONB with `value`, `confidence`, `matched_text` |
| OCR $\to$ RAG Ingestion | `full_text` $\to$ `document_chunks` | `full_text`, `document_id` | Chunked by page boundaries & section markers | Intra-sentence linebreaks | 384-d float embeddings, computed `tsvector`, chunk layout metadata |
| Extraction $\to$ Validation | `fields` $\to$ `validation_results` | `fields`, `document_type` | Evaluates required fields, date formats, math balances | None | `is_valid` flag, `error_count`, `warning_count`, `issues` |
| Validation $\to$ Workflow | Document state $\to$ `workflow_history` | `document_id`, `status` | Action validation against state machine | None | `from_status`, `to_status`, transition log |

---

## 13. Invoice Field Data Lineage

This matrix audits the origin, storage location, and current accessibility of all business invoice fields across the 452 live extraction records and 1,299 documents.

| Business Field | Source | Extraction / Derivation | Stored Where | Live Availability & Quality |
|---|---|---|---|---|
| `invoice_number` | Document text | Extracted via regex / LLM | `extraction_results.fields['invoice_number']['value']` | **Populated in 360/452 (79.6%)**. Strings like `"51109338"`, `"INV-2026-001"`. Not in `documents`. |
| `invoice_date` | Document text | Extracted via regex / LLM | `extraction_results.fields['invoice_date']['value']` | **Populated in 357/452 (79.0%)**. ISO strings like `"2013-04-13"`, `"2026-06-15"`. Not in `documents`. |
| `vendor_name` | Document text | Extracted as `seller_name` / `seller.name` | `extraction_results.fields['seller_name']['value']` | **Populated under `seller_name` in 357/452 (79.0%)**. Key `vendor_name` is **0.0%**. Not in `documents`. |
| `buyer_name` | Document text | Extracted as `buyer_name` / `buyer.name` | `extraction_results.fields['buyer_name']['value']` | **Populated in 381/452 (84.3%)**. Strings like `"Becker Ltd"`, `"Our Co"`. Not in `documents`. |
| `currency` | Document text | Extracted via regex / LLM | `extraction_results.fields['currency']['value']` | **Populated in 357/452 (79.0%)**. ISO codes like `"USD"`, `"INR"`, `"EUR"`. Not in `documents`. |
| `subtotal_net_amount`| Document text | Extracted via regex / LLM | `extraction_results.fields['subtotal_net_amount']['value']` | **Populated in 345/452 (76.3%)**. Decimal strings like `"2640.17"`. Key `net_amount` is **0.0%**. |
| `total_tax_amount` | Document text | Extracted via regex / LLM | `extraction_results.fields['total_tax_amount']['value']` | **Populated in 345/452 (76.3%)**. Decimal strings like `"2564.03"`. Key `tax_amount` is **0.0%**. |
| `grand_total_amount`| Document text | Extracted via regex / LLM | `extraction_results.fields['grand_total_amount']['value']` | **Populated in 363/452 (80.3%)**. Decimal strings like `"5204.20"`. Key `grand_total` is **0.0%**. |
| `due_date` | Document text | Extraction attempted | `extraction_results.fields['due_date']['value']` | **Populated in 0/452 (0.0%)**. Key exists in schema but zero records populated. |
| `payment_terms` | Document text | Extracted via regex / LLM | `extraction_results.fields['payment_terms']['value']` | **Populated in 37/452 (8.2%)**. Raw strings like `"Net 30"`, `"NET60"`. |
| `payment_status` | Business transaction | N/A | None | **MISSING ENTIRELY**. No column or extraction key exists. |
| `outstanding_amount` | ERP / AP ledger | N/A | None | **MISSING ENTIRELY**. No column or extraction key exists. |
| `paid_amount` | ERP / AP ledger | N/A | None | **MISSING ENTIRELY**. No column or extraction key exists. |
| `balance_due` | ERP / AP ledger | N/A | None | **MISSING ENTIRELY**. No column or extraction key exists. |
| `po_number` | Document text | Extracted via regex / LLM | `extraction_results.fields['po_number']['value']` | **Populated in 193/452 (42.7%)**. Strings like `"PO-2026-789"`. |
| `vendor_code` | Manual / Database | Metadata injection | `documents.vendor_code` | **Populated in 192/1,299 (14.8%)** of documents (`"V100"`). |
| `company_code` | Manual / Database | Metadata injection | `documents.company_code` | **Populated in 223/1,299 (17.2%)** of documents (`"CC100"`). |
| `document_type` | Document text | Classified by rule engine | `documents.document_type` & `extraction_results` | **100% populated** in `documents` (`UNKNOWN`, `NPO`, `POI`, `MSI`, `JER`, `BKA`). |
| `original_filename`| Upload client | User-supplied string | `documents.original_filename` | **100% populated** in `documents`. |
| `upload_timestamp` | System clock | System-generated | `documents.created_at` | **100% populated** in `documents`. |
| `uploaded_by` | Auth token | Injected from JWT | `documents.uploaded_by` | **100% populated** in `documents` (FK `users.id`). |
| `workflow_status` | Approval engine | State machine transition | `documents.status` | **100% populated** in `documents` (`UPLOADED`, `EXTRACTED`, `VALIDATED`, etc.). |
| `approval_status` | Workflow history | Set by reviewer | `workflow_history.to_status` | **Populated in 87 rows** (`APPROVED`, `REJECTED`). |

---

## 14. Payment / Deadline Capability Audit

A major expectation for the target conversational agent is to resolve payment urgency and deadline inquiries:
- *"Which documents do I need to pay by next week?"*
- *"Which documents do I need to pay by the end of October?"*
- *"Which invoices do I need to settle urgently?"*

### 14.1 Structured Field Availability in PostgreSQL

| Field Investigated | Relational Column Exists? | Extraction JSON Key Exists? | Populated Rows (out of 452 extractions) | Population % | Reliable for SQL Filtering? |
|---|---|---|---|---|---|
| `invoice_date` | NO | YES (`fields->'invoice_date'->>'value'`) | 357 | 79.0% | **Partially** (requires JSONB arrow operator; date format varies) |
| `due_date` | NO | YES (`fields->'due_date'->>'value'`) | 0 | **0.0%** | **NO** (Zero values in database) |
| `payment_terms` | NO | YES (`fields->'payment_terms'->>'value'`) | 37 | 8.2% | **NO** (Only 8.2% populated; raw unparsed text) |
| `payment_status` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `outstanding_amount` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `paid_amount` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `balance_due` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `discount_deadline` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `early_payment_discount`| NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `late_payment_penalty` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |
| `settlement_status` | NO | NO | 0 | **0.0%** | **NO** (Field does not exist) |

### 14.2 Payment Term Interpretation & Due Date Derivation

Codebase inspection of [backend/app/rag/financial_calculator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py) and [backend/app/extraction/](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/) confirms:
1. **No Terms Parser:** There is **no deterministic logic** to parse payment term strings such as:
   - `"Net 30"`, `"Net 60"`, `"Net 45"`
   - `"Due upon receipt"`
   - `"2/10 Net 30"` (2% discount within 10 days, net due in 30 days)
   - `"30 days from invoice date"`
2. **Calculator Tool Limitations:** `FinancialCalculator.calculate_discount()` requires explicit numerical arguments passed to Python:
   - `gross_amount` (Decimal)
   - `discount_percentage` (Decimal)
   - `days_offset` (integer)
   - `invoice_date` (optional string `YYYY-MM-DD`)
3. **No Dynamic Due Date Derivation:** The system never executes `invoice_date + interval '30 days'` to populate a missing due date in the database.

### 14.3 Disambiguation: Workflow Approval Status vs. Payment Status

The codebase enforces a document workflow state machine with values:
`UPLOADED` $\to$ `OCR_COMPLETED` $\to$ `EXTRACTED` $\to$ `VALIDATED` $\to$ `PENDING_APPROVAL` $\to$ `APPROVED` (or `REJECTED`).

> [!CAUTION]
> In EFDI, **`APPROVED` DOES NOT MEAN PAID**.
> `APPROVED` strictly represents financial approval within the internal AP invoice review workflow ([workflow_service.py:L114](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/workflow_service.py#L114)). There is no downstream payment execution, remittance feed, or settlement ledger in the current database. An approved invoice may remain completely unpaid.

### 14.4 Can Payment Deadline Questions Be Answered?

- **Via Structured SQL:** **IMPOSSIBLE**. Neither `due_date`, `payment_status`, nor `outstanding_amount` exists as a relational column or populated extraction field.
- **Via RAG Retrieval:** **LIMITED / FRAGMENTED**. RAG chunks of type `TERMS` or `HEADER` may contain raw text snippets stating payment conditions (e.g., *"Payment due within 30 days"*). However, RAG cannot perform portfolio-wide sorting, date math, or deadline aggregation across hundreds of documents.

---

## 15. Vendor Data Audit

Audit for vendor-related inquiries:
- *"Which invoices are from vendor XYZ?"*
- *"How much money do I owe to vendor XYZ?"*

### 15.1 Where Vendor Identity Is Stored

1. **`documents.vendor_code`:**
   - Data type: `varchar(20)`
   - Nullability: `NULL` in 85.2% of rows.
   - Values: Only `"V100"` appears in the current corpus (192 rows).
2. **`extraction_results.fields`:**
   - Field key: Extracted under `seller_name` (357 populated rows) and `seller.name` (169 populated rows).
   - Data type inside JSON: string.
   - **`vendor_name` DOES NOT EXIST** in `extraction_results.fields`.
3. **`vendor_knowledge` Table:**
   - Dedicated table exists with columns: `vendor_code`, `vendor_name`, `tax_id`, `default_gl_account`, `default_cost_center`, `search_text`, `embedding`.
   - **Row count: 0**. The table is completely empty.

### 15.2 Vendor Name Duplication & Normalization

Sample extracted seller names demonstrate that vendor strings are unnormalized:
- `"Kirby and Valdez Andrews"` (Invoice 51109338)
- `"Acme Corp"` vs. `"Acme Corp Global"`
- `"Global Industrial Supplies Ltd."`

There are no canonical vendor IDs, no alias tables, and no foreign keys linking `documents` to a centralized vendor master record.

### 15.3 Can Vendor Queries Be Answered?

- *"Which invoices are from vendor XYZ?":*
  - **Can be answered via SQL ONLY IF** the query inspects `extraction_results.fields->'seller_name'->>'value' ILIKE '%XYZ%'`.
  - **Currently fails in practice** because `TextToSQLService.SCHEMA_CONTEXT` tells the LLM to query `fields->'vendor_name'->>'value'`, which evaluates to `NULL` for every document.
- *"How much money do I owe to vendor XYZ?":*
  - **CANNOT BE ANSWERED RELIABLY**. While `grand_total_amount` can be summed for a matching seller name, the system has no record of payment status. The agent cannot know if invoices are paid, partially paid, or outstanding.

---

## 16. Document Identity / Reference Resolution

Inquiries frequently reference human document identifiers:
- *"How much do I need to pay according to invoice INV-1001?"*
- *"What does the ABC invoice say?"*
- *"Tell me about INV-123."*
- *"How much do I need to pay according to invoice_51109301.pdf?"*

### 16.1 Document Identifiers in the Database

| Identifier | Column / Location | Type | Sample Value | Uniqueness Scope |
|---|---|---|---|---|
| Database ID | `documents.id` | `integer` | `4116` | Globally unique (PK) |
| Original Filename | `documents.original_filename` | `varchar(255)` | `"invoice_51109301.pdf"` | Not unique (users can upload identically named files) |
| Stored Filename | `documents.stored_filename` | `varchar(255)` | `"9b0f278dc5f29b89.pdf"` | Globally unique (UUID) |
| Invoice Number | `extraction_results.fields->'invoice_number'->>'value'` | JSON string | `"51109301"` | Not unique across different vendors |
| PO Number | `extraction_results.fields->'po_number'->>'value'` | JSON string | `"PO-2026-789"` | Not unique |
| Seller Name | `extraction_results.fields->'seller_name'->>'value'` | JSON string | `"Kirby and Valdez Andrews"`| Unnormalized text |

### 16.2 Resolution Flow Gaps

```
Human Query: "How much according to invoice INV-1001?"
                      │
                      ▼
[Resolution Layer: CURRENTLY NON-EXISTENT]
- No entity-linking service
- No lookup from "INV-1001" to documents.id
- Document Chat requires explicit integer ID in URL path: /api/v1/chat/documents/{id}/messages
- Global Chat passes raw text directly to SQL/RAG without resolving target document ID
```

In the current implementation, if a user in Global Chat asks about `"INV-1001"`, the system relies entirely on the Text-to-SQL LLM to write a join across `documents` and `extraction_results` filtering on `fields->'invoice_number'->>'value' = 'INV-1001'`.

---

## 17. RAG Metadata Inventory

Detailed audit of `document_chunks` table storage, indexing, and runtime metadata:

### 17.1 Stored Column Architecture

```
TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NULL,
    chunk_type VARCHAR(30) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    metadata_json JSONB NULL DEFAULT '{}'::jsonb,
    tsv_content TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 17.2 Vector Search Specification
- **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions)
- **Distance Operator:** Cosine Distance (`<=>`)
- **Index:** `ix_document_chunks_embedding_hnsw`
  - Engine: `hnsw`
  - Opclass: `vector_cosine_ops`
  - Parameters: `m = 16`, `ef_construction = 64`

### 17.3 Sparse Full-Text Search Specification
- **Column:** `tsv_content`
- **Configuration:** Stored generated column using PostgreSQL `'english'` dictionary.
- **Index:** `ix_document_chunks_tsv` (GIN)
- **Query Ranking:** `ts_rank_cd(document_chunks.tsv_content, websearch_to_tsquery('english', query))`

### 17.4 Complete Inventory of `metadata_json` Keys

Inspection of all 142 live chunks reveals that `metadata_json` contains **only layout and structural provenance**:
- `chunk_index` (`int`): Sequential index within document (0, 1, 2, ...)
- `section` (`str`): Detected section name (`"HEADER & METADATA"`, `"PARTIES"`, `"LINE ITEMS"`, `"TOTALS & SUMMARY"`, `"TERMS"`, `"DOCUMENT_BODY"`)
- `page_number` (`int`): Page index (1-indexed)
- `has_table` (`bool`): Indicates presence of markdown table markup
- `table_rows_count` (`int`): Row count for table chunks
- `line_range` (`list[int]`): Starting and ending line offsets `[start, end]`
- `bounding_box_refs` (`list`): Spatial bounding boxes mapped from `ocr_results.raw_blocks`

> [!IMPORTANT]
> `document_chunks.metadata_json` contains **NO business metadata**:
> - NO `vendor_name` or `seller_name`
> - NO `invoice_date` or `due_date`
> - NO `grand_total` or `currency`
> - NO `document_type`
> - NO `uploaded_by` (user ID)

---

## 18. Potential RAG Metadata Filtering Fields

Evaluation of candidate fields for hybrid RAG filtering:

| Candidate Field | Exists in DB? | Location | Directly Available on Chunk? | Requires Relational Join? | Suitable for Chunk Metadata? | Suitable for Document-Level Filter? | Recommendation / Architectural Role |
|---|---|---|---|---|---|---|---|
| `document_id` | YES | `document_chunks.document_id` | **YES** (Indexed FK column) | NO | **YES** | **YES** | Primary filter for Document Chat |
| `chunk_type` | YES | `document_chunks.chunk_type` | **YES** (Indexed column) | NO | **YES** | NO | Filter for clause types (`TERMS`, `LINE_ITEMS`) |
| `page_number` | YES | `document_chunks.page_number` | **YES** (Column & metadata) | NO | **YES** | NO | Scoping by document page |
| `uploaded_by` | YES | `documents.uploaded_by` | **NO** | YES (`JOIN documents`) | Conditionally | **YES** | Mandatory authorization boundary for `FINANCE_ANALYST` |
| `is_deleted` | YES | `documents.is_deleted` | **NO** | YES (`JOIN documents`) | NO | **YES** | Soft-delete exclusion filter |
| `document_type` | YES | `documents.document_type` | **NO** | YES (`JOIN documents`) | Conditionally | **YES** | Filter by taxonomy (`POI`, `NPO`, `JER`) |
| `workflow_status`| YES | `documents.status` | **NO** | YES (`JOIN documents`) | NO | **YES** | Filter by review status (`APPROVED`, `VALIDATED`) |
| `invoice_date` | YES | `extraction_results.fields` | **NO** | YES (2 joins: `chunks` $\to$ `docs` $\to$ `ext`) | NO | **YES** | Temporal filtering |
| `due_date` | NO | None (0% populated) | **NO** | N/A | NO | NO | Cannot be used until extracted |
| `vendor_code` | YES | `documents.vendor_code` | **NO** | YES (`JOIN documents`) | Conditionally | **YES** | Partitioning by vendor |
| `seller_name` | YES | `extraction_results.fields` | **NO** | YES (2 joins: `chunks` $\to$ `docs` $\to$ `ext`) | NO | **YES** | Vendor semantic filtering |
| `company_code` | YES | `documents.company_code` | **NO** | YES (`JOIN documents`) | Conditionally | **YES** | Multi-entity corporate code filtering |

---

## 19. Text-to-SQL Schema Context Audit

Audit of [backend/app/services/text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py):

### 19.1 Table and Column Allowlists

- **Allowed Tables:** `documents`, `extraction_results`, `validation_results`, `classification_results`, `users`.
- **Forbidden Tables:** `audit_logs`, `chat_sessions`, `chat_messages`, `document_chunks`, `vendor_knowledge`, `workflow_history`, `training_examples`.
- **Allowed Columns:**
  - `documents`: `id`, `original_filename`, `stored_filename`, `document_type`, `status`, `company_code`, `vendor_code`, `validation_status`, `file_size_bytes`, `mime_type`, `page_count`, `is_deleted`, `uploaded_by`, `created_at`, `updated_at`.
  - `extraction_results`: `id`, `document_id`, `engine_name`, `overall_confidence`, `fields`, `created_at`, `updated_at`.
  - `validation_results`: `id`, `document_id`, `is_valid`, `error_count`, `warning_count`, `issues`, `created_at`, `updated_at`.
  - `classification_results`: `id`, `document_id`, `predicted_type`, `confidence`, `scores_by_type`, `created_at`, `updated_at`.
  - `users`: `id`, `username`, `email`, `full_name`, `role`, `is_active`, `created_at`.
  - `users.password_hash` is **strictly excluded**.

### 19.2 Prompt Schema Context Given to the LLM

```text
Table: documents
Columns: id (int), original_filename (str), document_type (str: POI, NPOI), status (str: UPLOADED, OCR_COMPLETED, EXTRACTED, VALIDATED, APPROVED, REJECTED), company_code (str), vendor_code (str), validation_status (str), file_size_bytes (int), uploaded_by (int), is_deleted (bool), created_at (timestamp)

Table: extraction_results
Columns: id (int), document_id (int, FK documents.id), fields (JSONB: e.g. fields->'vendor_name'->>'value', fields->'invoice_date'->>'value', fields->'grand_total_amount'->>'value', fields->'invoice_number'->>'value'), overall_confidence (float), created_at (timestamp)

Table: validation_results
Columns: id (int), document_id (int, FK documents.id), is_valid (bool), error_count (int), warning_count (int), issues (JSONB), created_at (timestamp)

Table: classification_results
Columns: id (int), document_id (int, FK documents.id), predicted_type (str), confidence (float), created_at (timestamp)

Table: users
Columns: id (int), username (str), email (str), full_name (str), role (str: FINANCE_ANALYST, FINANCE_MANAGER, AUDITOR, ADMIN)
```

### 19.3 AST Validation and Security Enforcement
- **Parser:** `sqlglot.parse_one(sql, read="postgres")`
- **Statement Type:** Rejects anything that is not `exp.Select`.
- **Forbidden Functions Blacklist:** `pg_sleep`, `query_to_xml`, `pg_read_file`, `pg_write_file`, `pg_stat_file`, `version`, `current_setting`, `set_config`, `dblink`, `dblink_exec`.
- **Row Limit Clamping:** Hard limit of `LIMIT 100` enforced at AST level.
- **Read-Only Transaction:** Executes with `SET TRANSACTION READ ONLY;` and `SET LOCAL statement_timeout = '5000ms';`.

### 19.4 AST Authorization Injection Deficiencies
Lines 153-176 of `text_to_sql_service.py` show how analyst scoping is enforced:
```python
if is_analyst and policy == "scoped":
    if "documents" in tables:
        auth_predicate = sqlglot.parse_one(f"documents.uploaded_by = {user.id} AND documents.is_deleted = false", read="postgres")
    else:
        ast = ast.join("documents", on=f"extraction_results.document_id = documents.id")
        auth_predicate = sqlglot.parse_one(f"documents.uploaded_by = {user.id} AND documents.is_deleted = false", read="postgres")
```

> [!WARNING]
> **AST Join Defect:** If a `FINANCE_ANALYST` queries the `users` table directly (e.g. `SELECT username, role FROM users`), `"documents"` is not in `tables`. The code unconditionally joins `documents` on `extraction_results.document_id = documents.id`, which causes a PostgreSQL syntax error because `extraction_results` is not part of the query!

---

## 20. Role-Based Data Access Matrix

The current backend enforces permissions across user roles as follows:

| Resource / Action | FINANCE_ANALYST | FINANCE_MANAGER | AUDITOR | ADMIN | Enforced By |
|---|---|---|---|---|---|
| Document Read (`documents`) | Own uploads only (`uploaded_by == user.id`) | All non-deleted documents | All non-deleted documents | All documents | [document_service.py:L170](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L170) |
| Document Delete (`documents`) | Own uploads only | Forbidden (Admin only for hard-purge) | Forbidden | All documents | [document_service.py:L202](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L202) |
| Document Chat (`/chat/documents/{id}`) | Allowed if document owner | Allowed on all documents | Allowed on all documents | Allowed on all documents | [chat_service.py:L38](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L38) |
| Global Chat (`/chat/corpus`) | Scoped to own documents via SQL/RAG injection | Allowed across entire corpus | Allowed across entire corpus | Allowed across entire corpus | [agent_orchestrator.py:L68](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L68) |
| Text-to-SQL Execution | Injects `documents.uploaded_by = :user_id` | Unscoped across allowed tables | Unscoped across allowed tables | Unscoped across allowed tables | [text_to_sql_service.py:L153](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L153) |
| RAG Retrieval Scope | Injects `Document.uploaded_by == user.id` | All non-deleted documents | All non-deleted documents | All non-deleted documents | [chunk_repository.py:L116](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py#L116) |
| User Directory (`users` table) | Forbidden in REST API; **leaked in Text-to-SQL allowlist** | Forbidden in REST API | Forbidden in REST API | Full CRUD | [users.py:L24](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/users.py#L24) |
| Audit Logs (`audit_logs`) | Forbidden in REST API | Forbidden in REST API | Read-only access in REST API | Full access in REST API | [audit.py:L24](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/audit.py#L24) |

---

## 21. Data Quality / NULL Analysis

Comprehensive audit of data quality and NULL frequencies across 1,299 documents and 452 extractions:

| Field Analyzed | Total Rows | Populated Rows | NULL / Missing Rows | % NULL | Data Quality Assessment |
|---|---|---|---|---|---|
| `documents.id` | 1,299 | 1,299 | 0 | 0.0% | Excellent. Continuous serial sequence. |
| `documents.original_filename` | 1,299 | 1,299 | 0 | 0.0% | Clean filenames (`.pdf`, `.png`, `.jpg`). |
| `documents.document_type` | 1,299 | 1,299 | 0 | 0.0% | 73.7% are `"UNKNOWN"` because classification was run on only ~342 documents. |
| `documents.status` | 1,299 | 1,299 | 0 | 0.0% | Consistent enum values. 801 are in initial `"UPLOADED"` state. |
| `documents.company_code` | 1,299 | 223 | 1,076 | 82.8% | Populated only when specifically injected. |
| `documents.vendor_code` | 1,299 | 192 | 1,107 | 85.2% | Heavily sparse. Only single value `"V100"` present. |
| `documents.validation_status` | 1,299 | 0 | 1,299 | **100.0%** | Never written to by the validation service. |
| `documents.page_count` | 1,299 | 0 | 1,299 | **100.0%** | Column unused in `documents`; populated in `ocr_results` instead. |
| `extraction.invoice_number` | 452 | 360 | 92 | 20.4% | Reliable where extracted (79.6% populated). |
| `extraction.invoice_date` | 452 | 357 | 95 | 21.0% | ISO strings (`YYYY-MM-DD`). 79.0% populated. |
| `extraction.seller_name` | 452 | 357 | 95 | 21.0% | Clean extracted vendor names. Keyed as `seller_name`. |
| `extraction.grand_total_amount`| 452 | 363 | 89 | 19.7% | Clean decimal strings. Keyed as `grand_total_amount`. |
| `extraction.currency` | 452 | 357 | 95 | 21.0% | 3-letter ISO currency codes (`USD`, `INR`, `EUR`). |
| `extraction.due_date` | 452 | 0 | 452 | **100.0%** | **Complete absence**. Zero rows populated. |
| `extraction.payment_terms` | 452 | 37 | 415 | 91.8% | Severe sparsity (8.2% populated). |
| `ocr_results.full_text` | 590 | 590 | 0 | 0.0% | Complete text present for all OCR runs. |
| `document_chunks.content` | 142 | 142 | 0 | 0.0% | Clean text with markdown tables intact. |
| `document_chunks.embedding` | 142 | 142 | 0 | 0.0% | 100% populated with 384-d float vectors. |

---

## 22. Existing Chat History / Chat Context Architecture

### 22.1 Tables & Schema
Chat persistence is backed by two dedicated tables defined in [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py):
- `chat_sessions`: Partitioned by `session_type` (`'DOCUMENT'` or `'GLOBAL'`) and scoped by `user_id`.
- `chat_messages`: Child table containing conversation turns.

```
chat_sessions (id, user_id, session_type, document_id, title, created_at, updated_at)
      │
      └──< chat_messages (id, session_id, role, content, tool_calls, citations, created_at, updated_at)
```

### 22.2 Session Scoping & User Isolation
- **Document Chat:** Keyed to `(user_id, document_id, 'DOCUMENT')`. When a user opens document chat for document 4116, [ChatHistoryRepository.get_or_create_document_session()](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py#L20) retrieves or initializes that user's private session for that document. Users cannot see other users' conversations.
- **Global Chat:** Keyed to `(user_id, 'GLOBAL')`. Each user maintains a single rolling global chat session.

### 22.3 History Windowing & Context Forwarding to LLM
- **Document Chat:** [ChatService.send_document_message()](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L53) fetches the last 10 messages from the database and forwards `[{"role": m.role, "content": m.content}]` to `llm_client.generate_grounded_answer()`.
- **Global Chat:** [AgentOrchestrator.process_global_query()](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L64) persists turns to `chat_messages`, but **does NOT forward past conversation history to the LLM**. Each global query is processed as a stateless single turn.

### 22.4 Persistence of Tool Calls and Citations
- Assistant turns in `chat_messages` persist full JSONB metadata:
  - `tool_calls`: Contains records of executed tools, proposed SQL queries, and calculator outputs.
  - `citations`: Contains retrieved chunk IDs, document IDs, page numbers, text snippets, and bounding box coordinates.

---

## 23. Expected Query Capability Matrix

Factual capability assessment of the 12 expected user queries:

| # | User Query | Required Information | Current Source in EFDI | Structured? | RAG Needed? | Calculator Needed? | Current Capability | Missing Data / Failure Reason |
|---|---|---|---|---|---|---|---|---|
| 1 | *"What is the amount I need to pay?"* (Document Chat) | `grand_total_amount`, `currency` | `extraction_results.fields['grand_total_amount']` & RAG chunk `SUMMARY` | YES (in JSONB) | YES (Fallback) | NO | **CAPABLE** | None for total invoice amount. (Outstanding balance cannot be determined if partially paid). |
| 2 | *"What is the recent document that I have uploaded?"* (Global Chat) | `original_filename`, `created_at`, `uploaded_by` | `documents` table | **YES** | NO | NO | **CAPABLE** | None. Fully supported via `SELECT ... ORDER BY created_at DESC LIMIT 1`. |
| 3 | *"How many documents have I uploaded?"* (Global Chat) | `COUNT(*)`, `uploaded_by`, `is_deleted` | `documents` table | **YES** | NO | NO | **CAPABLE** | None. Fully supported via `SELECT COUNT(*) FROM documents WHERE uploaded_by = :uid`. |
| 4 | *"Which documents do I need to pay by next week?"* (Global Chat) | `due_date`, `payment_status`, `outstanding_amount` | None | **NO** | NO (Cannot aggregate dates) | YES (Date math) | **INCAPABLE** | `due_date` is 0% populated; `payment_status` and `outstanding_amount` do not exist. |
| 5 | *"Which documents do I need to pay by the end of October?"* (Global Chat) | `due_date`, `payment_status`, `outstanding_amount` | None | **NO** | NO | YES | **INCAPABLE** | `due_date` is 0% populated; no payment status. |
| 6 | *"Which invoices are urgent?"* (Global Chat) | `due_date`, `payment_status`, `invoice_date`, `payment_terms` | None | **NO** | YES (Fragmented text) | NO | **INCAPABLE** | No structured urgency or deadline fields exist. |
| 7 | *"Which invoices are from vendor XYZ?"* (Global Chat) | `seller_name`, `invoice_number`, `document_id` | `extraction_results.fields['seller_name']` | YES (in JSONB) | NO | NO | **PARTIALLY CAPABLE** | Fails currently because Text-to-SQL prompt instructs LLM to query `vendor_name` instead of `seller_name`. |
| 8 | *"How much money do I owe to vendor XYZ?"* (Global Chat) | `seller_name`, `grand_total_amount`, `payment_status` | `extraction_results.fields['seller_name']` & `grand_total_amount` | YES (in JSONB) | NO | YES (Sum) | **INCAPABLE** | Can sum total billed amount, but cannot determine what is *owed* vs. *paid* because payment status is missing. |
| 9 | *"What are the payment terms in this invoice?"* (Document Chat) | `payment_terms` clause | `extraction_results.fields['payment_terms']` & RAG chunk `TERMS` | Partial (8.2%) | **YES** | NO | **CAPABLE** | Answered accurately via Document RAG chunk retrieval over `TERMS` section. |
| 10 | *"What does this invoice say about late payment?"* (Document Chat) | Late payment penalty clause | RAG chunk `TERMS` / `ocr_results.full_text` | NO | **YES** | NO | **CAPABLE** | Fully supported via Document RAG hybrid retrieval. |
| 11 | *"When is this invoice due?"* (Document Chat) | `due_date` / payment terms clause | RAG chunk `TERMS` / `ocr_results.full_text` | NO | **YES** | YES (If date offset needed) | **PARTIALLY CAPABLE** | Can retrieve clause if present in text, but cannot calculate calendar date deterministically. |
| 12 | *"How much do I need to pay according to invoice XYZ?"* (Global Chat) | Document resolution, `grand_total_amount` | `extraction_results.fields` | YES (in JSONB) | NO | NO | **PARTIALLY CAPABLE** | Relies on LLM writing complex JSONB SQL query without entity resolution helper. |

---

## 24. Security / Data Exposure Findings

### 24.1 User Directory Leakage via Text-to-SQL Tool
`ALLOWED_TABLES` in [text_to_sql_service.py:L35](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L35) includes the `users` table. The allowed columns include `username`, `email`, `full_name`, and `role`. While `password_hash` is excluded, an authenticated `FINANCE_ANALYST` can submit a natural language query such as *"List all users and their emails"*, causing the tool to execute `SELECT username, email, full_name, role FROM users LIMIT 100`, exposing enterprise employee identities.

### 24.2 AST Join Defect on Non-Document Queries
When a `FINANCE_ANALYST` executes a query that does not reference `documents`, the AST sanitizer attempts to forcibly join `documents` on `extraction_results.document_id = documents.id`. If `extraction_results` is also not in the query (e.g. querying `users`), the database throws a SQL syntax error, which is logged and returned to the LLM.

### 24.3 Auditor Role Blocked from Audit Logs in SQL Tool
The `AUDITOR` role has permission to review audit logs in the REST API ([audit.py:L24](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/audit.py#L24)), but `audit_logs` is **omitted from `ALLOWED_TABLES`** in `TextToSQLService`. As a result, Auditors cannot query audit statistics through the Conversational Agent.

### 24.4 Soft-Delete Bypassing in Complex Subqueries
The soft-delete predicate (`documents.is_deleted = false`) is injected only at the top-level `WHERE` clause. Complex nested subqueries generated by an LLM could theoretically inspect soft-deleted records if tables are aliased inside sub-selects.

---

## 25. Missing Information / Capability Gaps

This factual inventory summarizes all missing capabilities:

1. **Missing Relational Columns on `documents`:**
   - No `invoice_number`
   - No `invoice_date`
   - No `due_date`
   - No `vendor_name`
   - No `total_amount` or `grand_total`
   - No `currency`
   - No `payment_status`
2. **Missing Extraction Fields in `extraction_results`:**
   - `due_date` is 0.0% populated.
   - `payment_status`, `outstanding_amount`, `paid_amount`, `balance_due`, and `discount_deadline` do not exist in the extraction taxonomy.
   - Key naming discrepancy: `seller_name` is extracted, but Text-to-SQL prompts expect `vendor_name`.
3. **Missing RAG Chunk Metadata:**
   - No document ownership (`uploaded_by`) stored on chunks.
   - No document taxonomy (`document_type`) stored on chunks.
   - No temporal markers (`invoice_date`, `due_date`) stored on chunks.
   - All filtering requires expensive relational joins to `documents`.
4. **Missing Conversational Services:**
   - No entity linking / document reference resolution service (cannot map `"INV-1001"` to `document_id`).
   - Global Chat is stateless; conversation history is not forwarded across multi-turn interactions.
   - No payment terms NLP interpreter (`"Net 30"` $\to$ +30 days).
   - `vendor_knowledge` table is completely unpopulated (0 rows).

---

## 26. Evidence and Source References

All statements, schema definitions, and statistical findings in this audit report are backed by explicit codebase files and live database records:

### Codebase Source Files
- **SQLAlchemy Models:**
  - `Document`: [backend/app/models/document.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py)
  - `ExtractionResult`: [backend/app/models/extraction_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/extraction_result.py)
  - `DocumentChunk`: [backend/app/models/document_chunk.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py)
  - `User`: [backend/app/models/user.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/user.py)
  - `AuditLog`: [backend/app/models/audit_log.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/audit_log.py)
  - `OCRResult`: [backend/app/models/ocr_result.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py)
  - `ChatSession`, `ChatMessage`: [backend/app/models/chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py)
  - `VendorKnowledge`: [backend/app/models/vendor_knowledge.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/vendor_knowledge.py)
  - `DocumentType`, `DocumentStatus`, `AuditAction`: [backend/app/models/document_enums.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_enums.py)
  - `UserRole`: [backend/app/models/roles.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/roles.py)
- **Services & Repositories:**
  - `TextToSQLService`: [backend/app/services/text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py)
  - `RAGService`: [backend/app/services/rag_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py)
  - `RAGIngestionService`: [backend/app/services/rag_ingestion_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py)
  - `AgentOrchestrator`: [backend/app/rag/agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py)
  - `ChatService`: [backend/app/services/chat_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py)
  - `FinancialCalculator`: [backend/app/rag/financial_calculator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py)
  - `StructureAwareChunker`: [backend/app/rag/chunking.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py)
  - `ChunkRepository`: [backend/app/repositories/chunk_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py)
  - `ChatHistoryRepository`: [backend/app/repositories/chat_history_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py)
  - `DocumentService`: [backend/app/services/document_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py)
  - `FieldSchemas`: [backend/app/extraction/field_schemas.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/extraction/field_schemas.py)
- **Alembic Migrations:**
  - `4cf4fda96099_create_users_table_foundation_.py`
  - `25865efaaa0b_add_documents_table.py`
  - `46222a8b1535_add_ocr_results_table.py`
  - `87d0535e0a9c_add_extraction_results_table.py`
  - `018069fabf68_add_pgvector_document_chunks_and_vendor_.py`
  - `22cf2e444b51_add_tsv_content_and_chat_tables.py`
  - `014cab3b4e0b_add_hnsw_and_doc_id_indexes_on_document_.py`

### Database Inspection Queries Executed
- Information schema table & column definitions: `information_schema.tables`, `information_schema.columns`
- Constraint catalog: `information_schema.table_constraints`, `information_schema.referential_constraints`
- Index definitions: `pg_indexes WHERE schemaname = 'public'`
- Live row counts & null statistics: Executed across all 15 public tables
- JSONB field key analysis: Queried across `extraction_results.fields` and `document_chunks.metadata_json`
