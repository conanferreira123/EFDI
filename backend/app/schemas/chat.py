"""Pydantic schemas for Conversational RAG and Chat endpoints.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="User question or prompt")


class CitationItem(BaseModel):
    chunk_id: int
    document_id: Optional[int] = None
    page_number: int
    chunk_type: str
    snippet: str
    bounding_box_refs: List[Dict[str, Any]] = Field(default_factory=list)
    rerank_score: Optional[float] = None


class ChatMessageResponse(BaseModel):
    session_id: int
    message_id: int
    user_message_id: Optional[int] = None
    role: str
    content: str
    citations: List[CitationItem] = Field(default_factory=list)
    created_at: str


class GlobalChatMessageResponse(BaseModel):
    session_id: int
    message_id: int
    user_message_id: Optional[int] = None
    role: str
    content: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[CitationItem] = Field(default_factory=list)
    relational_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    calculation_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str
    execution_time_ms: Optional[float] = None


class ChatHistoryItem(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    citations: List[CitationItem] = Field(default_factory=list)
    relational_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    calculation_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None


class ChatHistoryClearResponse(BaseModel):
    status: str
    document_id: Optional[int] = None
    session_id: int
    deleted_messages: int
