# EFDI Chatbot Codebase Inventory

**Document Version:** 1.0.0  
**Audit Date:** 2026-09-21  
**Target Repository:** Enterprise Financial Document Intelligence (EFDI)  
**Inspection Mode:** READ-ONLY Forensic Codebase Audit (Zero Code, Config, or Schema Modifications)  
**Primary Output File:** `docs/CHATBOT_CODEBASE_INVENTORY.md`

---

## 1. Executive Summary

This document provides a comprehensive, file-by-file forensic inventory of the entire Conversational AI subsystem within the Enterprise Financial Document Intelligence (EFDI) repository. It establishes a definitive map of all frontend components, backend routers, domain services, security layers, data repositories, database models, LLM clients, configuration settings, and automated tests.

### Key Architectural Findings:
1. **Dual Chatbot Subsystems:**
   The repository contains two distinct conversational workflows sharing common underlying infrastructure:
   - **Global AI Assistant (`/api/v1/chat/corpus`):** Portfolio-wide multi-tool conversational assistant that attempts to coordinate Text-to-SQL, Financial Arithmetic, and Hybrid Document RAG across the enterprise corpus.
   - **Document-Level Chat (`/api/v1/chat/documents/{id}`):** Single-document conversational assistant strictly scoped to a single document's OCR chunks, with conversation memory continuity and provenance citations.
2. **Deterministic Orchestration (No Agentic Framework):**
   The global chatbot is driven by a deterministic Python router ([`AgentOrchestrator`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L47)) that evaluates user queries against hardcoded substring trigger lists. Neither LangChain, LangGraph, nor model function calling (`bind_tools`, `tools=`) is installed or utilized.
3. **Strict Separation of SQL Proposal vs. Database Authorization:**
   The Text-to-SQL component uses Mistral to generate raw candidate SQL based on a static text prompt, but relies on a trusted backend AST validation gateway ([`sqlglot`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L97)) to enforce SELECT-only execution, table/column allowlists, read-only transactions, statement timeouts, and programmatic injection of tenant/user authorization predicates (`documents.uploaded_by = <user_id>`).
4. **Clean Decoupling for Future LangChain/LangGraph ReAct Migration:**
   Because all three underlying specialized capabilities (`TextToSQLService`, `RAGService`, `FinancialCalculator`) and the frontend response contracts (`GlobalChatMessageResponse`) are cleanly encapsulated, migrating to a true ReAct agent will involve replacing the orchestrator layer without needing to redesign the database, OCR, classification, or extraction subsystems.

---

## 2. Current Chatbot Architecture

The EFDI Conversational AI architecture is divided into three distinct operational tiers:

