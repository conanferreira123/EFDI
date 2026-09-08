"""
Non-destructive normalization layer for OCR text and structured table data.

Separates raw recognized values from normalized representations.
Never mutates or overwrites raw OCR evidence.
"""
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


@dataclass
class NormalizedLineItem:
    """A normalized invoice line item alongside its raw OCR evidence."""
    raw_item_number: Optional[str] = None
    normalized_item_number: Optional[int] = None

    raw_description: str = ""
    normalized_description: str = ""

    raw_quantity: Optional[str] = None
    normalized_quantity: Optional[float] = None

    raw_unit: Optional[str] = None
    normalized_unit: Optional[str] = None

    raw_unit_price: Optional[str] = None
    normalized_unit_price: Optional[float] = None

    raw_net_amount: Optional[str] = None
    normalized_net_amount: Optional[float] = None

    raw_vat_rate: Optional[str] = None
    normalized_vat_rate: Optional[float] = None  # e.g., 0.10 for 10%
    vat_interpretation: Optional[str] = None     # e.g., "10%"
    vat_normalization_evidence: Optional[Dict[str, Any]] = None
    vat_normalization_confidence: Optional[float] = None

    raw_gross_amount: Optional[str] = None
    normalized_gross_amount: Optional[float] = None

    confidence: float = 1.0
    raw_blocks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedInvoiceData:
    """Document-level normalized fields and line items."""
    raw_invoice_number: Optional[str] = None
    normalized_invoice_number: Optional[str] = None

    raw_issue_date: Optional[str] = None
    normalized_issue_date: Optional[str] = None  # ISO format YYYY-MM-DD

    raw_seller_name: Optional[str] = None
    normalized_seller_name: Optional[str] = None

    raw_buyer_name: Optional[str] = None
    normalized_buyer_name: Optional[str] = None

    raw_currency: Optional[str] = None
    normalized_currency: Optional[str] = None

    line_items: List[NormalizedLineItem] = field(default_factory=list)

    raw_subtotal: Optional[str] = None
    normalized_subtotal: Optional[float] = None

    raw_total_vat: Optional[str] = None
    normalized_total_vat: Optional[float] = None

    raw_grand_total: Optional[str] = None
    normalized_grand_total: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["line_items"] = [item.to_dict() for item in self.line_items]
        return res


def normalize_whitespace(text: Optional[str]) -> str:
    """Collapse multiple spaces, tabs, and trim edges."""
    if not text:
        return ""
    # Replace non-breaking spaces \u00a0 with standard space
    cleaned = text.replace("\u00a0", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_unit(unit_str: Optional[str]) -> Optional[str]:
    """Normalize common unit of measure tokens (e.g., 'pCs', 'PCS' -> 'pcs')."""
    if not unit_str:
        return None
    cleaned = normalize_whitespace(unit_str).lower()
    unit_map = {
        "pcs": "pcs",
        "pc": "pcs",
        "piece": "pcs",
        "pieces": "pcs",
        "each": "each",
        "ea": "each",
        "stk": "pcs",
        "stk.": "pcs",
        "kg": "kg",
        "kgs": "kg",
        "g": "g",
        "m": "m",
        "mtr": "m",
        "hrs": "hours",
        "hr": "hours",
        "hours": "hours",
        "box": "box",
        "boxes": "box",
        "set": "set",
        "sets": "set",
    }
    return unit_map.get(cleaned, cleaned)


def parse_numeric(val_str: Optional[str]) -> Optional[float]:
    """
    Parse a numeric string from OCR into a float.
    Robustly handles European and US number formats:
      - European space thousands + comma decimal: '1 394,67' -> 1394.67, '5 640,17' -> 5640.17
      - European dot thousands + comma decimal: '1.394,67' -> 1394.67, '1.676.976,00' -> 1676976.00
      - US comma thousands + dot decimal: '1,394.67' -> 1394.67, '1,676,976.00' -> 1676976.00
      - Lone comma decimal: '689,70' -> 689.70, '3,00' -> 3.00, ',00' -> 0.00
      - Lone dot decimal: '689.70' -> 689.70
      - Leading/trailing currency symbols: '$ 5 640,17' -> 5640.17
      - Punctuation artifacts e.g. '52.,083.00' -> 52083.00
    """
    if not val_str:
        return None
    raw = normalize_whitespace(val_str)
    if not raw:
        return None

    # Strip leading currency words/symbols with optional dot (e.g. 'Rs. ', 'EUR ', 'USD ', '$ ', 'CHF ')
    raw = re.sub(r"^[A-Za-z\$\€\£\¥\s\:]+(\.\s*)?", "", raw).strip()
    # Strip currency symbols and letters (e.g. $, EUR, USD, CHF, £, ¥)
    cleaned = re.sub(r"[^\d.,\-\s]", "", raw).strip()
    if not cleaned or cleaned == "-":
        return None

    # Normalize adjacent punctuation artifacts e.g. '52.,083.00' -> '52,083.00'
    cleaned = re.sub(r"\.,|\,\.", ",", cleaned)

    # Handle European space thousand separators: '1 394,67' or '5 640.17'
    # Check if space is separating digit groups (e.g., '1 394' or '5 640')
    if " " in cleaned:
        # If space exists between digits: remove thousand separator space
        cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned).strip()

    if not cleaned:
        return None

    # Handle leading comma decimal without leading zero: ',00' -> '0.00' or ',70' -> '0.70'
    if cleaned.startswith(",") or cleaned.startswith("."):
        cleaned = "0" + cleaned
    elif cleaned.startswith("-,") or cleaned.startswith("-."):
        cleaned = "-0" + cleaned[1:]

    # Distinguish decimal comma vs decimal dot vs thousands separators
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(".") > cleaned.rfind(","):
            # Format: 1,234.56 (US standard)
            cleaned = cleaned.replace(",", "")
        else:
            # Format: 1.234,56 (European standard)
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        parts = cleaned.split(",")
        # If single comma and last segment has 1 or 2 digits (or standard 3 decimal digits if preceded by no dots)
        if len(parts) == 2:
            # e.g. '689,70' or '3,00' or '1394,67'
            cleaned = parts[0] + "." + parts[1]
        else:
            # Multiple commas: e.g. '1,676,976'
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2:
            # Multiple dots e.g., '1.676.976' or '667.080.00' -> last part is decimal if 2 digits
            if len(parts[-1]) in (1, 2):
                cleaned = "".join(parts[:-1]) + "." + parts[-1]
            else:
                cleaned = "".join(parts)

    try:
        return round(float(cleaned), 4)
    except (ValueError, TypeError):
        return None


