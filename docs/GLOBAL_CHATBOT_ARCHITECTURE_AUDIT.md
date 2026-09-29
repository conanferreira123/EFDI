# EFDI Global Chatbot Architecture Audit

## 1. Executive Summary

This architectural audit evaluates the EFDI Global Conversational Intelligence Assistant (`/api/v1/chat/corpus` and `GlobalChatPage`), specifically diagnosing why it fails to reliably answer enterprise cross-document financial, contractual, and relational queries (represented by benchmark test suite **Q58–Q81**).

### High-Level Verdict
The EFDI Global Chatbot is constructed as a LangChain ReAct agent (`GlobalReActAgent`) equipped with three tools: `database_query_tool`, `document_rag_tool`, and `financial_calculator_tool`. While the architectural ambition—coordinating structured SQL, semantic OCR RAG, and deterministic Decimal arithmetic—is sound, the implementation suffers from severe architectural disconnects, data model omissions, tool communication barriers, and fragile heuristics that prevent it from answering complex cross-document questions:

1. **Data Model & Schema Blindspots**: Crucial business entities needed for enterprise AP questions do not exist in the relational schema or are barred from the SQL engine. There is **no Purchase Orders table** in the system, preventing any inquiry regarding open POs, price variances against POs, or PO vs. non-PO comparisons. Furthermore, the `workflow_history` table (which records approval timestamps, actions, and human rejection notes) and `audit_logs` are **strictly excluded** from the text-to-SQL allowlist. As a result, questions regarding approval turnaround times, pending approval durations, or rejection reasons fail completely.
2. **Two-Phase Text-to-SQL Latency and Silent Heuristic Fallback**: The `database_query_tool` wraps an internal `TextToSQLService` that invokes a separate secondary LLM call to generate PostgreSQL code. Crucially, if this internal LLM generation fails or produces syntax errors, the service **silently executes a hardcoded heuristic fallback query** (e.g. `SELECT ... FROM documents WHERE status = 'VALIDATED'`), returning bogus data to the agent that bears no relation to the user's actual financial question.
3. **Severe Global RAG Top-K Bottleneck**: The global RAG service enforces a hard limit of `top_k = 5` chunks across the *entire enterprise corpus*. Semantic retrieval cannot perform aggregations, counts, or exhaustive enumerations across hundreds of documents. Questions such as *"Which vendors across our entire system operate under Net 60?"* or *"How many invoices contain late payment penalty clauses?"* retrieve at most 5 arbitrary chunks and hallucinate or undercount.
4. **Scalar-Only Calculator**: The `financial_calculator_tool` is restricted to evaluating single arithmetic expressions (e.g. `a * b`) or single invoice discount calculations. It cannot consume SQL tabular rows, cannot iterate across multiple records, and cannot aggregate portfolio savings.
5. **Brittle ReAct Loop & Aggressive Guardrails**: The agent is restricted to `MAX_ITERATIONS = 5`. The loop guard (`_is_redundant_query`) prematurely aborts valid multi-step workflows if the agent rephrases a query with >70% token overlap. Additionally, SQL results are truncated to 15 sample rows, hiding data from the reasoning model.
6. **Fragmented Evidence Provenance**: Only `document_rag_tool` populates citations. Relational SQL queries and calculations produce zero citation metadata, rendering the final synthesis unable to distinguish verified database facts from inferred assertions.

### Benchmark Capability Summary (Q58–Q81)
- **Fully Supported**: 2 / 24 (8.3%) — Simple single-table SQL aggregations on existing columns (e.g., Q58, Q77).
- **Partially Supported**: 6 / 24 (25.0%) — Require workarounds, vulnerable to date blindness, 15-row truncation, or single-chunk RAG limits (e.g., Q59, Q60, Q62, Q64, Q66, Q75).
- **Not Supported**: 16 / 24 (66.7%) — Blocked by missing tables (POs, workflow history), missing attributes (department, cost center, SKU), RAG aggregation inability, or scalar calculator limitations (e.g., Q61, Q63, Q65, Q67, Q68, Q69, Q70, Q71, Q72, Q73, Q74, Q76, Q78, Q79, Q80, Q81).

---

## 2. Current Global Chatbot Architecture

The global chatbot spans frontend entry points, API routes, context resolvers, a ReAct agent loop, three backend tool adapters, and underlying persistence services.

```
                             [ USER QUERY ]
                                   │
                                   ▼
          POST /api/v1/chat/corpus/messages (global_chat.py)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       ChatHistoryRepository          ConversationContextResolver
       (Fetch sliding window)         (LLM rewrite / anaphora check)
                    │                             │
                    └──────────────┬──────────────┘
                                   ▼
                           GlobalReActAgent
               (ChatMistralAI + bind_tools, Max 5 steps)
                                   │
       ┌───────────────────────────┼───────────────────────────┐
       ▼                           ▼                           ▼
[database_query_tool]     [document_rag_tool]     [financial_calculator_tool]
       │                           │                           │
TextToSQLService              RAGService              FinancialCalculator
- Prompt Mistral for SQL      - 384-dim dense search  - Python ast eval
- sqlglot AST validation        (pgvector top 30)     - Decimal discount calc
- Scoping predicate injection - Sparse FTS (top 30)   - Date offset calc
- Read-only Postgres run      - RRF Fusion (top 25)
- Truncate to 15 rows         - CrossEncoder rerank
                              - Top 5 chunks
       │                           │                           │
       └───────────────────────────┼───────────────────────────┘
                                   ▼
                      Observation ToolMessages
                                   │
                                   ▼
                         Final LLM Synthesis
                                   │
                                   ▼
                   GlobalChatMessageResponse
           (content, tool_calls, citations, execution_time)
```

### Exact Codebase Map

