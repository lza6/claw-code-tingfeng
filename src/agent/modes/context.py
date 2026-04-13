"""Context Mode — 文件定位模式（移植自 Aider context_coder.py）

自动识别用户请求涉及的文件，减少上下文浪费。

工作流程:
1. 用户描述需求
2. LLM 分析需要读取哪些文件来理解上下文
3. 将相关文件加入会话上下文
4. 可选: 自动切换到编辑模式

使用场景:
- 用户不确定需要修改哪些文件
- 大型项目中快速定位相关代码
- 减少 token 浪费
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FileContext:
    """文件上下文信息"""
    path: str
    reason: str              # 为什么需要这个文件
    relevance: str = "high"  # high/medium/low


@dataclass
class ContextResult:
    """文件定位结果"""
    files: list[FileContext] = field(default_factory=list)
    suggested_action: str = ""


CONTEXT_SYSTEM_PROMPT = """你是一个代码上下文分析助手。根据用户的请求，识别需要查看或修改的文件。

只输出文件路径列表，每行一个，格式: `path/to/file.py` (原因)

如果请求涉及多个文件，列出所有相关文件。
如果请求不需要修改任何文件（纯问答），输出: (no files needed)
"""


class ContextMode:
    """文件定位模式 — 自动识别相关文件

    用法:
        mode = ContextMode(engine)
        result = await mode.locate_files("添加用户登录功能")
        for f in result.files:
            print(f"  {f.path}: {f.reason}")
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def locate_files(
        self,
        request: str,
        *,
        max_files: int = 10,
    ) -> ContextResult:
        """分析请求并定位相关文件

        参数:
            request: 用户请求
            max_files: 最大返回文件数

        返回:
            ContextResult 包含文件列表
        """
        messages = [
            {"role": "system", "content": CONTEXT_SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]

        try:
            response = await self.engine.llm_provider.chat(
                messages,
                max_tokens=1024,
            )
            files = self._parse_file_mentions(response.content, max_files)
            return ContextResult(files=files)
        except Exception as e:
            logger.error(f'文件定位失败: {e}')
            return ContextResult()

    def _parse_file_mentions(self, text: str, max_files: int) -> list[FileContext]:
        """从 LLM 响应中提取文件提及"""
        import re

        files: list[FileContext] = []
        # 匹配 `path/to/file` (reason) 格式
        pattern = r'`([^`]+)`\s*\(([^)]+)\)'
        matches = re.findall(pattern, text)

        for path, reason in matches[:max_files]:
            files.append(FileContext(path=path, reason=reason))

        # 如果没有匹配到格式化的输出，尝试提取所有反引号路径
        if not files:
            paths = re.findall(r'`([^`]+\.[a-zA-Z]+)`', text)
            for path in paths[:max_files]:
                files.append(FileContext(path=path, reason="mentioned in context"))

        return files

    async def locate_and_load(
        self,
        request: str,
        *,
        max_files: int = 10,
    ) -> ContextResult:
        """定位文件并加载其内容到引擎上下文"""
        result = await self.locate_files(request, max_files=max_files)

        loaded_files: list[FileContext] = []
        for fc in result.files:
            try:
                content = await self._read_file(fc.path)
                if content:
                    loaded_files.append(fc)
                    logger.info(f'已加载上下文文件: {fc.path}')
            except Exception as e:
                logger.warning(f'无法加载文件 {fc.path}: {e}')

        result.files = loaded_files
        return result

    async def _read_file(self, path: str) -> str | None:
        """读取文件内容"""
        from pathlib import Path

        file_path = Path(path)
        if not file_path.exists():
            return None

        try:
            return file_path.read_text(encoding='utf-8', errors='replace')[:50000]
        except Exception:
            return None
