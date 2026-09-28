# EFDI — Conversation Context & Memory Implementation Record

This document records the narrowly scoped two-level implementation addressing conversation context, history correctness, state management, and redundant tool-loop prevention in EFDI, as approved from [CONVERSATION_CONTEXT_AND_MEMORY_AUDIT.md](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docs/CONVERSATION_CONTEXT_AND_MEMORY_AUDIT.md).

---

## 1. Summary of Changes

The implementation delivers two distinct tiers of enhancements without modifying the core OCR, extraction, classification, RAG retrieval (pgvector, FTS, RRF, CrossEncoder), SQL AST authorization, RBAC, or calculator architectures:

- **Level 1 — Immediate Correctness & Robustness:**
  - True sliding window for chat history (`created_at DESC, id DESC LIMIT N`, reversed in application code).
  - Configurable history window (`settings.CHAT_HISTORY_LIMIT = 10`).
  - Redundant tool-call loop guard within single ReAct agent turns preventing identical or substantially similar repeated queries (Jaccard similarity threshold $\ge 0.70$).
  - Tool provenance preservation in historical turns (`AIMessage.additional_kwargs["has_verified_tool_evidence"]` and `tool_calls`).

- **Level 2 — Conversational Context Resolver & Structured Conversation State:**
  - Dedicated `ConversationContextResolver` in [context_resolver.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/context_resolver.py) that resolves affirmations ("yes", "sure"), negations ("no", "cancel"), anaphora ("it", "that"), ordinals ("second item"), and flags ambiguous references without hallucination.
  - Negative confirmation bypass: "no" directly acknowledges user decline without invoking ReAct agent or document RAG tools.
  - Ambiguous query interception: ungrounded elliptical references return polite clarification without tool invocation.
  - Lightweight structured session state (`state_json` JSONB column in `chat_sessions` table via Alembic migration `2f07f92cbbd1`) storing `active_document_id`, `pending_offer`, and bounded `verified_facts`.
  - Pending assistant offer lifecycle: captures assistant proposals requiring confirmation, resolves follow-ups against them, and clears them after execution or rejection so they never loop.
  - System prompt additions for [DocumentReActAgent](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py) and [GlobalReActAgent](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py) instructing grounding precedence and termination upon missing evidence.

---

## 2. Level 1 Changes

### 2.1 Sliding Window Ordering Fix
- **Location:** [chat_history_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py) (`get_session_history`).
- **Defect Fixed:** Previously, the repository queried `order_by(ChatMessage.created_at.asc()).limit(limit)`. Once a conversation reached $>10$ messages, only the oldest 10 messages were returned indefinitely, dropping all recent conversational turns.
- **Implementation:**
  ```python
  stmt = (
      select(ChatMessage)
      .where(ChatMessage.session_id == session_id)
      .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
      .limit(limit)
  )
  messages = list(self.db.scalars(stmt).all())
  messages.reverse()
  return messages
  ```
  Messages are fetched newest-first, tied by `id.desc()`, and then reversed in Python so the LLM receives the newest $N$ messages in chronological order (`oldest -> newest`).

### 2.2 History Window Configuration
- **Location:** [config.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/config.py)
- **Setting:** `CHAT_HISTORY_LIMIT: int = 10` (default 10 individual messages, preserving the established parameter while remaining configurable via environment variables).

### 2.3 Redundant Tool-Call Loop Guard
- **Locations:** [document_agent.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py) and [global_agent.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py).
- **Mechanism:** Tracks executed `(tool_name, query_str)` tuples/dicts within a single ReAct turn.
  - Matches exact duplicate queries for any tool.
  - Calculates keyword Jaccard overlap (excluding common stopwords and short tokens) for `document_rag_tool`. If overlap is $\ge 0.70$, the search is identified as redundant.
  - Injects a synthetic `ToolMessage` informing the agent that an equivalent search was already executed and yielded no additional clauses, breaking the loop to grounded synthesis and preventing the 5-iteration runaway loop observed on Document `#1876`.
  - Legitimate distinct queries and separate tools (e.g. `financial_calculator_tool` vs `document_rag_tool`) are never blocked.

### 2.4 Historical Tool Provenance
- **Location:** [chat_history_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chat_history_repository.py) (`get_langchain_history`).
- **Implementation:** Attaches `tool_calls` and `has_verified_tool_evidence: bool` to `AIMessage.additional_kwargs`. Assistant messages without verified tool calls are marked as `has_verified_tool_evidence = False`, preventing conversational claims from masquerading as verified evidence.

---

## 3. Level 2 Changes

