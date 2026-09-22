"""Vendor and VendorAlias models.

Represents normalized commercial vendor identities, tax IDs, and trade name aliases
for cross-document aggregation and deterministic entity resolution.
"""
from typing import List, Optional
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vendor_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="vendor")
    aliases: Mapped[List["VendorAlias"]] = relationship(
        "VendorAlias", back_populates="vendor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Vendor id={self.id} canonical_name='{self.canonical_name}' code='{self.vendor_code}'>"


class VendorAlias(Base):
    __tablename__ = "vendor_aliases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("vendor_id", "alias", name="uq_vendor_aliases_vendor_alias"),
    )

    def __repr__(self) -> str:
        return f"<VendorAlias id={self.id} vendor_id={self.vendor_id} alias='{self.alias}'>"