```
+---------------------------------------------------------------------------------------------------+
|                                      TIER 1: PRESENTATION (FRONTEND)                              |
|  - Global Chat Page: frontend/src/pages/GlobalChatPage.tsx (Portfolio query & tool badges)       |
|  - Document Chat Tab: frontend/src/components/document-chat.tsx (Single-document Q&A)             |
|  - API Client & Types: frontend/src/services/chat.ts                                              |
|  - Markdown & Math Rendering: frontend/src/components/markdown-renderer.tsx                       |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼ (HTTP JSON REST via Axios/Fetch)
+---------------------------------------------------------------------------------------------------+
|                                      TIER 2: API & ROUTING (FASTAPI)                              |
|  - Global Chat Router: backend/app/routers/global_chat.py                                          |
|  - Document Chat Router: backend/app/routers/chat.py                                              |
|  - Auth & RBAC Guards: backend/app/core/dependencies.py (get_current_user, require_roles)         |
|  - Pydantic Contracts: backend/app/schemas/chat.py                                                |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
|                               TIER 3: ORCHESTRATION & DOMAIN SERVICES                             |
|                                                                                                   |
|  [Global Multi-Tool Orchestrator]                     [Document Chat Coordinator]                 |
|  backend/app/rag/agent_orchestrator.py                backend/app/services/chat_service.py        |
|  (Deterministic keyword triggers & pipeline)          (Document scoping, grounding, citations)   |
|         │                  │                 │                               │                    |
|         ▼                  ▼                 ▼                               ▼                    |
|  +--------------+  +---------------+  +---------------+              +---------------+            |
|  | Text-to-SQL  |  |  Calculator   |  | Document RAG  |              | Document RAG  |            |
|  | Service      |  | Tool          |  | Service       |              | Service       |            |
|  | text_to_sql_ |  | financial_    |  | rag_service.  |              | rag_service.  |            |
|  | service.py   |  | calculator.py |  | py            |              | py            |            |
|  +--------------+  +---------------+  +---------------+              +---------------+            |
|         │                  │                 │                               │                    |
|         ├──────────────────┴─────────────────┼───────────────────────────────┤                    |
|         ▼                                    ▼                               ▼                    |
|  [LLM Client: llm_client.py]        [PostgreSQL + pgvector]        [Cross-Encoder Reranker]       |
|  (Mistral chat completions)         (Hybrid Dense + FTS chunks)    (ms-marco-MiniLM-L-6-v2)       |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Global Chat Execution Flow

The portfolio-wide query path traced through the active codebase:

1. **Frontend Dispatch:** User enters a query on the `/chat` route in [`frontend/src/pages/GlobalChatPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx). Invokes `chatApi.sendGlobalMessage(query)`.
2. **HTTP Endpoint:** `POST /api/v1/chat/corpus/messages` defined in [`backend/app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py#L30).
3. **Authentication:** FastAPI dependency injection calls `get_current_user` ([`dependencies.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py#L28)), which verifies the bearer JWT and fetches the active `User` record from PostgreSQL.
4. **Orchestrator Instantiation:** Router instantiates `AgentOrchestrator(db)` and executes `orchestrator.process_global_query(query, user)`.
5. **Role Gating:** If `user.role == "FINANCE_ANALYST"` and `GLOBAL_CHAT_ANALYST_POLICY == "forbidden"`, raises HTTP 403.
6. **Session & Message Persistence:** Creates or retrieves a `GLOBAL` chat session in `chat_sessions` table and persists the raw user message into `chat_messages` table via `ChatHistoryRepository`. *(Note: Prior messages are NOT retrieved or loaded into model context).*
7. **Rule-Based Tool Planning:** Calls `_plan_tool_execution(query)`. Checks `query.lower()` against hardcoded keyword lists (`sql_triggers`, `calc_triggers`, `rag_triggers`).
8. **Tool Execution Pipeline (Linear, Single-Pass):**
   - **Step 1 (SQL):** If `plan["use_sql"]`, calls `TextToSQLService.generate_and_execute_sql(query, user)`. Generates SQL via Mistral, validates AST and injects `uploaded_by` via `sqlglot`, and executes against PostgreSQL with a 5s statement timeout. Scrapes up to 20 document IDs if present.
   - **Step 2 (Calculator):** If `plan["use_calculator"]`, calls `_execute_calculator(query)`. Parses numbers via regex and calculates Decimal results via `FinancialCalculator`.
   - **Step 3 (RAG):** If `plan["use_rag"]`, calls `RAGService.retrieve_global(query, user, document_ids=matched_doc_ids, top_k=5)`. Runs pgvector dense search + PostgreSQL FTS + RRF + Cross-Encoder reranker.
9. **Final Answer Synthesis:** Calls `_synthesize_answer(query, tool_results, retrieved_chunks)`. Formats all tool outputs into an evidence string and calls Mistral Chat Completions API with `GLOBAL_AGENT_SYSTEM_PROMPT`. (Uses deterministic template string fallback if offline).
10. **Persistence & Response:** Persists assistant turn with JSONB `tool_calls` and `citations`. Commits database transaction and returns `GlobalChatMessageResponse`.

---

## 4. Document Chat Execution Flow

The single-document query path traced through the active codebase:

1. **Frontend Dispatch:** User clicks the **"Ask AI"** tab on a document's detail page (`/documents/:id`) in [`frontend/src/pages/DocumentDetailPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/DocumentDetailPage.tsx#L276), mounting [`frontend/src/components/document-chat.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx). User submits a message via `chatApi.sendDocumentMessage(documentId, text)`.
2. **HTTP Endpoint:** `POST /api/v1/chat/documents/{document_id}/messages` defined in [`backend/app/routers/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py#L29).
3. **Authentication & Authorization:** Calls `get_current_user`. Then `ChatService.send_document_message` calls `DocumentService.get_for_user(document_id, user)`, which verifies document existence, non-deleted status, and ownership (`FINANCE_ANALYST` can only access their own uploads; managers/auditors can access all).
4. **Session & History Fetching:** Retrieves or creates a `DOCUMENT` chat session in `chat_sessions`. Fetches the last 10 messages from `chat_messages` table and extracts the last 6 turns (3 Q&A pairs) to provide conversational continuity.
5. **Document-Scoped RAG Retrieval:** Calls `RAGService.retrieve_for_document(document_id, query, user)`. Restricts dense vector search and sparse FTS strictly to `document_chunks.document_id == document_id`. Fuses via RRF and reranks via Cross-Encoder to top-5 chunks.
6. **Grounded Answer Generation:** Calls `LLMClient.generate_grounded_answer(query, retrieved_chunks, conversation_history)`. Prompts Mistral with `DOCUMENT_GROUNDING_SYSTEM_PROMPT`, the formatted chunk snippets, and the conversation history turns.
7. **Citation Construction & Response:** Formats structured citations with chunk IDs, page numbers, and bounding boxes. Appends assistant response to database and returns `ChatMessageResponse`.

---

## 5. Deterministic Query Orchestrator

The orchestrator is implemented in [`backend/app/rag/agent_orchestrator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py).

### Core Components & Methods:
* **`class AgentOrchestrator` ([Line 47](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L47)):**
  - Constructor takes `db: Session`. Instantiates `TextToSQLService(db)`, `RAGService(db)`, `ChatHistoryRepository(db)`, and accesses `FinancialCalculator` and `LLMClient`.
* **`process_global_query(query, user, session_id)` ([Line 58](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L58)):**
  - Main workflow coordinator: role check, session lookup, tool planning, linear execution, answer synthesis, message persistence.
* **`_plan_tool_execution(query)` ([Line 191](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L191)):**
  - Evaluates `q_lower = query.lower()`:
    - `sql_triggers`: `["how many", "count", "sum", "total spend", "spent with", "average", "status", "validated", "rejected", "approved", "uploaded by", "list all", "show all invoices"]`
    - `calc_triggers`: `["calculate", "discount on", "discounted total", "difference between", "how much is", "percent", "%", "divided by", "minus", "plus", "deadline date"]`
    - `rag_triggers`: `["terms", "conditions", "penalty", "interest", "incoterms", "freight", "delivery", "clause", "dispute", "jurisdiction", "payment window", "early settlement"]`
  - Fallback: `if not (has_sql or has_calc or has_rag): has_rag = True`.
  - Compound detection: `is_compound = (has_sql and has_rag)`.
* **`_execute_calculator(query)` ([Line 226](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L226)):**
  - Extracts percentage, gross amount, and day offsets using `re.search` and dispatches to `FinancialCalculator.calculate_discount` or `evaluate_expression`.
* **`_synthesize_answer(query, tool_results, retrieved_chunks)` ([Line 249](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L249)):**
  - Serializes tool outputs into plain text and invokes `LLMClient._call_mistral_api` with `GLOBAL_AGENT_SYSTEM_PROMPT`. Contains deterministic template string fallbacks.

---

## 6. Database / Text-to-SQL Component

The Text-to-SQL capability is implemented in [`backend/app/services/text_to_sql_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py).

### Core Components & Responsibilities:
* **Static Schema Context ([Lines 76–91](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L76-L91)):**
  Hardcoded text specification describing 5 database tables:
  1. `documents`: `id`, `original_filename`, `document_type`, `status`, `company_code`, `vendor_code`, `validation_status`, `file_size_bytes`, `uploaded_by`, `is_deleted`, `created_at`.
  2. `extraction_results`: `id`, `document_id`, `fields` (JSONB), `overall_confidence`, `created_at`.
  3. `validation_results`: `id`, `document_id`, `is_valid`, `error_count`, `warning_count`, `issues` (JSONB), `created_at`.
  4. `classification_results`: `id`, `document_id`, `predicted_type`, `confidence`, `created_at`.
  5. `users`: `id`, `username`, `email`, `full_name`, `role`.
* **SQL Generation (`generate_and_execute_sql`) ([Line 218](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L218)):**
  Prompts Mistral (`settings.EXTRACTION_LLM_MODEL`) with schema rules. Strips markdown fences. Falls back to `_heuristic_sql_fallback` if the API call crashes.
* **AST Security Validation (`validate_and_sanitize_sql`) ([Line 97](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L97)):**
  Parses query via `sqlglot.parse_one(sql, read="postgres")`:
  - Enforces `isinstance(ast, exp.Select)`.
  - Rejects AST mutation expressions: `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Create`, `Command`.
  - Rejects blacklisted functions: `pg_sleep`, `query_to_xml`, `pg_read_file`, `pg_write_file`, `pg_stat_file`, `version`, `current_setting`, `set_config`, `dblink`, `dblink_exec`.
  - Enforces `ALLOWED_TABLES` allowlist.
  - Enforces `ALLOWED_COLUMNS` allowlist (strictly excluding `users.password_hash`).
  - Clamps `LIMIT <= 100`.
* **Programmatic Authorization Injection ([Lines 149–187](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L149-L187)):**
  If `user.role == "FINANCE_ANALYST"`, forcibly modifies AST WHERE clause to append `documents.uploaded_by = <user.id> AND documents.is_deleted = false`. For other roles, appends `documents.is_deleted = false`.
* **Safe Execution (`execute_safe_query`) ([Line 195](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L195)):**
  Uses `engine.connect()`, issues `SET TRANSACTION READ ONLY;`, `SET LOCAL statement_timeout = '5000ms';`, and fetches at most 100 records.

---

## 7. RAG Component

The RAG subsystem is distributed across ingestion, embedding, storage, retrieval, and reranking modules.

### Functional Breakdown:

#### A. RAG Ingestion & Chunking (Indexing Phase)
* [`backend/app/rag/chunking.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py): `StructureAwareChunker` divides document OCR output into typed chunks: `HEADER`, `LINE_ITEMS`, `SUMMARY`, `TERMS`.
* [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py): `RAGIngestionService` orchestrates background chunking and vector storage upon document OCR completion.

#### B. Dense & Sparse Storage
* [`backend/app/models/document_chunk.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py): `DocumentChunk` model mapped to PostgreSQL table `document_chunks`. Holds 384-dim vector (`Vector(384)`) and generated `tsv_content` (`TSVECTOR`).
* [`backend/app/rag/embeddings.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/embeddings.py): `EmbeddingService` singleton using `sentence-transformers/all-MiniLM-L6-v2`.

#### C. Hybrid Retrieval & Reranking (Retrieval Phase)
* [`backend/app/repositories/chunk_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py):
  - `search_vector_for_document` / `search_fts_for_document`: Scoped to `document_id`.
  - `search_vector_global` / `search_fts_global`: Corpus-wide search with in-database authorization filters (`_apply_authorization_predicates`).
* [`backend/app/rag/reranker.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/reranker.py): `RerankerService` singleton using `cross-encoder/ms-marco-MiniLM-L-6-v2`. Reranks hybrid RRF candidate chunks against query text.
* [`backend/app/services/rag_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py): `RAGService` orchestrates the 5-stage hybrid pipeline: Dense Top-30 + Sparse Top-30 $\to$ RRF ($k=60$) $\to$ Top-25 Candidates $\to$ Cross-Encoder $\to$ Top-5 Chunks.

#### D. Chatbot Integration
* [`backend/app/services/chat_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py): Document-level chat integration.
* [`backend/app/rag/agent_orchestrator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py): Global assistant multi-tool integration.

---

## 8. Financial Calculator Component

The financial calculator is implemented in [`backend/app/rag/financial_calculator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py).

### Core Components & Behavior:
* **Class:** `FinancialCalculator` (all `@classmethod` utilities).
* **`evaluate_expression(expr_str: str) -> Decimal` ([Line 25](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py#L25)):**
  - Parses arithmetic expressions into an AST via `ast.parse(clean_expr, mode="eval")`.
  - Evaluates binary operators (`+`, `-`, `*`, `/`) recursively using Python `Decimal` with `ROUND_HALF_UP` quantization to `0.01`.
  - Rejects unsafe characters, function calls, and unauthorized AST nodes.
* **`calculate_discount(...)` ([Line 59](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py#L59)):**
  - Computes early settlement discounts: `discount_amount = gross * (pct / 100)`, `discounted_total = gross - discount_amount`.
  - Computes calendar payment deadline using `datetime + timedelta(days=days_offset)`.
* **Execution Nature:**
  - 100% deterministic arithmetic. No LLM estimation.
  - Currently invoked strictly via regex parameter extraction in `AgentOrchestrator._execute_calculator`. Cannot receive outputs from SQL or RAG.

---

## 9. LLM Infrastructure

The LLM client is implemented in [`backend/app/rag/llm_client.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/llm_client.py).

### LLM Call Inventory Across Chatbot Components:

| # | File & Function | Purpose | Model / Config | Prompt Used | Direct Tool Calling? |
|---|---|---|---|---|---|
| **1** | [`text_to_sql_service.py:L232`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L232)<br>`generate_and_execute_sql` | Translate natural language question into raw SELECT SQL. | `settings.EXTRACTION_LLM_MODEL` (Mistral) via `LLMClient._call_mistral_api` | System: *"You output only valid PostgreSQL SELECT queries."*<br>User: `SCHEMA_CONTEXT` + user query. | **NO.** Returns plain text SQL string. |
| **2** | [`agent_orchestrator.py:L295`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L295)<br>`_synthesize_answer` | Synthesize final portfolio answer from accumulated tool outputs. | `settings.EXTRACTION_LLM_MODEL` (Mistral) via `LLMClient._call_mistral_api` | System: `GLOBAL_AGENT_SYSTEM_PROMPT`<br>User: Query + concatenated tool results evidence string. | **NO.** Returns markdown text. |
| **3** | [`chat_service.py:L64`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L64)<br>`send_document_message` | Generate strictly grounded answer for single-document chat. | `settings.EXTRACTION_LLM_MODEL` (Mistral) via `LLMClient.generate_grounded_answer` | System: `DOCUMENT_GROUNDING_SYSTEM_PROMPT` with chunk context.<br>Messages: Past 3 Q&A pairs + current query. | **NO.** Returns markdown text with citations. |

### Low-Level API Payload (`LLMClient._call_mistral_api`):
```python
payload = {
    "model": self.model_name,
    "messages": messages,
    "temperature": 0.1,
    "max_tokens": 1024,
}
```
* Uses standard library `urllib.request`.
* Does **not** pass `tools`, `tool_choice`, or schema definitions.
* Expects only text at `choices[0]["message"]["content"]`.

---

## 10. Authentication and Authorization

### Authentication Modules:
* [`backend/app/core/security.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/security.py): Handles password hashing via `bcrypt` and JWT encoding/decoding via `python-jose`.
* [`backend/app/core/dependencies.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py): `get_current_user` extracts JWT token, validates signature and expiration, queries `UserRepository`, and returns active `User`.

### Authorization & Access Control Modules:
* **Global Chat Policy Gate ([`agent_orchestrator.py:L68`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L68)):** Enforces `settings.GLOBAL_CHAT_ANALYST_POLICY`.
* **Document Chat Ownership Gate ([`document_service.py:L45`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L45)):** Ensures analysts cannot open chat sessions on documents uploaded by others.
* **SQL AST Authorization Gate ([`text_to_sql_service.py:L149`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L149)):** Forcibly injects `documents.uploaded_by = user.id` and `documents.is_deleted = false` into the query AST.
* **RAG Retrieval Authorization Gate ([`chunk_repository.py:L106`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py#L106)):** Injects SQL predicates into vector and full-text searches before execution.

---

## 11. Chat Persistence

Chat sessions and messages are persisted in PostgreSQL via SQLAlchemy models in [`backend/app/models/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py).

### Data Models:
* **`ChatSession` (`chat_sessions` table):**
  - `id: int` (Primary Key)
  - `user_id: int` (FK `users.id`, CASCADE)
  - `session_type: str` (`"DOCUMENT"` or `"GLOBAL"`)
  - `document_id: Optional[int]` (FK `documents.id`, CASCADE, nullable)
  - `title: Optional[str]`
* **`ChatMessage` (`chat_messages` table):**
  - `id: int` (Primary Key)
  - `session_id: int` (FK `chat_sessions.id`, CASCADE)
  - `role: str` (`"user"`, `"assistant"`, `"system"`, `"tool"`)
  - `content: str` (Message body)
  - `tool_calls: Optional[JSONB]` (Array of executed tool records)
  - `citations: Optional[JSONB]` (Array of retrieved chunk citations)

### Data Access Repository:
* [`backend/app/repositories/chat_history_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py):
  - `get_or_create_document_session(user_id, document_id)`
  - `get_or_create_global_session(user_id)`
  - `add_message(session_id, role, content, tool_calls, citations)`
  - `get_session_history(session_id, limit)`
  - `clear_session_history(session_id)`

### Database Migration:
* [`backend/alembic/versions/22cf2e444b51_add_tsv_content_and_chat_tables.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/alembic/versions/22cf2e444b51_add_tsv_content_and_chat_tables.py): Migration that created `chat_sessions` and `chat_messages` tables.

---

## 12. Frontend Chatbot Code

The frontend implementation is located in `frontend/src/`.

### File Inventory & Roles:
* [`frontend/src/services/chat.ts`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/chat.ts):
  - TypeScript interfaces: `CitationItem`, `ToolCallItem`, `ChatMessageResponse`, `GlobalChatMessageResponse`, `ChatHistoryItem`.
  - API client methods: `sendDocumentMessage`, `getDocumentHistory`, `clearDocumentHistory`, `sendGlobalMessage`, `getGlobalHistory`, `clearGlobalHistory`.
* [`frontend/src/pages/GlobalChatPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx):
  - Global AI Assistant page mounted at route `/chat`.
  - Features suggested prompt chips, conversation stream, tool execution badges accordion, SQL code preview, citations accordion, and conversation reset.
* [`frontend/src/components/document-chat.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx):
  - Single-document chat assistant embedded inside the "Ask AI" tab on `DocumentDetailPage`.
* [`frontend/src/components/markdown-renderer.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/markdown-renderer.tsx):
  - Renders markdown responses using `react-markdown` and `remark-gfm` with styled tables, code blocks, lists, and typography.
* [`frontend/src/App.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/App.tsx):
  - Declares the `/chat` route mapped to `<GlobalChatPage />`.
* [`frontend/src/layouts/Sidebar.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/layouts/Sidebar.tsx):
  - Provides the navigation link: `{ to: "/chat", label: "Ask AI", icon: Sparkles }`.

---

## 13. Database Models and Repositories Used by Chatbot

| Model File | Table Name | Repositories Accessing It | Primary Usage in Chatbot | Read/Write |
|---|---|---|---|---|
| [`models/user.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/user.py) | `users` | `UserRepository` | Authentication (`get_current_user`), user ID/role lookup, Text-to-SQL `SCHEMA_CONTEXT` | Read |
| [`models/document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py) | `documents` | `DocumentRepository`, `TextToSQLService`, `ChunkRepository` | Document metadata, authorization checks (`uploaded_by`), Text-to-SQL target table, RAG document joins | Read |
| [`models/document_chunk.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py) | `document_chunks` | `ChunkRepository` | Vector cosine search (`embedding`), Full-Text Search (`tsv_content`), chunk content retrieval | Read |
| [`models/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) | `chat_sessions` | `ChatHistoryRepository` | Conversation session tracking for global and document chats | Read / Write |
| [`models/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) | `chat_messages` | `ChatHistoryRepository` | Storing user questions, assistant answers, `tool_calls` JSONB, and `citations` JSONB | Read / Write |
| [`models/extraction_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/extraction_result.py) | `extraction_results` | Direct raw SQL queries generated by Text-to-SQL | Text-to-SQL target table for structured financial fields (`grand_total_amount`, `vendor_name`, etc.) | Read |
| [`models/validation_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/validation_result.py) | `validation_results` | Direct raw SQL queries generated by Text-to-SQL | Text-to-SQL target table for validation errors, warnings, and document validity | Read |
| [`models/classification_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/classification_result.py) | `classification_results` | Direct raw SQL queries generated by Text-to-SQL | Text-to-SQL target table for predicted document types (POI vs NPOI) | Read |
| [`models/ocr_result.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/ocr_result.py) | `ocr_results` | `OCRResultRepository` | Read by `RAGIngestionService` during background chunking of newly OCR'd documents | Read |

---

## 14. Tests

Automated tests directly validating chatbot and underlying retrieval/SQL behavior:

| Test File | Component Tested | Test Type | Key Scenarios Covered | Migration Preservation Note |
|---|---|---|---|---|
| [`backend/tests/test_global_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_global_agent.py) | `AgentOrchestrator`, `FinancialCalculator`, API routes | Integration & Behavioral | - SQL intent routing<br>- Calculator intent routing<br>- Compound query coordination<br>- Role policies (`scoped` vs `forbidden`)<br>- Full API endpoint verification | **UPDATE ORCHESTRATION TESTS:** Assertions verifying tool execution and answer contracts must be preserved; internal routing mocks should be updated to test LangGraph. |
| [`backend/tests/test_chat_document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_chat_document.py) | `ChatService`, `/api/v1/chat/documents/*` | Integration & Behavioral | - Authorized analyst chat with citations<br>- Unauthorized analyst 403 Forbidden<br>- Manager cross-document access<br>- Chat history and clear<br>- Negative evidence grounding refusal | **MUST PRESERVE UNCHANGED:** Document chat is fully functional and decoupled from global agent migration. |
| [`backend/tests/test_sql_safety.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_sql_safety.py) | `TextToSQLService.validate_and_sanitize_sql` | Unit & Security | - Rejection of DML (`UPDATE`, `DELETE`)<br>- Rejection of DDL (`DROP`, `ALTER`)<br>- Unauthorized table rejection<br>- `users.password_hash` column rejection<br>- Forbidden function rejection (`pg_sleep`)<br>- Hard row limit enforcement<br>- Automatic analyst authorization predicate injection | **MUST PRESERVE 100%:** These security tests validate core database safety invariants that the future ReAct agent tool must satisfy. |
| [`backend/tests/test_rag_retrieval.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_rag_retrieval.py) | `RAGService`, `ChunkRepository`, `RerankerService` | Integration & Unit | - Dense vector search accuracy<br>- Native PostgreSQL FTS accuracy<br>- Reciprocal Rank Fusion ($k=60$)<br>- Cross-Encoder reranker score filtering<br>- Pre-retrieval SQL authorization scoping | **MUST PRESERVE 100%:** Validates hybrid retrieval quality and in-database authorization. |
| [`backend/tests/test_rag_ingestion.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_rag_ingestion.py) | `RAGIngestionService`, `StructureAwareChunker` | Integration | - Chunking structure detection<br>- Embedding dimension validation (384-dim)<br>- Idempotent re-ingestion | **MUST PRESERVE 100%:** Validates chunk creation required by RAG. |

---

## 15. Configuration and Dependencies

### 1. Configuration Settings ([`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py)):
* **LLM & Provider:**
  - `LLM_PROVIDER: str = "mistral"`
  - `EXTRACTION_LLM_MODEL: str = "mistral-small-2603"`
  - `MISTRAL_API_KEY: str | None = None`
  - `MISTRAL_API_BASE: str = "https://api.mistral.ai/v1"`
* **RAG & Embeddings:**
  - `RAG_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"`
  - `RAG_RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"`
  - `RAG_EMBEDDING_DIM: int = 384`
  - `RAG_DENSE_TOP_K: int = 30`
  - `RAG_SPARSE_TOP_K: int = 30`
  - `RAG_RRF_K: int = 60`
  - `RAG_RERANK_CANDIDATES: int = 25`
  - `RAG_FINAL_TOP_K: int = 5`
  - `RAG_RERANKER_MIN_SCORE: float = -3.0`
* **Role Policies:**
  - `GLOBAL_CHAT_ANALYST_POLICY: str = "scoped"` (`"scoped"` or `"forbidden"`)

### 2. Backend Dependencies ([`backend/requirements.txt`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements.txt)):
* `fastapi==0.137.2`, `uvicorn==0.49.0` (Web framework)
* `SQLAlchemy==2.0.51`, `psycopg2-binary==2.9.12`, `alembic==1.18.4` (Relational persistence)
* `pgvector==0.3.6` (PostgreSQL vector extension client)
* `sqlglot==26.6.0` (SQL AST parsing, validation, and rewriting)
* `sentence-transformers==3.4.1` (Dense embeddings and Cross-Encoder reranking)
* `pydantic==2.13.4`, `pydantic-settings==2.14.1` (Validation and settings)
* `python-jose==3.5.0`, `bcrypt==5.0.0` (JWT and auth)

### 3. Frontend Dependencies ([`frontend/package.json`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/package.json)):
* `react==19.0.0`, `react-dom==19.0.0`
* `react-router-dom==7.3.0`
* `react-markdown==10.1.0`, `remark-gfm==4.0.1` (Markdown formatting)
* `lucide-react==1.16.0` (Icons for tools and citations)

---

## 16. Complete File Inventory

| Category | File Path | Primary Class / Function | Responsibility | Called By | Calls | Migration Relevance |
|---|---|---|---|---|---|---|
| **A. Core Chatbot Orchestration** | [`backend/app/rag/agent_orchestrator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py) | `AgentOrchestrator` | Deterministic keyword routing, linear tool execution, and final answer synthesis. | `global_chat.py` | `TextToSQLService`, `RAGService`, `FinancialCalculator`, `LLMClient`, `ChatHistoryRepository` | **LIKELY REPLACE** (Target of LangGraph ReAct migration) |
| **A. Core Chatbot Orchestration** | [`backend/app/services/chat_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py) | `ChatService` | Single-document chat workflow, authorization verification, conversational history feeding, and citation generation. | `routers/chat.py` | `DocumentService`, `RAGService`, `LLMClient`, `ChatHistoryRepository` | **MUST PRESERVE** |
| **A. Core Chatbot Orchestration** | [`backend/app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py) | `send_global_message`, `get_global_history`, `clear_global_history` | FastAPI router for portfolio-wide Global AI Assistant. | Frontend client | `AgentOrchestrator`, `ChatHistoryRepository`, `get_current_user` | **WRAPPER NEEDED / PRESERVE API** |
| **A. Core Chatbot Orchestration** | [`backend/app/routers/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py) | `send_document_message`, `get_document_history`, `clear_document_history` | FastAPI router for single-document conversational assistant. | Frontend client | `ChatService`, `get_current_user` | **MUST PRESERVE** |
| **A. Core Chatbot Orchestration** | [`backend/app/schemas/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/schemas/chat.py) | `GlobalChatMessageResponse`, `ChatMessageResponse`, `CitationItem` | Pydantic schemas defining request/response contracts for chat. | Routers | Pydantic BaseModel | **MUST PRESERVE** (Frontend API Contract) |
| **B. Database / Text-to-SQL** | [`backend/app/services/text_to_sql_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py) | `TextToSQLService` | Converts text to SQL via LLM, parses AST via `sqlglot`, validates security, injects authorization, and executes. | `AgentOrchestrator` | `LLMClient`, `sqlglot`, PostgreSQL engine | **MUST PRESERVE CORE / WRAP AS TOOL** |
| **C. RAG** | [`backend/app/services/rag_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py) | `RAGService` | 5-stage hybrid retrieval (vector + FTS + RRF + Cross-Encoder reranking). | `AgentOrchestrator`, `ChatService` | `EmbeddingService`, `RerankerService`, `ChunkRepository` | **MUST PRESERVE / WRAP AS TOOL** |
| **C. RAG** | [`backend/app/repositories/chunk_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py) | `ChunkRepository` | Vector cosine search (`pgvector`) and Full-Text Search with in-database authorization. | `RAGService`, `RAGIngestionService` | SQLAlchemy Session, `DocumentChunk`, `Document` | **MUST PRESERVE** |
| **C. RAG** | [`backend/app/rag/embeddings.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/embeddings.py) | `EmbeddingService` | Generates 384-dimensional dense vectors using `all-MiniLM-L6-v2`. | `RAGService`, `RAGIngestionService` | `sentence_transformers.SentenceTransformer` | **MUST PRESERVE** |
| **C. RAG** | [`backend/app/rag/reranker.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/reranker.py) | `RerankerService` | Semantic candidate reranking using `ms-marco-MiniLM-L-6-v2`. | `RAGService` | `sentence_transformers.CrossEncoder` | **MUST PRESERVE** |
| **C. RAG** | [`backend/app/rag/chunking.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py) | `StructureAwareChunker` | Chunking document OCR text into typed structural segments. | `RAGIngestionService` | Python regex and layout parsing | **NOT CHATBOT-SPECIFIC** (Ingestion pipeline) |
| **C. RAG** | [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py) | `RAGIngestionService` | Background indexing of document OCR text into vector store. | `OCRService` | `StructureAwareChunker`, `EmbeddingService`, `ChunkRepository` | **NOT CHATBOT-SPECIFIC** (Ingestion pipeline) |
| **D. Financial Calculator** | [`backend/app/rag/financial_calculator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py) | `FinancialCalculator` | Deterministic Decimal arithmetic and calendar discount deadline calculation. | `AgentOrchestrator` | Python `Decimal`, `ast.parse` | **MUST PRESERVE / WRAP AS TOOL** |
| **E. LLM Infrastructure** | [`backend/app/rag/llm_client.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/llm_client.py) | `LLMClient` | Mistral chat completion client with prompt formatting and fallbacks. | `TextToSQLService`, `AgentOrchestrator`, `ChatService` | `urllib.request`, Mistral API | **VERIFY BEFORE CHANGE** (May be augmented with LangChain ChatMistralAI) |
| **F. Authentication / Authorization** | [`backend/app/core/dependencies.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py) | `get_current_user`, `require_roles` | Decodes bearer JWT and retrieves active user record from database. | Routers | `UserRepository`, `security.py` | **MUST PRESERVE** |
| **F. Authentication / Authorization** | [`backend/app/core/security.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/security.py) | `decode_access_token` | JWT token signature verification and cryptographic decoding. | `dependencies.py` | `python-jose` | **MUST PRESERVE** |
| **G. Chat Persistence** | [`backend/app/models/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) | `ChatSession`, `ChatMessage` | SQLAlchemy entities mapping chat sessions, messages, tool calls, and citations. | `ChatHistoryRepository` | SQLAlchemy Base | **MUST PRESERVE** |
| **G. Chat Persistence** | [`backend/app/repositories/chat_history_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py) | `ChatHistoryRepository` | CRUD access for chat sessions and message histories. | `AgentOrchestrator`, `ChatService`, `routers` | `ChatSession`, `ChatMessage` | **MUST PRESERVE** |
| **H. Frontend Chatbot** | [`frontend/src/services/chat.ts`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/chat.ts) | `chatApi`, TypeScript Interfaces | Client-side API functions and data models for chat communication. | Pages and components | `apiRequest` | **MUST PRESERVE** |
| **H. Frontend Chatbot** | [`frontend/src/pages/GlobalChatPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx) | `GlobalChatPage` | Interactive UI for Global AI Assistant with tool-call inspection badges. | React Router | `chatApi`, `MarkdownRenderer` | **MUST PRESERVE** |
| **H. Frontend Chatbot** | [`frontend/src/components/document-chat.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx) | `DocumentChatAssistant` | Interactive UI for single-document chat tab. | `DocumentDetailPage.tsx` | `chatApi`, `MarkdownRenderer` | **MUST PRESERVE** |
| **H. Frontend Chatbot** | [`frontend/src/components/markdown-renderer.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/markdown-renderer.tsx) | `MarkdownRenderer` | Renders markdown tables, code blocks, and formatted text in chat bubbles. | `GlobalChatPage`, `document-chat` | `react-markdown`, `remark-gfm` | **MUST PRESERVE** |
| **I. Models / Repositories** | [`backend/app/models/document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py) | `Document` | Document metadata, status, file hashes, and ownership (`uploaded_by`). | All subsystems | SQLAlchemy Base | **NOT CHATBOT-SPECIFIC** |
| **I. Models / Repositories** | [`backend/app/models/document_chunk.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py) | `DocumentChunk` | Semantic chunk text, vectors, tsvectors, and metadata. | `ChunkRepository` | `pgvector.sqlalchemy.Vector` | **MUST PRESERVE** |
| **I. Models / Repositories** | [`backend/app/services/document_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py) | `DocumentService` | Document access control and permission enforcement. | `ChatService` | `DocumentRepository` | **NOT CHATBOT-SPECIFIC** |
| **J. Tests** | [`backend/tests/test_global_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_global_agent.py) | Test suite | End-to-end tests for global agent, tool routing, and API endpoints. | `pytest` | `AgentOrchestrator`, `TestClient` | **UPDATE ORCHESTRATION TESTS** |
| **J. Tests** | [`backend/tests/test_chat_document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_chat_document.py) | Test suite | End-to-end tests for document chat, grounding, and citations. | `pytest` | `ChatService`, `TestClient` | **MUST PRESERVE** |
| **J. Tests** | [`backend/tests/test_sql_safety.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_sql_safety.py) | Test suite | Unit tests for AST security validation and authorization injection. | `pytest` | `TextToSQLService` | **MUST PRESERVE** |
| **J. Tests** | [`backend/tests/test_rag_retrieval.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_rag_retrieval.py) | Test suite | Integration tests for hybrid retrieval, RRF, and Cross-Encoder reranking. | `pytest` | `RAGService` | **MUST PRESERVE** |
| **K. Configuration** | [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py) | `Settings` | Environment variables, model names, and retrieval hyperparameters. | Entire backend | `pydantic_settings` | **MUST PRESERVE** |

---

## 17. Dependency Graph

```
[Browser / User]
       │
       ▼
[frontend/src/pages/GlobalChatPage.tsx]  ──►  [frontend/src/components/markdown-renderer.tsx]
       │
       ▼
[frontend/src/services/chat.ts]
       │ (HTTP POST /api/v1/chat/corpus/messages)
       ▼
[backend/app/routers/global_chat.py]  ◄──  [backend/app/core/dependencies.py] (get_current_user)
       │                                                    │
       ▼                                                    ▼
[backend/app/rag/agent_orchestrator.py]            [backend/app/repositories/user_repository.py]
  ├──► [backend/app/repositories/chat_history_repository.py]
  │         └──► [backend/app/models/chat.py] (ChatSession, ChatMessage)
  │
  ├──► [backend/app/services/text_to_sql_service.py]
  │         ├──► [backend/app/rag/llm_client.py] (Mistral raw SELECT SQL generation)
  │         ├──► [sqlglot] (AST parsing, table/column allowlist, authorization injection)
  │         └──► [PostgreSQL Connection] (Read-only, 5000ms timeout)
  │                   ├── documents
  │                   ├── extraction_results
  │                   ├── validation_results
  │                   └── classification_results
  │
  ├──► [backend/app/rag/financial_calculator.py]
  │         └──► Python Decimal / ast.parse (Exact arithmetic)
  │
  ├──► [backend/app/services/rag_service.py]
  │         ├──► [backend/app/rag/embeddings.py] (all-MiniLM-L6-v2)
  │         ├──► [backend/app/repositories/chunk_repository.py]
  │         │         └──► [backend/app/models/document_chunk.py] (pgvector + FTS)
  │         └──► [backend/app/rag/reranker.py] (ms-marco-MiniLM-L-6-v2)
  │
  └──► [backend/app/rag/llm_client.py]
            └──► Mistral API (Final answer synthesis via GLOBAL_AGENT_SYSTEM_PROMPT)
```

---

## 18. Active vs Legacy / Unused Code

### 1. Active Code on Active Chatbot Execution Paths:
* `AgentOrchestrator` (`process_global_query`, `_plan_tool_execution`, `_synthesize_answer`, `_execute_calculator`)
* `TextToSQLService` (`generate_and_execute_sql`, `validate_and_sanitize_sql`, `execute_safe_query`)
* `RAGService` (`retrieve_global`, `retrieve_for_document`, `_reciprocal_rank_fusion`)
* `FinancialCalculator` (`calculate_discount`, `evaluate_expression`)
* `ChatService` (`send_document_message`, `get_document_history`, `clear_document_history`)
* `ChatHistoryRepository` (`get_or_create_global_session`, `add_message`, `get_session_history`)
* `LLMClient` (`_call_mistral_api`, `generate_grounded_answer`)
* `GlobalChatPage.tsx`, `document-chat.tsx`, `chat.ts`

### 2. Related Infrastructure Not on Active Query Path (Ingestion Only):
* `RAGIngestionService` and `StructureAwareChunker`: Crucial for populating `document_chunks` during OCR, but **not** executed during live conversational query resolution.
* `OCRService` and `ExtractionService`: Upstream document processing pipelines that populate `ocr_results` and `extraction_results`.

### 3. Legacy / Incomplete Implementations:
* **Stateless Global Memory:** While `chat_messages` are recorded to the database by `AgentOrchestrator`, `process_global_query` **never queries past messages back out of the database**. Global chat runs completely stateless between turns.
* **`TextToSQLService._heuristic_sql_fallback`:** Contains 3 static SQL queries used only if the Mistral API call crashes offline.
* **`LLMClient._fallback_grounded_synthesis`:** Deterministic string formatter used when `MISTRAL_API_KEY` is missing or the external API call fails.

---

## 19. Files Likely to Be Replaced / Preserved in Future Migration

### A. Files Likely to Be Replaced:
* [`backend/app/rag/agent_orchestrator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py): The entire deterministic query orchestrator, keyword trigger lists, and static pipeline execution will be replaced by a LangGraph StateGraph ReAct agent.

### B. Files That Require Tool Wrappers:
* [`backend/app/services/text_to_sql_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py): Core AST parsing and authorization logic must be preserved, but wrapped into a LangChain `StructuredTool` (e.g. `database_query_tool`).
* [`backend/app/services/rag_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py): Core hybrid retrieval and reranking logic must be preserved, but wrapped into a LangChain `StructuredTool` (e.g. `document_rag_tool`).
* [`backend/app/rag/financial_calculator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py): Arithmetic functions must be preserved, but wrapped into a LangChain `StructuredTool` with a Pydantic argument schema so the LLM can invoke it with structured parameters instead of fragile regex parsing.

### C. Files That Must Remain Preserved:
* [`backend/app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py): The HTTP endpoint and request/response signature must remain identical to maintain frontend compatibility.
* [`backend/app/schemas/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/schemas/chat.py): `GlobalChatMessageResponse` must remain unchanged so the frontend UI can seamlessly render the ReAct agent's intermediate tool calls and citations.
* [`frontend/src/services/chat.ts`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/chat.ts) & [`frontend/src/pages/GlobalChatPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx): The frontend is already designed to render arrays of tool calls and citations; zero frontend changes are required.

---

## 20. Files That Must Not Be Modified as Part of Chatbot Migration

The following files represent shared core infrastructure that lies strictly outside the scope of the chatbot orchestrator migration:

1. **Authentication & Identity:**
   - `backend/app/core/dependencies.py`
   - `backend/app/core/security.py`
   - `backend/app/models/user.py`
   - `backend/app/repositories/user_repository.py`
   *(Reason: Shared by all document upload, review, approval, and management routes).*
2. **Document Pipeline & Core Models:**
   - `backend/app/models/document.py`
   - `backend/app/models/document_enums.py`
   - `backend/app/models/ocr_result.py`
   - `backend/app/models/extraction_result.py`
   - `backend/app/models/validation_result.py`
   - `backend/app/models/classification_result.py`
   - `backend/app/services/document_service.py`
   - `backend/app/services/ocr_service.py`
   - `backend/app/services/extraction_service.py`
   - `backend/app/services/validation_service.py`
   - `backend/app/services/workflow_service.py`
   *(Reason: Core OCR, extraction, reconciliation, and approval business logic must not be disrupted).*
3. **Database Base & Session Management:**
   - `backend/app/database/session.py`
   - `backend/app/database/base.py`
   - `backend/alembic/*`
   *(Reason: Shared database connection pooling and transaction lifecycle).*

---

## 21. Open Questions / Ambiguities

1. **Table Aliasing in AST Rewriting:**
   In [`text_to_sql_service.py:L156-159`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L156-L159), the authorization predicate is parsed as:
   `documents.uploaded_by = {user.id} AND documents.is_deleted = false`.
   If the LLM introduces a table alias (e.g. `SELECT COUNT(*) FROM documents d`), PostgreSQL throws a query error: `invalid reference to FROM-clause entry for table "documents"`. The future tool wrapper must ensure alias-aware AST modification.
2. **Global Chat Conversational Memory Context:**
   Should the upcoming ReAct agent load previous turns from `chat_messages` into its prompt context? Currently, Document Chat loads 6 turns, but Global Chat loads zero turns.
3. **Prompt Pronoun Ownership Semantics:**
   When a user asks *"How many documents have I uploaded?"*, how should the ReAct database tool handle the first-person pronoun? The system prompt must instruct the model that user ownership predicates are attached automatically by the security gateway, so it should query `documents` without generating invalid pseudo-variables like `CURRENT_USER.id`.

---

## 22. Exact Files and Functions Inspected

1. [`backend/app/rag/agent_orchestrator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py) (`AgentOrchestrator`, `process_global_query`, `_plan_tool_execution`, `_execute_calculator`, `_synthesize_answer`)
2. [`backend/app/services/text_to_sql_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py) (`TextToSQLService`, `generate_and_execute_sql`, `validate_and_sanitize_sql`, `execute_safe_query`, `_heuristic_sql_fallback`)
3. [`backend/app/services/rag_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py) (`RAGService`, `retrieve_global`, `retrieve_for_document`, `_reciprocal_rank_fusion`)
4. [`backend/app/services/rag_ingestion_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_ingestion_service.py) (`RAGIngestionService`, `ingest_document`, `ingest_document_async`)
5. [`backend/app/services/chat_service.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py) (`ChatService`, `send_document_message`, `get_document_history`, `clear_document_history`)
6. [`backend/app/rag/financial_calculator.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py) (`FinancialCalculator`, `calculate_discount`, `evaluate_expression`, `_eval_ast_node`)
7. [`backend/app/rag/llm_client.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/llm_client.py) (`LLMClient`, `_call_mistral_api`, `generate_grounded_answer`, `format_context`)
8. [`backend/app/rag/chunking.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/chunking.py) (`StructureAwareChunker`, `chunk_document`)
9. [`backend/app/rag/embeddings.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/embeddings.py) (`EmbeddingService`, `generate_embeddings`, `generate_query_embedding`)
10. [`backend/app/rag/reranker.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/reranker.py) (`RerankerService`, `rerank`, `RetrievedChunk`)
11. [`backend/app/repositories/chunk_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py) (`ChunkRepository`, `search_vector_global`, `search_fts_global`, `_apply_authorization_predicates`)
12. [`backend/app/repositories/chat_history_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py) (`ChatHistoryRepository`, `get_or_create_global_session`, `get_or_create_document_session`, `add_message`, `get_session_history`)
13. [`backend/app/repositories/user_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/user_repository.py) (`UserRepository`, `get_by_username`, `get_by_id`)
14. [`backend/app/repositories/document_repository.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/document_repository.py) (`DocumentRepository`, `get_by_id`)
15. [`backend/app/routers/global_chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py) (`send_global_message`, `get_global_history`, `clear_global_history`)
16. [`backend/app/routers/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py) (`send_document_message`, `get_document_history`, `clear_document_history`)
17. [`backend/app/schemas/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/schemas/chat.py) (`GlobalChatMessageResponse`, `ChatMessageResponse`, `CitationItem`, `ChatMessageRequest`)
18. [`backend/app/models/chat.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py) (`ChatSession`, `ChatMessage`)
19. [`backend/app/models/document_chunk.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document_chunk.py) (`DocumentChunk`)
20. [`backend/app/models/document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/document.py) (`Document`)
21. [`backend/app/models/user.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/user.py) (`User`)
22. [`backend/app/models/roles.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/roles.py) (`UserRole`)
23. [`backend/app/core/dependencies.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py) (`get_current_user`, `require_roles`)
24. [`backend/app/core/security.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/security.py) (`decode_access_token`, `create_access_token`)
25. [`backend/app/core/config.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py) (`Settings`)
26. [`frontend/src/services/chat.ts`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/chat.ts) (`chatApi`, types)
27. [`frontend/src/pages/GlobalChatPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx) (`GlobalChatPage`)
28. [`frontend/src/components/document-chat.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx) (`DocumentChatAssistant`)
29. [`frontend/src/components/markdown-renderer.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/markdown-renderer.tsx) (`MarkdownRenderer`)
30. [`frontend/src/pages/DocumentDetailPage.tsx`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/DocumentDetailPage.tsx) (`DocumentDetailPage`)
31. [`backend/tests/test_global_agent.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_global_agent.py)
32. [`backend/tests/test_chat_document.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_chat_document.py)
33. [`backend/tests/test_sql_safety.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_sql_safety.py)
34. [`backend/tests/test_rag_retrieval.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_rag_retrieval.py)
35. [`backend/tests/test_rag_ingestion.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_rag_ingestion.py)
