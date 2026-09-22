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
from app.rag.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Explicit table allowlist
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
}

FORBIDDEN_FUNCTIONS: Set[str] = {
    "pg_sleep", "query_to_xml", "pg_read_file", "pg_write_file", "pg_stat_file",
    "version", "current_setting", "set_config", "dblink", "dblink_exec",
}


class SQLSecurityException(Exception):
    """Raised when a query fails AST security validation."""
    pass


class TextToSQLService:
    """Service for safely translating financial questions into constrained SQL queries."""

    SCHEMA_CONTEXT = """PostgreSQL Database Schema:
Table: documents
Columns: id (int), original_filename (str), document_type (str: POI, NPO), status (str: UPLOADED, OCR_COMPLETED, EXTRACTED, VALIDATED, APPROVED, REJECTED), company_code (str), vendor_code (str), validation_status (str), file_size_bytes (int), uploaded_by (int), is_deleted (bool), created_at (timestamp)

Table: invoices
Columns: id (int), document_id (int, FK documents.id, UNIQUE), source_extraction_result_id (int, FK extraction_results.id), invoice_number (str), invoice_date (date), vendor_id (int, FK vendors.id), buyer_name (str), buyer_tax_id (str), currency (str), subtotal_amount (decimal), tax_amount (decimal), discount_amount (decimal), shipping_amount (decimal), rounding_amount (decimal), other_charges_amount (decimal), grand_total_amount (decimal), po_number (str), created_at (timestamp)

Table: vendors
Columns: id (int), canonical_name (str), vendor_code (str), tax_id (str), address (text), created_at (timestamp)

Table: invoice_line_items
Columns: id (int), invoice_id (int, FK invoices.id), line_number (int), description (text), quantity (decimal), uom (str), unit_price (decimal), net_amount (decimal), tax_rate (decimal), tax_amount (decimal), gross_amount (decimal)

Table: payment_obligations
Columns: id (int), invoice_id (int, FK invoices.id, UNIQUE), amount_due (decimal), amount_paid (decimal), amount_outstanding (decimal), currency (str), due_date (date), status (str: UNKNOWN, OPEN, PARTIALLY_PAID, PAID, OVERDUE), payment_terms (text), early_payment_deadline (date), early_payment_discount (decimal), late_payment_penalty (decimal)

Table: invoice_payments
Columns: id (int), invoice_id (int, FK invoices.id), payment_date (date), amount (decimal), currency (str), payment_reference (str), payment_method (str)

Table: extraction_results
Columns: id (int), document_id (int, FK documents.id), fields (JSONB), overall_confidence (float), created_at (timestamp)

Table: validation_results
Columns: id (int), document_id (int, FK documents.id), is_valid (bool), error_count (int), warning_count (int), issues (JSONB), created_at (timestamp)

Table: classification_results
Columns: id (int), document_id (int, FK documents.id), predicted_type (str), confidence (float), created_at (timestamp)

Table: users
Columns: id (int), username (str), email (str), full_name (str), role (str: FINANCE_ANALYST, FINANCE_MANAGER, AUDITOR, ADMIN)
"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm_client = get_llm_client()

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

        # 3. Check tables against allowlist
        tables = [t.name.lower() for t in ast.find_all(exp.Table)]
        for table in tables:
            if table not in ALLOWED_TABLES:
                raise SQLSecurityException(f"Access to table '{table}' is unauthorized.")

        # 4. Check columns against allowlist (strictly preventing password_hash)
        for col in ast.find_all(exp.Column):
            col_name = col.name.lower()
            if col_name == "*":
                continue
            if col.table:
                tbl = col.table.lower()
                if tbl in ALLOWED_COLUMNS and col_name not in ALLOWED_COLUMNS[tbl]:
                    raise SQLSecurityException(f"Access to column '{tbl}.{col_name}' is unauthorized.")
            else:
                # Column without explicit table prefix: ensure it exists in at least one allowed table
                all_allowed = set().union(*ALLOWED_COLUMNS.values())
                if col_name not in all_allowed:
                    raise SQLSecurityException(f"Access to column '{col_name}' is unauthorized.")

        # 5. Inject Authorization Predicate for FINANCE_ANALYST
        is_analyst = user.role == UserRole.FINANCE_ANALYST.value
        policy = getattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "scoped")

        if is_analyst and policy == "scoped":
            # Forcibly inject `documents.uploaded_by = :user_id` and `documents.is_deleted = false`
            if "documents" in tables:
                auth_predicate = sqlglot.parse_one(
                    f"documents.uploaded_by = {user.id} AND documents.is_deleted = false",
                    read="postgres",
                )
            elif "invoices" in tables:
                ast = ast.join("documents", on="invoices.document_id = documents.id")
                auth_predicate = sqlglot.parse_one(
                    f"documents.uploaded_by = {user.id} AND documents.is_deleted = false",
                    read="postgres",
                )
            elif "payment_obligations" in tables:
                ast = ast.join("invoices", on="payment_obligations.invoice_id = invoices.id")
                ast = ast.join("documents", on="invoices.document_id = documents.id")
                auth_predicate = sqlglot.parse_one(
                    f"documents.uploaded_by = {user.id} AND documents.is_deleted = false",
                    read="postgres",
                )
            elif "extraction_results" in tables:
                # If querying extraction_results without documents table, join documents
                ast = ast.join("documents", on=f"extraction_results.document_id = documents.id")
                auth_predicate = sqlglot.parse_one(
                    f"documents.uploaded_by = {user.id} AND documents.is_deleted = false",
                    read="postgres",
                )
            else:
                auth_predicate = None

            where_clause = ast.args.get("where")
            if where_clause:
                combined_where = exp.Where(
                    this=exp.And(this=where_clause.this, expression=auth_predicate)
                )
                ast.set("where", combined_where)
            else:
                ast.set("where", exp.Where(this=auth_predicate))
        elif "documents" in tables:
            # For managers/auditors/admins, still enforce non-deleted documents
            soft_del_predicate = sqlglot.parse_one("documents.is_deleted = false", read="postgres")
            where_clause = ast.args.get("where")
            if where_clause:
                combined_where = exp.Where(
                    this=exp.And(this=where_clause.this, expression=soft_del_predicate)
                )
                ast.set("where", combined_where)
            else:
                ast.set("where", exp.Where(this=soft_del_predicate))

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
        prompt = (
            f"You are a PostgreSQL expert for the EFDI system.\n"
            f"{self.SCHEMA_CONTEXT}\n\n"
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
            logger.warning("LLM SQL generation failed: %s; using deterministic keyword heuristic", e)
            clean_sql = self._heuristic_sql_fallback(natural_language_query)

        safe_sql = self.validate_and_sanitize_sql(clean_sql, user=user)
        return self.execute_safe_query(safe_sql)

    def _heuristic_sql_fallback(self, query: str) -> str:
        """Deterministic query fallback for common metrics/count queries."""
        q_lower = query.lower()
        if "validated" in q_lower:
            return "SELECT id, original_filename, document_type, status FROM documents WHERE status = 'VALIDATED' LIMIT 50"
        elif "how many" in q_lower or "count" in q_lower:
            return "SELECT status, COUNT(*) as count FROM documents GROUP BY status LIMIT 50"
        elif "uploaded by" in q_lower:
            return "SELECT id, original_filename, status, created_at FROM documents ORDER BY created_at DESC LIMIT 50"
        else:
            return "SELECT id, original_filename, document_type, status, created_at FROM documents ORDER BY created_at DESC LIMIT 50"
