"""Multi-Tool Agent Orchestrator for EFDI Global Assistant.

DEPRECATED:
This deterministic keyword-routing orchestrator has been deprecated and replaced
by the LangChain ReAct Global Agent (GlobalReActAgent in app.rag.global_agent)
and Document ReAct Agent (DocumentReActAgent in app.rag.document_agent).
Retained only for backwards compatibility with legacy tests.
"""
import json
import logging
import re
import time
import warnings
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationException
from app.models.roles import UserRole
from app.models.user import User
from app.rag.financial_calculator import FinancialCalculator
from app.rag.llm_client import get_llm_client
from app.rag.reranker import RetrievedChunk
from app.repositories.chat_history_repository import ChatHistoryRepository
from app.services.rag_service import RAGService
from app.services.text_to_sql_service import TextToSQLService

logger = logging.getLogger(__name__)

GLOBAL_AGENT_SYSTEM_PROMPT = """You are the EFDI Global Financial Intelligence Agent.
You assist finance analysts, managers, and auditors across the corporate document portfolio.

You have access to evidence from three specialized tools:
1. Database Query Tool: Relational counts, sums, status filters, and structured fields.
2. Financial Calculator Tool: Deterministic Decimal financial arithmetic and discount deadlines.
3. Document RAG Tool: Unstructured clauses, Incoterms, dispute conditions, and payment terms from OCR text.

STRICT INSTRUCTIONS:
- Synthesize a comprehensive, professional, grounded answer from the provided tool outputs.
- Never invent numbers or terms that are not in the tool evidence.
- For relational metrics, quote the exact SQL results.
- For financial calculations, quote the exact calculator results.
- For document clauses, cite source documents and chunks: [Doc #{doc_id}, Chunk {chunk_id}, Page {page}].
- If the question cannot be answered from the provided tool results, explicitly say so.
"""


