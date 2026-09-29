"""Chat Service for Document-Level and Global Assistant conversations.

Orchestrates session state, hybrid retrieval, strict grounding, citation generation,
and audit logging.
"""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.user import User
from app.rag.agent_result import AgentResult
from app.rag.context_resolver import ConversationContextResolver
from app.rag.llm_client import get_llm_client
from app.rag.response_guardrails import GLOBAL_TIMEOUT_MESSAGE
from app.repositories.chat_history_repository import ChatHistoryRepository
from app.repositories.ocr_result_repository import OCRResultRepository
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
        self.ocr_repo = OCRResultRepository(db)
        self.llm_client = get_llm_client()

    def _is_ocr_completed(self, document: Document) -> bool:
        """Check if OCR has completed authoritatively for the document."""
        if document.status and document.status != DocumentStatus.UPLOADED.value:
            return True
        return self.ocr_repo.get_latest_for_document(document.id) is not None

    def _is_document_content_query(self, query: str) -> bool:
        """Determine if a query requires internal document content vs standalone calculation.

        In Document Chat, only standalone deterministic calculations (e.g. 'Calculate 150000 * (1 - 0.025)')
        do not require document content. All inquiries about document text, clauses, metadata,
        amounts, or entities require document OCR to be completed.
        """
        clean_query = query.strip().lower()

        # Check for document-specific context keywords
        doc_keywords = {
            "document", "doc", "invoice", "bill", "receipt", "supplier", "vendor",
            "customer", "client", "buyer", "seller", "po", "purchase order",
            "term", "terms", "condition", "clause", "penalty", "penalties",
            "line", "item", "items", "amount", "total", "subtotal", "tax", "vat",
            "date", "due", "about", "summarize", "summary", "content", "contents",
            "text", "mention", "say", "state", "show", "who", "where", "page",
            "incoterm", "discount", "settlement", "bank", "iban", "account",
        }

        tokens = set(re.findall(r"\b[a-z]+\b", clean_query))
        if tokens & doc_keywords:
            return True

        # Pure arithmetic expressions with digits and operators are standalone calculator queries
        has_math_operators = bool(re.search(r"[\+\*\/\^]", clean_query) or re.search(r"\d+\s*[\-]\s*\d+", clean_query))
        has_digits = bool(re.search(r"\d+", clean_query))
        has_calc_word = any(w in tokens for w in {"calculate", "compute", "calc", "math", "evaluate"})

        if (has_calc_word or has_math_operators) and has_digits:
            return False

        return True

    def send_document_message(
        self,
        document_id: int,
        user_message: str,
        user: User,
    ) -> Dict[str, Any]:
        """Process a user query scoped to a single document with strict authorization."""
        request_start_time = time.perf_counter()
        # 1. Verify user has permission to access this document
        document = self.doc_service.get_for_user(document_id, user)
        self.doc_service.record_activity(document.id, user)

        # 2. Get or create session
        session = self.history_repo.get_or_create_document_session(
            user_id=user.id, document_id=document.id
        )

        # 3. Fetch recent conversation history as LangChain messages (bounded sliding window)
        history_messages = self.history_repo.get_langchain_history(
            session.id, limit=settings.CHAT_HISTORY_LIMIT
        )

        # 4. Fetch structured conversation state
        session_state = self.history_repo.get_session_state(session.id)
        if "active_document_id" not in session_state or session_state["active_document_id"] != document.id:
            session_state["active_document_id"] = document.id

        # 5. Persist user message
        user_msg = self.history_repo.add_message(
            session_id=session.id,
            role="user",
            content=user_message.strip(),
        )

        # 6. Conversational Context Resolution
        resolver = ConversationContextResolver(llm_client=self.llm_client)
        resolution = resolver.resolve(
            query=user_message.strip(),
            history=history_messages,
            session_state=session_state,
        )

        # 6a. Negative Confirmation Handling: no RAG or tool execution required
        if resolution.action_type == "confirmation_negative":
            session_state["pending_offer"] = None
            self.history_repo.update_session_state(session.id, session_state)
            ack_content = (
                "Understood. Please let me know if you would like to explore or analyze "
                "anything else regarding this document."
            )
            assistant_msg = self.history_repo.add_message(
                session_id=session.id,
                role="assistant",
                content=ack_content,
                tool_calls=[],
                citations=[],
            )
            self.db.commit()
            return {
                "session_id": session.id,
                "message_id": assistant_msg.id,
                "user_message_id": user_msg.id,
                "role": "assistant",
                "content": ack_content,
                "citations": [],
                "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else datetime.now(timezone.utc).isoformat(),
            }

        # 6b. Ambiguous Reference Handling: request clarification without fabricating evidence
        if resolution.is_ambiguous or resolution.action_type == "clarification":
            clarification_content = (
                resolution.contextualized_query
                or "Could you please clarify what specific detail, section, or item you are referring to?"
            )
            assistant_msg = self.history_repo.add_message(
                session_id=session.id,
                role="assistant",
                content=clarification_content,
                tool_calls=[],
                citations=[],
            )
            self.db.commit()
            return {
                "session_id": session.id,
                "message_id": assistant_msg.id,
                "user_message_id": user_msg.id,
                "role": "assistant",
                "content": clarification_content,
                "citations": [],
                "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else datetime.now(timezone.utc).isoformat(),
            }

        effective_query = resolution.contextualized_query

        # 7. Precondition: OCR Completion Check for Document Content Queries
        if not self._is_ocr_completed(document) and self._is_document_content_query(effective_query):
            ocr_required_content = (
                "OCR has not been run for this document yet. Please run OCR on the "
                "document first, then I can answer questions about its contents."
            )
            assistant_msg = self.history_repo.add_message(
                session_id=session.id,
                role="assistant",
                content=ocr_required_content,
                tool_calls=[],
                citations=[],
            )
            self.db.commit()

            return {
                "session_id": session.id,
                "message_id": assistant_msg.id,
                "user_message_id": user_msg.id,
                "role": "assistant",
                "content": ocr_required_content,
                "citations": [],
                "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else datetime.now(timezone.utc).isoformat(),
            }

        # 8. Invoke Document ReAct Agent (strictly scoped to this document, NO SQL tool)
        from app.rag.document_agent import DocumentReActAgent
        remaining_timeout = max(
            1.0,
            float(getattr(settings, "CHAT_REQUEST_TIMEOUT_SECONDS", 30.0)) - (time.perf_counter() - request_start_time),
        )
        try:
            agent = DocumentReActAgent(self.db)
            agent_result = agent.run(
                document_id=document.id,
                query=effective_query,
                user=user,
                history=history_messages,
                timeout_seconds=remaining_timeout,
            )
        except TimeoutError:
            logger.warning("[DocumentChat] Global request timeout exceeded during agent execution")
            agent_result = AgentResult(
                content=GLOBAL_TIMEOUT_MESSAGE,
                tool_calls=[],
                citations=[],
                execution_time_ms=(time.perf_counter() - request_start_time) * 1000.0,
            )

        # 9. Update Structured State Lifecycle (if not timed out)
        if agent_result.content != GLOBAL_TIMEOUT_MESSAGE:
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

            self.history_repo.update_session_state(session.id, session_state)

        # 10. Persist assistant response with citations and tool metadata
        assistant_msg = self.history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=agent_result.content,
            tool_calls=agent_result.tool_calls if agent_result.content != GLOBAL_TIMEOUT_MESSAGE else [],
            citations=agent_result.citations if agent_result.content != GLOBAL_TIMEOUT_MESSAGE else [],
        )
        self.db.commit()

        return {
            "session_id": session.id,
            "message_id": assistant_msg.id,
            "user_message_id": user_msg.id,
            "role": "assistant",
            "content": agent_result.content,
            "citations": agent_result.citations if agent_result.content != GLOBAL_TIMEOUT_MESSAGE else [],
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
