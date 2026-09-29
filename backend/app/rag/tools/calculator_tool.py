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
            "Calculation action: 'calculate_expression' (for arithmetic math like '150000 * (1 - 0.025)'), "
            "'calculate_discount' (for scalar settlement discount, discounted totals, and deadline dates), "
            "'batch_discounts' (for multi-invoice batch discount calculations across a list of invoice items), "
            "'aggregate_column' (for exact Decimal aggregations: sum, average, min, max, variance over a list of numbers), "
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
    items: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of invoice dictionaries for 'batch_discounts', each containing 'invoice_id', 'gross_amount', 'discount_percentage', optional 'currency', and optional 'invoice_date'.",
    )
    values: Optional[List[Any]] = Field(
        default=None,
        description="List of numeric values for 'aggregate_column' (e.g. [100.50, 250.00, 75.25]).",
    )
    operation: Optional[str] = Field(
        default="sum",
        description="Aggregation operation for 'aggregate_column': 'sum', 'average', 'min', 'max', or 'variance'.",
    )


class FinancialCalculatorTool(BaseTool):
    name: str = "financial_calculator_tool"
    description: str = (
        "Perform exact Decimal financial calculations, early settlement discount formulas, "
        "batch discounts across multiple invoices, column aggregations, and calendar date offsets. "
        "Always use this tool for arithmetic rather than guessing."
    )
    args_schema: Type[BaseModel] = CalculatorInput
    execution_logs: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)
    calculation_provenance: List[Dict[str, Any]] = Field(default_factory=list, exclude=True)

    def _run(
        self,
        action: str = "calculate_expression",
        expression: Optional[str] = None,
        gross_amount: Optional[str] = None,
        discount_percentage: Optional[str] = None,
        days_offset: Optional[int] = 10,
        invoice_date: Optional[str] = None,
        base_date: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        values: Optional[List[Any]] = None,
        operation: Optional[str] = "sum",
    ) -> str:
        """Execute deterministic Decimal financial computation."""
        try:
            if action == "batch_discounts" or items is not None:
                if not items:
                    return "Financial Calculator Error: 'items' list is required for batch_discounts."
                res = FinancialCalculator.batch_calculate_discounts(items)
                summary_str = f"Calculated batch discounts for {res['calculated_count']} items across {len(res['totals_by_currency'])} currencies."
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "batch_discounts",
                    "result": res,
                    "summary": summary_str,
                })
                self.calculation_provenance.append({
                    "operation": "batch_discounts",
                    "formula": summary_str,
                    "totals_by_currency": res.get("totals_by_currency"),
                })
                return f"Financial Calculation Result (Batch Discounts):\n{json.dumps(res, indent=2)}"

            elif action == "aggregate_column" or values is not None:
                if not values:
                    return "Financial Calculator Error: 'values' list is required for aggregate_column."
                res = FinancialCalculator.aggregate_column(values, operation=operation or "sum")
                formula_str = f"{res['operation'].upper()}({res['count']} values) = {res['result']}"
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "aggregate_column",
                    "result": res,
                    "summary": f"Computed {res['operation']} on {res['count']} values: {res['result']}",
                })
                self.calculation_provenance.append({
                    "operation": f"aggregate_{res['operation']}",
                    "formula": formula_str,
                    "result": res["result"],
                })
                return f"Financial Calculation Result (Aggregate):\n{json.dumps(res, indent=2)}"

            elif action == "calculate_discount" or (gross_amount and discount_percentage):
                if not gross_amount or not discount_percentage:
                    return "Financial Calculator Error: 'gross_amount' and 'discount_percentage' are required for calculate_discount."
                res = FinancialCalculator.calculate_discount(
                    gross_amount=gross_amount,
                    discount_percentage=discount_percentage,
                    days_offset=days_offset or 10,
                    invoice_date=invoice_date,
                )
                formula_str = f"Gross=${res['original_gross']} * {res['discount_percentage']} = Savings ${res['discount_amount']} (Payable=${res['discounted_payable_total']})"
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_discount",
                    "result": res,
                    "summary": f"Calculated discount: Original Gross=${res['original_gross']}, Discount=${res['discount_amount']}, Payable=${res['discounted_payable_total']}",
                })
                self.calculation_provenance.append({
                    "operation": "early_discount",
                    "formula": formula_str,
                    "original_gross": res["original_gross"],
                    "discount_amount": res["discount_amount"],
                    "payable_total": res["discounted_payable_total"],
                })
                return f"Financial Calculation Result (Discount):\n{json.dumps(res, indent=2)}"

            elif action == "calculate_date_offset" or (base_date and days_offset is not None):
                target_date = base_date or invoice_date
                if not target_date:
                    return "Financial Calculator Error: 'base_date' is required for calculate_date_offset."
                new_date = FinancialCalculator.calculate_date_offset(target_date, days_offset or 0)
                res = {"base_date": target_date, "days_offset": days_offset, "calculated_date": new_date}
                formula_str = f"{target_date} + {days_offset} days = {new_date}"
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_date_offset",
                    "result": res,
                    "summary": f"Calculated date offset: {formula_str}",
                })
                self.calculation_provenance.append({
                    "operation": "date_offset",
                    "formula": formula_str,
                })
                return f"Financial Calculation Result (Date Offset):\n{json.dumps(res, indent=2)}"

            else:
                expr = expression or gross_amount
                if not expr:
                    return "Financial Calculator Error: 'expression' is required for calculate_expression."
                val = FinancialCalculator.evaluate_expression(expr)
                res = {"expression": expr.strip(), "result": str(val)}
                formula_str = f"{expr.strip()} = {val}"
                self.execution_logs.append({
                    "tool": "financial_calculator_tool",
                    "action": "calculate_expression",
                    "result": res,
                    "summary": f"Evaluated expression: {formula_str}",
                })
                self.calculation_provenance.append({
                    "operation": "expression",
                    "formula": formula_str,
                    "result": str(val),
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
