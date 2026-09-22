"""PaymentObligation model.

Represents the invoice-derived financial obligation and payment deadline tracking.
Maintains clear separation from actual payment events (stored in invoice_payments)
and avoids duplicate payment fields on invoices.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.document_enums import PaymentStatus


class PaymentObligation(Base, TimestampMixin):
    __tablename__ = "payment_obligations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    amount_due: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00"), server_default=text("'0.00'")
    )
    amount_outstanding: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)

    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PaymentStatus.UNKNOWN.value, index=True
    )

    payment_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    early_payment_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    early_payment_discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    late_payment_penalty: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)

    invoice = relationship("Invoice", back_populates="payment_obligation")

    def __repr__(self) -> str:
        return (
            f"<PaymentObligation id={self.id} invoice_id={self.invoice_id} "
            f"due={self.due_date} status='{self.status}' due_amt={self.amount_due}>"
        )
