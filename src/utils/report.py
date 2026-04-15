"""Bug Reporter — 错误报告模块（从 Aider report.py 移植）

提供：
1. 系统信息收集
2. GitHub Issue 自动创建
3. 异常处理和报告

用法:
    from src.utils.report import (
        get_system_info,
        report_github_issue,
        exception_handler,
    )

    # 获取系统信息
    info = get_system_info()

    # 报告 GitHub Issue
    report_github_issue("错误描述...")
"""
from __future__ import annotations

import os
import platform
import subprocess
import re
import sys
import urllib.parse
import webbrowser

# 敏感词模式，用于脱敏
SECRET_PATTERNS = [
    re.compile(r'(api[_-]key|secret|password|token|auth|credential|private[_-]key)["\s:]+["\']?([a-zA-Z0-9_\-\.]{8,})["\']?', re.IGNORECASE),
    re.compile(r'(?<=[:=])[a-zA-Z0-9_\-\.]{20,}(?=\s|&|$|")'), # 长的可能是 key 的字符串
]

def mask_secrets(text: str) -> str:
    """脱敏敏感信息"""
    if not text:
        return text
    masked = text
    for pattern in SECRET_PATTERNS:
        # 将捕获的 key 部分替换为 [MASKED]
        def repl(match):
            groups = match.groups()
            if len(groups) >= 2:
                # 针对 key-value 对，保留 key，脱敏 value
                prefix = match.group(0).split(groups[1])[0]
                return f"{prefix}[MASKED]"
            else:
                return "[MASKED]"
        masked = pattern.sub(repl, masked)
    return masked


def get_python_info() -> str:
    """获取 Python 环境信息"""
    implementation = platform.python_implementation()
    is_venv = sys.prefix != sys.base_prefix
    return (
        f"Python implementation: {implementation}\n"
        f"Virtual environment: {'Yes' if is_venv else 'No'}"
    )


def get_os_info() -> str:
    """获取操作系统信息"""
    return f"OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})"


def get_git_info() -> str:
    """获取 Git 版本信息"""
    try:
        git_version = subprocess.check_output(["git", "--version"]).decode().strip()
        return f"Git version: {git_version}"
    except Exception:
        return "Git information unavailable"


def get_system_info() -> str:
    """获取完整系统信息"""
    version_info = "Clawd Code version: (see package)\n"
    python_version = f"Python version: {sys.version.split()[0]}\n"
    platform_info = f"Platform: {platform.platform()}\n"
    python_info = get_python_info() + "\n"
    os_info = get_os_info() + "\n"
    git_info = get_git_info() + "\n"

    return version_info + python_version + platform_info + python_info + os_info + git_info


def report_github_issue(
    issue_text: str,
    title: str | None = None,
    confirm: bool = True,
    github_issues_url: str = "https://github.com/claw-code-tingfeng/claw-code-tingfeng/issues/new",
) -> None:
    """创建 GitHub Issue

    参数:
        issue_text: Issue 内容
        title: Issue 标题
        confirm: 是否确认后再打开浏览器
        github_issues_url: GitHub Issues URL
    """
    system_info = get_system_info() + "\n"
    full_text = mask_secrets(system_info + issue_text)

    params = {"body": full_text}
    if title is None:
        title = "Bug report"
    params["title"] = title

    issue_url = f"{github_issues_url}?{urllib.parse.urlencode(params)}"

    if confirm:
        print(f"\n# {title}\n")
        print(full_text.strip())
        print()
        print("Please consider reporting this bug to help improve Clawd Code!")
        prompt = "Open a GitHub Issue pre-filled with the above error in your browser? (Y/n) "
        confirmation = input(prompt).strip().lower()

        if confirmation and not confirmation.startswith("y"):
            return

    print("Attempting to open the issue URL in your default web browser...")
    try:
        if webbrowser.open(issue_url):
            print("Browser window should be opened.")
    except Exception:
        pass

    if confirm:
        print()
        print("You can also use this URL to file the GitHub Issue:")
        print()
        print(issue_url)
        print()


def exception_handler(
    exc_type: type,
    exc_value: BaseException,
    exc_traceback,
) -> None:
    """全局异常处理器

    参数:
        exc_type: 异常类型
        exc_value: 异常值
        exc_traceback: 追溯信息
    """
    # KeyboardInterrupt 使用默认处理器
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # 不再处理其他异常
    sys.excepthook = None

    import traceback
    traceback.print_exception(exc_type, exc_value, exc_traceback)

    # 生成简短报告
    error_msg = f"{exc_type.__name__}: {exc_value}"
    print(f"\n❌ Error: {error_msg}\n")
    print("Run with --verbose for full traceback.")
    print()


def install_exception_handler() -> None:
    """安装全局异常处理器"""
    sys.excepthook = exception_handler


# ==================== 便捷函数 ====================

def check_environment() -> dict[str, bool]:
    """检查运行环境

    返回:
        环境检查结果字典
    """
    checks = {
        "python": True,
        "git": False,
        "openai": False,
        "anthropic": False,
    }

    # Git
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        checks["git"] = True
    except Exception:
        pass

    # API Keys
    checks["openai"] = bool(os.environ.get("OPENAI_API_KEY"))
    checks["anthropic"] = bool(os.environ.get("ANTHROPIC_API_KEY"))

    return checks


# 导出
__all__ = [
    "check_environment",
    "exception_handler",
    "get_git_info",
    "get_os_info",
    "get_python_info",
    "get_system_info",
    "install_exception_handler",
    "report_github_issue",
]
