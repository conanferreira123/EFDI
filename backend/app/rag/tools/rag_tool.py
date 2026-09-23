"""Document RAG Tool Adapter for Global and Document ReAct Agents.

Wraps RAGService as a LangChain BaseTool, enforcing backend injection of
trusted current_user and document scoping.
"""
import logging
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langchain_core.tools import BaseTool

from app.models.user import User
from app.rag.reranker import RetrievedChunk
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


class GlobalRAGInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Semantic search query to retrieve unstructured clauses, payment terms, Incoterms, "
            "dispute conditions, penalties, or OCR text snippets across authorized documents."
        ),
    )
    document_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional list of specific document IDs to focus retrieval on.",
    )


class DocumentRAGInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Semantic search query to retrieve unstructured clauses, payment terms, Incoterms, "
            "freight, dispute conditions, or OCR text snippets from this specific document."
        ),
    )


class DocumentRAGTool(BaseTool):
    name: str = "document_rag_tool"
    description: str = (
        "Retrieve unstructured document clauses, contractual text, Incoterms, payment conditions, "
        "early settlement discount clauses, penalty terms, and OCR snippets from financial documents. "
        "Use this tool when answering questions about clauses, terms, or textual content."
    )
    args_schema: Type[BaseModel] = GlobalRAGInput

    db: Any = Field(exclude=True)
    user: Any = Field(exclude=True)
    enforced_document_id: Optional[int] = Field(default=None, exclude=True)
    retrieved_chunks: List[RetrievedChunk] = Field(default_factory=list, exclude=True)
    execution_logs: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)

    def _run(self, query: str, document_ids: Optional[List[int]] = None) -> str:
        """Execute hybrid RAG retrieval under backend-enforced authorization."""
        service = RAGService(self.db)
        try:
            if self.enforced_document_id is not None:
                # Defense-in-depth: ensure document has completed OCR
                from app.models.document import Document
                from app.models.document_enums import DocumentStatus
                from app.repositories.ocr_result_repository import OCRResultRepository
                doc = self.db.get(Document, self.enforced_document_id)
                if doc and doc.status == DocumentStatus.UPLOADED.value and OCRResultRepository(self.db).get_latest_for_document(self.enforced_document_id) is None:
                    return f"Document RAG Results: OCR has not been run for Document #{self.enforced_document_id} yet."

                # Document Chat: strictly scoped to the enforced document_id
                chunks = service.retrieve_for_document(
                    document_id=self.enforced_document_id,
                    query=query,
                    user=self.user,
                    top_k=5,
                )
                scope_info = f"Document #{self.enforced_document_id}"
                scoped_ids = [self.enforced_document_id]
            else:
                # Global Chat: authorized portfolio search with optional hint filter
                chunks = service.retrieve_global(
                    query=query,
                    user=self.user,
                    document_ids=document_ids,
                    top_k=5,
                )
                scope_info = f"Document IDs {document_ids}" if document_ids else "Authorized Portfolio"
                scoped_ids = document_ids

            # Accumulate retrieved chunks for citation building
            self.retrieved_chunks.extend(chunks)

            self.execution_logs.append({
                "tool": "document_rag_tool",
                "retrieved_count": len(chunks),
                "scoped_documents": scoped_ids,
                "summary": f"Retrieved {len(chunks)} evidence chunk(s) from {scope_info}",
            })

            if not chunks:
                return f"Document RAG Results: No matching text chunks found in {scope_info}."

            evidence_blocks = []
            for c in chunks:
                header = f"[Doc #{c.document_id}, Chunk {c.chunk_id}, Page {c.page_number or 1} - {c.chunk_type}]"
                evidence_blocks.append(f"{header}\n{c.content.strip()}")

            return f"Retrieved Document Evidence ({len(chunks)} chunks from {scope_info}):\n\n" + "\n---\n".join(evidence_blocks)
        except Exception as err:
            logger.error("[DocumentRAGTool] Retrieval error: %s", err, exc_info=True)
            self.execution_logs.append({
                "tool": "document_rag_tool",
                "status": "error",
                "error": str(err),
            })
            return f"Document RAG Retrieval Error: {err}"
