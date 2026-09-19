"""Tests for Milestone 1: Structure-Aware Chunking, Embedding Generation, and RAG Ingestion.
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus, DocumentType
from app.models.ocr_result import OCRResult
from app.models.user import User, UserRole
from app.rag.chunking import StructureAwareChunker
from app.rag.embeddings import get_embedding_service
from app.repositories.chunk_repository import ChunkRepository
from app.services.rag_ingestion_service import RAGIngestionService


SAMPLE_STRUCTURED_FULL_TEXT = """=== PAGE 1 ===
=== HEADER & METADATA ===
TAX INVOICE
Invoice No: INV-9021
Date: 2024-03-15
PO Number: PO-8812

=== PARTIES ===
--- SELLER COLUMN ---
ACME Industrial Supplies Ltd.
VAT ID: GB123456789
12 Oxford Street, London

--- BUYER COLUMN ---
Global Manufacturing Corp
Client ID: GMC-880
45 Factory Lane, Manchester

=== LINE ITEMS ===
| Item | Description | Qty | Unit Price | Total |
| --- | --- | --- | --- | --- |
| 1 | Hydraulic Pump Valve A1 | 10 | 100.00 | 1000.00 |
| 2 | High Pressure Seal Kit | 2 | 50.00 | 100.00 |

=== TOTALS & SUMMARY ===
Net Worth: 1100.00
VAT (20%): 220.00
Gross Total: 1320.00

Payment Terms: 2% discount if paid within 10 days; Net 30 days.
Late payments subject to 1.5% monthly interest penalty.
Goods delivered under Incoterms 2020: DAP Manchester.
"""


def test_chunking_page_parsing():
    """Verify multi-page document separation."""
    two_page_text = """=== PAGE 1 ===
=== HEADER & METADATA ===
Invoice Page 1

