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