| Component | File Path | Class / Function | Responsibility |
|---|---|---|---|
| **API Router** | `backend/app/routers/global_chat.py` | `send_global_message` | Endpoint entry point, user auth, context resolution, session persistence. |
| **Context Resolver** | `backend/app/rag/context_resolver.py` | `ConversationContextResolver` | Resolves anaphora, elliptical queries, and confirmations before agent routing. |
| **Agent Core** | `backend/app/rag/global_agent.py` | `GlobalReActAgent` | LangChain ReAct loop (`bind_tools`), iteration bounds, loop guards, synthesis. |
| **Agent LLM** | `backend/app/rag/agent_llm.py` | `get_agent_llm` | Instantiates `ChatMistralAI` (`mistral-small-2603`). |
| **Database Tool** | `backend/app/rag/tools/database_tool.py` | `DatabaseQueryTool` | `BaseTool` adapter wrapping SQL generation & execution. |
| **Text-to-SQL Service** | `backend/app/services/text_to_sql_service.py` | `TextToSQLService` | Mistral SQL generation, sqlglot AST security checks, row limit (100). |
| **RAG Tool** | `backend/app/rag/tools/rag_tool.py` | `DocumentRAGTool` | `BaseTool` adapter wrapping hybrid retrieval and chunk accumulation. |
| **RAG Service** | `backend/app/services/rag_service.py` | `RAGService` | Dense (pgvector) + Sparse (FTS) + RRF + Cross-Encoder reranking. |
| **Chunk Repository** | `backend/app/repositories/chunk_repository.py` | `ChunkRepository` | Database access for `DocumentChunk` with SQL scoping. |
| **Calculator Tool** | `backend/app/rag/tools/calculator_tool.py` | `FinancialCalculatorTool` | `BaseTool` adapter for mathematical operations. |
| **Calculator Engine** | `backend/app/rag/financial_calculator.py` | `FinancialCalculator` | AST mathematical evaluation, Decimal discount formulas, calendar arithmetic. |
| **Chat History Repo** | `backend/app/repositories/chat_history_repository.py` | `ChatHistoryRepository` | Persists sessions, messages, tool call logs, and state JSON. |
| **Frontend UI** | `frontend/src/pages/GlobalChatPage.tsx` | `GlobalChatPage` | Chat UI, prompt chips, message history, tool badges, citations viewer. |

---

## 3. Global System Prompt Audit

The active system prompt is hardcoded as `GLOBAL_REACT_SYSTEM_PROMPT` in `backend/app/rag/global_agent.py` (lines 26–49).

### Full System Prompt Text
```python
GLOBAL_REACT_SYSTEM_PROMPT = """You are the EFDI Global Financial Intelligence Agent, an enterprise copilot for corporate finance.
You assist finance analysts, managers, and auditors across corporate financial documents, invoices, line items, and business data.

You have access to three specialized tools:
1. database_query_tool: Queries relational counts, spend totals, invoices, line items, vendors, payment obligations, approval statuses and user information(only if user has role of Administrator).
2. document_rag_tool: Retrieves unstructured contract clauses, payment terms, Incoterms, freight, penalties, and OCR text snippets.
3. financial_calculator_tool: Performs deterministic Decimal arithmetic, early settlement discounts, and calendar deadline date calculations.

OPERATIONAL GUIDELINES:
- Dynamically select the most appropriate tool(s) for the user's question.
- For financial numbers, aggregations, and counts, query database_query_tool.
- For contractual terms, settlement percentages, or clauses, query document_rag_tool.
- For arithmetic, variances, settlement discounts, or date offsets, ALWAYS invoke financial_calculator_tool.
- You can perform multi-step reasoning: query data or text first, then pass observed numbers to financial_calculator_tool.
- Answer ONLY from verified tool observations. NEVER fabricate numbers, dates, or terms.
- When sufficient information has been gathered, provide a concise, professional, grounded final answer without exposing internal tool calls or reasoning.

CONVERSATIONAL CONTINUITY & EVIDENCE RULES:
- When the user asks a follow-up or confirms an offer, resolve their intent using the immediate dialogue context.
- Verified tool observations ALWAYS take precedence over historical assistant statements or conversational text.
- If a tool search returns no matching records/clauses, report clearly that the search yielded no results.
- Do NOT repeatedly query equivalent variations of the same search if previous attempts yielded no relevant findings.
- Do NOT repeat an offer or question you already extended and executed in the same dialogue thread.
"""
```

### Analysis of Prompt Mismatches and Deficiencies

1. **Misrepresentation of Database Tool Capabilities**:
   - The prompt tells the model that `database_query_tool` queries *"approval statuses and user information(only if user has role of Administrator)"*.
   - In reality, while `documents.status` has coarse states (`VALIDATED`, `APPROVED`), the detailed approval workflow timestamps, multi-step actions, and reviewer rejection comments reside in `workflow_history`, which is **blocked by the SQL security allowlist**.
   - The prompt mentions *"only if user has role of Administrator"*, but the prompt is **static**—it never injects the authenticated user's actual role! The model has no knowledge of whether the current user is an Admin, Manager, or Analyst, leading it to attempt queries on `users` that trigger security rejections for non-admins.
2. **Missing Tool Schema and Calling Instructions**:
   - The prompt lists the tools but provides **zero documentation on their arguments**.
   - `document_rag_tool` supports an optional `document_ids: List[int]` parameter for filtering retrieval to specific documents identified in a prior SQL step. The prompt **never informs the model that this parameter exists**, preventing efficient SQL $\rightarrow$ RAG chaining.
   - `financial_calculator_tool` requires specific actions (`action="calculate_discount"` or `action="calculate_expression"`). The prompt gives no parameter syntax, forcing the model to guess argument names.
3. **No Temporal Grounding**:
   - The prompt provides no system clock reference (`current_date`, current month, quarter, or year). When asked relative questions (Q59 *"due within the next 7 days"*, Q63 *"this calendar week"*, Q69 *"rejected this month"*, Q77 *"Q1 vs Q2"*), the model has no reference point and either passes raw relative strings to tools or hallucinates outdated anchor years (e.g. 2023).
4. **Vague Multi-Step Guidance**:
   - The prompt states: *"You can perform multi-step reasoning: query data or text first, then pass observed numbers to financial_calculator_tool."*
   - It fails to describe SQL $\rightarrow$ RAG or RAG $\rightarrow$ SQL workflows. It does not explain how to handle tabular data or how to combine structured invoice totals with unstructured contractual clauses.
5. **Citation Suppression Conflict**:
   - The prompt instructs: *"provide a concise, professional, grounded final answer without exposing internal tool calls or reasoning."*
   - This causes the LLM to strip source identifiers (e.g. `[Doc #12, Page 2]`) from its generated response. While the Python wrapper extracts citations from `rag_tool.retrieved_chunks`, the text itself lacks grounded inline anchors, making it impossible to know which paragraph came from the database vs. document text.

---

## 4. Actual Tool Architecture

