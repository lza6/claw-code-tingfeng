"""LSP 客户端（Content-Length 分帧的 JSON-RPC over stdio）

借鉴 OpenCode `internal/lsp/`（Go，MIT）的机制：stdio + Content-Length 帧 + 请求 id 分发。
我们只实现 agent 真正需要的最小面：诊断 / 跳转定义 / 悬停类型。

Windows 关键点：必须走**二进制流**。用文本流会把 "\r\n" 做换行转换、并按本地编码
（GBK）写入，帧长度与字节数就对不上——这类问题只有在真实服务器上才会暴露。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 语言 → (命令, 参数) 映射（可按需扩展；未配置的语言直接报"不支持"）
LANGUAGE_SERVERS: dict[str, tuple[str, list[str]]] = {
    "python": ("pylsp", []),
    "go": ("gopls", []),
    "typescript": ("typescript-language-server", ["--stdio"]),
    "rust": ("rust-analyzer", []),
}

_EXT_LANGUAGE = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".rs": "rust",
}


class LSPError(RuntimeError):
    """LSP 不可用或协议错误"""


class LSPUnavailable(LSPError):
    """找不到语言服务器（未安装）"""


def _which(cmd: str) -> str | None:
    """查找可执行文件：先 PATH，再当前解释器同目录（venv/Scripts）

    原因：pylsp 通常装在 venv 里，未激活时不在 PATH，只查 PATH 会误报"未安装"。
    """
    import shutil as _shutil

    found = _shutil.which(cmd)
    if found:
        return found
    exe_dir = Path(sys.executable).parent
    for suffix in ("", ".exe", ".cmd", ".bat"):
        candidate = exe_dir / (cmd + suffix)
        if candidate.is_file():
            return str(candidate)
    return None


def which_server(cmd: str) -> str | None:
    """公开别名：查找语言服务器可执行文件（PATH + venv 目录）"""
    return _which(cmd)


def language_for(path: str | Path) -> str | None:
    return _EXT_LANGUAGE.get(Path(path).suffix.lower())


@dataclass
class Diagnostic:
    line: int
    character: int
    severity: int
    message: str
    code: str | None = None

    @property
    def severity_name(self) -> str:
        return {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(self.severity, "?")


@dataclass
class LSPClient:
    """极简 LSP 客户端

    用法：
        client = LSPClient("pylsp", [], root=Path("."))
        client.start()
        client.open_file("pkg/core.py")
        diags = client.diagnostics("pkg/core.py")
        loc = client.definition("pkg/core.py", line=12, character=8)
        client.stop()
    """

    command: str
    args: list[str] = field(default_factory=list)
    root: Path = field(default_factory=lambda: Path.cwd())
    request_timeout: float = 20.0

    proc: subprocess.Popen | None = None
    _next_id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _responses: dict[int, dict[str, Any]] = field(default_factory=dict)
    _responses_cv: threading.Condition = field(default_factory=threading.Condition)
    _diagnostics: dict[str, list[Diagnostic]] = field(default_factory=dict)
    _reader: threading.Thread | None = None
    _opened: dict[str, int] = field(default_factory=dict)  # uri -> version
    _ready: bool = False
    _stderr_tail: list[str] = field(default_factory=list)

    # ---------- 生命周期 ----------
    def available(self) -> bool:
        return _which(self.command) is not None

    def start(self) -> None:
        if self.proc is not None:
            return
        if not self.available():
            raise LSPUnavailable(
                f"语言服务器未安装: {self.command}"
                f"（Python 可 `pip install python-lsp-server`）"
            )
        exe = _which(self.command) or self.command
        try:
            self.proc = subprocess.Popen(
                [exe, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.root),
            )
        except OSError as e:
            raise LSPUnavailable(f"启动语言服务器失败: {e}") from e

        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name="lsp-reader")
        self._reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True,
                         name="lsp-stderr").start()
        self._initialize()

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self._notify("exit", {})
        except Exception:  # noqa: BLE001 — 关闭阶段异常不重要
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self.proc = None
        self._ready = False
        self._opened.clear()

    # ---------- 帧读写 ----------
    def _write(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise LSPError("进程未启动")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self.proc.stdin.write(header + body)
            self.proc.stdin.flush()

    def _read_message(self) -> dict[str, Any] | None:
        assert self.proc is not None and self.proc.stdout is not None
        stream = self.proc.stdout
        length = None
        while True:
            line = stream.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if line.lower().startswith(b"content-length:"):
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    return None
        if length is None:
            return None
        body = stream.read(length)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    def _drain_stderr(self) -> None:
        if self.proc is None or self.proc.stderr is None:
            return
        for raw in self.proc.stderr:
            txt = raw.decode("utf-8", errors="replace").strip()
            if txt:
                self._stderr_tail.append(txt)
                del self._stderr_tail[:-20]

    def _read_loop(self) -> None:
        while True:
            try:
                msg = self._read_message()
            except Exception:  # noqa: BLE001 — 读流出错即结束
                break
            if msg is None:
                break

            # 服务端通知：publishDiagnostics
            if msg.get("method") == "textDocument/publishDiagnostics":
                params = msg.get("params") or {}
                uri = str(params.get("uri") or "")
                items = params.get("diagnostics") or []
                self._diagnostics[uri] = [
                    Diagnostic(
                        line=int((d.get("range", {}).get("start", {}) or {}).get("line", 0)),
                        character=int((d.get("range", {}).get("start", {}) or {}).get("character", 0)),
                        severity=int(d.get("severity") or 1),
                        message=str(d.get("message") or ""),
                        code=str(d.get("code")) if d.get("code") is not None else None,
                    )
                    for d in items if isinstance(d, dict)
                ]
                continue

            if "id" in msg and ("result" in msg or "error" in msg):
                with self._responses_cv:
                    self._responses[int(msg["id"])] = msg
                    self._responses_cv.notify_all()

    # ---------- RPC ----------
    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        req_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.time() + self.request_timeout
        with self._responses_cv:
            while req_id not in self._responses:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise LSPError(f"LSP 请求超时: {method}")
                self._responses_cv.wait(remaining)
            msg = self._responses.pop(req_id)
        if "error" in msg:
            raise LSPError(f"LSP 错误 {method}: {msg['error']}")
        return msg.get("result")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # ---------- 高层操作 ----------
    def _initialize(self) -> None:
        root_uri = self.root.resolve().as_uri()
        result = self._request("initialize", {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "publishDiagnostics": {},
                    "definition": {},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                }
            },
            "workspaceFolders": [{"uri": root_uri, "name": self.root.name}],
        })
        if not isinstance(result, dict):
            raise LSPError("initialize 返回异常")
        self._notify("initialized", {})
        self._ready = True

    def uri_for(self, path: str | Path) -> str:
        target = Path(path)
        if not target.is_absolute():
            target = (self.root / target)
        return target.resolve().as_uri()

    def open_file(self, path: str | Path) -> str:
        uri = self.uri_for(path)
        text = Path(path if Path(path).is_absolute() else self.root / path).read_text(
            encoding="utf-8", errors="replace"
        )
        lang = language_for(path) or "plaintext"
        version = self._opened.get(uri, 0) + 1
        self._notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": lang, "version": version, "text": text},
        })
        self._opened[uri] = version
        return uri

    def close_file(self, path: str | Path) -> None:
        uri = self.uri_for(path)
        if uri in self._opened:
            self._notify("textDocument/didClose", {"textDocument": {"uri": uri}})
            self._opened.pop(uri, None)

    def diagnostics(self, path: str | Path, wait: float = 3.0) -> list[Diagnostic]:
        """取某文件的诊断（等待 publishDiagnostics 通知）"""
        uri = self.uri_for(path)
        if uri not in self._opened:
            self.open_file(path)
        deadline = time.time() + wait
        while time.time() < deadline:
            if uri in self._diagnostics:
                return self._diagnostics[uri]
            time.sleep(0.05)
        return self._diagnostics.get(uri, [])

    def definition(self, path: str | Path, line: int, character: int) -> list[dict[str, Any]]:
        uri = self.uri_for(path)
        if uri not in self._opened:
            self.open_file(path)
        result = self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def hover(self, path: str | Path, line: int, character: int) -> str:
        uri = self.uri_for(path)
        if uri not in self._opened:
            self.open_file(path)
        result = self._request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not isinstance(result, dict):
            return ""
        contents = result.get("contents")
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            return str(contents.get("value") or "")
        if isinstance(contents, list):
            parts = []
            for c in contents:
                parts.append(c.get("value") if isinstance(c, dict) else str(c))
            return "\n".join(p for p in parts if p)
        return ""

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail[-5:])


def server_command_for(language: str) -> tuple[str, list[str]] | None:
    return LANGUAGE_SERVERS.get(language)


def available_servers() -> dict[str, bool]:
    """各语言服务器是否安装（供 CLI/工具如实展示）"""
    return {
        lang: _which(cmd) is not None
        for lang, (cmd, _args) in LANGUAGE_SERVERS.items()
    }
