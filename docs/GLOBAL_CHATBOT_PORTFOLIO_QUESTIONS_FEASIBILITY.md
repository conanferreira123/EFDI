# Global Chatbot Portfolio Questions Feasibility

## 1. Executive Summary

This feasibility analysis evaluates the readiness of the EFDI Global Chatbot architecture to answer seven portfolio-level financial questions (**Q47–Q53**) using the **current database schema and codebase**, without introducing synthetic data, Purchase Order tables, or speculative multi-document schemas.

### Key Findings
1. **No Purchase Order Entity**: EFDI has **no Purchase Orders table** and no two-way/three-way matching engine. Invoices store an optional, unverified string `po_number: Optional[str]`, and documents have an ML classification tag (`document_type = 'POI' | 'NPO'`). Consequently, **Q49 cannot be answered under its original enterprise semantic meaning of "PO-backed"**. It can only be supported if reframed around recorded PO number presence or document classification type.
2. **No Exchange Rate Mechanism**: The database contains **zero exchange rate tables or feeds**. Financial values are recorded in their source currency (`currency: str`). Therefore, questions requesting a portfolio-wide "dollar value" across mixed currencies (**Q48, Q53**) **cannot mathematically or financially sum heterogeneous currencies**. They must return **currency-separated breakdowns** or be explicitly scoped to USD transactions with transparent exclusions.
3. **No Configured Fiscal Calendar**: The system contains no fiscal calendar setting. Questions referencing the "current fiscal quarter" (**Q47**) or "current fiscal year" (**Q52**) must default to the **standard calendar year** (Q1 = Jan–Mar, etc.) unless an explicit corporate fiscal year start month is configured.
4. **Dynamic Overdue Semantics**: EFDI defines `PaymentStatus.OVERDUE`, but **no automated background job, trigger, or worker ever sets an obligation to 'OVERDUE'**. All obligations are initialized to `OPEN` or `UNKNOWN`. Therefore, **Q51** ("percentage of total invoices flagged as overdue") will report 0% if querying `status = 'OVERDUE'`. It can only be answered by dynamically calculating `due_date < CURRENT_DATE AND (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID'`.
5. **Impact of Proposed Improvements**:
   - **Reliably Supported After Improvements**: **Q47, Q50, Q51, Q52**.
   - **Supported Under Strict Policy (Currency-Separated / USD-Scoped)**: **Q48, Q53**.
   - **Unsupported Under Original ERP Semantics / Reframing Required**: **Q49**.

---

## 2. Q47 Analysis
> *"How many financial documents are currently recorded in the system for the current fiscal quarter?"*

1. **Current Database Content**: Contains all required document records and upload timestamps in `documents`.
2. **Tables and Columns Required**:
   - `documents.id` (integer, primary key)
   - `documents.created_at` (timestamp with time zone)
   - `documents.is_deleted` (boolean soft-delete filter)
   - `documents.document_type` (string enum, optional filter to exclude `UNKNOWN`)
   - `documents.uploaded_by` (integer, required for `FINANCE_ANALYST` role scoping)
3. **Current SQL Tool Execution**: Yes. A single-table query can execute `SELECT COUNT(*) FROM documents WHERE ...`.
4. **Current Authorization**: Fully allowed for all authenticated roles (`documents` is in `ROLE_ALLOWED_TABLES`).
5. **Current TextToSQL Generation Reliability**: **Unreliable**. TextToSQL has no knowledge of current system time and lacks instructions on what constitutes a "fiscal quarter".
6. **Temporal Awareness Required**: **YES (Critical)**. Requires system clock to resolve `CURRENT_DATE`, the current year, and the quarter boundary interval.
7. **Currency Handling Required**: No (pure document count).
8. **RAG Required**: No.
9. **Calculator Required**: No (PostgreSQL `COUNT(*)`).
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - LLM lacks clock injection; may hallucinate an arbitrary year (e.g. 2023 or 2024).
    - If the LLM produces invalid SQL date functions, `TextToSQLService` silently falls back to `_heuristic_sql_fallback`, returning an unconstrained status count.
