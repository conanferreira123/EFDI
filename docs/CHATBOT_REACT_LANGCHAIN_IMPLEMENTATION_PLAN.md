# EFDI Global Chatbot — Current Architecture Analysis & ReAct Migration Plan

**Document Version:** 1.0.0  
**Classification:** Architectural Investigation & Migration Blueprint  
**Status:** READ-ONLY ARCHITECTURAL AUDIT — ZERO CODE MUTATIONS  
**Target Subsystem:** Conversational AI, Global AI Assistant, and RAG Subsystem (`backend/app/rag/`, `backend/app/routers/`, `frontend/src/`)

---

## 1. Executive Summary

This document presents a comprehensive, forensic architectural analysis of the Enterprise Financial Document Intelligence (EFDI) Conversational AI Subsystem (both Document-Level Chat and Global AI Assistant) and details a production-grade migration plan to transition the Global AI Assistant from its current **rule-based, keyword-matched, single-pass pipeline** to a **true LangChain/LangGraph-based ReAct (Reasoning + Acting) / tool-calling agent**.

### Key Investigation Findings:
1. **Tool Selection Is Deterministic and Rule-Based:** The current orchestrator (`AgentOrchestrator` in `backend/app/rag/agent_orchestrator.py`) decides which tools to execute using case-insensitive substring matching against three hardcoded Python lists of keyword triggers (`sql_triggers`, `calc_triggers`, `rag_triggers`). The LLM plays zero role in routing or deciding which tools to call.
2. **The System Is Not an LLM-Agent:** The application is **not** a true ReAct or tool-calling agent. There is no agentic loop, no `bind_tools`, no tool schema passed to Mistral, no iterative observation-action step, and no `AgentExecutor` or LangGraph state machine.
3. **Execution Is Static and Monolithic:** Tools are executed in a fixed, sequential waterfall order (`use_sql` $\rightarrow$ `use_calculator` $\rightarrow$ `use_rag`). Tool outputs are collected into a dictionary and concatenated as raw text blocks into a final prompt for single-turn answer synthesis.
4. **SQL Generation Uses AST Validation with Decoupled Authorization:** `TextToSQLService` uses Mistral (`mistral-small-2603`) to generate raw PostgreSQL SELECT statements from natural language. Crucially, the authenticated user context is **not** passed into the LLM prompt. Instead, security is enforced post-generation via `sqlglot` AST parsing, which validates table/column allowlists, enforces `LIMIT <= 100`, and injects authorization predicates (`documents.uploaded_by = user.id` and `documents.is_deleted = false`) for `FINANCE_ANALYST` users.
5. **The Calculator Uses Brittle Regex:** Numerical and mathematical parameters for `FinancialCalculator` are extracted from the raw user query string using regular expressions rather than structured LLM argument generation.
6. **Zero LangChain/LangGraph Dependencies:** Neither `langchain`, `langchain-core`, `langchain-community`, `langchain-mistralai`, nor `langgraph` is installed in the repository. The LLM integration is an internal, synchronous wrapper using standard library `urllib.request`.
7. **Clean Frontend Contract:** The frontend (`frontend/src/pages/GlobalChatPage.tsx`) already renders structured `tool_calls` (with tool badges, execution summaries, SQL code blocks, and JSON result inspection) and `citations` (with chunk provenance and bounding box references). The target architecture can preserve this exact API contract.

---

## 2. Chatbot Code Inventory

The conversational capabilities span both backend and frontend. Below is the complete inventory of all chatbot-related files in the repository:

| File Path | Subsystem Layer | Purpose & Key Classes/Functions | Connects To |
|:---|:---|:---|:---|
| `backend/app/routers/global_chat.py` | API / Router | Exposes `/api/v1/chat/corpus` (`messages`, `history`, `clear`). Role-based access enforcement. | `AgentOrchestrator`, `ChatHistoryRepository`, `get_current_user` |
| `backend/app/routers/chat.py` | API / Router | Exposes `/api/v1/chat/documents/{id}` (`messages`, `history`, `clear`). Scoped document chat. | `ChatService`, `get_current_user` |
| `backend/app/rag/agent_orchestrator.py` | Orchestration | `AgentOrchestrator`: keyword routing (`_plan_tool_execution`), tool dispatching, regex calculator execution, answer synthesis. | `TextToSQLService`, `RAGService`, `FinancialCalculator`, `LLMClient`, `ChatHistoryRepository` |
| `backend/app/services/text_to_sql_service.py` | SQL / Security | `TextToSQLService`: LLM SQL generation, `validate_and_sanitize_sql` via `sqlglot` AST validation, tenant predicate injection, read-only 5s execution. | `LLMClient`, PostgreSQL `engine`, `sqlglot` |
| `backend/app/services/rag_service.py` | RAG Retrieval | `RAGService`: hybrid retrieval (`retrieve_global`, `retrieve_for_document`), Reciprocal Rank Fusion (`_reciprocal_rank_fusion`), Cross-Encoder reranking. | `ChunkRepository`, `EmbeddingService`, `CrossEncoderReranker` |
| `backend/app/services/chat_service.py` | Document Chat Service | `ChatService`: single-document conversational workflow, authorization check via `DocumentService`, grounded synthesis. | `DocumentService`, `RAGService`, `ChatHistoryRepository`, `LLMClient` |
| `backend/app/rag/financial_calculator.py` | Calculator Tool | `FinancialCalculator`: deterministic financial math using `Decimal(0.01)`, AST arithmetic evaluation (`evaluate_expression`), discount deadlines (`calculate_discount`). | Standard library `ast`, `decimal`, `datetime` |
| `backend/app/rag/llm_client.py` | LLM Integration | `LLMClient`: custom synchronous client calling Mistral Chat Completions via `urllib.request`. Grounded synthesis prompts and deterministic fallback. | Mistral API (`https://api.mistral.ai/v1`) |
| `backend/app/rag/reranker.py` | RAG Reranking | `CrossEncoderReranker`: reranks candidate chunks using `cross-encoder/ms-marco-MiniLM-L-6-v2`. | `sentence_transformers.CrossEncoder` |
| `backend/app/rag/embeddings.py` | RAG Embeddings | `EmbeddingService`: computes 384-dimensional dense vectors using `sentence-transformers/all-MiniLM-L6-v2`. | `sentence_transformers.SentenceTransformer` |
| `backend/app/rag/chunking.py` | RAG Chunking | `StructureAwareChunker`: chunks layout-reconstructed OCR text into typed sections (HEADER, LINE_ITEMS, SUMMARY, TERMS). | `OCRResult.full_text` |
| `backend/app/services/rag_ingestion_service.py` | RAG Ingestion | `RAGIngestionService`: processes documents post-OCR, generates chunks, embeddings, FTS tsvectors, and commits to DB. | `ChunkRepository`, `DocumentRepository` |
| `backend/app/models/chat.py` | Persistence Models | SQLAlchemy entities: `ChatSession` (DOCUMENT, GLOBAL), `ChatMessage` (`role`, `content`, `tool_calls` JSONB, `citations` JSONB). | PostgreSQL `chat_sessions`, `chat_messages` |
| `backend/app/models/document_chunk.py` | Persistence Models | SQLAlchemy entity: `DocumentChunk` with pgvector `embedding` (384-dim) and `tsv_content` (tsvector). | PostgreSQL `document_chunks` |
| `backend/app/repositories/chat_history_repository.py` | Persistence Repo | `ChatHistoryRepository`: session lifecycle management, appending turns, retrieving history, clearing history. | `ChatSession`, `ChatMessage` |
| `backend/app/repositories/chunk_repository.py` | Persistence Repo | `ChunkRepository`: dense pgvector search, sparse FTS (`websearch_to_tsquery`), in-database RBAC predicate injection. | `DocumentChunk`, `Document` |
| `backend/app/schemas/chat.py` | Schemas | Pydantic models: `ChatMessageRequest`, `ChatMessageResponse`, `GlobalChatMessageResponse`, `CitationItem`, `ChatHistoryItem`. | FastAPI request/response validation |
| `backend/app/core/config.py` | Configuration | Environment settings: `EXTRACTION_LLM_MODEL`, `MISTRAL_API_KEY`, `GLOBAL_CHAT_ANALYST_POLICY`, RAG hyperparameters. | `pydantic_settings` |
| `frontend/src/services/chat.ts` | Frontend API | TypeScript API client: `chatApi` (`sendGlobalMessage`, `getGlobalHistory`, `clearGlobalHistory`, document methods) and interfaces (`ToolCallItem`, `CitationItem`). | Backend `/api/v1/chat/*` |
| `frontend/src/pages/GlobalChatPage.tsx` | Frontend UI | React page: multi-tool chat interface, prompt chips, tool execution accordions, citation drawers, markdown rendering. | `frontend/src/services/chat.ts` |
| `frontend/src/components/document-chat.tsx` | Frontend UI | Slide-over drawer for single-document interactive Q&A. | `frontend/src/services/chat.ts` |
| `backend/tests/test_global_agent.py` | Automated Tests | Pytest test suite covering SQL routing, calculator routing, compound orchestration, RBAC scoping, and API endpoints. | Backend test suite |
| `backend/tests/test_sql_safety.py` | Automated Tests | Pytest test suite verifying AST validation, DDL/DML rejection, allowlists, and RBAC injection. | `TextToSQLService` |