### Agent Nature: Genuine Tool-Calling vs. Deterministic Routing
- **Active Architecture**: `GlobalReActAgent` is a **genuine ReAct tool-using agent**. It binds tools via `llm.bind_tools([db_tool, rag_tool, calc_tool])` on `ChatMistralAI`.
- **Decision Maker**: The LLM autonomously inspects tool definitions and decides whether to emit `tool_calls` or text.
- **Legacy Artifact**: `AgentOrchestrator` in `backend/app/rag/agent_orchestrator.py` previously used hardcoded regex/keyword routing (`if "validated" in query...`). It is explicitly marked `@deprecated` and is bypassed by `global_chat.py`.

### Execution Flow and Flaws
1. **Loop Structure**: `for step in range(MAX_ITERATIONS):` where `MAX_ITERATIONS = 5`.
2. **Double-LLM Inefficiency for SQL**:
   When the agent invokes `database_query_tool(query="...")`, it does not write SQL directly. Instead, it passes a natural language query to `TextToSQLService`, which executes a **second, nested LLM call** to Mistral to generate the SQL.
   - *Impact*: High latency (2000–4500ms per SQL step), doubled token costs, and loss of agent context (the second LLM only sees the natural language string, not the conversation history or reasoning chain).
3. **Loop Guard Over-Aggressiveness**:
   Function `_is_redundant_query` computes Jaccard word overlap between consecutive tool invocations:
   ```python
   overlap = len(words_a & words_b) / len(words_a | words_b)
   if overlap >= 0.70:
       return True
   ```
   If overlap $\ge 70\%$, the agent forcibly intercepts the call, injects a suppression message, sets `should_break_loop = True`, and terminates the agent. If the agent queries RAG for *"early discount terms"* and then refines to *"settlement discount terms for invoice 104"*, the loop guard frequently triggers a false positive, killing the execution.
4. **Tool Result Truncation**:
   In `database_tool.py`:
   ```python
   sample_rows = rows[:15]
   compact_obs = {"row_count": row_count, "columns": columns, "rows": sample_rows}
   if row_count > 15:
       compact_obs["note"] = f"Showing top 15 of {row_count} records."
   ```
   The database tool strictly caps results to **15 rows**. For queries requiring whole-portfolio analysis (e.g., Q62 freight charges, Q71 Net 60 vendors, Q74 SKU price differences), any records beyond the 15th are completely invisible to the agent.

---

## 5. Database / Text-to-SQL Audit

### Accessible vs. Forbidden Tables

```
                    RELATIONAL SCHEMA ACCESS AUDIT

ALLOWED TABLES (ROLE_ALLOWED_TABLES)       FORBIDDEN / MISSING TABLES
┌──────────────────────────────────┐      ┌──────────────────────────────────┐
│ documents                        │      │ workflow_history (BLOCKED)       │
│ extraction_results               │      │ audit_logs (BLOCKED)             │
│ validation_results               │      │ vendor_knowledge (BLOCKED)       │
│ classification_results           │      │ purchase_orders (NON-EXISTENT)   │
│ invoices                         │      │ purchase_order_lines (NON-EXIST) │
│ vendors                          │      │ departments (NON-EXISTENT)       │
│ vendor_aliases                   │      │ cost_centers (NON-EXISTENT)      │
│ invoice_line_items               │      └──────────────────────────────────┘
│ payment_obligations              │
│ invoice_payments                 │
│ users (ADMIN role only)          │
└──────────────────────────────────┘
```

### Schema Knowledge Given to the LLM
`TextToSQLService.SCHEMA_CONTEXT` exposes table and column summaries as a static string.

#### Critical Missing Entities and Columns
1. **No Purchase Orders Entity**: The database contains **zero Purchase Order tables**. Invoices merely store a string `po_number: Optional[str]`. There is no record of PO line items, PO committed amounts, PO unbilled status, or PO unit prices.
   - *Impact*: Q76, Q80, and Q81 are **fundamentally unanswerable** in the database.
2. **Omission of Workflow History**: The `workflow_history` table exists in PostgreSQL and records all workflow status transitions, actor user IDs, and human comments. However:
   - It is omitted from `ALLOWED_TABLES`.
   - It is omitted from `SCHEMA_CONTEXT`.
   - Any query attempting to join `workflow_history` is rejected with `SQLSecurityException: Access to table 'workflow_history' is unauthorized.`
   - *Impact*: Q61 (average approval turnaround time), Q67 (time stuck in Pending Approval), and Q69 (rejection comments) cannot access the data.
3. **Omission of Audit Logs**: `audit_logs` is not in `ALLOWED_TABLES`. Q70 (automated vs. manual processing percentage) cannot inspect whether `EXTRACTION_FIELD_CORRECTED` or manual approval occurred.
4. **Missing Department and Cost Center**: Neither `documents` nor `invoices` contains a `department` or `cost_center` column.
   - *Impact*: Q68 (*"Which department or cost center has the highest number of unvalidated or unapproved invoices?"*) cannot be answered.
5. **Missing Product SKU**: `invoice_line_items` contains `description`, `quantity`, `uom`, `unit_price`, `net_amount`, but **no `sku` or `item_code` column**. Q74 (SKU price variance across invoices) relies on exact text matching of OCR descriptions, which breaks under OCR variations (e.g. *"Widget A"* vs *"Widget A, 10pk"*).
6. **No Currency Conversion**: `invoices` and `payment_obligations` store `currency: str`. However, SQL aggregations (`SUM(grand_total_amount)`) sum numbers directly without exchange rate conversion, producing invalid totals if the portfolio contains mixed currencies (USD, EUR, GBP).

### The Silent Heuristic Fallback Hazard
In `TextToSQLService.generate_and_execute_sql` (lines 406–409):
```python
try:
    generated_sql = self.llm_client._call_mistral_api(...)
    clean_sql = re.sub(...)
except Exception as e:
    logger.warning("LLM SQL generation failed: %s; using deterministic keyword heuristic", e)
    clean_sql = self._heuristic_sql_fallback(natural_language_query)
```
If the LLM generates invalid SQL or fails:
```python
def _heuristic_sql_fallback(self, query: str) -> str:
    q_lower = query.lower()
    if "validated" in q_lower:
        return "SELECT id, original_filename, document_type, status FROM documents WHERE status = 'VALIDATED' LIMIT 50"
    elif "how many" in q_lower or "count" in q_lower:
        return "SELECT status, COUNT(*) as count FROM documents GROUP BY status LIMIT 50"
    ...
```
This is a **critical failure mode**: if a user asks a complex question (e.g., Q67 on approval delays) and SQL generation fails, the system executes a fallback query returning status counts from `documents`. The agent receives these irrelevant counts and reports them as the answer.

