# EFDI Forensic Audit: Historical Tool-Call Serialization Failure

## 1. Executive Summary

When a user submits a second conversational turn (e.g., *"Give it in a tabular format"*) following an assistant response that executed specialized tools, the backend crashes with an **HTTP 502 Bad Gateway**.

The stack trace terminates inside `langchain_mistralai/chat_models.py` at `_convert_message_to_mistral_chat_message()`:
```python
"name": tc["function"]["name"],
KeyError: 'function'
```

### Forensic Verdict
The failure is caused by a **schema collision** between EFDI's application-level tool execution log and LangChain's wire-level LLM tool-calling protocol.

Specifically, in `ChatHistoryRepository.get_langchain_history()`, EFDI's UI tool execution logs stored in `ChatMessage.tool_calls` (e.g. `[{"tool": "document_rag_tool", "summary": "..."}]`) were packed into `AIMessage.additional_kwargs["tool_calls"]`.

In the LangChain/OpenAI/Mistral ecosystem, `additional_kwargs["tool_calls"]` is a **reserved wire-protocol key**. The `langchain_mistralai` adapter assumes that any dictionary in `additional_kwargs["tool_calls"]` follows the raw OpenAI function-calling format:
```json
{
  "id": "...",
  "type": "function",
  "function": {
    "name": "...",
    "arguments": "..."
  }
}
```

When Mistral's message converter encounters EFDI's UI summary dictionary, it attempts to access `tc["function"]["name"]`, triggering `KeyError: 'function'`.

Furthermore, if this dictionary were formatted to satisfy the Mistral adapter, Mistral's converter would execute:
```python
if tool_calls and content:
    content = ""
```
This would **wipe out the assistant's previous conversational content**, blinding the LLM to its own prior answer and causing Mistral's API to reject the request for having tool calls without corresponding `ToolMessage` replies.

The issue was introduced in the recent conversation-context changes in commit `42ec4cf` when `additional_kwargs["tool_calls"]` was added to `AIMessage` in `get_langchain_history()`.

---

## 2. Exact Failure Trace

The complete runtime call stack for the observed failure:

```
FastAPI Router: /api/v1/chat/documents/{id}/messages (or /api/v1/chat/corpus/messages)
    │
    ▼
ChatService.send_document_message()
    │
    ▼
ChatHistoryRepository.get_langchain_history(session_id)
    │  Constructs:
    │  AIMessage(
    │      content="The payment terms are Net 30...",
    │      additional_kwargs={
    │          "tool_calls": [{"tool": "document_rag_tool", "summary": "..."}],
    │          "has_verified_tool_evidence": True
    │      }
    │  )
    │
    ▼
DocumentReActAgent.run(..., history=history_messages)
    │
    ▼
messages = [SystemMessage(...), HumanMessage(...), AIMessage(...), HumanMessage("Give it in a tabular format")]
    │
    ▼
llm_with_tools.invoke(messages)
    │
    ▼
ChatMistralAI._generate(messages, ...)
    │
    ▼
ChatMistralAI._create_message_dicts(messages, ...)
    │
    ▼
_convert_message_to_mistral_chat_message(message=AIMessage)
    │
    │  Line 495 in langchain_mistralai/chat_models.py:
    │  elif "tool_calls" in message.additional_kwargs:
    │      for tc in message.additional_kwargs["tool_calls"]:
    │          chunk = {
    │              "function": {
    │                  "name": tc["function"]["name"],      <--- CRASH: KeyError: 'function'
    │                  "arguments": tc["function"]["arguments"],
    │              }
    │          }
    │
    ▼
Exception caught in DocumentReActAgent:
    logger.error("[DocumentReActAgent] LLM invocation failed...")
    raise AIServiceException("Something went wrong while processing your request. Please try again.")
    │
    ▼
FastAPI Exception Handler:
    HTTP 502 Bad Gateway
```

---

## 3. Actual Historical Message Structure

