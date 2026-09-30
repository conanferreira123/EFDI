"""Text-to-SQL Service with AST-Based Security Validation.

Uses sqlglot for robust AST parsing and validation.
Enforces:
- SELECT-only execution
- Strict table and column allowlists
- Rejection of DDL, DML, and dangerous functions
- Application-enforced authorization predicate injection
- Read-only transactions and 5-second execution timeout
- Hard row limit of 100 records
"""
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import text
from sqlalchemy.orm import Session
import sqlglot
from sqlglot import exp

from app.core.config import settings
from app.database.session import engine
from app.models.roles import UserRole
from app.models.user import User
from app.utils.clock import get_temporal_prompt_block
from app.rag.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Explicit table allowlist (universal superset)
ALLOWED_TABLES: Set[str] = {
    "documents",
    "extraction_results",
    "validation_results",
    "classification_results",
    "users",
    "invoices",
    "vendors",
    "vendor_aliases",
    "invoice_line_items",
    "payment_obligations",
    "invoice_payments",
    "workflow_history",
}

# Role-specific table allowlists
ROLE_ALLOWED_TABLES: Dict[str, Set[str]] = {
    UserRole.FINANCE_ANALYST.value: {
        "documents",
        "extraction_results",
        "classification_results",
        "validation_results",
        "invoices",
        "invoice_line_items",
        "payment_obligations",
        "vendors",
        "vendor_aliases",
        "invoice_payments",
    },
    UserRole.FINANCE_MANAGER.value: {
        "documents",
        "extraction_results",
        "classification_results",
        "validation_results",
        "invoices",
        "invoice_line_items",
        "payment_obligations",
        "vendors",
        "vendor_aliases",
        "invoice_payments",
    },
    UserRole.AUDITOR.value: {
        "documents",
        "extraction_results",
        "classification_results",
        "validation_results",
        "invoices",
        "invoice_line_items",
        "payment_obligations",
        "vendors",
        "vendor_aliases",
        "invoice_payments",
        "workflow_history",
    },
    UserRole.ADMIN.value: {
        "documents",
        "extraction_results",
        "classification_results",
        "validation_results",
        "invoices",
        "invoice_line_items",
        "payment_obligations",
        "vendors",
        "vendor_aliases",
        "invoice_payments",
        "users",
        "workflow_history",
    },
}

# Explicit column allowlist (users.password_hash is STRICTLY excluded)
ALLOWED_COLUMNS: Dict[str, Set[str]] = {
    "documents": {
        "id", "original_filename", "stored_filename", "document_type", "status",
        "company_code", "vendor_code", "validation_status", "file_size_bytes",
        "mime_type", "page_count", "is_deleted", "uploaded_by", "created_at", "updated_at",
    },
    "extraction_results": {
        "id", "document_id", "engine_name", "overall_confidence", "fields",
        "created_at", "updated_at",
    },
    "validation_results": {
        "id", "document_id", "is_valid", "error_count", "warning_count",
        "issues", "created_at", "updated_at",
    },
    "classification_results": {
        "id", "document_id", "predicted_type", "confidence", "scores_by_type",
        "created_at", "updated_at",
    },
    "users": {
        "id", "username", "email", "full_name", "role", "is_active", "created_at",
    },
    "invoices": {
        "id", "document_id", "source_extraction_result_id", "invoice_number",
        "invoice_date", "vendor_id", "buyer_name", "buyer_tax_id", "currency",
        "subtotal_amount", "tax_amount", "discount_amount", "shipping_amount",
        "rounding_amount", "other_charges_amount", "grand_total_amount",
        "po_number", "created_at", "updated_at",
    },
    "vendors": {
        "id", "canonical_name", "vendor_code", "tax_id", "address",
        "created_at", "updated_at",
    },
    "vendor_aliases": {
        "id", "vendor_id", "alias", "created_at",
    },
    "invoice_line_items": {
        "id", "invoice_id", "line_number", "description", "quantity",
        "uom", "unit_price", "net_amount", "tax_rate", "tax_amount",
        "gross_amount", "created_at",
    },
    "payment_obligations": {
        "id", "invoice_id", "amount_due", "amount_paid", "amount_outstanding",
        "currency", "due_date", "status", "payment_terms", "paid_at",
        "early_payment_deadline", "early_payment_discount", "late_payment_penalty",
        "created_at", "updated_at",
    },
    "invoice_payments": {
        "id", "invoice_id", "payment_date", "amount", "currency",
        "payment_reference", "payment_method", "created_at",
    },
    "workflow_history": {
        "id", "document_id", "action", "from_status", "to_status", "comment",
        "performed_by", "created_at",
    },
}

FORBIDDEN_FUNCTIONS: Set[str] = {
    "pg_sleep", "query_to_xml", "pg_read_file", "pg_write_file", "pg_stat_file",
    "version", "current_setting", "set_config", "dblink", "dblink_exec",
}


