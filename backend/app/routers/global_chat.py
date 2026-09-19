"""Global Multi-Tool Conversational Agent Router.

Provides portfolio-wide conversational capabilities:
- POST /api/v1/chat/corpus/messages
- GET /api/v1/chat/corpus/history
- DELETE /api/v1/chat/corpus/history
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.rag.agent_orchestrator import AgentOrchestrator
from app.repositories.chat_history_repository import ChatHistoryRepository
from app.schemas.chat import (
    ChatHistoryClearResponse,
    ChatHistoryItem,
    ChatMessageRequest,
    GlobalChatMessageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/corpus", tags=["Conversational AI - Global Multi-Tool Agent"])


@router.post(
    "/messages",
    response_model=GlobalChatMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit query to Global Multi-Tool Agent",
    description="Submit portfolio-wide questions coordinating Database SQL Query, Financial Calculator, and Document RAG tools.",
)
def send_global_message(
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    orchestrator = AgentOrchestrator(db)
    return orchestrator.process_global_query(
        query=payload.message,
        user=current_user,
    )


@router.get(
    "/history",
    response_model=List[ChatHistoryItem],
    status_code=status.HTTP_200_OK,
    summary="Get Global Assistant chat history",
    description="Retrieve recent turns in the portfolio-wide global conversation.",
)
def get_global_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    history_repo = ChatHistoryRepository(db)
    session = history_repo.get_or_create_global_session(user_id=current_user.id)
    messages = history_repo.get_session_history(session.id)

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


@router.delete(
    "/history",
    response_model=ChatHistoryClearResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear Global Assistant chat history",
    description="Reset the portfolio-wide conversation history.",
)
def clear_global_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    history_repo = ChatHistoryRepository(db)
    session = history_repo.get_or_create_global_session(user_id=current_user.id)
    deleted_count = history_repo.clear_session_history(session.id)
    db.commit()

    return {
        "status": "cleared",
        "document_id": None,
        "session_id": session.id,
        "deleted_messages": deleted_count,
    }
