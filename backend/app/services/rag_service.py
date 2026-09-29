"""RAG Retrieval Service.

Implements Hybrid Retrieval:
Dense Vector Top-30 + PostgreSQL FTS Top-30
-> Reciprocal Rank Fusion (k=60)
-> Top-25 Candidates
-> Cross-Encoder Reranker (ms-marco-MiniLM-L-6-v2)
-> Top-5 Grounded Chunks
"""
from collections import defaultdict
import logging
import time
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.rag.embeddings import get_embedding_service
from app.rag.reranker import RetrievedChunk, get_reranker_service
from app.repositories.chunk_repository import ChunkRepository

logger = logging.getLogger(__name__)


class RAGService:
    """Hybrid retrieval service combining vector search, PostgreSQL FTS, RRF, and Cross-Encoder."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.chunk_repo = ChunkRepository(db)
        self.embedding_service = get_embedding_service()
        self.reranker_service = get_reranker_service()
        self.rrf_k = settings.RAG_RRF_K
        self.dense_top_k = settings.RAG_DENSE_TOP_K
        self.sparse_top_k = settings.RAG_SPARSE_TOP_K
        self.rerank_candidates_k = settings.RAG_RERANK_CANDIDATES
        self.final_top_k = settings.RAG_FINAL_TOP_K

    def retrieve_for_document(
        self,
        document_id: int,
        query: str,
        user: User,
        top_k: Optional[int] = None,
    ) -> List[RetrievedChunk]:
        """Hybrid retrieval scoped strictly to a single document."""
        limit = top_k or self.final_top_k
        start_time = time.perf_counter()

        # 1. Generate query embedding
        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.generate_query_embedding(query)
        t_embed_ms = (time.perf_counter() - t_embed_start) * 1000.0

        # 2. Dense vector search
        t_dense_start = time.perf_counter()
        dense_chunks = self.chunk_repo.search_vector_for_document(
            document_id=document_id,
            query_vector=query_vector,
            limit=self.dense_top_k,
        )
        t_dense_ms = (time.perf_counter() - t_dense_start) * 1000.0

        # 3. Sparse PostgreSQL FTS search
        t_sparse_start = time.perf_counter()
        sparse_chunks = self.chunk_repo.search_fts_for_document(
            document_id=document_id,
            query_text=query,
            limit=self.sparse_top_k,
        )
        t_sparse_ms = (time.perf_counter() - t_sparse_start) * 1000.0

        # 4. Reciprocal Rank Fusion
        t_rrf_start = time.perf_counter()
        fused_candidates = self._reciprocal_rank_fusion(
            dense_chunks=dense_chunks,
            sparse_chunks=sparse_chunks,
            max_candidates=self.rerank_candidates_k,
        )
        t_rrf_ms = (time.perf_counter() - t_rrf_start) * 1000.0

        # 5. Cross-Encoder Reranking
        t_rerank_start = time.perf_counter()
        final_chunks = self.reranker_service.rerank(
            query=query,
            candidates=fused_candidates,
            top_k=limit,
        )
        t_rerank_ms = (time.perf_counter() - t_rerank_start) * 1000.0

        total_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "[RAG Document Retrieval] doc_id=%d query=%r: dense=%d (%.1fms), sparse=%d (%.1fms), rrf=%d (%.1fms), final=%d (%.1fms), total=%.1fms",
            document_id,
            query[:50],
            len(dense_chunks),
            t_dense_ms,
            len(sparse_chunks),
            t_sparse_ms,
            len(fused_candidates),
            t_rrf_ms,
            len(final_chunks),
            t_rerank_ms,
            total_ms,
        )

        return final_chunks

    def retrieve_global(
        self,
        query: str,
        user: User,
        document_ids: Optional[List[int]] = None,
        section: Optional[str] = None,
        document_type: Optional[str] = None,
        vendor_id: Optional[int] = None,
        top_k: Optional[int] = None,
    ) -> List[RetrievedChunk]:
        """Hybrid retrieval across authorized corpus with pre-retrieval SQL enforcement and metadata pre-filtering."""
        # Dynamic candidate scaling: for broad portfolio searches, allow scaling up to 15 chunks
        if top_k is not None:
            limit = top_k
        elif document_ids is not None and len(document_ids) == 1:
            limit = 5
        else:
            limit = max(self.final_top_k, 10)

        start_time = time.perf_counter()

        # 1. Generate query embedding
        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.generate_query_embedding(query)
        t_embed_ms = (time.perf_counter() - t_embed_start) * 1000.0

        # 2. Dense vector search with pre-retrieval authorization and metadata pre-filters
        t_dense_start = time.perf_counter()
        dense_chunks = self.chunk_repo.search_vector_global(
            query_vector=query_vector,
            user=user,
            document_ids=document_ids,
            section=section,
            document_type=document_type,
            vendor_id=vendor_id,
            limit=max(self.dense_top_k, 40),
        )
        t_dense_ms = (time.perf_counter() - t_dense_start) * 1000.0

        # 3. Sparse PostgreSQL FTS search with pre-retrieval authorization and metadata pre-filters
        t_sparse_start = time.perf_counter()
        sparse_chunks = self.chunk_repo.search_fts_global(
            query_text=query,
            user=user,
            document_ids=document_ids,
            section=section,
            document_type=document_type,
            vendor_id=vendor_id,
            limit=max(self.sparse_top_k, 40),
        )
        t_sparse_ms = (time.perf_counter() - t_sparse_start) * 1000.0

        # 4. Reciprocal Rank Fusion
        t_rrf_start = time.perf_counter()
        fused_candidates = self._reciprocal_rank_fusion(
            dense_chunks=dense_chunks,
            sparse_chunks=sparse_chunks,
            max_candidates=self.rerank_candidates_k,
        )
        t_rrf_ms = (time.perf_counter() - t_rrf_start) * 1000.0

        # 5. Cross-Encoder Reranking
        t_rerank_start = time.perf_counter()
        final_chunks = self.reranker_service.rerank(
            query=query,
            candidates=fused_candidates,
            top_k=limit,
        )
        t_rerank_ms = (time.perf_counter() - t_rerank_start) * 1000.0

        total_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "[RAG Global Retrieval] user=%d role=%s query=%r docs_filter=%s: dense=%d (%.1fms), sparse=%d (%.1fms), rrf=%d (%.1fms), final=%d (%.1fms), total=%.1fms",
            user.id,
            user.role,
            query[:50],
            document_ids,
            len(dense_chunks),
            t_dense_ms,
            len(sparse_chunks),
            t_sparse_ms,
            len(fused_candidates),
            t_rrf_ms,
            len(final_chunks),
            t_rerank_ms,
            total_ms,
        )

        return final_chunks

    def _reciprocal_rank_fusion(
        self,
        dense_chunks: List,
        sparse_chunks: List,
        max_candidates: int,
    ) -> List[RetrievedChunk]:
        """Combine dense and sparse rankings using RRF formula: 1 / (k + rank)."""
        rrf_scores: Dict[int, float] = defaultdict(float)
        chunk_map: Dict[int, RetrievedChunk] = {}

        # Process dense ranks
        for rank, chunk in enumerate(dense_chunks, start=1):
            rrf_scores[chunk.id] += 1.0 / (self.rrf_k + rank)
            if chunk.id not in chunk_map:
                doc_title = (getattr(chunk, "document", None) and getattr(chunk.document, "original_filename", None)) or (chunk.metadata_json.get("filename") if chunk.metadata_json else None)
                chunk_map[chunk.id] = RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    page_number=chunk.page_number,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    metadata_json=chunk.metadata_json or {},
                    document_title=doc_title,
                    dense_rank=rank,
                )
            else:
                chunk_map[chunk.id].dense_rank = rank

        # Process sparse ranks
        for rank, chunk in enumerate(sparse_chunks, start=1):
            rrf_scores[chunk.id] += 1.0 / (self.rrf_k + rank)
            if chunk.id not in chunk_map:
                doc_title = (getattr(chunk, "document", None) and getattr(chunk.document, "original_filename", None)) or (chunk.metadata_json.get("filename") if chunk.metadata_json else None)
                chunk_map[chunk.id] = RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    page_number=chunk.page_number,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    metadata_json=chunk.metadata_json or {},
                    document_title=doc_title,
                    sparse_rank=rank,
                )
            else:
                chunk_map[chunk.id].sparse_rank = rank

        # Attach computed RRF scores
        for chunk_id, score in rrf_scores.items():
            chunk_map[chunk_id].rrf_score = score

        # Sort descending by RRF score
        sorted_candidates = sorted(chunk_map.values(), key=lambda c: c.rrf_score, reverse=True)
        return sorted_candidates[:max_candidates]