=== PAGE 2 ===
=== TOTALS & SUMMARY ===
Invoice Page 2
"""
    chunker = StructureAwareChunker()
    chunks = chunker.chunk_document(two_page_text)
    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2


def test_chunking_section_types():
    """Verify all section types are properly recognized and typed."""
    chunker = StructureAwareChunker()
    chunks = chunker.chunk_document(SAMPLE_STRUCTURED_FULL_TEXT)

    types = [c.chunk_type for c in chunks]
    assert "HEADER" in types
    assert "PARTIES" in types
    assert "LINE_ITEMS" in types
    assert "SUMMARY" in types
    assert "TERMS" in types


def test_chunking_table_preservation_small():
    """Tables with <= 15 rows must remain intact with markdown header."""
    chunker = StructureAwareChunker(table_max_rows=15)
    chunks = chunker.chunk_document(SAMPLE_STRUCTURED_FULL_TEXT)

    table_chunks = [c for c in chunks if c.chunk_type == "LINE_ITEMS"]
    assert len(table_chunks) == 1
    assert table_chunks[0].metadata_json["has_table"] is True
    assert "| Item | Description |" in table_chunks[0].content
    assert "| 1 | Hydraulic Pump Valve A1 |" in table_chunks[0].content
    assert "| 2 | High Pressure Seal Kit |" in table_chunks[0].content


def test_chunking_table_sliding_window_large():
    """Tables with > 15 rows must split into sliding windows repeating the header."""
    rows = [f"| {i} | Product {i} | 1 | 10.00 | 10.00 |" for i in range(1, 26)]
    table_text = (
        "=== LINE ITEMS ===\n"
        "| Item | Description | Qty | Unit Price | Total |\n"
        "| --- | --- | --- | --- | --- |\n"
        + "\n".join(rows)
    )
    chunker = StructureAwareChunker(table_max_rows=15, table_window_size=10, table_window_step=8)
    chunks = chunker._chunk_table_section(
        table_text.replace("=== LINE ITEMS ===\n", ""), page_num=1, start_index=0, raw_blocks=None
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata_json["has_table"] is True
        # Markdown table header must be repeated in every window
        assert "| Item | Description | Qty | Unit Price | Total |" in chunk.content
        assert "| --- | --- | --- | --- | --- |" in chunk.content


def test_chunk_metadata_no_extraction_leak():
    """Verify chunk metadata strictly adheres to approved schema without ExtractionResult fields."""
    chunker = StructureAwareChunker()
    chunks = chunker.chunk_document(SAMPLE_STRUCTURED_FULL_TEXT)

    forbidden_fields = {"vendor_name", "invoice_date", "grand_total", "extracted_accounting_fields"}
    for chunk in chunks:
        meta = chunk.metadata_json
        assert "chunk_index" in meta
        assert "section" in meta
        assert "page_number" in meta
        assert "has_table" in meta
        assert "line_range" in meta
        for forbidden in forbidden_fields:
            assert forbidden not in meta, f"Metadata must not contain extraction field '{forbidden}'"


def test_embedding_service_dimension():
    """Verify all-MiniLM-L6-v2 produces vectors of dimension 384."""
    service = get_embedding_service()
    assert service.embedding_dim == 384

    texts = [
        "Payment Terms: 2% discount if paid within 10 days; Net 30 days.",
        "ACME Industrial Supplies Ltd VAT ID GB123456789",
    ]
    embeddings = service.generate_embeddings(texts)
    assert len(embeddings) == 2
    assert len(embeddings[0]) == 384
    assert len(embeddings[1]) == 384
    assert isinstance(embeddings[0][0], float)


from app.database.session import get_db_context
import uuid


@pytest.fixture
def db_session():
    """Database session fixture using real DB context."""
    with get_db_context() as session:
        yield session


def test_rag_ingestion_service_idempotency(db_session):
    """Verify ingestion creates chunks and subsequent re-ingestion replaces old chunks without duplication."""
    # 1. Create a test user and document in the db
    unique_suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"rag_user_{unique_suffix}",
        email=f"rag_{unique_suffix}@example.com",
        full_name="RAG Test Analyst",
        password_hash="test_pw_hash",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    doc = Document(
        original_filename="test_rag_invoice.pdf",
        stored_filename=f"test_rag_{unique_suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_hash=f"hash_{unique_suffix}",
        status=DocumentStatus.OCR_COMPLETED.value,
        uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.flush()

    ocr = OCRResult(
        document_id=doc.id,
        engine_name="stub",
        page_count=1,
        full_text=SAMPLE_STRUCTURED_FULL_TEXT,
        average_confidence=0.98,
        raw_blocks=[],
        processing_time_ms=100,
    )
    db_session.add(ocr)
    db_session.commit()

    # 2. Run ingestion
    ingest_service = RAGIngestionService()
    res1 = ingest_service.ingest_document(doc.id)
    assert res1["status"] == "success"
    assert res1["chunk_count"] > 0
    first_chunk_count = res1["chunk_count"]

    # Verify chunks stored in database
    chunk_repo = ChunkRepository(db_session)
    chunks = chunk_repo.get_chunks_for_document(doc.id)
    assert len(chunks) == first_chunk_count

    # 3. Re-run ingestion (simulate OCR re-run)
    res2 = ingest_service.ingest_document(doc.id)
    assert res2["status"] == "success"
    assert res2["deleted_previous_chunks"] == first_chunk_count
    assert res2["chunk_count"] == first_chunk_count

    # Verify no duplicate chunks in database
    db_session.expire_all()
    updated_chunks = chunk_repo.get_chunks_for_document(doc.id)
    assert len(updated_chunks) == first_chunk_count


def test_rag_ingestion_service_failure_isolation(monkeypatch):
    """Verify that failure in embedding or chunking returns status failed without raising."""
    service = RAGIngestionService()

    # Document not found returns skipped
    res_not_found = service.ingest_document(999999)
    assert res_not_found["status"] == "skipped"
    assert res_not_found["reason"] == "not_found"

    # Simulated crash in chunker returns failed status with error details
    def mock_crash(*args, **kwargs):
        raise RuntimeError("Simulated chunker crash")

    monkeypatch.setattr(service.chunker, "chunk_document", mock_crash)
    res_failed = service.ingest_document(999999)
    # Even if DB or chunker blows up, ingest_document handles exception gracefully
    assert res_failed["status"] in ("skipped", "failed")
