"""
Rule-based document classifier.

Scores OCR-extracted text against a curated set of keywords and regex
patterns per DocumentType, then picks the highest-scoring type if it
clears a minimum confidence floor (otherwise UNKNOWN). This is the
"Rule-based initially" implementation called for by the spec; a future
ML-based engine can implement the same ClassificationEngine interface
(app/classification/base.py) and be swapped in via the factory
(app/classification/factory.py) with zero router/service changes.

Document types and rule rationale (derived from the client's
AP-AR_DocuementTypes.xlsx field-mapping sheet):

  POI - PO-based vendor invoice: has BOTH a PO Number and Invoice
        Number. The presence of a PO reference is what distinguishes
        it from NPO.
  NPO - Non-PO-based vendor invoice: has an Invoice Number but
        explicitly NO PO reference. Rules for NPO award points for
        invoice-ish language but the classifier overall favors POI
        when a PO number is also present (see _apply_po_npo_disambiguation).
  IMA - Employee reimbursement/expense claim: travel, expense,
        reimbursement language -- structurally an "invoice-like" claim
        document but about an employee, not a vendor.
  MSI - Sales invoice issued TO a customer (R2R/receivables side, the
        mirror image of POI/NPO which are vendor invoices on the AP
        side). Distinguished by customer-facing language.
  PSI - Pay-in-slip / customer receipt acknowledging money received.
  JER - Journal entry: GL account codes, debit/credit, posting date.
  BKA - Bank document / advice: bank name, account number, advice date.
  DPR - Down payment request: advance payment request against a PO,
        before the goods/services are fully invoiced.
  LCA - Letter of credit advice: trade finance instrument, distinct
        vocabulary (issuing bank, beneficiary, shipment, LC number).

Scoring approach:
- Each rule contributes a weight when its keyword/pattern is found.
- The raw score per type is normalized by the maximum possible score
  for that type, so types with more rules don't have an unfair
  advantage purely from having more chances to match.
- The classification floor (MIN_CONFIDENCE) exists so that a document
  with no recognizable signals (e.g. a blank page, or a stub-OCR
  placeholder string) is correctly labeled UNKNOWN rather than forced
  into whatever type happens to score highest by chance.
"""
import re

from app.classification.base import (
    ClassificationEngine,
    ClassificationResultData,
    ClassificationSignal,
)
from app.models.document_enums import DocumentType

MIN_CONFIDENCE = 0.23


class Rule:
    """A single keyword or regex rule contributing to a type's score."""

    __slots__ = ("pattern", "description", "weight", "is_regex")

    def __init__(self, pattern: str, description: str, weight: float, *, is_regex: bool = False):
        self.pattern = pattern
        self.description = description
        self.weight = weight
        self.is_regex = is_regex

    def find(self, text_lower: str, original_text: str) -> str | None:
        """Return the matched substring if this rule fires, else None."""
        if self.is_regex:
            match = re.search(self.pattern, original_text, re.IGNORECASE)
            return match.group(0) if match else None
        # Use word boundary check for short tokens (<= 3 chars) to avoid false substring matches
        if len(self.pattern) <= 3:
            match = re.search(r"\b" + re.escape(self.pattern) + r"\b", text_lower)
            return match.group(0) if match else None
        if self.pattern in text_lower:
            return self.pattern
        return None


# Requires the trailing token to contain at least one digit -- a
# real PO number/code always has one; a plain English word (e.g.
# "invoice" in "non-PO invoice") never does. Without this, the
# pattern matched benign phrases like "non-PO invoice" as if they
# were an actual PO number, incorrectly boosting POI over NPO.
PO_NUMBER_PATTERN = r"\bpo\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]{3,}"

