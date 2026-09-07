"""
SystemSetting model – a simple key-value store for global configuration.

The OCR service uses this table to retrieve the default OCR engine name.
If a row with key \"default_ocr_engine\" does not exist, the service falls back to
the static setting ``settings.OCR_DEFAULT_ENGINE``.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class SystemSetting(Base, TimestampMixin):
    """Key‑value pair for system‑wide settings.

    * ``key``   – unique identifier for the setting (e.g. "default_ocr_engine").
    * ``value`` – arbitrary string value; callers are responsible for interpreting
      the type (bool, int, enum, etc.).
    """

    __tablename__ = "system_setting"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
