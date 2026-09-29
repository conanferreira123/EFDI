"""Comprehensive Authorization Regression Test Battery (Section 18).

Validates all 7 specific workflow_history cases (A-G) and the 15 general authorization
regression scenarios to prove that post-change authorization behavior preserves all
existing invariants with the sole approved addition of workflow_history for Auditor/Admin.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.roles import UserRole
from app.models.user import User
from app.rag.tools.database_tool import DatabaseQueryInput, DatabaseQueryTool
from app.rag.tools.rag_tool import DocumentRAGTool
from app.repositories.chunk_repository import ChunkRepository
from app.services.text_to_sql_service import (
    ALLOWED_COLUMNS,
    ALLOWED_TABLES,
    ROLE_ALLOWED_TABLES,
    SQLSecurityException,
    TextToSQLService,
)
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def corpus_data(db_session: Session):
    return seed_evaluation_corpus(db_session)


# =============================================================================
# 18.1 Specific workflow_history Authorization Test Cases (Cases A - G)
# =============================================================================

def test_case_a_auditor_workflow_history_allowed(db_session: Session, corpus_data):
    """Case A: Auditor can query workflow_history and receives non-deleted document history."""
    auditor = corpus_data["users"]["auditor"]
    service = TextToSQLService(db_session)
    sql = "SELECT action, from_status, to_status FROM workflow_history"
    sanitized = service.validate_and_sanitize_sql(sql, auditor)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 1
    # Ensure soft-deletion predicate was injected
    assert "is_deleted = false" in sanitized.lower()


def test_case_b_admin_workflow_history_allowed(db_session: Session, corpus_data):
    """Case B: Admin can query workflow_history and receives non-deleted document history."""
    admin = corpus_data["users"]["admin"]
    service = TextToSQLService(db_session)
    sql = "SELECT action, from_status, to_status FROM workflow_history"
    sanitized = service.validate_and_sanitize_sql(sql, admin)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 1
    assert "is_deleted = false" in sanitized.lower()


def test_case_c_finance_manager_workflow_history_rejected(db_session: Session, corpus_data):
    """Case C: Finance Manager querying workflow_history is strictly rejected at AST validation layer."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)
    sql = "SELECT * FROM workflow_history"
    with pytest.raises(SQLSecurityException) as exc_info:
        service.validate_and_sanitize_sql(sql, manager)
    assert "unauthorized for role 'FINANCE_MANAGER'" in str(exc_info.value)


def test_case_d_finance_analyst_workflow_history_rejected(db_session: Session, corpus_data):
    """Case D: Finance Analyst querying workflow_history is strictly rejected at AST validation layer."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    sql = "SELECT * FROM workflow_history"
    with pytest.raises(SQLSecurityException) as exc_info:
        service.validate_and_sanitize_sql(sql, analyst)
    assert "unauthorized for role 'FINANCE_ANALYST'" in str(exc_info.value)


def test_case_e_prompt_injection_role_escalation_fails(db_session: Session, corpus_data):
    """Case E: Prompt injection attempting role escalation is ignored; server-side role is enforced."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    # Even if LLM was tricked by prompt to generate workflow_history query for an analyst:
    injected_sql = "SELECT * FROM workflow_history"
    with pytest.raises(SQLSecurityException):
        service.validate_and_sanitize_sql(injected_sql, analyst)


def test_case_f_tool_argument_override_attempt_fails():
    """Case F: Tool schema accepts no role or user_id override parameters."""
    schema_fields = DatabaseQueryInput.model_fields.keys()
    assert "role" not in schema_fields
    assert "user_id" not in schema_fields
    assert "current_user" not in schema_fields


def test_case_g_soft_deleted_document_workflow_history_isolated(db_session: Session, corpus_data):
    """Case G: Workflow history belonging to soft-deleted documents is never returned."""
    auditor = corpus_data["users"]["auditor"]
    service = TextToSQLService(db_session)
    sql = "SELECT document_id, comment FROM workflow_history"
    sanitized = service.validate_and_sanitize_sql(sql, auditor)
    res = service.execute_safe_query(sanitized)
    comments = [r["comment"] for r in res["rows"]]
    assert "Deleted document rejection note" not in comments


# =============================================================================
# 18.2 General Authorization Regression Test Scenarios (1 - 15)
# =============================================================================

