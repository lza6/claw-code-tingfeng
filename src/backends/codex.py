"""Codex CLI 后端适配器

把 OpenAI Codex（Apache-2.0，Rust 内核）当作 clawd 的一个执行后端：
我们提供目标与配置，Codex 负责真正的 agent 循环、工具执行与沙箱。

协议: `codex exec --json <prompt>` 输出 JSONL 事件流，典型事件
  {"type":"thread.started","thread_id":"..."}
  {"type":"item.completed","item":{"item_type":"agent_message","text":"..."}}
  {"type":"item.completed","item":{"item_type":"command_execution","command":"...","exit_code":0}}
  {"type":"turn.completed","usage":{"input_tokens":123,"output_tokens":45}}
  {"type":"error","message":"..."}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import os
import shutil
import subprocess
import sys

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


class CodexBackendError(RuntimeError):
    """Codex 后端不可用 / 执行失败"""


@dataclass
class CodexRunResult:
    """一次 Codex 执行的结果"""

    text: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.errors and not self.timed_out


def parse_events(lines: Iterable[str]) -> dict[str, Any]:
    """把 codex 的 JSONL 事件流归一化成结构化结果

    容错原则：单行 JSON 坏掉只记 warning，不中断整轮（长程任务不能因一行脏输出全丢）。
    """
    events: list[dict[str, Any]] = []
    messages: list[str] = []
    commands: list[dict[str, Any]] = []
    errors: list[str] = []
    usage: dict[str, Any] = {}
    thread_id: str | None = None

    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        etype = event.get("type")

        if etype == "thread.started":
            thread_id = event.get("thread_id") or thread_id
        elif etype == "turn.completed":
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
        elif etype == "error":
            msg = event.get("message") or event.get("error") or "unknown error"
            errors.append(str(msg))
        elif etype == "item.completed":
            item = event.get("item") or {}
            item_type = item.get("item_type") or item.get("type")
            if item_type in ("agent_message", "assistant_message"):
                text = item.get("text") or item.get("content") or ""
                if text:
                    messages.append(str(text))
            elif item_type in ("command_execution", "exec_command", "tool_call"):
                commands.append({
                    "command": item.get("command") or item.get("cmd") or "",
                    "exit_code": item.get("exit_code"),
                })

    return {
        "events": events,
        "text": "\n".join(messages).strip(),
        "messages": messages,
        "commands": commands,
        "errors": errors,
        "usage": usage,
        "thread_id": thread_id,
    }


def _resolve_binary(binary: str | Sequence[str]) -> list[str]:
    """解析可执行文件（Windows 上 npm 全局装的 codex 是 .cmd）"""
    if isinstance(binary, (list, tuple)):
        argv = [str(b) for b in binary]
        if not argv:
            raise CodexBackendError("binary 不能为空")
        head = argv[0]
        if not (Path(head).exists() or shutil.which(head)):
            raise CodexBackendError(f"未找到 codex 可执行文件（{head}）")
        return argv

    found = shutil.which(binary)
    if found:
        return [found]
    if sys.platform == "win32":
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(binary + suffix)
            if found:
                return [found]
    raise CodexBackendError(
        f"未找到 codex 可执行文件（{binary}）。安装: npm i -g @openai/codex"
    )


@dataclass
class CodexBackend:
    """Codex CLI 后端

    Attributes:
        binary: 可执行名或 argv 前缀（测试可注入假进程）
        model: 模型名（None 用 Codex 自身配置）
        provider: 模型提供方标识（如 openai）
        base_url: OpenAI 兼容端点（None 用 Codex 配置）
        sandbox: 沙箱模式：read-only / workspace-write / danger-full-access
        workdir: 执行目录
        extra_config: 追加的 `-c key=value` 覆盖项
    """

    binary: str | Sequence[str] = "codex"
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    sandbox: str = "workspace-write"
    workdir: Path | str = "."
    extra_config: dict[str, Any] = field(default_factory=dict)
    skip_git_check: bool = True
    #: 从哪个环境变量读取 API Key（Codex 自定义 provider 用 env_key 引用）
    api_key_env: str = "OPENAI_API_KEY"
    #: 兼容端点协议：responses（Codex 0.165 起 chat 已废弃）
    wire_api: str = "responses"
    #: 跳过 Codex 的审批与沙箱（挂机/CI 用；会让 MCP 工具调用不再等人批）
    dangerously_bypass_approvals: bool = False
    #: 注入给 Codex 的 MCP server（把我们的领域工具交给它调用）
    #: 形如 {"clawd": {"command": "python", "args": ["-m", "src.mcp.domain_server"]}}
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ---------- 可用性 ----------
    def available(self) -> bool:
        try:
            _resolve_binary(self.binary)
            return True
        except CodexBackendError:
            return False

    def version(self) -> str | None:
        argv = _resolve_binary(self.binary)
        try:
            proc = subprocess.run(
                [*argv, "--version"], capture_output=True, text=True, timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        out = (proc.stdout or proc.stderr or "").strip()
        return out.splitlines()[-1] if out else None

    # ---------- 参数组装 ----------
    def build_argv(self, goal: str) -> list[str]:
        argv = [*_resolve_binary(self.binary), "exec", "--json", "--sandbox", self.sandbox]
        if self.skip_git_check:
            argv.append("--skip-git-repo-check")
        if self.dangerously_bypass_approvals:
            # 实测：MCP 工具调用默认需要审批；不跳过会返回
            # "MCP tool call requires approval, but approval policy is never"
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        if self.model:
            argv += ["-c", f'model="{self.model}"']

        if self.base_url:
            # Codex 禁止覆盖内置 provider（openai/oss 等），自定义端点必须注册成新 provider。
            # 见实测: "model_providers contains reserved built-in provider IDs: openai"
            builtin = {"openai", "oss", "anthropic", "gemini", "ollama", "azure"}
            name = self.provider or "clawd"
            if name.lower() in builtin:
                name = f"{name}-custom"
            argv += [
                "-c", f'model_provider="{name}"',
                "-c", f'model_providers.{name}.name="{name}"',
                "-c", f'model_providers.{name}.base_url="{self.base_url}"',
                "-c", f'model_providers.{name}.env_key="{self.api_key_env}"',
                "-c", f'model_providers.{name}.wire_api="{self.wire_api}"',
            ]
        elif self.provider:
            argv += ["-c", f'model_provider="{self.provider}"']
        for name, spec in self.mcp_servers.items():
            argv += ["-c", f"mcp_servers.{name}.command={json.dumps(spec['command'])}"]
            if spec.get("args"):
                argv += ["-c", f"mcp_servers.{name}.args={json.dumps(spec['args'])}"]
            if spec.get("env"):
                argv += ["-c", f"mcp_servers.{name}.env={json.dumps(spec['env'])}"]
        for key, value in self.extra_config.items():
            argv += ["-c", f"{key}={json.dumps(value)}"]
        argv.append(goal)
        return argv

    # ---------- 执行 ----------
    def run(self, goal: str, timeout: float = 900.0) -> CodexRunResult:
        """执行一次非交互式 agent 任务

        Args:
            goal: 任务描述
            timeout: 硬超时（秒）。超时后强杀进程树，返回 timed_out=True，
                     绝不无限等待（长程任务的可控性底线）。
        """
        if not goal or not goal.strip():
            raise CodexBackendError("goal 不能为空")

        import time

        argv = self.build_argv(goal)
        env = dict(os.environ)
        started = time.perf_counter()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self.workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as e:
            raise CodexBackendError(f"启动 codex 失败: {e}") from e

        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""

        duration = time.perf_counter() - started
        parsed = parse_events((stdout or "").splitlines())
        if stderr and stderr.strip():
            parsed["errors"].extend(
                ln.strip() for ln in stderr.splitlines() if ln.strip()
            )

        return CodexRunResult(
            text=parsed["text"],
            events=parsed["events"],
            commands=parsed["commands"],
            usage=parsed["usage"],
            thread_id=parsed["thread_id"],
            errors=parsed["errors"],
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_s=duration,
            timed_out=timed_out,
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """强杀进程树（Windows 下 codex 会拉起子进程，不能只 kill 父进程）"""
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=20, check=False,
                )
                return
            except (OSError, subprocess.SubprocessError) as e:
                logger.debug("taskkill 失败，回退到 kill: %s", e)
        try:
            proc.kill()
        except OSError as e:
            logger.debug("进程强杀失败（忽略）: %s", e)
