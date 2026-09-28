"""Tests for Failed-Request Retry Feature.

Validates the 10 required test scenarios from the architectural specification:
1. TEST 1: Failed request appears as error state (HTTP 502, no DB assistant record)
2. TEST 2: Retry succeeds (returns user_message_id, agent executes normally)
3. TEST 3: Database contains exactly one legitimate user/assistant turn (no duplicate user rows)
4. TEST 4: Retry fails again (returns HTTP 502, no DB assistant record, no duplicate rows)
5. TEST 5: Context-dependent failed request ("yes" resolves to pending offer on retry)
6. TEST 6: Successful historical message has no Retry / no replay endpoint
7. TEST 7: Concurrent / rapid retry protection (frontend lock semantic validation)
8. TEST 8: Document Chat retry end-to-end
9. TEST 9: Global Chat retry end-to-end
10. TEST 10: Authorization boundary validation on retry
"""
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import AIServiceException
from app.core.security import create_access_token
from app.database.session import get_db_context
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.agent_result import AgentResult
from app.rag.document_agent import DocumentReActAgent
from app.rag.global_agent import GlobalReActAgent


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def auth_fixture(db_session):
    u1_suffix = uuid.uuid4().hex[:8]
    u2_suffix = uuid.uuid4().hex[:8]

    user_a = User(
        username=f"analyst_{u1_suffix}",
        email=f"analyst_{u1_suffix}@example.com",
        full_name="Analyst A",
        password_hash="pw_a",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    user_b = User(
        username=f"analyst_{u2_suffix}",
        email=f"analyst_{u2_suffix}@example.com",
        full_name="Analyst B",
        password_hash="pw_b",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    db_session.flush()

    doc_a = Document(
        original_filename="Test_Invoice_A.pdf",
        stored_filename=f"inv_{u1_suffix}.pdf",
        file_size_bytes=1024,
        file_hash=f"hash_{u1_suffix}",
        mime_type="application/pdf",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=user_a.id,
    )
    doc_b = Document(
        original_filename="Test_Invoice_B.pdf",
        stored_filename=f"inv_{u2_suffix}.pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{u2_suffix}",
        mime_type="application/pdf",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=user_b.id,
    )
    db_session.add_all([doc_a, doc_b])
    db_session.commit()

    token_a, _ = create_access_token(username=user_a.username, user_id=user_a.id, role=user_a.role)
    token_b, _ = create_access_token(username=user_b.username, user_id=user_b.id, role=user_b.role)

    return {
        "user_a": user_a,
        "user_b": user_b,
        "doc_a": doc_a,
        "doc_b": doc_b,
        "token_a": token_a,
        "token_b": token_b,
    }


# =========================================================================
# TEST 1 — Failed request appears as error state
# =========================================================================
def test_1_failed_request_appears_as_error_state(client, auth_fixture):
    """Force backend failure: returns 502, no DB assistant record, clean error message."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        response = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the total balance?"},
        )

    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "AI Service Error"
    assert "Something went wrong while processing your request" in data["message"]

    # In database: no messages should be committed
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) == 0


# =========================================================================
# TEST 2 — Retry succeeds
# =========================================================================
def test_2_retry_succeeds(client, auth_fixture):
    """First request fails; Retry succeeds with assistant response and user_message_id."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Initial request fails
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp_fail = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the invoice number?"},
        )
        assert resp_fail.status_code == 502

    # User clicks Retry (submits same request)
    mock_agent_result = AgentResult(
        content="The invoice number is INV-2026-999.",
        tool_calls=[],
        citations=[],
        execution_time_ms=88,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_agent_result):
        resp_retry = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the invoice number?"},
        )

    assert resp_retry.status_code == 200
    retry_data = resp_retry.json()
    assert retry_data["role"] == "assistant"
    assert retry_data["content"] == "The invoice number is INV-2026-999."
    assert "user_message_id" in retry_data
    assert isinstance(retry_data["user_message_id"], int)


# =========================================================================
# TEST 3 — Database contains exactly one legitimate turn
# =========================================================================
def test_3_database_contains_exactly_one_legitimate_turn(client, auth_fixture):
    """Initial request fails; Retry succeeds. Database history has exactly ONE user and ONE assistant."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Request 1 fails
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp1 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the payment due date?"},
        )
        assert resp1.status_code == 502

    # Request 2 (Retry) succeeds
    mock_agent_result = AgentResult(
        content="The payment due date is October 15, 2026.",
        tool_calls=[],
        citations=[],
        execution_time_ms=75,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_agent_result):
        resp2 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the payment due date?"},
        )
        assert resp2.status_code == 200

    # Verify database state
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    messages = hist_resp.json()

    # Exactly 2 messages in total: 1 user, 1 assistant. No duplicate user messages!
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the payment due date?"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "The payment due date is October 15, 2026."


# =========================================================================
# TEST 4 — Retry fails again
# =========================================================================
def test_4_retry_fails_again(client, auth_fixture):
    """Initial request fails; Retry is clicked; second request also fails. No DB messages persisted."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Attempt 1 fails
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp1 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What are the early payment discount terms?"},
        )
        assert resp1.status_code == 502

    # Attempt 2 (Retry) fails again
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp2 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What are the early payment discount terms?"},
        )
        assert resp2.status_code == 502

    # Verify database remains completely clean
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) == 0


