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

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.rag.context_resolver import ConversationContextResolver
from app.rag.global_agent import GlobalReActAgent
from app.rag.llm_client import get_llm_client
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
    history_repo = ChatHistoryRepository(db)
    session = history_repo.get_or_create_global_session(user_id=current_user.id)

    # 1. Fetch recent conversation context (bounded sliding window)
    history_messages = history_repo.get_langchain_history(
        session.id, limit=settings.CHAT_HISTORY_LIMIT
    )

    # 2. Fetch structured conversation state
    session_state = history_repo.get_session_state(session.id)

    # 3. Persist incoming user message
    user_msg = history_repo.add_message(
        session_id=session.id,
        role="user",
        content=payload.message.strip(),
    )

    # 4. Conversational Context Resolution
    resolver = ConversationContextResolver(llm_client=get_llm_client())
    resolution = resolver.resolve(
        query=payload.message.strip(),
        history=history_messages,
        session_state=session_state,
    )

    # 4a. Negative Confirmation Handling: no tool execution required
    if resolution.action_type == "confirmation_negative":
        session_state["pending_offer"] = None
        history_repo.update_session_state(session.id, session_state)
        ack_content = (
            "Understood. Let me know if you would like me to assist with any other "
            "financial analysis, database queries, or documents."
        )
        assistant_msg = history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=ack_content,
            tool_calls=[],
            citations=[],
        )
        db.commit()
        return GlobalChatMessageResponse(
            session_id=session.id,
            message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            role="assistant",
            content=ack_content,
            tool_calls=[],
            citations=[],
            created_at=assistant_msg.created_at.isoformat() if assistant_msg.created_at else "",
            execution_time_ms=0,
        )

    # 4b. Ambiguous Reference Handling: request clarification without fabricating evidence
    if resolution.is_ambiguous or resolution.action_type == "clarification":
        clarification_content = (
            resolution.contextualized_query
            or "Could you please clarify what document, metric, or entity you are referring to?"
        )
        assistant_msg = history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=clarification_content,
            tool_calls=[],
            citations=[],
        )
        db.commit()
        return GlobalChatMessageResponse(
            session_id=session.id,
            message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            role="assistant",
            content=clarification_content,
            tool_calls=[],
            citations=[],
            created_at=assistant_msg.created_at.isoformat() if assistant_msg.created_at else "",
            execution_time_ms=0,
        )

    effective_query = resolution.contextualized_query

    # 5. Invoke Global ReAct Agent
    agent = GlobalReActAgent(db)
    agent_result = agent.run(
        query=effective_query,
        user=current_user,
        history=history_messages,
    )

    # 6. Update Structured State Lifecycle
    if resolution.action_type == "confirmation_affirmative":
        session_state["pending_offer"] = None

    new_offer = resolver.extract_pending_offer(agent_result.content)
    session_state["pending_offer"] = new_offer

    if agent_result.tool_calls:
        verified = session_state.get("verified_facts", [])
        for tc in agent_result.tool_calls:
            tool_name = tc.get("tool") or tc.get("name")
            if tool_name:
                verified.append({"tool": tool_name, "query": tc.get("query") or tc.get("input")})
        session_state["verified_facts"] = verified[-10:]

    history_repo.update_session_state(session.id, session_state)

    # 7. Persist assistant turn with tool execution logs and citations
    assistant_msg = history_repo.add_message(
        session_id=session.id,
        role="assistant",
        content=agent_result.content,
        tool_calls=agent_result.tool_calls,
        citations=agent_result.citations,
    )
    db.commit()

    return GlobalChatMessageResponse(
        session_id=session.id,
        message_id=assistant_msg.id,
        user_message_id=user_msg.id,
        role="assistant",
        content=agent_result.content,
        tool_calls=agent_result.tool_calls,
        citations=agent_result.citations,
        created_at=assistant_msg.created_at.isoformat() if assistant_msg.created_at else "",
        execution_time_ms=agent_result.execution_time_ms,
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
