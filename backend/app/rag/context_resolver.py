"""Conversation Context Resolver for EFDI Chatbots.

Resolves conversational references, affirmations, negations, anaphora, and
ordinal references (e.g. "yes", "no", "the second item", "what about that?")
into explicit, standalone user queries before agent tool routing.
"""
from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.rag.agent_llm import get_agent_llm

logger = logging.getLogger(__name__)


@dataclass
class ContextResolutionResult:
    """Outcome of conversation reference resolution."""
    raw_query: str
    contextualized_query: str
    was_resolved: bool
    is_ambiguous: bool = False
    clarification_prompt: Optional[str] = None
    action_type: str = "query"  # "query", "confirmation_affirmative", "confirmation_negative", "clarification"


CONTEXT_RESOLVER_SYSTEM_PROMPT = """You are the EFDI Conversation Context Resolver.
Your job is to rewrite ambiguous, affirmative, elliptical, or reference-dependent user messages into an explicit, standalone query using the provided conversation history.

OPERATIONAL RULES:
1. ONLY resolve references (e.g., "second item", "that vendor", "it", "that one") using entities EXPLICITLY present in the conversation history.
2. DO NOT invent or assume facts, names, or numbers that do not appear in the history.
3. If the user message is an affirmative response (e.g. "yes", "sure", "please do") to a question or offer in the last assistant turn, rewrite the query into an explicit imperative instruction to perform that offered action.
4. If the user message has NO clear antecedent or is completely ambiguous (e.g., "what about that?" with no prior entity), respond with:
   AMBIGUOUS: <brief reason>
5. DO NOT answer the question. Only output the rewritten standalone query or the AMBIGUOUS marker.
"""


