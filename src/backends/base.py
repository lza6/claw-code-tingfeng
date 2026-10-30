"""统一后端抽象 — 让不同 agent 引擎共用一套驱动/探活/结果语义

设计目标（多引擎整合）:
- **一个接口**：`CliBackend.run(goal) -> BackendResult`，上层无需关心引擎差异
- **一份代码**：子进程管理、超时强杀、JSONL 归一化只写一次（`CliBackend`）
- **按引擎配置**：argv 模板 + 事件映射写在 `CliEngineProfile`，新增引擎只加配置
- **诚实探活**：`probe()` 返回真实可用性（未安装 / 版本不兼容 / 就绪），不假装支持
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


class BackendUnavailable(RuntimeError):
    """引擎不可用（未安装 / 版本不兼容 / 探活失败）"""


@dataclass
class BackendResult:
    """统一的执行结果（跨引擎）"""

    engine: str = ""
    text: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    session_id: str | None = None
    exit_code: int = 0
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.errors and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "ok": self.ok,
            "text": self.text,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 2),
            "timed_out": self.timed_out,
            "usage": self.usage,
            "commands": self.commands,
            "errors": self.errors[:5],
            "session_id": self.session_id,
        }


@dataclass
class EngineProbe:
    """引擎探活结果"""

    name: str
    status: str  # ready | not_installed | incompatible | error
    version: str | None = None
    detail: str = ""
    binary: str | None = None

    @property
    def usable(self) -> bool:
        return self.status == "ready"


@dataclass
class CliEngineProfile:
    """CLI 引擎画像（新增引擎只需一份配置）

    Attributes:
        name: 引擎标识
        binary: 可执行名（Windows 会尝试 .cmd/.exe/.bat）
        version_args: 打印版本的参数
        argv_template: argv 模板，支持占位符 {goal} / {sandbox} / {model}
        json_flag_args: 开启结构化输出的参数（空 = 纯文本模式）
        event_text_keys: 从 JSONL 事件里取"助手文本"的候选字段路径
        event_command_keys: 从事件里取"命令执行"的候选字段路径
        event_usage_keys: 从事件里取 token 用量的候选字段路径
        event_session_keys: 从事件里取会话 id 的候选字段
        min_node: 可选，Node 引擎的最低/最高版本约束（探活用）
    """

    name: str
    binary: str
    version_args: tuple[str, ...] = ("--version",)
    argv_template: tuple[str, ...] = ()
    json_flag_args: tuple[str, ...] = ()
    event_text_keys: tuple[str, ...] = ()
    event_command_keys: tuple[str, ...] = ()
    event_usage_keys: tuple[str, ...] = ()
    event_session_keys: tuple[str, ...] = ()
    runtime_check: str | None = None  # 例如 "node"


def _dig(obj: Any, dotted: str) -> Any:
    """按 'a.b.c' 取嵌套字段（不存在返回 None）"""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def resolve_binary(binary: str | Sequence[str]) -> list[str]:
    """解析可执行文件（兼容 Windows 的 .cmd/.exe/.bat）"""
    if isinstance(binary, (list, tuple)):
        argv = [str(b) for b in binary]
        if not argv:
            raise BackendUnavailable("binary 不能为空")
        head = argv[0]
        if not (Path(head).exists() or shutil.which(head)):
            raise BackendUnavailable(f"未找到可执行文件: {head}")
        return argv

    found = shutil.which(binary)
    if found:
        return [found]
    if sys.platform == "win32":
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(binary + suffix)
            if found:
                return [found]
    raise BackendUnavailable(f"未找到可执行文件: {binary}")


class CliBackend:
    """通用 CLI 引擎后端（子进程 + JSONL 归一化 + 超时强杀）"""

    def __init__(
        self,
        profile: CliEngineProfile,
        *,
        workdir: Path | str = ".",
        sandbox: str = "workspace-write",
        model: str | None = None,
        extra_args: Sequence[str] = (),
        binary_override: Sequence[str] | None = None,
    ):
        self.profile = profile
        self.workdir = Path(workdir)
        self.sandbox = sandbox
        self.model = model
        self.extra_args = list(extra_args)
        self.binary_override = list(binary_override) if binary_override else None

    # ---------- 探活 ----------
    def _argv0(self) -> list[str]:
        if self.binary_override:
            return resolve_binary(self.binary_override)
        return resolve_binary(self.profile.binary)

    def probe(self) -> EngineProbe:
        name = self.profile.name
        try:
            argv = self._argv0()
        except BackendUnavailable as e:
            return EngineProbe(name=name, status="not_installed", detail=str(e))

        version: str | None = None
        try:
            proc = subprocess.run(
                [*argv, *self.profile.version_args],
                capture_output=True, text=True, timeout=45, check=False,
                encoding="utf-8", errors="replace",
            )
            raw = ((proc.stdout or "") + (proc.stderr or "")).strip()
            version = raw.splitlines()[-1] if raw else None
            # 有些 CLI 用版本探测来报运行时版本不满足（如 openclaw）
            if proc.returncode not in (0, None) and raw:
                if "Node.js" in raw and "required" in raw:
                    return EngineProbe(
                        name=name, status="incompatible",
                        version=None, detail=raw.splitlines()[0], binary=argv[0],
                    )
                return EngineProbe(
                    name=name, status="error", version=version,
                    detail=raw.splitlines()[0] if raw else f"exit={proc.returncode}",
                    binary=argv[0],
                )
        except (OSError, subprocess.SubprocessError) as e:
            return EngineProbe(name=name, status="error", detail=str(e), binary=argv[0])

        return EngineProbe(name=name, status="ready", version=version, binary=argv[0])

    # ---------- 执行 ----------
    def build_argv(self, goal: str) -> list[str]:
        argv = [*self._argv0()]
        for part in self.profile.argv_template:
            argv.append(part.format(goal=goal, sandbox=self.sandbox, model=self.model or ""))
        argv += list(self.profile.json_flag_args)
        argv += self.extra_args
        return argv

    def parse(self, stdout_lines: Sequence[str], stderr: str = "") -> BackendResult:
        """把引擎输出归一化为 BackendResult（容错：坏行跳过，不中断）"""
        events: list[dict[str, Any]] = []
        texts: list[str] = []
        commands: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        session_id: str | None = None
        plain_lines: list[str] = []
        errors_from_events: list[str] = []

        for raw in stdout_lines:
            line = (raw or "").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                plain_lines.append(line)
                continue
            if not isinstance(event, dict):
                plain_lines.append(line)
                continue
            events.append(event)

            for key in self.profile.event_text_keys:
                value = _dig(event, key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
                    break
            for key in self.profile.event_command_keys:
                value = _dig(event, key)
                if isinstance(value, str) and value.strip():
                    commands.append({"command": value.strip(), "exit_code": None})
                    break
                if isinstance(value, dict):
                    commands.append({
                        "command": value.get("command") or value.get("cmd") or "",
                        "exit_code": value.get("exit_code"),
                    })
                    break
            for key in self.profile.event_usage_keys:
                value = _dig(event, key)
                if isinstance(value, dict) and value:
                    usage = value
                    break
            for key in self.profile.event_session_keys:
                value = _dig(event, key)
                if isinstance(value, str) and value:
                    session_id = value
                    break

        # 纯文本引擎（无 JSONL）：整体输出即文本
        if not texts and plain_lines:
            texts = ["\n".join(plain_lines)]

        # JSON 事件里的 error 也要计入 errors（否则引擎失败会被当成"无输出成功"）
        for event in events:
            if str(event.get("type") or "").lower() in ("error", "turn.failed", "failed"):
                raw = event.get("error") or event.get("message") or event
                if isinstance(raw, dict):
                    msg = raw.get("message") or raw.get("data") or json.dumps(raw, ensure_ascii=False)
                else:
                    msg = str(raw)
                if msg:
                    errors_from_events.append(str(msg)[:500])

        errors = errors_from_events + [
            ln.strip() for ln in (stderr or "").splitlines() if ln.strip()
        ]
        return BackendResult(
            engine=self.profile.name,
            text="\n".join(texts).strip(),
            events=events,
            commands=commands,
            usage=usage,
            errors=errors,
            session_id=session_id,
        )

    def run(self, goal: str, timeout: float = 900.0) -> BackendResult:
        if not goal or not goal.strip():
            raise BackendUnavailable("goal 不能为空")
        argv = self.build_argv(goal)
        started = time.perf_counter()
        try:
            proc = subprocess.Popen(
                argv, cwd=str(self.workdir),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as e:
            raise BackendUnavailable(f"启动 {self.profile.name} 失败: {e}") from e

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

        result = self.parse((stdout or "").splitlines(), stderr or "")
        result.exit_code = proc.returncode if proc.returncode is not None else -1
        result.duration_s = time.perf_counter() - started
        result.timed_out = timed_out
        return result

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
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