### 3.1 Conversation Context Resolver
- **Location:** [context_resolver.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/context_resolver.py).
- **Class:** `ConversationContextResolver` returning `ContextResolutionResult`.
- **Pipeline Position:** Placed between incoming user message retrieval and ReAct agent routing in both [ChatService](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py) and [global_chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py).
- **Behaviors:**
  1. **Empty History Bypass:** If conversation history is empty, passes raw query immediately.
  2. **Standalone Interrogative Fast-Path:** Queries matching standalone interrogative patterns (e.g., "What is the invoice date?", "Who is the supplier?") without reference triggers bypass LLM rewriting completely.
  3. **Affirmative Resolution ("yes", "sure", "please do"):**
     - Resolves against active `pending_offer` in session state or preceding assistant question.
     - Rewrites into explicit action query (e.g., "Check the document for other payment-related terms such as payment terms, early settlement discounts, due dates, or contractual penalties.").
     - Never re-anchors to older questions (e.g., bank account).
  4. **Negative Confirmation ("no", "cancel", "stop"):**
     - Returns `action_type = "confirmation_negative"`.
     - `ChatService` / `global_chat` clears pending offers and responds politely without triggering any RAG or tool execution.
  5. **Ambiguous Reference Detection ("what about that?"):**
     - If no antecedent exists, marks `is_ambiguous = True` and `action_type = "clarification"`.
     - Returns polite clarification prompt without hallucinating facts or invoking tools.
  6. **Elliptical / Anaphora Resolution:**
     - Uses lightweight agent LLM call to resolve references (e.g. "second item" -> explicit item details) strictly grounded in prior conversation messages.

### 3.2 Structured Conversation State
- **Database Schema:** Added `state_json: JSONB` to `chat_sessions` table via Alembic migration `2f07f92cbbd1_add_state_json_to_chat_sessions.py`. Defaults to `'{}'::jsonb`.
- **State Fields:**
  - `active_document_id`: Integer ID of the active authorized document.
  - `pending_offer`: `{"offer_text": str, "action_query": str, "user_confirmation_expected": bool}` tracking the latest assistant offer requiring confirmation.
  - `verified_facts`: Bounded list of verified observations derived strictly from tool executions (never from unsupported assistant prose).
- **Lifecycle:**
  - When an offer is accepted and executed, `pending_offer` is cleared.
  - When a user rejects with "no", `pending_offer` is cleared.
  - When a new assistant response ends with an offer question, `extract_pending_offer()` updates `pending_offer`.
  - When history is cleared, `state_json` resets to `{}`.

### 3.3 Prompt Enhancements
- **Locations:** `DOCUMENT_REACT_SYSTEM_PROMPT` in [document_agent.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/document_agent.py) and `GLOBAL_REACT_SYSTEM_PROMPT` in [global_agent.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/global_agent.py).
- Added instructions on dialogue continuity, tool evidence precedence over conversational text, reporting missing evidence clearly instead of repeatedly querying, and avoiding repeating accepted offers.

---

## 4. Context Flow

```text
User Message
     │
     ▼
ChatService / GlobalChatRouter
     │
     ├── Fetch Recent History (DESC limit N, reversed in Python: oldest -> newest)
     └── Fetch Structured Session State (active_doc, pending_offer, verified_facts)
     │
     ▼
ConversationContextResolver
     ├── Standalone Query? ───────────────► Pass through raw query
     ├── Negative ("no")? ────────────────► Clear offer, return acknowledgment (NO RAG)
     ├── Ambiguous? ──────────────────────► Return clarification request (NO RAG)
     └── Affirmative / Elliptical? ───────► Contextualize using offer / history
     │
     ▼
Contextualized Query
     │
     ▼
DocumentReActAgent / GlobalReActAgent
     ├── Loop Guard (checks exact & Jaccard overlap against executed queries)
     ├── Existing Tools (document_rag_tool, financial_calculator_tool, sql_query_tool)
     └── Grounded Synthesis (verified tool observations take precedence)
     │
     ▼
State & History Update
     ├── Clear / update pending_offer in state_json
     ├── Append verified tool calls to verified_facts
     └── Persist user & assistant messages with citations and tool metadata
```

---

## 5. Files Changed

