"""Enterprise Logging Module — Clawd Code

Provides structured JSON logging and human-readable console output.
Maintains backward compatibility with the legacy ClawdLogger interface.
"""
from __future__ import annotations

import io
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

def _make_utf8_stream_handler(stream) -> logging.StreamHandler:
    """构造对中文/emoji 安全的控制台 Handler。

    背景:
        中文 Windows 的 `sys.stdout.encoding` 默认是 GBK。当日志包含
        emoji（如 U+26A0）或部分 CJK 字符时，logging 内部的
        StreamHandler.emit 会抛 UnicodeEncodeError，Python 的
        handleError 再把整段堆栈打到 stderr —— 用户看到的是一屏
        乱码加调用栈，而非他们实际关心的问题。

    做法:
        优先调用 TextIOWrapper.reconfigure() 把流切到 UTF-8（Python 3.7+），
        失败时退回到一个带 errors='replace' 的包装流，保证"永远不崩"。
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
            return logging.StreamHandler(stream)
        except (ValueError, OSError):
            # 例如流已被 detach，或本身不是 TextIOWrapper
            pass

    try:
        safe_stream = io.TextIOWrapper(
            stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        return logging.StreamHandler(safe_stream)
    except (AttributeError, ValueError):
        # 无 .buffer（如已重定向到 StringIO）——直接使用原流
        return logging.StreamHandler(stream)


def setup_logging(level: int = logging.INFO, log_file: str | None = None):
    """Initialize structured logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console Handler (Human-readable, UTF-8 safe)
    console = _make_utf8_stream_handler(sys.stdout)
    console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    root_logger.addHandler(console)

    # File Handler (JSON structured)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)
