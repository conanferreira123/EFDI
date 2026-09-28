"""Tests for Chat Error Handling & Robustness.

Validates that:
1. AI service / LLM communication failures raise AIServiceException with clean user-facing error text.
2. Backend returns HTTP 502 Bad Gateway with structured error JSON instead of HTTP 200 with an error text bubble.
3. Failed requests do NOT persist assistant error messages into the database.
4. Failed requests do NOT poison subsequent turns in the conversation.
5. Successful requests continue functioning identically with citations and agent results.
"""
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import AIServiceException
from app.core.security import create_access_token
from app.database.session import get_db_context
from app.main import app
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.agent_result import AgentResult
from app.rag.document_agent import DocumentReActAgent
from app.rag.global_agent import GlobalReActAgent
from app.repositories.chat_history_repository import ChatHistoryRepository


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def auth_user_and_doc(db_session):
    suffix = uuid.uuid4().hex[:8]

    user = User(
        username=f"analyst_err_{suffix}",
        email=f"analyst_err_{suffix}@example.com",
        full_name="Analyst Error Test",
        password_hash="pw",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    doc = Document(
        original_filename="Test_Invoice.pdf",
        stored_filename=f"inv_err_{suffix}.pdf",
        file_size_bytes=1024,
        file_hash=f"hash_{suffix}",
        mime_type="application/pdf",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.commit()

    token, _ = create_access_token(username=user.username, user_id=user.id, role=user.role)

    return {
        "user": user,
        "doc": doc,
        "token": token,
    }


def test_document_agent_raises_ai_service_exception_on_llm_failure(db_session, auth_user_and_doc):
    """TEST 1: DocumentReActAgent raises AIServiceException when LLM invocation fails."""
    doc = auth_user_and_doc["doc"]
    user = auth_user_and_doc["user"]

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.side_effect = RuntimeError("Upstream LLM connection timed out")

    agent = DocumentReActAgent(db_session, llm=mock_llm)

    with pytest.raises(AIServiceException) as exc_info:
        agent.run(
            document_id=doc.id,
            query="What are the payment terms?",
            user=user,
            history=[],
        )

    assert exc_info.value.status_code == 502
    assert "Something went wrong while processing your request" in exc_info.value.message
    # Raw internal exception string must NOT be in user-facing message
    assert "Upstream LLM connection timed out" not in exc_info.value.message


def test_global_agent_raises_ai_service_exception_on_llm_failure(db_session, auth_user_and_doc):
    """TEST 2: GlobalReActAgent raises AIServiceException when LLM invocation fails."""
    user = auth_user_and_doc["user"]

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value.invoke.side_effect = ConnectionError("AI service unavailable")

    agent = GlobalReActAgent(db_session, llm=mock_llm)

    with pytest.raises(AIServiceException) as exc_info:
        agent.run(
            query="List all invoices",
            user=user,
            history=[],
        )

    assert exc_info.value.status_code == 502
    assert "Something went wrong while processing your request" in exc_info.value.message
    assert "ConnectionError" not in exc_info.value.message


def test_document_chat_endpoint_returns_502_and_no_assistant_error_message(client, auth_user_and_doc, db_session):
    """TEST 3: Document Chat endpoint returns HTTP 502 and does NOT store assistant error message."""
    doc = auth_user_and_doc["doc"]
    token = auth_user_and_doc["token"]

    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        response = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the total amount?"},
        )

    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "AI Service Error"
    assert "Something went wrong while processing your request" in data["message"]

    # Verify that NO assistant error message was persisted in the chat history
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    messages = hist_resp.json()
    # There should NOT be any assistant message containing error text
    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 0


def test_global_chat_endpoint_returns_502_and_no_assistant_error_message(client, auth_user_and_doc, db_session):
    """TEST 4: Global Chat endpoint returns HTTP 502 and does NOT store assistant error message."""
    token = auth_user_and_doc["token"]

    with patch("app.rag.global_agent.GlobalReActAgent.run", side_effect=AIServiceException()):
        response = client.post(
            "/api/v1/chat/corpus/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the total quarterly spend?"},
        )

    assert response.status_code == 502
    data = response.json()
    assert data["error"] == "AI Service Error"
    assert "Something went wrong while processing your request" in data["message"]

    # Verify no assistant error message in global history
    hist_resp = client.get(
        "/api/v1/chat/corpus/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    messages = hist_resp.json()
    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 0


def test_failed_request_followed_by_successful_request(client, auth_user_and_doc, db_session):
    """TEST 5: A failed turn does not poison subsequent turns; successful turn works normally."""
    doc = auth_user_and_doc["doc"]
    token = auth_user_and_doc["token"]

    # Turn 1: Fails with AI service error
    with patch("app.rag.document_agent.DocumentReActAgent.run", side_effect=AIServiceException()):
        resp1 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the invoice number?"},
        )
        assert resp1.status_code == 502

    # Turn 2: Followed by normal successful turn
    mock_result = AgentResult(
        content="The invoice number is INV-2026-001.",
        tool_calls=[{"tool": "document_rag_tool", "query": "invoice number"}],
        citations=[],
        execution_time_ms=105,
    )
    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_result):
        resp2 = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What is the invoice number?"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["role"] == "assistant"
        assert data2["content"] == "The invoice number is INV-2026-001."

    # Verify chat history contains only clean turns, not error prose
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    messages = hist_resp.json()
    for m in messages:
        assert "An error occurred while communicating with the AI service" not in m["content"]
        assert "Something went wrong" not in m["content"]
