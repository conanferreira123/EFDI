"""Tests for SQL Safety and AST Validation in TextToSQLService.
"""
import pytest
from app.database.session import get_db_context
from app.models.user import User, UserRole
from app.services.text_to_sql_service import SQLSecurityException, TextToSQLService


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def mock_analyst():
    return User(
        id=42,
        username="analyst_test",
        email="analyst@example.com",
        full_name="Analyst Test",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )


@pytest.fixture
def mock_manager():
    return User(
        id=1,
        username="manager_test",
        email="manager@example.com",
        full_name="Manager Test",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )


def test_sql_safety_rejects_dml_update(db_session, mock_manager):
    """AST validator must reject UPDATE statements."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="Only SELECT statements are permitted"):
        service.validate_and_sanitize_sql("UPDATE documents SET status = 'APPROVED'", user=mock_manager)


def test_sql_safety_rejects_dml_delete(db_session, mock_manager):
    """AST validator must reject DELETE statements."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="Only SELECT statements are permitted"):
        service.validate_and_sanitize_sql("DELETE FROM documents WHERE id = 1", user=mock_manager)


def test_sql_safety_rejects_ddl_drop(db_session, mock_manager):
    """AST validator must reject DROP statements."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="Only SELECT statements are permitted"):
        service.validate_and_sanitize_sql("DROP TABLE documents", user=mock_manager)


def test_sql_safety_rejects_ddl_alter(db_session, mock_manager):
    """AST validator must reject ALTER statements."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="Only SELECT statements are permitted"):
        service.validate_and_sanitize_sql("ALTER TABLE documents ADD COLUMN hacked TEXT", user=mock_manager)


def test_sql_safety_rejects_unauthorized_table(db_session, mock_manager):
    """AST validator must reject queries to tables outside allowlist."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="unauthorized"):
        service.validate_and_sanitize_sql("SELECT * FROM audit_logs", user=mock_manager)


def test_sql_safety_rejects_unauthorized_columns_password_hash(db_session, mock_manager):
    """AST validator must strictly reject access to users.password_hash."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="unauthorized"):
        service.validate_and_sanitize_sql("SELECT id, username, password_hash FROM users", user=mock_manager)


def test_sql_safety_rejects_dangerous_functions(db_session, mock_manager):
    """AST validator must reject sleep or dangerous DB functions."""
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException, match="Forbidden SQL function"):
        service.validate_and_sanitize_sql("SELECT id, pg_sleep(5) FROM documents", user=mock_manager)


def test_sql_safety_enforces_limit(db_session, mock_manager):
    """Query without LIMIT or with LIMIT > 100 must be clamped to LIMIT 100."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT id, status FROM documents", user=mock_manager)
    assert "LIMIT 100" in sanitized

    sanitized_high = service.validate_and_sanitize_sql("SELECT id, status FROM documents LIMIT 5000", user=mock_manager)
    assert "LIMIT 100" in sanitized_high


def test_sql_safety_injects_analyst_authorization(db_session, mock_analyst):
    """AST validator must inject documents.uploaded_by = :user_id for FINANCE_ANALYST."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT id, status FROM documents WHERE status = 'VALIDATED'", user=mock_analyst)
    # Both uploaded_by and is_deleted must be present in the generated SQL
    assert "documents.uploaded_by = 42" in sanitized
    assert "documents.is_deleted = false" in sanitized.lower()


@pytest.fixture
def mock_admin():
    return User(
        id=99,
        username="admin_test",
        email="admin@example.com",
        full_name="Admin Test",
        role=UserRole.ADMIN.value,
        is_active=True,
    )


def test_sql_safety_alias_handling_documents(db_session, mock_analyst):
    """AST validator must scope documents using table alias identifier."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT d.id FROM documents d", user=mock_analyst)
    assert "d.uploaded_by = 42" in sanitized
    assert "d.is_deleted = false" in sanitized.lower()


def test_sql_safety_alias_handling_invoices(db_session, mock_analyst):
    """AST validator must scope invoices using alias identifier and subquery."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT i.invoice_number FROM invoices i", user=mock_analyst)
    assert "i.document_id in" in sanitized.lower()
    assert "uploaded_by = 42" in sanitized
    assert "is_deleted = false" in sanitized.lower()


