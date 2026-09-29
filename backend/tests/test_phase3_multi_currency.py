"""Phase 3 Unit and Integration Tests: Structured SQL Results and Multi-Currency Safety.

Tests structured formatting in DatabaseQueryTool and multi-currency querying behavior.
"""
import json
import pytest
from app.rag.tools.database_tool import DatabaseQueryTool
from app.database.session import get_db_context
from app.models.roles import UserRole
from app.models.user import User
from app.services.text_to_sql_service import TextToSQLService
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


def test_compact_observation_scalar_aggregate():
    res = {
        "sql": "SELECT COUNT(*) as count FROM documents WHERE is_deleted = false",
        "row_count": 1,
        "columns": ["count"],
        "rows": [{"count": 42}],
    }
    obs_str = DatabaseQueryTool._format_compact_observation(res)
    obs = json.loads(obs_str)
    assert obs["status"] == "success"
    assert obs["classification"] == "scalar_aggregate"
    assert obs["row_count"] == 1
    assert obs["rows"] == [{"count": 42}]
    assert "candidate_document_ids" not in obs


def test_compact_observation_grouped_breakdown():
    res = {
        "sql": "SELECT currency, SUM(total_amount) FROM invoices GROUP BY currency",
        "row_count": 3,
        "columns": ["currency", "sum"],
        "rows": [
            {"currency": "USD", "sum": 1000.0},
            {"currency": "EUR", "sum": 2000.0},
            {"currency": "GBP", "sum": 1500.0},
        ],
    }
    obs_str = DatabaseQueryTool._format_compact_observation(res)
    obs = json.loads(obs_str)
    assert obs["status"] == "success"
    assert obs["classification"] == "grouped_breakdown"
    assert obs["row_count"] == 3
    assert len(obs["rows"]) == 3


def test_compact_observation_candidate_ids():
    res = {
        "sql": "SELECT document_id, invoice_number FROM invoices WHERE status = 'PENDING_APPROVAL'",
        "row_count": 2,
        "columns": ["document_id", "invoice_number"],
        "rows": [
            {"document_id": "doc-uuid-1", "invoice_number": "INV-001"},
            {"document_id": "doc-uuid-2", "invoice_number": "INV-002"},
        ],
    }
    obs_str = DatabaseQueryTool._format_compact_observation(res)
    obs = json.loads(obs_str)
    assert obs["status"] == "success"
    assert "candidate_document_ids" in obs
    assert obs["candidate_document_ids"] == ["doc-uuid-1", "doc-uuid-2"]


def test_compact_observation_large_enumeration():
    rows = [{"id": f"row-{i}", "val": i} for i in range(50)]
    res = {
        "sql": "SELECT id, val FROM documents",
        "row_count": 50,
        "columns": ["id", "val"],
        "rows": rows,
    }
    obs_str = DatabaseQueryTool._format_compact_observation(res)
    obs = json.loads(obs_str)
    assert obs["status"] == "success"
    assert obs["classification"] == "large_enumeration"
    assert obs["row_count"] == 50
    assert obs["displayed_rows"] == 20
    assert len(obs["rows"]) == 20
    assert "notice" in obs


def test_multi_currency_queries_with_seeded_data(db_session):
    data = seed_evaluation_corpus(db_session)
    service = TextToSQLService(db_session)
    manager = data["users"]["manager"]

    # Q50: Currency breakdown
    q50_sql = (
        "SELECT currency, SUM(grand_total_amount) as total_spend "
        "FROM invoices "
        "WHERE currency IS NOT NULL "
        "GROUP BY currency "
        "ORDER BY currency"
    )
    sanitized_q50 = service.validate_and_sanitize_sql(q50_sql, manager)
    res_q50 = service.execute_safe_query(sanitized_q50)
    assert res_q50["row_count"] >= 2
    currencies = {r["currency"] for r in res_q50["rows"]}
    assert "USD" in currencies
    assert "EUR" in currencies

    # Q48/Q53: USD-scoped calculation
    q48_sql = (
        "SELECT SUM(grand_total_amount) as usd_spend "
        "FROM invoices "
        "WHERE currency = 'USD'"
    )
    sanitized_q48 = service.validate_and_sanitize_sql(q48_sql, manager)
    res_q48 = service.execute_safe_query(sanitized_q48)
    assert res_q48["row_count"] == 1
    assert float(res_q48["rows"][0]["usd_spend"]) > 0

    # Q52: Separate rankings per currency
    q52_sql = (
        "SELECT v.canonical_name, i.currency, SUM(i.grand_total_amount) as spend "
        "FROM invoices i "
        "JOIN vendors v ON i.vendor_id = v.id "
        "WHERE i.currency IS NOT NULL "
        "GROUP BY v.canonical_name, i.currency "
        "ORDER BY i.currency, spend DESC"
    )
    sanitized_q52 = service.validate_and_sanitize_sql(q52_sql, manager)
    res_q52 = service.execute_safe_query(sanitized_q52)
    assert res_q52["row_count"] >= 2
    for r in res_q52["rows"]:
        assert isinstance(r["currency"], str) and len(r["currency"]) == 3
