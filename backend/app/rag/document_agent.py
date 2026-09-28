"""Document ReAct Agent for Scoped Single-Document Inquiries.

Coordinates Document RAG and Financial Calculator tools scoped strictly to a single
document without exposure to the Database / Text-to-SQL tool.
"""
import logging
import re
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.exceptions import AIServiceException
from app.models.user import User
from app.rag.agent_llm import get_agent_llm
from app.rag.agent_result import AgentResult
from app.rag.tools.calculator_tool import FinancialCalculatorTool
from app.rag.tools.rag_tool import DocumentRAGTool

logger = logging.getLogger(__name__)

DOCUMENT_REACT_SYSTEM_PROMPT = """You are the EFDI Document Financial Assistant, an enterprise copilot scoped strictly to a single financial document.
You answer inquiries about line items, payment terms, early payment discounts, freight, penalties, and contractual clauses for this specific document.

You have access to two specialized tools:
1. document_rag_tool: Retrieves textual clauses, payment terms, Incoterms, freight details, penalties, and OCR snippets from this document.
2. financial_calculator_tool: Performs deterministic Decimal arithmetic, settlement discount formulas, and calendar deadline date calculations.

OPERATIONAL GUIDELINES:
- Dynamically select the appropriate tool(s) to answer the user's question about this document.
- For contractual terms, settlement percentages, or clauses, query document_rag_tool.
- For exact discount totals, net payable amounts, or deadline dates, invoke financial_calculator_tool.
- Answer ONLY from verified tool observations. NEVER invent or extrapolate terms or figures.
- When sufficient information has been gathered, provide a concise, professional, grounded final answer citing relevant chunk and page numbers where applicable.

CONVERSATIONAL CONTINUITY & EVIDENCE RULES:
- When the user asks a follow-up or confirms an offer, resolve their intent using the immediate dialogue context.
- Verified tool observations ALWAYS take precedence over historical assistant statements or conversational text.
- If a tool search returns no matching clauses or negative evidence, report clearly that the document was searched and does not contain those terms.
- Do NOT repeatedly query equivalent variations of the same search if previous attempts yielded no relevant clauses.
- Do NOT repeat an offer or question you already extended and executed in the same dialogue thread.
"""

MAX_ITERATIONS = 5


def _is_redundant_query(tool_name: str, query_str: str, executed_queries: Any) -> bool:
    """Check if query_str is substantially duplicate to an already executed query for this tool."""
    if not query_str or not executed_queries:
        return False

    q_lower = query_str.lower().strip()
    stopwords = {"the", "for", "and", "or", "in", "of", "to", "document", "details", "any", "other", "is", "a", "an"}
    words_a = {w for w in re.findall(r"\b[a-z0-9]+\b", q_lower) if len(w) > 2 and w not in stopwords}

    for item in executed_queries:
        if isinstance(item, dict):
            prev_tool = item.get("tool") or item.get("name")
            prev_q = item.get("query") or item.get("input") or ""
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            prev_tool, prev_q = item[0], item[1]
        else:
            continue

        if prev_tool != tool_name:
            continue
        prev_lower = prev_q.lower().strip()
        if q_lower == prev_lower:
            return True
        # For document_rag_tool, check high keyword overlap
        if tool_name == "document_rag_tool":
            words_b = {w for w in re.findall(r"\b[a-z0-9]+\b", prev_lower) if len(w) > 2 and w not in stopwords}
            if words_a and words_b:
                overlap = len(words_a & words_b) / len(words_a | words_b)
                if overlap >= 0.70:
                    return True

    return False