### What is stored in PostgreSQL (`chat_messages.tool_calls`):
When an assistant message is persisted after executing a tool, the database contains:
```json
[
  {
    "tool": "document_rag_tool",
    "retrieved_count": 5,
    "scoped_documents": [1],
    "summary": "Retrieved 5 evidence chunk(s) from Document #1"
  }
]
```
For calculator tools:
```json
[
  {
    "tool": "financial_calculator_tool",
    "expression": "1320 * (1 - 0.02)",
    "result": "1293.6",
    "summary": "Calculated 1320 * (1 - 0.02) = 1293.6"
  }
]
```
For database query tools:
```json
[
  {
    "tool": "database_query_tool",
    "sql": "SELECT COUNT(*) FROM documents WHERE status = 'VALIDATED'",
    "row_count": 1,
    "summary": "Retrieved 1 row(s)"
  }
]
```

### What `get_langchain_history()` passes to LangChain:
```python
AIMessage(
    content="The payment terms are Net 30 with 2% discount within 10 days.",
    additional_kwargs={
        "tool_calls": [
            {
                "tool": "document_rag_tool",
                "retrieved_count": 5,
                "scoped_documents": [1],
                "summary": "Retrieved 5 evidence chunk(s) from Document #1",
            }
        ],
        "has_verified_tool_evidence": True,
    },
)
```

The object missing `"function"` is:
```python
{
    "tool": "document_rag_tool",
    "retrieved_count": 5,
    "scoped_documents": [1],
    "summary": "Retrieved 5 evidence chunk(s) from Document #1",
}
```
This dictionary has keys `["tool", "retrieved_count", "scoped_documents", "summary"]`.  
It contains **no `"function"` key**.

---

## 4. Tool-Call Persistence Flow

1. During turn 1, the ReAct agent executes tools (e.g. `DocumentRAGTool.invoke(tool_args)`).
2. The tool appends structured execution information to `self.execution_logs`.
3. The ReAct agent collects these logs into `chronological_tool_logs: List[Dict[str, Any]]`.
4. The agent returns `AgentResult(content=..., tool_calls=chronological_tool_logs, citations=...)`.
5. In `ChatService` and `GlobalChatRouter`:
   ```python
   assistant_msg = self.history_repo.add_message(
       session_id=session.id,
       role="assistant",
       content=agent_result.content,
       tool_calls=agent_result.tool_calls,
       citations=agent_result.citations,
   )
   ```
6. The `chat_messages` table stores this data in the `tool_calls` JSON column.
7. This persistence is **correct and intentional**: it is consumed by the frontend to render the collapsible tool execution badges (`"Executed 1 Specialized Tool"`, tool name, summary, SQL query, etc.).

---

## 5. Tool-Call Reconstruction Flow

When turn 2 begins:
1. `ChatService` queries recent messages via `ChatHistoryRepository.get_langchain_history(session_id)`.
2. Inside `get_langchain_history()` (`backend/app/repositories/chat_history_repository.py`, lines 139-144):
   ```python
   elif m.role == "assistant" and m.content:
       extra = {
           "tool_calls": m.tool_calls or [],
           "has_verified_tool_evidence": bool(m.tool_calls),
       }
       lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
   ```
3. This creates an `AIMessage` with `additional_kwargs["tool_calls"]` containing the application UI log list.

---

## 6. Mistral Adapter Expectation

In `langchain_mistralai` version 1.1.6 (`langchain_mistralai/chat_models.py` lines 480-515):

```python
    if isinstance(message, AIMessage):
        message_dict: dict[str, Any] = {"role": "assistant"}
        tool_calls: list = []
        if message.tool_calls or message.invalid_tool_calls:
            if message.tool_calls:
                tool_calls.extend(
                    _format_tool_call_for_mistral(tool_call)
                    for tool_call in message.tool_calls
                )
            if message.invalid_tool_calls:
                tool_calls.extend(
                    _format_invalid_tool_call_for_mistral(invalid_tool_call)
                    for invalid_tool_call in message.invalid_tool_calls
                )
        elif "tool_calls" in message.additional_kwargs:
            for tc in message.additional_kwargs["tool_calls"]:
                chunk = {
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    }
                }
                if _id := tc.get("id"):
                    chunk["id"] = _id
                tool_calls.append(chunk)
```

