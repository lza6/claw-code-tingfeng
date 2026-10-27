"""逆向原生工具测试 - strings/entropy/hexdump/ghidra/binary_cli/register_all"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.reverse_tools import register_all
from src.reverse_tools.binary_cli import BinwalkTool, FileTool, ObjdumpTool, ReadelfTool, _run_cli
from src.reverse_tools.ghidra_bridge import GhidraTool
from src.reverse_tools.static_analysis import EntropyTool, HexDumpTool, StringsTool
from src.tools_runtime.tool_interface import ToolCallStatus, ToolRegistry


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def binary_file(tmp_path: Path) -> Path:
    """构造小二进制：含可打印字符串 + 低熵填充 + 高熵随机段"""
    import os

    data = b"Hello, World!\n\x00\x00\x00" + b"\x41" * 64 + os.urandom(256)
    p = tmp_path / "sample.bin"
    p.write_bytes(data)
    return p


# ----------------------------------------------------------------------
# StringsTool
# ----------------------------------------------------------------------
class TestStringsTool:
    def test_extract_default_min_length(self, binary_file: Path):
        result = StringsTool().execute(path=str(binary_file))
        assert result.status == ToolCallStatus.SUCCESS
        assert "Hello, World!" in result.output
        assert result.metadata["count"] >= 1

    def test_min_length_filter(self, binary_file: Path):
        result = StringsTool().execute(path=str(binary_file), min_length=10)
        assert result.status == ToolCallStatus.SUCCESS
        # "Hello, World!" 13 字符应保留
        assert "Hello, World!" in result.output

    def test_min_length_invalid(self, binary_file: Path):
        result = StringsTool().execute(path=str(binary_file), min_length=0)
        assert result.status == ToolCallStatus.ERROR
        assert "min_length" in result.error

    def test_file_not_found(self, tmp_path: Path):
        result = StringsTool().execute(path=str(tmp_path / "nope.bin"))
        assert result.status == ToolCallStatus.ERROR
        assert "读取文件失败" in result.error


# ----------------------------------------------------------------------
# EntropyTool
# ----------------------------------------------------------------------
class TestEntropyTool:
    def test_entropy_range_for_file(self, binary_file: Path):
        result = EntropyTool().execute(path=str(binary_file))
        assert result.status == ToolCallStatus.SUCCESS
        ent = result.metadata["entropy"]
        assert 0.0 <= ent <= 8.0

    def test_constant_bytes_low_entropy(self, binary_file: Path):
        # 64 字节全 'A' 段 → 熵接近 0
        result = EntropyTool().execute(path=str(binary_file), limit=69)  # 跳过头部后仍含字符串
        assert result.status == ToolCallStatus.SUCCESS

    def test_random_data_high_entropy_packing_hint(self):
        import os

        result = EntropyTool().execute(data=os.urandom(4096))
        assert result.status == ToolCallStatus.SUCCESS
        assert result.metadata["entropy"] > 7.0
        assert result.metadata["packing_suspect"] is True

    def test_empty_data_zero_entropy(self):
        result = EntropyTool().execute(data=b"")
        assert result.status == ToolCallStatus.SUCCESS
        assert result.metadata["entropy"] == 0.0

    def test_missing_params(self):
        result = EntropyTool().execute()
        assert result.status == ToolCallStatus.ERROR


# ----------------------------------------------------------------------
# HexDumpTool
# ----------------------------------------------------------------------
class TestHexDumpTool:
    def test_hexdump_format(self, binary_file: Path):
        result = HexDumpTool().execute(path=str(binary_file), offset=0, limit=16)
        assert result.status == ToolCallStatus.SUCCESS
        line = result.output.splitlines()[0]
        # 格式: 8位偏移 + 两位空格 + hex + |ascii|
        assert line[:8] == "00000000"
        assert "|" in line and line.rstrip().endswith("|")

    def test_offset(self, binary_file: Path):
        result = HexDumpTool().execute(path=str(binary_file), offset=16, limit=16)
        assert result.status == ToolCallStatus.SUCCESS
        assert result.output.splitlines()[0][:8] == "00000010"

    def test_offset_beyond_file(self, binary_file: Path):
        result = HexDumpTool().execute(path=str(binary_file), offset=10**9)
        assert result.status == ToolCallStatus.ERROR
        assert "超出文件大小" in result.error

    def test_invalid_params(self, binary_file: Path):
        result = HexDumpTool().execute(path=str(binary_file), offset=-1)
        assert result.status == ToolCallStatus.ERROR


# ----------------------------------------------------------------------
# GhidraTool（mock httpx.Client）
# ----------------------------------------------------------------------
def _mock_client(response_text: str = "ok", status_code: int = 200) -> MagicMock:
    """构造 mock httpx.Client，捕获请求 url/params"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = response_text
    resp.request.url = "http://mocked"
    resp.raise_for_status = MagicMock()

    client = MagicMock()
    client.get.return_value = resp
    client.post.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestGhidraTool:
    def test_decompile_by_name(self):
        client = _mock_client("int main() { return 0; }")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            result = GhidraTool().execute("decompile", name="main")
        assert result.status == ToolCallStatus.SUCCESS
        assert result.output == "int main() { return 0; }"
        args, kwargs = client.get.call_args
        assert args[0] == "http://localhost:8080/decompile"
        assert kwargs["params"]["name"] == "main"

    def test_decompile_by_address(self):
        client = _mock_client()
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            result = GhidraTool().execute("decompile", address="00401000")
        assert result.status == ToolCallStatus.SUCCESS
        args, kwargs = client.get.call_args
        assert args[0] == "http://localhost:8080/decompile_function"
        assert kwargs["params"]["address"] == "00401000"

    def test_decompile_missing_args(self):
        result = GhidraTool().execute("decompile")
        assert result.status == ToolCallStatus.ERROR
        assert "name 或 address" in result.error

    def test_list_functions(self):
        client = _mock_client("[]")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            result = GhidraTool().execute("list_functions", offset=10, limit=5, filter="main")
        assert result.status == ToolCallStatus.SUCCESS
        args, kwargs = client.get.call_args
        assert args[0] == "http://localhost:8080/functions"
        assert kwargs["params"] == {"offset": 10, "limit": 5, "filter": "main"}

    def test_list_imports_and_exports(self):
        tool = GhidraTool()
        client = _mock_client("imports")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            r1 = tool.execute("list_imports")
        assert r1.status == ToolCallStatus.SUCCESS
        assert client.get.call_args[0][0] == "http://localhost:8080/imports"

        client2 = _mock_client("exports")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client2):
            r2 = tool.execute("list_exports")
        assert r2.status == ToolCallStatus.SUCCESS
        assert client2.get.call_args[0][0] == "http://localhost:8080/exports"

    def test_rename_symbol_function(self):
        client = _mock_client("renamed")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            result = GhidraTool().execute("rename_symbol", old_name="FUN_1", new_name="main")
        assert result.status == ToolCallStatus.SUCCESS
        args, kwargs = client.post.call_args
        assert args[0] == "http://localhost:8080/rename_function"
        assert kwargs["data"] == {"old_name": "FUN_1", "new_name": "main"}

    def test_rename_symbol_data_by_address(self):
        client = _mock_client()
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            result = GhidraTool().execute("rename_symbol", address="00401000", new_name="g_buf")
        assert result.status == ToolCallStatus.SUCCESS
        assert client.post.call_args[0][0] == "http://localhost:8080/rename_data"

    def test_rename_symbol_missing_new_name(self):
        result = GhidraTool().execute("rename_symbol", old_name="FUN_1")
        assert result.status == ToolCallStatus.ERROR

    def test_get_xrefs_to_and_from(self):
        tool = GhidraTool()
        client = _mock_client("xrefs")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client):
            r1 = tool.execute("get_xrefs", address="00401000")
        assert r1.status == ToolCallStatus.SUCCESS
        assert client.get.call_args[0][0] == "http://localhost:8080/xrefs_to"

        client2 = _mock_client("xrefs")
        with patch("src.reverse_tools.ghidra_bridge.httpx.Client", return_value=client2):
            r2 = tool.execute("get_xrefs", address="00401000", direction="from")
        assert r2.status == ToolCallStatus.SUCCESS
        assert client2.get.call_args[0][0] == "http://localhost:8080/xrefs_from"

    def test_connection_error_returns_error_result(self):
        with patch(
            "src.reverse_tools.ghidra_bridge.httpx.Client"
        ) as client_cls:
            client_cls.return_value.__enter__.side_effect = httpx.ConnectError("refused")
            result = GhidraTool().execute("list_functions")
        assert result.status == ToolCallStatus.ERROR
        assert "无法连接 GhidraMCP 后端" in result.error

    def test_unknown_action(self):
        result = GhidraTool().execute("no_such_action")
        assert result.status == ToolCallStatus.ERROR
        assert "未知 action" in result.error


