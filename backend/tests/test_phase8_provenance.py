"""Phase 8 Unit Tests: Unified Evidence and Provenance.

Tests extraction and serialization of relational and calculation provenance in tools and schemas.
"""
import pytest
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.rag.agent_result import AgentResult
from app.rag.tools.calculator_tool import FinancialCalculatorTool
from app.rag.tools.database_tool import DatabaseQueryTool
from app.schemas.chat import GlobalChatMessageResponse
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


from unittest.mock import patch


def test_database_tool_captures_relational_provenance(db_session: Session):
    data = seed_evaluation_corpus(db_session)
    manager = data["users"]["manager"]
    tool = DatabaseQueryTool(db=db_session, user=manager)

    with patch("app.rag.tools.database_tool.TextToSQLService") as MockService:
        instance = MockService.return_value
        instance.generate_and_execute_sql.return_value = {
            "sql": "SELECT id, document_id, invoice_number, grand_total_amount FROM invoices WHERE currency = 'USD'",
            "row_count": 2,
            "rows": [
                {"id": 1, "document_id": 10, "invoice_number": "INV-001", "grand_total_amount": "5000.00", "currency": "USD"},
                {"id": 2, "document_id": 11, "invoice_number": "INV-002", "grand_total_amount": "8000.00", "currency": "USD"},
            ],
        }
        obs = tool._run("Show all USD invoices")
        assert len(tool.relational_provenance) == 2
        first_rec = tool.relational_provenance[0]
        assert first_rec["table"] == "invoices"
        assert first_rec["invoice_number"] == "INV-001"
        assert first_rec["document_id"] == 10


def test_calculator_tool_captures_calculation_provenance():
    tool = FinancialCalculatorTool()

    # 1. Discount calculation
    tool._run(action="calculate_discount", gross_amount="1000", discount_percentage="2%")
    assert len(tool.calculation_provenance) >= 1
    assert tool.calculation_provenance[0]["operation"] == "early_discount"
    assert "1000" in tool.calculation_provenance[0]["formula"]

    # 2. Expression
    tool._run(action="calculate_expression", expression="2500 * 0.98")
    assert any(c["operation"] == "expression" for c in tool.calculation_provenance)


def test_global_chat_message_response_serialization():
    resp = GlobalChatMessageResponse(
        session_id=1,
        message_id=2,
        user_message_id=1,
        role="assistant",
        content="Test content",
        tool_calls=[],
        citations=[],
        relational_provenance=[{"table": "invoices", "invoice_number": "INV-001"}],
        calculation_provenance=[{"operation": "expression", "formula": "10 + 20 = 30"}],
        created_at="2026-09-29T12:00:00Z",
    )
    dumped = resp.model_dump()
    assert dumped["relational_provenance"] == [{"table": "invoices", "invoice_number": "INV-001"}]
    assert dumped["calculation_provenance"] == [{"operation": "expression", "formula": "10 + 20 = 30"}]
