"""Chat models for Document-Level and Global Assistant conversations.

Stores chat sessions and conversation turns (messages, tool calls, citations).
"""
from typing import List, Optional
from sqlalchemy import ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DOCUMENT", index=True
    )  # "DOCUMENT" or "GLOBAL"
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    user = relationship("User", lazy="joined")
    document = relationship("Document", lazy="joined")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<ChatSession id={self.id} user_id={self.user_id} "
            f"type={self.session_type} doc={self.document_id}>"
        )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict | list]] = mapped_column(JSONB, nullable=True)
    citations: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} session_id={self.session_id} role={self.role}>"
