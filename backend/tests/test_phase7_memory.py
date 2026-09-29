"""Phase 7 Unit Tests: Conversation Context and Tool Memory Rehydration.

Tests get_langchain_history reconstruction of AIMessage with tool_calls and ToolMessages.
"""
import pytest
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.database.session import get_db_context
from app.models.chat import ChatSession, ChatMessage
from app.models.roles import UserRole
from app.models.user import User
from app.repositories.chat_history_repository import ChatHistoryRepository


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


def test_tool_memory_rehydration(db_session: Session):
    repo = ChatHistoryRepository(db_session)

    # Create dummy user and session
    import uuid
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"mem_user_{suffix}",
        email=f"mem_user_{suffix}@example.com",
        full_name="Memory User",
        password_hash="secret",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    session = repo.get_or_create_global_session(user_id=user.id, title="Tool Memory Test")

    # Turn 1: User asks question
    repo.add_message(session_id=session.id, role="user", content="Show overdue invoices")

    # Turn 1 Assistant response with tool_calls
    tool_logs = [
        {
            "tool": "database_query_tool",
            "query": "SELECT document_id, grand_total_amount FROM invoices WHERE status = 'PENDING_APPROVAL'",
            "row_count": 2,
            "rows": [
                {"document_id": 101, "grand_total_amount": "5000.00"},
                {"document_id": 102, "grand_total_amount": "12000.00"},
            ],
            "candidate_document_ids": [101, 102],
            "summary": "Found 2 pending invoices",
        }
    ]
    repo.add_message(
        session_id=session.id,
        role="assistant",
        content="I found 2 pending invoices: Doc #101 and Doc #102.",
        tool_calls=tool_logs,
    )

    # Fetch LangChain history
    lc_history = repo.get_langchain_history(session_id=session.id)
    assert len(lc_history) == 3  # HumanMessage, AIMessage, ToolMessage

    assert isinstance(lc_history[0], HumanMessage)
    assert lc_history[0].content == "Show overdue invoices"

    assert isinstance(lc_history[1], AIMessage)
    assert lc_history[1].tool_calls is not None
    assert len(lc_history[1].tool_calls) == 1
    assert lc_history[1].tool_calls[0]["name"] == "database_query_tool"

    assert isinstance(lc_history[2], ToolMessage)
    assert "101" in lc_history[2].content
    assert "102" in lc_history[2].content