# Rule sets per document type. Weights are hand-tuned: distinctive
# multi-word phrases and ID-number patterns score higher than single
# generic words that show up across many financial document types.
RULES: dict[DocumentType, list[Rule]] = {
    DocumentType.POI: [
        Rule("purchase order", "phrase 'purchase order'", 2.5),
        Rule(PO_NUMBER_PATTERN, "PO number pattern", 3.0, is_regex=True),
        Rule(r"\bpo\s*(?:number|no\.?|#)", "phrase 'po number'", 2.5, is_regex=True),
        Rule(r"\binvoice\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]{3,}", "invoice number pattern", 2.0, is_regex=True),
        Rule("invoice number", "phrase 'invoice number'", 1.5),
        Rule("invoice", "word 'invoice'", 1.0),
        Rule("grn", "term 'GRN'", 1.5),
        Rule("srn", "term 'SRN'", 1.0),
        Rule(r"\b(?:vendor|seller|supplier)\b", "vendor/seller indicator", 1.0, is_regex=True),
        Rule(r"\b(?:bill\s+to|client|buyer)\b", "bill to/client indicator", 1.0, is_regex=True),
        Rule("tax invoice", "phrase 'tax invoice'", 1.0),
        Rule("gstin", "term 'GSTIN'", 1.0),
    ],
    DocumentType.NPO: [
        Rule("invoice number", "phrase 'invoice number'", 2.5),
        Rule(r"\binvoice\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]{3,}", "invoice number pattern", 3.0, is_regex=True),
        Rule(r"\binvoice\s*no\.?", "phrase 'invoice no'", 2.5, is_regex=True),
        Rule("invoice", "word 'invoice'", 1.5),
        Rule(r"\b(?:bill\s+to|client|buyer|billed\s+to)\b", "phrase 'bill to / client'", 2.0, is_regex=True),
        Rule(r"\b(?:vendor|seller|supplier|billed\s+by)\b", "word 'vendor / seller'", 2.0, is_regex=True),
        Rule("vendor code", "phrase 'vendor code'", 2.0),
        Rule("tax invoice", "phrase 'tax invoice'", 2.0),
        Rule("gstin", "term 'GSTIN'", 1.5),
        Rule(r"\btax\s*id\b", "term 'Tax Id'", 1.5, is_regex=True),
        Rule("date of issue", "phrase 'date of issue'", 1.5),
        Rule(r"\b(?:amount\s+due|gross\s+worth|net\s+worth|total\s+amount|grand\s+total)\b", "phrase 'amount due / total summary'", 1.5, is_regex=True),
        Rule("remit to", "phrase 'remit to'", 1.5),
    ],
    DocumentType.IMA: [
        Rule("reimbursement", "word 'reimbursement'", 3.0),
        Rule("expense claim", "phrase 'expense claim'", 3.0),
        Rule("expense report", "phrase 'expense report'", 2.5),
        Rule(r"\btravel\b", "word 'travel'", 1.5, is_regex=True),
        Rule("travel end date", "phrase 'travel end date'", 2.5),
        Rule(r"\bemployee\b", "word 'employee'", 1.5, is_regex=True),
        Rule("claim form", "phrase 'claim form'", 2.0),
        Rule("per diem", "phrase 'per diem'", 1.5),
        Rule(r"\bmileage\b", "word 'mileage'", 1.0, is_regex=True),
    ],
    DocumentType.MSI: [
        Rule(r"\bcustomer\b", "word 'customer'", 1.5, is_regex=True),
        Rule("customer code", "phrase 'customer code'", 2.5),
        Rule("customer name", "phrase 'customer name'", 1.5),
        Rule("sales invoice", "phrase 'sales invoice'", 3.0),
        Rule("msi invoice", "phrase 'msi invoice'", 3.0),
        Rule("invoice number", "phrase 'invoice number'", 1.0),
        Rule("ship to", "phrase 'ship to'", 2.0),
        Rule("sold to", "phrase 'sold to'", 2.0),
        Rule("ship mode", "phrase 'ship mode'", 2.0),
        Rule("order id", "phrase 'order id'", 1.5),
    ],
    DocumentType.PSI: [
        Rule("pay in slip", "phrase 'pay in slip'", 3.0),
        Rule("pay-in slip", "phrase 'pay-in slip'", 3.0),
        Rule("pis number", "phrase 'pis number'", 2.5),
        Rule(r"\bdeposit\b", "word 'deposit'", 1.5, is_regex=True),
        Rule("deposit amount", "phrase 'deposit amount'", 2.0),
        Rule(r"\breceipt\b", "word 'receipt'", 1.0, is_regex=True),
        Rule("customer receipt", "phrase 'customer receipt'", 2.5),
        Rule("bank name", "phrase 'bank name'", 1.0),
        Rule(r"\bcheque\b", "word 'cheque'", 1.0, is_regex=True),
        Rule("cash deposit", "phrase 'cash deposit'", 1.5),
    ],
    DocumentType.JER: [
        Rule("journal entry", "phrase 'journal entry'", 3.0),
        Rule("journal voucher", "phrase 'journal voucher'", 2.5),
        Rule("gl account", "phrase 'gl account'", 2.5),
        Rule("gl account code", "phrase 'gl account code'", 3.0),
        Rule("general ledger", "phrase 'general ledger'", 2.0),
        Rule(r"\bdebit\b", "word 'debit'", 1.5, is_regex=True),
        Rule(r"\bcredit\b", "word 'credit'", 1.5, is_regex=True),
        Rule("posting date", "phrase 'posting date'", 1.5),
        Rule(r"\bnarration\b", "word 'narration'", 1.0, is_regex=True),
        Rule(r"\bje\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]+", "JE number pattern", 2.0, is_regex=True),
    ],
    DocumentType.BKA: [
        Rule("bank name", "phrase 'bank name'", 1.5),
        Rule("advice date", "phrase 'advice date'", 2.5),
        Rule("advice amount", "phrase 'advice amount'", 2.5),
        Rule("bank advice", "phrase 'bank advice'", 3.0),
        Rule("debit advice", "phrase 'debit advice'", 2.5),
        Rule("credit advice", "phrase 'credit advice'", 2.5),
        Rule("account number", "phrase 'account number'", 1.5),
        Rule(r"\bifsc\b", "term 'IFSC'", 1.5, is_regex=True),
        Rule(r"\baccount\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]{6,}", "account number pattern", 1.5, is_regex=True),
    ],
    DocumentType.DPR: [
        Rule("down payment request", "phrase 'down payment request'", 3.0),
        Rule("down payment", "phrase 'down payment'", 2.0),
        Rule("advance payment", "phrase 'advance payment'", 2.0),
        Rule("advance percentage", "phrase 'advance percentage'", 2.5),
        Rule("requested amount", "phrase 'requested amount'", 2.0),
        Rule("request number", "phrase 'request number'", 2.0),
        Rule(r"\bdpr\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]+", "DPR number pattern", 2.5, is_regex=True),
        Rule(r"\bpurpose\b", "word 'purpose'", 0.5, is_regex=True),
    ],
    DocumentType.LCA: [
        Rule("letter of credit", "phrase 'letter of credit'", 3.0),
        Rule(r"\blc\s*(?:number|no\.?|#)?\s*[:\-]?\s*(?=[a-z0-9\-]{0,10}\d)[a-z0-9\-]+", "LC number pattern", 2.5, is_regex=True),
        Rule("issuing bank", "phrase 'issuing bank'", 2.5),
        Rule(r"\bbeneficiary\b", "word 'beneficiary'", 2.0, is_regex=True),
        Rule("beneficiary name", "phrase 'beneficiary name'", 2.5),
        Rule("shipment reference", "phrase 'shipment reference'", 2.0),
        Rule("trade reference", "phrase 'trade reference'", 2.0),
        Rule("lc amount", "phrase 'lc amount'", 2.0),
        Rule("expiry date", "phrase 'expiry date'", 1.0),
    ],
}