---

## 6. Authorization Audit

### Role-Based Access Control Enforcement Architecture
EFDI enforces strict server-side authorization:
- The authenticated `User` object is resolved from the JWT token and injected by FastAPI dependency `get_current_user`.
- The user ID is **never accepted as a client argument** or LLM parameter.
- Authorization predicates are injected programmatically into the AST before SQL execution and into SQLAlchemy queries before vector/FTS search.

### SQL AST Authorization Rewriting
In `TextToSQLService.validate_and_sanitize_sql`:
- **For `FINANCE_ANALYST`**:
  - Scoping is enforced: Analysts may only access documents they personally uploaded (`uploaded_by = user.id`).
  - The AST walker identifies all referenced tables and injects filtering predicates:
    - `documents` $\rightarrow$ `{ref}.uploaded_by = {user.id} AND {ref}.is_deleted = false`
    - `invoices` $\rightarrow$ `{ref}.document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false)`
    - `invoice_line_items` $\rightarrow$ `{ref}.invoice_id IN (SELECT id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false))`
- **For `FINANCE_MANAGER`, `AUDITOR`, `ADMIN`**:
  - Soft-delete filtering is injected: `{ref}.is_deleted = false`.
- **AST Bug on Subqueries and CTEs**:
  In lines 346–355:
  ```python
  where_clause = ast.args.get("where")
  combined_pred = where_clause.this if where_clause else None
  for p in predicates:
      combined_pred = exp.And(this=combined_pred, expression=p) if combined_pred else p
  if combined_pred:
      ast.set("where", exp.Where(this=combined_pred))
  ```
  `ast.find_all(exp.Table)` finds tables inside subqueries or CTEs (e.g. `FROM (SELECT id FROM invoices) AS sub`), but `ast.set("where", ...)` attaches the generated predicate (`invoices.document_id IN ...`) **only to the outer SELECT statement**. In the outer SELECT, `invoices` does not exist in the `FROM` clause (only `sub` exists), causing PostgreSQL to throw:
  `ERROR: missing FROM-clause entry for table "invoices"`.
- **Rejection of `UNION` Statements**:
  Line 215 enforces `if not isinstance(ast, exp.Select): raise SQLSecurityException(...)`.
  In `sqlglot`, a `UNION` expression parses as `exp.Union`, not `exp.Select`. Thus, all `UNION` queries are unconditionally rejected.

### RAG Pre-Retrieval Scoping
In `ChunkRepository._apply_authorization_predicates`:
```python
predicates = [Document.is_deleted.is_(False)]
if user.role == UserRole.FINANCE_ANALYST.value:
    predicates.append(Document.uploaded_by == user.id)
if document_ids is not None:
    if len(document_ids) == 0:
        predicates.append(Document.id == -1)
    else:
        predicates.append(Document.id.in_(document_ids))
return stmt.join(Document, DocumentChunk.document_id == Document.id).where(and_(*predicates))
```
Authorization is enforced **in-database before vector distance computation and text ranking**. Chunks from unauthorized or soft-deleted documents are never loaded into memory.

---

## 7. RAG Pipeline Audit

### Canonical Ingestion and Embeddings
- **Source**: Canonical OCR full text (`OCRResult.full_text`), strictly independent of extraction results.
- **Chunking**:
  - Docling documents: `DoclingNativeChunker` using Docling `HybridChunker` (`tokenizer="sentence-transformers/all-MiniLM-L6-v2"`, `max_tokens=512`).
  - Fallback / OCR engines: `StructureAwareChunker` preserving `=== PAGE {n} ===` boundaries and table layouts.
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, normalized).
- **Hybrid Retrieval**:
  - Dense Vector: `pgvector` cosine distance, top 30 candidates.
  - Sparse Text: Native PostgreSQL FTS using `websearch_to_tsquery('english', q)` on `tsv_content` with `ts_rank_cd`, top 30 candidates.
  - Fusion: Reciprocal Rank Fusion ($k=60$) combining dense and sparse ranks into top 25 candidates.
  - Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2` scoring query-chunk pairs, outputting top `RAG_FINAL_TOP_K` (default 5).

### Why Global RAG Fails on Target Questions

```
                 PORTFOLIO RAG RETRIEVAL BOTTLENECK

  CORPUS: 500 INVOICES / CONTRACTS
  ┌─────────────────────────────────────────────────────────────┐
  │ Doc 1   Doc 2   Doc 3   Doc 4   Doc 5   ...   Doc 499  Doc 500│
  └─────────────────────────────────────────────────────────────┘
                                 │
                     Hybrid Search + Cross-Encoder
                                 │
                                 ▼
                     TOP 5 CHUNKS RETURNED ONLY
                     ┌────────────────────────┐
                     │ Chunk A (Doc 12)       │
                     │ Chunk B (Doc 12)       │
                     │ Chunk C (Doc 88)       │
                     │ Chunk D (Doc 104)      │
                     │ Chunk E (Doc 215)      │
                     └────────────────────────┘