The adapter explicitly supports two paths for tool calls:
1. **LangChain Standard `message.tool_calls`**: A list of `ToolCall` TypedDicts (`{"name": str, "args": dict, "id": str}`).
2. **Provider Raw Wire `message.additional_kwargs["tool_calls"]`**: A list of OpenAI-formatted function call dicts (`{"id": str, "type": "function", "function": {"name": str, "arguments": str}}`).

Neither path permits arbitrary application metadata or UI logs under the key `"tool_calls"`.

---

## 7. First Point of Schema Mismatch

The schema mismatch occurs at:
**`backend/app/repositories/chat_history_repository.py`, line 141:**
```python
extra = {
    "tool_calls": m.tool_calls or [],   # <--- FIRST POINT OF SCHEMA MISMATCH
    "has_verified_tool_evidence": bool(m.tool_calls),
}
lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
```

The key `"tool_calls"` inside `additional_kwargs` is a reserved identifier in LangChain for provider-level function calling. Assigning EFDI's application UI dictionaries to this key violates the LangChain message contract.

---

## 8. Root Cause

1. **Semantic Ambiguity of `tool_calls`:**
   - In EFDI's database and frontend, `tool_calls` represents a human-readable *execution audit trail* (tool name, query summary, retrieved count, SQL query).
   - In LangChain and LLM APIs, `tool_calls` represents an active *instruction to the model orchestrator* to invoke external functions, requiring subsequent `ToolMessage` responses.
2. **Improper Injection into Wire Protocol:**
   - Packing the UI execution audit trail into `AIMessage.additional_kwargs["tool_calls"]` tricked the Mistral serializer into treating a finished conversational answer as an incomplete, active tool invocation.
3. **Absence of ToolMessage Sequence in History:**
   - In standard LLM tool calling, an `AIMessage` with tool calls must be followed by `ToolMessage` outputs. EFDI's database correctly stores the synthesized final answer, not the intermediate scratchpad iterations. Passing `tool_calls` on the final answer violates the chat completions conversational invariant.

---

## 9. Whether Recent Conversation-Context Changes Introduced It

**YES.**

Prior to the conversation-context commit, `get_langchain_history()` in `chat_history_repository.py` contained:
```python
elif m.role == "assistant" and m.content:
    lc_messages.append(AIMessage(content=m.content))
```
This was completely clean and functioned properly.

During the conversation-context implementation, the following lines were added:
```python
extra = {
    "tool_calls": m.tool_calls or [],
    "has_verified_tool_evidence": bool(m.tool_calls),
}
lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
```
This was added alongside a test in `test_conversation_context.py` line 340:
```python
assert lc_history[0].additional_kwargs.get("has_verified_tool_evidence") is False
```
Because that test only verified an assistant message where `tool_calls=[]` (empty list), the `for tc in message.additional_kwargs["tool_calls"]` loop had 0 iterations, masking the latent `KeyError` until a live turn with actual tool executions occurred.

---

## 10. Minimum Safe Fix

In `backend/app/repositories/chat_history_repository.py`, lines 139-144:

Change from:
```python
elif m.role == "assistant" and m.content:
    extra = {
        "tool_calls": m.tool_calls or [],
        "has_verified_tool_evidence": bool(m.tool_calls),
    }
    lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
```

To:
```python
elif m.role == "assistant" and m.content:
    extra = {
        "executed_tools": m.tool_calls or [],
        "has_verified_tool_evidence": bool(m.tool_calls),
    }
    lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
```

