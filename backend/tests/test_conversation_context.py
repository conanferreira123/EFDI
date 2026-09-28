"""Tests for Level 1 & Level 2 Conversation Context & Memory Improvements.

Validates the 10 required test scenarios:
1. Reported "yes" failure (affirmative confirmation resolves to pending offer, no 5-loop tool failure)
2. Negative confirmation ("no" cleanly terminates without RAG/tool execution)
3. Recent history sliding window (returns newest N in chronological order, ties handled by id)
4. Elliptical reference resolution (identifies item #2 without hallucinations)
5. Ambiguous reference handling ("what about that?" flags ambiguity, requests clarification)
6. Wrong assistant answer handling (unsupported claims not promoted to verified_facts)
7. Pending offer lifecycle (cleared after execution, does not recur)
8. Standalone query bypass (standalone queries pass through without LLM rewrites)
9. Tool-loop prevention (catches duplicate/substantially similar queries, allows distinct tools)
10. Authorization boundaries (unauthorized document cannot be accessed via chat/memory)
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.core.security import create_access_token
from app.database.session import get_db_context
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.context_resolver import ContextResolutionResult, ConversationContextResolver
from app.rag.document_agent import DocumentReActAgent
from app.repositories.chat_history_repository import ChatHistoryRepository
from app.services.chat_service import ChatService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def auth_users_and_doc(db_session):
    u1_suffix = uuid.uuid4().hex[:8]
    u2_suffix = uuid.uuid4().hex[:8]

    user_a = User(
        username=f"user_a_{u1_suffix}",
        email=f"user_a_{u1_suffix}@example.com",
        full_name="User A",
        password_hash="pwa",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    user_b = User(
        username=f"user_b_{u2_suffix}",
        email=f"user_b_{u2_suffix}@example.com",
        full_name="User B",
        password_hash="pwb",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    db_session.flush()

    doc_a = Document(
        original_filename="Invoice A.pdf",
        stored_filename=f"inv_a_{u1_suffix}.pdf",
        file_size_bytes=1024,
        file_hash=f"hash_a_{u1_suffix}",
        mime_type="application/pdf",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=user_a.id,
    )
    doc_b = Document(
        original_filename="Invoice B.pdf",
        stored_filename=f"inv_b_{u2_suffix}.pdf",
        file_size_bytes=2048,
        file_hash=f"hash_b_{u2_suffix}",
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
# TEST 1 — Reported "yes" failure
# =========================================================================
def test_reported_yes_scenario_resolution():
    """TEST 1: Affirmative 'yes' resolves to preceding assistant offer, not bank account."""
    resolver = ConversationContextResolver()

    # Preceding context: user asked about bank account, assistant offered to check payment terms
    history = [
        HumanMessage(content="What is the bank account number?"),
        AIMessage(
            content="The bank account number is not explicitly stated in the document. "
            "Would you like me to check for any other payment-related terms?"
        ),
    ]
    session_state = {
        "pending_offer": {
            "offer_text": "Would you like me to check for any other payment-related terms?",
            "action_query": "Check the document for other payment-related terms such as payment terms, early settlement discounts, due dates, or contractual penalties.",
            "user_confirmation_expected": True,
        }
    }

    result = resolver.resolve(
        query="yes",
        history=history,
        session_state=session_state,
    )

    assert result.was_resolved is True
    assert result.action_type == "confirmation_affirmative"
    # Must NOT be bank account
    assert "bank account" not in result.contextualized_query.lower()
    # Must be payment-related terms
    assert "payment" in result.contextualized_query.lower()
    assert "terms" in result.contextualized_query.lower()


# =========================================================================
# TEST 2 — Negative confirmation
# =========================================================================
def test_negative_confirmation_no_rag(client, auth_users_and_doc, db_session):
    """TEST 2: 'no' does not invoke RAG execution and clears pending offer."""
    user = auth_users_and_doc["user_a"]
    doc = auth_users_and_doc["doc_a"]
    token = auth_users_and_doc["token_a"]

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=user.id, document_id=doc.id)

    # Establish preceding assistant offer in history & state
    repo.add_message(session.id, "user", "What is the penalty?")
    repo.add_message(
        session.id,
        "assistant",
        "There is a 2% monthly late fee. Would you like me to check for payment terms?",
    )
    repo.update_session_state(
        session.id,
        {
            "pending_offer": {
                "offer_text": "Would you like me to check for payment terms?",
                "action_query": "Check the document for payment terms.",
                "user_confirmation_expected": True,
            }
        },
    )
    db_session.commit()

    with patch("app.rag.document_agent.DocumentReActAgent.run") as mock_agent_run, \
         patch("app.rag.tools.rag_tool.DocumentRAGTool._run") as mock_rag_run:
        response = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "no"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "assistant"
        assert "Understood" in data["content"]
        # Agent and tools must NOT have been called
        mock_agent_run.assert_not_called()
        mock_rag_run.assert_not_called()

    # Session state pending offer must now be cleared
    updated_state = repo.get_session_state(session.id)
    assert updated_state.get("pending_offer") is None


# =========================================================================
# TEST 3 — Recent history window
# =========================================================================
def test_recent_history_window_ordering(db_session, auth_users_and_doc):
    """TEST 3: Sliding window retrieves newest N messages in chronological order."""
    user = auth_users_and_doc["user_a"]
    doc = auth_users_and_doc["doc_a"]

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=user.id, document_id=doc.id)

    # Insert 15 messages (with sequentially increasing timestamps)
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(1, 16):
        msg = ChatMessage(
            session_id=session.id,
            role="user" if i % 2 != 0 else "assistant",
            content=f"Message {i:02d}",
            created_at=base_time + timedelta(minutes=i),
        )
        db_session.add(msg)
    db_session.commit()

    # Retrieve with limit=10
    history = repo.get_session_history(session.id, limit=10)

    assert len(history) == 10
    # Must be the 10 MOST RECENT: Message 06 through Message 15
    contents = [m.content for m in history]
    expected_contents = [f"Message {i:02d}" for i in range(6, 16)]
    assert contents == expected_contents

    # Verify chronological ordering: first element is oldest of the 10, last is newest
    assert contents[0] == "Message 06"
    assert contents[-1] == "Message 15"

    # Verify LangChain history format also preserves the recent 10 in chronological order
    lc_history = repo.get_langchain_history(session.id, limit=10)
    assert len(lc_history) == 10
    assert lc_history[0].content == "Message 06"
    assert lc_history[-1].content == "Message 15"


# =========================================================================
# TEST 4 — Elliptical reference
# =========================================================================
def test_elliptical_reference_resolution():
    """TEST 4: 'What about the second item?' resolves item #2 without hallucinating."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="What is the amount and details for line item 2: Cloud Infrastructure Hosting?"
    )

    resolver = ConversationContextResolver(llm=mock_llm)
    history = [
        HumanMessage(content="What are the invoice line items?"),
        AIMessage(
            content=(
                "The invoice lists three line items:\n"
                "1. IT Consulting Services - ₹100,000\n"
                "2. Cloud Infrastructure Hosting - ₹45,000\n"
                "3. Software Licenses - ₹25,000"
            )
        ),
    ]

    result = resolver.resolve(
        query="What about the second item?",
        history=history,
        session_state={},
    )

    assert result.was_resolved is True
    assert result.is_ambiguous is False
    assert "Cloud Infrastructure Hosting" in result.contextualized_query
    # LLM should have been called because "second item" is an elliptical reference
    mock_llm.invoke.assert_called_once()


