"""工具函数子包 - 提供结构化日志系统和环境变量加载。

本模块包含：
- logger: 多名称独立日志器（DEBUG/INFO/WARN/ERROR 四级）
- env_loader: 零依赖 .env 文件加载器
- debug: 调试辅助工具（从 Aider dump.py 移植）
- run_cmd: 命令执行工具（从 Aider run_cmd.py 移植）
"""

from __future__ import annotations

import json
from pathlib import Path

# Aider integration module exports
from . import deprecated_args, diff_utils, file_patterns, image_utils, urls

# Aider imports
from .analytics import Analytics, get_analytics, track_event
from .debug import dump, dump_as_table, dump_json
from .deprecated_args import (
    check_deprecated_args,
    get_deprecated_message,
    is_deprecated_model_arg,
)
from .env_loader import get_env, get_env_bool, get_env_int, load_env
from .io_adapter import CommandCompletionException, InputOutput, get_completions
from .logger import ClawdLogger, LogLevel, debug, error, get_logger, info, sanitize_for_log, warn
from .onboarding import detect_api_keys, select_default_model, try_select_default_model
from .run_cmd import is_windows_powershell, run_cmd, run_cmd_check_output, run_cmd_subprocess
from .scrape import Scraper, is_playwright_available, scrape
from .url_utils import (
    ParsedURL,
    build_url,
    extract_urls,
    get_domain,
    get_file_extension,
    get_url_fingerprint,
    get_url_path,
    get_url_query,
    is_document_url,
    is_image_url,
    is_internal_link,
    is_same_domain,
    is_valid_url,
    normalize_url,
    parse_url,
    sanitize_url,
)
from .voice import SoundDeviceError, Voice
from .voice import is_available as is_voice_available
from .watch import FileWatcher
from .watch import is_available as is_watch_available

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / 'reference_data' / 'subsystems' / 'utils.json'
try:
    _SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())
    ARCHIVE_NAME = _SNAPSHOT['archive_name']
    MODULE_COUNT = _SNAPSHOT['module_count']
    SAMPLE_FILES = tuple(_SNAPSHOT['sample_files'])
    PORTING_NOTE = f"Python 移植包 '{ARCHIVE_NAME}'，包含 {MODULE_COUNT} 个归档模块的引用。"
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    ARCHIVE_NAME = 'utils'
    MODULE_COUNT = 0
    SAMPLE_FILES = ()
    PORTING_NOTE = "Python 移植包 'utils' 的引用。"

__all__ = [
    'ARCHIVE_NAME',
    'MODULE_COUNT',
    'PORTING_NOTE',
    'SAMPLE_FILES',
    # Aider integrations
    'Analytics',
    # Logger
    'ClawdLogger',
    'CommandCompletionException',
    'FileWatcher',
    'InputOutput',
    'LogLevel',
    # Deprecated args (from aider)
    'check_deprecated_args',
    'get_deprecated_message',
    'is_deprecated_model_arg',
    # URL Utilities (from aider)
    'ParsedURL',
    'Scraper',
    'SoundDeviceError',
    'Voice',
    'build_url',
    'debug',
    'detect_api_keys',
    # Debug (from Aider)
    'dump',
    'dump_as_table',
    'dump_json',
    'error',
    'extract_urls',
    'get_analytics',
    'get_completions',
    'get_domain',
    # Env loader
    'get_env',
    'get_env_bool',
    'get_env_int',
    'get_file_extension',
    'get_logger',
    'get_url_fingerprint',
    'get_url_path',
    'get_url_query',
    'info',
    'is_document_url',
    'is_image_url',
    'is_internal_link',
    'is_playwright_available',
    'is_same_domain',
    'is_valid_url',
    'is_voice_available',
    'is_watch_available',
    'is_windows_powershell',
    'load_env',
    'normalize_url',
    'parse_url',
    # Run cmd (from Aider)
    'run_cmd',
    'run_cmd_check_output',
    'run_cmd_subprocess',
    'sanitize_for_log',
    'sanitize_url',
    'scrape',
    'select_default_model',
    'track_event',
    'try_select_default_model',
    'warn',
]
