"""Financial Calculator Tool Adapter for ReAct Agents.

Wraps FinancialCalculator as a LangChain BaseTool, providing deterministic
Decimal precision arithmetic and settlement discount computations.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

from app.rag.financial_calculator import FinancialCalculator

logger = logging.getLogger(__name__)


class CalculatorInput(BaseModel):
    action: str = Field(
        default="calculate_expression",
        description=(
            "Calculation action: 'calculate_expression' (for arithmetic math like '150000 * (1 - 0.025)') "
            "or 'calculate_discount' (for settlement discount amounts, discounted totals, and deadline dates) "
            "or 'calculate_date_offset' (for date additions YYYY-MM-DD + days)."
        ),
    )
    expression: Optional[str] = Field(
        default=None,
        description="Arithmetic expression for 'calculate_expression' (e.g. '5000 + 1250.50' or '150000 * 0.98').",
    )
    gross_amount: Optional[str] = Field(
        default=None,
        description="Original gross total amount for 'calculate_discount' (e.g. '150000.00').",
    )
    discount_percentage: Optional[str] = Field(
        default=None,
        description="Discount percentage for 'calculate_discount' (e.g. '2.5' or '2.5%').",
    )
    days_offset: Optional[int] = Field(
        default=10,
        description="Discount window or offset days (default: 10).",
    )
    invoice_date: Optional[str] = Field(
        default=None,
        description="Invoice date (YYYY-MM-DD) for deadline date calculation.",
    )
    base_date: Optional[str] = Field(
        default=None,
        description="Base date (YYYY-MM-DD) for 'calculate_date_offset'.",
    )


class FinancialCalculatorTool(BaseTool):
    name: str = "financial_calculator_tool"
    description: str = (
        "Perform exact Decimal financial calculations, early settlement discount formulas, "
        "variances, taxes, and calendar date offsets. Always use this tool for arithmetic rather than guessing."
    )
    args_schema: Type[BaseModel] = CalculatorInput
    execution_logs: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)

    def _run(
        self,
        action: str = "calculate_expression",
        expression: Optional[str] = None,
        gross_amount: Optional[str] = None,
        discount_percentage: Optional[str] = None,
        days_offset: Optional[int] = 10,
        invoice_date: Optional[str] = None,
        base_date: Optional[str] = None,
    ) -> str:
        """Execute deterministic Decimal financial computation."""
        try:
            if action == "calculate_discount" or (gross_amount and discount_percentage):
                if not gross_amount or not discount_percentage:
                    return "Financial Calculator Error: 'gross_amount' and 'discount_percentage' are required for calculate_discount."
                res = FinancialCalculator.calculate_discount(
                    gross_amount=gross_amount,
                    discount_percentage=discount_percentage,
                    days_offset=days_offset or 10,
                    invoice_date=invoice_date,
                )
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_discount",
                    "result": res,
                    "summary": f"Calculated discount: Original Gross=${res['original_gross']}, Discount=${res['discount_amount']}, Payable=${res['discounted_payable_total']}",
                })
                return f"Financial Calculation Result (Discount):\n{json.dumps(res, indent=2)}"

            elif action == "calculate_date_offset" or (base_date and days_offset is not None):
                target_date = base_date or invoice_date
                if not target_date:
                    return "Financial Calculator Error: 'base_date' is required for calculate_date_offset."
                new_date = FinancialCalculator.calculate_date_offset(target_date, days_offset or 0)
                res = {"base_date": target_date, "days_offset": days_offset, "calculated_date": new_date}
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_date_offset",
                    "result": res,
                    "summary": f"Calculated date offset: {target_date} + {days_offset} days = {new_date}",
                })
                return f"Financial Calculation Result (Date Offset):\n{json.dumps(res, indent=2)}"

            else:
                expr = expression or gross_amount
                if not expr:
                    return "Financial Calculator Error: 'expression' is required for calculate_expression."
                val = FinancialCalculator.evaluate_expression(expr)
                res = {"expression": expr.strip(), "result": str(val)}
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_expression",
                    "result": res,
                    "summary": f"Evaluated expression: {expr.strip()} = {val}",
                })
                return f"Financial Calculation Result:\n{expr.strip()} = {val}"

        except Exception as err:
            logger.warning("[FinancialCalculatorTool] Calculation error: %s", err)
            self.execution_logs.append({
                "tool": "financial_calculator_tool",
                "status": "error",
                "error": str(err),
            })
            return f"Financial Calculator Error: {err}"
