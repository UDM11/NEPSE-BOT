"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import structlog

from core.config import PROJECT_ROOT, get_app_config, get_settings


def setup_logging() -> structlog.stdlib.BoundLogger:
    """Configure structured JSON logging to console, file, and optional DB."""
    settings = get_settings()
    app_config = get_app_config()
    log_config = app_config.get("logging", {})

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_path = PROJECT_ROOT / log_config.get("file_path", "logs/nepse_bot.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Standard library logging
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=log_config.get("max_bytes", 10_485_760),
        backupCount=log_config.get("backup_count", 10),
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Structlog processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_config.get("format") == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    return structlog.get_logger("nepse_bot")


def get_logger(name: str = "nepse_bot") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
