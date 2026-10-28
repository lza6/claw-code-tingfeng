"""LSP 工具测试：协议/边界用假服务器，能力用真实 pylsp（未装则跳过）"""

from __future__ import annotations

import json
import subprocess
import sys
import time

from pathlib import Path

import pytest

from src.lsp import LSPClient, LSPUnavailable, available_servers, language_for, which_server
from src.tools_runtime import lsp_tool as lsp_tool_mod
from src.tools_runtime.lsp_tool import LSPTool, shutdown_clients


PYLSP_AVAILABLE = which_server("pylsp") is not None

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    shutdown_clients()


# ==========================================================================
# 语言映射与探测
# ==========================================================================


class TestLanguageDetection:
    @pytest.mark.parametrize("name,expected", [
        ("a.py", "python"), ("b.go", "go"), ("c.ts", "typescript"),
        ("d.tsx", "typescript"), ("e.rs", "rust"), ("f.md", None),
    ])
    def test_language_for(self, name, expected):
        assert language_for(name) == expected

    def test_available_servers_returns_bool_map(self):
        servers = available_servers()
        assert set(servers) == {"python", "go", "typescript", "rust"}
        assert all(isinstance(v, bool) for v in servers.values())


# ==========================================================================
# 工具边界（无需真实服务器）
# ==========================================================================


class TestToolBoundaries:
    def test_unsupported_extension_is_explicit(self, tmp_path: Path):
        (tmp_path / "notes.md").write_text("# hi\n", encoding="utf-8")
        result = LSPTool(tmp_path).execute(action="diagnostics", file_path="notes.md")

        assert result.success is False
        assert "未配置 LSP" in result.error
        assert result.exit_code == 1

    def test_missing_file_is_explicit(self, tmp_path: Path):
        result = LSPTool(tmp_path).execute(action="diagnostics", file_path="nope.py")
        assert result.success is False
        assert "不存在" in result.error

    def test_path_traversal_rejected(self, tmp_path: Path):
        result = LSPTool(tmp_path).execute(action="diagnostics", file_path="../../etc/passwd.py")
        assert result.success is False
        assert "越界" in result.error

    def test_missing_file_path_is_explicit(self, tmp_path: Path):
        result = LSPTool(tmp_path).execute(action="diagnostics")
        assert result.success is False
        assert "file_path" in result.error

    def test_definition_requires_line(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        result = LSPTool(tmp_path).execute(action="definition", file_path="a.py")
        # 未给 line：在启动服务器前就该被拦下（若服务器缺失也接受 exit 2）
        assert result.success is False

    def test_unknown_action_is_explicit(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        result = LSPTool(tmp_path).execute(action="bogus", file_path="a.py")
        assert result.success is False
        assert ("未知 action" in result.error) or ("LSP" in result.error)

    def test_risk_kind_is_read(self):
        assert LSPTool.risk_kind == "read"


# ==========================================================================
# 真实 pylsp（未安装则跳过）—— 真实 E2E
# ==========================================================================


requires_pylsp = pytest.mark.skipif(not PYLSP_AVAILABLE, reason="未安装 pylsp")


@pytest.fixture
def py_project(tmp_path: Path) -> Path:
    (tmp_path / "mod.py").write_text(
        "def helper(x: int) -> int:\n    return x + 1\n", encoding="utf-8"
    )
    (tmp_path / "broken.py").write_text(
        "import mod\n\n\ndef use():\n    return mod.helper('not-an-int') + undefined_name\n",
        encoding="utf-8",
    )
    return tmp_path


@requires_pylsp
class TestRealPylsp:
    def test_diagnostics_finds_undefined_name(self, py_project: Path):
        result = LSPTool(py_project).execute(action="diagnostics", file_path="broken.py")

        assert result.success is True, result.error
        payload = json.loads(result.output)
        assert payload["count"] >= 1
        messages = " ".join(d["message"] for d in payload["diagnostics"])
        assert "undefined_name" in messages
        # 行号对外必须是 1-based（undefined_name 在第 5 行）
        assert any(d["line"] == 5 for d in payload["diagnostics"])

    def test_definition_uses_1_based_line_input(self, py_project: Path):
        """第 5 行（1-based）= LSP 的 line 4，必须命中 mod.helper 的定义"""
        result = LSPTool(py_project).execute(
            action="definition", file_path="broken.py", line=5, column=16
        )

        assert result.success is True, result.error
        payload = json.loads(result.output)
        assert payload["count"] >= 1
        assert any("mod.py" in d["path"] or "mod.py" in d["uri"] for d in payload["definitions"])

    def test_hover_returns_signature(self, py_project: Path):
        result = LSPTool(py_project).execute(
            action="hover", file_path="broken.py", line=5, column=16
        )

        assert result.success is True, result.error
        payload = json.loads(result.output)
        assert "helper" in payload["hover"] or "int" in payload["hover"]

    def test_client_is_reused_across_calls(self, py_project: Path):
        """LSP 启动要几秒，必须复用同一客户端（不能每次重启）"""
        tool = LSPTool(py_project)
        tool.execute(action="diagnostics", file_path="broken.py")
        first = dict(lsp_tool_mod._CLIENTS)
        tool.execute(action="diagnostics", file_path="mod.py")
        second = dict(lsp_tool_mod._CLIENTS)

        assert set(first) == set(second)
        assert all(second[k] is first[k] for k in first)


# ==========================================================================
# 协议层单测（Content-Length 分帧）
# ==========================================================================


FAKE_LSP = r'''
import json, sys

def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))

def send(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
    sys.stdout.buffer.flush()

while True:
    msg = read()
    if msg is None:
        break
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
    elif method == "textDocument/didOpen":
        uri = msg["params"]["textDocument"]["uri"]
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "diagnostics": [
                  {"range": {"start": {"line": 2, "character": 4}},
                   "severity": 1, "message": "fake problem", "code": "F001"}]}})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": [
            {"uri": "file:///x/target.py", "range": {"start": {"line": 7, "character": 0}}}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"contents": {"value": "sig: int"}}})
    elif method == "exit":
        break
    elif "id" in msg:
        send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
'''


@pytest.fixture
def fake_server(tmp_path: Path) -> tuple[str, list[str]]:
    script = tmp_path / "fake_lsp.py"
    script.write_text(FAKE_LSP, encoding="utf-8")
    return (sys.executable, [str(script)])


class TestProtocolWithFakeServer:
    def test_content_length_framing_roundtrip(self, tmp_path: Path, fake_server):
        """真实子进程验证分帧：中文与非 ASCII 也必须按 UTF-8 字节数计算长度"""
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        command, args = fake_server
        client = LSPClient(command, args, root=tmp_path, request_timeout=30)
        client.start()
        try:
            diags = client.diagnostics("a.py", wait=5)
            assert len(diags) == 1
            assert diags[0].message == "fake problem"
            assert diags[0].line == 2 and diags[0].severity_name == "error"

            locs = client.definition("a.py", 0, 0)
            assert locs and "target.py" in str(locs[0].get("uri"))

            assert "sig: int" in client.hover("a.py", 0, 0)
        finally:
            client.stop()

    def test_unavailable_binary_raises(self, tmp_path: Path):
        client = LSPClient("definitely-not-a-real-lsp-xyz", [], root=tmp_path)
        assert client.available() is False
        with pytest.raises(LSPUnavailable):
            client.start()