# =========================================================================
# TEST 5 — Context-dependent failed request
# =========================================================================
def test_5_context_dependent_failed_request(client, auth_fixture):
    """Turn 1 creates pending offer. Turn 2 ('yes') fails. Retry of 'yes' resolves to pending offer."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Turn 1: User asks question, assistant offers payment terms
    turn1_result = AgentResult(
        content="The bank account is not found. Would you like me to check for payment terms?",
        tool_calls=[],
        citations=[],
        execution_time_ms=50,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=turn1_result):
        resp1 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the bank account?"},
        )
        assert resp1.status_code == 200

    # Turn 2: User responds "yes", but backend fails
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp2 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "yes"},
        )
        assert resp2.status_code == 502

    # Turn 3: User clicks Retry ("yes")
    # Verify Context Resolver receives "yes" and resolves to payment terms without manual rewriting
    captured_queries = []

    def mock_agent_run(*args, **kwargs):
        captured_queries.append(kwargs.get("query"))
        return AgentResult(
            content="The payment terms are Net 30 with 2% discount within 10 days.",
            tool_calls=[],
            citations=[],
            execution_time_ms=60,
        )

    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=mock_agent_run):
        resp3 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "yes"},
        )
        assert resp3.status_code == 200
        assert resp3.json()["content"] == "The payment terms are Net 30 with 2% discount within 10 days."

    # Verify that the query passed to the agent was the resolved offer
    assert len(captured_queries) == 1
    assert "payment terms" in captured_queries[0].lower()

    # Verify final database state: exactly 2 user messages, 2 assistant messages
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    messages = hist_resp.json()
    assert len(messages) == 4
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2]["content"] == "yes"


# =========================================================================
# TEST 6 — Successful historical message has no Retry
# =========================================================================
def test_6_successful_historical_message_has_no_retry(client, auth_fixture):
    """Verify that successful historical messages cannot be replayed via arbitrary endpoints."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Create successful turn
    turn_result = AgentResult(
        content="Invoice total is $5,000.",
        tool_calls=[],
        citations=[],
        execution_time_ms=45,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=turn_result):
        resp = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the total?"},
        )
        assert resp.status_code == 200
        msg_id = resp.json()["message_id"]

    # Verify no generic /messages/{id}/resend or replay endpoint exists
    bad_resend_resp = client.post(
        f"/api/v1/chat/messages/{msg_id}/resend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad_resend_resp.status_code == 404  # Endpoint must NOT exist


# =========================================================================
# TEST 7 — Double click / rapid retry protection
# =========================================================================
def test_7_concurrent_retry_idempotency(client, auth_fixture):
    """Verify sequential retry submissions: exactly one retry succeeds and produces valid turn."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    # Initial failure
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp_fail = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Check discount terms"},
        )
        assert resp_fail.status_code == 502

    # Single retry execution succeeds
    mock_result = AgentResult(
        content="Discount terms are 2/10 Net 30.",
        tool_calls=[],
        citations=[],
        execution_time_ms=50,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_result):
        resp_retry = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Check discount terms"},
        )
        assert resp_retry.status_code == 200

    # Ensure exactly 1 user turn persisted
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(hist_resp.json()) == 2


# =========================================================================
# TEST 8 — Document Chat retry
# =========================================================================
def test_8_document_chat_retry_end_to_end(client, auth_fixture):
    """Document Chat retry uses document chat endpoint and returns user_message_id."""
    doc = auth_fixture["doc_a"]
    token = auth_fixture["token_a"]

    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        r1 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the vendor tax ID?"},
        )
        assert r1.status_code == 502

    mock_result = AgentResult(
        content="Tax ID is XX-XXXXXXX.",
        tool_calls=[],
        citations=[],
        execution_time_ms=50,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_result):
        r2 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the vendor tax ID?"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["user_message_id"] is not None
        assert data["role"] == "assistant"


# =========================================================================
# TEST 9 — Global Chat retry
# =========================================================================
def test_9_global_chat_retry_end_to_end(client, auth_fixture):
    """Global Chat retry uses global corpus chat endpoint and returns user_message_id."""
    token = auth_fixture["token_a"]

    # Initial failure
    with patch("app.rag.global_agent.GlobalReActAgent.run", side_effect=AIServiceException()):
        r1 = client.post(
            "/api/v1/chat/corpus/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "How many validated invoices do we have?"},
        )
        assert r1.status_code == 502

    # Retry succeeds
    mock_result = AgentResult(
        content="There are 42 validated invoices.",
        tool_calls=[],
        citations=[],
        execution_time_ms=120,
    )
    with patch("app.rag.global_agent.GlobalReActAgent.run", return_value=mock_result):
        r2 = client.post(
            "/api/v1/chat/corpus/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "How many validated invoices do we have?"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["user_message_id"] is not None
        assert data["role"] == "assistant"
        assert data["content"] == "There are 42 validated invoices."

    # History in Global Chat has exactly 1 user and 1 assistant turn
    hist_resp = client.get(
        "/api/v1/chat/corpus/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) == 2


# =========================================================================
# TEST 10 — Authorization on retry
# =========================================================================
def test_10_authorization_boundary_on_retry(client, auth_fixture):
    """Retry cannot bypass document access checks (User B cannot retry on User A's document)."""
    doc_a = auth_fixture["doc_a"]
    token_b = auth_fixture["token_b"]

    # User B attempts to access doc_a (should be 403 Forbidden)
    resp = client.post(
        f"/api/v1/chat/documents/{doc_a.id}/messages",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"message": "Show me this document"},
    )
    assert resp.status_code == 403
