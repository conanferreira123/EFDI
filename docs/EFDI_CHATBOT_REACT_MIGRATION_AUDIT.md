# EFDI Chatbot ReAct Migration & Architecture Audit

**Document Version:** 1.0.0  
**Audit Date:** 2026-09-22  
**Authoritative Migration Target:** [docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd)  
**Database Schema Baseline:** Alembic Head `361bf56d16a1`  
**Audit Mode:** Strict Read-Only Migration & Architecture Verification

---

## 1. Executive Summary

### 1.1 Architectural State & Readiness Verdict
- **Current Architecture:** A hybrid system featuring a deterministic, substring-keyword router for portfolio-wide inquiries ([agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py)) and a direct single-hop RAG retrieval pipeline for document-scoped inquiries ([chat_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py)).
- **Target Architecture:** Dual ReAct agent loops governed by a trusted Python Backend Security Boundary as specified in [EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd):
  - **Global ReAct Agent** (`/api/v1/chat/corpus`): Iterative reasoning over Database / Text-to-SQL Tool, Financial Calculator Tool, and Document RAG Tool.
  - **Document ReAct Agent** (`/api/v1/chat/documents/{id}`): Document ownership access check followed by scoped iterative reasoning over Document RAG Tool and Financial Calculator Tool.
- **Migration Readiness:** **READY WITH PREREQUISITE FIXES**. The underlying domain services (`TextToSQLService`, `RAGService`, `FinancialCalculator`), session/message database persistence models (`ChatSession`, `ChatMessage`), and authentication infrastructure (`get_current_user`, JWT OAuth2 Bearer) are fully implemented and architecturally sound.
- **Major Blockers:**
  1. **Text-to-SQL Table Aliasing & Scoping Defects (`CRIT-01`, `CRIT-02`)**: Identified in the security audit; AST rewriting crashes on SQL table aliases (e.g. `FROM documents d`) and injects invalid AST nodes on child tables (`invoice_line_items`, `vendors`).
  2. **Missing LangChain Ecosystem Dependencies**: The Python virtual environment does not contain `langchain`, `langchain-core`, or any agent framework; LLM interactions currently use raw HTTP calls via `urllib.request`.
- **Major Risks:**
  1. **Reasoning / Chain-of-Thought Leakage**: Risk of intermediate ReAct thoughts or raw JSON tool outputs leaking into the user-facing response if agent output parsing is not strictly separated from the presentation payload.
  2. **ReAct Infinite Loops & Context Window Explosion**: Multi-hop tool iteration without hard step limits (max iterations $= 5$) and context window truncation.

---

## 2. Authoritative Target Architecture

The target architecture is authoritatively defined in [docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/EFDI_CHATBOT_FINAL_ARCHITECTURE.mmd).

```
+---------------------------------------------------------------------------------------------------+
| 1. CLIENT & AUTHENTICATION LAYER                                                                  |
|    User -> HTTP Bearer JWT -> get_current_user -> Trusted Current User Context (user.id, user.role)|
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| 2. BACKEND AUTHORIZATION BOUNDARY (Python Security Gateway - NEVER delegated to LLM)               |
|    Role Policies: FINANCE_ANALYST (own docs), FINANCE_MANAGER (corpus), AUDITOR, ADMIN            |
+---------------------------------------------------------------------------------------------------+
                         |                                                  |
                         v                                                  v
+---------------------------------------------+    +-----------------------------------------------+
| 3. GLOBAL CHATBOT SUBSYSTEM                 |    | 4. DOCUMENT-LEVEL CHATBOT SUBSYSTEM           |
|    POST /api/v1/chat/corpus/messages        |    |    POST /api/v1/chat/documents/{id}/messages  |
|    Global ReAct Agent (Dynamic Loop)        |    |    DocScopeCheck (Ownership / 403)            |
|    - Think -> Select Tool -> Observe        |    |    Document ReAct Agent (Scoped Loop)         |
|    - Multi-Hop Reasoning Loop               |    |    - Think -> Select Tool -> Observe          |
+---------------------------------------------+    +-----------------------------------------------+
         |                  |                 |                      |                  |
         v                  v                 v                      v                  v
+------------------+ +-------------+ +------------------+   +------------------+ +-------------+
| 5.1 Database Tool| |5.2 Calc Tool| |5.3 RAG Tool      |   |5.3 RAG Tool      | |5.2 Calc Tool|
| (Global ONLY)    | |(Global+Doc) | |(Global+Doc)      |   |(Global+Doc)      | |(Global+Doc) |
| - LLM Writer     | |Deterministic| |Hybrid Retrieval  |   |Hybrid Retrieval  | |Deterministic|
| - SQLGlot Check  | |AST Math     | |Dense + Sparse    |   |Dense + Sparse    | |AST Math     |
| - Role Scoping   | |Decimals     | |RRF + Cross-Enc   |   |RRF + Cross-Enc   | |Decimals     |
| - Read-Only Exec | |Date Offsets | |Scoped to User    |   |Scoped to Doc ID  | |Date Offsets |
+------------------+ +-------------+ +------------------+   +------------------+ +-------------+
         |                                    |                      |
         +------------------------------------+----------------------+
                                              |
                                              v
+---------------------------------------------------------------------------------------------------+
| 7. UNIFIED POSTGRESQL 16 DATABASE (Relational Tables + document_chunks pgvector & FTS)            |
+---------------------------------------------------------------------------------------------------+
```