# All 7 financial document types now have field schemas (per the
# updated, fully-specified field list); no types are excluded from
# scoring anymore. Kept as an empty tuple (rather than removing the
# concept entirely) in case a future type is added before its rules
# are written.
_UNRULED_TYPES = ()


def _max_possible_score(rules: list[Rule]) -> float:
    return sum(rule.weight for rule in rules)


def _apply_po_npo_disambiguation(
    normalized_scores: dict[DocumentType, float],
    signals_by_type: dict[DocumentType, list[ClassificationSignal]],
) -> None:
    """
    POI and NPO are both vendor invoices and share most rule language
    ("invoice", "vendor", "bill to"). The one structurally reliable
    distinguishing signal is the presence of an actual PO number. If a
    PO number pattern matched, boost POI and suppress NPO (a PO-based
    invoice should never be misfiled as non-PO); if no PO number
    matched at all, suppress POI in favor of NPO.
    """
    poi_signals = signals_by_type.get(DocumentType.POI, [])
    has_po_number = any(
        "PO number" in s.rule_description or "phrase 'po number'" in s.rule_description or "phrase 'purchase order'" in s.rule_description
        for s in poi_signals
    )

    if has_po_number:
        normalized_scores[DocumentType.NPO] *= 0.4
    else:
        normalized_scores[DocumentType.POI] *= 0.5

