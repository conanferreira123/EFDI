"""
Shared extraction primitives.

Most fields in this domain follow a "Label: Value" pattern in OCR text
(e.g. "Invoice Number: INV-2026-001", "PO Number PO-2026-789"). This
module provides a generic label-based extractor plus normalization
helpers for dates and amounts, so each per-type extractor module
(invoice_extractors.py, etc.) just declares which labels to look for
per field rather than re-implementing pattern matching each time.
"""
import re
from datetime import datetime

from app.extraction.base import ExtractedField

# The complete set of every label string used anywhere across every
# document type's extractor (app/extraction/type_extractors.py).
# Critical for _VALUE_CAPTURE below: a captured value must stop before
# the NEXT label begins, and the only reliable way to detect "a label
# is starting here" is to check against the real, finite set of labels
# this system actually uses -- not a generic heuristic (tried and
# discarded: capitalization patterns, word-count guesses, colon
# proximity alone -- all produced wrong captures on real OCR text).
#
# This was added after a real bug: OCR engines like EasyOCR don't
# preserve the original 2D page layout, so labels and values that were
# visually separated on the source document (e.g. "Bill To:" and
# "Ship To:" in different columns) end up adjacent on a single
# flattened line of text with only single spaces between them. The
# original capture pattern's "stop at 2+ spaces or newline" heuristic
# assumed well-formatted text and silently captured one label's
# leftover text as another field's value.
#
# IMPORTANT: when adding a new label to any per-type extractor in
# type_extractors.py, add it here too, or it won't be recognized as a
# stop-boundary for OTHER fields' captures (it will still work as a
# label to search FOR, just not as a boundary to stop AT).
KNOWN_LABELS = [
    "Deposit Reference Number", "Manager Approval Status", "Letter of Credit Number",
    "Trade Reference Number", "GL Account Description", "Reconciliation Status",
    "Purchase Order Number", "Transaction Reference", "Sales Invoice Number",
    "Journal Entry Number", "Reimbursement Amount", "Account Description",
    "MSI Invoice Number", "PIS Deposit Amount", "MSI Invoice Amount",
    "Sales Invoice Date", "Pay In Slip Number", "Shipment Reference",
    "Transaction Amount", "Advance Percentage", "PIS Customer Name",
    "Validation Status", "Processing Status", "Travel Start Date",
    "Document Category", "PIS Customer Code", "Transaction Type",
    "Requested Amount", "Reference Number", "MSI Invoice Date",
    "Expense Category", "Beneficiary Name", "Trade Reference",
    "Document Source", "Travel End Date", "GL Account Code",
    "Approved Amount", "Transaction Ref", "Approval Status",
    "Account Number", "Invoice Amount", "Deposit Amount",
    "Invoice Number", "Document Date", "Profit Center",
    "Payment Terms", "Customer Name", "Advice Amount",
    "Employee Name", "Vertical Code", "Credit Amount",
    "Customer Code", "Advice Number", "Location Code",
    "Employee Code", "Profit Centre", "Posting Date",
    "Total Amount", "Deposit Date", "Issuing Bank",
    "Invoice Date", "Claim Number", "Company Name",
    "Claim Amount", "Company Code", "Debit Amount",
    "Cost Center", "Cost Centre", "Vendor Name",
    "Expiry Date", "Vendor Code", "Beneficiary",
    "Fiscal Year", "Employee ID", "Advice Date",
    "Document ID", "Claim Date", "Tax Amount",
    "Net Amount", "Value Date", "GRN Number",
    "GL Account", "Invoice No", "SRN Number",
    "Account No", "GST Amount", "Issue Date",
    "Doc Source", "PIS Number", "Advance %",
    "LC Number", "Invoice #", "Advice No",
    "LC Amount", "Bank Name", "PO Number",
    "JE Number", "Bar Code", "Employee",
    "Subtotal", "Claim No", "Customer",
    "Due Date", "LOC CODE", "Currency",
    "PIS Date", "Doc Date", "CO CODE",
    "Bill To", "Country", "Purpose",
    "Barcode", "Doc ID", "COCODE",
    "Vendor", "Credit", "GRN No",
    "SRN No", "DOCID", "Total",
    "PO No", "Debit", "JE No",
    "Date", "GRN", "Tax",
    "SRN", "FY", "Ship To",
    "Ship Mode", "Order ID",
]

# Longest-first so multi-word labels are checked before any shorter
# label that might be a substring/prefix of them.
_KNOWN_LABELS_SORTED = sorted(set(KNOWN_LABELS), key=len, reverse=True)

# \b word boundaries around each alternative -- without this, searching
# for "Total" would also match inside "Subtotal" (confirmed as a real
# failure mode during testing: "Subtotal: 848.71 ... Total: 950.10"
# incorrectly returned 848.71 for a "Total" search before this was added).
_NEXT_LABEL_BOUNDARY = "|".join(r"\b" + re.escape(label) + r"\b" for label in _KNOWN_LABELS_SORTED)