# =========================================================================
# TEST 5 — Ambiguous reference
# =========================================================================
def test_ambiguous_reference_requests_clarification(client, auth_users_and_doc, db_session):
    """TEST 5: 'What about that?' with no antecedent flags ambiguity and asks clarification."""
    user = auth_users_and_doc["user_a"]
    doc = auth_users_and_doc["doc_a"]
    token = auth_users_and_doc["token_a"]

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=user.id, document_id=doc.id)
    repo.add_message(session.id, "user", "Hello")
    repo.add_message(session.id, "assistant", "Hello! How can I help you today?")
    db_session.commit()

    ambiguous_res = ContextResolutionResult(
        raw_query="What about that?",
        contextualized_query="Could you please clarify what specific detail or section you are referring to?",
        was_resolved=True,
        is_ambiguous=True,
        action_type="clarification",
    )

    with patch.object(ConversationContextResolver, "resolve", return_value=ambiguous_res), \
         patch("app.rag.document_agent.DocumentReActAgent.run") as mock_agent_run:
        response = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What about that?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "assistant"
        # Must request clarification, not call ReAct agent or invent context
        assert "clarify" in data["content"].lower()
        mock_agent_run.assert_not_called()


# =========================================================================
# TEST 6 — Wrong assistant answer
# =========================================================================
def test_unsupported_assistant_claim_not_promoted_to_verified_facts(db_session, auth_users_and_doc):
    """TEST 6: Unverified assistant claims are never automatically added to verified_facts."""
    user = auth_users_and_doc["user_a"]
    doc = auth_users_and_doc["doc_a"]

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=user.id, document_id=doc.id)

    # An assistant message with an unsupported claim and NO tool calls
    repo.add_message(
        session_id=session.id,
        role="assistant",
        content="The invoice total is ₹999,999.00.",
        tool_calls=[],
        citations=[],
    )
    db_session.commit()

    # Verify session state does not contain ₹999,999.00 as a verified fact
    state = repo.get_session_state(session.id)
    verified_facts = state.get("verified_facts", [])
    assert len(verified_facts) == 0

    # Verify LangChain history preserves tool provenance: has_verified_tool_evidence is False
    lc_history = repo.get_langchain_history(session.id)
    assert len(lc_history) == 1
    assert lc_history[0].additional_kwargs.get("has_verified_tool_evidence") is False