# Recognized standard international VAT / Tax rates (fractional form)
STANDARD_TAX_RATES = [
    0.0, 0.05, 0.06, 0.07, 0.077, 0.08, 0.081, 0.10, 0.12, 0.13, 0.14,
    0.15, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.27
]


def interpret_vat_rate(
    pct_str: Optional[str],
    net_amount: Optional[float] = None,
    gross_amount: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str], Optional[Dict[str, Any]], Optional[float]]:
    """
    Parse and interpret a VAT / Tax percentage string into canonical float fraction (e.g. '10%' -> 0.10)
    with evidence-based interpretation for OCR-corrupted percentage tokens (e.g. '1090' in VAT column).

    Returns:
      (normalized_vat_rate, interpretation_str, evidence_dict, confidence)

    Rule: Never blindly convert '1090' -> 0.10 without contextual / mathematical evidence.
    """
    if not pct_str:
        return None, None, None, None

    raw_clean = normalize_whitespace(pct_str)
    if not raw_clean:
        return None, None, None, None

    # Case 1: Explicit percentage symbol present (e.g. '10%', '10 %', '10,0%', '10,00 %', '18%')
    if "%" in raw_clean:
        clean_num = raw_clean.replace("%", "").strip()
        num = parse_numeric(clean_num)
        if num is not None:
            fraction = round(num / 100.0 if num > 1.0 else num, 4)
            interp = f"{int(round(fraction * 100))}%" if fraction > 0 else "0%"
            evidence = {
                "source": "explicit_percentage_symbol",
                "raw_text": raw_clean,
                "parsed_percentage": fraction,
            }
            return fraction, interp, evidence, 1.0

    # Case 2: Standard numeric percentage string in VAT column (e.g. '10', '18', '20', '0.10')
    direct_num = parse_numeric(raw_clean)
    if direct_num is not None:
        if direct_num in (0.0, 0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.27):
            fraction = round(direct_num, 4)
            return fraction, f"{int(round(fraction * 100))}%", {"source": "direct_fraction_match"}, 0.95
        if direct_num in (0.0, 5.0, 7.0, 8.0, 10.0, 12.0, 15.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 27.0):
            fraction = round(direct_num / 100.0, 4)
            return fraction, f"{int(round(fraction * 100))}%", {"source": "direct_percentage_integer"}, 0.95

    # Case 3: Evidence-based interpretation for OCR-corrupted glyph tokens (e.g. '1090', '109', '1000' in VAT column)
    # Checks financial reconciliation with Net and Gross amounts on the same line item
    if net_amount is not None and gross_amount is not None and net_amount > 0 and gross_amount >= net_amount:
        implied_rate = (gross_amount - net_amount) / net_amount

        # Find closest standard tax rate
        closest_rate = min(STANDARD_TAX_RATES, key=lambda r: abs(r - implied_rate))
        rate_diff = abs(closest_rate - implied_rate)

        # Require high mathematical precision (within 0.5% margin)
        if rate_diff <= 0.005:
            expected_pct_int = int(round(closest_rate * 100))
            expected_prefix = str(expected_pct_int)

            # Morphological check: Does the raw OCR string start with or correspond to the expected percentage digits?
            # e.g., '1090' starts with '10' where '90' is OCR distortion of '%' glyph ('/0' or '0/0')
            if raw_clean.startswith(expected_prefix):
                fraction = round(closest_rate, 4)
                interp = f"{expected_pct_int}%"
                evidence = {
                    "source": "financial_reconciliation",
                    "raw_ocr_token": raw_clean,
                    "net_amount": net_amount,
                    "gross_amount": gross_amount,
                    "calculated_implied_rate": round(implied_rate, 4),
                    "matched_standard_rate": fraction,
                    "reconciliation_formula": f"Net ({net_amount}) * (1 + {interp}) = {round(net_amount * (1 + fraction), 2)} vs Gross ({gross_amount})",
                }
                return fraction, interp, evidence, 0.98

    # No reliable evidence to interpret: Retain raw value without guessing
    return None, None, None, None


