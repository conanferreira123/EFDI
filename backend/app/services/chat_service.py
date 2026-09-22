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

        # 3. Fetch recent conversation history as LangChain messages
        history_messages = self.history_repo.get_langchain_history(session.id, limit=10)

        # 4. Persist user message
        self.history_repo.add_message(
            session_id=session.id,
            role="user",
            content=user_message.strip(),
        )

        # 5. Invoke Document ReAct Agent (strictly scoped to this document, NO SQL tool)
        from app.rag.document_agent import DocumentReActAgent
        agent = DocumentReActAgent(self.db)
        agent_result = agent.run(
            document_id=document.id,
            query=user_message.strip(),
            user=user,
            history=history_messages,
        )

        # 6. Persist assistant response with citations and tool metadata
        assistant_msg = self.history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=agent_result.content,
            tool_calls=agent_result.tool_calls,
            citations=agent_result.citations,
        )
        self.db.commit()

        return {
            "session_id": session.id,
            "message_id": assistant_msg.id,
            "role": "assistant",
            "content": agent_result.content,
            "citations": agent_result.citations,
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
