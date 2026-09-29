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

    @classmethod
    def _parse_percentage(cls, raw_pct: Any) -> Decimal:
        """Parse percentage robustly from string, float, or integer."""
        raw_str = str(raw_pct).strip()
        has_pct_sign = "%" in raw_str
        clean_str = raw_str.replace("%", "").strip()
        if not clean_str:
            return Decimal("0.00")
        pct_dec = Decimal(clean_str)
        # If passed as decimal fraction (e.g. 0.02 instead of 2 or 2%)
        if not has_pct_sign and Decimal("0") < pct_dec <= Decimal("0.20"):
            pct_dec = pct_dec * Decimal("100")
        return pct_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def batch_calculate_discounts(cls, items: list) -> Dict[str, Any]:
        """Compute early settlement discounts across multiple invoices with exact Decimal precision.

        Groups totals by currency and outputs both itemized and aggregate savings.
        """
        if not items:
            return {
                "calculated_count": 0,
                "items": [],
                "totals_by_currency": {},
            }

        calculated_items = []
        totals_by_currency: Dict[str, Dict[str, Any]] = {}

        for item in items:
            raw_gross = (
                item.get("gross_amount")
                or item.get("grand_total_amount")
                or item.get("total_amount")
                or item.get("amount")
                or 0
            )
            raw_pct = (
                item.get("discount_percentage")
                or item.get("early_payment_discount")
                or item.get("discount_pct")
                or 0
            )
            currency = (item.get("currency") or "USD").upper().strip()
            inv_id = item.get("invoice_id") or item.get("id") or item.get("invoice_number")
            days_offset = item.get("days_offset", 10)
            inv_date = item.get("invoice_date")

            try:
                gross = Decimal(str(raw_gross).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                pct = cls._parse_percentage(raw_pct)
                discount_amount = (gross * (pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                payable_total = (gross - discount_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception as e:
                # If unparseable row, skip calculation for this item
                continue

            deadline_str = None
            if inv_date:
                try:
                    base_dt = datetime.strptime(str(inv_date).strip()[:10], "%Y-%m-%d")
                    deadline_dt = base_dt + timedelta(days=int(days_offset))
                    deadline_str = deadline_dt.strftime("%Y-%m-%d")
                except Exception:
                    deadline_str = None

            calc_entry = {
                "invoice_id": inv_id,
                "currency": currency,
                "gross_amount": str(gross),
                "discount_percentage": f"{pct}%",
                "discount_savings": str(discount_amount),
                "discounted_payable_total": str(payable_total),
                "deadline_date": deadline_str,
            }
            calculated_items.append(calc_entry)

            if currency not in totals_by_currency:
                totals_by_currency[currency] = {
                    "total_gross": Decimal("0.00"),
                    "total_discount_savings": Decimal("0.00"),
                    "total_discounted_payable": Decimal("0.00"),
                    "invoice_count": 0,
                }

            totals_by_currency[currency]["total_gross"] += gross
            totals_by_currency[currency]["total_discount_savings"] += discount_amount
            totals_by_currency[currency]["total_discounted_payable"] += payable_total
            totals_by_currency[currency]["invoice_count"] += 1

        formatted_totals = {
            curr: {
                "currency": curr,
                "total_gross": str(data["total_gross"].quantize(Decimal("0.01"))),
                "total_discount_savings": str(data["total_discount_savings"].quantize(Decimal("0.01"))),
                "total_discounted_payable": str(data["total_discounted_payable"].quantize(Decimal("0.01"))),
                "invoice_count": data["invoice_count"],
            }
            for curr, data in totals_by_currency.items()
        }

        return {
            "calculated_count": len(calculated_items),
            "items": calculated_items,
            "totals_by_currency": formatted_totals,
        }

    @classmethod
    def aggregate_column(cls, values: list, operation: str = "sum") -> Dict[str, Any]:
        """Compute exact Decimal aggregations (sum, average, min, max, variance) over a numeric list."""
        if not values:
            return {"operation": operation, "count": 0, "result": "0.00"}

        dec_values = []
        for v in values:
            try:
                dec = Decimal(str(v).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip())
                dec_values.append(dec)
            except Exception:
                continue

        if not dec_values:
            return {"operation": operation, "count": 0, "result": "0.00"}

        op = operation.lower().strip()
        count = len(dec_values)

        if op in ("sum", "total"):
            res = sum(dec_values).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif op in ("avg", "average", "mean"):
            res = (sum(dec_values) / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif op == "min":
            res = min(dec_values).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif op == "max":
            res = max(dec_values).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif op in ("var", "variance"):
            mean = sum(dec_values) / Decimal(count)
            res = (sum((x - mean) ** 2 for x in dec_values) / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            raise ValueError(f"Unsupported aggregate operation: '{operation}'")

        return {
            "operation": op,
            "count": count,
            "result": str(res),
        }
