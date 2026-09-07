"""
Table-derived extraction helpers for RuleBasedExtractor.

Extracts net amounts, tax amounts, and gross invoice amounts from
reconstructed table line-item data and summary rows when available.
"""
from typing import Any, Dict, Optional

from app.extraction.base import ExtractedField
from app.extraction.primitives import normalize_amount


def extract_amount_from_table(
    table_data: Optional[Dict[str, Any]],
    role: str,
) -> ExtractedField:
    """
    Extract or calculate summary amounts (net_amount, tax_amount, invoice_amount)
    from reconstructed table line items.

    Deterministic logic:
    - 'net_amount': Sum of line item net amounts if all items have valid net amounts.
    - 'invoice_amount': Sum of line item gross amounts if present; otherwise sum(net) + tax.
    - 'tax_amount': If gross and net totals exist, calculate gross - net; or sum(net * vat_rate).
    """
    if not table_data:
        return ExtractedField(value=None, confidence=0.0)

    line_items = table_data.get("line_items") or []
    if not line_items:
        return ExtractedField(value=None, confidence=0.0)

    # Calculate net total from line items
    net_values = []
    for item in line_items:
        raw_net = item.get("net_amount")
        norm_net = normalize_amount(raw_net) if raw_net else None
        if norm_net is not None:
            try:
                net_values.append(float(norm_net))
            except ValueError:
                pass

    # Calculate gross total from line items
    gross_values = []
    for item in line_items:
        raw_gross = item.get("gross_amount")
        norm_gross = normalize_amount(raw_gross) if raw_gross else None
        if norm_gross is not None:
            try:
                gross_values.append(float(norm_gross))
            except ValueError:
                pass

    total_net = sum(net_values) if (net_values and len(net_values) == len(line_items)) else None
    total_gross = sum(gross_values) if (gross_values and len(gross_values) == len(line_items)) else None

    if role == "net_amount" and total_net is not None and total_net > 0:
        return ExtractedField(
            value=f"{total_net:.2f}",
            confidence=0.82,
            matched_text="Table Reconstructed Line Items Net Total",
        )

    if role in ("invoice_amount", "gross_amount") and total_gross is not None and total_gross > 0:
        return ExtractedField(
            value=f"{total_gross:.2f}",
            confidence=0.82,
            matched_text="Table Reconstructed Line Items Gross Total",
        )

    if role == "tax_amount":
        if total_gross is not None and total_net is not None and total_gross >= total_net:
            tax_diff = total_gross - total_net
            if tax_diff > 0:
                return ExtractedField(
                    value=f"{tax_diff:.2f}",
                    confidence=0.80,
                    matched_text="Table Reconstructed Derived Tax Total",
                )

    return ExtractedField(value=None, confidence=0.0)
