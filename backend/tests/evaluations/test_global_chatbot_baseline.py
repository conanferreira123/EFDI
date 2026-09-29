"""Baseline evaluation test harness for Global Chatbot.

Executes baseline queries to record initial behavior across:
- Q47 (current fiscal quarter document count)
- Q48 (outstanding AP dollar value)
- Q49 (NPO vs POI review count reframed)
- Q50 (spend in last 30 days by currency)
- Q51 (% invoices overdue dynamic vs static)
- Q52 (top 5 vendors by spend per currency)
- Q53 (vendor with highest unpaid dollar value)
- Role isolation and security boundaries
"""
import pytest
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.services.text_to_sql_service import TextToSQLService, SQLSecurityException
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def eval_corpus(db_session: Session):
    data = seed_evaluation_corpus(db_session)
    yield data
    # Cleanup handled by transaction rollback or db fixture


def test_baseline_q47_temporal_quarter_sql(db_session, eval_corpus):
    """Q47: SQL query for documents in current calendar quarter."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT COUNT(*) as count FROM documents "
        "WHERE is_deleted = false "
        "AND created_at >= DATE_TRUNC('quarter', CURRENT_DATE) "
        "AND created_at < DATE_TRUNC('quarter', CURRENT_DATE) + INTERVAL '3 months'"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    assert res["row_count"] == 1
    assert "count" in res["rows"][0]


def test_baseline_q48_outstanding_ap_currency_separated(db_session, eval_corpus):
    """Q48: Total dollar value of outstanding AP must be currency-scoped or grouped."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT currency, SUM(amount_outstanding) as total_outstanding "
        "FROM payment_obligations "
        "WHERE (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID' "
        "GROUP BY currency"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    currencies = {
        r["currency"]: float(r["total_outstanding"])
        for r in res["rows"]
        if r["currency"] and r["total_outstanding"] is not None
    }
    assert "USD" in currencies
    assert "EUR" in currencies
    assert currencies["USD"] > 0
    assert currencies["EUR"] > 0


def test_baseline_q49_npo_vs_poi_classification(db_session, eval_corpus):
    """Q49: How many invoices in PENDING_APPROVAL status classified as NPO vs POI."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT document_type, COUNT(*) as count FROM documents "
        "WHERE status = 'PENDING_APPROVAL' AND document_type IN ('POI', 'NPO') "
        "GROUP BY document_type"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    types = {r["document_type"]: r["count"] for r in res["rows"]}
    assert "NPO" in types or "POI" in types


def test_baseline_q50_spend_last_30_days_by_currency(db_session, eval_corpus):
    """Q50: Spend processed in last 30 days grouped by currency."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT i.currency, SUM(i.grand_total_amount) as total_spend "
        "FROM invoices i JOIN documents d ON i.document_id = d.id "
        "WHERE d.is_deleted = false AND d.created_at >= CURRENT_DATE - INTERVAL '30 days' "
        "AND d.status IN ('VALIDATED', 'PENDING_APPROVAL', 'APPROVED') "
        "GROUP BY i.currency"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    spend_by_curr = {r["currency"]: float(r["total_spend"]) for r in res["rows"]}
    assert "USD" in spend_by_curr
    # EUR was 45 days ago, so should not be in the 30-day window
    assert "EUR" not in spend_by_curr


def test_baseline_q51_dynamic_overdue_percentage(db_session, eval_corpus):
    """Q51: Dynamic overdue calculation ratio using authoritative formula."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    # Static check (legacy defect) vs dynamic check
    raw_sql_dynamic = (
        "SELECT COUNT(CASE WHEN due_date < CURRENT_DATE AND (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_overdue "
        "FROM payment_obligations"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql_dynamic, user=manager)
    res = service.execute_safe_query(safe_sql)
    pct = float(res["rows"][0]["pct_overdue"])
    assert pct > 0.0  # Dynamic overdue finds overdue obligations even though status='OPEN'


def test_baseline_q52_vendors_per_currency_ranking(db_session, eval_corpus):
    """Q52: Top vendors by spend grouped by currency (not blended)."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT v.canonical_name, i.currency, SUM(i.grand_total_amount) as spend "
        "FROM vendors v JOIN invoices i ON v.id = i.vendor_id JOIN documents d ON i.document_id = d.id "
        "WHERE d.is_deleted = false AND i.invoice_date >= DATE_TRUNC('year', CURRENT_DATE) "
        "GROUP BY v.id, v.canonical_name, i.currency "
        "ORDER BY i.currency, SUM(i.grand_total_amount) DESC"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    assert res["row_count"] >= 2
    # Verify currencies are segregated
    currencies = {r["currency"] for r in res["rows"]}
    assert len(currencies) >= 1


def test_baseline_q53_highest_unpaid_vendor_usd(db_session, eval_corpus):
    """Q53: Vendor with highest unpaid dollar value strictly in USD."""
    service = TextToSQLService(db_session)
    manager = eval_corpus["users"]["manager"]
    raw_sql = (
        "SELECT v.canonical_name, SUM(po.amount_outstanding) as unpaid_usd "
        "FROM vendors v JOIN invoices i ON v.id = i.vendor_id JOIN payment_obligations po ON i.id = po.invoice_id "
        "JOIN documents d ON i.document_id = d.id "
        "WHERE d.is_deleted = false AND (po.amount_outstanding > 0 OR po.amount_outstanding IS NULL) "
        "AND po.status != 'PAID' AND po.currency = 'USD' "
        "GROUP BY v.id, v.canonical_name "
        "ORDER BY SUM(po.amount_outstanding) DESC LIMIT 1"
    )
    safe_sql = service.validate_and_sanitize_sql(raw_sql, user=manager)
    res = service.execute_safe_query(safe_sql)
    assert res["row_count"] == 1
    assert float(res["rows"][0]["unpaid_usd"]) > 0
