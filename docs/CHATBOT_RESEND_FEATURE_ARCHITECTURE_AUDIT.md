# EFDI — Chatbot Resend Feature Architectural Audit

**Document Version:** 1.0.0  
**Status:** Architectural Investigation & Feasibility Audit (Read-Only)  
**Target Subsystems:** Document Chat, Global Corpus Chat, Chat History Repository, Conversation Context Resolver, Structured Session State, ReAct Agents (`DocumentReActAgent`, `GlobalReActAgent`).  

---

## 1. Executive Summary

This audit assesses the feasibility, safety, and systemic implications of introducing a **"Resend"** action on user messages within the EFDI conversational architecture.

Currently, the EFDI chatbot operates strictly on an append-only, sequential conversational turn model:
$$\text{User Query} \longrightarrow \text{Context Resolver} \longrightarrow \text{ReAct Agent Execution} \longrightarrow \text{Dual Message Persistence} \ (\text{User} + \text{Assistant})$$

Attempting to implement a naive "Resend" button by merely resubmitting the user's raw message (`send(message.content)`) is **fundamentally unsafe** in the current architecture. Doing so causes:
1. **Context Drift & Misinterpretation**: The Conversation Context Resolver resolves follow-ups (e.g., affirmative "yes", pronouns "it", or ordinals "the second item") against the *immediately preceding assistant offer or current dialogue window*. Resending an earlier message when subsequent turns have intervened causes the resolver to misinterpret intent or fail with false ambiguity.
2. **Conversation History Poisoning & Sliding Window Corruption**: Submitting a duplicate query creates consecutive duplicate user messages in PostgreSQL (`User` $\rightarrow$ `User` or `User` $\rightarrow$ `Assistant` $\rightarrow$ `User`), distorting the 10-message sliding window and confusing LLM grounding.
3. **State Inconsistency**: Active structured state (`pending_offer`, `verified_facts`, `active_document_id`) would be updated or cleared based on outdated assumptions.
4. **Duplicate Tool Executions & Financial Calculator Redundancy**: Heavy RAG vector searches, database SQL queries, and deterministic financial calculations would be re-executed needlessly.

**Core Architectural Recommendation**:  
EFDI must distinguish between two fundamentally different operations:
- **Operation 1: "Retry Failed Turn"** (Allowed only on user messages whose backend request failed and created no assistant message). This should execute as an in-place retry using the original conversation context state, without inserting duplicate user rows into the database.
- **Operation 2: "Regenerate Assistant Response"** (Allowed only on the latest assistant turn). This should replace the previous assistant message and citations, rather than resending an arbitrary historical user query.
- **Arbitrary Historical Resend** (clicking "Resend" on a turn from 5 turns ago) must **NOT** be permitted as an in-place replay; if allowed at all, it must be submitted as a brand-new turn with explicit user-prompt context.

---

## 2. Current Message Lifecycle

Understanding the exact lifecycle of a user query in EFDI is essential to tracing where resend would intervene:

```
[User Types Message]
       │
       ▼
[Frontend State] ──► Optimistically appends temp message: { id: Date.now(), role: 'user', content: text }
       │             Sets isLoading = true
       ▼
[POST /api/v1/chat/documents/{id}/messages OR /corpus/messages]
       │
       ├── 1. Authorize: doc_service.get_for_user(document_id, user)
       │
       ├── 2. Fetch Session: history_repo.get_or_create_document_session(user_id, document_id)
       │
       ├── 3. Fetch History: history_repo.get_langchain_history(session.id, limit=CHAT_HISTORY_LIMIT)
       │      (Queries newest 10 messages DESC, reverses in Python: oldest -> newest)
       │
       ├── 4. Fetch State: history_repo.get_session_state(session.id)
       │
       ├── 5. Add User Message: history_repo.add_message(session_id, role="user", content)
       │      (Flushes to session, but does NOT commit yet)
       │
       ├── 6. Context Resolver: resolver.resolve(query, history, session_state)
       │      ├── Standalone check (pass-through)
       │      ├── Negative confirmation ("no" -> ack, clear offer, return without RAG)
       │      ├── Ambiguous reference ("what about that?" -> ask clarification, return without RAG)
       │      └── Affirmative / Elliptical ("yes" -> rewrite to pending offer action)
       │
       ├── 7. Precondition Check: OCR completed for document content queries
       │
       ├── 8. ReAct Agent: agent.run(document_id, query=effective_query, user, history)
       │      ├── ReAct Loop (max 5 iterations)
       │      ├── Tool invocation (document_rag_tool, financial_calculator_tool, database_query_tool)
       │      ├── Loop Guard: checks _is_redundant_query() to prevent duplicate searches
       │      └── Grounded Synthesis: produces final answer with citations
       │
       ├── 9. State Lifecycle Update:
       │      ├── Clear pending_offer if accepted
       │      ├── Extract new pending_offer from assistant content
       │      └── Append verified tool calls to verified_facts
       │      history_repo.update_session_state(session.id, session_state)
       │
       ├── 10. Add Assistant Message: history_repo.add_message(session_id, role="assistant", content, tool_calls, citations)
       │
       └── 11. Transaction Commit: db.commit()
       │
       ▼
[Frontend Response] ──► Replaces/appends assistant message in UI state
                        Sets isLoading = false
```

