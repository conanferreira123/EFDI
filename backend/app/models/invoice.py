"""Invoice model.

Represents the normalized, queryable business projection of an uploaded invoice.
Establishes a 1:1 relationship with Document, preserves extraction provenance via
source_extraction_result_id, and links to normalized vendors, line items, and payment obligations.
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    source_extraction_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="SET NULL"), nullable=True, index=True
    )

    invoice_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    vendor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )

    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    subtotal_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    discount_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    shipping_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    rounding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    other_charges_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    grand_total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True, index=True)

    po_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Relationships
    document = relationship("Document", back_populates="invoice", lazy="joined")
    source_extraction_result = relationship("ExtractionResult", lazy="joined")
    vendor = relationship("Vendor", back_populates="invoices", lazy="joined")
    line_items: Mapped[List["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLineItem.line_number",
    )
    payment_obligation: Mapped[Optional["PaymentObligation"]] = relationship(
        "PaymentObligation",
        back_populates="invoice",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )
    payments: Mapped[List["InvoicePayment"]] = relationship(
        "InvoicePayment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoicePayment.payment_date",
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} doc_id={self.document_id} "
            f"number='{self.invoice_number}' total={self.grand_total_amount}>"
        )
