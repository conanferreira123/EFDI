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
from app.services.text_to_sql_service import SQLSecurityException, TextToSQLService

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

            rows = res.get("rows", [])
            row_count = res.get("row_count", 0)
            if row_count == 0:
                return "Database Query Result: 0 matching records found."

            # Format compact observation for ReAct agent
            columns = res.get("columns", [])
            sample_rows = rows[:15]  # Limit observation token footprint
            compact_obs = {
                "row_count": row_count,
                "columns": columns,
                "rows": sample_rows,
            }
            if row_count > 15:
                compact_obs["note"] = f"Showing top 15 of {row_count} records."

            return f"Database Query Results ({row_count} rows):\n{json.dumps(compact_obs, default=str)}"
        except SQLSecurityException as sec_err:
            logger.warning("[DatabaseQueryTool] Security validation failed: %s", sec_err)
            self.execution_logs.append({
                "tool": "database_query_tool",
                "status": "error",
                "error": str(sec_err),
            })
            return f"Database Query Rejected by Security Policy: {sec_err}"
        except Exception as err:
            logger.error("[DatabaseQueryTool] Execution error: %s", err, exc_info=True)
            self.execution_logs.append({
                "tool": "database_query_tool",
                "status": "error",
                "error": str(err),
            })
            return f"Database Query Error: {err}"
