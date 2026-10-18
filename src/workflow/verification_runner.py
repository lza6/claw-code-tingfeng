"""真实验证执行器 —— 运行命令并判定通过与否。

## 为什么需要它

`pipeline.py` 的 ralph-verify 阶段曾经硬编码
`"verification_result": "passed"`，**从不运行任何测试**。
v0.55.0 把它改成诚实的 `not_implemented`，但"不会撒谎"不等于"会验证"。

本模块补上执行侧：真正跑一条命令（默认是仓库自己的 pytest），
以**退出码**判定，并把命令、耗时、输出尾部作为证据保留。

## 不做的事

- 不猜结果：没配置验证命令时返回 `not_configured`，绝不返回 `passed`。
- 不用 shell：命令以参数列表执行，避免注入与引号差异。
- 不吞异常：超时/启动失败都有明确 status。

## 配置

优先级：
1. 显式传入的 `command`
2. 环境变量 `CLAWD_VERIFY_COMMAND`（shell 风格字符串，按 Windows 规则切分）
3. 仓库内存在 `tests/` → `python -m pytest -q --tb=short tests`
4. 都没有 → `not_configured`
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .verifier import (
    VerificationEvidence,
    VerificationResult,
    create_verification_result_from_evidence,
)

#: 默认超时（秒）。验证可能跑完整测试集，给足时间但必须有上限。
DEFAULT_TIMEOUT = 900


@dataclass(frozen=True)
class VerificationRun:
    """一次验证运行的完整结果。"""

    status: str  # passed | failed | not_configured | timeout | error
    verified: bool
    command: str
    exit_code: int | None
    duration_ms: int
    output_tail: str
    reason: str = ""

    @property
    def result(self) -> VerificationResult:
        """转换为项目既有的 VerificationResult（含证据列表）。"""
        evidence_type = "test" if self.command else "manual"
        return create_verification_result_from_evidence(
            [(evidence_type, self.verified, self.reason or None)],
            summary=self.reason or self.status,
        )

    def to_artifacts(self) -> dict:
        """可直接放进 StageResult.artifacts 的字典。"""
        return {
            "verification_result": self.status,
            "verified": self.verified,
            "verification_command": self.command,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "output_tail": self.output_tail,
            "reason": self.reason,
        }


def _split_command(cmd: str) -> list[str]:
    """按平台规则切分命令行。

    Windows 下必须用 `posix=False` 以保留反斜杠路径，但它**不会去掉引号**：
    `"C:/x/python.exe" -c "..."` 会被切成带引号的三个 token，导致启动失败。
    这里对每个 token 去掉成对的引号。
    """
    if os.name == "nt":
        tokens = shlex.split(cmd, posix=False)
        cleaned = []
        for t in tokens:
            if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
                t = t[1:-1]
            cleaned.append(t)
        return cleaned
    return shlex.split(cmd)


def resolve_command(
    workdir: Path,
    command: list[str] | str | None = None,
) -> tuple[list[str] | None, str]:
    """解析要执行的验证命令。返回 (argv, 展示用字符串)。"""
    if command:
        if isinstance(command, str):
            return _split_command(command), command
        return list(command), " ".join(command)

    env_cmd = os.environ.get("CLAWD_VERIFY_COMMAND", "").strip()
    if env_cmd:
        return _split_command(env_cmd), env_cmd

    if (workdir / "tests").is_dir():
        argv = [sys.executable, "-m", "pytest", "-q", "--tb=short", "tests"]
        return argv, " ".join(argv)

    return None, ""


def run_verification(
    workdir: Path | str,
    command: list[str] | str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    output_tail_chars: int = 4000,
) -> VerificationRun:
    """在工作目录运行验证命令，以退出码判定是否通过。"""
    cwd = Path(workdir)
    try:
        argv, display = resolve_command(cwd, command)
    except ValueError as exc:
        # 非法命令（例如未闭合引号）不能让异常穿透：
        # 本模块承诺所有失败都有结构化 status。
        return VerificationRun(
            status="error",
            verified=False,
            command=str(command or ""),
            exit_code=None,
            duration_ms=0,
            output_tail="",
            reason=f"验证命令无法解析: {exc}",
        )

    if argv is None:
        return VerificationRun(
            status="not_configured",
            verified=False,
            command="",
            exit_code=None,
            duration_ms=0,
            output_tail="",
            reason=(
                "未找到 tests/ 且未设置 CLAWD_VERIFY_COMMAND；"
                "本阶段未做任何验证（verified=False 不代表通过）"
            ),
        )

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        tail = _tail_of(exc.stdout, exc.stderr, output_tail_chars)
        return VerificationRun(
            status="timeout",
            verified=False,
            command=display,
            exit_code=None,
            duration_ms=elapsed,
            output_tail=tail,
            reason=f"验证命令超时（>{timeout}s）",
        )
    except OSError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return VerificationRun(
            status="error",
            verified=False,
            command=display,
            exit_code=None,
            duration_ms=elapsed,
            output_tail="",
            reason=f"验证命令无法启动: {type(exc).__name__}: {exc}",
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    tail = _tail_of(proc.stdout, proc.stderr, output_tail_chars)
    passed = proc.returncode == 0
    return VerificationRun(
        status="passed" if passed else "failed",
        verified=passed,
        command=display,
        exit_code=proc.returncode,
        duration_ms=elapsed,
        output_tail=tail,
        reason="" if passed else f"验证命令退出码 {proc.returncode}",
    )


def _tail_of(stdout, stderr, limit: int) -> str:
    """合并 stdout/stderr 并只保留尾部，避免把整份日志塞进 artifacts。"""
    parts: list[str] = []
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    if stdout:
        parts.append(str(stdout))
    if stderr:
        parts.append(str(stderr))
    merged = "\n".join(parts).strip()
    return merged[-limit:] if len(merged) > limit else merged