---

## 3. Current Persistence Model

1. **Table Structure**:
   - `chat_sessions`: Contains `id`, `user_id`, `document_id` (nullable for global chat), `state_json` (JSONB), `created_at`, `updated_at`.
   - `chat_messages`: Contains `id` (bigint PK), `session_id` (FK), `role` (`user` | `assistant` | `system`), `content` (text), `tool_calls` (JSONB), `citations` (JSONB), `created_at`, `updated_at`.
2. **Transaction Demarcation**:
   - User message is added via `db.add(msg); db.flush()` at Step 5.
   - Assistant message is added via `db.add(msg); db.flush()` at Step 10.
   - `db.commit()` occurs **strictly once at the end of the HTTP handler**.
3. **Failure Semantics**:
   - If an exception occurs during Step 6 (Context Resolver), Step 7 (Preconditions), or Step 8 (ReAct Agent / LLM / Tools), `db.commit()` is **never reached**.
   - FastAPI's `get_db()` dependency executes `db.close()`, which rolls back the uncommitted SQLAlchemy transaction.
   - **Result**: On a failed request, **neither the user message nor an assistant message exists in the database**. The database contains only previously committed, clean turns.

---

## 4. Current Conversation-State Interaction

Structured conversation state is stored in `chat_sessions.state_json`:
- `active_document_id`: Anchors Document Chat sessions.
- `pending_offer`: Tracks proposals made by the assistant expecting user confirmation (`{"offer_text": str, "action_query": str, "user_confirmation_expected": bool}`).
- `verified_facts`: Stores bounded history of tool executions verifying document data.

**State Lifecycle**:
- Affirmative resolution clears `pending_offer` so the action is not re-triggered on future turns.
- Negative resolution clears `pending_offer` without running tools.
- Assistant answers containing confirmation questions repopulate `pending_offer`.
- Rolling back a failed turn preserves the pre-turn `state_json` in PostgreSQL.

---

## 5. Resend Semantics Analysis

When a user in a modern web UI clicks "Resend" on a message bubble, different applications implement completely different behaviors:

### Model A: "Retry Failed Request" (Safe & Essential)
- **Scenario**: The user typed "What are the payment terms?", but the network dropped, the LLM timed out, or a 502 occurred. The UI displays the user's message and an error toast.
- **Semantics**: Re-issue the exact same user query against the session.
- **Architectural Fit**: Excellent. Because failed requests roll back the database transaction, the session in PostgreSQL is in the exact state it was in before the failed attempt. Retrying will execute Step 1 through Step 11 cleanly.

### Model B: "Submit Duplicate Query as a New Turn" (Problematic)
- **Scenario**: A turn previously succeeded (User: "What is the penalty?", Assistant: "2% late fee"). The user clicks "Resend" on the earlier question "What is the penalty?".
- **Semantics**: Append a new user message with identical text at the end of the dialogue.
- **Architectural Fit**: High friction. The Context Resolver now receives two identical queries in recent history. If the query was context-dependent (e.g. "yes"), submitting it again as a new turn when the pending offer was already cleared will fail or be misinterpreted.