def _apply_msi_npo_disambiguation(
    normalized_scores: dict[DocumentType, float],
    signals_by_type: dict[DocumentType, list[ClassificationSignal]],
) -> None:
    """
    MSI (sales invoice, customer-facing) and NPO (vendor invoice,
    AP-side) share generic invoice language ("invoice", "bill to"),
    which lets NPO's broader rule set outscore MSI even on a genuine
    retail sales invoice -- discovered on a real invoice where OCR
    correctly read "Ship To" and "Ship Mode" (retail-specific, MSI
    signals) but NPO still won on volume of generic matches alone.

    The structurally reliable distinguishing signal here is the
    *combination* of shipping-specific language ("ship to"/"ship
    mode"/"order id") with the *absence* of any vendor-side language
    ("vendor", "seller", "remit to", "tax invoice", "tax id", "gstin") -- a real vendor invoice
    practically always uses at least one of those vendor-side terms;
    a retail customer invoice practically never does.
    """
    msi_signals = signals_by_type.get(DocumentType.MSI, [])
    npo_signals = signals_by_type.get(DocumentType.NPO, [])

    has_shipping_language = any(
        s.rule_description in ("phrase 'ship to'", "phrase 'ship mode'", "phrase 'order id'")
        for s in msi_signals
    )
    has_vendor_language = any(
        "vendor" in s.rule_description.lower()
        or "seller" in s.rule_description.lower()
        or "remit to" in s.rule_description.lower()
        or "tax invoice" in s.rule_description.lower()
        or "tax id" in s.rule_description.lower()
        or "gstin" in s.rule_description.lower()
        for s in npo_signals
    )

    if has_shipping_language and not has_vendor_language:
        normalized_scores[DocumentType.MSI] *= 1.8
        normalized_scores[DocumentType.NPO] *= 0.5

class RuleBasedClassifier(ClassificationEngine):
    name = "rule_based"

    def classify(self, text: str) -> ClassificationResultData:
        scoreable_types = [t for t in DocumentType if t not in _UNRULED_TYPES and t != DocumentType.UNKNOWN]

        if not text or not text.strip():
            return ClassificationResultData(
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                engine_name=self.name,
                scores_by_type={t.value: 0.0 for t in scoreable_types},
            )

        text_lower = text.lower()

        normalized_scores: dict[DocumentType, float] = {}
        signals_by_type: dict[DocumentType, list[ClassificationSignal]] = {}

        for doc_type in scoreable_types:
            rules = RULES.get(doc_type, [])
            raw_score = 0.0
            matched_signals: list[ClassificationSignal] = []

            for rule in rules:
                match = rule.find(text_lower, text)
                if match:
                    raw_score += rule.weight
                    matched_signals.append(
                        ClassificationSignal(
                            matched_text=match, rule_description=rule.description, weight=rule.weight
                        )
                    )

            max_score = _max_possible_score(rules)
            normalized_scores[doc_type] = raw_score / max_score if max_score > 0 else 0.0
            signals_by_type[doc_type] = matched_signals

        _apply_po_npo_disambiguation(normalized_scores, signals_by_type)
        _apply_msi_npo_disambiguation(normalized_scores, signals_by_type)

        # Both disambiguation passes multiply an already-normalized
        # (0-1) score by a boost factor > 1 (e.g. MSI *= 1.8) without
        # re-normalizing afterward -- if the pre-boost score was
        # already fairly high, this can push it above 1.0. A
        # confidence value is meaningless above 100%, so clamp here
        # rather than let a "180%" confidence reach the API/UI.
        normalized_scores = {t: min(s, 1.0) for t, s in normalized_scores.items()}

        best_type = max(normalized_scores, key=normalized_scores.get)
        best_score = normalized_scores[best_type]

        scores_output = {t.value: round(s, 4) for t, s in normalized_scores.items()}

        if best_score < MIN_CONFIDENCE:
            return ClassificationResultData(
                document_type=DocumentType.UNKNOWN,
                confidence=round(best_score, 4),
                signals=[],
                engine_name=self.name,
                scores_by_type=scores_output,
            )

        return ClassificationResultData(
            document_type=best_type,
            confidence=round(best_score, 4),
            signals=signals_by_type[best_type],
            engine_name=self.name,
            scores_by_type=scores_output,
        )