12. **Specific Modification from Proposed Plan**:
    - Phase 1: Inject UTC timestamp, current year, and current quarter into system and SQL generation prompts.
    - Phase 2: Remove silent heuristic fallback.
13. **Remaining Limitations**:
    - EFDI has no custom fiscal calendar configuration. If the client operates on an off-calendar fiscal year (e.g. starting April 1 or October 1), the system will default to calendar quarters (Q1 = Jan–Mar) unless an explicit fiscal calendar policy is established.

---

## 3. Q48 Analysis
> *"What is the total dollar value of outstanding accounts payable across all vendors today?"*

1. **Current Database Content**: Contains `payment_obligations.amount_outstanding`, `payment_obligations.currency`, and `due_date`. However, **it does NOT contain currency exchange rates**.
2. **Tables and Columns Required**:
   - `payment_obligations.amount_outstanding` (numeric/decimal)
   - `payment_obligations.currency` (string, e.g. USD, EUR, GBP)
   - `payment_obligations.status` (string enum)
   - `payment_obligations.invoice_id` (foreign key)
   - `invoices.document_id` (foreign key)
   - `documents.is_deleted` (boolean)
3. **Current SQL Tool Execution**: Can execute `SELECT currency, SUM(amount_outstanding) FROM payment_obligations GROUP BY currency`.
4. **Current Authorization**: Allowed. `payment_obligations`, `invoices`, and `documents` are in `ROLE_ALLOWED_TABLES`.
5. **Current TextToSQL Generation Reliability**: **Severely Flawed**. The LLM routinely executes `SELECT SUM(amount_outstanding) FROM payment_obligations`, blindly summing USD, EUR, and GBP numbers together into an erroneous single number.
6. **Temporal Awareness Required**: Minor ("today" implies current open obligations where `amount_outstanding > 0` and `status != 'PAID'`).
7. **Currency Handling Required**: **CRITICAL**.
   - *Feasibility Determination*: EFDI **cannot compute a unified "dollar value" across mixed currencies** without exchange rates.
   - *Required Behavior*: The query must produce **currency-separated totals** (e.g. `$1,250,000 USD, €420,000 EUR, £85,000 GBP`) OR filter strictly to `currency = 'USD'` with an explicit note: *"Total USD AP is $1,250,000 (excluding €420,000 EUR and £85,000 GBP in non-USD obligations)"*.
8. **RAG Required**: No.
9. **Calculator Required**: No (PostgreSQL `SUM()` with `GROUP BY currency`).
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - Blind summation across currencies in current Text-to-SQL prompt.
    - Lack of currency contract in tool response schema.
12. **Specific Modification from Proposed Plan**:
    - Phase 2: Add strict SQL generation rule: *Always group monetary sums by currency; never sum mixed currencies into a single total.*
    - Phase 3: Structured result contract returning a multi-currency breakdown table.
13. **Remaining Limitations**:
    - Cannot provide a single consolidated USD figure for multi-currency portfolios without introducing an exchange rate data source.

---

## 4. Q49 Analysis
> *"How many non-PO invoices are currently awaiting review compared to PO-backed invoices?"*

1. **Current Database Content**:
   - Invoices contain an optional string `po_number: Optional[str]`.
   - Documents contain an ML classification tag `document_type: str` (`POI` = PO-based Invoice, `NPO` = Non-PO Invoice).
   - Documents contain `status: str` where `PENDING_APPROVAL` represents invoices awaiting human review.
   - **Crucial Absence**: The database **DOES NOT have a Purchase Order entity**, PO lines, or matching validation results verifying that an invoice is "PO-backed".
2. **Tables and Columns Required**:
   - `documents.id`, `documents.document_type`, `documents.status`, `documents.is_deleted`
   - `invoices.po_number`, `invoices.document_id`