class SQLSecurityException(Exception):
    """Raised when a query fails AST security validation."""
    pass


class SQLQueryException(Exception):
    """Raised when SQL generation or safe execution fails."""
    pass


class TextToSQLService:
    """Service for safely translating financial questions into constrained SQL queries."""

    SCHEMA_CONTEXT = """PostgreSQL Database Schema:
Table: documents
Columns: id (int), original_filename (str), document_type (str: POI, NPO), status (str: UPLOADED, OCR_COMPLETED, EXTRACTED, VALIDATED, APPROVED, REJECTED, PENDING_APPROVAL), company_code (str), vendor_code (str), validation_status (str), file_size_bytes (int), uploaded_by (int), is_deleted (bool), created_at (timestamp)

Table: invoices
Columns: id (int), document_id (int, FK documents.id, UNIQUE), source_extraction_result_id (int, FK extraction_results.id), invoice_number (str), invoice_date (date), vendor_id (int, FK vendors.id), buyer_name (str), buyer_tax_id (str), currency (str), subtotal_amount (decimal), tax_amount (decimal), discount_amount (decimal), shipping_amount (decimal), rounding_amount (decimal), other_charges_amount (decimal), grand_total_amount (decimal), po_number (str), created_at (timestamp)

Table: vendors
Columns: id (int), canonical_name (str), vendor_code (str), tax_id (str), address (text), created_at (timestamp)

Table: invoice_line_items
Columns: id (int), invoice_id (int, FK invoices.id), line_number (int), description (text), quantity (decimal), uom (str), unit_price (decimal), net_amount (decimal), tax_rate (decimal), tax_amount (decimal), gross_amount (decimal)

Table: payment_obligations
Columns: id (int), invoice_id (int, FK invoices.id, UNIQUE), amount_due (decimal), amount_paid (decimal), amount_outstanding (decimal), currency (str), due_date (date), status (str: UNKNOWN, OPEN, PARTIALLY_PAID, PAID), payment_terms (text), early_payment_deadline (date), early_payment_discount (decimal), late_payment_penalty (decimal)

Table: invoice_payments
Columns: id (int), invoice_id (int, FK invoices.id), payment_date (date), amount (decimal), currency (str), payment_reference (str), payment_method (str)

Table: extraction_results
Columns: id (int), document_id (int, FK documents.id), fields (JSONB), overall_confidence (float), created_at (timestamp)

Table: validation_results
Columns: id (int), document_id (int, FK documents.id), is_valid (bool), error_count (int), warning_count (int), issues (JSONB), created_at (timestamp)

Table: classification_results
Columns: id (int), document_id (int, FK documents.id), predicted_type (str), confidence (float), created_at (timestamp)

Table: workflow_history (Access restricted: AUDITOR and ADMIN only)
Columns: id (int), document_id (int, FK documents.id), action (str), from_status (str), to_status (str), comment (text), performed_by (int, FK users.id), created_at (timestamp)

Table: users (Access restricted: ADMIN only)
Columns: id (int), username (str), email (str), full_name (str), role (str: FINANCE_ANALYST, FINANCE_MANAGER, AUDITOR, ADMIN)

BUSINESS SEMANTICS RULES:
1. OVERDUE INVOICES / OBLIGATIONS:
   Must be computed dynamically using:
   due_date < CURRENT_DATE AND (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID'
   CRITICAL: Do NOT filter by status = 'OVERDUE' because EFDI background workers do not populate that status automatically.
2. AWAITING REVIEW:
   Maps to documents.status = 'PENDING_APPROVAL'.
3. PROCESSED SPEND / INGESTION TIMESTAMPS:
   Maps to documents.created_at with documents.status IN ('VALIDATED', 'PENDING_APPROVAL', 'APPROVED') AND documents.is_deleted = false.
4. MULTI-CURRENCY AGGREGATION CONTRACT:
   - Never blindly SUM monetary amounts across heterogeneous currencies.
   - Always GROUP BY currency when computing monetary totals or spend breakdowns.
   - For questions asking for 'dollar value' (e.g. Q48, Q53), filter strictly to currency = 'USD'.
5. VENDOR SPEND RANKINGS (Q52):
   - Group by vendor and currency, and order by currency, spend DESC so separate per-currency rankings are produced.
6. SOFT DELETED RECORDS:
   - Always filter documents.is_deleted = false.
"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm_client = get_llm_client()

    @staticmethod
    def _get_select_immediate_tables(select: exp.Select) -> List[exp.Table]:
        """Extract tables belonging strictly to this SELECT's immediate FROM and JOIN clauses."""
        tables: List[exp.Table] = []
        from_clause = select.args.get("from_") or select.args.get("from")
        if from_clause:
            for t in from_clause.find_all(exp.Table):
                if t.find_ancestor(exp.Select) == select:
                    tables.append(t)
        for j in select.args.get("joins") or []:
            for t in j.find_all(exp.Table):
                if t.find_ancestor(exp.Select) == select:
                    tables.append(t)
        return tables

    def validate_and_sanitize_sql(self, raw_sql: str, user: User) -> str:
        """Parse raw SQL with sqlglot and enforce all security rules.

        Returns safe, parameterized/scoped SQL string.
        """
        clean_sql = raw_sql.strip().rstrip(";")
        if not clean_sql:
            raise SQLSecurityException("Empty SQL query provided.")

        try:
            ast = sqlglot.parse_one(clean_sql, read="postgres")
        except Exception as e:
            raise SQLSecurityException(f"SQL parsing failed: {e}")

        # 1. Reject any query that is not a SELECT statement
        if not isinstance(ast, exp.Select):
            raise SQLSecurityException(f"Only SELECT statements are permitted, got: {type(ast).__name__}")

        # 2. Check for disallowed AST expressions anywhere in the tree
        disallowed_types = (
            exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
            exp.Create, exp.Command,
        )
        for node in ast.walk():
            if isinstance(node, disallowed_types):
                raise SQLSecurityException(f"Forbidden SQL operation detected: {type(node).__name__}")
            if isinstance(node, exp.Anonymous):
                func_name = node.name.lower()
                if func_name in FORBIDDEN_FUNCTIONS:
                    raise SQLSecurityException(f"Forbidden SQL function detected: '{func_name}'")

        # 3. Role-aware table allowlist check
        user_allowed_tables = ROLE_ALLOWED_TABLES.get(user.role, set())
        tables_in_query = list(ast.find_all(exp.Table))
        if not tables_in_query:
            raise SQLSecurityException("Query must reference at least one valid table.")

        for t in tables_in_query:
            table_name = t.name.lower()
            if table_name not in user_allowed_tables:
                if table_name in ALLOWED_TABLES:
                    raise SQLSecurityException(
                        f"Access to table '{table_name}' is unauthorized for role '{user.role}'."
                    )
                raise SQLSecurityException(f"Access to table '{table_name}' is unauthorized.")

        # 4. Check columns against allowlist (strictly preventing password_hash)
        # Collect aliases defined in SELECT or CTEs to prevent false-positive rejection of projected aliases
        defined_aliases = {
            a.alias_or_name.lower()
            for a in ast.find_all(exp.Alias)
        }

        for col in ast.find_all(exp.Column):
            col_name = col.name.lower()
            if col_name == "*":
                continue
            if col.table:
                col_tbl_ref = col.table.lower()
                matched_table_name = None
                for t in tables_in_query:
                    if t.alias_or_name.lower() == col_tbl_ref or t.name.lower() == col_tbl_ref:
                        matched_table_name = t.name.lower()
                        break
                if not matched_table_name:
                    raise SQLSecurityException(
                        f"Column references table '{col_tbl_ref}' which is not in the FROM or JOIN clause."
                    )
                target_tbl = matched_table_name
                if target_tbl in ALLOWED_COLUMNS and col_name not in ALLOWED_COLUMNS[target_tbl]:
                    raise SQLSecurityException(f"Access to column '{col_tbl_ref}.{col_name}' is unauthorized.")
            else:
                # If column name matches a projected expression alias in this query, allow it
                if col_name in defined_aliases:
                    continue
                # Column without explicit table prefix: ensure it exists in at least one allowed table
                all_allowed = set().union(*[ALLOWED_COLUMNS[t] for t in user_allowed_tables if t in ALLOWED_COLUMNS])
                if col_name not in all_allowed:
                    raise SQLSecurityException(f"Access to column '{col_name}' is unauthorized.")

        # 5. Inject Authorization Predicates (Scope-Aware & Normalized Child-Table Scoped)
        is_analyst = user.role == UserRole.FINANCE_ANALYST.value
        policy = getattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "scoped")

        if is_analyst and policy == "forbidden":
            raise SQLSecurityException(
                "Access to Global AI database query is restricted to Finance Managers, Auditors, and Admins."
            )

        # Snapshot all Select scopes in the AST before injecting subqueries
        select_nodes = list(ast.find_all(exp.Select))

        for select in select_nodes:
            immediate_tables = self._get_select_immediate_tables(select)
            if not immediate_tables:
                continue

            predicates: List[exp.Expression] = []

            if is_analyst and policy == "scoped":
                for t in immediate_tables:
                    table_name = t.name.lower()
                    ref = t.alias_or_name
                    if table_name == "documents":
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.uploaded_by = {user.id} AND {ref}.is_deleted = false",
                                read="postgres",
                            )
                        )
                    elif table_name in ("invoices", "extraction_results", "classification_results", "validation_results"):
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false)",
                                read="postgres",
                            )
                        )
                    elif table_name in ("invoice_line_items", "payment_obligations", "invoice_payments"):
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.invoice_id IN (SELECT id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false))",
                                read="postgres",
                            )
                        )
                    elif table_name == "vendors":
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.id IN (SELECT vendor_id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false) AND vendor_id IS NOT NULL)",
                                read="postgres",
                            )
                        )
                    elif table_name == "vendor_aliases":
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.vendor_id IN (SELECT vendor_id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE uploaded_by = {user.id} AND is_deleted = false) AND vendor_id IS NOT NULL)",
                                read="postgres",
                            )
                        )
                    else:
                        # Fail closed on any table without an explicit scoping rule for FINANCE_ANALYST
                        raise SQLSecurityException(
                            f"Table '{table_name}' cannot be safely scoped for role '{user.role}'."
                        )
            else:
                # Finance Manager, Auditor, Admin: enforce is_deleted = false on documents and child tables
                for t in immediate_tables:
                    table_name = t.name.lower()
                    ref = t.alias_or_name
                    if table_name == "documents":
                        predicates.append(
                            sqlglot.parse_one(f"{ref}.is_deleted = false", read="postgres")
                        )
                    elif table_name in ("invoices", "extraction_results", "classification_results", "validation_results"):
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.document_id IN (SELECT id FROM documents WHERE is_deleted = false)",
                                read="postgres",
                            )
                        )
                    elif table_name in ("invoice_line_items", "payment_obligations", "invoice_payments"):
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.invoice_id IN (SELECT id FROM invoices WHERE document_id IN (SELECT id FROM documents WHERE is_deleted = false))",
                                read="postgres",
                            )
                        )
                    elif table_name == "workflow_history":
                        predicates.append(
                            sqlglot.parse_one(
                                f"{ref}.document_id IN (SELECT id FROM documents WHERE is_deleted = false)",
                                read="postgres",
                            )
                        )

            where_clause = select.args.get("where")
            combined_pred = where_clause.this if where_clause else None

            for p in predicates:
                if p is not None:
                    combined_pred = exp.And(this=combined_pred, expression=p) if combined_pred else p

            if combined_pred:
                select.set("where", exp.Where(this=combined_pred))

        # 6. Enforce LIMIT <= 100
        limit_clause = ast.args.get("limit")
        if not limit_clause or not limit_clause.expression.is_int or int(limit_clause.expression.this) > 100:
            ast.set("limit", exp.Limit(expression=exp.Literal.number(100)))

        return ast.sql(dialect="postgres")

    def execute_safe_query(self, safe_sql: str) -> Dict[str, Any]:
        """Execute validated query with read-only transaction and 5-second timeout."""
        start_time = time.perf_counter()
        logger.info("[Database Query Tool] Executing safe SQL: %s", safe_sql)

        with engine.connect() as conn:
            # Set read-only transaction and 5-second statement timeout
            conn.execute(text("SET TRANSACTION READ ONLY;"))
            conn.execute(text("SET LOCAL statement_timeout = '5000ms';"))

            result = conn.execute(text(safe_sql))
            rows = [dict(row._mapping) for row in result.fetchmany(100)]
            columns = list(result.keys())

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return {
            "sql": safe_sql,
            "row_count": len(rows),
            "columns": columns,
            "rows": rows,
            "execution_time_ms": elapsed_ms,
        }

    def generate_and_execute_sql(self, natural_language_query: str, user: User) -> Dict[str, Any]:
        """Convert natural language query to safe SQL, validate AST, and execute."""
        temporal_block = get_temporal_prompt_block()
        prompt = (
            f"You are a PostgreSQL expert for the EFDI system.\n"
            f"{self.SCHEMA_CONTEXT}\n\n"
            f"{temporal_block}\n\n"
            f"Generate a single SELECT query answering this user question:\n"
            f"Question: {natural_language_query}\n\n"
            f"Rules:\n"
            f"- Return ONLY the raw SQL SELECT query, no markdown, no explanation.\n"
            f"- Use standard PostgreSQL syntax.\n"
            f"- Keep row limit <= 100.\n"
        )

        try:
            generated_sql = self.llm_client._call_mistral_api([
                {"role": "system", "content": "You output only valid PostgreSQL SELECT queries."},
                {"role": "user", "content": prompt},
            ])
            # Strip any markdown code fences if present
            clean_sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", generated_sql.strip(), flags=re.IGNORECASE)
        except Exception as e:
            logger.error("LLM SQL generation failed: %s", e)
            raise SQLQueryException(f"Failed to generate SQL from user query: {e}") from e

        if not clean_sql:
            raise SQLQueryException("LLM returned empty SQL query.")

        safe_sql = self.validate_and_sanitize_sql(clean_sql, user=user)
        return self.execute_safe_query(safe_sql)
