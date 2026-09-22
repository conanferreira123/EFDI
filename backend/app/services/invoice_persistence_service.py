"""Invoice Persistence Service.

Synchronizes raw/canonical extraction results from extraction_results.fields into the
normalized relational business projection tables:
- vendors
- invoices
- invoice_line_items
- payment_obligations

Preserves extraction provenance via invoices.source_extraction_result_id and ensures
idempotent replacement on extraction re-runs without mutating or replacing extraction_results.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_enums import PaymentStatus
from app.models.extraction_result import ExtractionResult
from app.models.invoice import Invoice
from app.models.invoice_line_item import InvoiceLineItem
from app.models.payment_obligation import PaymentObligation
from app.models.vendor import Vendor

logger = logging.getLogger(__name__)


class InvoicePersistenceService:
    """Synchronizes extraction results into normalized business tables."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_from_extraction(
        self,
        document_id: int,
        extraction_result_id: int,
    ) -> Optional[Invoice]:
        """Synchronize an authoritative extraction result to the relational business layer.

        Guarantees:
        1. extraction_results is never modified or deleted (provenance is preserved).
        2. invoices.source_extraction_result_id is set to extraction_result_id.
        3. Idempotent: updates existing invoice if present, replaces line items deterministically.
        4. Missing fields remain NULL (never fabricated).
        5. invoice_payments is NEVER populated from invoice extraction.
        """
        doc = self.db.get(Document, document_id)
        if not doc:
            logger.warning("Document %d not found for invoice synchronization", document_id)
            return None

        ext = self.db.get(ExtractionResult, extraction_result_id)
        if not ext:
            logger.warning("ExtractionResult %d not found for invoice synchronization", extraction_result_id)
            return None

        fields = ext.fields or {}
        canonical = self._extract_canonical_dict(fields)

        # 1. Resolve or create Vendor
        vendor_id = self._resolve_or_create_vendor(doc, canonical, fields)

        # 2. Extract header values
        inv_number = self._get_val(canonical, ["invoice_information", "invoice_number"]) or self._get_flat(fields, "invoice_number")
        inv_date = self._parse_date(self._get_val(canonical, ["invoice_information", "invoice_date"]) or self._get_flat(fields, "invoice_date"))
        currency = self._get_val(canonical, ["invoice_information", "currency"]) or self._get_flat(fields, "currency")

        buyer_name = self._get_val(canonical, ["buyer", "name"]) or self._get_flat(fields, "buyer_name")
        buyer_tax_id = self._get_val(canonical, ["buyer", "tax_id"]) or self._get_flat(fields, "buyer_tax_id")

        subtotal = self._parse_decimal(self._get_val(canonical, ["totals", "subtotal"]) or self._get_flat(fields, "subtotal_net_amount") or self._get_flat(fields, "subtotal"))
        tax_amt = self._parse_decimal(self._get_val(canonical, ["totals", "total_tax"]) or self._get_flat(fields, "total_tax_amount") or self._get_flat(fields, "tax"))
        grand_total = self._parse_decimal(self._get_val(canonical, ["totals", "grand_total"]) or self._get_flat(fields, "grand_total_amount") or self._get_flat(fields, "grand_total"))

        discount = self._parse_decimal(self._get_val(canonical, ["totals", "discount"]))
        shipping = self._parse_decimal(self._get_val(canonical, ["totals", "shipping"]))
        rounding = self._parse_decimal(self._get_val(canonical, ["totals", "rounding"]))
        other_charges = self._parse_decimal(self._get_val(canonical, ["totals", "other_charges"]))

        po_number = self._get_val(canonical, ["references", "po_number"]) or self._get_flat(fields, "po_number")

        # 3. Find or create Invoice
        stmt = select(Invoice).where(Invoice.document_id == document_id)
        invoice = self.db.execute(stmt).scalar_one_or_none()

        if invoice is None:
            invoice = Invoice(
                document_id=document_id,
                source_extraction_result_id=extraction_result_id,
                invoice_number=inv_number,
                invoice_date=inv_date,
                vendor_id=vendor_id,
                buyer_name=buyer_name,
                buyer_tax_id=buyer_tax_id,
                currency=currency,
                subtotal_amount=subtotal,
                tax_amount=tax_amt,
                discount_amount=discount,
                shipping_amount=shipping,
                rounding_amount=rounding,
                other_charges_amount=other_charges,
                grand_total_amount=grand_total,
                po_number=po_number,
            )
            self.db.add(invoice)
            self.db.flush()  # obtain invoice.id
        else:
            invoice.source_extraction_result_id = extraction_result_id
            invoice.invoice_number = inv_number
            invoice.invoice_date = inv_date
            invoice.vendor_id = vendor_id
            invoice.buyer_name = buyer_name
            invoice.buyer_tax_id = buyer_tax_id
            invoice.currency = currency
            invoice.subtotal_amount = subtotal
            invoice.tax_amount = tax_amt
            invoice.discount_amount = discount
            invoice.shipping_amount = shipping
            invoice.rounding_amount = rounding
            invoice.other_charges_amount = other_charges
            invoice.grand_total_amount = grand_total
            invoice.po_number = po_number
            self.db.flush()

        # 4. Synchronize Line Items (deterministic replacement)
        self._sync_line_items(invoice.id, canonical, fields)

        # 5. Synchronize Payment Obligations
        self._sync_payment_obligation(invoice, canonical, fields, grand_total, currency)

        self.db.flush()
        logger.info(
            "Synchronized business data for document %d into invoice %d (extraction_id=%d)",
            document_id, invoice.id, extraction_result_id
        )
        return invoice

    def _extract_canonical_dict(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Extract nested canonical dictionary if present."""
        can = fields.get("canonical")
        if isinstance(can, dict):
            val = can.get("value")
            if isinstance(val, dict):
                return val
            return can
        return {}

    def _get_val(self, canonical: Dict[str, Any], path: List[str]) -> Optional[str]:
        """Traverse nested dict structure handling LLMFieldItem format."""
        curr: Any = canonical
        for p in path:
            if not isinstance(curr, dict):
                return None
            curr = curr.get(p)
            if curr is None:
                return None

        if isinstance(curr, dict):
            # Might be {"value": "...", "confidence": ...}
            raw = curr.get("value")
            return str(raw).strip() if raw is not None and str(raw).strip() else None
        return str(curr).strip() if curr is not None and str(curr).strip() else None

    def _get_flat(self, fields: Dict[str, Any], key: str) -> Optional[str]:
        """Retrieve flat field string value."""
        entry = fields.get(key)
        if isinstance(entry, dict):
            val = entry.get("value")
            return str(val).strip() if val is not None and str(val).strip() else None
        return str(entry).strip() if entry is not None and str(entry).strip() else None

    def _parse_decimal(self, val_str: Optional[str]) -> Optional[Decimal]:
        if not val_str:
            return None
        cleaned = re.sub(r"[^\d.-]", "", str(val_str).strip())
        if not cleaned or cleaned in ("-", ".", "-."):
            return None
        try:
            return Decimal(cleaned).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    def _parse_date(self, val_str: Optional[str]) -> Optional[date]:
        if not val_str:
            return None
        val_str = str(val_str).strip()
        # Try common ISO and standard date formats
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(val_str, fmt).date()
            except ValueError:
                continue
        # Check regex YYYY-MM-DD
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", val_str)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None

    def _resolve_or_create_vendor(
        self,
        doc: Document,
        canonical: Dict[str, Any],
        fields: Dict[str, Any],
    ) -> Optional[int]:
        """Resolve vendor by vendor_code, tax_id, or canonical_name."""
        vendor_code = getattr(doc, "vendor_code", None) or self._get_flat(fields, "vendor_code")
        seller_name = (
            self._get_val(canonical, ["seller", "name"])
            or self._get_flat(fields, "seller_name")
            or self._get_flat(fields, "vendor_name")
        )
        tax_id = (
            self._get_val(canonical, ["seller", "tax_id"])
            or self._get_flat(fields, "seller_tax_id")
        )
        address = self._get_val(canonical, ["seller", "address"])

        if not seller_name and not vendor_code and not tax_id:
            return None

        # 1. Look up by vendor_code
        vendor: Optional[Vendor] = None
        if vendor_code:
            stmt = select(Vendor).where(Vendor.vendor_code == vendor_code)
            vendor = self.db.execute(stmt).scalar_one_or_none()

        # 2. Look up by tax_id
        if vendor is None and tax_id:
            stmt = select(Vendor).where(Vendor.tax_id == tax_id)
            vendor = self.db.execute(stmt).scalar_one_or_none()

        # 3. Look up by canonical_name (case-insensitive)
        if vendor is None and seller_name:
            stmt = select(Vendor).where(Vendor.canonical_name.ilike(seller_name.strip()))
            vendor = self.db.execute(stmt).scalar_one_or_none()

        if vendor:
            # Enrich existing vendor details if unstated
            if not vendor.tax_id and tax_id:
                vendor.tax_id = tax_id
            if not vendor.address and address:
                vendor.address = address
            if not vendor.vendor_code and vendor_code:
                vendor.vendor_code = vendor_code
            return vendor.id

        # 4. Create new vendor if seller_name or vendor_code exists
        canonical_name = seller_name or f"Vendor {vendor_code}"
        new_vendor = Vendor(
            canonical_name=canonical_name,
            vendor_code=vendor_code,
            tax_id=tax_id,
            address=address,
        )
        self.db.add(new_vendor)
        self.db.flush()
        return new_vendor.id

    def _sync_line_items(
        self,
        invoice_id: int,
        canonical: Dict[str, Any],
        fields: Dict[str, Any],
    ) -> None:
        """Deterministic replacement of invoice line items."""
        # Purge existing line items for idempotent re-runs
        self.db.execute(
            delete(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )

        raw_items = canonical.get("line_items")
        if not isinstance(raw_items, list) or not raw_items:
            return

        new_items = []
        for idx, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            desc = self._get_nested_str(item, "description")
            qty = self._parse_decimal(self._get_nested_str(item, "quantity"))
            uom = self._get_nested_str(item, "uom")
            unit_price = self._parse_decimal(self._get_nested_str(item, "unit_price"))
            net_amt = self._parse_decimal(self._get_nested_str(item, "net_amount"))
            tax_rate = self._parse_decimal(self._get_nested_str(item, "tax_rate"))
            tax_amt = self._parse_decimal(self._get_nested_str(item, "tax_amount"))
            gross_amt = self._parse_decimal(self._get_nested_str(item, "gross_amount"))

            # Only insert if at least one meaningful field is present
            if desc or qty or unit_price or net_amt or gross_amt:
                line_item = InvoiceLineItem(
                    invoice_id=invoice_id,
                    line_number=idx + 1,
                    description=desc,
                    quantity=qty,
                    uom=uom,
                    unit_price=unit_price,
                    net_amount=net_amt,
                    tax_rate=tax_rate,
                    tax_amount=tax_amt,
                    gross_amount=gross_amt,
                )
                new_items.append(line_item)

        if new_items:
            self.db.add_all(new_items)
            self.db.flush()

    def _get_nested_str(self, item: Dict[str, Any], key: str) -> Optional[str]:
        val = item.get(key)
        if isinstance(val, dict):
            raw = val.get("value")
            return str(raw).strip() if raw is not None and str(raw).strip() else None
        return str(val).strip() if val is not None and str(val).strip() else None

    def _sync_payment_obligation(
        self,
        invoice: Invoice,
        canonical: Dict[str, Any],
        fields: Dict[str, Any],
        grand_total: Optional[Decimal],
        currency: Optional[str],
    ) -> None:
        """Synchronize payment obligation without fabricating payment events."""
        due_date = self._parse_date(
            self._get_val(canonical, ["payment", "due_date"])
            or self._get_flat(fields, "due_date")
        )
        payment_terms = (
            self._get_val(canonical, ["payment", "payment_terms"])
            or self._get_flat(fields, "payment_terms")
        )

        early_deadline = self._parse_date(self._get_val(canonical, ["payment", "early_payment_deadline"]))
        early_discount = self._parse_decimal(self._get_val(canonical, ["payment", "early_payment_discount"]))
        late_penalty = self._parse_decimal(self._get_val(canonical, ["payment", "late_payment_penalty"]))

        # amount_due is derived from grand_total if not explicitly separate
        amount_due = grand_total

        # Look up existing obligation
        stmt = select(PaymentObligation).where(PaymentObligation.invoice_id == invoice.id)
        obligation = self.db.execute(stmt).scalar_one_or_none()

        # Determine status: if due_date or amount_due is known, OPEN; else UNKNOWN
        initial_status = PaymentStatus.OPEN.value if (due_date or amount_due) else PaymentStatus.UNKNOWN.value

        if obligation is None:
            obligation = PaymentObligation(
                invoice_id=invoice.id,
                amount_due=amount_due,
                amount_paid=Decimal("0.00"),
                amount_outstanding=amount_due,
                currency=currency,
                due_date=due_date,
                status=initial_status,
                payment_terms=payment_terms,
                early_payment_deadline=early_deadline,
                early_payment_discount=early_discount,
                late_payment_penalty=late_penalty,
            )
            self.db.add(obligation)
        else:
            obligation.amount_due = amount_due
            # Preserve existing amount_paid (which would be updated by real accounting payments)
            if obligation.amount_due is not None:
                obligation.amount_outstanding = obligation.amount_due - obligation.amount_paid
            obligation.currency = currency
            obligation.due_date = due_date
            obligation.payment_terms = payment_terms
            obligation.early_payment_deadline = early_deadline
            obligation.early_payment_discount = early_discount
            obligation.late_payment_penalty = late_penalty
            if obligation.status == PaymentStatus.UNKNOWN.value and (due_date or amount_due):
                obligation.status = PaymentStatus.OPEN.value

        self.db.flush()