---

## 3. Current End-to-End Architecture

### Architectural Flow Diagram

```
+-----------------------------------------------------------------------------------+
|                                 FRONTEND (React)                                  |
|  GlobalChatPage.tsx  --->  chatApi.sendGlobalMessage(query) in services/chat.ts   |
+------------------------------------------+----------------------------------------+
                                           | HTTP POST /api/v1/chat/corpus/messages
                                           v
+-----------------------------------------------------------------------------------+
|                                BACKEND API ROUTER                                 |
|  routers/global_chat.py: send_global_message()                                    |
|  - Authenticates user via get_current_user (JWT)                                  |
|  - Instantiates AgentOrchestrator(db)                                             |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                         AGENT ORCHESTRATOR (Static Pipeline)                      |
|  rag/agent_orchestrator.py: process_global_query()                                 |
|                                                                                   |
|  1. RBAC Policy Check (FINANCE_ANALYST policy == 'forbidden' -> HTTP 403)        |
|  2. Get/Create Global ChatSession & Persist User Message                          |
|  3. _plan_tool_execution(query) -> Keyword trigger substring checks               |
+--------------------+---------------------+--------------------+-------------------+
                     |                     |                    |
     [if use_sql]    |   [if use_calc]     |    [if use_rag]    |
                     v                     v                    v
+-----------------------+ +-----------------------+ +-----------------------------+
| TextToSQLService      | | FinancialCalculator   | | RAGService                  |
| - Mistral raw SQL gen | | - Regex parses query  | | - Dense Vector (Top-30)     |
| - sqlglot AST parsing | | - Decimal arithmetic  | | - Sparse FTS (Top-30)       |
| - RBAC injection      | | - Early discount calc | | - RRF Fusion (Top-25)       |
| - Read-only 5s exec   | |                       | | - Cross-Encoder (Top-5)     |
+-----------+-----------+ +-----------+-----------+ +--------------+--------------+
            |                         |                            |
            +-------------------------+----------------------------+
                                      | tool_results dict & retrieved_chunks
                                      v
+-----------------------------------------------------------------------------------+
|                        GROUNDED ANSWER SYNTHESIS                                  |
|  rag/agent_orchestrator.py: _synthesize_answer()                                  |
|  - Formats tool results and retrieved chunks into text evidence                   |
|  - Calls LLMClient._call_mistral_api() (or deterministic fallback)                |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                        PERSISTENCE & RESPONSE                                     |
|  - HistoryRepo.add_message(role="assistant", tool_calls=..., citations=...)       |
|  - db.commit()                                                                    |
|  - Return GlobalChatMessageResponse JSON                                          |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                        FRONTEND RENDERING                                         |
|  - GlobalChatPage.tsx updates message state                                       |
|  - Collapsible accordion for ToolCallItem (SQL, row counts, calc results)         |
|  - Collapsible accordion for CitationItem (Document ID, page, chunk snippet)      |
+-----------------------------------------------------------------------------------+
```

---

## 4. Current Tool Selection Mechanism

### A. Classification of Decision Logic
Tool selection is **100% hardcoded, deterministic rule-based keyword matching**. No LLM, no LangChain classifier, and no ML model is involved in determining which tools are chosen.

### B. Exact Location of Decision Logic
The routing logic is located in `backend/app/rag/agent_orchestrator.py`, inside the private method `AgentOrchestrator._plan_tool_execution(self, query: str) -> Dict[str, bool]`:

```python
# Lines 191-224 of backend/app/rag/agent_orchestrator.py
def _plan_tool_execution(self, query: str) -> Dict[str, bool]:
    """Determine which tool(s) are required to satisfy query intent."""
    q_lower = query.lower()

    sql_triggers = [
        "how many", "count", "sum", "total spend", "spent with", "average", "status",
        "validated", "rejected", "approved", "uploaded by", "list all", "show all invoices",
    ]
    calc_triggers = [
        "calculate", "discount on", "discounted total", "difference between", "how much is",
        "percent", "%", "divided by", "minus", "plus", "deadline date",
    ]
    rag_triggers = [
        "terms", "conditions", "penalty", "interest", "incoterms", "freight",
        "delivery", "clause", "dispute", "jurisdiction", "payment window", "early settlement",
    ]

    has_sql = any(t in q_lower for t in sql_triggers)
    has_calc = any(t in q_lower for t in calc_triggers)
    has_rag = any(t in q_lower for t in rag_triggers)

    # Default fallback: if no specific triggers match, use RAG for semantic answering
    if not (has_sql or has_calc or has_rag):
        has_rag = True

    # Check for compound query (e.g. SQL + RAG)
    is_compound = (has_sql and has_rag)

    return {
        "use_sql": has_sql,
        "use_calculator": has_calc,
        "use_rag": has_rag,
        "is_compound": is_compound,
    }
```

### C. Decision Logic Analysis
1. Substring matching is executed over `query.lower()`.
2. Any match sets the respective boolean flag (`has_sql`, `has_calc`, `has_rag`) to `True`.
3. If no keywords match in any list, the system falls back to `has_rag = True`.
4. If both `has_sql` and `has_rag` are `True`, `is_compound` is set to `True`.
5. The boolean dictionary is returned to `process_global_query()`, which executes an `if` statement block for each tool sequentially.

### D. LLM Role in Tool Routing
The LLM has **no role** in tool routing. The LLM is invoked only **after** tools have executed (to synthesize a text response from pre-collected outputs) or **inside** `TextToSQLService` (to write SQL syntax once the rule router has already decided to run SQL).

---

## 5. Is the Current System a Real ReAct Agent?

### Verdict: **NO**

The current implementation is **not** an LLM-driven tool-calling or ReAct agent.

### Verification Matrix:

| ReAct / Tool-Calling Characteristic | Present in Current Codebase? | Verification Evidence |
|:---|:---|:---|
| LangChain `@tool` decorator | ❌ NO | Grep for `@tool` yielded 0 matches across the entire repo. |
| LangChain `StructuredTool` / `BaseTool` | ❌ NO | Grep for `StructuredTool`, `BaseTool` yielded 0 matches. |
| Model `bind_tools()` | ❌ NO | `LLMClient` uses raw `urllib.request` without tool binding. |
| Mistral Tool Calling (`tools`, `tool_choice`) | ❌ NO | `_call_mistral_api` sends only `{"model", "messages", "temperature", "max_tokens"}`. |
| Native `tool_calls` generation by LLM | ❌ NO | Mistral never returns `tool_calls`; the application builds `tool_calls_record` manually. |
| `AgentExecutor` / `create_react_agent` | ❌ NO | No LangChain agent runners exist in the repository. |
| LangGraph State Graph / Cycles | ❌ NO | No state graphs, loops, or recursion limits exist. |
| Observation $\rightarrow$ Thought $\rightarrow$ Action Loop | ❌ NO | Tools are executed once in a static linear pass. |
| Intermediate Step Reasoning | ❌ NO | The model never inspects a tool output to decide the next step. |

### What the Current System Actually Is:
The system is a **Hardcoded Keyword-Based Dispatch Router** connected to **Synchronous Python Domain Services**, followed by **Single-Turn Grounded LLM Response Generation**.

---

## 6. Current Multi-Tool / Iterative Execution Capability

To distinguish between availability of multiple tools and true agentic multi-tool execution, we evaluated the seven operational capabilities:

| Capability | Supported? | Forensic Code Finding |
|:---|:---|:---|
| 1. Multiple tools exist | ✅ YES | Three tools exist: Database Query, Financial Calculator, Document RAG. |
| 2. Multiple tools can execute in one request | ✅ YES | If multiple keyword triggers match, multiple `if` blocks execute in one HTTP request. |
| 3. The LLM chooses multiple tools | ❌ NO | Tool flags are set purely by substring keyword matching against `query.lower()`. |
| 4. The LLM calls tools sequentially | ❌ NO | The sequence is hardcoded in Python: SQL first, Calculator second, RAG third. |
| 5. Tool results are returned to the LLM iteratively | ❌ NO | Tool results are collected in memory and passed all at once to the final synthesis prompt. |
| 6. The LLM decides the next tool based on prior results | ❌ NO | If SQL fails or returns unexpected data, the orchestrator cannot pivot or invoke another tool. |
| 7. Dynamic loop termination | ❌ NO | There is no loop. The execution terminates after the fixed sequence of `if` blocks completes. |

### Compound Query Execution in Current Code:
The only cross-tool coupling currently implemented is a manual Python handoff in `agent_orchestrator.py`:
```python
# Lines 100-110 of backend/app/rag/agent_orchestrator.py
if sql_res.get("rows"):
    extracted_ids = [r["id"] for r in sql_res["rows"] if "id" in r and isinstance(r["id"], int)]
    if not extracted_ids:
        extracted_ids = [r["document_id"] for r in sql_res["rows"] if "document_id" in r and isinstance(r["document_id"], int)]
    if extracted_ids:
        matched_doc_ids = extracted_ids[:20]

# Lines 130-140:
if plan.get("use_rag"):
    scoped_ids = matched_doc_ids if plan.get("is_compound") and matched_doc_ids else None
    rag_chunks = self.rag_service.retrieve_global(query=query, user=user, document_ids=scoped_ids, top_k=5)
```
While this allows RAG to be scoped to document IDs returned by SQL, the logic is hardcoded in Python and only works if SQL returns columns named `id` or `document_id`.

---

## 7. Current SQL Generation Architecture

The Text-to-SQL subsystem is implemented in `backend/app/services/text_to_sql_service.py`.

### A. SQL Generation Flow