def test_sql_safety_child_table_scoping_line_items(db_session, mock_analyst):
    """AST validator must scope invoice_line_items through invoices and documents."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT li.description FROM invoice_line_items li", user=mock_analyst)
    assert "li.invoice_id in" in sanitized.lower()
    assert "invoices" in sanitized
    assert "documents" in sanitized
    assert "uploaded_by = 42" in sanitized


def test_sql_safety_child_table_scoping_payment_obligations(db_session, mock_analyst):
    """AST validator must scope payment_obligations through invoices and documents."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT po.amount_due FROM payment_obligations po", user=mock_analyst)
    assert "po.invoice_id in" in sanitized.lower()
    assert "uploaded_by = 42" in sanitized


def test_sql_safety_child_table_scoping_vendors(db_session, mock_analyst):
    """AST validator must scope vendors through user's accessible invoices."""
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT v.canonical_name FROM vendors v", user=mock_analyst)
    assert "v.id in" in sanitized.lower()
    assert "uploaded_by = 42" in sanitized


def test_sql_safety_joins_handled_safely(db_session, mock_analyst):
    """AST validator must safely scope join queries with aliases."""
    service = TextToSQLService(db_session)
    query = "SELECT i.invoice_number, d.original_filename FROM invoices i JOIN documents d ON i.document_id = d.id"
    sanitized = service.validate_and_sanitize_sql(query, user=mock_analyst)
    assert "d.uploaded_by = 42" in sanitized
    assert "i.document_id in" in sanitized.lower()


def test_sql_safety_users_table_role_gating(db_session, mock_analyst, mock_manager, mock_admin):
    """Only ADMIN may query users table; analyst and manager must be rejected."""
    service = TextToSQLService(db_session)

    with pytest.raises(SQLSecurityException, match="unauthorized for role"):
        service.validate_and_sanitize_sql("SELECT id, username FROM users", user=mock_analyst)

    with pytest.raises(SQLSecurityException, match="unauthorized for role"):
        service.validate_and_sanitize_sql("SELECT id, username FROM users", user=mock_manager)

    # Admin query is permitted for allowlisted columns
    admin_sql = service.validate_and_sanitize_sql("SELECT id, username, email FROM users", user=mock_admin)
    assert "SELECT id, username, email FROM users" in admin_sql

    # Admin querying password_hash is still blocked
    with pytest.raises(SQLSecurityException, match="unauthorized"):
        service.validate_and_sanitize_sql("SELECT id, username, password_hash FROM users", user=mock_admin)


def test_sql_safety_nested_subquery_scope_awareness_manager(db_session, mock_manager):
    """AST validator must attach predicates to the SELECT scope that owns each table, not hoisting to outer WHERE."""
    service = TextToSQLService(db_session)
    query = (
        "SELECT COUNT(*) AS validated_invoice_count "
        "FROM invoices "
        "WHERE document_id IN ("
        "    SELECT id FROM documents WHERE status = 'VALIDATED'"
        ")"
    )
    sanitized = service.validate_and_sanitize_sql(query, user=mock_manager)

    # Invoices scoping belongs to outer query
    assert "invoices.document_id in (select id from documents where is_deleted = false)" in sanitized.lower()

    # Documents scoping belongs to inner query, NOT outer query
    assert "select id from documents where status = 'validated' and documents.is_deleted = false" in sanitized.lower()

    # Must execute against PostgreSQL with zero 'missing FROM-clause entry' error
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1
    assert "validated_invoice_count" in res["rows"][0]


def test_sql_safety_nested_subquery_scope_awareness_analyst(db_session, mock_analyst):
    """Finance analyst user scoping must be attached to the respective SELECT scope without out-of-scope references."""
    service = TextToSQLService(db_session)
    query = (
        "SELECT COUNT(*) AS validated_invoice_count "
        "FROM invoices "
        "WHERE document_id IN ("
        "    SELECT id FROM documents WHERE status = 'VALIDATED'"
        ")"
    )
    sanitized = service.validate_and_sanitize_sql(query, user=mock_analyst)

    # Invoices scoped to analyst in outer query
    assert "invoices.document_id in (select id from documents where uploaded_by = 42 and is_deleted = false)" in sanitized.lower()

    # Documents scoped to analyst in inner query
    assert "select id from documents where status = 'validated' and documents.uploaded_by = 42 and documents.is_deleted = false" in sanitized.lower()

    # Must execute against PostgreSQL with zero error
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1


