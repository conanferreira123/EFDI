"""
Tests for app.ocr.markdown_table_parser.

Validates that Markdown tables produced by PaddleOCR-VL are parsed accurately
into structured in-memory table_data without coordinate heuristics, and that
trailing tax/GST summaries are never captured as line items.
"""
from app.ocr.markdown_table_parser import parse_markdown_table, _match_column_name


def test_match_column_name():
    assert _match_column_name("Description") == "description"
    assert _match_column_name("Item Description") == "description"
    assert _match_column_name("QTY") == "quantity"
    assert _match_column_name("Quantity") == "quantity"
    assert _match_column_name("Unit Price") == "unit_price"
    assert _match_column_name("Net Amount") == "net_amount"
    assert _match_column_name("VAT %") == "vat_rate"
    assert _match_column_name("GST%") == "vat_rate"
    assert _match_column_name("Gross Amount") == "gross_amount"
    assert _match_column_name("Pos.") == "item_number"


def test_parse_standard_markdown_table():
    md_text = """
=== PAGE 1 ===
Acme Corp Invoice INV-2026-101

| # | Description | Qty | Unit | Unit Price | Net Amount | VAT % | Gross Amount |
|---|-------------|-----|------|------------|------------|-------|--------------|
| 1 | High Performance Bearings | 10 | pcs | 45.00 | 450.00 | 10% | 495.00 |
| 2 | Heavy Duty Hydraulic Seal  | 2  | set | 120.00 | 240.00 | 10% | 264.00 |

Subtotal: 690.00
Tax: 69.00
Grand Total: 759.00
"""
    result = parse_markdown_table(md_text)
    assert result["line_items_count"] == 2
    assert len(result["line_items"]) == 2

    item1 = result["line_items"][0]
    assert item1["item_number"] == "1"
    assert item1["description"] == "High Performance Bearings"
    assert item1["quantity"] == "10"
    assert item1["unit"] == "pcs"
    assert item1["unit_price"] == "45.00"
    assert item1["net_amount"] == "450.00"
    assert item1["vat_rate"] == "10%"
    assert item1["gross_amount"] == "495.00"

    item2 = result["line_items"][1]
    assert item2["item_number"] == "2"
    assert item2["description"] == "Heavy Duty Hydraulic Seal"
    assert item2["quantity"] == "2"


def test_parse_markdown_table_tax_non_leakage():
    """
    Asserts that tax schedules / GST summaries appearing outside the Markdown table
    are NEVER captured as line items.
    """
    md_text = """
| Pos | Particulars | Quantity | Rate | Taxable Amount | GST % | Total Amount |
| --- | ----------- | -------- | ---- | -------------- | ----- | ------------ |
| 1   | Industrial Lubricant 5L | 4 | 50.00 | 200.00 | 18% | 236.00 |

Tax Breakdown Schedule:
CGST (9%): 18.00
SGST (9%): 18.00
Total GST Amount: 36.00
Grand Total Payable: 236.00
"""
    result = parse_markdown_table(md_text)
    assert result["line_items_count"] == 1
    item = result["line_items"][0]
    assert item["description"] == "Industrial Lubricant 5L"
    assert item["net_amount"] == "200.00"
    assert item["gross_amount"] == "236.00"

    # Ensure none of the tax breakdown lines leaked into line items
    all_descriptions = [i["description"] for i in result["line_items"]]
    assert not any("CGST" in d for d in all_descriptions)
    assert not any("SGST" in d for d in all_descriptions)
    assert not any("Total GST" in d for d in all_descriptions)


def test_parse_empty_or_no_table():
    assert parse_markdown_table("")["line_items_count"] == 0
    assert parse_markdown_table("Just some general text without tables.")["line_items_count"] == 0