# Matches "Label: Value" or "Label - Value" or "Label  Value". The
# value is captured non-greedily and stops at the FIRST of: a run of
# 2+ spaces, a newline, the start of any other known label (the fix
# described above), or the end of the string.
_VALUE_CAPTURE = (
    # Optional trailing parenthetical right after the label (e.g.
    # "Tax Amount (GST)") -- without this, the parenthetical itself
    # gets captured as if it were the value, since there's no
    # colon/dash to signal "cross to the next line for the real value."
    r"(?:\s*\([^)\n]{0,30}\))?"
    # '=' included alongside ':'/'-' -- OCR engines sometimes misread
    # a colon glyph as an equals sign; without this the stray '='
    # itself gets captured as the "value."
    r"[:\-=]?\s*([^\n]*?)"
    # Next-label boundary requires the separator to be followed by
    # whitespace/newline/end (not immediately by more alnum content).
    # Without this, an ID value like "GRN-1123" gets misread as "the
    # label GRN, followed by a '-' separator" -- since "GRN" is itself
    # a known label -- causing the capture to stop before the value
    # even starts.
    r"(?=\s{2,}|\n|\s*(?:" + _NEXT_LABEL_BOUNDARY + r")\s*[:\-](?:\s|$)|$)"
)


def extract_by_labels(
    text: str, labels: list[str], *, max_value_length: int = 80
) -> ExtractedField:
    """
    Search for any of the given labels (tried in order; first match
    wins) followed by a value, and return it as an ExtractedField.
    Confidence is higher for earlier/more specific labels in the list
    (callers should order labels from most to least specific) and
    slightly reduced for very long captured values (a sign the regex
    over-matched into unrelated trailing text).
    """
    for i, label in enumerate(labels):
        pattern = r"\b" + re.escape(label) + r"\b" + _VALUE_CAPTURE
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip(":-").strip()
            if not value:
                continue

            base_confidence = 0.9 - (i * 0.1)  # later labels in the list are weaker signals
            if len(value) > max_value_length:
                value = value[:max_value_length]
                base_confidence -= 0.2

            return ExtractedField(
                value=value,
                confidence=round(max(base_confidence, 0.3), 2),
                matched_text=match.group(0).strip(),
            )

    return ExtractedField(value=None, confidence=0.0)


# Common date formats seen on financial documents. Tried in order;
# first successful parse wins. Includes both day-first (common outside
# the US, and explicitly relevant given GST-related fields elsewhere in
# this codebase) and ISO formats.
_DATE_FORMATS = [
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d %B %Y", "%d %b %Y",
    "%B %d, %Y", "%b %d, %Y",
    "%B %d %Y", "%b %d %Y",
    "%m-%d-%Y", "%m/%d/%Y",
    # Dash-separated day-month(name)-year (e.g. "05-Jun-2026") -- a
    # common format on Indian business documents that was previously
    # entirely unhandled, causing every such date to fail normalization
    # despite being captured correctly.
    "%d-%b-%Y", "%d-%B-%Y",
]
_DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}-[A-Za-z]{3,9}-\d{4})\b"
)
# Strips ordinal suffixes ("21st" -> "21", "3rd" -> "3") so dates typed
# the way people actually write them (e.g. "21st March 2012") match
# the patterns/formats above, none of which account for ordinals.
_ORDINAL_SUFFIX = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)


def normalize_date(raw_value: str | None) -> str | None:
    """
    Attempt to parse a raw extracted date string into ISO format
    (YYYY-MM-DD). Returns None if no recognizable date pattern is
    found, rather than guessing -- a downstream validation step
    (Phase 7) is the right place to flag an unparseable date, not this
    extraction layer.
    """
    if not raw_value:
        return None
    cleaned = _ORDINAL_SUFFIX.sub("", raw_value)
    match = _DATE_PATTERN.search(cleaned)
    candidate = match.group(0) if match else cleaned
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate.strip(), fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


_AMOUNT_PATTERN = re.compile(r"[\d,]+\.?\d*")


def normalize_amount(raw_value: str | None) -> str | None:
    """
    Strip currency symbols/thousands-separators from a raw extracted
    amount string and return a plain numeric string (e.g.
    "Rs. 15,000.00" -> "15000.00", "1 394,67" -> "1394.67",
    "5 640,17" -> "5640.17", "689,70" -> "689.70"). Returns None if no
    digits are present at all.
    """
    if not raw_value:
        return None
    raw_str = str(raw_value).strip()
    from app.ocr.normalization import parse_numeric
    num = parse_numeric(raw_str)
    if num is None:
        return None
    if "." in raw_str or "," in raw_str:
        if raw_str.endswith(".00") or raw_str.endswith(",00"):
            return f"{num:.2f}"
        if num == int(num) and not (raw_str.endswith(".0") or raw_str.endswith(",0")):
            return str(int(num))
        return f"{num:.2f}"
    return str(int(num)) if num == int(num) else f"{num:.2f}"