class ConversationContextResolver:
    """Disambiguates conversational references before agent execution."""

    # Words that strongly indicate standalone, self-contained questions
    STANDALONE_INTERROGATIVES = {"what is", "what are", "who is", "who are", "list all", "show all", "verify the", "calculate", "how many"}

    # Reference indicators that require contextualization
    REFERENCE_TRIGGERS = {
        "yes", "yeah", "yep", "sure", "ok", "okay", "please", "please do", "confirm", "proceed",
        "no", "nope", "cancel", "dont", "don't", "no thanks",
        "that", "it", "they", "them", "those", "this", "these",
        "second", "third", "first", "last", "previous", "other",
        "why", "why?", "how come", "is that correct", "what about",
    }

    def __init__(self, llm: Optional[Any] = None, llm_client: Optional[Any] = None) -> None:
        self._llm = llm or llm_client

    def _get_llm(self):
        return self._llm or get_agent_llm(temperature=0.0, max_tokens=256)

    def is_standalone(self, query: str, history_len: int) -> bool:
        """Fast deterministic check to bypass LLM when query is already standalone."""
        if history_len == 0:
            return True

        clean = query.strip().lower()
        tokens = set(re.findall(r"\b[a-z0-9\']+\b", clean))

        # If any reference trigger word is present, it's not standalone
        if tokens & self.REFERENCE_TRIGGERS:
            return False

        # If query starts with "what about" or contains ordinal words
        if clean.startswith("what about") or clean.startswith("how about"):
            return False

        # If query is reasonably long (>= 5 words) and starts with a clear interrogative
        words = clean.split()
        if len(words) >= 5:
            if any(clean.startswith(prefix) for prefix in self.STANDALONE_INTERROGATIVES):
                return True

        # Very short queries (< 4 words) without explicit nouns are usually context-dependent
        if len(words) < 4 and not any(w in clean for w in ["invoice", "vendor", "total", "amount", "date", "status"]):
            return False

        return True

    def resolve(
        self,
        current_message: Optional[str] = None,
        recent_history: Optional[Sequence[Any]] = None,
        session_state: Optional[Dict[str, Any]] = None,
        query: Optional[str] = None,
        history: Optional[Sequence[Any]] = None,
    ) -> ContextResolutionResult:
        """Resolve conversational references in current_message using history and state."""
        clean_query = (current_message if current_message is not None else (query or "")).strip()
        hist = recent_history if recent_history is not None else (history or [])
        state = session_state or {}

        # 1. Check if history is empty
        if not hist:
            return ContextResolutionResult(
                raw_query=clean_query,
                contextualized_query=clean_query,
                was_resolved=False,
            )

        clean_lower = clean_query.lower()
        words = clean_lower.split()

        # 2. Extract immediate preceding assistant message (if any)
        last_assistant_msg = ""
        for m in reversed(hist):
            role = getattr(m, "role", None)
            if role == "assistant":
                last_assistant_msg = getattr(m, "content", "")
                break
            elif isinstance(m, AIMessage):
                last_assistant_msg = m.content
                break

        # Check for pending offer in session_state or last assistant message
        pending_offer = state.get("pending_offer")
        if not pending_offer and last_assistant_msg:
            pending_offer = self.extract_pending_offer(last_assistant_msg)

        # 3. Handle Affirmative Confirmations ("yes", "sure", "please do", etc.)
        affirmative_tokens = {"yes", "yep", "yeah", "sure", "ok", "okay", "please", "please do", "confirm", "proceed", "go ahead"}
        if clean_lower in affirmative_tokens or (len(words) <= 3 and any(w in affirmative_tokens for w in words)):
            if pending_offer and pending_offer.get("action_query"):
                return ContextResolutionResult(
                    raw_query=clean_query,
                    contextualized_query=pending_offer["action_query"],
                    was_resolved=True,
                    action_type="confirmation_affirmative",
                )
            elif last_assistant_msg and ("check" in last_assistant_msg.lower() or "look" in last_assistant_msg.lower()):
                # Fallback extraction from assistant message
                if "payment" in last_assistant_msg.lower() or "terms" in last_assistant_msg.lower():
                    resolved = "Check the document for other payment-related terms such as payment terms, early settlement discounts, due dates, or contractual penalties."
                else:
                    resolved = f"Proceed with checking the details mentioned in: '{last_assistant_msg[:120]}'"
                return ContextResolutionResult(
                    raw_query=clean_query,
                    contextualized_query=resolved,
                    was_resolved=True,
                    action_type="confirmation_affirmative",
                )

        # 4. Handle Negative Confirmations ("no", "nope", "cancel", etc.)
        negative_tokens = {"no", "nope", "cancel", "dont", "don't", "no thanks", "stop"}
        if clean_lower in negative_tokens or (len(words) <= 3 and any(w in negative_tokens for w in words)):
            return ContextResolutionResult(
                raw_query=clean_query,
                contextualized_query="The user declined the offer. Acknowledge politely without calling retrieval tools.",
                was_resolved=True,
                action_type="confirmation_negative",
            )

        # 5. Check if query is already standalone
        if self.is_standalone(clean_query, len(hist)):
            return ContextResolutionResult(
                raw_query=clean_query,
                contextualized_query=clean_query,
                was_resolved=False,
            )

        # 6. For complex anaphora / ordinal / reference queries, invoke lightweight LLM
        return self._resolve_via_llm(clean_query, hist, pending_offer)

    def _resolve_via_llm(
        self,
        query: str,
        history: Sequence[Any],
        pending_offer: Optional[Dict[str, Any]],
    ) -> ContextResolutionResult:
        """Use ChatMistralAI to disambiguate references against recent history."""
        # Format recent history into clean readable turns (last 4 turns)
        history_lines = []
        for m in history[-8:]:
            role = getattr(m, "role", None)
            content = getattr(m, "content", "")
            if not role:
                role = "user" if isinstance(m, HumanMessage) else "assistant"
            history_lines.append(f"{role.upper()}: {content.strip()}")

        history_str = "\n".join(history_lines)
        user_prompt = (
            f"Conversation History:\n{history_str}\n\n"
            f"Incoming User Message: {query}\n\n"
            f"Rewritten Standalone Query:"
        )

        try:
            llm = self._get_llm()
            messages = [
                SystemMessage(content=CONTEXT_RESOLVER_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
            resp = llm.invoke(messages)
            rewritten = resp.content if isinstance(resp.content, str) else str(resp.content)
            rewritten = rewritten.strip()

            if rewritten.startswith("AMBIGUOUS:"):
                reason = rewritten.replace("AMBIGUOUS:", "").strip()
                return ContextResolutionResult(
                    raw_query=query,
                    contextualized_query=query,
                    was_resolved=True,
                    is_ambiguous=True,
                    clarification_prompt=f"Could you please clarify your request? {reason}",
                    action_type="clarification",
                )

            logger.info("[ContextResolver] Rewrote %r -> %r", query, rewritten)
            return ContextResolutionResult(
                raw_query=query,
                contextualized_query=rewritten,
                was_resolved=True,
                action_type="query",
            )
        except Exception as e:
            logger.warning("[ContextResolver] LLM resolution failed: %s; falling back to raw query", e)
            return ContextResolutionResult(
                raw_query=query,
                contextualized_query=query,
                was_resolved=False,
            )

    @classmethod
    def extract_pending_offer(cls, assistant_text: str) -> Optional[Dict[str, Any]]:
        """Inspect assistant text for explicit offer questions expecting user confirmation."""
        if not assistant_text or "?" not in assistant_text:
            return None

        # Look for typical offer phrases: "Would you like me to check...", "Shall I verify...", etc.
        patterns = [
            r"would you like (?:me to )?check (?:for )?(any other )?([^?]+)\?",
            r"should i (?:check|look for|verify) ([^?]+)\?",
            r"shall i (?:check|look for|verify) ([^?]+)\?",
        ]

        text_lower = assistant_text.lower()
        for p in patterns:
            match = re.search(p, text_lower)
            if match:
                target = match.group(match.lastindex).strip()
                if "payment" in target or "term" in target:
                    action_query = "Check the document for other payment-related terms such as payment terms, early settlement discounts, due dates, or contractual penalties."
                else:
                    action_query = f"Check the document for {target}."

                return {
                    "type": "offer",
                    "offer_text": target,
                    "action_query": action_query,
                    "original_question": assistant_text[match.start():match.end()],
                }

        return None
