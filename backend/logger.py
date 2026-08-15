from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from backend.config import settings


_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings.log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(getattr(handler, "_aegis_console", False) for handler in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler._aegis_console = True  # type: ignore[attr-defined]
        root_logger.addHandler(console_handler)

    if not any(getattr(handler, "_aegis_file", False) for handler in root_logger.handlers):
        file_handler = RotatingFileHandler(
            settings.log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._aegis_file = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
