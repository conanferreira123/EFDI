"""Unit tests for Phase 2: Database Reliability, Safe SQL, and workflow_history authorization."""
import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.models.roles import UserRole
from app.models.user import User
from app.services.text_to_sql_service import (
    SQLQueryException,
    SQLSecurityException,
    TextToSQLService,
)
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def eval_corpus(db_session: Session):
    data = seed_evaluation_corpus(db_session)
    yield data


def test_heuristic_fallback_removed(db_session, eval_corpus):
    """Verify _heuristic_sql_fallback attribute does not exist and LLM failure raises SQLQueryException."""
    service = TextToSQLService(db_session)
    assert not hasattr(service, "_heuristic_sql_fallback")

    # Mock LLM failure
    service.llm_client._call_mistral_api = MagicMock(side_effect=RuntimeError("Mistral API down"))
    manager = eval_corpus["users"]["manager"]

    with pytest.raises(SQLQueryException, match="Failed to generate SQL from user query"):
        service.generate_and_execute_sql("how many documents are validated?", user=manager)


def test_workflow_history_auditor_allowed(db_session, eval_corpus):
    """AUDITOR is allowed to query workflow_history for non-deleted documents."""
    service = TextToSQLService(db_session)
    auditor = eval_corpus["users"]["auditor"]

    sql = "SELECT id, action, from_status, to_status, comment FROM workflow_history"
    safe_sql = service.validate_and_sanitize_sql(sql, user=auditor)
    assert "workflow_history" in safe_sql
    assert "is_deleted = false" in safe_sql.lower()

    res = service.execute_safe_query(safe_sql)
    assert "rows" in res


def test_workflow_history_admin_allowed(db_session, eval_corpus):
    """ADMIN is allowed to query workflow_history for non-deleted documents."""
    service = TextToSQLService(db_session)
    admin = eval_corpus["users"]["admin"]

    sql = "SELECT id, action, from_status, to_status, comment FROM workflow_history"
    safe_sql = service.validate_and_sanitize_sql(sql, user=admin)
    assert "workflow_history" in safe_sql
    assert "is_deleted = false" in safe_sql.lower()

    res = service.execute_safe_query(safe_sql)
    assert "rows" in res


def test_workflow_history_finance_manager_denied(db_session, eval_corpus):
    """FINANCE_MANAGER is strictly rejected from querying workflow_history."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]

    sql = "SELECT id, action, from_status, to_status FROM workflow_history"
    with pytest.raises(SQLSecurityException, match="Access to table 'workflow_history' is unauthorized for role 'FINANCE_MANAGER'"):
        service.validate_and_sanitize_sql(sql, user=manager)


def test_workflow_history_finance_analyst_denied(db_session, eval_corpus):
    """FINANCE_ANALYST is strictly rejected from querying workflow_history."""
    service = TextToSQLService(db_session)
    analyst = eval_corpus["users"]["analyst"]

    sql = "SELECT id, action, from_status, to_status FROM workflow_history"
    with pytest.raises(SQLSecurityException, match="Access to table 'workflow_history' is unauthorized for role 'FINANCE_ANALYST'"):
        service.validate_and_sanitize_sql(sql, user=analyst)


def test_projected_column_alias_in_order_by_allowed(db_session, eval_corpus):
    """Projected aliases in SELECT (e.g. SUM(...) as spend ... ORDER BY spend DESC) must not fail column validation."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]

    sql = (
        "SELECT v.canonical_name, SUM(i.grand_total_amount) as spend "
        "FROM vendors v JOIN invoices i ON v.id = i.vendor_id "
        "GROUP BY v.id, v.canonical_name "
        "ORDER BY spend DESC"
    )
    safe_sql = service.validate_and_sanitize_sql(sql, user=manager)
    assert "ORDER BY spend DESC" in safe_sql


def test_soft_deleted_isolation_on_workflow_history(db_session, eval_corpus):
    """Auditor querying workflow_history never sees transitions for soft-deleted documents."""
    service = TextToSQLService(db_session)
    auditor = eval_corpus["users"]["auditor"]

    sql = "SELECT id, action, comment FROM workflow_history"
    safe_sql = service.validate_and_sanitize_sql(sql, user=auditor)
    res = service.execute_safe_query(safe_sql)

    comments = [r.get("comment") for r in res["rows"] if r.get("comment")]
    assert "Deleted document rejection note" not in comments
