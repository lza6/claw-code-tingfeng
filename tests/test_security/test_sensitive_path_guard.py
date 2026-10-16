"""敏感文件防护回归测试。

## 背景（真实发生的泄露）

`src/utils/path_security.py` 早已实现 `is_sensitive_file` 与 `FORBIDDEN_DIRS`，
但**从未被任何工具接线**。结果是 Agent 可以直接读 `.env`：

    await execute_tool(tools, 'FileReadTool', {'file_path': '.env'})
    → success=True
      output 含 "OPENAI_API_KEY=sk-ee3323e20cb4ede..."

该内容随后被 `engine_loop` 原样拼进消息上下文，发给远端 LLM。

另有第二处：`path_utils.TEXT_EXTENSIONS` 把 `.env` 列为"可读文本扩展名"。

## 修复

在 `path_utils.resolve_path()` —— FileReadTool / FileEditTool / GlobTool /
GrepTool 的**唯一统一入口** —— 接入敏感路径判定。一处改，全部生效。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agent.tool_executor import execute_tool
from src.tools_runtime.file_read_tool import FileReadTool
from src.tools_runtime.path_utils import is_sensitive_path, resolve_path

# ---------------------------------------------------------------------------
# 单元层：is_sensitive_path
# ---------------------------------------------------------------------------


class TestIsSensitivePath:
    @pytest.mark.parametrize("name", [
        ".env",
        ".env.local",
        ".env.production",
        ".env.test",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "private.key",
        "credentials.json",
        "secrets.yaml",
        "secrets.json",
    ])
    def test_credential_files_are_sensitive(self, name: str, tmp_path: Path):
        assert is_sensitive_path(tmp_path / name) is True, f"{name} 应被判定为敏感"

    @pytest.mark.parametrize("name", [
        ".env.example",
        ".env.sample",
        ".env.template",
    ])
    def test_template_files_are_exempt(self, name: str, tmp_path: Path):
        """模板文件不含真实凭据，且是引导配置的必需材料，应放行"""
        assert is_sensitive_path(tmp_path / name) is False

    @pytest.mark.parametrize("rel", [
        ".git/config",
        ".clawd/provider.json",
        ".clawd/config.toml",
        "node_modules/pkg/index.js",
        "__pycache__/mod.pyc",
    ])
    def test_forbidden_dirs_are_sensitive(self, rel: str, tmp_path: Path):
        assert is_sensitive_path(tmp_path / rel) is True

    @pytest.mark.parametrize("rel", [
        "src/main.py",
        "README.md",
        "tests/core/test_x.py",
        "docs/architecture.md",
    ])
    def test_normal_source_is_not_sensitive(self, rel: str, tmp_path: Path):
        assert is_sensitive_path(tmp_path / rel) is False


class TestResolvePath:
    def test_rejects_sensitive_file(self, tmp_path: Path):
        (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
        assert resolve_path(".env", tmp_path) is None

    def test_rejects_clawd_dir(self, tmp_path: Path):
        (tmp_path / ".clawd").mkdir()
        (tmp_path / ".clawd" / "provider.json").write_text("{}", encoding="utf-8")
        assert resolve_path(".clawd/provider.json", tmp_path) is None

    def test_still_allows_normal_file(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        assert resolve_path("a.py", tmp_path) is not None

    def test_still_rejects_traversal(self, tmp_path: Path):
        """回归：敏感判定不得削弱原有的路径穿越防护"""
        assert resolve_path("../../etc/passwd", tmp_path) is None


# ---------------------------------------------------------------------------
# 集成层：经工具真实调用
# ---------------------------------------------------------------------------


class TestViaToolExecutor:
    @pytest.fixture
    def tools(self) -> dict:
        cwd = Path.cwd()
        return {"FileReadTool": FileReadTool(base_path=cwd)}

    @pytest.mark.asyncio
    async def test_env_read_is_refused(self, tools):
        """回归核心：Agent 不得读到 .env"""
        with pytest.raises(Exception):  # noqa: B017 - ToolInvalidArgsError
            await execute_tool(tools, "FileReadTool", {"file_path": ".env"})

    @pytest.mark.asyncio
    async def test_env_content_never_reaches_output(self, tools):
        """即使以其它方式绕过，输出里也不得出现密钥模式"""
        try:
            result = await execute_tool(tools, "FileReadTool", {"file_path": ".env"})
        except Exception:
            return
        assert "sk-" not in (result.output or ""), "API Key 出现在工具输出中"
        assert "API_KEY" not in (result.output or "")

    @pytest.mark.asyncio
    async def test_clawd_dir_is_refused(self, tools):
        """`.clawd/` 内有明文 provider.json（apiKey）"""
        with pytest.raises(Exception):  # noqa: B017
            await execute_tool(tools, "FileReadTool", {"file_path": ".clawd/config.toml"})

    @pytest.mark.asyncio
    async def test_template_env_is_readable(self, tools):
        """.env.example 是引导配置的必需材料，必须可读"""
        result = await execute_tool(tools, "FileReadTool", {"file_path": ".env.example"})
        assert result.success is True, result.error
        assert result.output.strip(), "模板内容为空"

    @pytest.mark.asyncio
    async def test_normal_source_still_readable(self, tools):
        """防护不得误伤正常工作流"""
        result = await execute_tool(tools, "FileReadTool", {"file_path": "src/main.py"})
        assert result.success is True, result.error
        assert "def " in result.output


class TestNoEnvInReadableExtensions:
    """`.env` 曾被列在 TEXT_EXTENSIONS 白名单里，等于明文声明"可读文本"。"""

    def test_env_not_in_text_extensions(self):
        from src.tools_runtime.path_utils import TEXT_EXTENSIONS
        assert ".env" not in TEXT_EXTENSIONS, (
            "TEXT_EXTENSIONS 不应把 .env 声明为可读文本扩展名"
        )