3. **Current SQL Tool Execution**: Can execute grouping on `document_type` or `CASE WHEN po_number IS NOT NULL...`.
4. **Current Authorization**: Fully allowed.
5. **Current TextToSQL Generation Reliability**: **Unreliable**. LLM is uncertain whether "awaiting review" maps to `status = 'PENDING_APPROVAL'` or `status = 'VALIDATED'`.
6. **Temporal Awareness Required**: Minor ("currently").
7. **Currency Handling Required**: No.
8. **RAG Required**: No.
9. **Calculator Required**: No.
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - **Semantic Impossibility of Original Question**: In enterprise accounting, "PO-backed" implies verification against an approved PO. In EFDI, `po_number` is merely an unverified OCR string, and `document_type = 'POI'` is a classification prediction.
12. **Specific Modification from Proposed Plan**:
    - **Reframing Required**: Q49 must be explicitly defined and reframed as:
      *"How many invoices in Pending Approval status are classified as NPO versus POI?"*
      OR
      *"How many invoices in Pending Approval status have a PO number recorded versus no PO number recorded?"*
    - Document in `SCHEMA_CONTEXT` that "awaiting review" maps to `documents.status = 'PENDING_APPROVAL'`.
13. **Remaining Limitations**:
    - **Original Q49 remains unsupported** under true ERP semantics. EFDI cannot confirm that an invoice is genuinely backed by a valid Purchase Order.

---

## 5. Q50 Analysis
> *"What is the total spend processed through the system in the last 30 days broken down by currency?"*

1. **Current Database Content**: **Fully Available**. `invoices` contains `grand_total_amount` and `currency`. `documents` contains upload/processing timestamp `created_at` and `status`.
2. **Tables and Columns Required**:
   - `invoices.grand_total_amount` (numeric)
   - `invoices.currency` (string)
   - `invoices.document_id` (foreign key)
   - `documents.created_at` (timestamp, ingestion/processing date)
   - `documents.status` (filter for processed invoices, e.g. `VALIDATED`, `APPROVED`)
   - `documents.is_deleted` (boolean)
3. **Current SQL Tool Execution**: **Yes**.
   ```sql
   SELECT i.currency, SUM(i.grand_total_amount) AS total_spend, COUNT(*) AS invoice_count
   FROM invoices i
   JOIN documents d ON i.document_id = d.id
   WHERE d.is_deleted = false
     AND d.created_at >= CURRENT_DATE - INTERVAL '30 days'
     AND d.status IN ('VALIDATED', 'PENDING_APPROVAL', 'APPROVED')
   GROUP BY i.currency
   ```
4. **Current Authorization**: Fully allowed.
5. **Current TextToSQL Generation Reliability**: **Moderate to Poor**. Frequently confuses `documents.created_at` (processing date) with `invoices.invoice_date` (vendor issue date), and lacks system clock grounding.
6. **Temporal Awareness Required**: **YES (Critical)**. Requires resolving the rolling 30-day window from `CURRENT_DATE`.
7. **Currency Handling Required**: **Built-in**. The question explicitly requests a breakdown by currency, which matches EFDI's data model.
8. **RAG Required**: No.
9. **Calculator Required**: No (PostgreSQL aggregation).
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - TextToSQL lacks temporal context.
    - Ambiguity between `invoice_date` vs `created_at`.
12. **Specific Modification from Proposed Plan**:
    - Phase 1: Temporal context injection.
    - Phase 2: Schema documentation clarifying that "processed through the system" corresponds to `documents.created_at` and status `IN ('VALIDATED', 'PENDING_APPROVAL', 'APPROVED')`.
13. **Remaining Limitations**:
    - Records with unextracted/NULL currency will be grouped under `NULL` or `'UNKNOWN'`.

---

## 6. Q51 Analysis
> *"What percentage of total invoices are currently flagged as overdue?"*

1. **Current Database Content**: Contains `payment_obligations.due_date`, `payment_obligations.amount_outstanding`, and `payment_obligations.status`.
2. **Tables and Columns Required**:
   - `payment_obligations.due_date` (date)
   - `payment_obligations.amount_outstanding` (numeric)
   - `payment_obligations.status` (string enum)
   - `payment_obligations.invoice_id` (foreign key)
   - `invoices.id` (primary key)
   - `documents.is_deleted` (boolean)
