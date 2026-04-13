"""ANSI 颜色工具 — 终端彩色输出（汲取 oh-my-codex HUD 颜色系统）

特性:
- 自动检测终端是否支持颜色（NO_COLOR / TERM=dumb / Windows conhost）
- 可全局开关
- 进度着色（green→yellow→red）
- Windows 兼容（启用 ANSI VT 序列）
"""
from __future__ import annotations

import os
import sys

# ANSI 转义码
RESET = '\033[0m'
_BOLD = '\033[1m'
_DIM = '\033[2m'
_RED = '\033[31m'
_GREEN = '\033[32m'
_YELLOW = '\033[33m'
_BLUE = '\033[34m'
_MAGENTA = '\033[35m'
_CYAN = '\033[36m'
_WHITE = '\033[37m'

# 全局颜色开关
_color_enabled: bool | None = None  # None = 自动检测


def _detect_color_support() -> bool:
    """自动检测终端是否支持颜色"""
    # 环境变量显式禁用
    if os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('TERM') == 'dumb':
        return False
    # 非交互终端禁用
    return not (not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty())


def _ensure_windows_ansi() -> None:
    """Windows 平台启用 ANSI VT 序列（避免 conhost 乱码）"""
    if os.name == 'nt':
        try:
            # 触发 Windows 10+ ANSI 支持
            os.system('')
        except Exception:
            pass


def is_color_enabled() -> bool:
    """检查颜色是否启用"""
    global _color_enabled
    if _color_enabled is None:
        _color_enabled = _detect_color_support()
        if _color_enabled and os.name == 'nt':
            _ensure_windows_ansi()
    return _color_enabled


def set_color_enabled(enabled: bool) -> None:
    """手动设置颜色开关"""
    global _color_enabled
    _color_enabled = enabled


def _wrap(code: str, text: str) -> str:
    """用 ANSI 码包裹文本"""
    if not is_color_enabled():
        return text
    return f'{code}{text}{RESET}'


# ============================================================================
# 基础颜色函数
# ============================================================================

def red(text: str) -> str:
    return _wrap(_RED, text)


def green(text: str) -> str:
    return _wrap(_GREEN, text)


def yellow(text: str) -> str:
    return _wrap(_YELLOW, text)


def blue(text: str) -> str:
    return _wrap(_BLUE, text)


def magenta(text: str) -> str:
    return _wrap(_MAGENTA, text)


def cyan(text: str) -> str:
    return _wrap(_CYAN, text)


def white(text: str) -> str:
    return _wrap(_WHITE, text)


def dim(text: str) -> str:
    return _wrap(_DIM, text)


def bold(text: str) -> str:
    return _wrap(_BOLD, text)


def bold_green(text: str) -> str:
    return _wrap(_BOLD + _GREEN, text)


def bold_yellow(text: str) -> str:
    return _wrap(_BOLD + _YELLOW, text)


def bold_red(text: str) -> str:
    return _wrap(_BOLD + _RED, text)


def bold_cyan(text: str) -> str:
    return _wrap(_BOLD + _CYAN, text)


# ============================================================================
# 进度着色（汲取 OMX getRalphColor 模式）
# ============================================================================

def get_progress_color(current: int, maximum: int) -> str:
    """根据进度比例返回 ANSI 颜色码

    0%~70% → 绿色, 70%~90% → 黄色, 90%+ → 红色
    """
    if not is_color_enabled():
        return ''
    if maximum <= 0:
        return _GREEN
    ratio = current / maximum
    if ratio >= 0.9:
        return _RED
    if ratio >= 0.7:
        return _YELLOW
    return _GREEN


def progress_text(current: int, maximum: int, label: str = '') -> str:
    """生成带颜色的进度文本: label:current/maximum"""
    color = get_progress_color(current, maximum)
    text = f'{label}:{current}/{maximum}' if label else f'{current}/{maximum}'
    if not color:
        return text
    return f'{color}{text}{RESET}'


# ============================================================================
# 格式化辅助
# ============================================================================

def _safe_symbol(unicode_sym: str, ascii_fallback: str) -> str:
    """返回终端安全的符号（Windows GBK 兼容）"""
    try:
        unicode_sym.encode(sys.stdout.encoding or 'utf-8')
        return unicode_sym
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


def status_pass(text: str = 'PASS') -> str:
    """绿色 PASS 标记"""
    sym = _safe_symbol('\u2713', '+')
    return bold_green(f'{sym} {text}')


def status_fail(text: str = 'FAIL') -> str:
    """红色 FAIL 标记"""
    sym = _safe_symbol('\u2717', 'x')
    return bold_red(f'{sym} {text}')


def status_warn(text: str = 'WARN') -> str:
    """黄色 WARN 标记"""
    sym = _safe_symbol('\u26a0', '!')
    return bold_yellow(f'{sym} {text}')


def status_info(text: str = 'INFO') -> str:
    """蓝色 INFO 标记"""
    sym = _safe_symbol('\u2139', 'i')
    return _wrap(_BOLD + _BLUE, f'{sym} {text}')


def separator(char: str = '-', width: int = 50) -> str:
    """生成分隔线（使用 ASCII 横线兼容 Windows）"""
    return dim(char * width)


def format_token_count(value: int) -> str:
    """格式化 token 数量（汲取 OMX formatTokenCount）"""
    if value >= 1_000_000:
        return f'{value / 1_000_000:.1f}M'
    if value >= 1_000:
        return f'{value / 1_000:.1f}k'
    return str(value)
