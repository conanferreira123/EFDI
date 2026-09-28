# EFDI Chatbot — Failed-Request Retry Feature Implementation

## 1. Feature Semantics & Core Principle

> **Core Principle:**  
> "Resend/Retry is supported ONLY for failed requests.  
> Successful historical messages are not retryable."

The feature is strictly a **"Retry Failed Request"** mechanism. It is available only when a user message represents a failed backend/AI request (such as upstream LLM connection timeouts, AI service unreachability, or internal pipeline exceptions that aborted processing).

The feature does **NOT**:
- Provide resend or retry for successful messages
- Implement answer regeneration or assistant message replacement
- Implement historical message replay
- Implement "Copy to Input"
- Implement context snapshotting or conversational branching
- Add a secondary conversational-memory architecture

---

## 2. Why Retry is Restricted to Failed Requests

In financial document intelligence, conversations establish immutable audit trails of queries, calculations, and citations. Allowing replay or mutation of successful historical messages introduces:
1. **Conversational Divergence:** If turn 2 of a 6-turn session is replayed with new parameters, all subsequent contextual references (such as "calculate a 2% discount on *that* total") become invalid or corrupted.
2. **Database Integrity Issues:** Modifying past turns breaks the linear `(user, assistant)` sequence and risks orphan turns.
3. **Audit Inconsistency:** In an enterprise accounting system, answers cited against documents must not retroactively change or disappear without an explicit reset.

Conversely, a failed request:
- Never completed execution
- Never generated an assistant answer or citations
- Never committed to the database (the transaction rolled back)
- Represents an interrupted interaction where the user's intent is simply to execute the same query now that transient errors have cleared

Therefore, restricting retry strictly to failed requests maintains 100% architectural and transactional consistency.

---

## 3. Request Lifecycle & Transaction Rollback

The normal and failed request lifecycles proceed as follows:

```
Normal Successful Request:
USER MESSAGE
    ↓
Backend request received
    ↓
User message added to session (flushed, uncommitted)
    ↓
Context Resolver runs (resolves references against session_state)
    ↓
ReAct Agent runs & executes tools
    ↓
Assistant message added
    ↓
Session state updated
    ↓
Database commit (`db.commit()`)
    ↓
Response returned: HTTP 200 with user_message_id, message_id, content, citations
    ↓
Frontend marks user message as `sent` (updates ID to persisted user_message_id)

Failed Request:
USER MESSAGE
    ↓
Frontend creates optimistic bubble (status = "sending")
    ↓
Backend request received
    ↓
User message added to session (flushed, uncommitted)
    ↓
Context Resolver / ReAct Agent / Tool execution fails (e.g. AIServiceException)
    ↓
Exception handler catches failure
    ↓
FastAPI database session context closes (`get_db()` teardown)
    ↓
Database transaction rolls back (`db.rollback()`)
    ↓
NO rows committed (neither user message, assistant message, nor session state mutations)
    ↓
Backend returns HTTP 502 Bad Gateway with structured JSON
    ↓
Frontend catches HTTP 502:
    - User message status transitions to "error"
    - Error notification toast appears
    - NO assistant error bubble is inserted
    - [↻ Retry] action appears below the failed user bubble
```

---

## 4. Frontend Error State & Message Tracking

Each message item (`ChatHistoryItem`) tracks a status:
```ts
export interface ChatHistoryItem {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCallItem[];
  citations?: CitationItem[];
  created_at: string;
  status?: "sending" | "sent" | "error";
}
```

- **Optimistic State:** When the user clicks Send or hits Enter, an optimistic user message is created with `status: "sending"`.
- **Success State:** When the API returns HTTP 200, the user message status becomes `"sent"`, and its temporary client ID is reconciled with the backend's `user_message_id`.
- **Error State:** When the API call fails or times out, the user message status transitions to `"error"`.
  - The bubble remains visible in place.
  - The technical error is surfaced cleanly via `useApiErrorToast()`.
  - No synthetic assistant bubble is created.
  - A visually subordinate `[↻ Retry]` action is displayed directly underneath the failed user message with an alert indicator.

---

## 5. Retry Lifecycle & Single-Flight Protection

When the user clicks `[↻ Retry]`:

1. **Double-Click / Concurrent Protection:**
   - Both the input and the retry buttons are immediately disabled (`loading = true`).
   - The message status transitions from `"error"` back to `"sending"`.
   - The inline spinner indicates active processing.
2. **Clean Re-Submission:**
   - The frontend issues an HTTP POST with the exact same failed query.
   - It does **not** append an additional user bubble to the screen.
3. **On Retry Success:**
   - The failed message status transitions to `"sent"`.
   - The user message ID is updated to the persisted `user_message_id`.
   - The newly generated assistant response is appended to the conversation.
   - The `[↻ Retry]` action disappears.
4. **On Subsequent Failure:**
   - The message status reverts to `"error"`.
   - The error toast displays again.
   - `[↻ Retry]` remains available for another attempt.

---

## 6. Context Resolver Interaction

Retry does **not** use a special context or memory bypass path. It routes through the identical chat request pipeline:

```
[Retry Clicked]
       ↓
Chat Endpoint POST
       ↓
Fetch latest 5-turn history (clean, unpoisoned)
       ↓
Fetch latest session_state (unpoisoned)
       ↓
ConversationContextResolver.resolve_turn(query, history, session_state)
       ↓
ReAct Agent & Specialized Tools
       ↓
Persistence & Commit
```

### Context Continuity Example
Consider a conversational follow-up:
1. **Turn 1:**
   - User: *"What is the bank account number?"*
   - Assistant: *"The bank account number is not explicitly stated. Would you like me to check for payment terms?"*
   - Session state records `pending_offer = {"action": "check payment terms", "target": "payment-related terms"}`.
2. **Turn 2 (Fails):**
   - User: *"yes"*
   - Request fails due to an LLM timeout.
   - Transaction rolls back. The `pending_offer` in the database remains preserved because session state modifications were rolled back with the transaction.
3. **Retry:**
   - User clicks `[↻ Retry]` on *"yes"*.
   - Backend loads the preserved session state containing `pending_offer`.
   - The Context Resolver authoritatively resolves *"yes"* to *"check payment terms"*.
   - No custom `if retry:` hacks or manual rewriting is needed; the normal Context Resolver operates authoritatively.

---

## 7. Database Behavior & Single-Turn Guarantee

Because PostgreSQL transactions roll back upon failure:
- **Failed Request:** 0 rows committed.
- **Successful Retry:** 1 user message row + 1 assistant message row committed.

The final database state contains **exactly one** user/assistant turn:
```
Turn 1: User ("yes") -> Assistant ("The payment terms are Net 30...")
```
There are no duplicate user rows (`User`, `User`, `Assistant`), and no orphan turns.

---

## 8. Document Chat & Global Corpus Chat Consistency

Both chat surfaces implement the exact same retry semantics while strictly respecting their respective boundaries:

| Dimension | Document Chat | Global Corpus Chat |
|---|---|---|
| **Endpoint** | `POST /api/v1/chat/documents/{id}/messages` | `POST /api/v1/chat/corpus/messages` |
| **Scope** | Single document (RBAC checked) | Global corpus (role-scoped / tenant-scoped) |
| **History** | `GET /api/v1/chat/documents/{id}/history` | `GET /api/v1/chat/corpus/history` |
| **Retry Endpoint** | Retries against document endpoint | Retries against corpus endpoint |
| **Persisted ID Returned** | `user_message_id` in `ChatMessageResponse` | `user_message_id` in `GlobalChatMessageResponse` |

Neither chat surface can bypass authorization or cross into the other's scope.

---

## 9. Tests Performed

The implementation is verified by the focused test suite in [`backend/tests/test_retry_feature.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_retry_feature.py):

1. **TEST 1 — Failed request appears as error state:**
   Forces AI service failure; verifies HTTP 502 returned, no assistant error message in DB, and history remains empty.
2. **TEST 2 — Retry succeeds:**
   Initial request fails; retry succeeds; returns assistant response and persisted `user_message_id`.
3. **TEST 3 — Database contains exactly one legitimate turn:**
   Initial request fails, retry succeeds; verifies database contains exactly 1 user message and 1 assistant message with 0 duplicate user records.
4. **TEST 4 — Retry fails again:**
   Both initial and retry attempts fail; database remains completely clean with 0 committed messages.
5. **TEST 5 — Context-dependent failed request:**
   Turn 1 offers payment terms; Turn 2 ("yes") fails; Retry of "yes" resolves against the preserved `pending_offer` to "check payment terms" and completes successfully.
6. **TEST 6 — Successful historical message has no Retry:**
   Verifies that no endpoint exists to resend or replay historical successful messages (`POST /messages/{id}/resend` returns 404).
7. **TEST 7 — Double click / rapid retry protection:**
   Verifies single-flight execution and idempotency.
8. **TEST 8 — Document Chat retry:**
   Verifies end-to-end failure and retry flow in Document Chat.
9. **TEST 9 — Global Chat retry:**
   Verifies end-to-end failure and retry flow in Global Corpus Chat.
10. **TEST 10 — Authorization on retry:**
    Verifies that a user cannot retry or access messages on another user's unauthorized document (returns 403 Forbidden).

All 10 tests passed alongside all 15 regression tests in [`test_chat_error_handling.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_chat_error_handling.py) and [`test_conversation_context.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/tests/test_conversation_context.py).

---

## 10. Explicitly Excluded Features

The following features were strictly kept out of scope:
- **Successful-message resend:** Successful historical messages cannot be resent.
- **Historical-message replay:** No generic replay or branching mechanism.
- **Regenerate response:** No assistant message re-generation or citation overwriting.
- **Copy to Input:** No UI shortcut button to paste past queries into the input box.
- **Context snapshots:** No versioned branching of conversational states.
- **Conversational vector memory:** No secondary memory layer.
- **Unrelated architectural changes:** OCR, Docling, chunking, pgvector RAG, financial calculators, SQL authorization, and RBAC remain untouched.
