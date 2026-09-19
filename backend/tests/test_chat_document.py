"""Tests for Milestone 3: Level 1 Document-Level Conversational Assistant.
"""
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
from app.rag.embeddings import get_embedding_service


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def chat_test_setup(db_session):
    u1_suffix = uuid.uuid4().hex[:8]
    u2_suffix = uuid.uuid4().hex[:8]
    m_suffix = uuid.uuid4().hex[:8]

    analyst_1 = User(
        username=f"analyst_chat_1_{u1_suffix}",
        email=f"analyst_chat_1_{u1_suffix}@example.com",
        full_name="Analyst Chat One",
        password_hash="pw1",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    analyst_2 = User(
        username=f"analyst_chat_2_{u2_suffix}",
        email=f"analyst_chat_2_{u2_suffix}@example.com",
        full_name="Analyst Chat Two",
        password_hash="pw2",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    manager = User(
        username=f"manager_chat_{m_suffix}",
        email=f"manager_chat_{m_suffix}@example.com",
        full_name="Finance Chat Manager",
        password_hash="pwm",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    db_session.add_all([analyst_1, analyst_2, manager])
    db_session.flush()

    # Document 1 (Uploaded by Analyst 1)
    doc1 = Document(
        original_filename="acme_contract_terms.pdf",
        stored_filename=f"acme_{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{uuid.uuid4().hex[:12]}",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=analyst_1.id,
    )
    db_session.add(doc1)
    db_session.flush()

    terms_text = (
        "=== TERMS & CONDITIONS ===\n"
        "Payment Terms: 2% early settlement discount if paid within 10 days; Net 30 days.\n"
        "Late payments subject to 1.5% monthly interest penalty.\n"
        "Goods delivered under Incoterms 2020: DAP Manchester depot.\n"
        "Disputes shall be settled under the jurisdiction of the London Commercial Court."
    )
    embed_service = get_embedding_service()
    vecs = embed_service.generate_embeddings([terms_text])

    chunk = DocumentChunk(
        document_id=doc1.id,
        page_number=1,
        chunk_type="TERMS",
        content=terms_text,
        embedding=vecs[0],
        metadata_json={
            "chunk_index": 0,
            "section": "TERMS",
            "page_number": 1,
            "has_table": False,
            "bounding_box_refs": [{"text": "2% early settlement discount", "bounding_box": [10, 20, 30, 40]}],
        },
    )
    db_session.add(chunk)
    db_session.commit()

    token_analyst_1, _ = create_access_token(username=analyst_1.username, user_id=analyst_1.id, role=analyst_1.role)
    token_analyst_2, _ = create_access_token(username=analyst_2.username, user_id=analyst_2.id, role=analyst_2.role)
    token_manager, _ = create_access_token(username=manager.username, user_id=manager.id, role=manager.role)

    return {
        "doc1": doc1,
        "token_analyst_1": token_analyst_1,
        "token_analyst_2": token_analyst_2,
        "token_manager": token_manager,
    }


def test_document_chat_authorized_analyst_success(client, chat_test_setup):
    """Analyst querying their own document receives grounded response with citations."""
    doc1 = chat_test_setup["doc1"]
    token = chat_test_setup["token_analyst_1"]

    response = client.post(
        f"/api/v1/chat/documents/{doc1.id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "What is the early settlement discount and payment deadline?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "assistant"
    assert "content" in data
    assert len(data["content"]) > 0
    assert "citations" in data
    assert len(data["citations"]) > 0

    # Citations must reference chunk ID, page number, and chunk type
    top_cit = data["citations"][0]
    assert top_cit["document_id"] == doc1.id
    assert top_cit["page_number"] == 1
    assert top_cit["chunk_type"] == "TERMS"


def test_document_chat_unauthorized_analyst_forbidden(client, chat_test_setup):
    """Analyst attempting to chat with another user's document receives 403 Forbidden."""
    doc1 = chat_test_setup["doc1"]
    token_unauthorized = chat_test_setup["token_analyst_2"]

    response = client.post(
        f"/api/v1/chat/documents/{doc1.id}/messages",
        headers={"Authorization": f"Bearer {token_unauthorized}"},
        json={"message": "What are the payment terms?"},
    )
    assert response.status_code == 403


def test_document_chat_manager_access(client, chat_test_setup):
    """FINANCE_MANAGER can query any document."""
    doc1 = chat_test_setup["doc1"]
    token = chat_test_setup["token_manager"]

    response = client.post(
        f"/api/v1/chat/documents/{doc1.id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "What Incoterms and delivery conditions apply?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "assistant"
    assert len(data["citations"]) > 0


def test_document_chat_history_and_clear(client, chat_test_setup):
    """Verify chat turns are recorded in history and can be cleared."""
    doc1 = chat_test_setup["doc1"]
    token = chat_test_setup["token_analyst_1"]

    # 1. Send message
    client.post(
        f"/api/v1/chat/documents/{doc1.id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Does this invoice specify late payment interest?"},
    )

    # 2. Get history
    hist_resp = client.get(
        f"/api/v1/chat/documents/{doc1.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 2  # At least 1 user turn and 1 assistant turn
    roles = [h["role"] for h in history]
    assert "user" in roles
    assert "assistant" in roles

    # 3. Clear history
    del_resp = client.delete(
        f"/api/v1/chat/documents/{doc1.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "cleared"

    # 4. Verify history is empty
    hist_after = client.get(
        f"/api/v1/chat/documents/{doc1.id}/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(hist_after.json()) == 0


def test_document_chat_grounding_refusal_when_information_absent(client, chat_test_setup):
    """Negative evidence test: when asked for information not present in the document,
    the assistant must NOT hallucinate or invent facts and must state the information is absent.
    """
    doc1 = chat_test_setup["doc1"]
    token = chat_test_setup["token_analyst_1"]

    # Ask for bank branch and sort code, which are completely absent from doc1 text
    response = client.post(
        f"/api/v1/chat/documents/{doc1.id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "What is the supplier's bank branch and sort code?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "assistant"
    content_lower = data["content"].lower()

    # Verify that the LLM refused to invent facts and stated the absence of evidence
    absence_phrases = [
        "does not specify",
        "not specified",
        "not mention",
        "does not mention",
        "not provided",
        "does not provide",
        "insufficient",
        "not found",
        "no information",
        "no bank",
        "not contain",
    ]
    assert any(phrase in content_lower for phrase in absence_phrases), (
        f"Grounding failed: Assistant did not indicate missing information. Response was: {data['content']}"
    )

    # Citations, when present, must strictly match retrieved chunks for doc1
    if data.get("citations"):
        for cite in data["citations"]:
            assert cite["document_id"] == doc1.id
            assert cite["page_number"] >= 1