class DocumentReActAgent:
    """Dynamic ReAct Agent scoped strictly to a single document (/api/v1/chat/documents/{id})."""

    _is_redundant_query = staticmethod(_is_redundant_query)

    def __init__(self, db: Session, llm: Optional[Any] = None) -> None:
        self.db = db
        self._llm = llm

    def run(
        self,
        document_id: int,
        query: str,
        user: User,
        history: Optional[List[BaseMessage]] = None,
    ) -> AgentResult:
        """Execute dynamic ReAct tool loop scoped strictly to document_id."""
        start_time = time.perf_counter()

        # 1. Instantiate Scoped Tools (Text-to-SQL is STRICTLY EXCLUDED)
        rag_tool = DocumentRAGTool(
            db=self.db,
            user=user,
            enforced_document_id=document_id,
        )
        calc_tool = FinancialCalculatorTool()

        tools = [rag_tool, calc_tool]
        tool_map = {t.name: t for t in tools}

        # 2. Prepare Chat Model
        llm = self._llm or get_agent_llm()
        llm_with_tools = llm.bind_tools(tools)

        # 3. Construct Message History
        messages: List[BaseMessage] = [SystemMessage(content=DOCUMENT_REACT_SYSTEM_PROMPT)]
        if history:
            messages.extend(history)
        messages.append(HumanMessage(content=query.strip()))

        final_content = ""
        chronological_tool_logs: List[Dict[str, Any]] = []
        executed_tool_queries: List[tuple[str, str]] = []
        should_break_loop = False

        # 4. Iterative ReAct Loop (max 5 iterations)
        for step in range(MAX_ITERATIONS):
            try:
                response = llm_with_tools.invoke(messages)
            except Exception as e:
                logger.error("[DocumentReActAgent] LLM invocation failed at step %d: %s", step, e, exc_info=True)
                raise AIServiceException(
                    "Something went wrong while processing your request. Please try again."
                ) from e

            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                final_content = response.content if isinstance(response.content, str) else str(response.content)
                break

            for tc in tool_calls:
                if len(chronological_tool_logs) >= MAX_ITERATIONS:
                    logger.info("[DocumentReActAgent] Reached maximum allowed tool steps (%d)", MAX_ITERATIONS)
                    should_break_loop = True
                    break

                tool_name = tc.get("name")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id") or f"call_{step}_{tool_name}"
                query_str = str(tool_args.get("query", tool_args.get("expression", ""))).strip()

                target_tool = tool_map.get(tool_name)
                if not target_tool:
                    obs = f"Error: Tool '{tool_name}' is not available for document chat."
                    chronological_tool_logs.append({
                        "tool": tool_name,
                        "status": "error",
                        "error": f"Tool '{tool_name}' is not available for document chat",
                    })
                    messages.append(ToolMessage(content=str(obs), tool_call_id=tool_id))
                    continue

                # Check redundant tool-call loop guard
                if _is_redundant_query(tool_name, query_str, executed_tool_queries):
                    logger.info(
                        "[DocumentReActAgent] Loop guard intercepted redundant call to '%s' with query %r",
                        tool_name,
                        query_str,
                    )
                    obs = (
                        f"Notice: An equivalent search for '{query_str}' has already been executed in this turn. "
                        "No additional matching clauses were found. "
                        "Please synthesize your final grounded answer based on available verified observations."
                    )
                    chronological_tool_logs.append({
                        "tool": tool_name,
                        "summary": f"Suppressed redundant search for: {query_str[:50]}",
                        "status": "redundant_suppressed",
                    })
                    messages.append(ToolMessage(content=obs, tool_call_id=tool_id))
                    should_break_loop = True
                    continue

                executed_tool_queries.append((tool_name, query_str))
                pre_count = len(target_tool.execution_logs)
                try:
                    obs = target_tool.invoke(tool_args)
                except Exception as tool_err:
                    logger.warning("[DocumentReActAgent] Tool '%s' error: %s", tool_name, tool_err)
                    obs = f"Error executing tool '{tool_name}': {tool_err}"

                if len(target_tool.execution_logs) > pre_count:
                    chronological_tool_logs.append(target_tool.execution_logs[-1])
                else:
                    chronological_tool_logs.append({
                        "tool": tool_name,
                        "summary": f"Executed {tool_name}",
                    })

                messages.append(ToolMessage(content=str(obs), tool_call_id=tool_id))

            if should_break_loop or len(chronological_tool_logs) >= MAX_ITERATIONS:
                break

        # 5. If max iterations reached or loop broken without final answer, request synthesis
        if not final_content and len(messages) > 0:
            try:
                synthesis_prompt = HumanMessage(
                    content="Please provide a concise, grounded final answer based only on the verified tool observations above."
                )
                final_resp = llm.invoke(messages + [synthesis_prompt])
                resp_str = final_resp.content if isinstance(final_resp.content, str) else str(final_resp.content)
                if resp_str.strip():
                    final_content = resp_str.strip()
                else:
                    final_content = "The inquiry reached the maximum iteration limit without finding a complete answer. Please refine your question."

            except Exception as e:
                logger.warning("[DocumentReActAgent] Max-iteration synthesis failed: %s", e)
                final_content = "The inquiry reached the maximum iteration limit without finding a complete answer. Please refine your question."

        # 6. Format Citations from RAG tool
        citations: List[Dict[str, Any]] = []
        for c in rag_tool.retrieved_chunks:
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "page_number": c.page_number or 1,
                "chunk_type": c.chunk_type,
                "snippet": c.content.strip()[:300],
                "bounding_box_refs": c.metadata_json.get("bounding_box_refs", []),
                "rerank_score": getattr(c, "rerank_score", None),
            })

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return AgentResult(
            content=final_content.strip(),
            tool_calls=chronological_tool_logs,
            citations=citations,
            execution_time_ms=elapsed_ms,
        )