3. **Current SQL Tool Execution**: Can execute via conditional aggregation:
   ```sql
   SELECT
     COUNT(*) AS total_invoices,
     COUNT(CASE WHEN po.due_date < CURRENT_DATE AND (po.amount_outstanding > 0 OR po.amount_outstanding IS NULL) AND po.status != 'PAID' THEN 1 END) AS overdue_invoices,
     ROUND(
       COUNT(CASE WHEN po.due_date < CURRENT_DATE AND (po.amount_outstanding > 0 OR po.amount_outstanding IS NULL) AND po.status != 'PAID' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0),
       2
     ) AS overdue_percentage
   FROM invoices i
   JOIN documents d ON i.document_id = d.id
   LEFT JOIN payment_obligations po ON i.id = po.invoice_id
   WHERE d.is_deleted = false
   ```
4. **Current Authorization**: Fully allowed.
5. **Current TextToSQL Generation Reliability**: **Completely Fails**.
   - *Root Cause*: The LLM generates `WHERE po.status = 'OVERDUE'`.
   - *Database Reality*: In EFDI, **no process ever updates `payment_obligations.status` to 'OVERDUE'**. All obligations remain `OPEN`. The query returns `0.0%`.
6. **Temporal Awareness Required**: **YES (Critical)**. Requires comparing `due_date < CURRENT_DATE`.
7. **Currency Handling Required**: No (ratio of counts).
8. **RAG Required**: No.
9. **Calculator Required**: Optional. Can be computed entirely in SQL or formatted by calculator.
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - The LLM's false assumption that `status = 'OVERDUE'` is populated in data.
    - Lack of clock context.
12. **Specific Modification from Proposed Plan**:
    - Phase 1: Clock injection.
    - Phase 2: Update `SCHEMA_CONTEXT` to explicitly define overdue:
      *"Overdue invoices must be identified dynamically: po.due_date < CURRENT_DATE AND po.amount_outstanding > 0 AND po.status != 'PAID'. Do not filter by po.status = 'OVERDUE'."*
13. **Remaining Limitations**:
    - Invoices where OCR failed to extract a valid `due_date` cannot be evaluated for overdue status.

---

## 7. Q52 Analysis
> *"Who are our top 5 vendors by total invoiced spend in the current fiscal year?"*

1. **Current Database Content**: Contains `vendors.canonical_name`, `invoices.vendor_id`, `invoices.grand_total_amount`, and `invoices.invoice_date`.
2. **Tables and Columns Required**:
   - `vendors.id`, `vendors.canonical_name`
   - `invoices.vendor_id`, `invoices.grand_total_amount`, `invoices.invoice_date`, `invoices.currency`
   - `documents.is_deleted`
3. **Current SQL Tool Execution**: Yes, with `GROUP BY` and `LIMIT 5`.
4. **Current Authorization**: Fully allowed.
5. **Current TextToSQL Generation Reliability**: **Moderate**. Vulnerable to fiscal year ambiguity and currency mixing.
6. **Temporal Awareness Required**: **YES (Critical)**. Requires resolving the start date of the current fiscal year (default: Jan 1 of current year).
7. **Currency Handling Required**: **CRITICAL**.
   - If Vendor A has $100,000 USD and Vendor B has €95,000 EUR, sorting by raw `grand_total_amount` assumes 1 EUR = 1 USD.
   - *Required Behavior*: Must either group by `(v.canonical_name, i.currency)` or state that rankings are computed in primary currency (USD), with non-USD totals reported alongside.
8. **RAG Required**: No.
9. **Calculator Required**: No.
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - Blind currency mixing in `ORDER BY SUM(grand_total_amount)`.
    - No fiscal calendar definition.
    - Truncation limit (not an issue here since question specifies `LIMIT 5`).
12. **Specific Modification from Proposed Plan**:
    - Phase 1: Temporal context injection.
    - Phase 2: Schema rule enforcing currency grouping or USD-specific ranking.
13. **Remaining Limitations**:
    - A mathematically unified multi-currency top-5 ranking is impossible without real exchange rates.

---

## 8. Q53 Analysis
> *"Which vendor currently has the highest total dollar value of unpaid obligations?"*

