"""Database Query Tool Adapter for Global ReAct Agent.

Wraps TextToSQLService as a LangChain BaseTool, enforcing backend injection of
trusted current_user and database session.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langchain_core.tools import BaseTool

from app.models.user import User
from app.services.text_to_sql_service import SQLQueryException, SQLSecurityException, TextToSQLService

logger = logging.getLogger(__name__)


class DatabaseQueryInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Natural language question to translate into SQL and query the relational financial database. "
            "Examples: 'Total spend per vendor in 2026', 'How many invoices are in VALIDATED status?', "
            "'List all invoices for Vendor ACME'."
        ),
    )


class DatabaseQueryTool(BaseTool):
    name: str = "database_query_tool"
    description: str = (
        "Execute relational queries against invoices, vendors, line items, payment obligations, and documents. "
        "Use this tool for counts, aggregations, sums, averages, status filters, and tabular relational records. "
        "Input should be a clear natural language question."
    )
    args_schema: Type[BaseModel] = DatabaseQueryInput

    db: Any = Field(exclude=True)
    user: Any = Field(exclude=True)
    execution_logs: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)
    relational_provenance: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)

    def _run(self, query: str) -> str:
        """Translate natural language query to safe SQL and execute."""
        service = TextToSQLService(self.db)
        try:
            res = service.generate_and_execute_sql(natural_language_query=query, user=self.user)
            log_item = {
                "tool": "database_query_tool",
                "sql": res.get("sql", ""),
                "row_count": res.get("row_count", 0),
                "summary": f"Executed SQL returning {res.get('row_count', 0)} row(s)",
                "rows": res.get("rows", []),
            }
            self.execution_logs.append(log_item)

            # Capture relational provenance from authorized returned records
            rows = res.get("rows", [])
            for r in rows[:25]:
                if isinstance(r, dict):
                    rec = {}
                    if "invoice_number" in r:
                        rec["table"] = "invoices"
                        rec["invoice_number"] = r["invoice_number"]
                    elif "canonical_name" in r:
                        rec["table"] = "vendors"
                        rec["vendor_name"] = r["canonical_name"]
                    elif "stored_filename" in r or "original_filename" in r:
                        rec["table"] = "documents"
                        rec["filename"] = r.get("original_filename") or r.get("stored_filename")
                    else:
                        rec["table"] = "relational_record"

                    if "id" in r:
                        rec["record_id"] = r["id"]
                    if "document_id" in r:
                        rec["document_id"] = r["document_id"]
                    if "currency" in r:
                        rec["currency"] = r["currency"]
                    if "grand_total_amount" in r:
                        rec["amount"] = str(r["grand_total_amount"])
                    elif "amount_due" in r:
                        rec["amount"] = str(r["amount_due"])

                    if rec and rec not in self.relational_provenance:
                        self.relational_provenance.append(rec)

            return self._format_compact_observation(res)
        except SQLSecurityException as sec_err:
            logger.warning("[DatabaseQueryTool] Security validation failed: %s", sec_err)
            self.execution_logs.append({
                "tool": "database_query_tool",
                "status": "error",
                "error": str(sec_err),
            })
            return f"Database Query Rejected by Security Policy: {sec_err}"
        except SQLQueryException as q_err:
            logger.warning("[DatabaseQueryTool] SQL Query execution failed: %s", q_err)
            self.execution_logs.append({
                "tool": "database_query_tool",
                "status": "error",
                "error": str(q_err),
            })
            return f"Database Query Error: {q_err}"
        except Exception as err:
            logger.error("[DatabaseQueryTool] Execution error: %s", err, exc_info=True)
            self.execution_logs.append({
                "tool": "database_query_tool",
                "status": "error",
                "error": str(err),
            })
            return f"Database Query Error: {err}"

    @staticmethod
    def _format_compact_observation(res: Dict[str, Any]) -> str:
        """Formats SQL execution results into a compact structured observation for the ReAct agent.

        Classifies result sets:
        - Scalar Aggregates (1 row, e.g. COUNT, SUM): Return full JSON with exact metrics.
        - Grouped Breakdowns (<= 25 rows, e.g. spend by currency, top 5 vendors per currency): Return complete table without truncation.
        - Candidate Identifier Lists (rows with id or document_id): Extract compact array of IDs (up to 100) specifically structured for chaining.
        - Large Enumerations (> 25 rows): Return the top 20 rows, state total row count, and advise the agent.
        """
        rows = res.get("rows", [])
        row_count = res.get("row_count", len(rows))
        sql = res.get("sql", "")

        if not rows:
            return json.dumps({
                "status": "success",
                "row_count": 0,
                "message": "Query executed successfully returning 0 rows.",
                "sql": sql,
                "rows": [],
            }, indent=2)

        # Detect candidate document/entity IDs for chaining into subsequent tools
        candidate_document_ids = []
        for r in rows:
            if isinstance(r, dict):
                doc_id = r.get("document_id") or (r.get("id") if "document" in sql.lower() or "invoice" in sql.lower() else None)
                if doc_id and doc_id not in candidate_document_ids:
                    candidate_document_ids.append(doc_id)

        classification = "unknown"
        output_rows = rows
        truncated = False

        if row_count == 1:
            classification = "scalar_aggregate"
            output_rows = rows
        elif row_count <= 25:
            classification = "grouped_breakdown"
            output_rows = rows
        else:
            classification = "large_enumeration"
            output_rows = rows[:20]
            truncated = True

        result_payload: Dict[str, Any] = {
            "status": "success",
            "classification": classification,
            "row_count": row_count,
            "displayed_rows": len(output_rows),
            "sql": sql,
            "rows": output_rows,
        }

        if candidate_document_ids:
            result_payload["candidate_document_ids"] = candidate_document_ids[:100]

        if truncated:
            result_payload["notice"] = (
                f"Result contains {row_count} total rows. Showing the top 20 rows. "
                "If full portfolio calculations are needed, use SQL aggregate functions (SUM, COUNT, AVG) "
                "with GROUP BY rather than requesting large enumerations."
            )

        return json.dumps(result_payload, indent=2, default=str)
