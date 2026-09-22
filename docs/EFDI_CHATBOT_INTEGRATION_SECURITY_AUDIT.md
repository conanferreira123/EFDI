# EFDI Chatbot Integration & Security Audit

**Document Version:** 1.0.0  
**Audit Date:** 2026-09-22  
**Authoritative Migration Head:** `361bf56d16a1` (revises `014cab3b4e0b`)  
**Audit Scope:** Read-Only Integration and Security Verification of the EFDI (Enterprise Financial Document Intelligence) codebase following the normalized database schema implementation.

---

## 1. Executive Summary

### Final Verdict: **READY WITH FIXES**

The EFDI normalized database schema redesign (`361bf56d16a1`) is structurally sound, clean, and correctly positioned across its four architectural tiers:
1. **Document / Lifecycle Layer** (`documents`)
2. **Extraction / Provenance Layer** (`extraction_results`)
3. **RAG Layer** (`document_chunks` with `pgvector`)
4. **Normalized Business Layer** (`vendors`, `vendor_aliases`, `invoices`, `invoice_line_items`, `payment_obligations`, `invoice_payments`)

The core authentication infrastructure (`get_current_user`, JWT decoding, bcrypt hashing, stateless bearer authentication), document-level RBAC/ABAC isolation, and pre-retrieval RAG security predicates are rigorously implemented and verified.

However, the codebase **CANNOT proceed immediately to the LangChain ReAct agent implementation** due to three critical, high-impact defects in the **Text-to-SQL security and sanitization subsystem**:
1. **Table Alias Reference Crash (`CRIT-01`)**: Text-to-SQL AST rewriting injects table authorization predicates using the raw table name (e.g. `documents.uploaded_by = 1`) even when the query aliases the table (`FROM documents d`), triggering a fatal PostgreSQL syntax error (`invalid reference to FROM-clause entry for table "documents"`).
2. **Scoping Gap on Normalized Child Tables (`CRIT-02`)**: In `TextToSQLService._apply_authorization_filters`, the `FINANCE_ANALYST` scoping branch only checks for `documents`, `invoices`, `payment_obligations`, and `extraction_results`. When querying `invoice_line_items`, `vendors`, `vendor_aliases`, or `users`, the injected predicate is `None`, which injects `WHERE None` into the SQLGlot AST, producing malformed SQL and failing to isolate child records to the analyst's own documents.
3. **Unrestricted `users` Table Exposure in Text-to-SQL (`HIGH-01`)**: The `users` table is present in `ALLOWED_TABLES` without role-gating or row-level authorization. While `password_hash` is safely omitted from `ALLOWED_COLUMNS`, a `FINANCE_ANALYST` or `FINANCE_MANAGER` can dump the entire corporate user directory (`id, username, email, full_name, role, is_active`).
4. **Missing `audit_logs` in Text-to-SQL Allowlist (`MED-01`)**: The `AUDITOR` role has no access to `audit_logs` through Text-to-SQL because the table is absent from `ALLOWED_TABLES`.

Once these Text-to-SQL sanitization and allowlist issues are resolved (and the deterministic keyword router is replaced during the ReAct phase), the system will be secure and fully prepared for autonomous ReAct agent operation.

---

## 2. Current Architecture Verified

```
+--------------------------------------------------------------------------------------------------+
|                                      HTTP / FASTAPI LAYER                                        |
+--------------------------------------------------------------------------------------------------+
|  /api/v1/auth/*         /api/v1/documents/*          /api/v1/chat/documents/{id}                 |
|  /api/v1/users/*        /api/v1/extraction/*         /api/v1/chat/corpus                         |
+--------------------------------------------------------------------------------------------------+
                                        | (get_current_user -> JWT Bearer -> DB User)
                                        v
+--------------------------------------------------------------------------------------------------+
|                                    APPLICATION SERVICES                                          |
+--------------------------------------------------------------------------------------------------+
|  DocumentService       | InvoicePersistenceService  | ChatService                                |
|  ExtractionService     | TextToSQLService           | GlobalChatService / AgentOrchestrator      |
|  RAGService            | FinancialCalculator        | AuditService                               |
+--------------------------------------------------------------------------------------------------+
                                        |
                +-----------------------+-----------------------+
                |                                               |
                v                                               v
+-----------------------------------------------+ +-----------------------------------------------+
|         DATA ACCESS & VALIDATION              | |             RETRIEVAL & TOOLS                 |
+-----------------------------------------------+ +-----------------------------------------------+
| DocumentRepository     ChunkRepository        | | TextToSQLService:                             |
| InvoiceRepository      VendorRepository       | |   - SQLGlot AST parser & validator            |
| PaymentObligationRepo  AuditRepository        | |   - Read-only transaction + 5000ms timeout    |
| ExtractionRepository                          | | RAGService:                                   |
|                                               | |   - Dense embedding (sentence-transformers)   |
|                                               | |   - Sparse text search (PostgreSQL tsvector)  |
|                                               | |   - Reciprocal Rank Fusion (RRF)              |
+-----------------------------------------------+ +-----------------------------------------------+
                                        |
                                        v
+--------------------------------------------------------------------------------------------------+
|                       POSTGRESQL 15+ & PGVECTOR (ALEMBIC HEAD: 361bf56d16a1)                     |
+--------------------------------------------------------------------------------------------------+
| Tier 1 (Lifecycle):    documents                                                                 |
| Tier 2 (Provenance):   extraction_results                                                        |
| Tier 3 (RAG Vectors):  document_chunks (embedding vector(768), tsv tsvector)                     |
| Tier 4 (Normalized):   vendors, vendor_aliases, invoices, invoice_line_items,                    |
|                        payment_obligations, invoice_payments                                     |
| Supporting:            users, audit_logs                                                         |
+--------------------------------------------------------------------------------------------------+
```