### Why this is the Minimum Safe Fix:
1. **Eliminates Schema Collision:** Renaming `"tool_calls"` to `"executed_tools"` ensures `langchain_mistralai`'s check (`elif "tool_calls" in message.additional_kwargs`) evaluates to `False`.
2. **Preserves Tool Provenance:** `has_verified_tool_evidence` remains accessible in `additional_kwargs` for any component that inspects provenance.
3. **Preserves Content:** Because `tool_calls` is not set on the `AIMessage`, Mistral's converter retains `message.content` intact.
4. **Preserves Conversation Continuity:** The LLM receives the assistant's actual previous response as conversational context, enabling follow-up questions like *"Give it in a tabular format"* to work seamlessly.
5. **Zero Impact on Database or Frontend:** The database column `ChatMessage.tool_calls` and the frontend UI remain 100% unchanged.

---

## 11. Alternatives Considered and Rejected

### Alternative A: Reconstruct Full `ToolMessage` ReAct History
- **Description:** Store every intermediate `AIMessage(tool_calls=[...])` and `ToolMessage(content=...)` in the database, and reconstruct the full ReAct loop in `get_langchain_history()`.
- **Rejected Because:** Violates strict scope, massively inflates token usage across multi-turn conversations, pollutes conversational history with ephemeral scratchpad data, and risks hitting model context limits.

### Alternative B: Convert EFDI UI Logs into Fake OpenAI Function Dictionaries
- **Description:** Wrap `m.tool_calls` into `{"function": {"name": ..., "arguments": ...}}`.
- **Rejected Because:** Mistral's adapter executes `if tool_calls and content: content = ""`, which wipes out the assistant's answer text! Furthermore, Mistral's API will reject the request if the assistant's tool call is not followed by a matching `ToolMessage`.

### Alternative C: Strip `additional_kwargs` Entirely (`AIMessage(content=m.content)`)
- **Description:** Return only `AIMessage(content=m.content)`.
- **Viable, but Slightly Inferior to Minimum Fix:** While this also fixes the bug completely, renaming `"tool_calls"` to `"executed_tools"` retains `has_verified_tool_evidence` and metadata without breaking existing tests.

---

## 12. Secondary `watchfiles` Finding

### Observation
The backend terminal displayed repeated events:
```
watchfiles.main | 1 change detected: Change.modified '...\\backend\\logs\\app.log'
```

### Forensic Analysis
1. **What file is changing?**  
   `backend/logs/app.log`.
2. **What process is modifying it?**  
   The application's own `RotatingFileHandler` configured in `app/core/logging_config.py`:
   ```python
   filename=os.path.join(settings.LOG_DIR, "app.log")  # settings.LOG_DIR = "logs"
   ```
3. **Why does watchfiles detect it?**  
   Uvicorn was started with:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   When run without `--reload-dir app` or `--reload-exclude "logs/*"`, `watchfiles` monitors the entire current directory (`backend/`) recursively. Every HTTP request or log message writes to `logs/app.log`, which `watchfiles` detects as a source code change, triggering an unnecessary server reload loop.
4. **Is it related to the KeyError?**  
   No. It is purely a development server configuration artifact.

---

## 13. Regression Risks

The minimum fix carries **zero regression risk** to:
- Context Resolver (it only inspects `m.role` and `m.content`).
- ReAct Agent execution (it operates normally on `messages`).
- RAG retrieval and vector search.
- Financial calculator and Text-to-SQL tools.
- PostgreSQL database schemas and migrations.
- Frontend rendering and badges.

---

## 14. Required Tests

A regression test should be added to verify multi-turn chat with historical tool execution:

```python
def test_historical_assistant_with_tool_calls_does_not_break_llm_serialization(db_session):
    """Verify assistant messages with tool_calls serialize cleanly into LangChain / Mistral."""
    from langchain_mistralai.chat_models import _convert_message_to_mistral_chat_message
    from app.repositories.chat_history_repository import ChatHistoryRepository

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=1, document_id=1)

    # Seed an assistant turn with non-empty tool_calls
    repo.add_message(
        session_id=session.id,
        role="assistant",
        content="Invoice total is $5,000.",
        tool_calls=[{"tool": "document_rag_tool", "summary": "Retrieved 5 chunks"}],
    )

    lc_history = repo.get_langchain_history(session.id)
    assert len(lc_history) == 1

    # Must serialize without raising KeyError: 'function'
    mistral_dict = _convert_message_to_mistral_chat_message(lc_history[0])
    assert mistral_dict["role"] == "assistant"
    assert mistral_dict["content"] == "Invoice total is $5,000."
    assert "tool_calls" not in mistral_dict
```

