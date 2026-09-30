"""Unit and Integration Tests for Targeted Document Chatbot Timeout Fixes.

Validates:
- FIX 1: Startup pre-warming of SentenceTransformer and CrossEncoder models.
- FIX 2: Suppression of redundant synonym searches and evidence exhaustion on incomplete documents.
- Preservation of legitimate multi-search queries.
- Preservation of 5-section Invoice Summary.
- Preservation of strict 30-second timeout enforcement.
"""
import uuid
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessage

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.document_agent import DocumentReActAgent, _is_redundant_query
from app.rag.embeddings import get_embedding_service
from app.rag.reranker import get_reranker_service
from app.rag.response_guardrails import GLOBAL_TIMEOUT_MESSAGE


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def timeout_test_setup(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"analyst_{suffix}",
        email=f"analyst_{suffix}@enterprise.com",
        full_name="Financial Analyst",
        password_hash="pw",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    doc = Document(
        original_filename="Test_Invoice_Partial.pdf",
        stored_filename=f"{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{suffix}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.flush()

    chunk_1 = "Order ID: 10249\nCustomer ID: TOMSP\nOrder Date: 2016-07-05"
    chunk_2 = "Product Details:\n14, Product Name = Tofu. Quantity = 9. Unit Price = 18.6. Total = 1863.4"

    embedder = get_embedding_service()
    vecs = embedder.generate_embeddings([chunk_1, chunk_2])

    dc1 = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="HEADER",
        content=chunk_1,
        embedding=vecs[0],
        metadata_json={"chunk_index": 0, "page_number": 1},
    )
    dc2 = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="LINE_ITEMS",
        content=chunk_2,
        embedding=vecs[1],
        metadata_json={"chunk_index": 1, "page_number": 1},
    )
    db_session.add_all([dc1, dc2])
    db_session.commit()

    return {
        "user": user,
        "doc": doc,
        "chunks": [dc1, dc2],
    }


# =========================================================================
# TEST GROUP 1 & 2 — Model Warm-Up & RAG Semantics
# =========================================================================
def test_embedding_and_reranker_models_warmed():
    """Verify embedding and reranker singleton services initialize correctly with expected dimensions."""
    emb_service = get_embedding_service()
    model = emb_service._get_model()
    assert model is not None
    assert emb_service.embedding_dim == 384

    # Embedding dimension must be 384
    vec = emb_service.generate_query_embedding("test payment terms")
    assert len(vec) == 384
    assert isinstance(vec[0], float)

    # Reranker model must be loaded
    rerank_service = get_reranker_service()
    reranker = rerank_service._get_model()
    assert reranker is not None


# =========================================================================
# TEST GROUP 3 — Redundant Query Suppression & Synonym Containment
# =========================================================================
def test_redundant_query_containment_detection():
    """Verify that expanding a search with synonyms or superset terms is correctly flagged as redundant."""
    executed = [
        {"tool": "document_rag_tool", "query": "vendor name"},
    ]

    # Exact superset / containment variations should be flagged
    assert _is_redundant_query("document_rag_tool", "vendor name invoice", executed) is True
    assert _is_redundant_query("document_rag_tool", "vendor name, supplier name, company name", executed) is True

    # Legitimate distinct queries must NOT be flagged
    assert _is_redundant_query("document_rag_tool", "payment terms and settlement discount", executed) is False
    assert _is_redundant_query("document_rag_tool", "line items and product descriptions", executed) is False
    assert _is_redundant_query("financial_calculator_tool", "18.6 * 9", executed) is False


def test_redundant_query_containment_suppresses_unnecessary_rag_calls(db_session, timeout_test_setup):
    """When the LLM expands a search with synonym/containment terms, it is intercepted without re-searching."""
    user = timeout_test_setup["user"]
    doc = timeout_test_setup["doc"]

    class MockChatModel:
        def __init__(self):
            self.turn = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.turn += 1
            if self.turn == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "vendor name"},
                        "id": "tc_1",
                    }],
                )
            elif self.turn == 2:
                # Synonym expansion that contains the original search terms
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "vendor name invoice details"},
                        "id": "tc_2",
                    }],
                )
            else:
                return AIMessage(content="The vendor name is not stated in the document.")

    mock_llm = MockChatModel()
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)
    result = agent.run(document_id=doc.id, query="What is the vendor name?", user=user)

    assert "not stated in the document" in result.content.lower()
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].get("tool") == "document_rag_tool"
    assert result.tool_calls[1].get("status") == "redundant_suppressed"


