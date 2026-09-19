"""Financial Calculator Tool.

Provides deterministic Decimal precision arithmetic, calendar offsets,
and early-payment discount calculations without LLM estimation errors.
"""
import ast
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import operator
import re
from typing import Any, Dict, Optional, Union


class FinancialCalculator:
    """Safe financial calculation engine using Decimal precision and calendar arithmetic."""

    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    @classmethod
    def evaluate_expression(cls, expr_str: str) -> Decimal:
        """Safely evaluate an arithmetic expression into a Decimal using AST parsing."""
        # Sanitize input: allow only digits, decimal points, spaces, and basic arithmetic operators
        clean_expr = expr_str.strip().replace("$", "").replace("€", "").replace("£", "").replace(",", "")
        if not re.match(r"^[\d\.\s\+\-\*\/\(\)]+$", clean_expr):
            raise ValueError(f"Invalid characters in arithmetic expression: {expr_str}")

        try:
            tree = ast.parse(clean_expr, mode="eval")
            result = cls._eval_ast_node(tree.body)
            return Decimal(str(result)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception as e:
            raise ValueError(f"Failed to evaluate financial expression '{expr_str}': {e}")

    @classmethod
    def _eval_ast_node(cls, node: ast.AST) -> Union[Decimal, int, float]:
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        elif isinstance(node, ast.BinOp):
            left = cls._eval_ast_node(node.left)
            right = cls._eval_ast_node(node.right)
            op_type = type(node.op)
            if op_type in cls.OPERATORS:
                return cls.OPERATORS[op_type](Decimal(str(left)), Decimal(str(right)))
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        elif isinstance(node, ast.UnaryOp):
            operand = cls._eval_ast_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -Decimal(str(operand))
            elif isinstance(node.op, ast.UAdd):
                return Decimal(str(operand))
        raise ValueError(f"Unsupported AST node in expression: {type(node).__name__}")

    @classmethod
    def calculate_discount(
        cls,
        gross_amount: Union[str, float, Decimal],
        discount_percentage: Union[str, float, Decimal],
        days_offset: int,
        invoice_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute early settlement discount and discounted total payable with exact Decimal precision."""
        gross = Decimal(str(gross_amount).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pct = Decimal(str(discount_percentage).replace("%", "").strip())
        discount_amount = (gross * (pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discounted_total = (gross - discount_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        deadline_str = None
        if invoice_date:
            try:
                base_dt = datetime.strptime(invoice_date.strip()[:10], "%Y-%m-%d")
                deadline_dt = base_dt + timedelta(days=days_offset)
                deadline_str = deadline_dt.strftime("%Y-%m-%d")
            except Exception:
                deadline_str = None

        return {
            "original_gross": str(gross),
            "discount_percentage": f"{pct}%",
            "discount_amount": str(discount_amount),
            "discounted_payable_total": str(discounted_total),
            "discount_window_days": days_offset,
            "deadline_date": deadline_str,
        }

    @classmethod
    def calculate_date_offset(cls, base_date: str, days: int) -> str:
        """Calculate calendar date offset."""
        base_dt = datetime.strptime(base_date.strip()[:10], "%Y-%m-%d")
        new_dt = base_dt + timedelta(days=days)
        return new_dt.strftime("%Y-%m-%d")