---

## 15. Files/Functions Responsible

1. **`backend/app/repositories/chat_history_repository.py`**
   - Function: `get_langchain_history()` (lines 130–147)
   - Responsibility: Inappropriately assigns UI execution logs to reserved wire-protocol key `additional_kwargs["tool_calls"]`.
2. **`langchain_mistralai/chat_models.py`**
   - Function: `_convert_message_to_mistral_chat_message()` (line 498)
   - Responsibility: Strictly enforces OpenAI function calling format on `additional_kwargs["tool_calls"]`.

---

## 16. Final Recommendation

Apply the **Minimum Safe Fix**:
In `backend/app/repositories/chat_history_repository.py`, replace `"tool_calls": m.tool_calls or []` with `"executed_tools": m.tool_calls or []` (or omit the key).  
This immediately resolves the `KeyError: 'function'`, preserves the assistant message content across turns, and ensures 100% compatibility with `langchain_mistralai`.

---

# Explicit Answers to Mandatory Questions A through J

### A. Why does `tc["function"]` fail?
In `langchain_mistralai/chat_models.py` (`_convert_message_to_mistral_chat_message`), the adapter assumes any item in `message.additional_kwargs["tool_calls"]` is an OpenAI-format function call dictionary (`{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}`). Because EFDI's application-level UI execution summary was placed in `additional_kwargs["tool_calls"]`, indexing `tc["function"]` raises `KeyError: 'function'`.

### B. What exact object is missing "function"?
The application-level tool execution log dictionary stored in `m.tool_calls`:
```python
{"tool": "document_rag_tool", "retrieved_count": 5, "scoped_documents": [1], "summary": "Retrieved 5 evidence chunk(s) from Document #1"}
```
It has keys `"tool"`, `"summary"`, etc., but does **not** have a `"function"` key.

### C. Where was that object created?
In the tool execution logging inside `DocumentRAGTool` (`backend/app/rag/tools/rag_tool.py`), `FinancialCalculatorTool`, and `DatabaseQueryTool`, aggregated by the agent into `chronological_tool_logs`.

### D. Where was it transformed incorrectly?
In `backend/app/repositories/chat_history_repository.py`, line 141 inside `get_langchain_history()`, where it was placed into `AIMessage.additional_kwargs["tool_calls"]`.

### E. Is the problem caused by the recent conversation-history changes?
**YES.** Prior to the recent conversation-context changes, `get_langchain_history()` simply instantiated `AIMessage(content=m.content)`. The problematic `additional_kwargs={"tool_calls": ...}` assignment was introduced in commit `42ec4cf`.

### F. What is the minimum safe code change?
In `backend/app/repositories/chat_history_repository.py` (line 141), rename the dictionary key from `"tool_calls"` to `"executed_tools"` (e.g. `"executed_tools": m.tool_calls or []`).

### G. Does the fix require any database schema change?
**NO.** The PostgreSQL schema, tables, and columns remain completely unchanged.

### H. Does the fix require any RAG change?
**NO.** RAG retrieval, chunking, embeddings, vector search, and reranking are completely unaffected.

### I. Does the fix require any Context Resolver redesign?
**NO.** `ConversationContextResolver` only reads `message.content` and `message.role`. It does not use `additional_kwargs`.

### J. What is the exact regression test that should prevent this from happening again?
A test that persists an assistant message with populated `tool_calls`, loads it via `repo.get_langchain_history()`, and passes it through `_convert_message_to_mistral_chat_message()`, asserting that no `KeyError` is raised, `tool_calls` is not erroneously populated on the wire message, and `content` is not cleared.