```

1. **Top-5 Oblivion on Universal Queries**:
   When answering Q71 (*"Which vendors across our entire system operate under Net 60?"*), RAG retrieves 5 chunks. If 30 vendors operate under Net 60, 25+ vendors are completely omitted.
2. **Inability to Aggregate or Count**:
   RAG cannot count. For Q72 (*"How many invoices across all suppliers include explicit late payment penalty clauses?"*), RAG returns 5 chunks containing penalty text. It cannot determine if there are 5, 50, or 500 such invoices in the portfolio.
3. **No Metadata Filtering**:
   `DocumentRAGTool` accepts `query` and optional `document_ids`. It does not support metadata pre-filters on `vendor_name`, `date_range`, `invoice_amount`, or `document_type`. Semantic search on *"freight charges"* pulls random text chunks regardless of whether the invoice is from 2024, 2025, or 2026.

---

## 8. Financial Calculator Audit

### Engine Implementation
`FinancialCalculator` (`backend/app/rag/financial_calculator.py`) uses Python `ast.parse` in `mode="eval"` to safely evaluate math expressions without `eval()`, returning quantized `Decimal("0.01")` values.

Supported operations:
- Arithmetic: `+`, `-`, `*`, `/` with parenthetical precedence.
- Single Discount Formula:
  $$\text{discount} = \text{gross} \times \left(\frac{\text{pct}}{100}\right), \quad \text{payable} = \text{gross} - \text{discount}$$
- Calendar Date Offset: `base_date + timedelta(days=offset)`.

### Architectural Deficiencies
1. **Scalar Single-Row Limitation**: The calculator cannot accept a list or table of rows.
   - For Q65 (*"How much money could we save across the entire portfolio if we pay all early-discount eligible invoices before expiration?"*), the calculator cannot accept an array of `[($12000, 2%), ($45000, 3%), ...]`. The agent would have to call the calculator separately for every single invoice, quickly exceeding `MAX_ITERATIONS = 5`.
2. **No SQL Pipeline Integration**: The calculator does not connect to SQL outputs. The agent LLM must manually copy numbers from the SQL JSON string into the calculator argument string.
3. **No Currency Handling**: The calculator strips symbols (`$`, `€`, `£`) and assumes all numbers share the same currency.

---

## 9. Tool Chaining / Orchestration Audit

### Analysis of Chaining Patterns

| Pattern | Required By | Feasibility in Current Agent | Root Cause of Failure |
|---|---|---|---|
| **SQL $\rightarrow$ Calculator** | Q65, Q75, Q79 | **Partially Feasible** (Scalar only) | Agent must copy numbers from SQL JSON into calculator. Fails if more than 2–3 rows due to 5-iteration limit. |
| **SQL $\rightarrow$ RAG** | Q71, Q73, Q79 | **Extremely Fragile** | Model rarely passes `document_ids` to `document_rag_tool` because parameter is undocumented in system prompt. |
| **RAG $\rightarrow$ SQL** | Q73, Q78 | **Not Supported** | Agent cannot take entities found in RAG chunks and dynamically inject them into a structured SQL aggregation. |
| **SQL $\rightarrow$ RAG $\rightarrow$ Calculator** | Q79 | **Impossible** | Exceeds `MAX_ITERATIONS = 5`. Step 1: SQL ($N$ rows). Step 2: RAG ($N$ docs). Steps 3+: Calculator calls. Aborts before completion. |

### Context Window & Information Loss
When `database_query_tool` executes, rows are truncated to 15. If a query matches 40 invoices, rows 16–40 are discarded immediately. When the LLM subsequently calls RAG or the calculator, it only has access to the first 15 records.

---

## 10. Conversation Context Audit

### Flow from User to Model
1. User message arrives at `POST /api/v1/chat/corpus/messages`.
2. `ConversationContextResolver` checks whether the query is standalone using regex heuristics (`STANDALONE_INTERROGATIVES`).
3. If not standalone, a Mistral call rewrites the query into an explicit question using `session_state` and sliding window history.
4. `GlobalReActAgent` is invoked with `effective_query` and `history_messages`.

### History Truncation Defect
In `ChatHistoryRepository.get_langchain_history`:
```python
for m in raw_messages:
    if m.role == "user" and m.content:
        lc_messages.append(HumanMessage(content=m.content))
    elif m.role == "assistant" and m.content:
        extra = {"executed_tools": m.tool_calls or []}
        lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
