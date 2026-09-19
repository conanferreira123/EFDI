"""Cross-Encoder Reranker Service.

Uses cross-encoder/ms-marco-MiniLM-L-6-v2 for precision reranking of hybrid candidates.
"""
from dataclasses import dataclass
import logging
from threading import Lock
from typing import Any, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    page_number: Optional[int]
    chunk_type: str
    content: str
    metadata_json: dict
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None


class RerankerService:
    """Singleton cross-encoder reranker for high-precision semantic scoring."""

    _instance: Optional["RerankerService"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "RerankerService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self.model_name = settings.RAG_RERANKER_MODEL
        self.min_score = settings.RAG_RERANKER_MIN_SCORE
        self._model = None
        self._model_lock = Lock()
        self._initialized = True
        logger.info("RerankerService initialized (target model: %s)", self.model_name)

    def _get_model(self):
        """Lazy thread-safe loading of CrossEncoder model."""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("Loading CrossEncoder model '%s'...", self.model_name)
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.model_name)
                    logger.info("CrossEncoder model '%s' loaded successfully.", self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        top_k: int = 5,
        min_score: Optional[float] = None,
    ) -> List[RetrievedChunk]:
        """Rerank candidates using cross-encoder query-chunk pair scoring."""
        if not candidates:
            return []

        if not query or not query.strip():
            return candidates[:top_k]

        threshold = min_score if min_score is not None else self.min_score
        model = self._get_model()

        pairs = [[query.strip(), c.content] for c in candidates]
        scores = model.predict(pairs)

        for chunk, score in zip(candidates, scores):
            chunk.rerank_score = float(score)

        # Sort descending by reranker score
        sorted_candidates = sorted(candidates, key=lambda x: x.rerank_score or -999.0, reverse=True)

        # Filter out candidates below the noise threshold (if any score above threshold)
        filtered = [c for c in sorted_candidates if (c.rerank_score or -999.0) >= threshold]

        # If threshold filtered everything out, keep at least the top candidate to prevent empty context
        if not filtered and sorted_candidates:
            filtered = [sorted_candidates[0]]

        return filtered[:top_k]


_reranker_service: Optional[RerankerService] = None


def get_reranker_service() -> RerankerService:
    """Dependency / accessor for RerankerService singleton."""
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service