# =========================================================================
# TEST 7 — Pending offer lifecycle
# =========================================================================
def test_pending_offer_lifecycle(client, auth_users_and_doc, db_session):
    """TEST 7: Pending offer is cleared upon execution and does not recur on unrelated turn."""
    user = auth_users_and_doc["user_a"]
    doc = auth_users_and_doc["doc_a"]
    token = auth_users_and_doc["token_a"]

    repo = ChatHistoryRepository(db_session)
    session = repo.get_or_create_document_session(user_id=user.id, document_id=doc.id)

    # Turn 1: Setup assistant question expecting confirmation
    repo.add_message(session.id, "user", "What is the document number?")
    repo.add_message(
        session.id,
        "assistant",
        "The document number is INV-102. Would you like me to check payment terms?",
    )
    repo.update_session_state(
        session.id,
        {
            "pending_offer": {
                "offer_text": "Would you like me to check payment terms?",
                "action_query": "Check the document for payment terms.",
                "user_confirmation_expected": True,
            }
        },
    )
    db_session.commit()

    # Turn 2: User says "yes" -> executes payment terms
    from app.rag.agent_result import AgentResult
    mock_agent_result = AgentResult(
        content="Payment terms are Net 30 days from invoice date.",
        tool_calls=[{"tool": "document_rag_tool", "query": "payment terms"}],
        citations=[],
        execution_time_ms=120,
    )

    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_agent_result):
        resp = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "yes"},
        )
        assert resp.status_code == 200

    # Verify pending offer was cleared after execution
    state = repo.get_session_state(session.id)
    assert state.get("pending_offer") is None

    # Turn 3: User asks an unrelated standalone query
    mock_unrelated_result = AgentResult(
        content="The supplier is Acme Corp.",
        tool_calls=[{"tool": "document_rag_tool", "query": "supplier name"}],
        citations=[],
        execution_time_ms=90,
    )

    with patch("app.rag.document_agent.DocumentReActAgent.run", return_value=mock_unrelated_result) as mock_run:
        resp = client.post(
            f"/api/v1/chat/documents/{doc.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Who is the supplier?"},
        )
        assert resp.status_code == 200
        # The query passed to the agent must be supplier query, NOT payment terms
        mock_run.assert_called_once()
        assert "supplier" in mock_run.call_args[1]["query"].lower()
        assert "payment" not in mock_run.call_args[1]["query"].lower()


# =========================================================================
# TEST 8 — Standalone query
# =========================================================================
def test_standalone_query_bypass():
    """TEST 8: Standalone queries bypass LLM resolution without rewriting."""
    mock_llm = MagicMock()
    resolver = ConversationContextResolver(llm=mock_llm)

    history = [
        HumanMessage(content="Hello"),
        AIMessage(content="Hello, I am ready to help."),
    ]

    result = resolver.resolve(
        query="What is the invoice date?",
        history=history,
        session_state={},
    )

    assert result.was_resolved is False
    assert result.contextualized_query == "What is the invoice date?"
    # LLM must NOT be called for standalone queries
    mock_llm.invoke.assert_not_called()


# =========================================================================
# TEST 9 — Tool-loop prevention
# =========================================================================
def test_tool_loop_prevention(db_session):
    """TEST 9: Intercepts repeated equivalent tool calls without blocking distinct calls."""
    agent = DocumentReActAgent(db_session)

    # 1. Exact query match detection
    assert agent._is_redundant_query(
        "document_rag_tool",
        "check bank account payment terms",
        [{"tool": "document_rag_tool", "query": "check bank account payment terms"}],
    ) is True

    # 2. High Jaccard similarity query match detection (>= 0.70)
    assert agent._is_redundant_query(
        "document_rag_tool",
        "payment terms bank account check",
        [{"tool": "document_rag_tool", "query": "check bank account payment terms"}],
    ) is True

    # 3. Legitimate distinct query must NOT be blocked
    assert agent._is_redundant_query(
        "document_rag_tool",
        "total gross invoice amount and tax rate",
        [{"tool": "document_rag_tool", "query": "check bank account payment terms"}],
    ) is False

    # 4. Distinct tool must NOT be blocked
    assert agent._is_redundant_query(
        "financial_calculator_tool",
        "15000 * 0.18",
        [{"tool": "document_rag_tool", "query": "15000 * 0.18"}],
    ) is False


# =========================================================================
# TEST 10 — Authorization
# =========================================================================
def test_authorization_boundary_unauthorized_document(client, auth_users_and_doc):
    """TEST 10: User B cannot access User A's document via chat or conversation state."""
    doc_a = auth_users_and_doc["doc_a"]
    token_b = auth_users_and_doc["token_b"]  # User B's token

    # Attempting to access User A's document with User B's token must fail with 404/403
    response = client.post(
        f"/api/v1/chat/documents/{doc_a.id}/messages",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"message": "What is the invoice amount?"},
    )
    assert response.status_code in (403, 404)

    # Attempting to get history for User A's document with User B's token must fail
    hist_response = client.get(
        f"/api/v1/chat/documents/{doc_a.id}/history",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert hist_response.status_code in (403, 404)
