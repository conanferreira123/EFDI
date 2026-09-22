"""InvoicePayment model.

Represents actual settlement and payment transactions originating from external
banking or enterprise accounting systems (never populated from invoice extraction).
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class InvoicePayment(Base):
    __tablename__ = "invoice_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    payment_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    invoice = relationship("Invoice", back_populates="payments")

    def __repr__(self) -> str:
        return (
            f"<InvoicePayment id={self.id} invoice_id={self.invoice_id} "
            f"date={self.payment_date} amount={self.amount} ref='{self.payment_reference}'>"
        )
