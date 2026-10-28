"""领域原生工具 —— 直接内置在 agent 里，不走 MCP

设计取舍（重要）:
- **我们自己的 agent** → 用这里的原生工具：零进程、零序列化、可直接共享进程内缓存。
- **外部引擎**（Codex/OpenCode 跑在别的进程）→ 才需要 MCP（`src/mcp/domain_server.py`）。
  MCP 是跨进程桥，不是内部调用的常规路径。

世界模型索引由 `src/brain/warmup.py` 在引擎启动时**后台自动预热**，
因此这些工具调用通常是毫秒级；未就绪时如实返回进度而不是阻塞。
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from ..brain import warmup as wm_warmup
from .base import BaseTool, ParameterSchema, ToolCategory, ToolResult


class WorldModelTool(BaseTool):
    """世界模型查询：代码库认知（依赖上下游 / 相关文件预测 / 索引状态）

    索引在引擎启动时后台预热；本工具不会因为索引未就绪而挂起——
    未就绪时返回 indexing 状态与已等待秒数，让调用方自行决定是否稍后重试。
    """

    name = 'WorldModelTool'
    description = '查询代码库世界模型：文件上下游依赖/语义关联/设计模式，或预测相关文件'
    category = ToolCategory.KNOWLEDGE_GRAPH
    risk_kind = 'read'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='操作: stats(索引状态/规模) | context(某文件架构上下文) | predict(预测相关文件)',
            allowed_values=('stats', 'context', 'predict'),
        ),
        ParameterSchema(
            name='file_path',
            param_type='str',
            required=False,
            description='当 action=context 时的目标文件（相对工作目录）',
            max_length=500,
        ),
        ParameterSchema(
            name='current_file',
            param_type='str',
            required=False,
            description='当 action=predict 时的当前文件',
            max_length=500,
        ),
        ParameterSchema(
            name='depth',
            param_type='int',
            required=False,
            description='当 action=predict 时的依赖深度，默认 1',
            default=1,
            min_value=1,
            max_value=5,
        ),
        ParameterSchema(
            name='wait_seconds',
            param_type='float',
            required=False,
            description='索引未就绪时最多等待秒数（0 = 不等待，直接返回状态）',
            default=0.0,
            min_value=0.0,
            max_value=600.0,
        ),
    )

    def __init__(self, workdir: Path | str | None = None):
        super().__init__()
        self.workdir = Path(workdir or Path.cwd()).resolve()

    # ---------- 内部 ----------
    def _await_ready(self, wait_seconds: float) -> Any | None:
        """取模型：先看缓存，未就绪则（可选）等待；不触发全量索引以外的阻塞"""
        model = wm_warmup.get_model(self.workdir)
        if model is not None:
            return model
        if wait_seconds > 0:
            import time

            deadline = time.time() + wait_seconds
            wm_warmup.ensure_warm(self.workdir)
            while time.time() < deadline:
                model = wm_warmup.get_model(self.workdir)
                if model is not None:
                    return model
                time.sleep(0.1)
        return wm_warmup.get_model(self.workdir)

    def _not_ready(self, hint: str) -> ToolResult:
        status = wm_warmup.warm_status(self.workdir)
        # 大仓库被跳过时，把真实原因回给调用方（不要只说"未就绪"）
        if status["state"] == "skipped_large":
            reason = wm_warmup._state_for(self.workdir).error
            status["hint"] = reason or hint
            return ToolResult(
                success=False,
                output=json.dumps(status, ensure_ascii=False),
                error=f"世界模型已跳过索引（大仓库保护）：{reason or hint}",
                exit_code=1,
                metadata=status,
            )
        status["hint"] = hint
        return ToolResult(
            success=False,
            output=json.dumps(status, ensure_ascii=False),
            error=f"世界模型索引未就绪（state={status['state']}）",
            exit_code=1,
            metadata=status,
        )

    # ---------- 执行 ----------
    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get('action') or '').strip()
        wait_seconds = float(kwargs.get('wait_seconds') or 0.0)
        self._increment_usage()

        if action == 'stats':
            model = self._await_ready(wait_seconds)
            status = wm_warmup.warm_status(self.workdir)
            if model is None:
                return self._not_ready("索引仍在后台预热，稍后重试或用 clawd_project_map 轻量替代")
            try:
                payload = {**model.stats(), "warmup": status}
            except Exception as e:  # noqa: BLE001
                return ToolResult(success=False, output="", error=f"读取统计失败: {e}", exit_code=1)
            return ToolResult(success=True, output=json.dumps(payload, ensure_ascii=False, indent=2))

        if action == 'context':
            rel = str(kwargs.get('file_path') or '').strip()
            if not rel:
                return ToolResult(success=False, output="", error="action=context 需要 file_path", exit_code=1)
            target = (self.workdir / rel).resolve()
            if not target.is_relative_to(self.workdir):
                return ToolResult(success=False, output="", error=f"路径越界: {rel}", exit_code=1)
            if not target.is_file():
                return ToolResult(success=False, output="", error=f"文件不存在: {rel}", exit_code=1)
            model = self._await_ready(wait_seconds)
            if model is None:
                return self._not_ready("索引仍在后台预热，稍后重试")
            try:
                ctx = model.get_context_for_file(str(target))
            except Exception as e:  # noqa: BLE001
                return ToolResult(success=False, output="", error=f"查询失败: {e}", exit_code=1)
            return ToolResult(success=True, output=json.dumps(ctx, ensure_ascii=False, default=str, indent=2))

        if action == 'predict':
            current = str(kwargs.get('current_file') or '').strip()
            if not current:
                return ToolResult(success=False, output="", error="action=predict 需要 current_file", exit_code=1)
            depth = int(kwargs.get('depth') or 1)
            model = self._await_ready(wait_seconds)
            if model is None:
                return self._not_ready("索引仍在后台预热，稍后重试")
            try:
                files = model.predict_relevant_files(current, depth=depth)
            except Exception as e:  # noqa: BLE001
                return ToolResult(success=False, output="", error=f"预测失败: {e}", exit_code=1)
            return ToolResult(
                success=True,
                output=json.dumps({"current_file": current, "depth": depth, "predicted": files},
                                  ensure_ascii=False, indent=2),
            )

        return ToolResult(
            success=False, output="",
            error=f"未知 action: {action}（支持 stats/context/predict）", exit_code=1,
        )


class ProjectMapTool(BaseTool):
    """项目符号地图（Aider 风格 repo map）——纯本地、秒级，不依赖世界模型索引"""

    name = 'ProjectMapTool'
    description = '生成项目符号地图（类/函数及其位置），快速建立代码库认知'
    category = ToolCategory.SEARCH
    risk_kind = 'read'

    DEFAULT_MAX_FILES = 300

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='max_files',
            param_type='int',
            required=False,
            description='最多纳入的文件数（默认 300）',
            default=300,
            min_value=1,
            max_value=2000,
        ),
        ParameterSchema(
            name='subpath',
            param_type='str',
            required=False,
            description='只扫描该子目录（相对工作目录，可空）',
            max_length=300,
        ),
    )

    def __init__(self, workdir: Path | str | None = None):
        super().__init__()
        self.workdir = Path(workdir or Path.cwd()).resolve()

    def _collect(self, max_files: int, subpath: str) -> list[str]:
        base = (self.workdir / subpath).resolve() if subpath else self.workdir
        if not base.is_relative_to(self.workdir) or not base.exists():
            return []
        exts = {'.py', '.js', '.ts', '.tsx', '.go', '.rs', '.java'}
        skip = {'.git', 'node_modules', 'venv', '__pycache__', 'dist', 'build', '.venv'}
        out: list[str] = []
        for p in sorted(base.rglob('*')):
            if len(out) >= max_files:
                break
            if not p.is_file() or p.suffix not in exts:
                continue
            if any(part in skip for part in p.parts):
                continue
            out.append(str(p))
        return out

    def execute(self, **kwargs) -> ToolResult:
        max_files = int(kwargs.get('max_files') or self.DEFAULT_MAX_FILES)
        subpath = str(kwargs.get('subpath') or '').strip()
        self._increment_usage()

        files = self._collect(max_files, subpath)
        if not files:
            return ToolResult(success=False, output="", error="未找到可扫描的源文件", exit_code=1)
        try:
            from ..rag.repo_map import RepoMap

            with RepoMap(root_dir=self.workdir) as mapper:
                text = mapper.get_repo_map(chat_files=[], other_files=files) or ""
        except Exception as e:  # noqa: BLE001 — 图谱失败降级为文件清单，不静默
            listing = "\n".join(str(Path(f).relative_to(self.workdir)) for f in files[:max_files])
            return ToolResult(
                success=True,
                output=f"(符号解析不可用: {type(e).__name__}; 降级为文件清单)\n{listing}",
                metadata={"degraded": True, "file_count": len(files)},
            )
        if not text.strip():
            listing = "\n".join(str(Path(f).relative_to(self.workdir)) for f in files[:max_files])
            return ToolResult(success=True, output=listing,
                              metadata={"degraded": True, "file_count": len(files)})
        return ToolResult(success=True, output=text,
                          metadata={"file_count": len(files), "degraded": False})


def get_domain_tools(workdir: Path | str | None = None) -> list[BaseTool]:
    """返回领域原生工具实例（供引擎装配）"""
    wd = Path(workdir or Path.cwd()).resolve()
    return [WorldModelTool(wd), ProjectMapTool(wd)]
