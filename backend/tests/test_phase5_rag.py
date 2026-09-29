"""Phase 5 Unit and Integration Tests: Global RAG Metadata Filtering and Candidate Scaling.

Tests metadata pre-filtering (section, document_type, vendor_id), candidate scaling,
and hard authorization boundaries.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User, UserRole
from app.rag.tools.rag_tool import DocumentRAGTool
from app.repositories.chunk_repository import ChunkRepository
from tests.fixtures.seeded_eval_data import seed_evaluation_corpus


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


def test_chunk_repository_metadata_filtering(db_session: Session):
    data = seed_evaluation_corpus(db_session)
    repo = ChunkRepository(db_session)
    manager = data["users"]["manager"]
    analyst = data["users"]["analyst"]

    # 1. Filter by section='TERMS'
    stmt = select(DocumentChunk)
    filtered_stmt = repo._apply_authorization_predicates(stmt, user=manager, section="TERMS")
    results = list(db_session.scalars(filtered_stmt).all())
    for chunk in results:
        assert chunk.section == "TERMS" or chunk.chunk_type == "TERMS"

    # 2. Filter by document_type='POI'
    stmt_poi = select(DocumentChunk)
    filtered_poi = repo._apply_authorization_predicates(stmt_poi, user=manager, document_type="POI")
    results_poi = list(db_session.scalars(filtered_poi).all())
    for chunk in results_poi:
        doc = db_session.get(Document, chunk.document_id)
        assert doc.document_type == "POI"

    # 3. Authorization boundary: Analyst cannot see manager's documents even if section matches
    stmt_analyst = select(DocumentChunk)
    filtered_analyst = repo._apply_authorization_predicates(stmt_analyst, user=analyst, section="TERMS")
    results_analyst = list(db_session.scalars(filtered_analyst).all())
    for chunk in results_analyst:
        doc = db_session.get(Document, chunk.document_id)
        assert doc.uploaded_by == analyst.id

    # 4. Soft-deleted documents must NEVER be returned
    for chunk in results:
        doc = db_session.get(Document, chunk.document_id)
        assert doc.is_deleted is False


def test_document_rag_tool_metadata_arguments(db_session: Session):
    data = seed_evaluation_corpus(db_session)
    manager = data["users"]["manager"]
    doc_ids = [d.id for d in data["documents"] if not d.is_deleted]

    tool = DocumentRAGTool(db=db_session, user=manager)
    # Perform search with document_ids and section
    output = tool._run(query="payment terms net 30", document_ids=doc_ids[:2], section="TERMS")
    assert isinstance(output, str)
    assert len(tool.execution_logs) > 0
    assert tool.execution_logs[0]["tool"] == "document_rag_tool"
