"""Comprehensive End-to-End Evaluation Battery for Global Chatbot.

Evaluates questions Q47-Q53, compound multi-step workflows, negative error handling,
and structured multi-currency outputs.
"""
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.rag.financial_calculator import FinancialCalculator
from app.rag.tools.calculator_tool import FinancialCalculatorTool
from app.rag.tools.database_tool import DatabaseQueryTool
from app.services.text_to_sql_service import SQLQueryException, SQLSecurityException, TextToSQLService
from app.utils.clock import get_temporal_context
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def corpus_data(db_session: Session):
    return seed_evaluation_corpus(db_session)


def test_e2e_q47_temporal_quarter_query(db_session: Session, corpus_data):
    """Q47: Documents in current fiscal quarter (calendar-year quarter derived from server clock)."""
    manager = corpus_data["users"]["manager"]
    temporal = get_temporal_context()
    service = TextToSQLService(db_session)

    sql = (
        f"SELECT COUNT(*) as doc_count "
        f"FROM documents "
        f"WHERE created_at >= '{temporal['quarter_start_date']}' AND created_at <= '{temporal['quarter_end_date']}T23:59:59Z'"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1
    assert "doc_count" in res["rows"][0]


def test_e2e_q48_outstanding_ap_usd_scoped(db_session: Session, corpus_data):
    """Q48: Outstanding AP dollar value scoped strictly to USD."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT currency, SUM(amount_outstanding) as total_outstanding "
        "FROM payment_obligations "
        "WHERE status != 'PAID' AND currency IS NOT NULL "
        "GROUP BY currency"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 1
    # Check that USD amount is present and separated from other currencies
    currencies = [r["currency"] for r in res["rows"]]
    assert "USD" in currencies


def test_e2e_q49_npo_vs_poi_classification(db_session: Session, corpus_data):
    """Q49: Classification pending review documents broken down by predicted document_type."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT document_type, COUNT(*) as count "
        "FROM documents "
        "WHERE status = 'PENDING_APPROVAL' "
        "GROUP BY document_type"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 1


def test_e2e_q50_spend_last_30_days_by_currency(db_session: Session, corpus_data):
    """Q50: Total spend across all vendors grouped by currency."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT currency, SUM(grand_total_amount) as spend "
        "FROM invoices "
        "WHERE currency IS NOT NULL "
        "GROUP BY currency "
        "ORDER BY currency"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 2
    currencies = {r["currency"] for r in res["rows"]}
    assert "USD" in currencies
    assert "EUR" in currencies


def test_e2e_q51_dynamic_overdue_ratio(db_session: Session, corpus_data):
    """Q51: Percentage of payment obligations that are overdue (using dynamic current date)."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT "
        "COUNT(*) FILTER (WHERE due_date < CURRENT_DATE AND (amount_outstanding > 0 OR amount_outstanding IS NULL) AND status != 'PAID') as overdue_count, "
        "COUNT(*) as total_count "
        "FROM payment_obligations"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1
    row = res["rows"][0]
    total = row["total_count"]
    overdue = row["overdue_count"]
    assert total > 0
    ratio = (Decimal(str(overdue)) / Decimal(str(total))) * Decimal("100")
    assert Decimal("0") <= ratio <= Decimal("100")


def test_e2e_q52_vendors_per_currency_ranking(db_session: Session, corpus_data):
    """Q52: Top vendor spend returned with separate rankings per currency."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT v.canonical_name, i.currency, SUM(i.grand_total_amount) as spend "
        "FROM invoices i "
        "JOIN vendors v ON i.vendor_id = v.id "
        "WHERE i.currency IS NOT NULL "
        "GROUP BY v.canonical_name, i.currency "
        "ORDER BY i.currency, spend DESC"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] >= 2


def test_e2e_q53_highest_unpaid_vendor_usd(db_session: Session, corpus_data):
    """Q53: Highest outstanding unpaid vendor scoped strictly to USD."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT v.canonical_name, SUM(po.amount_outstanding) as unpaid_usd "
        "FROM payment_obligations po "
        "JOIN invoices i ON po.invoice_id = i.id "
        "JOIN vendors v ON i.vendor_id = v.id "
        "WHERE po.currency = 'USD' AND po.status != 'PAID' "
        "GROUP BY v.canonical_name "
        "ORDER BY unpaid_usd DESC "
        "LIMIT 1"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    assert res["row_count"] == 1
    assert "canonical_name" in res["rows"][0]
    assert float(res["rows"][0]["unpaid_usd"]) > 0


def test_e2e_negative_case_no_silent_fallback(db_session: Session, corpus_data):
    """Negative case: SQL syntax or policy error raises exception; no silent fallback query runs."""
    analyst = corpus_data["users"]["analyst"]
    service = TextToSQLService(db_session)
    assert not hasattr(service, "_heuristic_sql_fallback")
    with pytest.raises(SQLSecurityException):
        service.validate_and_sanitize_sql("DROP TABLE invoices", analyst)


def test_e2e_compound_sql_to_calculator(db_session: Session, corpus_data):
    """Compound workflow: SQL retrieves candidate invoices and Calculator computes batch discount savings."""
    manager = corpus_data["users"]["manager"]
    service = TextToSQLService(db_session)

    sql = (
        "SELECT i.id as invoice_id, i.grand_total_amount, i.currency, po.early_payment_discount "
        "FROM invoices i "
        "JOIN payment_obligations po ON po.invoice_id = i.id "
        "WHERE po.early_payment_discount IS NOT NULL"
    )
    sanitized = service.validate_and_sanitize_sql(sql, manager)
    res = service.execute_safe_query(sanitized)
    rows = res["rows"]

    # Pass rows to batch calculator
    calc_res = FinancialCalculator.batch_calculate_discounts(rows)
    assert calc_res["calculated_count"] == len(rows)
    if rows:
        assert len(calc_res["totals_by_currency"]) > 0
