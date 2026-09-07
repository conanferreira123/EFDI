"""
Non-destructive normalization layer for OCR text and structured table data.

Separates raw recognized values from normalized representations.
Never mutates or overwrites raw OCR evidence.
"""
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
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
    return re.sub(r"\s+", " ", text).strip()


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
    Handles thousands separators (comma, dot, space), adjacent punctuation, and decimal points.
    Preserves raw value intact while returning parsed float.
    """
    if not val_str:
        return None
    cleaned = normalize_whitespace(val_str)
    # Normalize adjacent punctuation artifacts e.g. '52.,083.00' -> '52,083.00' or '56.,912.90' -> '56,912.90'
    cleaned = re.sub(r"\.,|\,\.", ",", cleaned)
    # Remove currency symbols and extraneous chars except digits, dots, commas, minus
    cleaned = re.sub(r"[^\d.,\-]", "", cleaned)
    if not cleaned or cleaned == "-":
        return None

    # Handle European vs US number formats
    # e.g., '1.676.976,00' vs '1,676,976.00' vs '667.080.00' (OCR dot confusion)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(".") > cleaned.rfind(","):
            # 1,234.56 format
            cleaned = cleaned.replace(",", "")
        else:
            # 1.234,56 format
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        # Check if comma is decimal (e.g. '12,50' or '1,000')
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2:
            # Multiple dots e.g., '667.080.00' -> last part is decimal
            cleaned = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def parse_percentage(pct_str: Optional[str]) -> Optional[float]:
    """Parse VAT / Tax percentage string into decimal fraction (e.g. '10%' -> 0.10, '18' -> 0.18)."""
    if not pct_str:
        return None
    cleaned = normalize_whitespace(pct_str).replace("%", "").strip()
    num = parse_numeric(cleaned)
    if num is not None:
        return num / 100.0 if num > 1.0 else num
    return None


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
    """Normalize a StructuredLineItem or line item dictionary."""
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

    raw_vat = d.get("vat_rate")
    norm_vat = parse_percentage(raw_vat)

    raw_gross = d.get("gross_amount")
    norm_gross = parse_numeric(raw_gross)

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
        raw_gross_amount=raw_gross,
        normalized_gross_amount=norm_gross,
        confidence=conf,
        raw_blocks=raw_blocks,
    )


def normalize_table_data(table_data: Dict[str, Any]) -> List[NormalizedLineItem]:
    """Convert all line items in a reconstructed table to normalized representations."""
    items = table_data.get("line_items", [])
    return [normalize_line_item(itm) for itm in items]