def test_sql_safety_single_table_document_query_remains_successful(db_session, mock_manager):
    """Single-table document count query (Query 2) remains valid and executable."""
    service = TextToSQLService(db_session)
    query = "SELECT COUNT(*) AS validated_document_count FROM documents WHERE status = 'VALIDATED' AND is_deleted = false"
    sanitized = service.validate_and_sanitize_sql(query, user=mock_manager)

    assert "documents.is_deleted = false" in sanitized.lower()
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1
    assert "validated_document_count" in res["rows"][0]


# ==============================================================================
# RELATIONAL CAPABILITY & PROMPT REGRESSION TESTS
# ==============================================================================

def test_regression_existing_simple_query(db_session, mock_manager):
    """TEST 1: Existing simple query 'How many invoices are there?' works and returns rows."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("How many invoices are there?", user=mock_manager)
    assert res["row_count"] >= 1
    val = list(res["rows"][0].values())[0]
    assert int(val) > 0


def test_regression_acme_vendor_query_partial_matching(db_session, mock_manager):
    """TEST 2: 'How many invoices are from Acme?' produces vendor-name matching for partial name and finds records."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("How many invoices are from the vendor Acme?", user=mock_manager)
    assert res["row_count"] >= 1
    sql_lower = res["sql"].lower()
    assert "ilike" in sql_lower
    assert "acme" in sql_lower
    val = list(res["rows"][0].values())[0]
    assert int(val) > 0


def test_regression_top_5_vendors_query(db_session, mock_manager):
    """TEST 3: 'Who are the top 5 vendors based on the number of invoices sent?' generates valid SQL with JOINs, COUNT, GROUP BY, ORDER BY DESC, LIMIT 5."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("who are the top 5 vendors based on the number of invoices sent ?", user=mock_manager)
    assert res["row_count"] <= 5
    assert res["row_count"] > 0
    sql_lower = res["sql"].lower()
    assert "count" in sql_lower
    assert "group by" in sql_lower
    assert "order by" in sql_lower
    assert "desc" in sql_lower
    if "is_deleted" in sql_lower:
        assert "documents" in sql_lower


def test_regression_validated_document_query(db_session, mock_manager):
    """TEST 4: Existing query 'How many documents are validated?' continues to work."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("how many documents are validated?", user=mock_manager)
    assert res["row_count"] >= 1
    val = list(res["rows"][0].values())[0]
    assert int(val) > 0


def test_regression_invoice_status_query(db_session, mock_manager):
    """TEST 5: 'How many invoices are currently in VALIDATED status?' works with scope-aware authorization."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("How many invoices are currently in VALIDATED status?", user=mock_manager)
    assert res["row_count"] >= 1


def test_regression_vendor_structured_code_query(db_session, mock_manager):
    """TEST 6: Structured vendor identifier queries match on vendor_code without forcing ILIKE."""
    service = TextToSQLService(db_session)
    res = service.generate_and_execute_sql("invoices for vendor code V100", user=mock_manager)
    sql_lower = res["sql"].lower()
    assert "vendor_code" in sql_lower


def test_regression_security_unjoined_documents_alias_still_rejected(db_session, mock_manager):
    """TEST 7: Security regression - query referencing d.is_deleted without joining documents d is still rejected."""
    service = TextToSQLService(db_session)
    bad_sql = "SELECT v.canonical_name, COUNT(i.id) FROM vendors v JOIN invoices i ON v.id = i.vendor_id WHERE d.is_deleted = false GROUP BY v.canonical_name"
    with pytest.raises(SQLSecurityException, match="references table 'd' which is not in the FROM or JOIN clause"):
        service.validate_and_sanitize_sql(bad_sql, user=mock_manager)


def test_regression_database_tool_hint_for_unjoined_documents(db_session, mock_manager, monkeypatch):
    """TEST 8: DatabaseQueryTool returns an actionable hint when unjoined documents alias is rejected."""
    from app.rag.tools.database_tool import DatabaseQueryTool

    def mock_generate_and_execute(*args, **kwargs):
        raise SQLSecurityException("Column references table 'd' which is not in the FROM or JOIN clause.")

    monkeypatch.setattr(TextToSQLService, "generate_and_execute_sql", mock_generate_and_execute)
    tool = DatabaseQueryTool(db=db_session, user=mock_manager)
    obs = tool._run("test query")
    assert "Database Query Rejected by Security Policy" in obs
    assert "Hint: The query references documents/is_deleted but the documents table is not present in FROM/JOIN." in obs



