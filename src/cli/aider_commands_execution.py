"""执行命令 - Aider 风格执行命令

此模块包含执行相关的命令:
- cmd_run: 执行 shell 命令
- cmd_shell: 启动交互式 shell
- cmd_test: 运行测试
- cmd_lint: 运行代码检查
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from ..utils.colors import dim, status_pass, status_warn

if TYPE_CHECKING:
    from .aider_commands_base import AiderCommandHandler


def cmd_run(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """执行 shell 命令并返回结果

    用法: /run <command>
    """
    if not args.strip():
        return False, "用法: /run <command>"

    # [汲取 GoalX] 增加自动修复建议提示
    try:
        result = subprocess.run(
            args,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = []
        if result.stdout:
            output.append(result.stdout)
        if result.stderr:
            output.append(dim(f"[stderr] {result.stderr}"))

        if result.returncode != 0:
            output.append(status_warn(f"Exit code: {result.returncode}"))
            # 汲取 GoalX: 如果是常见错误，提示 AI 可能需要执行的操作
            if "not found" in result.stderr.lower() or "not recognized" in result.stderr.lower():
                output.append(dim("\n提示: 检查命令是否拼写正确，或是否已在 PATH 中。"))
            elif "denied" in result.stderr.lower() or "permission" in result.stderr.lower():
                output.append(dim("\n提示: 权限不足。在 God Mode 下 Bash 工具会自动尝试绕过安全限制。"))

        return True, '\n'.join(output) if output else "(无输出)"

    except subprocess.TimeoutExpired:
        return False, "命令超时 (30s)"
    except Exception as e:
        return False, f"执行失败: {e}"


def cmd_shell(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """启动交互式 shell

    用法: /shell [command]
    """
    if args.strip():
        # 执行命令
        return cmd_run(self, args)

    return True, """启动交互式 shell (输入 exit 退出)

提示: 使用 ! 前缀也可以执行命令
  !ls -la
"""


def cmd_test(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """运行测试

    用法: /test [test_file] [pytest args...]
    """
    # 检测测试框架
    test_cmd = "pytest"

    # [汲取 GoalX] 自动检测测试模式并注入环境变量
    os.environ["CLAWD_CLI_TEST_MODE"] = "1"

    if args.strip():
        # 检查是否有 pytest.ini 或 pyproject.toml
        if os.path.exists("pytest.ini") or os.path.exists("pyproject.toml") or os.path.exists("tests"):
            test_cmd = f"pytest {args}"
        else:
            # 尝试作为 Python 模块运行
            test_cmd = f"python -m pytest {args}" if "::" in args else f"python {args}"
    else:
        test_cmd = "pytest"

    try:
        # [汲取 GoalX] 运行前输出提示
        print(dim(f"  正在执行: {test_cmd}"))
        result = subprocess.run(
            test_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120, # 汲取 GoalX: 增加到 120s
        )

        output = []
        if result.stdout:
            # 汲取 GoalX: 增加智能截断，保留摘要和失败详情
            if len(result.stdout) > 5000:
                summary_match = re.search(r"=.*?short test summary info.*?=", result.stdout, re.DOTALL)
                if summary_match:
                    output.append(dim("... [输出过长，已截断前部] ...\n"))
                    output.append(result.stdout[summary_match.start():])
                else:
                    output.append(result.stdout[-3000:])
            else:
                output.append(result.stdout)

        if result.stderr:
            output.append(dim(f"[stderr] {result.stderr[-500:]}"))

        passed = result.returncode == 0
        status = status_pass("通过") if passed else status_warn("失败")
        output.append(f"\n{status} (exit code: {result.returncode})")

        # [汲取 GoalX] 自动记录证据 (Evidence)
        try:
            # 尝试获取当前运行状态管理器
            # 注意: 这里假设 AiderCommandHandler 能够访问到相关的 run_id 或 manager
            # 如果没有直接的 manager，我们尝试从默认路径加载
            run_manager = getattr(self, "run_manager", None)
            if run_manager:
                evidence_id = f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                run_manager.add_evidence_entry(
                    evidence_id=evidence_id,
                    evidence_type="test_result",
                    description=f"Executed test command: {test_cmd}",
                    data={
                        "command": test_cmd,
                        "exit_code": result.returncode,
                        "passed": passed,
                        "stdout_snippet": result.stdout[-500:] if result.stdout else ""
                    },
                    recorded_by="aider-cli"
                )
                print(dim(f"  已自动记录证据: {evidence_id}"))
        except Exception:
            # 记录证据失败不应导致命令报错
            pass

        return True, '\n'.join(output)

    except subprocess.TimeoutExpired:
        return False, "测试超时 (120s)"
    except Exception as e:
        return False, f"运行测试失败: {e}"


def cmd_lint(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """运行代码检查

    用法: /lint [file]
    """
    # 检测可用的 linter
    linters = []
    if os.path.exists("ruff.toml") or os.path.exists(".ruff.toml"):
        linters.append("ruff check")
    if os.path.exists("pyproject.toml"):
        linters.append("ruff check")

    if not linters:
        return False, "未找到可用的 linter (需要 ruff)"

    target = args.strip() if args.strip() else "."

    try:
        result = subprocess.run(
            f"{linters[0]} {target}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = []
        if result.stdout:
            output.append(result.stdout)
        if result.stderr:
            output.append(dim(f"[stderr] {result.stderr}"))

        status = status_pass("无问题") if result.returncode == 0 else status_warn("发现问题")
        output.append(f"\n{status}")

        return True, '\n'.join(output)

    except Exception as e:
        return False, f"运行 linter 失败: {e}"
