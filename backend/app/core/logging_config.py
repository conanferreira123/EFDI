"""
Application-wide logging configuration.

Sets up a console handler (for dev visibility) and a rotating file
handler (for persistent audit-friendly logs). Called once at app
startup via setup_logging().
"""
import logging
import logging.handlers
import os
import sys

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """
    Configure root logging for the application.

    - Console handler: human-readable, for local dev / docker logs.
    - Rotating file handler: app.log, rotates at 5MB, keeps 5 backups,
      so production logs don't grow unbounded.
    """
    os.makedirs(settings.LOG_DIR, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(settings.LOG_DIR, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging() is called more than once
    # (e.g. under uvicorn's reloader).
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Quiet down noisy third-party loggers; we still want SQL echo
    # controllable separately via the database module.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor so modules can do `logger = get_logger(__name__)`."""
    return logging.getLogger(name)