1. **Current Database Content**: Contains `vendors.canonical_name`, `invoices.vendor_id`, `payment_obligations.amount_outstanding`, and `payment_obligations.currency`.
2. **Tables and Columns Required**:
   - `vendors.canonical_name`
   - `invoices.vendor_id`, `invoices.id`
   - `payment_obligations.amount_outstanding`, `payment_obligations.currency`, `payment_obligations.status`
   - `documents.is_deleted`
3. **Current SQL Tool Execution**: Yes, joining `vendors`, `invoices`, and `payment_obligations`.
4. **Current Authorization**: Fully allowed.
5. **Current TextToSQL Generation Reliability**: **Poor**. LLM ignores currency and sums all unpaid obligations regardless of whether they are USD, EUR, or GBP.
6. **Temporal Awareness Required**: Minor ("currently").
7. **Currency Handling Required**: **CRITICAL**.
   - The question explicitly asks for **"dollar value"**.
   - *Required Behavior*: The query must filter strictly to `po.currency = 'USD'`:
     ```sql
     SELECT v.canonical_name, SUM(po.amount_outstanding) AS total_unpaid_usd
     FROM vendors v
     JOIN invoices i ON v.id = i.vendor_id
     JOIN payment_obligations po ON i.id = po.invoice_id
     JOIN documents d ON i.document_id = d.id
     WHERE d.is_deleted = false
       AND po.amount_outstanding > 0
       AND po.status != 'PAID'
       AND po.currency = 'USD'
     GROUP BY v.id, v.canonical_name
     ORDER BY total_unpaid_usd DESC
     LIMIT 1
     ```
     The agent must transparently report: *"Vendor X has the highest unpaid obligations in USD ($Y). Unpaid non-USD obligations are tracked separately (e.g. Vendor Z with €W EUR)."*
8. **RAG Required**: No.
9. **Calculator Required**: No.
10. **Multi-Tool Orchestration Required**: No.
11. **Existing Architectural Limitations Blocking It**:
    - The LLM merges mixed currencies into a false "dollar" answer.
12. **Specific Modification from Proposed Plan**:
    - Phase 2: Strict SQL currency filtering for dollar-specific questions.
13. **Remaining Limitations**:
    - If a vendor's debt is in Euros, they cannot be compared against a USD vendor on a single unified scale without exchange rates.

---

## 9. Capability Matrix

| Question | Current Data Available? | SQL Sufficient? | RAG Required? | Calculator Required? | Temporal Awareness? | Currency Handling? | Feasibility After Proposed Improvements | Primary Constraint / Reframing Required |
|---|---|---|---|---|---|---|---|---|
| **Q47** (Documents in current fiscal quarter) | **YES** | **YES** | No | No | **YES** (Current quarter) | No | **RELIABLY SUPPORTED** | Requires default calendar year policy (Jan–Dec). |
| **Q48** (Total dollar value of outstanding AP) | **PARTIAL** (No exchange rates) | **YES** (Grouped) | No | No | Minor (Today) | **YES (CRITICAL)** | **SUPPORTED (Policy)** | Must return currency breakdown or USD-only with disclosure. |
| **Q49** (Non-PO vs PO-backed awaiting review) | **NO** (No PO entity) | **YES** (Reframed) | No | No | Minor (Awaiting) | No | **REFRAMED ONLY** | **Original unsupported**. Must reframe to NPO vs POI or PO number recorded. |
| **Q50** (Spend in last 30 days by currency) | **YES** | **YES** | No | No | **YES** (Last 30 days) | **YES** (By currency) | **RELIABLY SUPPORTED** | Question already requests currency breakdown. |
| **Q51** (% invoices currently overdue) | **YES** | **YES** | No | Optional | **YES** (Due date < Today) | No | **RELIABLY SUPPORTED** | Must compute dynamically; cannot use `status = 'OVERDUE'`. |
| **Q52** (Top 5 vendors by spend in fiscal year) | **PARTIAL** (No exchange rates) | **YES** (Grouped) | No | No | **YES** (Current year) | **YES (CRITICAL)** | **SUPPORTED (Policy)** | Requires calendar year default and currency-grouped sorting. |
| **Q53** (Vendor with highest unpaid dollar value) | **PARTIAL** (No exchange rates) | **YES** (USD-filtered) | No | No | Minor (Currently) | **YES (CRITICAL)** | **SUPPORTED (Policy)** | Must filter to USD explicitly and report non-USD separately. |