| File Path | Nature of Change |
|---|---|
| `backend/app/core/config.py` | Added `CHAT_HISTORY_LIMIT: int = 10` |
| `backend/app/models/chat.py` | Added `state_json: Mapped[dict] = mapped_column(JSONB, nullable=True, server_default=text("'{}'::jsonb"))` to `ChatSession` |
| `backend/alembic/versions/2f07f92cbbd1_add_state_json_to_chat_sessions.py` | Alembic migration adding `state_json` column |
| `backend/app/repositories/chat_history_repository.py` | Fixed sliding window ordering, added `get_session_state` and `update_session_state`, reset state in `clear_session_history`, tracked tool evidence in `get_langchain_history` |
| `backend/app/rag/context_resolver.py` | Created `ConversationContextResolver` and `ContextResolutionResult` |
| `backend/app/rag/document_agent.py` | Added conversational continuity prompt rules, implemented `_is_redundant_query` loop guard |
| `backend/app/rag/global_agent.py` | Added conversational continuity prompt rules, implemented `_is_redundant_query` loop guard |
| `backend/app/services/chat_service.py` | Integrated context resolver, handled negative/ambiguous cases, updated session state lifecycle |
| `backend/app/routers/global_chat.py` | Integrated context resolver, handled negative/ambiguous cases, updated session state lifecycle |
| `backend/tests/test_conversation_context.py` | Test suite covering all 10 required test scenarios |

---

## 6. Verification and Test Results

The implementation was validated against all 10 required test scenarios in [test_conversation_context.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_conversation_context.py) plus existing regression suites:

1. **TEST 1 — Reported "yes" scenario:** Verified that "yes" following an assistant payment-terms offer resolves to checking payment terms and does not revert to bank account query (`test_reported_yes_scenario_resolution` - **PASSED**).
2. **TEST 2 — Negative confirmation:** Verified that "no" clears the pending offer and responds without invoking RAG or agent tools (`test_negative_confirmation_no_rag` - **PASSED**).
3. **TEST 3 — Recent history window:** Verified that when 15 messages exist, `get_session_history` returns messages 6–15 in chronological order (`test_recent_history_window_ordering` - **PASSED**).
4. **TEST 4 — Elliptical reference:** Verified that "What about the second item?" resolves to item #2 from dialogue history without hallucinations (`test_elliptical_reference_resolution` - **PASSED**).
5. **TEST 5 — Ambiguous reference:** Verified that "What about that?" with no antecedent flags ambiguity and asks for clarification without running tools (`test_ambiguous_reference_requests_clarification` - **PASSED**).
6. **TEST 6 — Wrong assistant answer:** Verified that assistant claims without tool citations are never promoted to `verified_facts` (`test_unsupported_assistant_claim_not_promoted_to_verified_facts` - **PASSED**).
7. **TEST 7 — Pending offer lifecycle:** Verified that after accepting an offer with "yes", the offer is cleared and does not repeat on subsequent turns (`test_pending_offer_lifecycle` - **PASSED**).
8. **TEST 8 — Standalone query bypass:** Verified that standalone queries bypass LLM resolution without rewriting (`test_standalone_query_bypass` - **PASSED**).
9. **TEST 9 — Tool-loop prevention:** Verified that identical or $\ge 0.70$ Jaccard duplicate searches are suppressed while distinct tools/queries proceed (`test_tool_loop_prevention` - **PASSED**).
10. **TEST 10 — Authorization boundary:** Verified that User B cannot access User A's document or conversation history (`test_authorization_boundary_unauthorized_document` - **PASSED**).

**Full Test Suite Summary:**
- `tests/test_conversation_context.py`: **10 passed** (100%)
- `tests/test_chat_document.py` & `tests/test_global_agent.py`: **17 passed** (100%)
- `tests/test_react_agents.py` & `tests/test_react_tools.py`: **20 passed** (100%)

---

## 7. Out-of-Scope Confirmations

As mandated by the implementation boundaries, the following architectural components were **NOT modified**:
- OCR pipeline & Docling implementation
- `OCRResult` schema
- Extraction pipeline
- Classification pipeline
- Document RAG retrieval architecture (pgvector embeddings, PostgreSQL FTS, RRF, Cross-Encoder reranker)
- `DocumentChunk` schema
- Financial calculator logic
- Text-to-SQL query generation & AST authorization
- RBAC, user authorization & document access rules
- Existing tool implementations
- Frontend / UI
- No new vector database, Redis memory, or LangGraph introduced

---

## 8. Remaining Limitations (Intentionally Unimplemented)

The following items from the forensic audit remain intentionally unimplemented as they were explicitly classified as Tier 3 / out-of-scope:
- Long-term semantic conversational retrieval across older sessions
- Dedicated conversation vector embeddings or memory vector store
- Redis-based conversation caching
- Asynchronous hierarchical conversation summarization jobs