### Model C: "Regenerate Previous Assistant Answer" (Alternative Feature)
- **Scenario**: The user wants an alternative synthesis or fresh RAG retrieval for the immediately preceding question.
- **Semantics**: Delete or supersede the last assistant message and citations, re-run agent with the same user query and identical conversation context, and persist the new answer.
- **Architectural Fit**: Requires explicit backend support (updating/replacing `chat_messages` row by ID). Currently not supported.

---

## 6. Duplicate Message Risks

If Resend creates a duplicate user message row in `chat_messages`, the following severe bugs occur:

1. **Consecutive User Messages**:
   In standard conversation modeling, turns alternate: $U_1 \rightarrow A_1 \rightarrow U_2 \rightarrow A_2$. If $U_2$ fails and is re-saved, or if a user clicks resend:
   $$\dots \rightarrow A_1 \rightarrow U_2 \rightarrow U_2 \rightarrow A_2$$
   The sliding window (`limit=10`) now contains adjacent duplicate user queries.
2. **Context Resolver Misinterpretation**:
   `ConversationContextResolver` inspects the immediate preceding assistant message. If the preceding message is another `UserMessage` instead of an `AIMessage`, the resolver's prompt history reads:
   ```text
   USER: What about the second item?
   USER: What about the second item?
   ```
   The LLM will either treat the second query as a repetitive user insistence, detect false ambiguity, or fail to locate the assistant antecedent.
3. **Sliding Window Depletion**:
   With `CHAT_HISTORY_LIMIT = 10`, two consecutive duplicate turns consume 2 slots out of 10, pushing older, valuable context out of the active window prematurely.

---

## 7. Tool Execution Risks

EFDI provides three ReAct tools: `document_rag_tool`, `financial_calculator_tool`, and `database_query_tool`.

| Tool | Idempotent? | Execution Cost | Risk on Resend |
|---|---|---|---|
| `document_rag_tool` | Yes (Read-only) | High (Embedding + pgvector + BM25 FTS + RRF + CrossEncoder rerank) | Latency spike; redundant cache misses; potential token exhaustion |
| `financial_calculator_tool` | Yes (Deterministic AST) | Negligible | Safe, but redundant |
| `database_query_tool` | Yes (SELECT only, guarded by SQL AST Authorizer) | Medium (PostgreSQL read query) | Safe, but repeated execution consumes database connections |

**Redundant Loop Guard Interaction**:
Within a *single turn*, `_is_redundant_query()` intercepts identical queries with $\ge 0.70$ Jaccard similarity.
However, across *distinct turns*, the loop guard resets!
Therefore, if Resend creates a new turn, the ReAct agent will execute the full hybrid RAG pipeline again from scratch, recalculating dense embeddings and reranking candidates.

---

## 8. Failed Request Retry Analysis

Consider the lifecycle of a failed request under the newly implemented Level A error handling:
1. User types: "What is the penalty rate?"
2. Frontend adds optimistic message `tempUserMsg` with temporary ID `Date.now()`.
3. Backend runs `agent.run()`.
4. LLM provider times out or throws an error.
5. Backend catches exception, logs technical details, and raises `AIServiceException` (HTTP 502).
6. Database rolls back: **no user message, no assistant message, and no state changes are committed in PostgreSQL**.
7. Frontend catches 502 `ApiError`, displays Radix error toast: *"Something went wrong while processing your request. Please try again."*
8. Frontend **retains** `tempUserMsg` in UI state; loading spinner stops; input remains unlocked.

**If User Clicks "Resend" on this Failed Message**:
- What history does the backend receive? It receives the clean, pre-failure history.
- Will duplicate messages exist in the DB? No, because the failed attempt was never committed.
- Will state be corrupted? No, because state was rolled back.
- **Conclusion**: Retrying a **failed** request is completely clean and safe, provided the frontend re-uses the uncommitted message and does not spawn an orphaned bubble.

---

## 9. Successful Request Resend Analysis