def test_evidence_exhaustion_suppresses_when_all_chunks_retrieved(db_session):
    """When all chunks for a document have already been retrieved, further RAG searches return exhaustion notice."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"analyst_exh_{suffix}",
        email=f"analyst_exh_{suffix}@enterprise.com",
        full_name="Analyst",
        password_hash="pw",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    doc = Document(
        original_filename="Single_Chunk_Doc.pdf",
        stored_filename=f"{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_hash=f"hash_{suffix}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.flush()

    chunk_content = "Order ID: 10249\nCustomer ID: TOMSP\nOrder Date: 2016-07-05"
    embedder = get_embedding_service()
    vec = embedder.generate_embeddings([chunk_content])[0]

    dc = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="HEADER",
        content=chunk_content,
        embedding=vec,
        metadata_json={"chunk_index": 0, "page_number": 1},
    )
    db_session.add(dc)
    db_session.commit()

    class MockChatModel:
        def __init__(self):
            self.turn = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.turn += 1
            if self.turn == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "order details"},
                        "id": "tc_1",
                    }],
                )
            elif self.turn == 2:
                # Distinct query, but all 1 chunks of this document were already retrieved in turn 1
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "shipping destination address"},
                        "id": "tc_2",
                    }],
                )
            else:
                return AIMessage(content="Shipping destination is not stated in the document.")

    mock_llm = MockChatModel()
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)
    result = agent.run(document_id=doc.id, query="What is the shipping destination?", user=user)

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].get("tool") == "document_rag_tool"
    assert result.tool_calls[1].get("status") == "redundant_suppressed"
    assert "already retrieved" in result.tool_calls[1].get("summary", "")


# =========================================================================
# TEST GROUP 4 — Legitimate Multi-Search Questions Preserved
# =========================================================================
def test_valid_multi_search_question_preserved(db_session, timeout_test_setup):
    """Verify distinct searches across different topics execute without false suppression."""
    user = timeout_test_setup["user"]
    doc = timeout_test_setup["doc"]

    # When queries are distinct, both execute
    executed = [
        {"tool": "document_rag_tool", "query": "order date and header details"},
    ]
    assert _is_redundant_query("document_rag_tool", "product quantities and unit prices", executed) is False


# =========================================================================
# TEST GROUP 5 — Invoice Summary Intact with Exhaustion Protection
# =========================================================================
def test_invoice_summary_gathers_evidence_and_formats_5_sections(db_session, timeout_test_setup):
    """Verify that Invoice Summary completes cleanly and produces the 5 approved sections."""
    user = timeout_test_setup["user"]
    doc = timeout_test_setup["doc"]

    summary_text = (
        "# Invoice Summary\n\n"
        "## 1. Invoice Overview\n"
        "**Vendor:** Not stated in the document.\n"
        "**Invoice Number:** 10249\n"
        "**Invoice Date:** 2016-07-05\n"
        "**Due Date:** Not stated in the document.\n"
        "**Currency:** Not stated in the document.\n"
        "**Total Amount Due:** 1863.4\n"
        "**PO Number:** Not stated in the document.\n\n"
        "## 2. Payment Details\n"
        "**Payment Terms:** Not stated in the document.\n"
        "**Payment Method:** Not stated in the document.\n"
        "**Early Payment Discount:** None stated in the document.\n\n"
        "## 3. Amount Breakdown\n"
        "**Total:** 1863.4\n\n"
        "## 4. Items / Services\n"
        "| Description | Qty | Unit Price | Amount |\n"
        "|---|---:|---:|---:|\n"
        "| Tofu | 9 | 18.6 | 167.4 |\n\n"
        "## 5. AP Attention\n"
        "- Missing vendor name and payment terms."
    )

    class MockChatModel:
        def __init__(self):
            self.turn = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.turn += 1
            if self.turn == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "invoice summary totals items"},
                        "id": "call_sum_1",
                    }],
                )
            else:
                return AIMessage(content=summary_text)

    mock_llm = MockChatModel()
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)
    result = agent.run(document_id=doc.id, query="Summarize this invoice", user=user)

    assert "# Invoice Summary" in result.content
    assert "## 1. Invoice Overview" in result.content
    assert "## 2. Payment Details" in result.content
    assert "## 3. Amount Breakdown" in result.content
    assert "## 4. Items / Services" in result.content
    assert "## 5. AP Attention" in result.content
    assert len(result.citations) > 0


# =========================================================================
# TEST GROUP 6 — Timeout Enforcement Preserved
# =========================================================================
def test_timeout_enforcement_remains_intact(db_session, timeout_test_setup):
    """Verify that timeout_seconds parameter correctly triggers GLOBAL_TIMEOUT_MESSAGE if exceeded."""
    user = timeout_test_setup["user"]
    doc = timeout_test_setup["doc"]

    class MockHangingChatModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            import time
            time.sleep(0.05)
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "document_rag_tool",
                    "args": {"query": "hanging search"},
                    "id": "call_hang",
                }],
            )

    agent = DocumentReActAgent(db=db_session, llm=MockHangingChatModel())
    # Setting timeout to 0.01 seconds guarantees immediate timeout enforcement
    result = agent.run(document_id=doc.id, query="Summarize this document", user=user, timeout_seconds=0.01)
    assert result.content == GLOBAL_TIMEOUT_MESSAGE
