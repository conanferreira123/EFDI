"""InvoiceLineItem model.

Represents itemized commercial product or service rows extracted from an invoice,
enabling deterministic aggregations, unit price queries, and tax calculations.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)

    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), nullable=True)
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)

    tax_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    invoice = relationship("Invoice", back_populates="line_items")

    def __repr__(self) -> str:
        return (
            f"<InvoiceLineItem id={self.id} invoice_id={self.invoice_id} "
            f"line={self.line_number} net={self.net_amount}>"
        )