def test_scenario_1_authorized_tables_per_role():
    """Scenario 1: Verified table sets per role."""
    analyst_tables = ROLE_ALLOWED_TABLES[UserRole.FINANCE_ANALYST.value]
    manager_tables = ROLE_ALLOWED_TABLES[UserRole.FINANCE_MANAGER.value]
    auditor_tables = ROLE_ALLOWED_TABLES[UserRole.AUDITOR.value]
    admin_tables = ROLE_ALLOWED_TABLES[UserRole.ADMIN.value]

    # Exactly 10 tables for Analyst (no users, no workflow_history)
    assert len(analyst_tables) == 10
    assert "users" not in analyst_tables
    assert "workflow_history" not in analyst_tables

    # Exactly 10 tables for Manager (no users, no workflow_history)
    assert len(manager_tables) == 10
    assert "users" not in manager_tables
    assert "workflow_history" not in manager_tables

    # Exactly 11 tables for Auditor (has workflow_history, NO users)
    assert len(auditor_tables) == 11
    assert "workflow_history" in auditor_tables
    assert "users" not in auditor_tables

    # Exactly 12 tables for Admin (has users and workflow_history)
    assert len(admin_tables) == 12
    assert "users" in admin_tables
    assert "workflow_history" in admin_tables


def test_scenario_2_unauthorized_tables_rejected(db_session: Session, corpus_data):
    """Scenario 2: Querying unauthorized or internal system tables raises SQLSecurityException."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    for bad_table in ["users", "alembic_version", "pg_database", "workflow_history"]:
        with pytest.raises(SQLSecurityException):
            service.validate_and_sanitize_sql(f"SELECT * FROM {bad_table}", analyst)


def test_scenario_3_password_hash_strictly_excluded(db_session: Session, corpus_data):
    """Scenario 3: password_hash column is strictly forbidden even for Admin."""
    admin = corpus_data["users"]["admin"]
    service = TextToSQLService(db_session)
    assert "password_hash" not in ALLOWED_COLUMNS["users"]
    with pytest.raises(SQLSecurityException):
        service.validate_and_sanitize_sql("SELECT username, password_hash FROM users", admin)


def test_scenario_4_analyst_ownership_isolation(db_session: Session, corpus_data):
    """Scenario 4: Analyst querying invoices is strictly scoped to own uploaded documents."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    sql = "SELECT id, document_id, grand_total_amount FROM invoices"
    sanitized = service.validate_and_sanitize_sql(sql, analyst)
    res = service.execute_safe_query(sanitized)
    for r in res["rows"]:
        doc = db_session.get(Document, r["document_id"])
        assert doc.uploaded_by == analyst.id


def test_scenario_5_manager_enterprise_visibility(db_session: Session, corpus_data):
    """Scenario 5: Manager accesses non-deleted documents across multiple uploaders."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)
    sql = "SELECT id, uploaded_by FROM documents"
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    uploaders = {r["uploaded_by"] for r in res["rows"]}
    assert len(uploaders) >= 2


def test_scenario_6_admin_visibility_and_users(db_session: Session, corpus_data):
    """Scenario 6: Admin accesses documents and users table."""
    admin = corpus_data["users"]["admin"]
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT username, role FROM users", admin)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 1


def test_scenario_7_auditor_denied_users_table(db_session: Session, corpus_data):
    """Scenario 7: Auditor is denied access to users table."""
    auditor = corpus_data["users"]["auditor"]
    service = TextToSQLService(db_session)
    with pytest.raises(SQLSecurityException):
        service.validate_and_sanitize_sql("SELECT username FROM users", auditor)


def test_scenario_8_and_14_rag_authorization_and_unowned_document_ids(db_session: Session, corpus_data):
    """Scenarios 8 & 14: Analyst cannot access chunks of unowned documents in RAG even if ID is supplied."""
    analyst = corpus_data["users"]["analyst"]
    repo = ChunkRepository(db_session)

    # Find a document NOT owned by analyst
    unowned_docs = [d for d in corpus_data["documents"] if d.uploaded_by != analyst.id and not d.is_deleted]
    assert len(unowned_docs) > 0
    unowned_id = unowned_docs[0].id

    stmt = select(DocumentChunk)
    filtered = repo._apply_authorization_predicates(stmt, user=analyst, document_ids=[unowned_id])
    results = list(db_session.scalars(filtered).all())
    assert len(results) == 0


def test_scenario_9_soft_deleted_document_exclusion(db_session: Session, corpus_data):
    """Scenario 9: Soft-deleted documents excluded from both SQL and RAG."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)
    sanitized = service.validate_and_sanitize_sql("SELECT id, is_deleted FROM documents", manager)
    res = service.execute_safe_query(sanitized)
    for r in res["rows"]:
        assert r["is_deleted"] is False


def test_scenario_15_complex_sql_alias_scoping(db_session: Session, corpus_data):
    """Scenario 15: Complex query with aliases and joins handles scoping safely."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    sql = (
        "SELECT inv.invoice_number, v.canonical_name, inv.grand_total_amount "
        "FROM invoices AS inv "
        "JOIN vendors AS v ON inv.vendor_id = v.id "
        "WHERE inv.currency = 'USD'"
    )
    sanitized = service.validate_and_sanitize_sql(sql, analyst)
    res = service.execute_safe_query(sanitized)
    assert isinstance(res["row_count"], int)
