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

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.models.user import User
from app.rag.agent_llm import get_agent_llm
from app.rag.agent_result import AgentResult
from app.rag.response_guardrails import (
    GLOBAL_TIMEOUT_MESSAGE,
    RESPONSE_GENERATION_GUARDRAIL_PROMPT,
    get_execution_state_refusal,
    is_execution_state_query,
    sanitize_response_content,
)
from app.rag.tools.calculator_tool import FinancialCalculatorTool
from app.rag.tools.rag_tool import DocumentRAGTool

logger = logging.getLogger(__name__)

DOCUMENT_REACT_SYSTEM_PROMPT = f"""You are the EFDI Document Financial Assistant, an enterprise copilot scoped strictly to a single financial document.
You answer inquiries about line items, payment terms, early payment discounts, freight, penalties, and contractual clauses for this specific document.

You have access to two specialized tools:
1. document_rag_tool: Retrieves textual clauses, payment terms, Incoterms, freight details, penalties, and OCR snippets from this document.
2. financial_calculator_tool: Performs deterministic Decimal arithmetic, settlement discount formulas, and calendar deadline date calculations.

OPERATIONAL GUIDELINES:
- Dynamically select the appropriate tool(s) to answer the user's question about this document.
- For contractual terms, settlement percentages, or clauses, query document_rag_tool.
- For exact discount totals, net payable amounts, or deadline dates, invoke financial_calculator_tool.
- Answer ONLY from verified tool observations. NEVER invent or extrapolate terms or figures.
- When sufficient information has been gathered, provide a concise, professional, grounded final answer citing relevant page numbers where applicable. Never mention chunk IDs or internal retrieval identifiers.

CONVERSATIONAL CONTINUITY & EVIDENCE RULES:
- When the user asks a follow-up or confirms an offer, resolve their intent using the immediate dialogue context.
- Verified tool observations ALWAYS take precedence over historical assistant statements or conversational text.
- If a tool search returns no matching clauses or negative evidence, report clearly that the document was searched and does not contain those terms.
- Do NOT repeatedly query equivalent variations of the same search if previous attempts yielded no relevant clauses.
- Do NOT repeat an offer or question you already extended and executed in the same dialogue thread.

QUESTION-ANSWERING SCOPE & NORMAL QUESTION RULES:
- The structured "Invoice Summary" format is EXCLUSIVELY for user requests where the intent is to summarize, provide an overview of, or give a structured summary of the current document (e.g. "Summarize this document", "Give me an invoice summary", "AP summary").
- It MUST NOT be used as the default format for normal questions.
- For all normal questions, specific inquiries, or follow-up questions:
  * Answer ONLY the specific question asked.
  * Do NOT regenerate or prepend the "Invoice Summary".
  * Do NOT include unrelated sections such as Payment Details, Amount Breakdown, Items / Services, or AP Attention.
  * Retrieve whatever evidence is necessary to answer the specific question and keep the response concise, grounded, and directly relevant.
  * Examples:
    - User asks: "What is the vendor name?" -> Answer directly: "The vendor is [Vendor Name]."
    - User asks: "What is the invoice number?" -> Answer directly: "The invoice number is [Invoice Number]."
    - User asks: "What are the payment terms?" -> Answer only the payment-terms question directly.
    - User asks: "Are there any issues I should know about?" -> Answer directly focusing on the relevant attention items without the rest of the summary structure.

ACCOUNTS PAYABLE (AP) DOCUMENT SUMMARY DIRECTIVE:
When the user explicitly asks to summarize the document, invoice, or billing details (e.g. "Summarize this document", "Give me an AP summary", "Invoice summary"):
- Produce a concise, operational summary tailored to an Accounts Payable employee.
- Gather all necessary evidence across header, line items, totals, and contractual clauses using document_rag_tool.
- If arithmetic calculation, discount computation, or deadline calculation is required, invoke financial_calculator_tool.
- Return the summary formatted strictly as ONE assistant response using the following 5 sections:

# Invoice Summary

## 1. Invoice Overview
**Vendor:** [Vendor Name]
**Invoice Number:** [Invoice Number]
**Invoice Date:** [Invoice Date]
**Due Date:** [Due Date, or state "Not stated in the document." if absent]
**Currency:** [Currency Code]
**Total Amount Due:** [Total Amount Stated]
**PO Number:** [PO Number, or state "Not stated in the document." if absent]

## 2. Payment Details
**Payment Terms:** [e.g. Net 30, Due on Receipt]
**Payment Method:** [e.g. Bank Transfer, Check, or omit if not stated]
**Early Payment Discount:** [Discount % and qualifying terms/deadline if explicitly stated, else state "None stated in the document."]

## 3. Amount Breakdown
**Subtotal:** [Amount]
**Tax:** [Amount and rate if stated]
**Discount:** [Amount, if explicitly applicable]
**Other Charges:** [Amount, if stated]
**Total:** [Total Amount Due]
(Only include amount fields actually supported by the document. Do not assume missing fields are zero. Do not silently combine different currencies.)

## 4. Items / Services
Render line items as a compact Markdown table with right-aligned numeric columns where supported. Include only columns supported by the document:
| Description | Qty | Unit Price | Amount |
|---|---:|---:|---:|
(Do not force unsupported columns. Do not dump raw OCR text. If itemized line items are not present in the document, concisely state that line item details are not stated.)

## 5. AP Attention
Highlight only material items an Accounts Payable employee should notice:
- Missing PO information (if absent)
- Payment deadlines, early payment discount opportunities, or late payment penalty conditions
- Tax information that is missing or unclear
- Any mathematical or reconciliation inconsistencies supported by document evidence
- Unclear or conflicting values in the document
(Do not manufacture warnings. If there are no material issues, state: "No specific AP attention items identified.")

SUMMARY RULES:
1. Return as ONE assistant response. Do not split into multiple messages.
2. Rely strictly on evidence from the CURRENT authorized document. Never use another document to fill missing fields.
3. Never fabricate or extrapolate values. Distinguish "Not stated in the document." from zero.
4. Do NOT calculate or present an early settlement discounted total unless the document explicitly defines the terms, the qualifying conditions are met, the financial calculator is used, and the discounted total is clearly distinguished from the stated total amount due.
5. Do NOT create separate sections for "Vendor & Buyer", "Financial & Tax Summary", "Payment Information", "Commercial / Contractual Terms", "Exceptions / Uncertainties", or "Final Payment Summary". Only use the 5 sections above.
6. EXCLUSIVE INTENT: Do NOT use the Invoice Summary structure as a default response. Only use it when the user explicitly requests a document summary or overview.
7. When responding to inquiries about the current conversation or previous messages, rely on the conversation history and tool observations. Do NOT use the invoice summary format for these types of questions.

SUMMARY MARKDOWN FORMATTING RULES:

When producing an Invoice Summary:

- Return the summary as normal Markdown.
- NEVER wrap the entire response, or any complete summary section, inside a Markdown code fence.
- NEVER use triple backticks (```) around the summary.
- Field names MUST be bold using Markdown syntax.
- Each field and subfield MUST appear on its own separate line.
- Do not combine multiple fields into the same paragraph or line.

{RESPONSE_GENERATION_GUARDRAIL_PROMPT}
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
        # For document_rag_tool, check high keyword overlap or containment
        if tool_name == "document_rag_tool":
            words_b = {w for w in re.findall(r"\b[a-z0-9]+\b", prev_lower) if len(w) > 2 and w not in stopwords}
            if words_a and words_b:
                common = words_a & words_b
                overlap = len(common) / len(words_a | words_b)
                containment = len(common) / min(len(words_a), len(words_b))
                if overlap >= 0.70 or (containment >= 0.75 and len(common) >= 2):
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
        timeout_seconds: Optional[float] = None,
    ) -> AgentResult:
        """Execute dynamic ReAct tool loop scoped strictly to document_id."""
        start_time = time.perf_counter()
        effective_timeout = timeout_seconds if timeout_seconds is not None else float(getattr(settings, "CHAT_REQUEST_TIMEOUT_SECONDS", 30.0))
        deadline = start_time + effective_timeout

        # Guardrail 6: Politely decline execution-state probing inquiries without exposing internal mechanics
        if is_execution_state_query(query):
            return AgentResult(
                content=get_execution_state_refusal(),
                tool_calls=[],
                citations=[],
                execution_time_ms=(time.perf_counter() - start_time) * 1000.0,
            )

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
        seen_chunk_ids: set[int] = set()

        # Count total chunks available for this document to detect evidence exhaustion
        from app.models.document_chunk import DocumentChunk
        try:
            total_doc_chunks = (
                self.db.query(DocumentChunk.id)
                .filter(DocumentChunk.document_id == document_id)
                .count()
            )
        except Exception:
            total_doc_chunks = 0

        # 4. Iterative ReAct Loop (max 5 iterations)
        for step in range(MAX_ITERATIONS):
            # Check global request deadline
            if time.perf_counter() > deadline:
                logger.warning("[DocumentReActAgent] Global timeout (%.1fs) exceeded before step %d", effective_timeout, step)
                return AgentResult(
                    content=GLOBAL_TIMEOUT_MESSAGE,
                    tool_calls=chronological_tool_logs,
                    citations=[],
                    execution_time_ms=(time.perf_counter() - start_time) * 1000.0,
                )

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
                # Check global request deadline before each tool
                if time.perf_counter() > deadline:
                    logger.warning("[DocumentReActAgent] Global timeout (%.1fs) exceeded before tool execution", effective_timeout)
                    return AgentResult(
                        content=GLOBAL_TIMEOUT_MESSAGE,
                        tool_calls=chronological_tool_logs,
                        citations=[],
                        execution_time_ms=(time.perf_counter() - start_time) * 1000.0,
                    )

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

                # Check evidence exhaustion guard: if all document chunks were already retrieved
                if tool_name == "document_rag_tool" and total_doc_chunks > 0 and len(seen_chunk_ids) >= total_doc_chunks:
                    logger.info(
                        "[DocumentReActAgent] All %d chunk(s) for Document #%d already retrieved; suppressing redundant search for %r",
                        total_doc_chunks,
                        document_id,
                        query_str,
                    )
                    obs = (
                        f"Notice: All textual content and clauses from this document have already been fully retrieved in previous steps. "
                        "No additional matching clauses exist in this document. "
                        "Please synthesize your final grounded answer based on available verified observations, "
                        "stating 'Not stated in the document' for any details not found."
                    )
                    chronological_tool_logs.append({
                        "tool": tool_name,
                        "summary": f"Suppressed redundant search: all {total_doc_chunks} chunk(s) already retrieved",
                        "status": "redundant_suppressed",
                    })
                    messages.append(ToolMessage(content=obs, tool_call_id=tool_id))
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

                if tool_name == "document_rag_tool":
                    current_chunks = getattr(target_tool, "retrieved_chunks", [])
                    new_chunks = [c for c in current_chunks if c.chunk_id not in seen_chunk_ids]
                    if len(seen_chunk_ids) > 0 and len(new_chunks) == 0:
                        obs += (
                            "\n\n(Notice: This search returned no new or additional document clauses beyond what was already retrieved. "
                            "If the requested information was not found in the retrieved evidence, it is not stated in the document. "
                            "Please conclude your findings without further repetitive searches.)"
                        )
                    seen_chunk_ids.update(c.chunk_id for c in current_chunks)

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
            if time.perf_counter() > deadline:
                logger.warning("[DocumentReActAgent] Global timeout (%.1fs) exceeded before synthesis", effective_timeout)
                return AgentResult(
                    content=GLOBAL_TIMEOUT_MESSAGE,
                    tool_calls=chronological_tool_logs,
                    citations=[],
                    execution_time_ms=(time.perf_counter() - start_time) * 1000.0,
                )

            try:
                is_summary = bool(re.search(r"\b(summariz\w*|summaris\w*|summary|overview|ap summary|invoice summary)\b", query, re.IGNORECASE))
                if is_summary:
                    synthesis_content = (
                        "Please provide the complete, concise Accounts Payable Invoice Summary based on the verified tool observations above.\n"
                        "Format strictly according to the 5 AP summary sections (# Invoice Summary, ## 1. Invoice Overview, ## 2. Payment Details, "
                        "## 3. Amount Breakdown, ## 4. Items / Services, ## 5. AP Attention).\n"
                        "Use a compact Markdown table for Items / Services. Follow strict response guardrails: Describe business findings only, "
                        "never invent figures or cite chunk IDs."
                    )
                else:
                    synthesis_content = (
                        "Please provide a concise, grounded final answer based only on the verified tool observations above.\n"
                        "Follow strict response guardrails: Describe business findings only. Do NOT expose internal chunk IDs, "
                        "tool names, or system execution details. Cite legitimate page numbers if applicable."
                    )
                synthesis_prompt = HumanMessage(content=synthesis_content)
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
            meta = getattr(c, "metadata_json", {}) or {}
            doc_title = getattr(c, "document_title", None) or meta.get("document_title") or meta.get("filename")
            citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "document_title": doc_title,
                "page_number": c.page_number or 1,
                "chunk_type": c.chunk_type,
                "snippet": c.content.strip()[:300],
                "bounding_box_refs": meta.get("bounding_box_refs", []) if isinstance(meta, dict) else [],
                "rerank_score": getattr(c, "rerank_score", None),
            })

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Guardrails 1-10: Deterministically sanitize response content
        sanitized_content = sanitize_response_content(final_content, query=query)

        return AgentResult(
            content=sanitized_content.strip(),
            tool_calls=chronological_tool_logs,
            citations=citations,
            execution_time_ms=elapsed_ms,
        )
