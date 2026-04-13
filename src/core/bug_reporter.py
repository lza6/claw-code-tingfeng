"""Bug Reporter — 全局异常处理与 GitHub Issue 生成（移植自 Aider report.py）

功能:
- 全局未捕获异常自动捕获
- 自动收集系统信息（Python 版本、OS、Git 等）
- 生成预填充的 GitHub Issue URL
- 可选自动打开浏览器

用法:
    from .bug_reporter import install_exception_handler

    install_exception_handler()  # 安装全局异常处理器
"""
from __future__ import annotations

import contextlib
import os
import platform
import sys
import traceback
import urllib.parse
import webbrowser
from typing import Any

GITHUB_ISSUES_URL = "https://github.com/claw-code-tingfeng/claw-code-tingfeng/issues/new"

FENCE = "`" * 3

# 版本检查文件路径
VERSION_CHECK_FNAME: Any = None  # 保留接口，暂不使用


def get_python_info() -> str:
    """获取 Python 环境信息"""
    implementation = platform.python_implementation()
    is_venv = sys.prefix != sys.base_prefix
    return f"Python implementation: {implementation}\nVirtual environment: {'Yes' if is_venv else 'No'}"


def get_os_info() -> str:
    """获取操作系统信息"""
    return f"OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})"


def get_git_info() -> str:
    """获取 Git 版本信息"""
    try:
        import subprocess
        git_version = subprocess.check_output(["git", "--version"]).decode().strip()
        return f"Git version: {git_version}"
    except Exception:
        return "Git information unavailable"


def get_clawcode_info() -> str:
    """获取 Clawd Code 版本信息"""
    try:
        from src import __version__
        return f"Clawd Code version: {__version__}"
    except Exception:
        return "Clawd Code version: unknown"


def get_system_info() -> str:
    """收集完整的系统信息"""
    return (
        f"{get_clawcode_info()}\n"
        f"Python version: {sys.version.split()[0]}\n"
        f"Platform: {platform.platform()}\n"
        f"{get_python_info()}\n"
        f"{get_os_info()}\n"
        f"{get_git_info()}\n"
    )


def report_github_issue(
    issue_text: str,
    title: str | None = None,
    confirm: bool = True,
) -> None:
    """生成并打开 GitHub Issue URL

    参数:
        issue_text: Issue 正文
        title: Issue 标题（可选）
        confirm: 是否需要用户确认（默认 True）
    """
    system_info = get_system_info()
    issue_text = system_info + "\n" + issue_text

    params: dict[str, str] = {"body": issue_text}
    if title is None:
        title = "Bug report"
    params["title"] = title

    issue_url = f"{GITHUB_ISSUES_URL}?{urllib.parse.urlencode(params)}"

    if confirm:
        print(f"\n# {title}\n")
        print(issue_text.strip())
        print()
        print("请考虑将此 Bug 报告提交到 GitHub 以帮助改进 Clawd Code!")
        prompt = "在浏览器中打开预填充的 GitHub Issue? [Y/n] "
        confirmation = input(prompt).strip().lower()

        yes = not confirmation or confirmation.startswith("y")
        if not yes:
            return

    print("正在打开浏览器...")
    with contextlib.suppress(Exception):
        webbrowser.open(issue_url)

    if confirm:
        print()
        print("你也可以手动使用此 URL 提交 Issue:")
        print(issue_url)
        print()


def exception_handler(exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
    """全局异常处理器

    捕获未处理的异常，收集信息并引导用户提交 Bug Report。
    """
    # KeyboardInterrupt 直接传递给默认处理器
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # 防止递归
    sys.excepthook = sys.__excepthook__

    # 格式化 traceback（替换完整路径为文件名）
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_lines_safe = []
    for line in tb_lines:
        try:
            if "File " in line:
                parts = line.split('"')
                if len(parts) > 1:
                    full_path = parts[1]
                    basename = os.path.basename(full_path)
                    line = line.replace(full_path, basename)
        except Exception:
            pass
        tb_lines_safe.append(line)

    tb_text = "".join(tb_lines_safe)

    # 获取最内层帧信息
    innermost_tb = exc_traceback
    while innermost_tb.tb_next:
        innermost_tb = innermost_tb.tb_next

    filename = innermost_tb.tb_frame.f_code.co_filename
    line_number = innermost_tb.tb_lineno
    try:
        basename = os.path.basename(filename)
    except Exception:
        basename = filename

    exception_type = exc_type.__name__

    issue_text = f"发生未捕获的异常:\n\n{FENCE}\n{tb_text}\n{FENCE}"
    title = f"Uncaught {exception_type} in {basename} line {line_number}"

    report_github_issue(issue_text, title=title)

    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def install_exception_handler() -> None:
    """安装全局异常处理器"""
    sys.excepthook = exception_handler