_CURRENCY_LOOKUP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "rs": "INR",
    "rs.": "INR",
    "inr": "INR",
    "usd": "USD",
    "eur": "EUR",
    "gbp": "GBP",
    "jpy": "JPY",
    "¥": "JPY",
    "c$": "CAD",
    "cad": "CAD",
    "a$": "AUD",
    "aud": "AUD",
    "chf": "CHF",
}


def normalize_currency(raw_value: str | None) -> str | None:
    """Normalize currency symbols, abbreviations, and names to 3-letter ISO code."""
    if not raw_value:
        return None
    cleaned = str(raw_value).strip()
    lower_cleaned = cleaned.lower()
    if lower_cleaned in _CURRENCY_LOOKUP:
        return _CURRENCY_LOOKUP[lower_cleaned]
    for sym, code in _CURRENCY_LOOKUP.items():
        if sym in lower_cleaned:
            return code
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned.upper()
    return None


def extract_date_field(text: str, labels: list[str]) -> ExtractedField:

    """Extract a field by label, then normalize the captured value as a date."""
    raw_field = extract_by_labels(text, labels)
    if not raw_field.is_found:
        return raw_field

    normalized = normalize_date(raw_field.value)
    if normalized is None:
        # Found a label match but couldn't parse a date out of it --
        # keep the raw matched text but reduce confidence sharply, since
        # this is now a candidate for a reviewer to fix manually rather
        # than a clean machine-readable value.
        return ExtractedField(
            value=raw_field.value,
            confidence=round(raw_field.confidence * 0.4, 2),
            matched_text=raw_field.matched_text,
        )
    return ExtractedField(
        value=normalized, confidence=raw_field.confidence, matched_text=raw_field.matched_text
    )


def extract_amount_field(text: str, labels: list[str]) -> ExtractedField:
    """Extract a field by label, then normalize the captured value as a numeric amount."""
    raw_field = extract_by_labels(text, labels)
    if not raw_field.is_found:
        return raw_field

    normalized = normalize_amount(raw_field.value)
    if normalized is None:
        return ExtractedField(
            value=raw_field.value,
            confidence=round(raw_field.confidence * 0.4, 2),
            matched_text=raw_field.matched_text,
        )
    return ExtractedField(
        value=normalized, confidence=raw_field.confidence, matched_text=raw_field.matched_text
    )


def extract_field_hybrid(
    text: str,
    labels: list[str],
    raw_blocks: list[dict] | None = None,
    *,
    field_type: str = "text",
    max_value_length: int = 80,
) -> ExtractedField:
    """
    Hybrid field extractor. Uses full_text as the primary source; if missing or
    weak, falls back to deterministic spatial layout queries across raw_blocks.
    """
    text_res = extract_by_labels(text, labels, max_value_length=max_value_length)
    if text_res.is_found and text_res.confidence >= 0.70:
        return text_res

    if raw_blocks:
        from app.extraction.layout_helpers import extract_field_spatially
        spatial_res = extract_field_spatially(
            raw_blocks, labels, field_type=field_type, max_value_length=max_value_length
        )
        if spatial_res.is_found:
            return spatial_res

    return text_res


def extract_date_hybrid(
    text: str,
    labels: list[str],
    raw_blocks: list[dict] | None = None,
) -> ExtractedField:
    """
    Hybrid date extractor. Uses full_text date regex as the primary candidate;
    falls back to spatial date queries when text is absent or unparseable.
    """
    text_res = extract_date_field(text, labels)
    # Check if a valid normalized date was successfully extracted
    if text_res.is_found and text_res.confidence >= 0.60 and normalize_date(text_res.value) == text_res.value:
        return text_res

    if raw_blocks:
        from app.extraction.layout_helpers import extract_field_spatially
        spatial_res = extract_field_spatially(raw_blocks, labels, field_type="date")
        if spatial_res.is_found:
            return spatial_res

    return text_res


def extract_amount_hybrid(
    text: str,
    labels: list[str],
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
    *,
    role: str | None = None,
) -> ExtractedField:
    """
    Hybrid amount extractor. Uses full_text amount regex as the primary candidate;
    falls back to spatial amount queries and reconstructed table summary calculations.
    """
    text_res = extract_amount_field(text, labels)
    if text_res.is_found and text_res.confidence >= 0.60 and normalize_amount(text_res.value) == text_res.value:
        return text_res

    if raw_blocks:
        from app.extraction.layout_helpers import extract_field_spatially
        spatial_res = extract_field_spatially(raw_blocks, labels, field_type="amount")
        if spatial_res.is_found:
            return spatial_res

    if table_data and role:
        from app.extraction.table_helpers import extract_amount_from_table
        table_res = extract_amount_from_table(table_data, role)
        if table_res.is_found:
            return table_res

    return text_res

