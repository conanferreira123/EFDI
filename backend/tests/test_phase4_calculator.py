"""Phase 4 Unit Tests: Batch Financial Calculator and Aggregations.

Tests batch discount calculations, column aggregations, and currency safety in the calculator.
"""
from decimal import Decimal
import json
import pytest

from app.rag.financial_calculator import FinancialCalculator
from app.rag.tools.calculator_tool import FinancialCalculatorTool


def test_batch_calculate_discounts_multi_currency():
    items = [
        {"invoice_id": f"INV-USD-{i}", "gross_amount": 1000.00, "discount_percentage": "2%", "currency": "USD"}
        for i in range(10)
    ] + [
        {"invoice_id": f"INV-EUR-{i}", "gross_amount": 2000.00, "discount_percentage": "0.03", "currency": "EUR"}
        for i in range(5)
    ]

    res = FinancialCalculator.batch_calculate_discounts(items)
    assert res["calculated_count"] == 15
    assert "USD" in res["totals_by_currency"]
    assert "EUR" in res["totals_by_currency"]

    usd_totals = res["totals_by_currency"]["USD"]
    assert usd_totals["invoice_count"] == 10
    assert usd_totals["total_gross"] == "10000.00"
    assert usd_totals["total_discount_savings"] == "200.00"
    assert usd_totals["total_discounted_payable"] == "9800.00"

    eur_totals = res["totals_by_currency"]["EUR"]
    assert eur_totals["invoice_count"] == 5
    assert eur_totals["total_gross"] == "10000.00"
    # 3% of 10,000 = 300.00
    assert eur_totals["total_discount_savings"] == "300.00"
    assert eur_totals["total_discounted_payable"] == "9700.00"


def test_batch_calculate_discounts_percentage_formats():
    items = [
        {"invoice_id": 1, "gross_amount": 100.00, "discount_percentage": "2%"},
        {"invoice_id": 2, "gross_amount": 100.00, "discount_percentage": "0.02"},
        {"invoice_id": 3, "gross_amount": 100.00, "discount_percentage": 2},
        {"invoice_id": 4, "gross_amount": 100.00, "discount_percentage": 2.0},
    ]
    res = FinancialCalculator.batch_calculate_discounts(items)
    assert res["calculated_count"] == 4
    for itm in res["items"]:
        assert itm["discount_percentage"] == "2.00%"
        assert itm["discount_savings"] == "2.00"
        assert itm["discounted_payable_total"] == "98.00"


def test_aggregate_column():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    sum_res = FinancialCalculator.aggregate_column(values, operation="sum")
    assert sum_res["result"] == "150.00"

    avg_res = FinancialCalculator.aggregate_column(values, operation="average")
    assert avg_res["result"] == "30.00"

    min_res = FinancialCalculator.aggregate_column(values, operation="min")
    assert min_res["result"] == "10.00"

    max_res = FinancialCalculator.aggregate_column(values, operation="max")
    assert max_res["result"] == "50.00"


def test_financial_calculator_tool_batch_and_aggregate():
    tool = FinancialCalculatorTool()

    # Batch discounts via tool
    tool_batch_res = tool._run(
        action="batch_discounts",
        items=[
            {"invoice_id": "I1", "gross_amount": "5000", "discount_percentage": "2%", "currency": "USD"},
            {"invoice_id": "I2", "gross_amount": "10000", "discount_percentage": "3%", "currency": "USD"},
        ],
    )
    assert "Financial Calculation Result (Batch Discounts):" in tool_batch_res
    assert "15000.00" in tool_batch_res  # total gross
    assert "400.00" in tool_batch_res    # 100 + 300 = 400

    # Aggregate via tool
    tool_agg_res = tool._run(
        action="aggregate_column",
        values=[100, 200, 300],
        operation="sum",
    )
    assert "Financial Calculation Result (Aggregate):" in tool_agg_res
    assert "600.00" in tool_agg_res