---

## 10. Required Modifications to the Implementation Plan

To ensure the implementation plan guarantees reliable execution of Q47–Q53 without over-engineering, the following concrete additions must be incorporated:

1. **Phase 1: Clock & Calendar Context Injection**:
   - Provide `CURRENT_UTC_DATE`, `CURRENT_YEAR`, and `CURRENT_CALENDAR_QUARTER` to both the ReAct Agent prompt and the `TextToSQLService` prompt.
   - Establish that "fiscal year" and "fiscal quarter" default to the standard calendar year (Q1: Jan 1–Mar 31, Q2: Apr 1–Jun 30, Q3: Jul 1–Sep 30, Q4: Oct 1–Dec 31).
2. **Phase 2: Database Schema Context & Dynamic Overdue Rule**:
   - Explicitly instruct Text-to-SQL:
     - *Overdue Rule*: `due_date < CURRENT_DATE AND (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID'`. (Never query `status = 'OVERDUE'`).
     - *Awaiting Review Rule*: `documents.status = 'PENDING_APPROVAL'`.
     - *Processed Spend Date Rule*: "Processed in last N days" maps to `documents.created_at >= CURRENT_DATE - INTERVAL 'N days'`.
3. **Phase 3: Multi-Currency Presentation Contract**:
   - Enforce that queries requesting sums, spend, or totals across the portfolio must `GROUP BY currency`.
   - When a user explicitly asks for "dollar value", the SQL must filter to `currency = 'USD'`, and the synthesis prompt must state non-USD amounts separately rather than attempting cross-currency addition.
4. **Phase 2: Removal of Silent Heuristic Fallback**:
   - Discard `_heuristic_sql_fallback`. If Text-to-SQL fails, return a structured error so the agent can report the failure accurately or retry with proper constraints.

---

## 11. Questions That Must Remain Unsupported

1. **Original Semantic Meaning of Q49 ("PO-backed invoices")**:
   - **Reason**: EFDI does not integrate with an ERP Purchase Order database. It cannot verify whether an invoice is legitimately backed by an authorized purchase order.
   - **Status**: The original question is **UNSUPPORTED**. It will only be supported if reframed as:
     *"Invoices awaiting review classified as NPO versus POI"* or *"Invoices awaiting review with a PO number recorded versus no PO number recorded"*.
2. **Unified Cross-Currency Net Totals in Q48, Q52, and Q53**:
   - **Reason**: The database does not contain exchange rates. Converting EUR, GBP, and JPY into USD is impossible without introducing synthetic or unverified rates.
   - **Status**: Consolidated cross-currency summation is **UNSUPPORTED**. Supported only as **currency-separated breakdowns** or **USD-specific scoped queries**.

---

## 12. Decisions Requiring Approval Before Implementation

Before proceeding to finalize the implementation plan, the following three architectural decisions require user confirmation:

1. **Fiscal Calendar Default**:
   - *Recommendation*: Default "fiscal quarter" and "fiscal year" to the **standard calendar year** (Jan 1–Dec 31).
   - *Alternative*: Specify a custom fiscal year start month (e.g. April 1).
2. **Reframing of Q49**:
   - *Recommendation*: Reframe Q49 to compare classification types (`document_type = 'NPO'` vs `document_type = 'POI'` in `status = 'PENDING_APPROVAL'`).
   - *Alternative*: Reframe to invoices with a non-empty `po_number` string vs empty `po_number`.
3. **Multi-Currency Policy for "Dollar" Questions (Q48, Q53)**:
   - *Recommendation*: Execute the query strictly on `currency = 'USD'`, and transparently summarize other currencies in the final response (e.g., *"Total USD AP is $X. In addition, there is €Y EUR and £Z GBP outstanding"*).
   - *Alternative*: Refuse single-currency total and return a full tabular breakdown by currency for all portfolio spend questions.