# ----------------------------------------------------------------------
# binary_cli 工具
# ----------------------------------------------------------------------
class TestBinaryCliTools:
    def test_cli_not_installed(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value=None):
            for tool in (ObjdumpTool(), FileTool(), BinwalkTool(), ReadelfTool()):
                result = tool.execute(path="x.bin")
                assert result.status == ToolCallStatus.ERROR
                assert result.error.startswith("工具未安装:")

    def test_objdump_success(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value="/usr/bin/objdump"), \
             patch("src.reverse_tools.binary_cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="disasm...", stderr="")
            result = ObjdumpTool().execute(path="a.out")
        assert result.status == ToolCallStatus.SUCCESS
        assert result.output == "disasm..."
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/objdump" and args[1] == "-d" and args[2] == "a.out"

    def test_readelf_success(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value="/usr/bin/readelf"), \
             patch("src.reverse_tools.binary_cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="ELF header...", stderr="")
            result = ReadelfTool().execute(path="a.out")
        assert result.status == ToolCallStatus.SUCCESS
        args = run.call_args[0][0]
        assert args[1] == "-a"

    def test_file_and_binwalk_success(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value="/usr/bin/x"), \
             patch("src.reverse_tools.binary_cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            assert FileTool().execute(path="f").status == ToolCallStatus.SUCCESS
            assert BinwalkTool().execute(path="f").status == ToolCallStatus.SUCCESS

    def test_nonzero_exit_code(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value="/usr/bin/objdump"), \
             patch("src.reverse_tools.binary_cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stdout="", stderr="bad file")
            result = ObjdumpTool().execute(path="a.out")
        assert result.status == ToolCallStatus.ERROR
        assert "退出码 1" in result.error
        assert "bad file" in result.error

    def test_timeout(self):
        with patch("src.reverse_tools.binary_cli.shutil.which", return_value="/usr/bin/objdump"), \
             patch("src.reverse_tools.binary_cli.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="objdump", timeout=120)):
            result = _run_cli("objdump", "objdump", ["-d", "a.out"])
        assert result.status == ToolCallStatus.TIMEOUT
        assert "超时" in result.error


# ----------------------------------------------------------------------
# register_all
# ----------------------------------------------------------------------
class TestRegisterAll:
    def test_register_and_search(self):
        registry = ToolRegistry()
        register_all(registry)
        names = {d.name for d in registry.list_tools()}
        assert {"ghidra", "strings", "entropy", "hexdump",
                "objdump", "file", "binwalk", "readelf"} <= names
        assert any(d.name == "ghidra" for d in registry.search("ghidra"))
        assert len(registry.search("readelf")) == 1

    def test_registered_tool_executable(self, binary_file: Path):
        registry = ToolRegistry()
        register_all(registry)
        tool = registry.get("entropy")
        result = tool.execute(path=str(binary_file))
        assert result.status == ToolCallStatus.SUCCESS
