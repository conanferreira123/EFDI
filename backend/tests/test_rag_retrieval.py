"""Tests for Milestone 2: Hybrid Retrieval (Dense Vector + PostgreSQL FTS + RRF + Cross-Encoder Reranker).
"""
import uuid
import pytest
from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.embeddings import get_embedding_service
from app.rag.reranker import RetrievedChunk, get_reranker_service
from app.repositories.chunk_repository import ChunkRepository
from app.services.rag_service import RAGService


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def test_users(db_session):
    u1_suffix = uuid.uuid4().hex[:8]
    u2_suffix = uuid.uuid4().hex[:8]
    m_suffix = uuid.uuid4().hex[:8]

    analyst_1 = User(
        username=f"analyst_1_{u1_suffix}",
        email=f"analyst_1_{u1_suffix}@example.com",
        full_name="Analyst One",
        password_hash="pw1",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    analyst_2 = User(
        username=f"analyst_2_{u2_suffix}",
        email=f"analyst_2_{u2_suffix}@example.com",
        full_name="Analyst Two",
        password_hash="pw2",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    manager = User(
        username=f"manager_{m_suffix}",
        email=f"manager_{m_suffix}@example.com",
        full_name="Finance Manager",
        password_hash="pwm",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    db_session.add_all([analyst_1, analyst_2, manager])
    db_session.flush()
    return analyst_1, analyst_2, manager


@pytest.fixture
def test_corpus(db_session, test_users):
    analyst_1, analyst_2, _ = test_users
    embed_service = get_embedding_service()

    # Document 1 (Uploaded by Analyst 1)
    doc1 = Document(
        original_filename="acme_invoice_9021.pdf",
        stored_filename=f"acme_{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{uuid.uuid4().hex[:12]}",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=analyst_1.id,
    )
    # Document 2 (Uploaded by Analyst 2)
    doc2 = Document(
        original_filename="apex_invoice_7700.pdf",
        stored_filename=f"apex_{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash_{uuid.uuid4().hex[:12]}",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=analyst_2.id,
    )
    db_session.add_all([doc1, doc2])
    db_session.flush()

    c1_text = (
        "TAX INVOICE INV-9021 PO-8812 Vendor Code V-1002 from ACME Industrial Supplies Ltd. "
        "VAT ID GB123456789. Payment Terms: 2% discount if paid within 10 days; Net 30 days. "
        "Late payments subject to 1.5% monthly interest penalty. Goods delivered under Incoterms 2020: DAP Manchester."
    )
    c2_text = (
        "TAX INVOICE INV-7700 PO-4401 Vendor Code V-5001 from Apex Logistics International. "
        "VAT ID GB987654321. Standard terms Net 60 days. Delivery under Incoterms CIF Liverpool."
    )

    vecs = embed_service.generate_embeddings([c1_text, c2_text])

    chunk1 = DocumentChunk(
        document_id=doc1.id,
        page_number=1,
        chunk_type="TERMS",
        content=c1_text,
        embedding=vecs[0],
        metadata_json={"chunk_index": 0, "section": "TERMS", "page_number": 1, "has_table": False},
    )
    chunk2 = DocumentChunk(
        document_id=doc2.id,
        page_number=1,
        chunk_type="TERMS",
        content=c2_text,
        embedding=vecs[1],
        metadata_json={"chunk_index": 0, "section": "TERMS", "page_number": 1, "has_table": False},
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()

    return doc1, doc2, chunk1, chunk2


def test_dense_vector_search_document_scoping(db_session, test_corpus):
    """Dense vector search must be strictly scoped to document_id."""
    doc1, doc2, chunk1, chunk2 = test_corpus
    repo = ChunkRepository(db_session)
    embed_service = get_embedding_service()

    q_vec = embed_service.generate_query_embedding("payment discount terms")
    results_doc1 = repo.search_vector_for_document(document_id=doc1.id, query_vector=q_vec, limit=5)

    assert len(results_doc1) > 0
    assert all(r.document_id == doc1.id for r in results_doc1)
    assert any(r.id == chunk1.id for r in results_doc1)
    assert all(r.id != chunk2.id for r in results_doc1)


def test_sparse_fts_natural_language_and_identifiers(db_session, test_corpus):
    """PostgreSQL FTS must successfully find natural language terms and exact alphanumeric identifiers."""
    doc1, doc2, chunk1, chunk2 = test_corpus
    repo = ChunkRepository(db_session)

    # 1. Natural language query
    nl_results = repo.search_fts_for_document(doc1.id, "payment discount 10 days")
    assert len(nl_results) > 0
    assert nl_results[0].id == chunk1.id

    # 2. Alphanumeric identifiers: INV-9021, PO-8812, V-1002, GB123456789
    for identifier in ["INV-9021", "PO-8812", "V-1002", "GB123456789"]:
        id_results = repo.search_fts_for_document(doc1.id, identifier)
        assert len(id_results) > 0, f"PostgreSQL FTS failed to match identifier '{identifier}'"
        assert id_results[0].id == chunk1.id


def test_rrf_scoring_deterministic():
    """Verify Reciprocal Rank Fusion computes standard RRF score: 1 / (60 + rank)."""
    service = RAGService(db=None)

    c1 = DocumentChunk(id=1, document_id=10, page_number=1, chunk_type="TERMS", content="Chunk 1")
    c2 = DocumentChunk(id=2, document_id=10, page_number=1, chunk_type="TERMS", content="Chunk 2")

    # Dense: [c1 (rank 1), c2 (rank 2)]
    # Sparse: [c2 (rank 1), c1 (rank 2)]
    fused = service._reciprocal_rank_fusion(dense_chunks=[c1, c2], sparse_chunks=[c2, c1], max_candidates=10)

    assert len(fused) == 2
    expected_c1_score = 1.0 / (60 + 1) + 1.0 / (60 + 2)
    assert pytest.approx(fused[0].rrf_score, 0.0001) == expected_c1_score


def test_cross_encoder_reranker_ordering():
    """Verify cross-encoder orders the most semantically relevant candidate at the top."""
    reranker = get_reranker_service()

    query = "What is the penalty for paying late?"
    chunks = [
        RetrievedChunk(
            chunk_id=1,
            document_id=1,
            page_number=1,
            chunk_type="HEADER",
            content="TAX INVOICE Invoice No: INV-9021 Date: 2024-03-15",
            metadata_json={},
        ),
        RetrievedChunk(
            chunk_id=2,
            document_id=1,
            page_number=1,
            chunk_type="TERMS",
            content="Late payments subject to 1.5% monthly interest penalty. Overdue balances incur collection costs.",
            metadata_json={},
        ),
    ]

    # Without threshold filtering, both chunks are ranked and the penalty chunk is top
    reranked = reranker.rerank(query, chunks, top_k=2, min_score=-999.0)
    assert len(reranked) == 2
    assert reranked[0].chunk_id == 2
    assert reranked[0].rerank_score > reranked[1].rerank_score
    assert reranked[0].rerank_score > 0.0


def test_pre_retrieval_authorization_analyst_isolation(db_session, test_corpus, test_users):
    """FINANCE_ANALYST global retrieval must strictly enforce uploaded_by in the database query.

    Never load unauthorized chunks into process memory.
    """
    doc1, doc2, chunk1, chunk2 = test_corpus
    analyst_1, analyst_2, _ = test_users
    rag_service = RAGService(db_session)

    # Analyst 1 searches for general terms
    results_analyst_1 = rag_service.retrieve_global(
        query="payment terms and delivery incoterms",
        user=analyst_1,
        top_k=10,
    )
    assert len(results_analyst_1) > 0
    # Every chunk must belong to a document uploaded by Analyst 1
    for chunk in results_analyst_1:
        assert chunk.document_id == doc1.id
        assert chunk.document_id != doc2.id


def test_pre_retrieval_authorization_manager_global(db_session, test_corpus, test_users):
    """FINANCE_MANAGER can retrieve authorized chunks across all users."""
    doc1, doc2, chunk1, chunk2 = test_corpus
    _, _, manager = test_users
    rag_service = RAGService(db_session)

    # Scope to doc1 and doc2 to isolate from existing database fixtures
    results = rag_service.retrieve_global(
        query="Incoterms",
        user=manager,
        document_ids=[doc1.id, doc2.id],
        top_k=10,
    )
    doc_ids = {r.document_id for r in results}
    # Manager sees both documents
    assert doc1.id in doc_ids
    assert doc2.id in doc_ids


def test_compound_document_ids_filter(db_session, test_corpus, test_users):
    """When document_ids list is provided (e.g. from SQL tool), retrieval is scoped strictly to those IDs."""
    doc1, doc2, chunk1, chunk2 = test_corpus
    _, _, manager = test_users
    rag_service = RAGService(db_session)

    # Scoped only to doc1
    results = rag_service.retrieve_global(
        query="Incoterms",
        user=manager,
        document_ids=[doc1.id],
        top_k=10,
    )
    assert len(results) > 0
    assert all(r.document_id == doc1.id for r in results)
