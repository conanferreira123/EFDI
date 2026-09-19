"""Chat Service for Document-Level and Global Assistant conversations.

Orchestrates session state, hybrid retrieval, strict grounding, citation generation,
and audit logging.
"""
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.rag.llm_client import get_llm_client
from app.repositories.chat_history_repository import ChatHistoryRepository
from app.services.document_service import DocumentService
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


class ChatService:
    """Coordinates conversational workflows, document authorization, and LLM grounding."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.doc_service = DocumentService(db)
        self.rag_service = RAGService(db)
        self.history_repo = ChatHistoryRepository(db)
        self.llm_client = get_llm_client()

    def send_document_message(
        self,
        document_id: int,
        user_message: str,
        user: User,
    ) -> Dict[str, Any]:
        """Process a user query scoped to a single document with strict authorization."""
        # 1. Verify user has permission to access this document
        document = self.doc_service.get_for_user(document_id, user)

        # 2. Get or create session
        session = self.history_repo.get_or_create_document_session(
            user_id=user.id, document_id=document.id
        )

        # 3. Persist user message
        self.history_repo.add_message(
            session_id=session.id,
            role="user",
            content=user_message.strip(),
        )

        # 4. Fetch recent conversation history
        history_msgs = self.history_repo.get_session_history(session.id, limit=10)
        history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

        # 5. Execute hybrid retrieval scoped strictly to this document
        retrieved_chunks = self.rag_service.retrieve_for_document(
            document_id=document.id,
            query=user_message.strip(),
            user=user,
        )

        # 6. Generate grounded answer via Mistral
        answer = self.llm_client.generate_grounded_answer(
            query=user_message.strip(),
            retrieved_chunks=retrieved_chunks,
            conversation_history=history,
        )

        # 7. Construct structured citations
        citations = []
        for c in retrieved_chunks:
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "page_number": c.page_number or 1,
                "chunk_type": c.chunk_type,
                "snippet": c.content.strip()[:300],
                "bounding_box_refs": c.metadata_json.get("bounding_box_refs", []),
                "rerank_score": c.rerank_score,
            })

        # 8. Persist assistant response
        assistant_msg = self.history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
        )
        self.db.commit()

        return {
            "session_id": session.id,
            "message_id": assistant_msg.id,
            "role": "assistant",
            "content": answer,
            "citations": citations,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else datetime.now(timezone.utc).isoformat(),
        }

    def get_document_history(
        self,
        document_id: int,
        user: User,
    ) -> List[Dict[str, Any]]:
        """Retrieve conversation history for a document chat session."""
        document = self.doc_service.get_for_user(document_id, user)
        session = self.history_repo.get_or_create_document_session(
            user_id=user.id, document_id=document.id
        )
        messages = self.history_repo.get_session_history(session.id)

        return [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]

    def clear_document_history(
        self,
        document_id: int,
        user: User,
    ) -> Dict[str, Any]:
        """Clear conversation history for a document chat session."""
        document = self.doc_service.get_for_user(document_id, user)
        session = self.history_repo.get_or_create_document_session(
            user_id=user.id, document_id=document.id
        )
        deleted_count = self.history_repo.clear_session_history(session.id)
        self.db.commit()

        return {
            "status": "cleared",
            "document_id": document.id,
            "session_id": session.id,
            "deleted_messages": deleted_count,
        }