```
User NL Query
     │
     ▼
TextToSQLService.generate_and_execute_sql()
     │
     ▼ LLM Call (Mistral via LLMClient._call_mistral_api)
     │ System: "You output only valid PostgreSQL SELECT queries."
     │ Prompt: Database Schema Context + User Question (No User Identity)
     │
     ▼ Raw SQL String (e.g. "SELECT COUNT(*) FROM documents WHERE status = 'VALIDATED'")
     │
     ▼ TextToSQLService.validate_and_sanitize_sql()
     │ 1. AST Parsing via sqlglot.parse_one(clean_sql, read="postgres")
     │ 2. Enforce isinstance(ast, exp.Select) -> Rejects INSERT, UPDATE, DELETE, DROP, ALTER
     │ 3. Check AST nodes against FORBIDDEN_FUNCTIONS (pg_sleep, query_to_xml, etc.)
     │ 4. Validate all tables against ALLOWED_TABLES
     │ 5. Validate all columns against ALLOWED_COLUMNS (password_hash strictly excluded)
     │ 6. Inject Authorization Predicate:
     │    - If FINANCE_ANALYST: injects documents.uploaded_by = user.id AND documents.is_deleted = false
     │    - If Manager/Auditor/Admin: injects documents.is_deleted = false
     │ 7. Enforce LIMIT <= 100
     │
     ▼ Safe Parameterized SQL String
     │
     ▼ TextToSQLService.execute_safe_query()
     │ Engine connection context:
     │ - SET TRANSACTION READ ONLY;
     │ - SET LOCAL statement_timeout = '5000ms';
     │ - conn.execute(text(safe_sql))
     │
     ▼ Row Fetch (fetchmany(100))
     │ Return dict: {sql, row_count, columns, rows, execution_time_ms}
```

### B. Detailed Security Evaluation
* **AST Validation:** Enforced via `sqlglot==26.6.0`. Any syntax error or non-SELECT statement raises `SQLSecurityException`.
* **Allowlists:**
  * `ALLOWED_TABLES`: `documents`, `extraction_results`, `validation_results`, `classification_results`, `users`.
  * `ALLOWED_COLUMNS`: Explicitly defined per table. Specifically, `users.password_hash` is omitted.
* **Authorization Decoupling:** The authenticated user is **never** passed to the LLM generating the SQL. The LLM cannot be prompted to bypass tenant isolation because authorization predicates are injected directly into the AST by Python code before database submission.
* **Timeout & Transaction Safety:** Every execution explicitly issues `SET TRANSACTION READ ONLY;` and `SET LOCAL statement_timeout = '5000ms';`.
* **SQL Error Masking Flaw:** In `agent_orchestrator.py`, when `generate_and_execute_sql` raises an exception, the orchestrator sets `tool_results["database_query"] = {"error": str(sql_err)}`. However, during `_synthesize_answer`, the synthesis logic checks:
  ```python
  sql_data.get('rows', [])
  ```
  Since `'rows'` is missing, it evaluates to `[]`. The error message is not formatted into the context for Mistral, leading the model to hallucinate or report that "no records exist" rather than explaining that the database query failed.

---

## 8. Current RAG Architecture

The Document RAG capability is implemented in `backend/app/services/rag_service.py` and supported by `ChunkRepository`, `EmbeddingService`, and `CrossEncoderReranker`.

### A. Technical Characteristics
* **Ingestion Source:** Grounded on `OCRResult.full_text` generated after OCR table and layout reconstruction.
* **Chunking Strategy:** `StructureAwareChunker` creates typed chunks: `HEADER`, `LINE_ITEMS`, `SUMMARY`, `TERMS`.
* **Dense Retrieval:** Generates 384-dimensional embeddings via `sentence-transformers/all-MiniLM-L6-v2`. Computes cosine distance in PostgreSQL using `pgvector` (`DocumentChunk.embedding.cosine_distance(query_vector)`), fetching Top-30 candidates.
* **Sparse Retrieval:** Native PostgreSQL Full-Text Search using `websearch_to_tsquery('english', query)` against `DocumentChunk.tsv_content`, ranked by `ts_rank_cd`, fetching Top-30 candidates.
* **Rank Fusion:** Reciprocal Rank Fusion (RRF) with constant $k=60$:
  $$RRF\_Score(d) = \sum_{m \in \{dense, sparse\}} \frac{1}{60 + \text{rank}_m(d)}$$
  Produces Top-25 candidate chunks.
* **Cross-Encoder Reranking:** Evaluates the candidate pairs using `cross-encoder/ms-marco-MiniLM-L-6-v2`, returning the Top-5 most relevant chunks.
* **In-Database Authorization Scoping:** `ChunkRepository._apply_authorization_predicates()` joins `Document` and applies:
  ```python
  predicates = [Document.is_deleted.is_(False)]
  if user.role == UserRole.FINANCE_ANALYST.value:
      predicates.append(Document.uploaded_by == user.id)
  if document_ids is not None:
      predicates.append(Document.id.in_(document_ids) if document_ids else Document.id == -1)
  ```
  Unauthorized document chunks never enter Python process memory.

---

## 9. Current Financial Calculator Architecture

Implemented in `backend/app/rag/financial_calculator.py`.

### A. Capabilities & Implementation
* **Exact Arithmetic:** Uses Python's standard `decimal.Decimal` with `ROUND_HALF_UP` to prevent floating-point rounding errors common in LLM math.
* **Safe AST Expression Evaluation:** `FinancialCalculator.evaluate_expression(expr_str)` sanitizes input using regex `^[\d\.\s\+\-\*\/\(\)]+$` and evaluates the expression tree via Python's `ast` module, restricting operators strictly to `Add`, `Sub`, `Mult`, `Div`, `USub`, and `UAdd`. It rejects any arbitrary code execution.
* **Discount Calculation:** `calculate_discount(gross_amount, discount_percentage, days_offset, invoice_date)` computes:
  $$\text{discount\_amount} = \text{gross} \times \left(\frac{\text{percentage}}{100}\right)$$
  $$\text{discounted\_total} = \text{gross} - \text{discount\_amount}$$
  And calculates calendar deadline dates using `datetime.timedelta`.

### B. Current Invocation Bottleneck
In `agent_orchestrator.py` (`_execute_calculator`), arguments are parsed from the raw user query string using fragile regular expressions:
```python
pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", query)
amount_match = re.search(r"(?:on|\$|£|€)\s*(\d+(?:\.\d+)?)", query)
days_match = re.search(r"(\d+)\s*(?:days|day)", query)
```
If a user writes *"Deduct two percent from thirteen hundred dollars"*, the regex fails completely, returning `{"status": "skipped", "reason": "no_computational_expression_matched"}`. Under a true tool-calling agent, the LLM will parse natural language into structured Pydantic parameters.

---

## 10. Current LLM Integration

Implemented in `backend/app/rag/llm_client.py`.

* **Provider:** Mistral AI.
* **Model:** Configured via `settings.EXTRACTION_LLM_MODEL` (default: `mistral-small-2603`).
* **Client Architecture:** Custom synchronous wrapper using Python's standard library `urllib.request`.
* **API Endpoint:** `POST {settings.MISTRAL_API_BASE}/chat/completions`.
* **Synchronous vs Asynchronous:** 100% synchronous and blocking. Each LLM call blocks the worker thread for up to 30 seconds (`urllib.request.urlopen(req, timeout=30)`).
* **Tool Calling Support:** **None.** The payload does not send `tools`, `tool_choice`, or parse `tool_calls`.
* **Streaming Support:** **None.**
* **Structured Output Support:** **None.**
* **`bind_tools` Availability:** The current `LLMClient` does not implement `bind_tools`.

