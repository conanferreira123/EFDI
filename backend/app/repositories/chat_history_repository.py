"""Chat History Repository.

Persists and retrieves chat sessions, user/assistant conversation turns,
tool calls, and citations.
"""
from typing import List, Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession


class ChatHistoryRepository:
    """Data access repository for ChatSession and ChatMessage entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create_document_session(self, user_id: int, document_id: int) -> ChatSession:
        """Get existing session for this user and document, or create a new one."""
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.document_id == document_id,
                ChatSession.session_type == "DOCUMENT",
            )
            .order_by(ChatSession.created_at.desc())
        )
        session = self.db.scalars(stmt).first()
        if not session:
            session = ChatSession(
                user_id=user_id,
                document_id=document_id,
                session_type="DOCUMENT",
                title=f"Document {document_id} Assistant",
            )
            self.db.add(session)
            self.db.flush()
        return session

    def get_or_create_global_session(
        self, user_id: int, title: Optional[str] = None
    ) -> ChatSession:
        """Get or create a portfolio-wide global chat session."""
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.session_type == "GLOBAL",
            )
            .order_by(ChatSession.updated_at.desc())
        )
        session = self.db.scalars(stmt).first()
        if not session:
            session = ChatSession(
                user_id=user_id,
                document_id=None,
                session_type="GLOBAL",
                title=title or "Global Financial Assistant",
            )
            self.db.add(session)
            self.db.flush()
        return session

    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        tool_calls: Optional[dict | list] = None,
        citations: Optional[list] = None,
    ) -> ChatMessage:
        """Append a message turn to the chat session."""
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            citations=citations,
        )
        self.db.add(msg)
        self.db.flush()
        return msg

    def get_session_history(self, session_id: int, limit: int = 50) -> List[ChatMessage]:
        """Fetch chronological message history for a session (most recent N turns).

        Queries the newest `limit` messages ordered by `created_at DESC, id DESC`,
        and reverses them in Python so callers receive chronological order
        (oldest -> newest) while ensuring the window tracks the latest turns.
        """
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        newest_desc = list(self.db.scalars(stmt).all())
        return list(reversed(newest_desc))

    def get_session_state(self, session_id: int) -> dict:
        """Fetch current structured conversation state for a session."""
        stmt = select(ChatSession.state_json).where(ChatSession.id == session_id)
        result = self.db.scalar(stmt)
        return result or {}

    def update_session_state(self, session_id: int, state_updates: dict) -> dict:
        """Merge updates into the structured conversation state for a session."""
        session = self.db.get(ChatSession, session_id)
        if not session:
            return {}
        current_state = dict(session.state_json or {})
        current_state.update(state_updates)
        session.state_json = current_state
        self.db.flush()
        return current_state

    def clear_session_history(self, session_id: int) -> int:
        """Delete all messages belonging to a chat session."""
        stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
        result = self.db.execute(stmt)
        # Also reset session state
        session = self.db.get(ChatSession, session_id)
        if session:
            session.state_json = {}
            self.db.flush()
        return result.rowcount

    def get_langchain_history(self, session_id: int, limit: int = 10) -> list:
        """Fetch recent conversation turns converted to LangChain BaseMessage instances."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        raw_messages = self.get_session_history(session_id=session_id, limit=limit)
        lc_messages = []
        for m in raw_messages:
            if m.role == "user" and m.content:
                lc_messages.append(HumanMessage(content=m.content))
            elif m.role == "assistant" and m.content:
                extra = {
                    "tool_calls": m.tool_calls or [],
                    "has_verified_tool_evidence": bool(m.tool_calls),
                }
                lc_messages.append(AIMessage(content=m.content, additional_kwargs=extra))
            elif m.role == "system" and m.content:
                lc_messages.append(SystemMessage(content=m.content))
        return lc_messages


