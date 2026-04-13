"""Command execution utility — 从 Aider run_cmd.py 移植增强

提供跨平台命令执行能力：
- Windows PowerShell 自动检测
- pexpect 交互式 shell 支持 (非 Windows)
- subprocess 实时输出
- 父进程检测

用法:
    from src.utils.run_cmd import run_cmd, run_cmd_subprocess

    # 简单执行
    returncode, output = run_cmd("ls -la")

    # 子进程模式
    returncode, output = run_cmd_subprocess("echo hello")
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from io import BytesIO

try:
    import pexpect
    HAS_PEXPECT = True
except ImportError:
    HAS_PEXPECT = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def get_windows_parent_process_name() -> str | None:
    """获取 Windows 父进程名称

    检测当前进程是否在 PowerShell 或 Cmd 中运行。

    Returns:
        'powershell.exe', 'cmd.exe', 或 None
    """
    if not HAS_PSUTIL:
        return None

    try:
        current_process = psutil.Process()
        while True:
            parent = current_process.parent()
            if parent is None:
                break
            parent_name = parent.name().lower()
            if parent_name in ["powershell.exe", "cmd.exe"]:
                return parent_name
            current_process = parent
        return None
    except Exception:
        return None


def run_cmd(
    command: str,
    verbose: bool = False,
    error_print: str | None = None,
    cwd: str | None = None,
) -> tuple[int, str]:
    """执行命令（自动选择最佳方式）

    Args:
        command: 要执行的命令
        verbose: 是否打印详细信息
        error_print: 自定义错误打印函数
        cwd: 工作目录

    Returns:
        (返回码, 输出内容) 元组
    """
    try:
        # Windows 使用 subprocess，非 Windows 且有 TTY 时尝试 pexpect
        if sys.stdin.isatty() and HAS_PEXPECT and platform.system() != "Windows":
            return run_cmd_pexpect(command, verbose, cwd)

        return run_cmd_subprocess(command, verbose, cwd)
    except OSError as e:
        error_message = f"Error occurred while running command '{command}': {e!s}"
        if error_print is None:
            print(error_message)
        else:
            error_print(error_message)
        return 1, error_message


def run_cmd_subprocess(
    command: str,
    verbose: bool = False,
    cwd: str | None = None,
    encoding: str | None = None,
) -> tuple[int, str]:
    """使用 subprocess 执行命令

    Args:
        command: 要执行的命令
        verbose: 是否打印详细信息
        cwd: 工作目录
        encoding: 输出编码

    Returns:
        (返回码, 输出内容) 元组
    """
    if verbose:
        print("Using run_cmd_subprocess:", command)

    if encoding is None:
        encoding = sys.stdout.encoding or "utf-8"

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        parent_process = None

        # Windows 特殊处理
        if platform.system() == "Windows":
            parent_process = get_windows_parent_process_name()
            if parent_process == "powershell.exe":
                command = f"powershell -Command {command}"

        if verbose:
            print("Running command:", command)
            print("SHELL:", shell)
            if platform.system() == "Windows":
                print("Parent process:", parent_process)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding=encoding,
            errors="replace",
            bufsize=0,
            universal_newlines=True,
            cwd=cwd,
        )

        output: list[str] = []
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            print(chunk, end="", flush=True)
            output.append(chunk)

        process.wait()
        return process.returncode, "".join(output)

    except Exception as e:
        return 1, str(e)


def run_cmd_pexpect(
    command: str,
    verbose: bool = False,
    cwd: str | None = None,
) -> tuple[int, str]:
    """使用 pexpect 执行交互式命令

    Args:
        command: 要执行的命令
        verbose: 是否打印详细信息
        cwd: 工作目录

    Returns:
        (返回码, 输出内容) 元组
    """
    if verbose:
        print("Using run_cmd_pexpect:", command)

    if not HAS_PEXPECT:
        return run_cmd_subprocess(command, verbose, cwd)

    output = BytesIO()

    def output_callback(b: bytes) -> bytes:
        output.write(b)
        return b

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        if verbose:
            print("With shell:", shell)

        if os.path.exists(shell):
            if verbose:
                print("Running pexpect.spawn with shell:", shell)
            child = pexpect.spawn(shell, args=["-i", "-c", command], encoding="utf-8", cwd=cwd)
        else:
            if verbose:
                print("Running pexpect.spawn without shell.")
            child = pexpect.spawn(command, encoding="utf-8", cwd=cwd)

        child.interact(output_filter=output_callback)
        child.close()
        return child.exitstatus, output.getvalue().decode("utf-8", errors="replace")

    except (pexpect.ExceptionPexpect, TypeError, ValueError) as e:
        error_msg = f"Error running command {command}: {e}"
        return 1, error_msg


def run_cmd_check_output(command: str, cwd: str | None = None) -> str:
    """执行命令并返回输出（检查返回码）

    Args:
        command: 要执行的命令
        cwd: 工作目录

    Returns:
        命令输出

    Raises:
        subprocess.CalledProcessError: 命令返回非零退出码
    """
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    result.check_returncode()
    return result.stdout


def is_windows_powershell() -> bool:
    """检测是否在 Windows PowerShell 中运行

    Returns:
        True 如果在 PowerShell 中
    """
    if platform.system() != "Windows":
        return False

    parent = get_windows_parent_process_name()
    return parent == "powershell.exe"


__all__ = [
    "get_windows_parent_process_name",
    "is_windows_powershell",
    "run_cmd",
    "run_cmd_check_output",
    "run_cmd_pexpect",
    "run_cmd_subprocess",
]