def parse_percentage(
    pct_str: Optional[str],
    net_amount: Optional[float] = None,
    gross_amount: Optional[float] = None,
) -> Optional[float]:
    """
    Parse a VAT / Tax percentage string into canonical float fraction (e.g. '10%' -> 0.10).
    For full interpretation tuple (rate, interpretation, evidence, confidence), use interpret_vat_rate().
    """
    fraction, _, _, _ = interpret_vat_rate(pct_str, net_amount=net_amount, gross_amount=gross_amount)
    return fraction


def parse_date(date_str: Optional[str]) -> Optional[str]:
    """
    Parse common date formats (DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, etc.)
    and return ISO format string 'YYYY-MM-DD'.
    """
    if not date_str:
        return None
    cleaned = normalize_whitespace(date_str)
    date_patterns = [
        r"%d/%m/%Y",
        r"%d-%m-%Y",
        r"%Y-%m-%d",
        r"%Y/%m/%d",
        r"%d.%m.%Y",
        r"%d %b %Y",
        r"%d %B %Y",
        r"%b %d, %Y",
        r"%B %d, %Y",
    ]
    for pattern in date_patterns:
        try:
            dt = datetime.strptime(cleaned, pattern)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_line_item(item: Any) -> NormalizedLineItem:
    """Normalize a StructuredLineItem or line item dictionary with evidence-based resolution."""
    if hasattr(item, "to_dict"):
        d = item.to_dict()
    elif isinstance(item, dict):
        d = item
    else:
        d = {}

    raw_item_no = d.get("item_number")
    norm_item_no = None
    if raw_item_no:
        clean_no = re.sub(r"[^\d]", "", str(raw_item_no))
        if clean_no.isdigit():
            norm_item_no = int(clean_no)

    raw_desc = d.get("description", "")
    norm_desc = normalize_whitespace(raw_desc)

    raw_qty = d.get("quantity")
    norm_qty = parse_numeric(raw_qty)

    raw_unit = d.get("unit")
    norm_unit = normalize_unit(raw_unit)

    raw_price = d.get("unit_price")
    norm_price = parse_numeric(raw_price)

    raw_net = d.get("net_amount")
    norm_net = parse_numeric(raw_net)

    raw_gross = d.get("gross_amount")
    norm_gross = parse_numeric(raw_gross)

    raw_vat = d.get("vat_rate")
    norm_vat, vat_interp, vat_ev, vat_conf = interpret_vat_rate(
        raw_vat, net_amount=norm_net, gross_amount=norm_gross
    )

    conf = float(d.get("confidence", 1.0))
    raw_blocks = d.get("raw_blocks", [])

    return NormalizedLineItem(
        raw_item_number=raw_item_no,
        normalized_item_number=norm_item_no,
        raw_description=raw_desc,
        normalized_description=norm_desc,
        raw_quantity=raw_qty,
        normalized_quantity=norm_qty,
        raw_unit=raw_unit,
        normalized_unit=norm_unit,
        raw_unit_price=raw_price,
        normalized_unit_price=norm_price,
        raw_net_amount=raw_net,
        normalized_net_amount=norm_net,
        raw_vat_rate=raw_vat,
        normalized_vat_rate=norm_vat,
        vat_interpretation=vat_interp,
        vat_normalization_evidence=vat_ev,
        vat_normalization_confidence=vat_conf,
        raw_gross_amount=raw_gross,
        normalized_gross_amount=norm_gross,
        confidence=conf,
        raw_blocks=raw_blocks,
    )


def normalize_table_data(table_data: Dict[str, Any]) -> List[NormalizedLineItem]:
    """Convert all line items in a reconstructed table to normalized representations."""
    items = table_data.get("line_items", [])
    return [normalize_line_item(itm) for itm in items]