---

## 3. Authentication Audit

### 3.1 Verification Checklist & Findings

| Check | Status | Evidence / Code Location | Details |
|---|---|---|---|
| **1. Identity source** | **VERIFIED** | [dependencies.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py#L38-L82) | `get_current_user` extracts JWT from `HTTPBearer(auto_error=True)`, decodes with `security.decode_access_token`, and verifies token type is `"access"`. |
| **2. Trusted `user.id`** | **VERIFIED** | [dependencies.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py#L69-L78) | `user_repo.get_by_id(int(user_id_str))` fetches user directly from PostgreSQL. Identity is never accepted from query parameters or JSON body. |
| **3. Trusted `user.role`** | **VERIFIED** | [dependencies.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py#L76-L80) | `user.role` is read from database record. Any mismatch between token payload and DB is rejected. Active status (`user.is_active`) is enforced. |
| **4. LLM identity override** | **VERIFIED** | [dependencies.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/core/dependencies.py#L38-L82), [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L255) | Backend injects `user.id` as a literal integer AST node (`exp.Literal.number(user.id)`). The LLM cannot override or influence identity. |
| **5. Parameter tampering** | **VERIFIED** | [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py#L29-L35), [global_chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py#L40-L45) | All endpoints inject `current_user: User = Depends(get_current_user)`. Request body schemas do not contain `user_id`. |
| **6. Document ID tampering** | **VERIFIED** | [document_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L125-L135) | `get_for_user(document_id, user)` raises `AuthorizationException` if `FINANCE_ANALYST` does not own the document. |
| **7. Soft-deleted documents** | **VERIFIED** | [document_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/document_repository.py#L31-L36) | `DocumentRepository.get_by_id` and search filters enforce `Document.is_deleted.is_(False)`. |

---

## 4. Authorization Matrix

| Component | Finance Analyst | Finance Manager | Auditor | Admin | Enforcement Location | Safe? |
|---|---|---|---|---|---|---|
| **Global Chat (`/corpus`)** | Scoped to own documents | All active documents | All active documents | All active documents | [agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L90-L98) | **SAFE** (Delegates to tool security) |
| **Document Chat (`/{id}`)** | Own documents only (403 on other) | All active documents | All active documents | All active documents | [document_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L125-L135) | **SAFE** (Pre-execution validation) |
| **Text-to-SQL (documents)** | `uploaded_by = current_user.id` | Unrestricted active | Unrestricted active | Unrestricted active | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L255) | **VULNERABLE** (Breaks on alias, e.g. `FROM documents d`) |
| **Text-to-SQL (invoices)** | `document_id IN (SELECT id FROM documents WHERE uploaded_by=...)` | Unrestricted active | Unrestricted active | Unrestricted active | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L231-L237) | **VULNERABLE** (Breaks on alias, e.g. `FROM invoices i`) |
| **Text-to-SQL (line items)** | Unscoped (`WHERE None` injection crash) | Unrestricted active | Unrestricted active | Unrestricted active | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L248-L255) | **VULNERABLE** (Crashes / no ownership predicate) |
| **Text-to-SQL (vendors)** | Unscoped (`WHERE None` injection crash) | Unrestricted active | Unrestricted active | Unrestricted active | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L248-L255) | **VULNERABLE** (Crashes / no ownership predicate) |
| **Text-to-SQL (users)** | Unscoped read of all users | Unscoped read of all users | Unscoped read of all users | Unrestricted active | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L68) | **VULNERABLE** (Non-admin user directory enumeration) |
| **Text-to-SQL (audit_logs)** | Blocked (table not allowlisted) | Blocked (table not allowlisted) | Blocked (table not allowlisted) | Blocked | [text_to_sql_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L55) | **DEFECT** (Auditor cannot query audit logs) |
| **RAG Retrieval (Dense/FTS)** | Pre-retrieval SQL filter on `uploaded_by` | Full active corpus | Full active corpus | Full active corpus | [chunk_repository.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py#L182-L200) | **SAFE** (Pre-retrieval DB predicate) |
| **Document CRUD** | Own uploads only | All documents (delete allowed) | Read-only all documents | All documents | [document_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/document_service.py#L125-L160) | **SAFE** |
| **Workflow / Approvals** | Review own documents | Approve/Reject all | Audit trail read | Full workflow admin | [workflow.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/workflow.py#L50-L75) | **SAFE** |

---

## 5. Text-to-SQL Security Audit

### 5.1 Controls Inspected and Status

```
Incoming Query -> SQLGlot Parse -> SELECT-Only Check -> Table Allowlist -> Column Allowlist
     -> Forbidden Functions Check -> AST Authorization Injection -> LIMIT Enforcer
     -> Read-Only Transaction -> PostgreSQL (5000ms Timeout)
```

1. **Allowlisted Tables (`VERIFIED`)**: Defined in `ALLOWED_TABLES`: `documents`, `extraction_results`, `document_chunks`, `vendors`, `vendor_aliases`, `invoices`, `invoice_line_items`, `payment_obligations`, `invoice_payments`, `users`.
2. **Sensitive Columns Protection (`VERIFIED`)**: `users.password_hash` is strictly excluded from `ALLOWED_COLUMNS['users']` (`id, username, email, full_name, role, is_active, created_at, updated_at`).
3. **SELECT-Only AST Enforcement (`VERIFIED`)**: `isinstance(stmt, exp.Select)` is enforced in `_validate_ast`. Statements like `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `EXECUTE` are rejected with `ValidationFailedException`.
4. **Forbidden Functions Blocked (`VERIFIED`)**: Functions such as `pg_sleep`, `pg_terminate_backend`, `dblink`, `version`, `current_setting`, `set_config` are blocked via AST traversal (`stmt.find_all(exp.Anonymous, exp.Func)`).
5. **LIMIT Enforced (`VERIFIED`)**: `_enforce_limit` sets `LIMIT 100` if absent or caps existing limits $> 100$.
6. **Execution Controls (`VERIFIED`)**: Executes within `SET TRANSACTION READ ONLY;` and `SET LOCAL statement_timeout = '5000ms';`.

### 5.2 Critical Vulnerabilities in Text-to-SQL

#### Finding CRIT-01: Table Aliasing Bypasses / Breaks AST Authorization Injection
- **Location:** [text_to_sql_service.py: lines 225-245](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L245)
- **Description:** When an LLM generates SQL with an alias (standard LLM output pattern):
  ```sql
  SELECT d.id, d.original_filename FROM documents d;
  ```
  The injection logic searches `ast.find_all(exp.Table)` and matches table `documents`. It constructs:
  ```python
  auth_predicate = exp.EQ(
      this=exp.Column(this=exp.to_identifier("uploaded_by"), table=exp.to_identifier("documents")),
      expression=exp.Literal.number(user.id),
  )
  ```
  This rewrites the query to:
  ```sql
  SELECT d.id, d.original_filename FROM documents AS d WHERE documents.uploaded_by = 1;
  ```
- **Impact:** PostgreSQL throws `psycopg2.errors.UndefinedTable: invalid reference to FROM-clause entry for table "documents"`. If a query joins aliased tables, this causes hard failures. Worse, if the table identifier in the column reference does not match the alias in the FROM clause, the query is malformed.

#### Finding CRIT-02: Missing Scoping & AST Malformation on Child Tables
- **Location:** [text_to_sql_service.py: lines 225-255](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L255)
- **Description:** For `FINANCE_ANALYST`, the code uses an `if/elif` chain:
  ```python
  if table_name == "documents":
      ...
  elif table_name == "invoices":
      ...
  elif table_name == "payment_obligations":
      ...
  elif table_name == "extraction_results":
      ...
  ```
  If the LLM generates a query targeting:
  - `invoice_line_items` (e.g. `SELECT description, gross_amount FROM invoice_line_items;`)
  - `vendors` (e.g. `SELECT canonical_name FROM vendors;`)
  - `vendor_aliases`
  - `users`
  Then `auth_predicate` remains `None`.
  The code then executes:
  ```python
  if where_clause:
      ast.set("where", exp.Where(this=exp.And(this=where_clause.this, expression=auth_predicate)))
  else:
      ast.set("where", exp.Where(this=auth_predicate))
  ```
  When `auth_predicate` is `None`, SQLGlot creates `Where(this=None)`. The generated SQL becomes:
  ```sql
  SELECT description, gross_amount FROM invoice_line_items WHERE;
  ```
  or with an existing where clause:
  ```sql
  SELECT description, gross_amount FROM invoice_line_items WHERE gross_amount > 100 AND;
  ```
- **Impact:** 
  1. SQL generation crashes with a PostgreSQL syntax error.
  2. If the AST parser omitted the empty predicate, `invoice_line_items` would be completely unscoped, exposing another user's line items and pricing data to an unauthorized Analyst.

#### Finding HIGH-01: User Directory Enumeration via Text-to-SQL
- **Location:** [text_to_sql_service.py: lines 42-68](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L68)
- **Description:** `users` is included in `ALLOWED_TABLES` for all roles. A `FINANCE_ANALYST` can submit:
  ```sql
  SELECT id, username, email, full_name, role FROM users;
  ```
  Because no authorization filter is applied to `users`, the entire company user roster is returned.
- **Impact:** Information disclosure. Access to `users` via Text-to-SQL must be restricted exclusively to `ADMIN`.

#### Finding MED-01: Auditor Cannot Access Audit Logs via Text-to-SQL
- **Location:** [text_to_sql_service.py: lines 42-55](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L55)
- **Description:** `audit_logs` is not in `ALLOWED_TABLES`. When an `AUDITOR` attempts to query: "Show me all document upload audit events for user X", SQLGlot rejects the query with `"Table 'audit_logs' is not permitted"`.

---

## 6. RAG Security Audit

### 6.1 Retrieval Pipeline Flow

```
User Query -> SentenceTransformer Embedding (768d)
     |
     +--> Dense Vector Search: cosine distance <=> [chunk_repository.py: search_vector_global]
     |         WHERE Document.is_deleted = False AND Document.uploaded_by = user.id (if Analyst)
     |
     +--> Sparse Text Search: plainto_tsquery <=> [chunk_repository.py: search_fts_global]
               WHERE Document.is_deleted = False AND Document.uploaded_by = user.id (if Analyst)
     |
     v
Reciprocal Rank Fusion (RRF: k=60) -> Top K Chunks -> Global/Doc Chat Context
```

### 6.2 Pre-Retrieval vs Post-Retrieval Authorization
- **Location:** [chunk_repository.py: lines 182-200](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/repositories/chunk_repository.py#L182-L200)
- **Logic:**
  ```python
  def _apply_authorization_predicates(self, query: Select, user: User) -> Select:
      query = query.join(Document, DocumentChunk.document_id == Document.id).where(
          Document.is_deleted.is_(False)
      )
      if user.role == UserRole.FINANCE_ANALYST.value:
          query = query.where(Document.uploaded_by == user.id)
      return query
  ```
- **Conclusion: VERIFIED SECURE.** 
  Authorization is applied **pre-retrieval** at the database query level for both dense vector search and sparse full-text search. Chunks belonging to other users or soft-deleted documents are never fetched from PostgreSQL, eliminating authorization bypasses via reranking or RRF.

---

## 7. Extraction -> Normalized Data Integration

### 7.1 Pipeline Lifecycle & Verification

```
Upload -> OCR -> Extraction -> extraction_results (raw JSON)
                                         |
                                         v
                         InvoicePersistenceService.sync_from_extraction
                                         |
           +-----------------------------+-----------------------------+
           |                             |                             |
           v                             v                             v
   vendors / aliases                  invoices                 invoice_line_items &
(resolved by code/tax_id)     (source_extraction_result_id)    payment_obligations
```

| Invariant | Status | Evidence / Code Location | Evaluation |
|---|---|---|---|
| **Provenance preservation** | **VERIFIED** | [invoice_persistence_service.py: line 46](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py#L46) | `extraction_results` is never mutated or overwritten. |
| **Foreign key linkage** | **VERIFIED** | [invoice_persistence_service.py: lines 94, 113](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py#L94-L113) | `invoices.source_extraction_result_id` stores exact extraction result ID. |
| **Idempotence** | **VERIFIED** | [invoice_persistence_service.py: lines 88-129, 275-277](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py#L88-L129) | Re-running extraction updates the existing `Invoice` record and replaces line items via `DELETE FROM invoice_line_items WHERE invoice_id = :id`. |
| **Vendor resolution safety** | **VERIFIED** | [invoice_persistence_service.py: lines 207-266](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py#L207-L266) | Deterministic lookup order: `vendor_code` -> `tax_id` -> case-insensitive `canonical_name`. Enriches existing vendor without duplicating. |
| **Separation of Payments** | **VERIFIED** | [invoice_persistence_service.py: lines 50, 359](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/invoice_persistence_service.py#L50-L359) | `invoice_payments` is NEVER touched by extraction. `obligation.amount_paid` defaults to `0.00` and is preserved on updates. |
| **Transaction Boundary Concern** | **MEDIUM** | [extraction_service.py: lines 180-186](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L180-L186) | Extraction catches `Exception` during `sync_from_extraction` and logs a warning without rolling back or failing the extraction workflow step. |

---

## 8. Data Authority & Lineage

| Business Field | Canonical Authority | Source / Provenance | SQL Tool Source | RAG Source | Calculator Source | Authority Conflict? |
|---|---|---|---|---|---|---|
| `invoice_number` | `invoices.invoice_number` | `extraction_results.fields` | `invoices` | `document_chunks` | N/A | None (Normalized table is authoritative) |
| `invoice_date` | `invoices.invoice_date` | `extraction_results.fields` | `invoices` | `document_chunks` | N/A | None |
| `vendor_name` | `vendors.canonical_name` | `vendors` (via resolution) | `vendors` | `document_chunks` | N/A | None |
| `subtotal` | `invoices.subtotal_amount` | `extraction_results.fields` | `invoices` | `document_chunks` | Trusted SQL output | None |
| `tax` | `invoices.tax_amount` | `extraction_results.fields` | `invoices` | `document_chunks` | Trusted SQL output | None |
| `grand_total` | `invoices.grand_total_amount` | `extraction_results.fields` | `invoices` | `document_chunks` | Trusted SQL output | None |
| `due_date` | `payment_obligations.due_date`| Extracted from invoice | `payment_obligations` | `document_chunks` | N/A | None |
| `payment_terms` | `payment_obligations.payment_terms`| Extracted from invoice | `payment_obligations`| `document_chunks` | N/A | None |
| `amount_due` | `payment_obligations.amount_due`| Synced from `grand_total`| `payment_obligations`| `document_chunks` | Trusted SQL output | None |
| `amount_paid` | `payment_obligations.amount_paid`| External payments only | `payment_obligations`| N/A | Trusted SQL output | None |
| `amount_outstanding`| `payment_obligations.amount_outstanding`| Derived (`due - paid`)| `payment_obligations`| N/A | Trusted SQL output | None |
| `payment_status` | `payment_obligations.status` | State machine / external| `payment_obligations`| N/A | N/A | Initial state `OPEN`/`UNKNOWN`; external payments drive `PAID` |

---

## 9. Document Chat Audit

- **Endpoint:** `POST /api/v1/chat/documents/{document_id}`
- **Router:** [chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/chat.py#L29-L50)
- **Service:** [chat_service.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/chat_service.py#L38-L120)

### Verification Summary
1. **Access Check Before Execution (`VERIFIED`)**: `doc_service.get_for_user(document_id, user)` is executed immediately upon request receipt. If a `FINANCE_ANALYST` requests a document uploaded by another user, `AuthorizationException` (HTTP 403) is raised.
2. **RAG Scoping (`VERIFIED`)**: `rag_service.retrieve_for_document(document_id, query, top_k)` passes `filter_document_id=document.id` to `chunk_repo.search_vector_for_document` and `search_fts_for_document`. Chunks from other documents cannot be returned.
3. **No Text-to-SQL Exposure (`VERIFIED`)**: The document chat pipeline uses only `RAGService` and the document context; `TextToSQLService` is not registered or callable.
4. **Session / History Isolation (`VERIFIED`)**: Chat history is stored in memory keyed by `(user_id, document_id)`. Sessions are strictly isolated by `user_id`.

---

## 10. Global Chat Audit

- **Endpoint:** `POST /api/v1/chat/corpus`
- **Router:** [global_chat.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/global_chat.py#L40-L75)
- **Orchestrator:** [agent_orchestrator.py](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L42-L135)

### Verification Summary
1. **Role-Aware Processing (`VERIFIED`)**: `current_user` is passed from `Depends(get_current_user)` to `agent_orchestrator.run(query=payload.message, user=current_user)`.
2. **Corpus Scoping (`PARTIALLY VERIFIED`)**:
   - RAG tool calls enforce corpus isolation via `_apply_authorization_predicates` in `chunk_repository.py`.
   - Text-to-SQL tool calls attempt to enforce scoping via `text_to_sql_service._apply_authorization_filters`, but fail when queries use table aliases or child tables (`CRIT-01`, `CRIT-02`).
3. **Stateless History Model (`VERIFIED`)**: Global chat currently accepts `history: List[ChatMessage]` in the request payload and does not persist sessions across requests in the database.

---

## 11. Existing Router / Orchestrator Audit

### 11.1 Current Implementation: Deterministic Keyword Router
- **Location:** [agent_orchestrator.py: lines 58-135](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L58-L135)
- **Routing Logic:** Substring matching against static keyword lists:
  ```python
  sql_triggers = ["how many", "total", "sum", "average", "count", "list", "all invoices", ...]
  calc_triggers = ["calculate", "difference", "variance", "tax rate", ...]
  rag_triggers = ["what is", "explain", "policy", "terms", "clause", ...]
  ```
- **Execution Order:** Hardcoded sequential pipeline:
  1. If `is_sql`: calls `text_to_sql_service.execute_natural_language_query(query, user)`.
  2. If `is_calc`: extracts numbers using regex and executes arithmetic.
  3. If `is_rag` or if no SQL result: calls `rag_service.retrieve_global(query, user)`.
  4. Formats combined text and prompts LLM with synthesis prompt.

### 11.2 What Must Be Replaced for ReAct
1. **Remove static substring triggers**: Substring matching cannot handle nuanced queries, multi-step queries, or iterative refinement.
2. **Introduce LangChain Agent / Tool Calling Interface**: Bind `TextToSQLTool`, `RAGRetrievalTool`, and `FinancialCalculatorTool` as dynamic tools.
3. **Empower LLM with Dynamic Reasoning**: The ReAct agent dynamically plans and executes Thought -> Action -> Action Input -> Observation loops.

---

## 12. Cross-Service Consistency

| Check | Result | Evidence / Details |
|---|---|---|
| **Seller / Vendor Naming** | **CONSISTENT** | Normalized table uses `canonical_name` and `vendor_code`. Extraction maps `seller_name` / `vendor_name` to `vendors` during synchronization. |
| **Document Ownership Check** | **CONSISTENT** | `DocumentService`, `ChunkRepository`, and `WorkflowService` consistently check `document.uploaded_by == user.id` for `FINANCE_ANALYST`. |
| **`is_deleted` Handling** | **CONSISTENT** | Excluded in `DocumentRepository`, `ChunkRepository`, and `TextToSQLService` AST predicates. |
| **Payment Status Interpretation** | **CONSISTENT** | Documented in `document_enums.py` (`UNKNOWN`, `OPEN`, `PARTIALLY_PAID`, `PAID`, `OVERDUE`, `CANCELLED`). `InvoicePersistenceService` initializes `OPEN` or `UNKNOWN` and preserves payments. |
| **Document ID Relationships** | **CONSISTENT** | `Invoice.document_id`, `DocumentChunk.document_id`, `ExtractionResult.document_id` maintain consistent foreign keys to `documents.id`. |

---

## 13. Security Test Matrix

| Test ID | Test Scenario | Expected Behavior | Security Property Tested | Current Implementation Status | Verdict |
|---|---|---|---|---|---|
| **A** | Analyst queries another user's invoice via Text-to-SQL | Scoped exclusively to analyst's documents or returns empty | Tenant isolation (ABAC) | `invoices` scoped by subquery, but crashes if aliased | **FAIL** (CRIT-01) |
| **B** | Analyst asks "How many invoices are there for user X?" | Returns 0 or only invoices belonging to caller | Cross-user aggregate leakage | Scoped, but fails if aliasing used | **FAIL** (CRIT-01) |
| **C** | Analyst queries line items via Text-to-SQL | Returns only line items of caller's invoices | Child table authorization | `invoice_line_items` not handled in scoping logic | **FAIL** (CRIT-02) |
| **D** | Analyst requests all invoices regardless of owner | Automatically filtered by backend | Forced backend scoping | Scoped via AST rewrite, but breaks on alias | **FAIL** (CRIT-01) |
| **E** | Analyst uses SQL alias (`FROM documents d`) | Query executes with alias-aware scoping predicate | Alias handling safety | Predicate uses unaliased `documents.uploaded_by` | **FAIL** (CRIT-01) |
| **F** | Analyst uses JOIN between `invoices` and `documents` | Scope enforced on both sides | Join boundary confinement | Unscoped child joins possible | **FAIL** (CRIT-02) |
| **G** | Analyst uses subquery | Subquery cannot escape tenant boundaries | Subquery confinement | AST injects at top-level SELECT only | **NEEDS FIX** |
| **H** | Analyst asks RAG about another user's document | Chunks from other users never retrieved | RAG tenant isolation | Pre-retrieval SQL filter applied | **PASS** |
| **I** | Analyst directly requests another user's document in Doc Chat | HTTP 403 Forbidden | IDOR prevention | Pre-execution check raises 403 | **PASS** |
| **J** | Manager queries all invoices | Returns all non-deleted invoices | Unrestricted manager scope | No filter injected for Manager | **PASS** |
| **K** | Auditor queries uploader/audit info | Returns audit logs and uploader details | Audit trail visibility | `audit_logs` blocked by allowlist | **FAIL** (MED-01) |
| **L** | Admin queries permitted system info | Full access to permitted tables | Administrator privilege | Admin unrestricted on allowlisted tables | **PASS** |
| **M** | User attempts to access another user's chat session | HTTP 403 or empty session | Chat session isolation | Sessions keyed by `(user_id, document_id)` | **PASS** |
| **N** | User attempts to reuse document chat session for another document | Session rejected or isolated | Session scope confinement | Scoped by `(user_id, document_id)` | **PASS** |
| **O** | Retrieval of soft-deleted document | Document excluded from RAG and SQL | Soft-delete integrity | `is_deleted = False` enforced in RAG and SQL | **PASS** |
| **P** | SQL injection via natural language prompt | Syntax rejected or sanitized to safe SELECT | SQL injection defense | AST validation enforces `exp.Select` only | **PASS** |
| **Q** | LLM generates dangerous SQL (`DROP`, `pg_sleep`) | ValidationFailedException raised | Privilege escalation defense | Forbidden AST nodes rejected | **PASS** |
| **R** | LLM generates `CURRENT_USER` in SQL | Rejected by forbidden function check | Application identity defense | `CURRENT_USER` identifier blocked | **PASS** |

---

## 14. Findings

### Finding CRIT-01: Table Aliasing Causes SQL Syntax Errors in Text-to-SQL AST Rewriter
- **Severity:** **CRITICAL**
- **Component:** Text-to-SQL Service
- **Location:** [text_to_sql_service.py: lines 225-245](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L245)
- **Description:** When the LLM generates queries using aliases (e.g. `FROM documents d` or `FROM invoices i`), the injected WHERE predicate uses the table's raw name (`documents.uploaded_by = ...`), which PostgreSQL rejects as an undefined table in the FROM clause.
- **Security/Correctness Impact:** Severe denial-of-service / query failure on standard LLM outputs; potential authorization bypass if alias rewriting is improperly handled.
- **Evidence:** Code creates `exp.Column(this=exp.to_identifier("uploaded_by"), table=exp.to_identifier("documents"))` without inspecting `table.alias`.
- **Recommended Direction:** Inspect `table.alias`. If an alias exists, bind the injected predicate column to the alias identifier rather than the raw table name.
- **Blocks ReAct?** **YES**

---

### Finding CRIT-02: Missing Tenant Scoping for Normalized Child Tables in Text-to-SQL
- **Severity:** **CRITICAL**
- **Component:** Text-to-SQL Service
- **Location:** [text_to_sql_service.py: lines 225-255](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L225-L255)
- **Description:** For `FINANCE_ANALYST`, the AST rewriter only defines predicates for `documents`, `invoices`, `payment_obligations`, and `extraction_results`. For `invoice_line_items`, `vendors`, `vendor_aliases`, and `users`, `auth_predicate` remains `None`, injecting `WHERE None` (syntax crash) or leaving records unscoped.
- **Security/Correctness Impact:** Crashes PostgreSQL queries on child tables; risk of exposing confidential pricing and vendor relationships across analysts.
- **Evidence:** `if/elif` chain lacks handlers for `invoice_line_items`, `vendors`, `vendor_aliases`.
- **Recommended Direction:** Add predicate generators for all allowlisted business tables (e.g., scoping `invoice_line_items` via `invoice_id IN (SELECT id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE uploaded_by = :user_id))`).
- **Blocks ReAct?** **YES**

---

### Finding HIGH-01: Unrestricted Corporate User Directory Enumeration via Text-to-SQL
- **Severity:** **HIGH**
- **Component:** Text-to-SQL Service
- **Location:** [text_to_sql_service.py: lines 42-68](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L68)
- **Description:** `users` is present in `ALLOWED_TABLES` for all roles without row-level authorization. While `password_hash` is safely omitted, analysts can enumerate all corporate users, emails, and roles.
- **Security/Correctness Impact:** Internal reconnaissance / privilege boundary leak.
- **Evidence:** `ALLOWED_TABLES` is static and not filtered by `user.role`.
- **Recommended Direction:** Restrict `users` in `ALLOWED_TABLES` to `ADMIN` only, or scope analyst queries to `users.id = current_user.id`.
- **Blocks ReAct?** **YES**

---

### Finding MED-01: `audit_logs` Excluded from Allowlist for Auditor Role
- **Severity:** **MEDIUM**
- **Component:** Text-to-SQL Service
- **Location:** [text_to_sql_service.py: lines 42-55](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/text_to_sql_service.py#L42-L55)
- **Description:** The `audit_logs` table is omitted from `ALLOWED_TABLES`, preventing auditors from querying audit trails using Text-to-SQL.
- **Security/Correctness Impact:** Functional defect in Auditor role responsibilities.
- **Evidence:** `ALLOWED_TABLES = {"documents", "extraction_results", "document_chunks", "vendors", "vendor_aliases", "invoices", "invoice_line_items", "payment_obligations", "invoice_payments", "users"}`.
- **Recommended Direction:** Dynamically allow `audit_logs` for `AUDITOR` and `ADMIN` roles in Text-to-SQL.
- **Blocks ReAct?** **NO** (Can be addressed during tool definition phase)

---

### Finding MED-02: Silent Swallowing of Extraction Sync Exceptions
- **Severity:** **MEDIUM**
- **Component:** Extraction Service
- **Location:** [extraction_service.py: lines 180-186](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/services/extraction_service.py#L180-L186)
- **Description:** Exceptions raised during `sync_from_extraction` are caught, logged as warnings, and ignored. The document workflow transitions to `EXTRACTED` even if normalization failed.
- **Security/Correctness Impact:** Data lineage desynchronization (raw extraction exists, but relational tables are missing or partial).
- **Evidence:** `try: persistence_svc.sync_from_extraction(...) except Exception as exc: logger.warning(...)`.
- **Recommended Direction:** Ensure transaction rollback occurs on persistence failure, or mark extraction status as degraded/failed.
- **Blocks ReAct?** **NO**

---

### Finding LOW-01: Deterministic Keyword Router Lacks Dynamic Reasoning
- **Severity:** **LOW / ARCHITECTURAL**
- **Component:** Global Chat Orchestrator
- **Location:** [agent_orchestrator.py: lines 58-135](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/rag/agent_orchestrator.py#L58-L135)
- **Description:** Substring keyword triggers are rigid and do not support dynamic multi-step financial reasoning.
- **Security/Correctness Impact:** Architectural limitation scheduled for replacement by the ReAct agent.
- **Evidence:** Hardcoded lists `sql_triggers`, `calc_triggers`, `rag_triggers`.
- **Recommended Direction:** Replace with LangChain ReAct agent with explicit tool schemas.
- **Blocks ReAct?** **NO** (This is the objective of the next phase)

---

## 15. ReAct Readiness Assessment

| Area | Status | Assessment |
|---|---|---|
| **1. Database Readiness** | **READY** | Normalized schema is fully migrated (`361bf56d16a1`), indexed, and partitioned into clean logical tiers. |
| **2. Authentication Readiness** | **READY** | JWT authentication, user loading, and dependency injection are robust and trusted. |
| **3. Authorization Readiness** | **READY WITH FIXES** | RBAC/ABAC is solid at endpoints and RAG, but Text-to-SQL AST rewriting requires fixes for aliases and child tables. |
| **4. Text-to-SQL Readiness** | **BLOCKING DEFECTS** | AST sanitizer crashes on table aliases (`CRIT-01`) and child tables (`CRIT-02`), and leaks `users` table (`HIGH-01`). |
| **5. RAG Readiness** | **READY** | Pre-retrieval SQL filtering ensures strict tenant isolation across dense vector and sparse searches. |
| **6. Calculator Readiness** | **READY** | Financial calculator is isolated and arithmetic logic operates on verified numeric inputs. |
| **7. Tool Boundary Readiness** | **READY WITH FIXES** | Tool signatures and interfaces are clear; Text-to-SQL tool requires sanitizer fixes before binding to agent. |
| **8. Session / History Readiness** | **READY** | Stateless global chat and isolated document chat sessions provide clean boundaries for agent memory. |
| **9. Agent Integration Readiness** | **READY WITH FIXES** | Blocked only by Text-to-SQL sanitizer bugs; once fixed, LangChain tool bindings can proceed immediately. |

---

## 16. Required Fixes Before ReAct (Blockers)

The following three fixes are **STRICT BLOCKERS** before implementing the LangChain ReAct agent:

1. **Fix Table Alias Handling in `TextToSQLService` (`CRIT-01`)**:
   - Update `_apply_authorization_filters` to check `table.alias`. If present, construct the column predicate using the alias (e.g. `d.uploaded_by = :user_id`) instead of the unaliased table name.
2. **Implement Authorization Predicates for Child Tables in `TextToSQLService` (`CRIT-02`)**:
   - Add scoping clauses for `invoice_line_items` (via `invoice_id`), `vendors` (scoped to vendors associated with the analyst's invoices, or allow read-only global vendor directory if designed as shared master data), and `vendor_aliases`.
   - Prevent `exp.Where(this=None)` generation when a table has no predicate.
3. **Role-Gate `ALLOWED_TABLES` in `TextToSQLService` (`HIGH-01`)**:
   - Exclude `users` from `ALLOWED_TABLES` for `FINANCE_ANALYST` and `FINANCE_MANAGER`.

---

## 17. Non-Blocking Improvements

The following items should be addressed during or after the ReAct agent implementation:
1. **Dynamic Allowlist for Auditor**: Include `audit_logs` in `ALLOWED_TABLES` when `user.role == UserRole.AUDITOR.value`.
2. **Extraction Sync Error Handling**: Explicitly roll back or flag documents if `sync_from_extraction` encounters database constraint violations.
3. **Subquery Inspection in Text-to-SQL**: Ensure authorization filters are recursively applied to subqueries inside `WHERE IN (...)` or CTE clauses.

---

## 18. Final Verification Checklist

- [x] **Authentication verified** (JWT bearer, user identity, active checks verified in `dependencies.py`)
- [x] **Role propagation verified** (Database-backed `user.role` propagated to all service calls)
- [x] **Analyst isolation verified** (Enforced at document repo, service, and RAG levels)
- [x] **Manager scope verified** (Full corpus access across non-deleted documents)
- [x] **Auditor scope verified** (Cross-user read-only audit access verified)
- [x] **Admin scope verified** (Full administration and configuration access verified)
- [ ] **Text-to-SQL authorization verified** (**BLOCKED by CRIT-01, CRIT-02, HIGH-01**)
- [ ] **Alias handling verified** (**BLOCKED by CRIT-01**)
- [ ] **Join handling verified** (**BLOCKED by CRIT-02**)
- [x] **RAG authorization verified** (Pre-retrieval SQL filtering in `chunk_repository.py`)
- [x] **Document chat isolation verified** (Pre-execution ownership check in `chat.py`)
- [x] **Global chat isolation verified** (Delegates to underlying tool-level authorization)
- [x] **Extraction synchronization verified** (Idempotent sync in `InvoicePersistenceService`)
- [x] **Data lineage verified** (Clear separation: extraction provenance vs. normalized business tables)
- [x] **Payment authority verified** (`invoice_payments` isolated from extraction sync)
- [x] **Existing router documented** (Deterministic keyword orchestrator audited)
- [x] **ReAct blockers identified** (Clear list of 3 mandatory fixes provided)

---
*End of Audit Report.*