```
- **The Defect**: Prior turns are passed only as `HumanMessage` and `AIMessage(content=...)`.
- **Raw `ToolMessage`s are NEVER restored into the conversation history**.
- If Turn 1 executed a SQL query returning 15 invoices and the assistant summarized 2 in its text, the underlying 15 records, invoice IDs, and amounts are **completely lost** in Turn 2. Follow-up questions (*"Calculate early discount on those"*) fail because the model no longer has the raw data.

---

## 11. Error Handling Audit

1. **Text-to-SQL Failure**:
   - Syntax error or parsing failure triggers `_heuristic_sql_fallback`, executing an irrelevant hardcoded query and returning unrelated data.
   - `SQLSecurityException` returns `Database Query Rejected by Security Policy: <reason>`. The agent LLM has no access to the generated SQL and cannot fix it; it can only rephrase the natural language prompt.
2. **RAG Empty Result**:
   - Returns `Document RAG Results: No matching text chunks found in <scope>`. The agent generally synthesizes an answer stating no records were found, but the loop guard may suppress follow-up attempts.
3. **Calculator Failure**:
   - Returns `Financial Calculator Error: <reason>`. The agent typically reports the error or attempts an ungrounded mental arithmetic calculation.
4. **Max Iterations Exhaustion**:
   - If iteration 5 concludes with a tool call, the agent executes a final fallback prompt: `"Please provide a concise, grounded final answer based only on the verified tool observations above."`
   - If intermediate tool calls returned partial data, the synthesis often hallucinates missing links to produce a complete-sounding answer.

---

## 12. Evidence and Grounding Audit

### Provenance Tracking Disconnect
- **RAG Provenance**: `DocumentRAGTool` records `chunk_id`, `document_id`, `page_number`, and `chunk_type`. These are returned in the API response under `citations`.
- **Database Provenance**: `DatabaseQueryTool` logs the executed SQL string and row count, but **attaches zero citation or document grounding metadata**.
- **Calculator Provenance**: Logs the evaluated expression and result, but has no link back to source documents.

### Impact on Enterprise Reliability
The frontend renders citations exclusively from `res.citations`. Pure SQL answers have **zero verified citations displayed in the UI**, despite being derived directly from verified relational records. Conversely, the model is unable to explicitly cite *"Invoice table row ID 42"* in its synthesis because the prompt forbids exposing tool execution details.

---

## 13. Q58–Q81 Capability Matrix

Statuses:
- **SUPPORTED**: Current architecture reliably executes and answers the question.
- **PARTIALLY SUPPORTED**: Architecture can theoretically execute, but suffers from row truncation, date blindness, or single-row calculator limits.
- **NOT SUPPORTED**: Blocked by missing tables, schema omissions, scalar calculator limits, or RAG aggregation inability.

| ID | Class | Question Summary | Primary Tool | Data Source | Schema Support | RAG Support | Calc Support | Current Status | Primary Architectural Gap |
|---|---|---|---|---|---|---|---|---|---|
| **Q58** | Invoice Analysis | Invoices with gross value > $50k | SQL | `invoices` | Yes (`grand_total_amount`) | N/A | No | **SUPPORTED** | Simple single-table aggregate filter. |
| **Q59** | Invoice Analysis | Invoices due in next 7 days > $10k | SQL | `invoices`, `payment_obligations` | Yes (`due_date`, `grand_total`) | N/A | No | **PARTIALLY SUPPORTED** | LLM lacks system clock / anchor date awareness. |
| **Q60** | Invoice Analysis | Potential duplicate invoices (amount & date) | SQL | `invoices` | Yes (`vendor_id`, `amount`, `date`) | N/A | No | **PARTIALLY SUPPORTED** | Self-join / `HAVING COUNT(*) > 1` triggers AST subquery bugs. |
| **Q61** | Invoice Analysis | Average time issue date to final approval | SQL | `invoices`, `workflow_history` | **NO** (`workflow_history` blocked) | N/A | Possibly | **NOT SUPPORTED** | `workflow_history` table barred from SQL allowlist. |
| **Q62** | Invoice Analysis | Invoices with express/air freight line items | SQL / RAG | `invoice_line_items` | Yes (`description`) | Yes | No | **PARTIALLY SUPPORTED** | SQL limited to 15 rows; RAG limited to top 5 chunks. |
| **Q63** | Payment Oblig. | Cash required to settle invoices due this week | SQL | `payment_obligations` | Yes (`amount_due`, `due_date`) | N/A | Yes | **NOT SUPPORTED** | No system date awareness; no cross-currency exchange rate. |
| **Q64** | Payment Oblig. | Total AP past due > 30 days | SQL | `payment_obligations` | Yes (`due_date`, `amount_due`) | N/A | No | **PARTIALLY SUPPORTED** | Relative date arithmetic vulnerable in Text-to-SQL. |
| **Q65** | Payment Oblig. | Portfolio savings if all early discounts paid | SQL + Calc | `payment_obligations` | Partial (often text only) | Partial | **NO** (scalar) | **NOT SUPPORTED** | Calculator cannot iterate or aggregate across portfolio rows. |
| **Q66** | Payment Oblig. | Liabilities scheduled for 30, 60, 90 days | SQL | `payment_obligations` | Yes (`due_date`, `amount_due`) | N/A | No | **PARTIALLY SUPPORTED** | Multi-bucket SQL CASE statements fail without system date. |
| **Q67** | Status | Invoices in Pending Approval > 5 business days | SQL | `documents`, `workflow_history` | **NO** (`workflow_history` blocked) | N/A | No | **NOT SUPPORTED** | Status transition timestamps in blocked `workflow_history`. |
| **Q68** | Status | Department/cost center with most unvalidated | SQL | `documents`, `invoices` | **NO** (Columns do not exist) | N/A | No | **NOT SUPPORTED** | Schema lacks `department` and `cost_center` columns. |
| **Q69** | Status | Invoices rejected this month and notes why | SQL | `documents`, `workflow_history` | **NO** (`workflow_history` blocked) | N/A | No | **NOT SUPPORTED** | Rejection comments stored in blocked `workflow_history`. |
| **Q70** | Status | % invoices processed without manual intervention | SQL | `documents`, `audit_logs` | **NO** (`audit_logs` blocked) | N/A | Yes | **NOT SUPPORTED** | `audit_logs` table barred from SQL allowlist. |
| **Q71** | Contractual | Vendors operating under Net 60 or longer | SQL / RAG | `payment_obligations` / Chunks | Partial (terms in text) | **NO** (top 5) | No | **NOT SUPPORTED** | Global RAG top 5 cannot enumerate vendors across system. |
| **Q72** | Contractual | How many invoices have late penalty clauses | RAG | Document Chunks (TERMS) | No | **NO** (top 5) | No | **NOT SUPPORTED** | Semantic RAG cannot count or perform full-corpus boolean check. |
| **Q73** | Contractual | Suppliers shipping under DDP Incoterms | RAG | Document Chunks (TERMS) | No (`incoterms` not in DB) | **NO** (top 5) | No | **NOT SUPPORTED** | Incoterms not in relational schema; RAG misses non-top-5 docs. |
| **Q74** | Contractual | Different unit prices for same SKU across invoices | SQL | `invoice_line_items` | Partial (no `sku` column) | No | No | **NOT SUPPORTED** | No normalized SKU column; line description OCR variance. |
| **Q75** | Comparative | Spend Vendor A vs Vendor B past 2 quarters | SQL + Calc | `invoices`, `vendors` | Yes (`grand_total`, `vendor_id`) | N/A | Yes | **PARTIALLY SUPPORTED** | Works if dates are explicit; fails on relative quarter offsets. |
| **Q76** | Comparative | Turnaround time PO vs non-PO invoices | SQL | `documents`, `workflow_history` | **NO** (`workflow_history` blocked) | N/A | Yes | **NOT SUPPORTED** | Approval turnaround timestamps in blocked `workflow_history`. |
| **Q77** | Comparative | Higher volume of freight charges: Q1 vs Q2 | SQL | `invoices` | Yes (`shipping_amount`, `date`) | N/A | No | **SUPPORTED** | Exists in `invoices.shipping_amount`; aggregate query works. |
| **Q78** | Comparative | Payment terms Supplier X vs Supplier Y | SQL / RAG | `payment_obligations` / Chunks | Partial (`payment_terms`) | Partial | No | **NOT SUPPORTED** | Unstructured contract comparison fails across separate vendors. |
| **Q79** | Multi-Step | Pending >$20k with early discount & cash savings | SQL + Calc | `invoices`, `payment_obligations` | Yes | Partial | **NO** (scalar) | **NOT SUPPORTED** | Multi-step chaining exceeds 5 iterations; calc cannot batch. |
| **Q80** | Multi-Step | Overdue invoices with active unbilled POs | SQL | `payment_obligations`, `purchase_orders` | **NO** (No PO table) | N/A | No | **NOT SUPPORTED** | No Purchase Orders table or PO billing status tracking. |
| **Q81** | Multi-Step | Outstanding amount flagged for PO price variance | SQL | `payment_obligations`, `validation_results` | Partial (`issues` JSONB) | N/A | No | **NOT SUPPORTED** | TextToSQL cannot parse complex JSONB `issues` arrays. |

---

## 14. Root-Cause Analysis

### Category A: Prompt Problems
- The system prompt is static and omits runtime contextual anchors (current date, user role).
- Tool calling parameters (e.g. `document_ids` for RAG, structured arguments for calculator) are completely undocumented.
- The prompt instructs the model to suppress tool call and provenance details, conflicting with enterprise citation requirements.

### Category B: Tool Definition Problems
- `financial_calculator_tool` defines only scalar inputs (`expression`, `gross_amount`, `discount_percentage`). It cannot accept array structures, tabular rows, or list aggregates.
- `database_query_tool` defines only a natural language string input, forcing a lossy double-hop LLM generation step.

### Category C: Tool Invocation & Orchestration Problems
- `MAX_ITERATIONS = 5` is insufficient for multi-step reasoning (e.g. SQL filter $\rightarrow$ RAG text retrieval $\rightarrow$ multi-invoice calculation $\rightarrow$ synthesis).
- `_is_redundant_query` utilizes crude Jaccard token overlap ($\ge 70\%$) to terminate loops, falsely intercepting valid iterative refinements.

### Category D: Database & Schema Problems
- **Total Absence of Purchase Orders Table**: The system has no concept of PO records, PO line items, or unbilled PO tracking.
- **Missing Workflow History Table from SQL Allowlist**: `workflow_history` is barred from text-to-SQL execution, blinding the chatbot to approval timestamps and human rejection reasons.
- **Missing Domain Columns**: No `department`, `cost_center`, `sku`, or `incoterms` fields exist in normalized business tables.
- **No Exchange Rate Normalization**: Cross-currency sums sum heterogeneous currencies directly without normalization.

### Category E: SQL Generation Problems
- Secondary LLM call in `TextToSQLService` operates in a vacuum without conversation context.
- Silent fallback to `_heuristic_sql_fallback` executes misleading dummy queries upon SQL error.
- No awareness of relative date resolution (`CURRENT_DATE`, calendar weeks, business days).

### Category F: Authorization Problems
- AST authorization predicate injection fails on complex subqueries, CTEs, and aliases, attaching inner table predicates to the outer query block and causing Postgres `missing FROM-clause` errors.
- Unconditional rejection of `exp.Union` prevents multi-set combining queries.

### Category G: RAG Retrieval Problems
- Hard limit of `top_k = 5` makes whole-portfolio contractual inquiries mathematically impossible.
- Complete absence of metadata pre-filtering (by date, vendor, status, or amount) forces vector search to compete against irrelevant portfolio noise.
- Vector search cannot perform counting, boolean aggregation, or exhaustive listing.

### Category H: Financial Calculator Limitations
- Pure scalar AST parser. Cannot perform column sums, weighted averages, or row-by-row discount computations.

### Category I: Context & Memory Problems
- `ChatHistoryRepository.get_langchain_history` serializes prior turns into plain text `HumanMessage` and `AIMessage`, completely discarding raw `ToolMessage` contents and intermediate tabular rows.

---

## 15. Required Capabilities for a Production-Useful Global Chatbot

To reliably answer questions Q58–Q81, an enterprise financial chatbot architecture requires:

1. **Direct Agent SQL Generation**: Eliminate the secondary nested LLM call. The agent LLM should generate SQL directly via specialized database inspection tools (schema schema-viewer, query planner).
2. **Schema Whitelist Expansion**:
   - Safely expose `workflow_history` (read-only, scoped to non-deleted documents).
   - Safely expose `audit_logs` (read-only, scoped).
   - Model Purchase Orders as a queryable entity (or extract PO headers into a queryable projection).
   - Promote `cost_center`, `department`, and `incoterms` into indexed relational columns.
3. **Temporal Awareness & Clock Injection**: Inject the exact UTC date, day of week, current month, and quarter into the agent system prompt and Text-to-SQL context.
4. **Vector RAG Metadata Pre-Filtering & Chunk Expansion**:
   - Support structured metadata pre-filters on `document_chunks` (filter by `vendor_id`, `document_type`, `date_range`, `section`).
   - Increase global candidate pool when answering enumeration questions or route to SQL where structured fields exist.
5. **Batch/Tabular Financial Calculator**:
   - Enhance the calculator to accept tabular arrays of rows (e.g. `calculate_aggregate_discount(rows=[...])`).
   - Provide deterministic aggregations (`sum`, `average`, `variance`, `currency_convert`).
6. **Subquery-Safe AST Rewriting**:
   - Refactor AST predicate injection in `TextToSQLService` to inject scoping predicates directly into the specific sub-AST clause where the target table is declared.
7. **Full Tool History Restoration**:
   - Restore raw tool execution records into conversation memory so follow-up turns retain intermediate tabular facts.
8. **Unified Provenance & Citation Pipeline**:
   - Track provenance for SQL records (`table:id`) and calculator formulas alongside OCR chunks, presenting grounded evidence in the UI.

---

## 16. Proposed Future Architecture (Design Only)

*Note: This architecture is proposed for future planning and is NOT implemented.*

```
                                  [ USER QUERY ]
                                        │
                                        ▼
                     POST /api/v1/chat/corpus/messages
                                        │
                                        ▼
                            Context & Clock Resolver
                  (Inject UTC Timestamp, Resolve Antecedents)
                                        │
                                        ▼
                     Global Financial Planner & Agent
                      (Stateful Tool Calling Engine)
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
 [Database Toolset]             [Document RAG Tool]            [Batch Calculator]
 1. get_schema_context          1. hybrid_search               1. evaluate_expression
 2. execute_scoped_sql             - Query semantic search     2. batch_discount_calc
    - Direct Agent SQL             - Metadata pre-filter          (consumes SQL rows)
    - Clause-level AST scoping       (vendor, date, section)   3. aggregate_columns
    - Full row-set streaming       - Dynamic top-k (up to 20)  4. currency_convert
        │                               │                               │
        └───────────────────────────────┼───────────────────────────────┘
                                        ▼
                            Intermediate State Buffer
                     (Preserves tabular rows & chunk text)
                                        │
                                        ▼
                            Evidence & Grounding Synthesizer
                    - Reconciles relational numbers with OCR text
                    - Formats multi-tier citations:
                      [Relational: Invoices #104, #108]
                      [OCR: Doc #12, Page 2, Terms]
                      [Calculation: $150,000 * 0.02 = $3,000]
                                        │
                                        ▼
                            Final Grounded Response
```

### Architectural Distinctions from Current System
1. **Single-Hop Tool Execution**: The agent writes SQL directly using schema inspection tools, eliminating the brittle 2-phase text-to-SQL translation and removing the silent heuristic fallback.
2. **Tabular Data Passing**: Tool outputs pass structured JSON arrays that the batch calculator can consume directly without manual number re-typing by the LLM.
3. **Metadata-Constrained RAG**: RAG retrieval filters by document metadata (e.g. `section='PAYMENT'`, `vendor='ACME'`) before computing vector distance.
4. **Comprehensive Provenance**: Citations capture database rows, document chunks, and calculation formulas uniformly.

---

## 17. Security Requirements

Any future implementation must strictly preserve and reinforce the following security invariants:

1. **Non-Bypassable Server-Side Authorization**:
   - The user identity (`user.id`, `user.role`) must always be derived from trusted backend authentication context. It must never be accepted as a parameter from the LLM or client.
2. **Clause-Level SQL AST Validation**:
   - Must continue using AST parsers (`sqlglot`) to strictly enforce `SELECT`-only execution.
   - Prohibit DDL, DML, write operations, and PostgreSQL system/file functions (`pg_read_file`, `dblink`, etc.).
   - Enforce read-only database connections (`SET TRANSACTION READ ONLY`) and statement execution timeouts (5000ms max).
3. **Strict Column & Table Whitelisting**:
   - `users.password_hash` and sensitive auth tokens must remain strictly barred from AST column allowlists.
   - Any access to newly exposed tables (`workflow_history`, `audit_logs`) must be read-only and strictly scoped to non-deleted documents matching the user's role policy.
4. **Pre-Retrieval Vector Isolation**:
   - Vector similarity search and full-text search must continue applying SQL-level tenant isolation predicates *before* distance calculation, guaranteeing that unauthorized chunks are never resident in memory.
5. **Prompt Injection & Data Leakage Defenses**:
   - Unstructured OCR text from uploaded documents must be treated as untrusted data. Tool observation wrappers must escape and delimit document content to prevent prompt injection from executing unauthorized tool calls.

---

## 18. Recommended Implementation Phases (Proposal Only)

*The following phases represent an architectural roadmap for future review and approval. No code changes are implemented at this time.*

### Phase 1: Temporal Awareness & Prompt Normalization
- Inject current UTC timestamp, day of week, and current calendar quarter into the agent system prompt.
- Explicitly document all tool arguments (`document_ids`, `action`, `expression`) in the prompt.
- Eliminate the static prompt role restriction and dynamically tailor system instructions based on `user.role`.

### Phase 2: Schema Allowlist Expansion & Direct SQL Capabilities
- Add `workflow_history` to `ROLE_ALLOWED_TABLES` with safe column whitelisting (`id`, `document_id`, `action`, `from_status`, `to_status`, `comment`, `created_at`).
- Fix the `TextToSQLService` AST injection bug by scoping predicates to the specific sub-AST clause where the table is instantiated.
- Eliminate `_heuristic_sql_fallback`; surface clear SQL errors to the agent so it can re-plan rather than presenting misleading dummy data.

### Phase 3: Batch Financial Calculator Tool
- Extend `FinancialCalculatorTool` with `batch_calculate_discounts` and `aggregate_column` operations that directly ingest tabular rows returned by SQL.
- Implement basic cross-currency normalization flags.

### Phase 4: Metadata-Filtered RAG & Dynamic Top-K
- Implement pre-retrieval metadata filtering on `document_chunks` (filter by `section`, `document_type`, `vendor_id`).
- Increase `final_top_k` dynamically based on query type (e.g. 5 for single-document queries, up to 20 for portfolio surveys).

### Phase 5: ReAct Orchestration & Memory Refinement
- Increase `MAX_ITERATIONS` from 5 to 8 for complex multi-step workflows.
- Replace the token-overlap loop guard with an semantic progress detector.
- Rehydrate raw `ToolMessage` structures in `get_langchain_history` to preserve tabular facts across conversation turns.

### Phase 6: Provenance & Multi-Tier Evidence Grounding
- Update `DatabaseQueryTool` and `FinancialCalculatorTool` to record structured provenance logs.
- Update frontend and response schemas to display relational database evidence alongside OCR grounding references.

---

## 19. Files Likely Requiring Modification

*(When future implementation is approved)*

1. `backend/app/rag/global_agent.py`: System prompt rewrite, clock injection, loop guard replacement, iteration increase.
2. `backend/app/services/text_to_sql_service.py`: Schema expansion (`workflow_history`), AST subquery injection fix, removal of silent fallback, clock injection in SQL prompt.
3. `backend/app/rag/tools/database_tool.py`: Result truncation threshold adjustment, SQL provenance capture.
4. `backend/app/rag/tools/calculator_tool.py`: Batch calculation schemas, multi-row inputs.
5. `backend/app/rag/financial_calculator.py`: Tabular evaluation, list reductions.
6. `backend/app/rag/tools/rag_tool.py`: Exposure of metadata filter arguments (`section`, `vendor_id`).
7. `backend/app/services/rag_service.py`: Dynamic top-k handling, metadata pre-filtering in vector/FTS queries.
8. `backend/app/repositories/chat_history_repository.py`: Rehydration of `ToolMessage` instances in conversation history.
9. `backend/app/schemas/chat.py`: Multi-tier evidence/citation schemas (SQL + RAG + Calc).
10. `frontend/src/pages/GlobalChatPage.tsx`: Rendering of relational and calculation evidence badges.

---

## 20. Risks and Open Questions

1. **Absence of Real Purchase Order Records**:
   - *Risk*: Target questions Q76, Q80, and Q81 assume the existence of a Purchase Orders table with open/unbilled statuses. Because EFDI only extracts invoice headers and line items, answering these questions requires either ingesting actual PO documents or defining a new PO entity model.
   - *Question*: Will the client provide PO document samples for ingestion, or should PO comparisons be scoped strictly to PO-referencing invoices (`document_type = 'POI'`)?
2. **Context Window vs. Large Portfolio Queries**:
   - *Risk*: Increasing SQL row limits or RAG top-k increases token consumption and risks exceeding the context window of `mistral-small-2603`.
   - *Mitigation*: Tabular aggregation should occur inside PostgreSQL or the calculator tool rather than dumping hundreds of raw rows into LLM context.
3. **Multi-Currency Portfolios**:
   - *Risk*: Summing invoices across different currencies without exchange rates creates inaccurate financial metrics.
   - *Question*: Should the system introduce a static or API-backed exchange rate table, or restrict aggregations to single-currency groupings?
4. **Performance of Cross-Encoder Reranking on Larger Candidate Pools**:
   - *Risk*: Increasing RAG retrieval candidates from 25 to 100 for global enumeration queries will increase cross-encoder reranking latency on CPU.
   - *Mitigation*: Leverage PostgreSQL FTS for keyword-exact contractual terms before falling back to cross-encoder reranking.