### Key Target Architecture Invariants
1. **Dual Independent Entry Points**:
   - `/api/v1/chat/corpus/messages` hosts the **Global ReAct Agent** with access to all 3 tools (Database, Calculator, RAG).
   - `/api/v1/chat/documents/{id}/messages` hosts the **Document ReAct Agent** with access to 2 tools (Calculator, Document-Scoped RAG). **Text-to-SQL is strictly forbidden in Document Chat.**
2. **Dynamic Tool Selection**: Elimination of all deterministic keyword/substring router heuristics. The LLM dynamically selects tools, observes output, and decides if follow-up actions are required.
3. **Backend Authorization Boundary**: The LLM is NEVER trusted with user identity, user role, or document scoping. All SQL queries and RAG searches are injected with trusted backend constraints derived from JWT authentication.

---

## 3. Current Chatbot Architecture

### 3.1 Discovered Codebase Components

| Component | Current File Location | Primary Class / Function | Architectural Nature | Target Role |
|---|---|---|---|---|
| **Global Router** | [global_chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py#L30-L47) | `send_global_message` | FastAPI Endpoint | Preserve endpoint; route to Global ReAct Agent |
| **Document Router** | [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py#L29-L48) | `send_document_message` | FastAPI Endpoint | Preserve endpoint; route to Document ReAct Agent |
| **Global Orchestrator** | [agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L47-L190) | `AgentOrchestrator` | Deterministic Keyword Router | **REPLACE ENTIRELY** |
| **Document Chat Service**| [chat_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L20-L100) | `ChatService.send_document_message` | Direct Single-Turn RAG Pipeline | **REPLACE PIPELINE WITH REACT AGENT** |
| **Text-to-SQL Service** | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L108-L309) | `TextToSQLService` | SQL Generation & AST Validator | **PRESERVE DOMAIN SERVICE; WRAP AS TOOL** |
| **RAG Service** | [rag_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py#L25-L181) | `RAGService` | Hybrid Retrieval (Dense+Sparse+RRF+Rerank) | **PRESERVE DOMAIN SERVICE; WRAP AS TOOL** |
| **Financial Calculator**| [financial_calculator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py#L14-L96) | `FinancialCalculator` | AST Decimal Precision Engine | **PRESERVE DOMAIN SERVICE; WRAP AS TOOL** |
| **LLM Client** | [llm_client.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/llm_client.py#L32-L123) | `LLMClient` | Raw HTTP Client (`urllib.request`) | **REPLACE / WRAP WITH LANGCHAIN CHAT MODEL** |
| **Session Persistence** | [chat_history_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py#L13-L101) | `ChatHistoryRepository` | DB Repository (`chat_sessions`, `chat_messages`) | **PRESERVE & EXTEND FOR REACT MEMORY** |

---

## 4. Current Deterministic Orchestrator

### 4.1 Detailed Control Flow in `AgentOrchestrator`
- **File:** [backend/app/rag/agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py)
- **Class:** `AgentOrchestrator`
- **Entry Method:** `process_global_query(query, user, session_id)`

```
Incoming Request (query, user)
       |
       +---> 1. Role Check: FINANCE_ANALYST policy check ("scoped" vs "forbidden")
       |
       +---> 2. Session Init: history_repo.get_or_create_global_session(user.id)
       |
       +---> 3. History Append: history_repo.add_message(session_id, role="user", query)
       |
       +---> 4. _plan_tool_execution(query): Static Substring Triggers
       |            |
       |            |---> "how many", "count", "sum", "total spend"... -> use_sql = True
       |            |---> "calculate", "discount on", "%", "minus"...  -> use_calculator = True
       |            |---> "terms", "penalty", "freight", "clause"...   -> use_rag = True
       |            +---> Fallback: if no matches -> use_rag = True
       |
       +---> 5. Sequential Tool Execution:
       |            |
       |            +---> [Step 1] if use_sql:
       |            |         sql_service.generate_and_execute_sql(query, user)
       |            |         Extract matched document IDs from SQL rows
       |            |
       |            +---> [Step 2] if use_calculator:
       |            |         _execute_calculator(query) -> Regex on query string!
       |            |
       |            +---> [Step 3] if use_rag:
       |                      rag_service.retrieve_global(query, user, matched_doc_ids)
       |
       +---> 6. _synthesize_answer(query, tool_results, retrieved_chunks):
       |            Single prompt combining raw SQL rows, calc dict, and chunk text
       |            Calls llm_client._call_mistral_api() or deterministic fallback
       |
       +---> 7. Citations & History Commit:
                    Formats chunk snippets; persists assistant message to chat_messages
```

### 4.2 Architectural Defects of the Current Orchestrator
1. **Keyword/Substring Brittleness (`CONFLICTS WITH TARGET`)**:
   - Queries like *"Compare our standard payment terms with the actual terms in Acme's invoice"* trigger neither SQL nor Calc triggers, falling back blindly to RAG.
   - Queries like *"What is the total of Acme invoices with a 3% early discount?"* trigger SQL and Calc simultaneously, but the calculator parses the original question string with regex instead of the SQL output.
2. **Inability to Perform Multi-Hop Reasoning (`CONFLICTS WITH TARGET`)**:
   - The calculator cannot consume numbers discovered by Text-to-SQL or RAG.
   - Text-to-SQL cannot refine a query based on RAG clause findings.
3. **Monolithic Synthesis (`REQUIRES CHANGE`)**:
   - The LLM does not decide its own actions; it is merely a summarization engine at the end of a hardcoded waterfall pipeline.

---

## 5. TextToSQLService

### 5.1 Service Profile & Capabilities
- **File:** [backend/app/services/text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py)
- **Public API:**
  - `generate_and_execute_sql(natural_language_query: str, user: User) -> Dict[str, Any]`
  - `validate_and_sanitize_sql(raw_sql: str, user: User) -> str`
  - `execute_safe_query(safe_sql: str) -> Dict[str, Any]`
- **Input:** Natural language query string (`str`), authenticated `User` entity.
- **Output:** Structured dictionary:
  ```python
  {
      "sql": str,              # Validated, sanitized, and scoped SQL query
      "row_count": int,        # Number of rows fetched (capped at 100)
      "columns": List[str],    # List of column names
      "rows": List[Dict],      # Array of row records
      "execution_time_ms": float
  }
  ```

### 5.2 Tool Boundary Assessment
- **Status:** **VERIFIED READY AS A DOMAIN SERVICE TO BE WRAPPED AS A TOOL**.
- **Assessment:** `TextToSQLService.generate_and_execute_sql` already encapsulates the entire SQL generation, SQLGlot AST validation, table/column allowlists, read-only transaction execution, and 5-second timeout.
- **Future ReAct Database Tool Interface:**
  - The ReAct agent should pass a natural language query intent (e.g. `{"query": "Total spend per vendor in 2026"}`) to the tool.
  - The backend tool wrapper injects the authenticated `user: User` into `TextToSQLService.generate_and_execute_sql(query, user=trusted_user)`.
  - The tool outputs a clean, formatted Markdown table or compact JSON summary suitable for the ReAct LLM's observation step.
- **Prerequisite Fixes (Security Blockers from Previous Audit):**
  - **`CRIT-01` Table Alias AST Fix**: Must resolve table aliases (e.g. `FROM documents d`) in `validate_and_sanitize_sql` to prevent PostgreSQL runtime errors.
  - **`CRIT-02` Child Table Scoping**: Must add predicate generators for `invoice_line_items`, `vendors`, and `vendor_aliases`.
  - **`HIGH-01` Users Table Allowlist**: Restrict `users` table to `ADMIN`.

---

## 6. RAGService

### 6.1 Service Profile & Capabilities
- **File:** [backend/app/services/rag_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/rag_service.py)
- **Public API:**
  - `retrieve_global(query: str, user: User, document_ids: Optional[List[int]] = None, top_k: Optional[int] = None) -> List[RetrievedChunk]`
  - `retrieve_for_document(document_id: int, query: str, user: User, top_k: Optional[int] = None) -> List[RetrievedChunk]`
- **Retrieval Pipeline:**
  1. Dense vector embedding (`all-MiniLM-L6-v2`, 384 dimensions, cosine distance).
  2. Sparse text search (PostgreSQL `tsvector` with `plainto_tsquery`).
  3. Pre-retrieval SQL authorization scoping (`uploaded_by == user.id` for analysts; non-deleted documents).
  4. Reciprocal Rank Fusion (RRF: $k=60$) fusing Top-30 Dense + Top-30 Sparse $\to$ Top-25 candidates.
  5. Cross-Encoder reranking (`ms-marco-MiniLM-L-6-v2`) selecting Top-5 chunks.
- **Output:** List of `RetrievedChunk` objects containing `chunk_id`, `document_id`, `page_number`, `chunk_type`, `content`, `metadata_json`, `rerank_score`.

### 6.2 Tool Boundary Assessment
- **Status:** **VERIFIED READY AS A DOMAIN SERVICE TO BE WRAPPED AS A TOOL**.
- **Assessment:** RAGService already exposes clean, decoupled retrieval methods. The internal mechanics (pgvector, tsvector, RRF, Cross-Encoder) remain strictly encapsulated inside the service.
- **Future ReAct RAG Tool Interface:**
  - **Global Agent**: Exposes `document_rag_tool(query: str, document_ids: Optional[List[int]] = None)`. Backend automatically injects `user=current_user`.
  - **Document Agent**: Exposes `document_rag_tool(query: str)`. Backend automatically locks `document_id=selected_document_id` and `user=current_user`. The LLM cannot alter `document_id`.
  - **Tool Output to Agent:** Formatted snippet evidence with chunk provenance headers (e.g. `[Chunk 12, Page 2, Section: payment_terms]: "Net 30 days..."`).

---

## 7. FinancialCalculator

### 7.1 Service Profile & Capabilities
- **File:** [backend/app/rag/financial_calculator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/financial_calculator.py)
- **Public API:**
  - `FinancialCalculator.evaluate_expression(expr_str: str) -> Decimal`
  - `FinancialCalculator.calculate_discount(gross_amount, discount_percentage, days_offset, invoice_date=None) -> Dict[str, Any]`
  - `FinancialCalculator.calculate_date_offset(base_date: str, days: int) -> str`
- **Design Highlights:**
  - Completely deterministic Python engine using Python's `ast` parser.
  - Rejects all unauthorized operations (only `Add`, `Sub`, `Mult`, `Div`, unary `-`/`+` permitted).
  - Regex pre-sanitizes input characters to `[\d\.\s\+\-\*\/\(\)]+`.
  - All arithmetic executes via `Decimal` with `ROUND_HALF_UP` precision.
  - Zero database access, zero LLM calls.

### 7.2 Tool Boundary Assessment
- **Status:** **VERIFIED READY AS A DOMAIN SERVICE TO BE WRAPPED AS A TOOL**.
- **Assessment:** In the current orchestrator, `_execute_calculator` attempted to parse arithmetic from the user's natural language string via regex. In ReAct, the LLM itself generates structured tool arguments!
- **Future ReAct Calculator Tool Interface:**
  - Exposes two distinct structured tool actions:
    1. `calculate_expression(expression: str)`: E.g., `"(14500.50 + 3200.00) * 0.18"`.
    2. `calculate_discount(gross_amount: str, discount_percentage: str, days_offset: int, invoice_date: Optional[str] = None)`: E.g., `gross_amount="12500.00", discount_percentage="2.5", days_offset=10`.
  - Returns exact Decimal string observations back to the agent's reasoning loop.

---

## 8. LLM Integration

### 8.1 Current Implementation
- **File:** [backend/app/rag/llm_client.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/llm_client.py)
- **Class:** `LLMClient`
- **Protocol:** Direct synchronous HTTP POST requests using standard library `urllib.request` to `https://api.mistral.ai/v1/chat/completions`.
- **Model:** `settings.EXTRACTION_LLM_MODEL` (default: `mistral-small-2603`).
- **Temperature:** Hardcoded `0.1`, `max_tokens: 1024`.
- **Fallback:** If `MISTRAL_API_KEY` is not set or network fails, executes `_fallback_grounded_synthesis()`.

### 8.2 LangChain Ecosystem Audit
- **Current Dependency Audit:**
  - Verified via `venv\Scripts\python.exe -m pip list` and [requirements.txt](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/requirements.txt):
  - `langchain`: **NOT INSTALLED**
  - `langchain-core`: **NOT INSTALLED**
  - `langchain-community`: **NOT INSTALLED**
  - `langgraph`: **NOT INSTALLED**
  - `langchain-mistralai`: **NOT INSTALLED**
- **Evaluation:** The EFDI codebase currently has **zero LangChain packages**. The ReAct migration requires installing the necessary lightweight LangChain core libraries (`langchain-core`, `langchain`, `langchain-mistralai` or a standard tool-calling wrapper around `ChatMistralAI`).

---

## 9. Chat Endpoints

### 9.1 Global Chat Endpoint
- **Route:** `POST /api/v1/chat/corpus/messages` ([global_chat.py:30-47](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py#L30-L47))
- **Request Schema:** `ChatMessageRequest(message="...")`
- **Current Execution:** `AgentOrchestrator(db).process_global_query(query=payload.message, user=current_user)`
- **Response Schema:** `GlobalChatMessageResponse` ([chat.py (schemas):30-39](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/schemas/chat.py#L30-L39))
  - `session_id: int`
  - `message_id: int`
  - `role: "assistant"`
  - `content: str` (Answer text)
  - `tool_calls: List[Dict[str, Any]]` (Executed tools log)
  - `citations: List[CitationItem]`
  - `execution_time_ms: float`
- **Preservation Status:** **PRESERVE ENDPOINT & RESPONSE SCHEMA**. The endpoint and its Pydantic response contract are already integrated with the frontend. Only the internal orchestrator implementation is replaced by `GlobalReActAgent`.

### 9.2 Document Chat Endpoint
- **Route:** `POST /api/v1/chat/documents/{document_id}/messages` ([chat.py:29-48](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py#L29-L48))
- **Request Schema:** `ChatMessageRequest(message="...")`
- **Current Execution:** `ChatService(db).send_document_message(document_id, user_message=payload.message, user=current_user)`
- **Access Control:** `DocumentService(db).get_for_user(document_id, user)` raises `AuthorizationException` (HTTP 403) if analyst does not own document.
- **Response Schema:** `ChatMessageResponse` ([chat.py (schemas):21-28](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/schemas/chat.py#L21-L28))
  - `session_id: int`
  - `message_id: int`
  - `role: "assistant"`
  - `content: str`
  - `citations: List[CitationItem]`
  - `created_at: str`
- **Preservation Status:** **PRESERVE ENDPOINT, PRE-EXECUTION ACCESS CHECK, & RESPONSE SCHEMA**. Replace the internal single-hop retrieval pipeline inside `ChatService` with `DocumentReActAgent`.

---

## 10. Session & History Model

### 10.1 Current State vs Target Requirements

| Dimension | Current Implementation | Target ReAct Requirement | Migration Delta |
|---|---|---|---|
| **Storage Engine** | PostgreSQL tables `chat_sessions` & `chat_messages` ([chat.py:13-60](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/models/chat.py#L13-L60)) | Same PostgreSQL tables | **Preserve existing database models** |
| **Global Session** | `ChatSession(user_id=X, session_type="GLOBAL", document_id=None)` | Same | **Preserve** |
| **Document Session** | `ChatSession(user_id=X, session_type="DOCUMENT", document_id=doc_id)` | Same | **Preserve** |
| **History Loading** | Loads last 10 messages from `chat_messages` ([chat_service.py:53](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L53)) | Formats last $N$ turns into LangChain `HumanMessage` / `AIMessage` | **Adapt repository output to LangChain messages** |
| **Tool Execution Persistence** | Stored as summary JSON in `chat_messages.tool_calls` column | Store structured tool actions and observations in `chat_messages.tool_calls` | **Preserve schema; enrich JSON payload** |
| **Agent Thought State** | Ephemeral; not stored | Ephemeral; internal thoughts must NEVER be persisted to `chat_messages.content` | **Strict separation of internal trace vs final answer** |

---

## 11. Tool Contract Analysis

```
+-------------------------------------------------------------------------------------------------------------------------+
|                                         REAct AGENT TOOL CONTRACT SPECIFICATION                                         |
+-----------------------------------+-----------------------+-----------------------------+-------------------------------+
| Tool Name                         | Existing Service      | LLM-Controlled Input Schema | Backend-Controlled Injection  |
+-----------------------------------+-----------------------+-----------------------------+-------------------------------+
| database_query_tool               | TextToSQLService      | {                           | - user: User (JWT context)    |
| (Global Agent ONLY)               |                       |   "query": string           | - Read-only transaction       |
|                                   |                       | }                           | - Statement timeout: 5000ms   |
|                                   |                       |                             | - Row limit: <= 100           |
+-----------------------------------+-----------------------+-----------------------------+-------------------------------+
| document_rag_tool                 | RAGService            | Global Agent:               | - user: User (JWT context)    |
| (Global & Document Agents)        |                       | {                           | - Document Agent locks:       |
|                                   |                       |   "query": string,          |     document_id = target_id   |
|                                   |                       |   "document_ids": int[]     | - Pre-retrieval SQL filtering |
|                                   |                       | }                           | - Top-K clamp (default: 5)    |
|                                   |                       | Document Agent:             |                               |
|                                   |                       | {                           |                               |
|                                   |                       |   "query": string           |                               |
|                                   |                       | }                           |                               |
+-----------------------------------+-----------------------+-----------------------------+-------------------------------+
| financial_calculator_tool         | FinancialCalculator   | {                           | - None (pure deterministic    |
| (Global & Document Agents)        |                       |   "action": "eval"|"disc",  |   math engine)                |
|                                   |                       |   "expression": string,     | - Safe AST verification       |
|                                   |                       |   "gross_amount": string,   | - Decimal precision clamp     |
|                                   |                       |   "discount_pct": string,   |                               |
|                                   |                       |   "days_offset": int        |                               |
|                                   |                       | }                           |                               |
+-----------------------------------+-----------------------+-----------------------------+-------------------------------+
```

### 11.1 Proposed Tool Contracts

#### 1. Database Tool (`database_query_tool`)
- **Scope:** Global ReAct Agent ONLY. (Forbidden in Document Chat).
- **LLM Input:** `{"query": "Total invoice amounts grouped by vendor for Q1 2026"}`.
- **Backend Action:** Calls `TextToSQLService.generate_and_execute_sql(query=query, user=trusted_user)`.
- **Tool Observation Returned to Agent:**
  ```markdown
  | vendor_name | total_spend | invoice_count |
  | ACME Corp   | 145250.00   | 12            |
  | Globex Inc  | 89400.50    | 7             |
  (2 rows returned)
  ```

#### 2. Document RAG Tool (`document_rag_tool`)
- **Scope:** Global ReAct Agent (with optional `document_ids`) & Document ReAct Agent (strictly scoped to current `document_id`).
- **LLM Input:** `{"query": "early settlement discount terms and penalty clauses"}`.
- **Backend Action:**
  - In Global Chat: `RAGService.retrieve_global(query=query, user=trusted_user, document_ids=doc_ids, top_k=5)`.
  - In Document Chat: `RAGService.retrieve_for_document(document_id=enforced_doc_id, query=query, user=trusted_user, top_k=5)`.
- **Tool Observation Returned to Agent:**
  ```text
  [Chunk 42, Page 1, Section: payment_terms]: "Payment due within 30 days. A 2% discount applies if settled within 10 days of invoice date."
  [Chunk 45, Page 2, Section: dispute_clause]: "Late payments incur a 1.5% monthly service charge."
  ```

#### 3. Financial Calculator Tool (`financial_calculator_tool`)
- **Scope:** Global & Document ReAct Agents.
- **LLM Input:** `{"expression": "145250.00 * (1 - 0.02)"}` or `{"gross_amount": "145250.00", "discount_pct": "2.0", "days_offset": 10, "invoice_date": "2026-03-01"}`.
- **Backend Action:** Dispatches to `FinancialCalculator.evaluate_expression` or `FinancialCalculator.calculate_discount`.
- **Tool Observation Returned to Agent:**
  ```json
  {"original_gross": "145250.00", "discount_percentage": "2.0%", "discount_amount": "2905.00", "discounted_payable_total": "142345.00", "deadline_date": "2026-03-11"}
  ```

---

## 12. Authorization Boundary Analysis

The authority over security parameters is strictly partitioned between the LLM, the Python backend, and the domain services:

```
+--------------------------------------------------------------------------------------------------+
|                                    AUTHORIZATION BOUNDARIES                                      |
+--------------------------+------------------------------+----------------------------------------+
| Dimension                | LLM / ReAct Agent Control    | Python Backend Security Gateway Control|
+--------------------------+------------------------------+----------------------------------------+
| Authenticated Identity   | ZERO CONTROL                 | Injected from validated JWT Bearer     |
| User Role                | ZERO CONTROL                 | Injected from PostgreSQL User record   |
| Document Ownership Scope | ZERO CONTROL                 | Enforced via SQL AST / RAG joins       |
| Document ID in Doc Chat  | ZERO CONTROL                 | Extracted from URL path; validated 403 |
| SQL Table Allowlists     | Proposes target tables       | Enforced via SQLGlot AST validation    |
| SQL Column Allowlists    | Proposes target columns      | Enforced via SQLGlot AST validation    |
| SQL Mutation Denial      | Can attempt DDL/DML          | Blocked; AST requires exp.Select       |
| SQL Timeout & Isolation  | ZERO CONTROL                 | SET TRANSACTION READ ONLY; 5000ms limit|
| RAG Chunk Access         | Queries semantic intent      | Pre-retrieval SQL filter on user.id    |
| Calculator Parameters    | Proposes math expressions    | Python AST restricts operators & types |
+--------------------------+------------------------------+----------------------------------------+
```

---

## 13. Reasoning / Tool Output Leakage Analysis

### 13.1 Current System Audit
- In [agent_orchestrator.py:286-298](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L286-L298), the current deterministic orchestrator injects raw tool outputs into a synthesis prompt:
  ```python
  prompt = (
      f"{GLOBAL_AGENT_SYSTEM_PROMPT}\n\n"
      f"User Question: {query}\n\n"
      f"Available Tool Evidence:\n{evidence_str}\n\n"
      f"Assistant Answer:"
  )
  ```
- If the LLM generates reasoning prefixes (e.g. *"Thought: The user is asking about spend. Action: database_query_tool. Observation: ... Final Answer: The total spend is $50,000"*), the entire raw string is returned as `content` to the client!
- Furthermore, in the fallback synthesis branch ([agent_orchestrator.py:302-323](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L302-L323)), raw dictionary structures like `Sample data: [{'status': 'VALIDATED', 'count': 12}]` are directly string-concatenated into the user-facing answer.

### 13.2 Required ReAct Architectural Boundary
1. **Strict Separation of Agent State vs Final Answer**:
   - The ReAct agent execution generates intermediate steps: `List[Tuple[AgentAction, str]]` (Thought, Action, Action Input, Observation).
   - These intermediate steps are formatted into the `tool_calls: List[Dict[str, Any]]` field of `GlobalChatMessageResponse` for the frontend's expandable execution badge ([GlobalChatPage.tsx:260-295](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/GlobalChatPage.tsx#L260-L295)).
   - **`content` must contain ONLY the final grounded natural language answer.** Any intermediate `Thought:`, `Action:`, or `Observation:` tokens must be stripped or kept in memory during the ReAct loop.

---

## 14. Multi-Tool Query Analysis

### 14.1 Evaluation of Compound Scenarios

#### Scenario A: Relational Aggregation $\to$ Financial Calculator
- **Query:** *"What is our total spend with Acme Corp in 2026, and what would we save with a 2.5% early payment discount?"*
- **Current Deterministic Orchestrator:**
  - `_plan_tool_execution` detects "total spend" (SQL) and "%" (Calc).
  - Step 1: SQL executes `SELECT SUM(grand_total_amount) FROM invoices WHERE ...` $\to$ returns `$150,000`.
  - Step 2: Calculator executes `_execute_calculator(query)`: Searches `query` for regex amount `(?:on|\$)\d+`. Because the query contains no numeric gross amount, regex matching **fails** (`{"status": "skipped"}`).
  - **Verdict:** **FAILS IN CURRENT SYSTEM.**
- **Target ReAct Agent:**
  - Step 1: `Thought: I need to find the total spend with Acme Corp in 2026 first.`
  - Step 2: `Action: database_query_tool({"query": "Total spend with Acme Corp in 2026"})`.
  - Step 3: `Observation: [{"total_spend": 150000.00}]`.
  - Step 4: `Thought: Now I need to calculate a 2.5% discount on 150,000.00.`
  - Step 5: `Action: financial_calculator_tool({"gross_amount": "150000.00", "discount_pct": "2.5", "days_offset": 10})`.
  - Step 6: `Observation: {"discount_amount": "3750.00", "discounted_payable_total": "146250.00"}`.
  - Step 7: `Thought: I have both the total spend and the discount calculation. I can now form the final answer.`
  - Step 8: `Final Answer: Total spend with Acme Corp in 2026 is $150,000.00. With a 2.5% early payment discount, you would save $3,750.00, resulting in a discounted payable total of $146,250.00.`

#### Scenario B: Unstructured RAG Clause $\to$ Database Validation
- **Query:** *"What are the payment terms on Invoice #INV-9021, and what is its recorded due date in the database?"*
- **Current Deterministic Orchestrator:**
  - Triggers both RAG and SQL, executes them in fixed order, and dumps both results into synthesis. If SQL does not extract the exact invoice number into an ID filter, RAG searches the entire corpus.
- **Target ReAct Agent:**
  - Dispatches RAG to retrieve the terms clause, then queries `payment_obligations` table via SQL to verify the recorded `due_date`, iteratively cross-validating the extraction against business records.

---

## 15. Preserve vs Replace Matrix

| Current Component | File / Location | Action | Architectural Rationale |
|---|---|---|---|
| **Global Chat Endpoint** | `app/routers/global_chat.py` | **PRESERVE** | Endpoint URL, HTTP methods, and Pydantic response contract are already integrated with the UI. |
| **Document Chat Endpoint** | `app/routers/chat.py` | **PRESERVE** | Endpoint URL and document ID path validation are correct and verified. |
| **Document Access Check** | `DocumentService.get_for_user()` | **PRESERVE** | Critical ABAC boundary preventing unauthorized document chat access. |
| **AgentOrchestrator** | `app/rag/agent_orchestrator.py` | **REPLACE** | Replace rigid keyword waterfall with dynamic LangChain ReAct agent loop. |
| **ChatService Document Pipeline** | `app/services/chat_service.py:30-100` | **REPLACE** | Replace single-turn RAG retrieval with scoped Document ReAct Agent loop. |
| **TextToSQLService** | `app/services/text_to_sql_service.py` | **MODIFY (FIX BLOCKERS) & WRAP** | Fix alias (`CRIT-01`) and child table (`CRIT-02`) bugs; wrap public API as LangChain tool. |
| **RAGService** | `app/services/rag_service.py` | **PRESERVE & WRAP** | Encapsulates dense, sparse, RRF, and Cross-Encoder pipelines cleanly; wrap as tool. |
| **FinancialCalculator** | `app/rag/financial_calculator.py` | **PRESERVE & WRAP** | Pure deterministic math engine; wrap as tool with structured Pydantic input schema. |
| **LLMClient** | `app/rag/llm_client.py` | **REPLACE / ADAPT** | Replace raw `urllib.request` with LangChain `ChatMistralAI` or custom LangChain model wrapper. |
| **ChatSession / ChatMessage** | `app/models/chat.py` | **PRESERVE** | Database schema already supports `session_type`, `tool_calls`, `citations`. |
| **ChatHistoryRepository** | `app/repositories/chat_history_repository.py` | **PRESERVE & EXTEND** | Existing persistence methods are sound; add LangChain message list converter. |
| **Frontend Contract** | `frontend/src/services/chat.ts` | **PRESERVE** | Frontend expects `content`, `tool_calls`, `citations`. |

---

## 16. Dependency Analysis

### 16.1 Current Installed Dependencies (Verified via `pip list`)
- Python 3.11+
- `fastapi==0.137.2`, `pydantic==2.13.4`, `SQLAlchemy==2.0.51`, `sqlglot==26.6.0`
- `sentence-transformers==3.4.1`, `pgvector==0.3.6`, `psycopg2-binary==2.9.12`
- **LangChain Packages:** **NONE INSTALLED**

### 16.2 Required Dependencies for ReAct Migration
To implement the target ReAct architecture without bloated dependency trees, the following packages will be required:
1. `langchain-core` (Provides `BaseTool`, `@tool`, `AIMessage`, `HumanMessage`, `SystemMessage`, `ToolMessage`)
2. `langchain` (Provides agent executors and ReAct prompt templates)
3. `langchain-mistralai` (or `httpx` wrapper providing a standard `ChatMistralAI` tool-calling model interface)

---

## 17. Migration Risks & Classifications

| Risk ID | Category | Description | Severity | Mitigation Strategy |
|---|---|---|---|---|
| **RISK-01** | Tool Security | Text-to-SQL alias crash or child table scoping leak | **BLOCKING** | Resolve `CRIT-01` and `CRIT-02` before wiring Text-to-SQL tool to agent. |
| **RISK-02** | Agent Execution | Infinite reasoning loops on ambiguous questions | **HIGH** | Enforce `max_iterations = 5` and hard stop fallback. |
| **RISK-03** | UI / Privacy | Chain-of-Thought or prompt leaking into user response | **HIGH** | Strict separation: return only final synthesis in `content`; tool executions in `tool_calls`. |
| **RISK-04** | Performance | Excessive latency from sequential tool executions | **MEDIUM** | Cache vector queries; set 5-second timeout on SQL execution; clamp Top-K chunks. |
| **RISK-05** | API Drift | Breaking frontend chat contracts | **LOW** | Preserve exact `ChatMessageResponse` and `GlobalChatMessageResponse` shapes. |

---

## 18. ReAct Implementation Plan

The migration will be executed across six structured phases:

```
Phase 1: Security & Service Prerequisite Fixes (Text-to-SQL AST Aliasing & Scoping)
     |
Phase 2: Dependency Installation & LangChain Model Abstraction
     |
Phase 3: Domain Service Tool Wrappers (Database, RAG, Financial Calculator)
     |
Phase 4: Global ReAct Agent Subsystem (/api/v1/chat/corpus)
     |
Phase 5: Document ReAct Agent Subsystem (/api/v1/chat/documents/{id})
     |
Phase 6: Integration Verification, Output Sanitization & Security Testing
```

### Phase 1: Security & Service Prerequisite Fixes
- **Goal:** Resolve `CRIT-01`, `CRIT-02`, and `HIGH-01` in `TextToSQLService`.
- **Files:** [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py)
- **Work:** Update SQLGlot AST rewriting to inspect `table.alias` and bind column predicates to aliases. Add scoping subqueries for `invoice_line_items` and `vendors`. Role-gate `users` table to `ADMIN`.

### Phase 2: Dependency Installation & LangChain Model Abstraction
- **Goal:** Install required LangChain libraries and configure `ChatMistralAI`.
- **Files:** `requirements.txt`, new [app/rag/agent_llm.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_llm.py)
- **Work:** Configure Mistral chat model with tool-calling capabilities, binding `settings.MISTRAL_API_KEY` and fallback handlers.

### Phase 3: Domain Service Tool Wrappers
- **Goal:** Wrap existing domain services as LangChain structured tools with Pydantic schemas.
- **Files:** New `app/rag/tools/database_tool.py`, `app/rag/tools/rag_tool.py`, `app/rag/tools/calculator_tool.py`.
- **Work:** Enforce backend injection of `user: User` and `document_id: int`. Formatted tool observations for agent consumption.

### Phase 4: Global ReAct Agent Subsystem
- **Goal:** Implement portfolio-wide ReAct agent replacing `AgentOrchestrator`.
- **Files:** New `app/rag/global_agent.py`, update [global_chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py).
- **Work:** Bind Database, RAG, and Calculator tools. Implement Thought $\to$ Action $\to$ Observation loop. Output structured `GlobalChatMessageResponse`.

### Phase 5: Document ReAct Agent Subsystem
- **Goal:** Implement document-scoped ReAct agent inside `ChatService`.
- **Files:** New `app/rag/document_agent.py`, update [chat_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py).
- **Work:** Bind Document-Scoped RAG Tool and Calculator Tool (Text-to-SQL excluded). Maintain document ownership security check. Output `ChatMessageResponse`.

### Phase 6: Integration Verification, Output Sanitization & Security Testing
- **Goal:** Execute comprehensive unit, integration, and security test suites.
- **Work:** Verify reasoning leakage protection, multi-hop accuracy, role isolation, and frontend rendering compatibility.

---

## 19. Future Test Strategy

### 19.1 Unit Tests
- **Tool Schemas:** Verify Pydantic validation on valid and invalid arguments for Calculator, RAG, and SQL tools.
- **Calculator Engine:** Verify exact Decimal calculations (rounding, negative amounts, date offsets).
- **Output Sanitization:** Verify that `content` contains only the assistant's final response, with zero leaked `Thought:`, `Action:`, or `Observation:` tokens.

### 19.2 Multi-Tool Integration Tests
- **SQL $\to$ Calculator:** Verify "Total spend on Vendor X with a 3% discount" correctly queries database, feeds amount into calculator, and answers accurately.
- **RAG $\to$ Calculator:** Verify "What is the early settlement discount in document X and how much would we pay on $10,000?" queries RAG, passes percentage to calculator, and answers accurately.
- **SQL $\to$ RAG Compound:** Verify portfolio queries filtering by status and retrieving specific policy clauses.

### 19.3 Authorization & Scoping Tests
- **Analyst Scoping:** Verify `FINANCE_ANALYST` queries only retrieve own documents across both RAG and Text-to-SQL tools.
- **Document Chat Isolation:** Verify Document Agent cannot query other document IDs or invoke Text-to-SQL.
- **Audit Access:** Verify `AUDITOR` can inspect documents without modifying records.

---

## 20. Blockers Before Implementation

### 20.1 MUST FIX BEFORE IMPLEMENTATION (Blockers)
1. **Fix Table Alias Handling in `TextToSQLService` (`CRIT-01`)**:
   - `validate_and_sanitize_sql` must bind predicates to table aliases (e.g. `d.uploaded_by = :user_id`) to prevent fatal PostgreSQL runtime errors.
2. **Implement Authorization Scoping on Child Tables (`CRIT-02`)**:
   - Provide scoping predicates for `invoice_line_items`, `vendors`, and `vendor_aliases`. Guard against generating empty `exp.Where(this=None)`.
3. **Role-Gate `users` Table in `TextToSQLService` (`HIGH-01`)**:
   - Remove `users` from `ALLOWED_TABLES` for non-admin roles to prevent corporate user enumeration.
4. **Install Required LangChain Dependencies**:
   - Add `langchain-core`, `langchain`, and model bindings to project environment.

### 20.2 CAN BE HANDLED DURING IMPLEMENTATION
1. **Tool Schema Pydantic Definitions**: Define clean input/output schemas wrapping the domain services.
2. **Reasoning Stripping & Formatting**: Implement the extraction of final text to `content` and tool logs to `tool_calls`.
3. **Document Chat Calculator Addition**: Bind the existing `FinancialCalculator` to Document Chat.

### 20.3 POST-IMPLEMENTATION HARDENING
1. **Auditor Text-to-SQL Access to `audit_logs`**: Dynamically allow `audit_logs` table for `AUDITOR` and `ADMIN`.
2. **Context Window Compression**: Implement history truncation strategies for long-running sessions.

---

## 21. Final Readiness Assessment

### Verdict: **READY TO PROCEED TO REACT MIGRATION PLANNING & EXECUTION**

The EFDI codebase is thoroughly understood, structurally sound, and cleanly mapped to the target architecture:
- The normalized database schema (`361bf56d16a1`) is fully operational.
- The three core domain services (`TextToSQLService`, `RAGService`, `FinancialCalculator`) provide robust, decoupled logic ready to be wrapped as agent tools.
- The authentication and session persistence models (`chat_sessions`, `chat_messages`) require no schema migrations.
- The path to resolving the Text-to-SQL blockers (`CRIT-01`, `CRIT-02`, `HIGH-01`) is clearly defined and localized to a single service file.

Once the three prerequisite Text-to-SQL fixes and dependency installations are completed in Phase 1, the implementation of the Global and Document ReAct agents can proceed with confidence and architectural integrity.

---
*End of Audit Report.*