---

## 11. Dependency / LangChain Status

Inspection of `backend/requirements.txt` and `backend/requirements-dev.txt` confirmed:

```text
langchain              --> NOT INSTALLED (Missing)
langchain-core         --> NOT INSTALLED (Missing)
langchain-community    --> NOT INSTALLED (Missing)
langchain-mistralai    --> NOT INSTALLED (Missing)
langgraph              --> NOT INSTALLED (Missing)
```

Existing relevant packages already installed:
* `pydantic==2.13.4` & `pydantic-settings==2.14.1`
* `sqlglot==26.6.0`
* `pgvector==0.3.6`
* `SQLAlchemy==2.0.51`
* `sentence-transformers==3.4.1`
* `httpx==0.28.1` (in `requirements-dev.txt`)

---

## 12. Current Architectural Problems and Limitations

Based strictly on forensic code analysis, the existing architecture has the following limitations:

1. **Brittle Keyword Routing:** Queries such as *"Give me a summary of total expenditures"* trigger SQL because of the word *"total"*, even if the user meant an unstructured narrative summary. Conversely, *"What is our liability to ACME?"* matches no SQL triggers and falls back to RAG, failing to query relational totals.
2. **Regex Parameter Extraction for Math:** The calculator cannot handle verbal numbers, currency codes after numbers, or multi-step discount terms unless they match rigid regex patterns.
3. **Inability to Reason Iteratively:** In compound queries, if the SQL query returns empty or ambiguous document IDs, RAG cannot refine its search query based on that observation.
4. **Static Tool Order:** The sequence is hardcoded as SQL $\rightarrow$ Calculator $\rightarrow$ RAG. The system cannot execute RAG first (to extract a contract clause mentioning a penalty percentage) and then feed that percentage into the Calculator.
5. **Error Masking:** When SQL generation or execution fails, the error string is swallowed in synthesis, presenting an empty dataset to the model rather than enabling recovery or explanation.
6. **Synchronous Blocking I/O:** Using `urllib.request` inside FastAPI synchronous endpoints blocks Uvicorn threads during external Mistral API network calls.
7. **No Conversational Memory in Global Chat:** In `agent_orchestrator.py`, previous conversation turns are persisted to `chat_messages`, but they are **not** loaded or passed into the synthesis prompt during subsequent turns. Only single-turn user queries are processed.

---

## 13. Target ReAct / LangChain Architecture

The target architecture replaces the static keyword router with a **LangChain/LangGraph-based ReAct Agent** while preserving all underlying domain services (`TextToSQLService`, `RAGService`, `FinancialCalculator`).

### Target Conceptual Architecture

```
                                +---------------------------+
                                |  Frontend (GlobalChatPage)|
                                +-------------+-------------+
                                              | HTTP POST /chat/corpus/messages
                                              v
                                +---------------------------+
                                |  FastAPI Router           |
                                |  (routers/global_chat.py) |
                                +-------------+-------------+
                                              | passes (db, query, user, history)
                                              v
                  +-------------------------------------------------------+
                  |         LangGraph ReAct Tool-Calling Agent            |
                  |                                                       |
                  |  State: {messages, user, db, tool_records, citations} |
                  +---------------------------+---------------------------+
                                              |
                   +--------------------------+--------------------------+
                   |                          ^                          |
                   v                          |                          v
         +-------------------+      +-------------------+      +-------------------+
         | database_query    |      | financial_calc    |      | document_rag      |
         | tool              |      | tool              |      | tool              |
         +---------+---------+      +---------+---------+      +---------+---------+
                   |                          |                          |
                   v                          v                          v
         +-------------------+      +-------------------+      +-------------------+
         | TextToSQLService  |      |FinancialCalculator|      | RAGService        |
         | (AST + Auth Valid)|      | (Decimal Math)    |      | (Hybrid RRF)      |
         +---------+---------+      +---------+---------+      +---------+---------+
                   |                          |                          |
                   v                          v                          v
             PostgreSQL DB              Python Decimal             PostgreSQL +
           (Read-Only, 5s)             (Deterministic)             pgvector / FTS
                   |                          |                          |
                   +--------------------------+--------------------------+
                                              | ToolMessage (Observations)
                                              v
                              +-------------------------------+
                              | Mistral ReAct Next Step Logic |
                              | (Decide another tool OR end)  |
                              +---------------+---------------+
                                              | Final AI Response
                                              v
                              +-------------------------------+
                              | ChatHistoryRepository & DB    |
                              +-------------------------------+
                                              | JSON (matches frontend contract)
                                              v
                                   Frontend UI Rendering
```

---

## 14. Proposed Tool Definitions

Each tool will be implemented as a LangChain `StructuredTool` with strict Pydantic `args_schema`.

### Tool 1: Database Query Tool (`database_query_tool`)
* **Purpose:** Query relational records, aggregate counts, sums, status distributions, and metadata across documents, extraction results, validation results, and users.
* **Input Schema:**
  ```python
  class DatabaseQueryInput(BaseModel):
      question: str = Field(
          ...,
          description="Natural language question specifying the relational metric, count, sum, or filter needed (e.g. 'How many invoices are in VALIDATED status?')"
      )
  ```
* **Output Schema:**
  ```python
  class DatabaseQueryResult(BaseModel):
      success: bool
      sql: Optional[str]
      row_count: int
      columns: List[str]
      rows: List[Dict[str, Any]]
      error: Optional[str] = None
  ```
* **Wrapped Service:** `TextToSQLService.generate_and_execute_sql(question, user=user)`.
* **Security & Authorization Constraints:**
  * Tool factory injects the authenticated `user: User` into the service closure. The agent LLM cannot modify or forge `user`.
  * `TextToSQLService` performs AST parsing, SELECT-only validation, table/column allowlisting, analyst tenant predicate injection, and 5-second timeout execution.

### Tool 2: Document RAG Tool (`document_rag_tool`)
* **Purpose:** Retrieve unstructured text, contract terms, payment clauses, penalty conditions, Incoterms, and OCR snippets across the document corpus or scoped to specific document IDs.
* **Input Schema:**
  ```python
  class DocumentRAGInput(BaseModel):
      query: str = Field(
          ...,
          description="Semantic search query describing the clause, condition, or term to locate (e.g. 'early settlement discount terms' or 'freight delivery conditions')"
      )
      document_ids: Optional[List[int]] = Field(
          default=None,
          description="Optional list of specific document IDs to constrain retrieval to (e.g. from a prior database query)"
      )
  ```
