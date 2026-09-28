"""RAG Ingestion Service.

Orchestrates document chunking, embedding generation, and idempotent chunk persistence.
Always executes with an independent database session so core processing is never blocked.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

from app.database.session import get_db_context
from app.models.document_chunk import DocumentChunk
from app.rag.chunking import DoclingNativeChunker, StructureAwareChunker
from app.rag.embeddings import get_embedding_service
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.ocr_result_repository import OCRResultRepository

logger = logging.getLogger(__name__)


class RAGIngestionService:
    """Service responsible for chunking and indexing documents into the vector store."""

    def __init__(self) -> None:
        self.chunker = StructureAwareChunker()
        self.docling_chunker = DoclingNativeChunker()

    def ingest_document(self, document_id: int, docling_doc: Optional[Any] = None) -> Dict[str, Any]:
        """Synchronously ingest a document using a fresh, independent DB session.

        Guarantees:
        1. Uses its own DB session (get_db_context).
        2. Strictly uses canonical OCRResult.full_text (never ExtractionResult fields).
        3. Idempotent: deletes old chunks for document_id before inserting new ones.
        4. Soft-deleted documents are skipped.
        5. Commits/rollbacks independently.
        """
        start_time = time.perf_counter()
        logger.info("[RAG Ingestion] Started for document_id=%d", document_id)

        try:
            with get_db_context() as db:
                doc_repo = DocumentRepository(db)
                ocr_repo = OCRResultRepository(db)
                chunk_repo = ChunkRepository(db)

                document = doc_repo.get_by_id(document_id)
                if not document:
                    logger.warning("[RAG Ingestion] Document %d not found, aborting", document_id)
                    return {"status": "skipped", "document_id": document_id, "reason": "not_found"}

                if getattr(document, "is_deleted", False):
                    logger.warning("[RAG Ingestion] Document %d is soft-deleted, skipping", document_id)
                    return {"status": "skipped", "document_id": document_id, "reason": "soft_deleted"}

                ocr_result = ocr_repo.get_latest_for_document(document_id)
                if not ocr_result or not ocr_result.full_text or not ocr_result.full_text.strip():
                    logger.warning("[RAG Ingestion] Document %d has no OCR text, skipping", document_id)
                    return {"status": "skipped", "document_id": document_id, "reason": "no_ocr_text"}

                is_docling = (ocr_result.engine_name == "docling")
                if is_docling and docling_doc is None:
                    try:
                        from app.ocr.factory import get_ocr_engine
                        from app.utils.file_storage import get_file_path

                        file_path = get_file_path(document.stored_filename)
                        if file_path.exists():
                            engine = get_ocr_engine("docling")
                            conv = engine._get_converter()
                            conv_res = conv.convert(file_path)
                            docling_doc = conv_res.document
                    except Exception as doc_err:
                        logger.error("[RAG Ingestion] Failed to convert document %d with Docling: %s", document_id, doc_err)
                        raise

                if is_docling:
                    if docling_doc is None:
                        raise ValueError(f"DoclingDocument unavailable for docling-processed document {document_id}")
                    chunks_data = self.docling_chunker.chunk_document(docling_doc)
                else:
                    # Canonical OCR text & raw blocks for legacy / non-docling engines
                    full_text = ocr_result.full_text
                    raw_blocks = ocr_result.raw_blocks if isinstance(ocr_result.raw_blocks, list) else None
                    chunks_data = self.chunker.chunk_document(full_text, raw_blocks=raw_blocks)

                if not chunks_data:
                    logger.warning("[RAG Ingestion] 0 chunks produced for document %d", document_id)
                    return {"status": "skipped", "document_id": document_id, "reason": "zero_chunks"}

                # Generate embeddings for chunk content only (never metadata)
                embedding_service = get_embedding_service()
                texts = [c.content for c in chunks_data]
                t_embed_start = time.perf_counter()
                embeddings = embedding_service.generate_embeddings(texts)
                t_embed_ms = (time.perf_counter() - t_embed_start) * 1000.0

                # Idempotent replacement: remove existing chunks
                deleted_chunks = chunk_repo.delete_for_document(document_id)

                # Persist new chunks
                entities = []
                for c_data, vec in zip(chunks_data, embeddings):
                    chunk_entity = DocumentChunk(
                        document_id=document_id,
                        page_number=c_data.page_number,
                        chunk_type=c_data.chunk_type,
                        section=c_data.section or "OTHER",
                        content=c_data.content,
                        embedding=vec,
                        metadata_json=c_data.metadata_json,
                    )
                    entities.append(chunk_entity)

                chunk_repo.bulk_create(entities)
                # Session commits on context exit

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "[RAG Ingestion] Finished for document_id=%d: chunks=%d, old_deleted=%d, embed_ms=%.1f, total_ms=%.1f",
                document_id,
                len(entities),
                deleted_chunks,
                t_embed_ms,
                elapsed_ms,
            )
            return {
                "status": "success",
                "document_id": document_id,
                "chunk_count": len(entities),
                "deleted_previous_chunks": deleted_chunks,
                "embedding_time_ms": t_embed_ms,
                "total_time_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.exception("[RAG Ingestion] Error ingesting document %d: %s", document_id, exc)
            return {
                "status": "failed",
                "document_id": document_id,
                "error": str(exc),
            }

    def ingest_document_async(self, document_id: int, docling_doc: Optional[Any] = None) -> None:
        """Asynchronously trigger document ingestion in a background thread.

        Completely isolated; failure will never impact the calling thread or request.
        """
        def _run():
            try:
                self.ingest_document(document_id, docling_doc=docling_doc)
            except Exception as e:
                logger.error("[RAG Ingestion Async] Background thread error for document %d: %s", document_id, e)

        worker = threading.Thread(target=_run, name=f"rag-ingest-{document_id}", daemon=True)
        worker.start()


_rag_ingestion_service: Optional[RAGIngestionService] = None


def get_rag_ingestion_service() -> RAGIngestionService:
    """Dependency / accessor for RAGIngestionService singleton."""
    global _rag_ingestion_service
    if _rag_ingestion_service is None:
        _rag_ingestion_service = RAGIngestionService()
    return _rag_ingestion_service
