"""Enterprise Logging Module — Clawd Code

Provides structured JSON logging and human-readable console output.
Maintains backward compatibility with the legacy ClawdLogger interface.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARN = logging.WARNING
    ERROR = logging.ERROR

class JsonFormatter(logging.Formatter):
    """JSON log formatter for automated log analytics."""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        if hasattr(record, "props"):
            log_data.update(record.props)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

class ClawdLogger:
    """Enterprise-grade logger with structured telemetry support."""
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def log(self, level: LogLevel, msg: str, **props):
        self.logger.log(level.value, msg, extra={"props": props})

    def debug(self, msg: str, **props):
        self.logger.debug(msg, extra={"props": props})

    def info(self, msg: str, **props):
        self.logger.info(msg, extra={"props": props})

    def warning(self, msg: str, **props):
        self.logger.warning(msg, extra={"props": props})

    def warn(self, msg: str, **props):
        self.logger.warning(msg, extra={"props": props})

    def error(self, msg: str, **props):
        self.logger.error(msg, extra={"props": props}, exc_info=True)

# Global helper functions for backward compatibility
def get_logger(name: str) -> ClawdLogger:
    return ClawdLogger(name)

_default_logger = ClawdLogger("clawd")

def debug(msg: str, **props): _default_logger.debug(msg, **props)
def info(msg: str, **props): _default_logger.info(msg, **props)
def warn(msg: str, **props): _default_logger.warn(msg, **props)
def error(msg: str, **props): _default_logger.error(msg, **props)

def sanitize_for_log(data: Any) -> str:
    """Prepare data for logging by ensuring it is string-serializable."""
    try:
        if isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False)
        return str(data)
    except Exception:
        return "[Unserializable Data]"

def setup_logging(level: int = logging.INFO, log_file: str | None = None):
    """Initialize structured logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console Handler (Human-readable)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    root_logger.addHandler(console)

    # File Handler (JSON structured)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)