* **Output Schema:**
  ```python
  class DocumentRAGResult(BaseModel):
      success: bool
      retrieved_count: int
      scoped_documents: Optional[List[int]]
      chunks: List[Dict[str, Any]]
      error: Optional[str] = None
  ```
* **Wrapped Service:** `RAGService.retrieve_global(query, user=user, document_ids=document_ids, top_k=5)`.
* **Security & Authorization Constraints:**
  * Pre-retrieval SQL authorization predicates applied inside PostgreSQL (`uploaded_by = user.id` for analysts).
  * Chunks returned include full provenance: `chunk_id`, `document_id`, `page_number`, `chunk_type`, and `bounding_box_refs`.

### Tool 3: Financial Calculator Tool (`financial_calculator_tool`)
* **Purpose:** Perform deterministic arithmetic, percentage discount calculations, and calendar settlement deadlines with exact Decimal precision.
* **Input Schema:**
  ```python
  class FinancialCalculatorInput(BaseModel):
      operation: Literal["discount", "expression"] = Field(
          ...,
          description="Type of calculation: 'discount' for early settlement calculations, or 'expression' for standard arithmetic"
      )
      gross_amount: Optional[str] = Field(
          default=None,
          description="Gross total amount before discount (e.g. '1320.00')"
      )
      discount_percentage: Optional[str] = Field(
          default=None,
          description="Discount percentage (e.g. '2%')"
      )
      days_offset: Optional[int] = Field(
          default=10,
          description="Days allowed for early payment discount (e.g. 10)"
      )
      invoice_date: Optional[str] = Field(
          default=None,
          description="Base invoice date in YYYY-MM-DD format to compute deadline date"
      )
      expression: Optional[str] = Field(
          default=None,
          description="Mathematical expression for arithmetic evaluation (e.g. '1320.00 - 26.40')"
      )
  ```
* **Output Schema:**
  ```python
  class FinancialCalculatorResult(BaseModel):
      success: bool
      result: Dict[str, Any]
      error: Optional[str] = None
  ```
* **Wrapped Service:** `FinancialCalculator.calculate_discount` and `FinancialCalculator.evaluate_expression`.
* **Security Constraints:** AST evaluation only; rejects non-arithmetic characters; handles division by zero gracefully.

---

## 15. Proposed Agent Loop

### Recommendation: **LangGraph StateGraph**

We recommend implementing the agent via **LangGraph** (e.g., using `create_react_agent` from `langgraph.prebuilt` or a custom `StateGraph` over `langchain-core` / `langchain-mistralai`).

#### Why LangGraph over Legacy LangChain `AgentExecutor`:
1. **Official Standard:** `AgentExecutor` in `langchain.agents` is deprecated in modern LangChain in favor of LangGraph.
2. **Explicit Cycle and Recursion Control:** LangGraph natively enforces `recursion_limit` (e.g., max 5 tool iterations) to prevent infinite execution loops.
3. **Structured Context Injection:** Enables passing non-LLM state (like `Session`, `User`, `accumulated_citations`, and `tool_calls_record`) through graph node state without polluting the LLM prompt.
4. **Streaming and Tool State Visibility:** Easily emits intermediate tool events to construct the response payload required by the frontend.

### ReAct Loop Sequence:

```
[User Input + Chat History]
           │
           ▼
     [Agent Node] ◄────────────────────────────────────────┐
           │                                               │
           ▼ Calls model.bind_tools([tools])               │
     [LLM Generates]                                       │
     ├── Tool Calls Required?                              │
     │   ├── YES ──────────────────────────────────┐       │
     │   └── NO (Final Answer) ──► [Synthesize]    │       │
     │                                             │       │
     └─────────────────────────────────────────────┘       │
                                                           │
                                                           ▼
                                                    [Tool Node]
                                                    - Execute Selected Tool(s)
                                                    - Catch & Format Tool Errors
                                                    - Append ToolMessage(s)
                                                    - Update Citations / Metadata
                                                           │
                                                           └─────── Iteration Loop (Max 5)
```

### Loop Parameters:
* **Max Iterations (`recursion_limit`):** 5 iterations.
* **Overall Execution Timeout:** 25 seconds (enforced at API/async level).
* **Early Exit Condition:** When the model outputs a text response without `tool_calls`.

---

## 16. SQL Tool Migration Strategy

1. **Retain `TextToSQLService` Intact:** The service already contains AST security, table/column allowlists, and predicate injection.
2. **Tool Wrapper (`create_database_query_tool(db: Session, user: User)`):**
   ```python
   def create_database_query_tool(db: Session, user: User) -> StructuredTool:
       service = TextToSQLService(db)

       def run_query(question: str) -> str:
           try:
               res = service.generate_and_execute_sql(question, user=user)
               return json.dumps({
                   "status": "success",
                   "sql": res["sql"],
                   "row_count": res["row_count"],
                   "columns": res["columns"],
                   "rows": res["rows"],
               }, default=str)
           except SQLSecurityException as sec_err:
               return json.dumps({
                   "status": "security_error",
                   "error": f"Query blocked by security policy: {sec_err}",
               })
           except Exception as err:
               return json.dumps({
                   "status": "execution_error",
                   "error": f"SQL execution failed: {err}",
               })

       return StructuredTool.from_function(
           name="database_query_tool",
           description="Query relational financial database for counts, sums, status filters, and tabular records.",
           func=run_query,
           args_schema=DatabaseQueryInput,
       )
   ```
3. **Security Invariant:** Notice that `user` is captured by closure and **never** accepted from LLM tool arguments.

---

## 17. RAG Tool Migration Strategy

