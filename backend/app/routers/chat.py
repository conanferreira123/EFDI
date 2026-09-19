"""Document-Level Conversational RAG Router.

Provides conversational chat scoped strictly to a single document:
- POST /api/v1/chat/documents/{document_id}/messages
- GET /api/v1/chat/documents/{document_id}/history
- DELETE /api/v1/chat/documents/{document_id}/history
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.chat import (
    ChatHistoryClearResponse,
    ChatHistoryItem,
    ChatMessageRequest,
    ChatMessageResponse,
)
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Conversational AI - Document Chat"])


@router.post(
    "/documents/{document_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Send message to Document Assistant",
    description="Submit a question regarding clauses, discounts, freight, penalties, or payment terms for a single document.",
)
def send_document_message(
    document_id: int,
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    return service.send_document_message(
        document_id=document_id,
        user_message=payload.message,
        user=current_user,
    )


@router.get(
    "/documents/{document_id}/history",
    response_model=List[ChatHistoryItem],
    status_code=status.HTTP_200_OK,
    summary="Get Document Assistant chat history",
    description="Retrieve chronological conversation history between the current user and the document assistant.",
)
def get_document_history(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    return service.get_document_history(
        document_id=document_id,
        user=current_user,
    )


@router.delete(
    "/documents/{document_id}/history",
    response_model=ChatHistoryClearResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear Document Assistant chat history",
    description="Reset the conversation history for this document.",
)
def clear_document_history(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChatService(db)
    return service.clear_document_history(
        document_id=document_id,
        user=current_user,
    )
