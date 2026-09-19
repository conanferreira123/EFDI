"""Tests for Milestone 4: Global Multi-Tool Agent, Financial Calculator, and Compound Orchestration.
"""
from decimal import Decimal
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.database.session import get_db_context
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.financial_calculator import FinancialCalculator
from app.rag.agent_orchestrator import AgentOrchestrator
from app.rag.embeddings import get_embedding_service


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def global_test_setup(db_session):
    u_suffix = uuid.uuid4().hex[:8]
    manager = User(
        username=f"mgr_agent_{u_suffix}",
        email=f"mgr_agent_{u_suffix}@example.com",
        full_name="Agent Manager",
        password_hash="pwm",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    db_session.add(manager)
    db_session.flush()

    doc = Document(
        original_filename="acme_industrial_invoice_9021.pdf",
        stored_filename=f"acme_{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{uuid.uuid4().hex[:12]}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=manager.id,
    )
    db_session.add(doc)
    db_session.flush()

    c_text = (
        "TAX INVOICE INV-9021 Vendor: ACME Supplies Ltd. Gross Total: 1320.00. "
        "Payment Terms: 2% early settlement discount if paid within 10 days; Net 30 days."
    )
    embed_service = get_embedding_service()
    vec = embed_service.generate_embeddings([c_text])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="TERMS",
        content=c_text,
        embedding=vec,
        metadata_json={"chunk_index": 0, "section": "TERMS", "page_number": 1, "has_table": False},
    )
    db_session.add(chunk)
    db_session.commit()

    analyst = User(
        username=f"analyst_agent_{u_suffix}",
        email=f"analyst_agent_{u_suffix}@example.com",
        full_name="Agent Analyst",
        password_hash="pwa",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(analyst)
    db_session.commit()


    token_manager, _ = create_access_token(username=manager.username, user_id=manager.id, role=manager.role)
    token_analyst, _ = create_access_token(username=analyst.username, user_id=analyst.id, role=analyst.role)
    return {
        "manager": manager,
        "analyst": analyst,
        "doc": doc,
        "token": token_manager,
        "token_analyst": token_analyst,
    }



def test_financial_calculator_deterministic_decimal():
    """Verify financial calculator computes exact Decimal arithmetic without rounding drift."""
    calc = FinancialCalculator

    # 1. Exact arithmetic
    val = calc.evaluate_expression("1320.00 - 26.40")
    assert val == Decimal("1293.60")

    # 2. Early payment discount
    res = calc.calculate_discount(
        gross_amount="1320.00",
        discount_percentage="2%",
        days_offset=10,
        invoice_date="2024-03-15",
    )
    assert res["original_gross"] == "1320.00"
    assert res["discount_percentage"] == "2%"
    assert res["discount_amount"] == "26.40"
    assert res["discounted_payable_total"] == "1293.60"
    assert res["deadline_date"] == "2024-03-25"


def test_global_agent_sql_intent(db_session, global_test_setup):
    """Verify orchestrator routes aggregations to the Database Query Tool."""
    manager = global_test_setup["manager"]
    orchestrator = AgentOrchestrator(db_session)

    res = orchestrator.process_global_query(
        query="How many invoices are currently in VALIDATED status?",
        user=manager,
    )
    assert res["role"] == "assistant"
    tool_names = [tc.get("tool") for tc in res["tool_calls"]]
    assert "database_query_tool" in tool_names


def test_global_agent_calculator_intent(db_session, global_test_setup):
    """Verify orchestrator routes discount math to the Financial Calculator Tool."""
    manager = global_test_setup["manager"]
    orchestrator = AgentOrchestrator(db_session)

    res = orchestrator.process_global_query(
        query="Calculate a 2% discount on $1320 within 10 days",
        user=manager,
    )
    tool_names = [tc.get("tool") for tc in res["tool_calls"]]
    assert "financial_calculator_tool" in tool_names
    assert "26.40" in res["content"] or "1293.60" in res["content"]


def test_global_agent_compound_orchestration(db_session, global_test_setup):
    """Verify compound queries coordinate both SQL Tool and Document RAG Tool."""
    manager = global_test_setup["manager"]
    orchestrator = AgentOrchestrator(db_session)

    res = orchestrator.process_global_query(
        query="List all invoices in status VALIDATED and check what payment discount terms apply",
        user=manager,
    )
    tool_names = [tc.get("tool") for tc in res["tool_calls"]]
    # Must use both tools
    assert "database_query_tool" in tool_names
    assert "document_rag_tool" in tool_names
    assert len(res["citations"]) > 0


def test_global_chat_api_endpoints(client, global_test_setup):
    """Verify /api/v1/chat/corpus endpoints: message, history, and clear."""
    token = global_test_setup["token"]

    # 1. Send global message
    post_res = client.post(
        "/api/v1/chat/corpus/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "What Incoterms or payment terms are documented in our portfolio?"},
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["role"] == "assistant"
    assert len(data["content"]) > 0
    assert "tool_calls" in data

    # 2. Get history
    hist_res = client.get(
        "/api/v1/chat/corpus/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_res.status_code == 200
    history = hist_res.json()
    assert len(history) >= 2

    # 3. Clear history
    del_res = client.delete(
        "/api/v1/chat/corpus/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cleared"


def test_global_chat_analyst_policy_scoped(client, global_test_setup, monkeypatch):
    """Option A (Default): FINANCE_ANALYST can use Global Chat with queries strictly scoped to their uploads."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "scoped")

    token_analyst = global_test_setup["token_analyst"]
    post_res = client.post(
        "/api/v1/chat/corpus/messages",
        headers={"Authorization": f"Bearer {token_analyst}"},
        json={"message": "How many invoices are currently in VALIDATED status?"},
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["role"] == "assistant"


def test_global_chat_analyst_policy_forbidden(client, global_test_setup, monkeypatch):
    """Option B: When policy is 'forbidden', FINANCE_ANALYST is denied access to Global Chat with HTTP 403."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "forbidden")

    token_analyst = global_test_setup["token_analyst"]
    post_res = client.post(
        "/api/v1/chat/corpus/messages",
        headers={"Authorization": f"Bearer {token_analyst}"},
        json={"message": "How many invoices are currently in VALIDATED status?"},
    )
    assert post_res.status_code == 403