1. **Retain `RAGService` Intact:** Hybrid dense + sparse + RRF + Cross-Encoder pipeline remains the core retrieval engine.
2. **Tool Wrapper (`create_document_rag_tool(db: Session, user: User, state_citations: list)`):**
   ```python
   def create_document_rag_tool(db: Session, user: User, citations_accumulator: list) -> StructuredTool:
       service = RAGService(db)

       def run_rag(query: str, document_ids: Optional[List[int]] = None) -> str:
           try:
               chunks = service.retrieve_global(query=query, user=user, document_ids=document_ids, top_k=5)
               formatted_chunks = []
               for c in chunks:
                   cite = {
                       "chunk_id": c.chunk_id,
                       "document_id": c.document_id,
                       "page_number": c.page_number or 1,
                       "chunk_type": c.chunk_type,
                       "snippet": c.content.strip()[:300],
                       "bounding_box_refs": c.metadata_json.get("bounding_box_refs", []),
                       "rerank_score": getattr(c, "rerank_score", None),
                   }
                   citations_accumulator.append(cite)
                   formatted_chunks.append({
                       "doc_id": c.document_id,
                       "page": c.page_number,
                       "section": c.chunk_type,
                       "content": c.content.strip(),
                   })
               return json.dumps({
                   "status": "success",
                   "count": len(chunks),
                   "chunks": formatted_chunks,
               })
           except Exception as err:
               return json.dumps({
                   "status": "error",
                   "error": f"Document retrieval failed: {err}",
               })

       return StructuredTool.from_function(
           name="document_rag_tool",
           description="Retrieve unstructured text, clauses, terms, and conditions from the document portfolio.",
           func=run_rag,
           args_schema=DocumentRAGInput,
       )
   ```

---

## 18. Calculator Tool Migration Strategy

1. **Retain `FinancialCalculator` Intact:** Deterministic `Decimal` operations remain untouched.
2. **Tool Wrapper (`financial_calculator_tool`):**
   ```python
   def create_financial_calculator_tool() -> StructuredTool:
       calc = FinancialCalculator

       def run_calc(
           operation: str,
           gross_amount: Optional[str] = None,
           discount_percentage: Optional[str] = None,
           days_offset: int = 10,
           invoice_date: Optional[str] = None,
           expression: Optional[str] = None,
       ) -> str:
           try:
               if operation == "discount":
                   if not gross_amount or not discount_percentage:
                       return json.dumps({"status": "error", "error": "gross_amount and discount_percentage required for discount"})
                   res = calc.calculate_discount(
                       gross_amount=gross_amount,
                       discount_percentage=discount_percentage,
                       days_offset=days_offset,
                       invoice_date=invoice_date,
                   )
                   return json.dumps({"status": "success", "result": res})
               elif operation == "expression":
                   if not expression:
                       return json.dumps({"status": "error", "error": "expression required for arithmetic evaluation"})
                   val = calc.evaluate_expression(expression)
                   return json.dumps({"status": "success", "result": {"expression": expression, "value": str(val)}})
               else:
                   return json.dumps({"status": "error", "error": f"Unknown operation: {operation}"})
           except Exception as err:
               return json.dumps({"status": "error", "error": str(err)})

       return StructuredTool.from_function(
           name="financial_calculator_tool",
           description="Perform deterministic Decimal arithmetic and early settlement discount calculations.",
           func=run_calc,
           args_schema=FinancialCalculatorInput,
       )
   ```

---

## 19. Authorization and Security Model

The cardinal architectural rule for EFDI is: **The LLM is NEVER the security boundary.**

```
[ Untrusted LLM Space ]
        │  Generates tool call: database_query_tool(question="...")
        ▼
[ Trusted Boundary / Tool Factory ]
        │  Injects authenticated user context: TextToSQLService(db).generate_and_execute_sql(..., user=user)
        ▼
[ AST Validation Layer (sqlglot) ]
        │  1. Check SELECT-only
        │  2. Allowlist Tables & Columns (Exclude password_hash)
        │  3. Inject Tenant Predicate (documents.uploaded_by = user.id)
        │  4. Enforce LIMIT <= 100
        ▼
[ Database Connection Layer ]
        │  1. SET TRANSACTION READ ONLY;
        │  2. SET LOCAL statement_timeout = '5000ms';
        ▼
[ PostgreSQL Engine ]
```

### Role-Based Enforcement Across Tools:
1. **Global Chat Access Gating:** If `user.role == "FINANCE_ANALYST"` and `settings.GLOBAL_CHAT_ANALYST_POLICY == "forbidden"`, the API router raises `AuthorizationException` (HTTP 403) before the agent is invoked.
2. **Analyst Scoped Policy:** If `GLOBAL_CHAT_ANALYST_POLICY == "scoped"`:
   * `database_query_tool`: SQL AST injection automatically forces `documents.uploaded_by = user.id AND documents.is_deleted = false`.
   * `document_rag_tool`: Pre-retrieval SQL query joins `Document` and forces `Document.uploaded_by == user.id`.
3. **No Direct Parameter Passing of User ID:** The LLM cannot provide or alter `user_id`. It is bound via Python closure from the verified JWT token.

---

## 20. Error Handling Strategy

In a ReAct agent, confusing a tool execution failure with a successful empty result causes hallucination. The error strategy enforces explicit tool response contracts:

```json
// Successful zero-row query:
{
  "status": "success",
  "sql": "SELECT id FROM documents WHERE status = 'REJECTED'",
  "row_count": 0,
  "columns": ["id"],
  "rows": []
}

// Security rejection:
{
  "status": "security_error",
  "error": "Query blocked by security policy: Only SELECT statements are permitted, got: Update"
}

// Database execution timeout or syntax error:
{
  "status": "execution_error",
  "error": "canceling statement due to statement timeout"
}
```

### Model Recovery Behavior:
* When receiving `status: "success"` with `row_count: 0`, the model explains that zero matching documents exist in the database.
* When receiving `status: "execution_error"`, the model can reformulate the query in iteration 2 or inform the user that the query timed out, rather than falsely claiming zero records exist.

---

## 21. Observability Strategy

To monitor agent decisions without violating enterprise privacy or data regulations:

1. **Logged Information:**
   * `session_id`, `message_id`, `user_id`, `user_role`
   * Selected tool name and execution iteration index
   * Sanitized tool parameters (excluding passwords/tokens)
   * Tool execution latency in milliseconds (`execution_time_ms`)
   * Result metadata (`row_count`, `retrieved_count`, `status`)
   * Tool exceptions and error codes
2. **Prohibited from Logs:**
   * LLM Chain-of-thought (CoT) internal monologue
   * User passwords or authentication credentials
   * Full database row contents containing sensitive PII/vendor banking details
3. **Standard Audit Logging:** Logged via EFDI's existing `app.audit.audit_service` as `CHAT_GLOBAL_QUERY` events.

---

## 22. Testing Strategy

The migration must include automated tests in `backend/tests/test_react_agent.py`:

| Test Category | Target Scenario | Verification Assertion |
|:---|:---|:---|
| 1. SQL-Only | *"How many invoices are in VALIDATED status?"* | Agent calls `database_query_tool` once; output cites row count; iteration count = 1. |
| 2. Calculator-Only | *"Calculate a 2% discount on $1320 within 10 days"* | Agent calls `financial_calculator_tool`; quotes `$26.40` and `$1293.60`. |
| 3. RAG-Only | *"What dispute conditions apply under our Incoterms?"* | Agent calls `document_rag_tool`; output contains verified citations. |
| 4. Compound Multi-Hop | *"What are the payment terms and how many invoices have them?"* | Agent executes `database_query_tool`, observes results, then calls `document_rag_tool`. |
| 5. Zero-Result Handling | Query matching no records | Distinct from error; response states no matching records found. |
| 6. Tool Failure Recovery | Synthetic SQL error in iteration 1 | Agent catches error and explains failure or attempts alternative formulation. |
| 7. Authorization Scoping | Analyst queries global count | Injected SQL contains `uploaded_by = analyst.id`. |
| 8. Recursion Limiter | Malicious cyclic prompt | Agent terminates cleanly at `recursion_limit = 5` without unhandled exception. |
| 9. Prompt Injection Defense | Prompt asking to `DROP TABLE documents` | `sqlglot` blocks query; security error returned to agent; table remains intact. |

---

## 23. Step-by-Step Implementation Plan

### Phase 1: Dependency Preparation
* Add `langchain-core`, `langchain-mistralai`, and `langgraph` to `backend/requirements.txt`.
* Pin versions compatible with Python 3.11/3.12 and `pydantic>=2.13`.

### Phase 2: LangChain Tool Wrappers
* Create `backend/app/rag/tools/`:
  * `database_query.py`: wraps `TextToSQLService`.
  * `document_rag.py`: wraps `RAGService`.
  * `financial_calculator.py`: wraps `FinancialCalculator`.
* Enforce strict Pydantic schemas and closure-based authorization injection.

### Phase 3: LangGraph ReAct Agent Implementation
* Implement `backend/app/rag/react_agent.py`:
  * Configure `ChatMistralAI(model=settings.EXTRACTION_LLM_MODEL, api_key=settings.MISTRAL_API_KEY)`.
  * Define state: `AgentState` containing messages, user, db, tool execution logs, and citations.
  * Build graph using `create_react_agent` from `langgraph.prebuilt` or custom `StateGraph`.
  * Set `recursion_limit = 5`.

### Phase 4: Orchestrator Migration
* Update `AgentOrchestrator.process_global_query()` in `backend/app/rag/agent_orchestrator.py`:
  * Delegate query processing to the ReAct agent runner.
  * Map agent execution outputs to the existing `GlobalChatMessageResponse` schema (`tool_calls`, `citations`, `content`).
  * Ensure full backward compatibility with `frontend/src/pages/GlobalChatPage.tsx`.

### Phase 5: Verification & End-to-End Testing
* Run unit and integration tests covering single-tool, multi-tool, error, and RBAC test cases.
* Verify frontend rendering in `GlobalChatPage.tsx` against live running dev server.

---

## 24. Files Expected to Change

> [!NOTE]
> In accordance with the strict READ-ONLY constraints of this investigation, **no code has been modified**. The files below represent the target inventory for future execution.

| File Path | Nature of Eventual Change | Rationale |
|:---|:---|:---|
| `backend/requirements.txt` | [MODIFY] | Add `langchain-core`, `langchain-mistralai`, `langgraph`. |
| `backend/app/rag/tools/__init__.py` | [NEW] | Package initialization for LangChain tool registry. |
| `backend/app/rag/tools/database_query.py` | [NEW] | Factory for `database_query_tool` wrapping `TextToSQLService`. |
| `backend/app/rag/tools/document_rag.py` | [NEW] | Factory for `document_rag_tool` wrapping `RAGService`. |
| `backend/app/rag/tools/financial_calculator.py` | [NEW] | Factory for `financial_calculator_tool` wrapping `FinancialCalculator`. |
| `backend/app/rag/react_agent.py` | [NEW] | LangGraph agent graph, state definition, and executor. |
| `backend/app/rag/agent_orchestrator.py` | [MODIFY] | Replace keyword `_plan_tool_execution` with ReAct agent invocation; preserve session persistence and response formatting. |
| `backend/tests/test_global_agent.py` | [MODIFY] | Update tests to validate dynamic multi-tool calling and ReAct behavior. |
| `backend/tests/test_react_agent.py` | [NEW] | Comprehensive test suite for ReAct agent iterations, tool errors, and RBAC. |

---

## 25. Risks and Architectural Considerations

1. **Mistral API Latency in Multi-Hop Queries:** Each ReAct iteration requires an LLM network round-trip. If an agent calls Tool A, observes the result, calls Tool B, and synthesizes an answer, total latency could reach 3–6 seconds. Mitigation: Set `temperature=0.0`, enforce `recursion_limit=5`, and use fast models (`mistral-small-latest`).
2. **Tool Hallucination / Schema Drift:** Small LLMs may produce malformed tool arguments. Mitigation: Strict Pydantic validation via `StructuredTool` and providing clear tool docstrings.
3. **Database Concurrency:** Multiple simultaneous tool calls could exhaust connection pools. Mitigation: Use `engine.connect()` context managers with strict 5-second timeouts and read-only transactions.
4. **Preserving Backward Compatibility:** The frontend `GlobalChatPage.tsx` expects `tool_calls` with keys `tool`, `sql`, `summary`, `result`, `row_count`, and `citations`. The orchestrator must adapt LangGraph's internal `ToolMessage` structure to this exact contract.

---

## 26. Open Questions / Decisions Required

1. **Async vs Sync Agent Invocation:** Should the ReAct agent be implemented as an `async` workflow (`ainvoke`) or synchronous (`invoke`)? Since `uvicorn` runs asynchronously, `ainvoke` is recommended to prevent worker thread starvation.
2. **Conversational Memory Window:** How many prior conversational turns should be passed to the ReAct agent? Recommended: Pass the last 6 turns (3 Q&A pairs) from `ChatHistoryRepository`.
3. **Offline / Fallback Mode:** If `MISTRAL_API_KEY` is not set or network access is offline, should the system fall back to the existing keyword heuristic or return an explicit offline warning?

---

## 27. Final Recommendation

Migrating from the current rule-based orchestrator to a **LangGraph Tool-Calling ReAct Agent** will dramatically improve EFDI's conversational intelligence:
* Eliminates brittle keyword matching and regex math parsing.
* Enables true multi-hop reasoning (e.g., querying relational document counts, extracting contractual discount percentages via RAG, and computing exact settlement dates via the calculator in a unified workflow).
* Preserves 100% of EFDI's proven database security, AST validation, tenant isolation, and deterministic Decimal accuracy.
* Integrates seamlessly into the existing frontend without requiring changes to the user interface.
