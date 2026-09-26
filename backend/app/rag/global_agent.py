"""Global ReAct Agent for Portfolio-Wide Financial Inquiries.

Coordinates Database / Text-to-SQL, Document RAG, and Financial Calculator tools
through dynamic LangChain iterative reasoning without keyword-based routing.
"""
import logging
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.config import settings
from app.core.exceptions import AuthorizationException
from app.models.roles import UserRole
from app.models.user import User
from app.rag.agent_llm import get_agent_llm
from app.rag.agent_result import AgentResult
from app.rag.tools.calculator_tool import FinancialCalculatorTool
from app.rag.tools.database_tool import DatabaseQueryTool
from app.rag.tools.rag_tool import DocumentRAGTool

logger = logging.getLogger(__name__)

GLOBAL_REACT_SYSTEM_PROMPT = """You are the EFDI Global Financial Intelligence Agent, an enterprise copilot for corporate finance.
You assist finance analysts, managers, and auditors across corporate financial documents, invoices, line items, and business data.

You have access to three specialized tools:
1. database_query_tool: Queries relational counts, spend totals, invoices, line items, vendors, payment obligations, approval statuses and user information(only if user has role of Administrator).
2. document_rag_tool: Retrieves unstructured contract clauses, payment terms, Incoterms, freight, penalties, and OCR text snippets.
3. financial_calculator_tool: Performs deterministic Decimal arithmetic, early settlement discounts, and calendar deadline date calculations.

OPERATIONAL GUIDELINES:
- Dynamically select the most appropriate tool(s) for the user's question.
- For financial numbers, aggregations, and counts, query database_query_tool.
- For contractual terms, settlement percentages, or clauses, query document_rag_tool.
- For arithmetic, variances, settlement discounts, or date offsets, ALWAYS invoke financial_calculator_tool.
- You can perform multi-step reasoning: query data or text first, then pass observed numbers to financial_calculator_tool.
- Answer ONLY from verified tool observations. NEVER fabricate numbers, dates, or terms.
- When sufficient information has been gathered, provide a concise, professional, grounded final answer without exposing internal tool calls or reasoning.
"""

MAX_ITERATIONS = 5


class GlobalReActAgent:
    """Dynamic ReAct Agent for portfolio-wide inquiries (/api/v1/chat/corpus)."""

    def __init__(self, db: Session, llm: Optional[Any] = None) -> None:
        self.db = db
        self._llm = llm

    def run(
        self,
        query: str,
        user: User,
        history: Optional[List[BaseMessage]] = None,
    ) -> AgentResult:
        """Execute dynamic ReAct tool loop for global chat."""
        start_time = time.perf_counter()

        # 1. Enforce Role Policy for Global Chat
        if user.role == UserRole.FINANCE_ANALYST.value:
            policy = getattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "scoped")
            if policy == "forbidden":
                raise AuthorizationException(
                    "Access to Global AI Chat is restricted to Finance Managers, Auditors, and Admins."
                )

        # 2. Instantiate Tools with Backend Injected Context
        db_tool = DatabaseQueryTool(db=self.db, user=user)
        rag_tool = DocumentRAGTool(db=self.db, user=user)
        calc_tool = FinancialCalculatorTool()

        tools = [db_tool, rag_tool, calc_tool]
        tool_map = {t.name: t for t in tools}

        # 3. Prepare Chat Model
        llm = self._llm or get_agent_llm()
        llm_with_tools = llm.bind_tools(tools)

        # 4. Construct Message History
        messages: List[BaseMessage] = [SystemMessage(content=GLOBAL_REACT_SYSTEM_PROMPT)]
        if history:
            messages.extend(history)
        messages.append(HumanMessage(content=query.strip()))

        final_content = ""
        chronological_tool_logs: List[Dict[str, Any]] = []

        # 5. Iterative ReAct Loop (max 5 iterations)
        for step in range(MAX_ITERATIONS):
            try:
                response = llm_with_tools.invoke(messages)
            except Exception as e:
                logger.error("[GlobalReActAgent] LLM invocation failed at step %d: %s", step, e)
                final_content = f"An error occurred while communicating with the AI service: {e}"
                break

            messages.append(response)

            # Check if model requested tool calls
            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                # No tool calls requested: final answer produced
                final_content = response.content if isinstance(response.content, str) else str(response.content)
                break

            # Execute requested tools
            for tc in tool_calls:
                if len(chronological_tool_logs) >= MAX_ITERATIONS:
                    logger.info("[GlobalReActAgent] Reached maximum allowed tool steps (%d)", MAX_ITERATIONS)
                    break

                tool_name = tc.get("name")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id") or f"call_{step}_{tool_name}"

                target_tool = tool_map.get(tool_name)
                if not target_tool:
                    obs = f"Error: Tool '{tool_name}' is not available."
                    chronological_tool_logs.append({
                        "tool": tool_name,
                        "status": "error",
                        "error": f"Tool '{tool_name}' is not available",
                    })
                else:
                    pre_count = len(target_tool.execution_logs)
                    try:
                        obs = target_tool.invoke(tool_args)
                    except Exception as tool_err:
                        logger.warning("[GlobalReActAgent] Tool '%s' error: %s", tool_name, tool_err)
                        obs = f"Error executing tool '{tool_name}': {tool_err}"

                    if len(target_tool.execution_logs) > pre_count:
                        chronological_tool_logs.append(target_tool.execution_logs[-1])
                    else:
                        chronological_tool_logs.append({
                            "tool": tool_name,
                            "summary": f"Executed {tool_name}",
                        })

                messages.append(ToolMessage(content=str(obs), tool_call_id=tool_id))

            if len(chronological_tool_logs) >= MAX_ITERATIONS:
                break

        # 6. If max iterations reached without final answer, request synthesis
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
                logger.warning("[GlobalReActAgent] Max-iteration synthesis failed: %s", e)
                final_content = "The inquiry reached the maximum iteration limit without finding a complete answer. Please refine your question."

        # 7. Format Citations from RAG tool
        citations: List[Dict[str, Any]] = []
        for c in rag_tool.retrieved_chunks:
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "page_number": c.page_number or 1,
                "chunk_type": c.chunk_type,
                "snippet": c.content.strip()[:300],
                "bounding_box_refs": c.metadata_json.get("bounding_box_refs", []),
            })

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return AgentResult(
            content=final_content.strip(),
            tool_calls=chronological_tool_logs,
            citations=citations,
            execution_time_ms=elapsed_ms,
        )