class AgentOrchestrator:
    """Autonomous agent router and coordinator for portfolio-wide inquiries."""

    def __init__(self, db: Session) -> None:
        warnings.warn(
            "AgentOrchestrator is deprecated. Use GlobalReActAgent instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.db = db
        self.sql_service = TextToSQLService(db)
        self.rag_service = RAGService(db)
        self.calculator = FinancialCalculator
        self.history_repo = ChatHistoryRepository(db)
        self.llm_client = get_llm_client()

    def process_global_query(
        self,
        query: str,
        user: User,
        session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Process global query with role gating, multi-tool execution, and grounded answer synthesis."""
        start_time = time.perf_counter()

        # 1. Enforce Role Policy for Global Chat
        if user.role == UserRole.FINANCE_ANALYST.value:
            policy = getattr(settings, "GLOBAL_CHAT_ANALYST_POLICY", "scoped")
            if policy == "forbidden":
                raise AuthorizationException("Access to Global AI Chat is restricted to Finance Managers, Auditors, and Admins.")

        # 2. Get or create Global ChatSession
        if session_id:
            session = self.history_repo.get_or_create_global_session(user.id)
        else:
            session = self.history_repo.get_or_create_global_session(user.id)

        # 3. Persist user message
        self.history_repo.add_message(session_id=session.id, role="user", content=query.strip())

        # 4. Determine Tool Execution Plan
        plan = self._plan_tool_execution(query)
        tool_results: Dict[str, Any] = {}
        tool_calls_record: List[Dict[str, Any]] = []
        retrieved_chunks: List[RetrievedChunk] = []
        matched_doc_ids: Optional[List[int]] = None

        # Execute Tool 1: Database SQL Query Tool (if applicable)
        if plan.get("use_sql"):
            try:
                sql_res = self.sql_service.generate_and_execute_sql(query, user=user)
                tool_results["database_query"] = sql_res
                tool_calls_record.append({
                    "tool": "database_query_tool",
                    "sql": sql_res["sql"],
                    "row_count": sql_res["row_count"],
                    "summary": f"Executed SQL with {sql_res['row_count']} row(s) returned",
                })
                # Extract any matching document IDs for compound queries
                if sql_res.get("rows"):
                    extracted_ids = [
                        r["id"] for r in sql_res["rows"] if "id" in r and isinstance(r["id"], int)
                    ]
                    if not extracted_ids:
                        extracted_ids = [
                            r["document_id"] for r in sql_res["rows"] if "document_id" in r and isinstance(r["document_id"], int)
                        ]
                    if extracted_ids:
                        matched_doc_ids = extracted_ids[:20]
            except Exception as sql_err:
                logger.warning("Database Query Tool error: %s", sql_err)
                tool_results["database_query"] = {"error": str(sql_err)}
                tool_calls_record.append({"tool": "database_query_tool", "error": str(sql_err)})

        # Execute Tool 2: Financial Calculator Tool (if applicable)
        if plan.get("use_calculator"):
            try:
                calc_res = self._execute_calculator(query)
                tool_results["financial_calculator"] = calc_res
                tool_calls_record.append({
                    "tool": "financial_calculator_tool",
                    "result": calc_res,
                })
            except Exception as calc_err:
                logger.warning("Financial Calculator Tool error: %s", calc_err)
                tool_results["financial_calculator"] = {"error": str(calc_err)}

        # Execute Tool 3: Document RAG Tool (if applicable)
        if plan.get("use_rag"):
            try:
                # If compound query with matched doc IDs from SQL, scope RAG to those documents
                scoped_ids = matched_doc_ids if plan.get("is_compound") and matched_doc_ids else None
                rag_chunks = self.rag_service.retrieve_global(
                    query=query,
                    user=user,
                    document_ids=scoped_ids,
                    top_k=5,
                )
                retrieved_chunks = rag_chunks
                tool_results["document_rag"] = {
                    "chunks_retrieved": len(rag_chunks),
                    "scoped_document_ids": scoped_ids,
                }
                tool_calls_record.append({
                    "tool": "document_rag_tool",
                    "retrieved_count": len(rag_chunks),
                    "scoped_documents": scoped_ids,
                })
            except Exception as rag_err:
                logger.warning("Document RAG Tool error: %s", rag_err)
                tool_results["document_rag"] = {"error": str(rag_err)}

        # 5. Synthesize Grounded Global Answer
        answer = self._synthesize_answer(query, tool_results, retrieved_chunks)

        # 6. Format Citations
        citations = []
        for c in retrieved_chunks:
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "page_number": c.page_number or 1,
                "chunk_type": c.chunk_type,
                "snippet": c.content.strip()[:300],
                "bounding_box_refs": c.metadata_json.get("bounding_box_refs", []),
            })

        # 7. Persist Assistant Response
        assistant_msg = self.history_repo.add_message(
            session_id=session.id,
            role="assistant",
            content=answer,
            tool_calls=tool_calls_record,
            citations=citations,
        )
        self.db.commit()

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return {
            "session_id": session.id,
            "message_id": assistant_msg.id,
            "role": "assistant",
            "content": answer,
            "tool_calls": tool_calls_record,
            "citations": citations,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else "",
            "execution_time_ms": elapsed_ms,
        }

    def _plan_tool_execution(self, query: str) -> Dict[str, bool]:
        """Determine which tool(s) are required to satisfy query intent."""
        q_lower = query.lower()

        sql_triggers = [
            "how many", "count", "sum", "total spend", "spent with", "average", "status",
            "validated", "rejected", "approved", "uploaded by", "list all", "show all invoices",
        ]
        calc_triggers = [
            "calculate", "discount on", "discounted total", "difference between", "how much is",
            "percent", "%", "divided by", "minus", "plus", "deadline date",
        ]
        rag_triggers = [
            "terms", "conditions", "penalty", "interest", "incoterms", "freight",
            "delivery", "clause", "dispute", "jurisdiction", "payment window", "early settlement",
        ]

        has_sql = any(t in q_lower for t in sql_triggers)
        has_calc = any(t in q_lower for t in calc_triggers)
        has_rag = any(t in q_lower for t in rag_triggers)

        # Default fallback: if no specific triggers match, use RAG for semantic answering
        if not (has_sql or has_calc or has_rag):
            has_rag = True

        # Check for compound query (e.g. SQL + RAG)
        is_compound = (has_sql and has_rag)

        return {
            "use_sql": has_sql,
            "use_calculator": has_calc,
            "use_rag": has_rag,
            "is_compound": is_compound,
        }

    def _execute_calculator(self, query: str) -> Dict[str, Any]:
        """Parse numerical parameters and perform exact Decimal arithmetic."""
        # Check for discount computation pattern: e.g. "2% discount on 1320" or "2% on 1320.00 within 10 days"
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", query)
        amount_match = re.search(r"(?:on|\$|£|€)\s*(\d+(?:\.\d+)?)", query)
        days_match = re.search(r"(\d+)\s*(?:days|day)", query)

        if pct_match and amount_match:
            pct = pct_match.group(1)
            gross = amount_match.group(1)
            days = int(days_match.group(1)) if days_match else 10
            return self.calculator.calculate_discount(
                gross_amount=gross, discount_percentage=pct, days_offset=days
            )

        # Arithmetic expression fallback
        math_expr = re.search(r"[\d\.\s\+\-\*\/]+", query)
        if math_expr and any(op in math_expr.group(0) for op in ("+", "-", "*", "/")):
            val = self.calculator.evaluate_expression(math_expr.group(0))
            return {"expression": math_expr.group(0).strip(), "result": str(val)}

        return {"status": "skipped", "reason": "no_computational_expression_matched"}

    def _synthesize_answer(
        self,
        query: str,
        tool_results: Dict[str, Any],
        retrieved_chunks: List[RetrievedChunk],
    ) -> str:
        """Combine tool outputs into a coherent, grounded response."""
        context_parts = []

        if "database_query" in tool_results:
            sql_data = tool_results["database_query"]
            context_parts.append(
                f"[Tool: Database Query Tool]\n"
                f"SQL: {sql_data.get('sql')}\n"
                f"Rows ({sql_data.get('row_count')}): {json.dumps(sql_data.get('rows', []), default=str)}\n"
            )

        if "financial_calculator" in tool_results:
            calc_data = tool_results["financial_calculator"]
            context_parts.append(
                f"[Tool: Financial Calculator Tool]\n"
                f"Result: {json.dumps(calc_data, default=str)}\n"
            )

        if retrieved_chunks:
            rag_blocks = []
            for c in retrieved_chunks:
                rag_blocks.append(
                    f"[Doc #{c.document_id}, Chunk {c.chunk_id}, Page {c.page_number or 1} - {c.chunk_type}]\n"
                    f"{c.content.strip()}"
                )
            context_parts.append(
                f"[Tool: Document RAG Hybrid Retrieval]\n" + "\n---\n".join(rag_blocks)
            )

        evidence_str = "\n\n".join(context_parts) if context_parts else "No tool evidence available."

        prompt = (
            f"{GLOBAL_AGENT_SYSTEM_PROMPT}\n\n"
            f"User Question: {query}\n\n"
            f"Available Tool Evidence:\n{evidence_str}\n\n"
            f"Assistant Answer:"
        )

        try:
            if self.llm_client.api_key:
                return self.llm_client._call_mistral_api([
                    {"role": "system", "content": GLOBAL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ])
        except Exception as e:
            logger.warning("Global answer synthesis via Mistral failed: %s; using deterministic fallback", e)

        # Deterministic synthesis fallback
        lines = []
        if "database_query" in tool_results and "rows" in tool_results["database_query"]:
            rows = tool_results["database_query"]["rows"]
            lines.append(f"Database Query Results: Found {len(rows)} matching record(s).")
            if rows:
                lines.append(f"Sample data: {rows[:3]}")

        if "financial_calculator" in tool_results and "discount_amount" in tool_results["financial_calculator"]:
            c_res = tool_results["financial_calculator"]
            lines.append(
                f"Financial Calculation: Original Gross = ${c_res['original_gross']}, "
                f"Discount ({c_res['discount_percentage']}) = ${c_res['discount_amount']}, "
                f"Discounted Total Payable = ${c_res['discounted_payable_total']}."
            )

        if retrieved_chunks:
            lines.append("Document Clauses & Evidence:")
            for c in retrieved_chunks[:2]:
                lines.append(f"- [Doc #{c.document_id}, Page {c.page_number or 1}]: {c.content.strip()[:200]}...")

        return "\n\n".join(lines) if lines else "The system could not locate relevant records for this query."
