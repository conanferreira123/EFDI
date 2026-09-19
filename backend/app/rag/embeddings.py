"""Embedding Service for EFDI Conversational RAG.

Uses sentence-transformers/all-MiniLM-L6-v2 (384 dimensions) with singleton
model loading, thread safety, and batch processing.
"""
import logging
from threading import Lock
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Singleton service for generating 384-dimensional dense embeddings."""

    _instance: Optional["EmbeddingService"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "EmbeddingService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self.model_name = settings.RAG_EMBEDDING_MODEL
        self.embedding_dim = settings.RAG_EMBEDDING_DIM
        self._model = None
        self._model_lock = Lock()
        self._initialized = True
        logger.info("EmbeddingService initialized (target model: %s, dim: %d)", self.model_name, self.embedding_dim)

    def _get_model(self):
        """Lazy thread-safe model loading."""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("Loading sentence-transformers model '%s'...", self.model_name)
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
                    logger.info("SentenceTransformer model '%s' loaded successfully.", self.model_name)
        return self._model

    def generate_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generate 384-dim embeddings for a batch of text chunks.

        Note: Metadata must NOT be included in the text passed here.
        """
        if not texts:
            return []

        model = self._get_model()
        # SentenceTransformer.encode returns numpy ndarray
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        result: List[List[float]] = []
        for emb in embeddings:
            vec = emb.tolist()
            if len(vec) != self.embedding_dim:
                raise ValueError(
                    f"Generated embedding dim {len(vec)} does not match required dim {self.embedding_dim}"
                )
            result.append(vec)

        return result

    def generate_query_embedding(self, query: str) -> List[float]:
        """Generate normalized embedding for a single search query."""
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty for embedding generation")

        results = self.generate_embeddings([query.strip()])
        return results[0]


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Dependency / accessor for EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