Consider clicking "Resend" on a message that **already succeeded**:
1. User previously asked: "What is the invoice total?"
2. Assistant replied: "₹15,411.04" (Citing chunk #12).
3. Two turns later, user clicks "Resend" on "What is the invoice total?".

**Consequences**:
- **Option A (Create new turn at bottom of chat)**:
  Sends "What is the invoice total?" at Turn 4. The assistant will answer again at Turn 4. This is functionally identical to the user copying and pasting the text into the input box.
- **Option B (In-place regeneration)**:
  Overwriting the assistant's Turn 1 answer when Turns 2 and 3 have already occurred would invalidate the conversational foundation upon which Turns 2 and 3 were built!
- **Recommendation**:
  "Resend" on historical, successful messages should **NOT** modify historical turns. If a user wishes to ask a historical question again, it must be appended as a new turn at the current conversational horizon, or the action should be labeled "Copy to Input".

---

## 10. Conversation Context Resolver Interaction

The Context Resolver specifically resolves anaphora, ordinals, and confirmations against **recent dialogue history**:

### The "yes" / Confirmation Hazard
- Assistant: *"Would you like me to check payment terms?"*
- User: *"yes"*
- System executes payment terms search, clears `pending_offer`.
- Later, user clicks "Resend" on the earlier *"yes"*.
- Context Resolver receives query: `"yes"`.
- Resolver checks `pending_offer`: it is `None`!
- Resolver checks immediate preceding assistant message: it is about a completely different topic!
- Resolver outcome: Either completely misinterprets "yes" against the new topic, or returns `is_ambiguous=True` ("Could you please clarify what you are confirming?").
- **Direct Finding**: Resending short context-dependent messages ("yes", "no", "the second one", "why?") using raw query text will fail unpredictably if the dialogue context has advanced.

---

## 11. Structured State Interaction

Structured state tracking introduces specific lifecycle dependencies:

### Case 1: Failed Request Followed by Resend
- Assistant offered: *"Would you like me to check payment terms?"*
- State: `pending_offer = {"action_query": "Check document for payment terms", ...}`
- User replies: *"yes"*
- Backend fails (HTTP 502) before committing.
- Database rolls back: `pending_offer` remains intact in `chat_sessions.state_json`!
- User clicks Resend on *"yes"*.
- Backend receives query `"yes"` with `pending_offer` still present!
- Context Resolver resolves *"yes"* $\rightarrow$ *"Check document for payment terms"*.
- **Result**: Resend on a failed request succeeds seamlessly because the transaction rollback preserved the pending offer.

### Case 2: Resend on a Completed Affirmation
- If the turn had succeeded, `pending_offer` was cleared to `None`.
- Resending the same *"yes"* after success finds no pending offer to resolve against, breaking the resolver.

---

## 12. Context Snapshot Analysis

Should a future resend feature record a "context snapshot"?

If EFDI intends to allow resending an elliptical query (e.g., *"What about the second item?"*) after subsequent turns have elapsed, the system has two architectural choices:
1. **Model 1: Dynamic Current Context (No Snapshot)**
   - Re-runs the raw string against *current* history.
   - Pros: Simple; no additional storage.
   - Cons: Will resolve to whatever item #2 happens to be in recent turns, or fail if no list was recently mentioned.
2. **Model 2: Persisted Contextualized Query (Recommended)**
   - When a query is resolved at Turn $T$, store `contextualized_query` in `chat_messages.contextualized_query` (or `chat_messages.metadata_json`).
   - If the user resends Turn $T$ later, the system resends the *already-contextualized* query (*"What are the details of line item 2: Cloud Infrastructure Hosting?"*), bypassing context drift entirely.

---

## 13. Message ID and Frontend State Requirements

Currently, message identification across frontend and backend is asymmetric:
1. **Frontend Optimistic Message**:
   Created with `id: Date.now()` (client-side timestamp).
2. **Backend Persisted Message**:
   Created with database sequence `id: bigint` (e.g. `1935`).
3. **API Response**:
   Returns `message_id` for the *assistant* message (`response.message_id`), but **does not return the persisted user message ID**!
4. **Current Frontend Message Rendering**:
   `document-chat.tsx` and `GlobalChatPage.tsx` render messages by mapping over `messages.map((m, idx) => ...)`.
   The `tempUserMsg` retains its client `id: Date.now()`.
5. **Requirements for Future Resend Button**:
   - The UI needs to know the execution status of each message: `status: "sending" | "success" | "error"`.
   - The "Resend" button should appear **only on messages with `status === "error"`**.
   - The frontend must retain `raw_message: string` on the failed item so that clicking "Resend" invokes `handleSendMessage(failedMsg.content)`.

---

## 14. Race Condition Analysis

If a user rapidly double-clicks "Resend", or types a new message while a resend is in flight:
1. **Concurrent Request Collision**:
   Two concurrent HTTP requests would hit FastAPI with the same `session_id`.
2. **Database Concurrency**:
   Both requests would read `get_session_history()` simultaneously, see the same 10 messages, and simultaneously execute ReAct agent loops.
3. **Interleaved Assistant Writes**:
   Whichever completes first commits $A_1$; the second commits $A_2$. The chat history becomes duplicate and disjointed.
4. **Future Mitigation Required**:
   - Frontend must disable the Resend button immediately upon click (`isLoading` guard).
   - Backend can enforce per-session concurrency locking (e.g., `SELECT ... FOR UPDATE` on `chat_sessions` or an application-level mutex per session).

---

## 15. Citation and Grounded Source Analysis

How does Resend interact with RAG chunk citations?
- In EFDI, citations (`document_id`, `chunk_id`, `page_number`, `snippet`, `rerank_score`) are tied strictly to individual **assistant** messages (`chat_messages.citations`).
- They are **not** tied to user messages.
- If a failed query is retried, no previous assistant message or citations exist. When the retry succeeds, it generates fresh, authentic citations.
- If a successful query were regenerated, the old citations must be replaced alongside the old assistant message content to prevent orphaned or misattributed citations.

---

## 16. Recommended Resend Semantics

Based on this audit, the recommended architectural design for EFDI is:

```
                                  USER CLICKS RESEND
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   ▼                                             ▼
          Message Succeeded                             Message Failed (Error)
                   │                                             │
      Do NOT perform in-place                       Allow In-Place Retry (Safe)
      resend of raw string                                       │
                   │                                 Re-execute handleSendMessage()
      Instead: Provide "Copy to Input"               using clean session state;
      allowing user to refine query                  User bubble transitions from
      at the current conversation horizon            "error" back to "sending".
```

---

## 17. Required Changes for Future Implementation

When the Resend feature is approved for implementation, the following changes will be required:

### Backend Requirements:
1. Return `user_message_id` in `ChatMessageResponse` and `GlobalChatMessageResponse` so the client can map both sides of the turn.
2. Add optional `contextualized_query` column to `chat_messages` to persist resolved query intent.
3. Ensure `SELECT ... FOR UPDATE` on `chat_sessions` during message dispatch to prevent concurrent turn races.

### Frontend Requirements:
1. Add `status?: "sent" | "sending" | "error"` to `ChatHistoryItem`.
2. On API error (HTTP 502/500/network), mark the user message as `status: "error"`.
3. Render a subtle `[↻ Retry]` or `[Resend]` button specifically on messages with `status === "error"`.
4. Clicking Retry triggers `handleSendMessage(msg.content)` while clearing the error status.
5. Disable all send/retry buttons while `isLoading === true`.

---

## 18. Risks and Mitigations

| Risk | Impact | Recommended Mitigation |
|---|---|---|
| Retrying context-dependent queries ("yes", "second item") after dialogue shift | Severe intent drift / hallucinations | Only permit in-place retry for the immediately failed turn |
| Rapid repeated clicks creating duplicate agent runs | Resource exhaustion / duplicate DB rows | Debounce & disable retry buttons while request is active |
| Database session locks under heavy concurrent retries | Request timeouts | Short query timeouts and optimistic retry guards |
| Stale citations attached to regenerated responses | Grounding corruption | Associate citations strictly with assistant turn IDs |

---

## 19. Test Cases Required Before Implementation

Before deploying any future Resend feature, the following test suite must be authored:
1. **Retry Failed Turn (Network/502)**: Verify that retrying a failed turn generates a clean assistant response without creating duplicate database rows.
2. **Context Continuity on Failed Affirmation**: Assistant asks confirmation question $\rightarrow$ User says "yes" $\rightarrow$ Turn fails $\rightarrow$ User clicks Retry $\rightarrow$ Intent correctly resolves to payment terms.
3. **Double-Click Debounce**: Two rapid clicks on Retry result in exactly one agent execution.
4. **Retry Button Visibility**: Ensure Retry is rendered *only* on failed turns, never on historical successful turns.
5. **Clear History with Failed Messages**: Clearing chat history properly removes failed optimistic messages from React state.

---

## 20. Explicit Answers to Audit Questions

### A. Is resend safe with the current architecture?
**Only for failed requests.** Retrying a failed request is safe because uncommitted database transactions roll back cleanly. Resending an arbitrary historical message that previously succeeded is **unsafe** due to context drift, resolver confusion, and duplicate history.

### B. Can resend simply submit the same raw user message again?
**No.** Submitting the raw string blindly (especially for context-dependent queries like "yes", "no", "that one") causes the Context Resolver to evaluate the query against the *current* dialogue state rather than the state when the question was asked.

### C. Would doing that create duplicate conversation-history problems?
**Yes.** If a previously successful query is resent, it introduces consecutive or duplicate user queries into `chat_messages`, depleting the 10-message sliding window and confusing the LLM.

### D. Should resend create a new user-message row?
**For a failed request: NO.** The failed request rolled back, so the retry will create the single legitimate user-message row upon commit.  
**For an already-completed turn: YES**, but only if treated as a brand-new turn at the conversation horizon.

### E. Should resend be allowed only for failed requests?
**Yes.** Restricting "Resend / Retry" exclusively to failed requests eliminates 95% of architectural risks, race conditions, and context desynchronizations.

### F. What should happen to Context Resolver state?
On a retry of a failed request, Context Resolver operates on the exact pre-failure state. On an arbitrary historical resend, the resolver would be corrupted unless the previously contextualized query was stored and re-used.

### G. What should happen to `pending_offer`?
When a confirmation turn fails, `pending_offer` is preserved by database transaction rollback. When retried, the offer is successfully resolved and then cleared upon execution.

### H. Should resend use the original conversational context or current context?
For a failed request, the original context **is** the current context (since no turns intervened). For a historical resend, it must use the *original* context (via a stored contextualized query snapshot) to avoid context drift.

### I. Can resend execute the same RAG/database/calculator tools again safely?
**Yes.** All EFDI tools are read-only and deterministic. However, repeated RAG execution is computationally expensive (pgvector embeddings + CrossEncoder reranking).

### J. Can resend cause duplicate tool execution?
**Yes.** While `_is_redundant_query()` suppresses duplicates within a single turn, a resent message constitutes a new turn, causing tools to execute again.

### K. Are race conditions possible?
**Yes.** Rapid double-clicking without client-side debouncing or session locking can spawn concurrent ReAct agent executions and interleaved database writes.

### L. What minimum backend changes would eventually be required?
1. Return `user_message_id` in chat message response schemas.
2. Support session concurrency protection (`SELECT ... FOR UPDATE`).
3. Optionally store `contextualized_query` in `chat_messages`.

### M. What minimum frontend changes would eventually be required?
1. Track per-message status (`status: "sent" | "sending" | "error"`).
2. Render `[↻ Retry]` button only on messages with `status === "error"`.
3. Disable all inputs and retry triggers while `isLoading` is true.

### N. What should be the exact semantics of "Resend" in EFDI?
In EFDI, **"Resend" should strictly mean "Retry Failed Request"**: an in-place retry of an uncommitted, failed user message against the preserved session state, displaying an active spinner, clearing the error toast, and committing the resulting turn upon success.

---

## 21. Explicit Statement of What Was NOT Implemented

In strict adherence to the scope boundaries:
- **No Resend button, retry endpoint, or retry logic was implemented.**
- **No changes were made to message persistence schemas or database models for resend.**
- **No concurrency locks or context snapshotting systems were added.**
- **The audit is strictly read-only and advisory.**
