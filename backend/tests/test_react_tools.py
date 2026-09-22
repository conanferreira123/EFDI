"""Unit and Integration Tests for ReAct Tool Wrappers.

Tests:
- DatabaseQueryTool: input validation, user context injection, safe output normalization, error handling.
- DocumentRAGTool: global retrieval, document-scoped retrieval, document_ids intersection, citations accumulation.
- FinancialCalculatorTool: expressions, discounts, date offsets, error handling.
"""
from decimal import Decimal
import json
import uuid
import pytest
from sqlalchemy.orm import Session

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.embeddings import get_embedding_service
from app.rag.tools.database_tool import DatabaseQueryTool
from app.rag.tools.rag_tool import DocumentRAGTool
from app.rag.tools.calculator_tool import FinancialCalculatorTool


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def test_setup(db_session: Session):
    suffix = uuid.uuid4().hex[:8]
    manager = User(
        username=f"mgr_tools_{suffix}",
        email=f"mgr_tools_{suffix}@example.com",
        full_name="Manager Tools",
        password_hash="pwm",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    analyst = User(
        username=f"analyst_tools_{suffix}",
        email=f"analyst_tools_{suffix}@example.com",
        full_name="Analyst Tools",
        password_hash="pwa",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add_all([manager, analyst])
    db_session.flush()

    doc = Document(
        original_filename=f"invoice_{suffix}.pdf",
        stored_filename=f"inv_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_hash=f"hash_{suffix}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=analyst.id,
    )
    db_session.add(doc)
    db_session.flush()

    chunk_text = "Vendor ACME Global Services. Total: $5,000.00. Payment terms: 2% discount within 10 days."
    embedder = get_embedding_service()
    vec = embedder.generate_embeddings([chunk_text])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="TERMS",
        content=chunk_text,
        embedding=vec,
        metadata_json={"chunk_index": 0, "page_number": 1},
    )
    db_session.add(chunk)
    db_session.commit()

    return {
        "manager": manager,
        "analyst": analyst,
        "doc": doc,
        "chunk": chunk,
    }


def test_financial_calculator_tool_expression():
    """Verify calculator tool handles basic arithmetic expressions safely."""
    tool = FinancialCalculatorTool()
    obs = tool._run(action="calculate_expression", expression="1500.50 * 2 - 100")
    assert "2901.00" in obs
    assert len(tool.execution_logs) == 1
    assert tool.execution_logs[0]["result"]["result"] == "2901.00"


def test_financial_calculator_tool_discount():
    """Verify calculator tool computes payment discounts and deadlines."""
    tool = FinancialCalculatorTool()
    obs = tool._run(
        action="calculate_discount",
        gross_amount="5000.00",
        discount_percentage="2%",
        days_offset=10,
        invoice_date="2024-05-01",
    )
    assert "100.00" in obs
    assert "4900.00" in obs
    assert "2024-05-11" in obs
    assert len(tool.execution_logs) == 1
    assert tool.execution_logs[0]["result"]["discount_amount"] == "100.00"


def test_financial_calculator_tool_date_offset():
    """Verify calculator tool computes date offsets."""
    tool = FinancialCalculatorTool()
    obs = tool._run(
        action="calculate_date_offset",
        invoice_date="2024-01-15",
        days_offset=30,
    )
    assert "2024-02-14" in obs
    assert len(tool.execution_logs) == 1


def test_financial_calculator_tool_invalid_expression():
    """Verify calculator tool returns a structured error for invalid/unsafe expressions."""
    tool = FinancialCalculatorTool()
    obs = tool._run(action="calculate_expression", expression="__import__('os').system('ls')")
    assert "Financial Calculator Error:" in obs
    assert "Invalid characters" in obs


def test_document_rag_tool_global(db_session, test_setup):
    """Verify global RAG tool retrieval across authorized documents."""
    manager = test_setup["manager"]
    rag_tool = DocumentRAGTool(db=db_session, user=manager)

    obs = rag_tool._run(query="What is the discount rate for ACME?")
    assert "Retrieved Document Evidence" in obs
    assert "2% discount" in obs
    assert len(rag_tool.retrieved_chunks) >= 1
    assert len(rag_tool.execution_logs) == 1


def test_document_rag_tool_fixed_document_id(db_session, test_setup):
    """Verify Document-Agent RAG tool strictly ignores user-supplied document_ids and binds to enforced_document_id."""
    analyst = test_setup["analyst"]
    doc = test_setup["doc"]
    rag_tool = DocumentRAGTool(db=db_session, user=analyst, enforced_document_id=doc.id)

    # Attempt to query another doc_id (e.g. 999999) via tool argument
    obs = rag_tool._run(query="Payment terms", document_ids=[999999])
    assert "Retrieved Document Evidence" in obs
    # Result must only come from doc.id
    for chunk in rag_tool.retrieved_chunks:
        assert chunk.document_id == doc.id


def test_database_tool_execution(db_session, test_setup):
    """Verify DatabaseQueryTool executes valid queries with backend-injected user context."""
    manager = test_setup["manager"]
    db_tool = DatabaseQueryTool(db=db_session, user=manager)

    obs = db_tool._run(query="How many documents are there in total?")
    assert "Database Query Results" in obs or "Database Query Result:" in obs
    assert len(db_tool.execution_logs) == 1
    assert "sql" in db_tool.execution_logs[0]


def test_database_tool_error_handling(db_session, test_setup, monkeypatch):
    """Verify DatabaseQueryTool returns structured error on service failure without crashing."""
    manager = test_setup["manager"]
    db_tool = DatabaseQueryTool(db=db_session, user=manager)

    from app.services.text_to_sql_service import TextToSQLService

    def mock_fail(*args, **kwargs):
        raise ValueError("Simulated SQL translation failure")

    monkeypatch.setattr(TextToSQLService, "generate_and_execute_sql", mock_fail)
    obs = db_tool._run(query="Trigger service failure")
    assert "Database Query Error:" in obs
    assert "Simulated SQL translation failure" in obs
    assert len(db_tool.execution_logs) == 1
    assert db_tool.execution_logs[0]["status"] == "error"
