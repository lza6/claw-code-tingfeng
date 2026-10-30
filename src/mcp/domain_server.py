"""Clawd 领域能力 MCP Server（stdio）

用途：把我们自己的领域能力反向供给**任意**外部 agent 引擎（Codex / OpenCode / OpenClaw …），
这样"用别人的内核跑我们自己的领域工具"才真正成立——这是多引擎整合的粘合层。

协议：MCP 2024-11-05，stdio 上按行分隔的 JSON-RPC 2.0。
支持方法：initialize / notifications/initialized / ping / tools/list / tools/call

暴露的工具（只读、有边界，绝不暴露写操作或 shell）：
- clawd_read_file     读取仓库内文件（路径穿越防护 + 大小上限）
- clawd_grep          代码/文本搜索（优先 ripgrep，回退纯 Python）
- clawd_project_map   代码库符号地图（复用 src/rag/repo_map.py）
- clawd_tool_list     列出本项目注册的领域工具（让外部引擎知道我们有什么）

启动: python -m src.mcp.domain_server --root <项目根>
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "clawd-domain"
PROTOCOL_VERSION = "2024-11-05"

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 200
MAX_MAP_FILES = 400


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _text_content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _error_content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


class DomainServer:
    """领域能力 MCP 服务"""

    def __init__(self, root: Path | None = None):
        self.root = (root or Path.cwd()).resolve()
        self._wm = None
        self._tools = self._build_tools()

    # ---------- 工具定义 ----------
    def _build_tools(self) -> dict[str, dict[str, Any]]:
        return {
            "clawd_read_file": {
                "description": "读取项目内文件内容（只读，带路径穿越防护与大小上限）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "相对项目根的路径"},
                        "max_bytes": {"type": "integer", "description": f"最多读取字节（默认 {MAX_READ_BYTES}）"},
                    },
                    "required": ["path"],
                },
                "handler": self._tool_read_file,
            },
            "clawd_grep": {
                "description": "在项目内搜索文本/正则（优先 ripgrep），返回 文件:行号:内容",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "要搜索的文本或正则"},
                        "path": {"type": "string", "description": "搜索起点（默认项目根）"},
                        "glob": {"type": "string", "description": "文件过滤，如 *.py"},
                    },
                    "required": ["pattern"],
                },
                "handler": self._tool_grep,
            },
            "clawd_project_map": {
                "description": "生成代码库符号地图（类/函数及其文件位置），用于快速建立项目认知",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "max_files": {"type": "integer", "description": f"最多扫描文件数（默认 {MAX_MAP_FILES}）"},
                    },
                },
                "handler": self._tool_project_map,
            },
            "clawd_tool_list": {
                "description": "列出本项目注册的领域工具（名称/说明），便于外部引擎发现可用能力",
                "inputSchema": {"type": "object", "properties": {}},
                "handler": self._tool_list,
            },
            "clawd_world_model_context": {
                "description": "查询世界模型：某文件的上游/下游依赖、语义关联与设计模式（架构级上下文）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "相对项目根的文件路径"},
                    },
                    "required": ["file_path"],
                },
                "handler": self._tool_world_model_context,
            },
            "clawd_world_model_predict": {
                "description": "世界模型：根据当前文件预测接下来最相关的文件（用于上下文预取）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "current_file": {"type": "string", "description": "当前正在处理的文件"},
                        "depth": {"type": "integer", "description": "依赖深度（默认 1）"},
                    },
                    "required": ["current_file"],
                },
                "handler": self._tool_world_model_predict,
            },
            "clawd_world_model_stats": {
                "description": "世界模型健康度：节点数/边数/已索引文档数（判断索引是否就绪）",
                "inputSchema": {"type": "object", "properties": {}},
                "handler": self._tool_world_model_stats,
            },
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in self._tools.items()
        ]

    # ---------- 工具实现 ----------
    def _resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"路径越界（必须在 {self.root} 内）: {rel}")
        return target

    def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("path") or "").strip()
        if not rel:
            return _error_content("path 不能为空")
        max_bytes = int(args.get("max_bytes") or MAX_READ_BYTES)
        try:
            target = self._resolve(rel)
        except ValueError as e:
            return _error_content(str(e))
        if not target.is_file():
            return _error_content(f"文件不存在: {rel}")
        try:
            raw = target.read_bytes()[:max_bytes]
        except OSError as e:
            return _error_content(f"读取失败: {e}")
        return _text_content(raw.decode("utf-8", errors="replace"))

    def _tool_grep(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern") or "")
        if not pattern:
            return _error_content("pattern 不能为空")
        base = str(args.get("path") or ".")
        glob = args.get("glob")

        rg = shutil.which("rg")
        if rg:
            argv = [rg, "--line-number", "--no-heading", "--color", "never",
                    "--max-count", str(MAX_GREP_RESULTS), pattern]
            if glob:
                argv += ["--glob", str(glob)]
            argv.append(str(self._resolve(base)))
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                                      encoding="utf-8", errors="replace", check=False)
            except (OSError, subprocess.SubprocessError) as e:
                return _error_content(f"搜索失败: {e}")
            out = (proc.stdout or "").strip()
            if not out:
                return _text_content("(无匹配)")
            lines = out.splitlines()[:MAX_GREP_RESULTS]
            return _text_content("\n".join(lines))

        # 回退：纯 Python 扫描（无 rg 环境）
        matches: list[str] = []
        base_path = self._resolve(base)
        candidates = [base_path] if base_path.is_file() else sorted(base_path.rglob("*"))
        for path in candidates:
            if len(matches) >= MAX_GREP_RESULTS:
                break
            if not path.is_file():
                continue
            if glob and not path.match(str(glob)):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern in line:
                    matches.append(f"{path}:{lineno}:{line.strip()}")
                    if len(matches) >= MAX_GREP_RESULTS:
                        break
        return _text_content("\n".join(matches) if matches else "(无匹配)")

    def _tool_project_map(self, args: dict[str, Any]) -> dict[str, Any]:
        """符号级项目图谱（Aider 风格 RepoMap）

        回归背景：旧实现写的是 `RepoMap(root=...)`，而真实签名是
        `RepoMap(token_budget, root_dir, ...)`；即便构造成功，`get_map()` 还必须
        传 `files`。两处都会 TypeError —— 于是本工具**永远走降级分支**，
        只吐一份 Python 文件清单，却带着"符号图谱不可用"的字样当结果返回。
        """
        max_files = int(args.get("max_files") or MAX_MAP_FILES)

        files = sorted(
            str(p)
            for p in self.root.rglob("*.py")
            if ".git" not in p.parts and len(p.parts) < 12 and p.is_file()
        )[:max_files]
        if not files:
            return _text_content("(项目里没有 Python 文件)")

        try:
            from ..rag.repo_map import RepoMap

            mapper = RepoMap(token_budget=4096, root_dir=self.root)
            text = mapper.get_map(files)
        except Exception as e:  # noqa: BLE001 — 图谱失败要如实说明，不能假装有结果
            rel = [str(Path(f).relative_to(self.root)) for f in files]
            return _text_content(
                f"(符号图谱不可用: {type(e).__name__}: {e}; 降级为 Python 文件清单)\n"
                + "\n".join(rel)
            )

        if not text or not str(text).strip():
            return _text_content("(项目图谱为空)")
        lines = str(text).splitlines()[: max_files * 20]
        return _text_content("\n".join(lines))

    def _tool_list(self, args: dict[str, Any]) -> dict[str, Any]:

        import importlib
        import inspect

        from ..tools_runtime.base import BaseTool

        found: list[str] = []
        pkg_root = Path(__file__).resolve().parents[1] / "tools_runtime"
        for py in sorted(pkg_root.rglob("*.py")):
            if ".git" in py.parts or py.name.startswith("_"):
                continue
            rel = py.relative_to(pkg_root).with_suffix("")
            module = "src.tools_runtime." + ".".join(rel.parts)
            try:
                mod = importlib.import_module(module)
            except Exception:
                continue
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, BaseTool) and obj is not BaseTool and obj.__module__ == module:
                    desc = (inspect.getdoc(obj) or "").splitlines()[0] if inspect.getdoc(obj) else ""
                    found.append(f"- {name}: {desc}")
        return _text_content("\n".join(found) if found else "(未发现工具类)")

    # ---------- 世界模型 ----------
    def _world_model(self, *, initialize: bool = True, timeout: float | None = None):
        """惰性构造 RepositoryWorldModel

        initialize=True 时会索引仓库——大仓库可能要几分钟，因此**必须有超时上限**：
        超时就诚实报错并提示预热，绝不让 MCP 调用无限挂起（真实仓库实测 300s 未完成）。
        """
        if getattr(self, "_wm", None) is not None:
            return self._wm
        from ..brain.world_model import RepositoryWorldModel

        model = RepositoryWorldModel(self.root)
        if not initialize:
            self._wm = model
            return model

        if timeout is None:
            try:
                timeout = float(os.environ.get("CLAWD_WM_TIMEOUT", "180"))
            except ValueError:
                timeout = 180.0

        import concurrent.futures

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(asyncio.run, model.initialize())
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            pool.shutdown(wait=False, cancel_futures=True)
            raise TimeoutError(
                f"世界模型索引超时（>{timeout:.0f}s）——本仓库较大，全量索引不适合在单次 MCP 调用里做。"
                f"替代方案：用 clawd_project_map / clawd_grep 获取轻量代码认知；"
                f"确需世界模型可调大上限：环境变量 CLAWD_WM_TIMEOUT=<秒>"
            ) from e
        except Exception:
            pool.shutdown(wait=False)
            raise
        pool.shutdown(wait=False)
        self._wm = model
        return model

    def _tool_world_model_context(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("file_path") or "").strip()
        if not rel:
            return _error_content("file_path 不能为空")
        try:
            target = self._resolve(rel)
        except ValueError as e:
            return _error_content(str(e))
        if not target.is_file():
            return _error_content(f"文件不存在: {rel}")
        try:
            model = self._world_model()
            ctx = model.get_context_for_file(str(target))
        except Exception as e:
            return _error_content(f"世界模型不可用: {type(e).__name__}: {e}")
        return _text_content(json.dumps(ctx, ensure_ascii=False, default=str, indent=2))

    def _tool_world_model_predict(self, args: dict[str, Any]) -> dict[str, Any]:
        current = str(args.get("current_file") or "").strip()
        if not current:
            return _error_content("current_file 不能为空")
        depth = int(args.get("depth") or 1)
        try:
            model = self._world_model()
            files = model.predict_relevant_files(current, depth=depth)
        except Exception as e:
            return _error_content(f"世界模型不可用: {type(e).__name__}: {e}")
        return _text_content(json.dumps({"current_file": current, "depth": depth,
                                         "predicted": files}, ensure_ascii=False, indent=2))

    def _tool_world_model_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        """健康度：走快速路径（不触发全量索引），索引未就绪时如实说明"""
        try:
            model = self._world_model(initialize=False)
            stats = model.stats()
            return _text_content(json.dumps(
                {**stats, "indexed": bool(getattr(model, "_is_initialized", False))},
                ensure_ascii=False, default=str, indent=2,
            ))
        except Exception as e:
            return _error_content(f"世界模型不可用: {type(e).__name__}: {e}")

    # ---------- JSON-RPC 分发 ----------
    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        req_id = request.get("id")

        # 通知（无 id）不需要响应
        if req_id is None and method in ("notifications/initialized", "initialized"):
            return None

        if method == "initialize":
            return _result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            })

        if method == "ping":
            return _result(req_id, {})

        if method == "tools/list":
            _probe = os.environ.get("CLAWD_MCP_EMPTY_TOOLS") == "1"
            return _result(req_id, {"tools": [] if _probe else self.list_tools()})

        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            spec = self._tools.get(str(name))
            if spec is None:
                return _error(req_id, -32602, f"未知工具: {name}")
            if not isinstance(args, dict):
                return _error(req_id, -32602, "arguments 必须是对象")
            try:
                return _result(req_id, spec["handler"](args))
            except Exception as e:
                return _result(req_id, _error_content(f"{type(e).__name__}: {e}"))

        return _error(req_id, -32601, f"不支持的方法: {method}")

    # ---------- stdio 主循环 ----------
    def serve(self, stdin=None, stdout=None) -> int:
        """stdio 主循环

        Windows 关键点：必须显式把协议流包成 UTF-8。
        否则中文会被 GBK 编码写出，MCP 客户端按 UTF-8 解码失败 →
        读任务直接死掉、请求全部超时（真实 E2E 抓到的 bug）。
        """
        if stdin is None:
            stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline=chr(10))
        if stdout is None:
            stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", newline=chr(10), write_through=True
            )

        while True:
            line = stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                stdout.write(json.dumps(_error(None, -32700, "JSON 解析失败")) + chr(10))
                stdout.flush()
                continue
            if not isinstance(request, dict):
                continue
            # 通知（无 id）不产生响应；否则会被客户端当作协议违规
            if request.get("id") is None:
                continue
            try:
                response = self.handle(request)
            except Exception as exc:
                response = _error(request.get("id"), -32603, f"{type(exc).__name__}: {exc}")
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + chr(10))
                stdout.flush()
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Clawd 领域能力 MCP Server（stdio）")
    ap.add_argument("--root", default=os.getcwd(), help="项目根目录")
    args = ap.parse_args(argv)
    return DomainServer(Path(args.root)).serve()


if __name__ == "__main__":
    sys.exit(main())
