"""笔记本工具（内置原生）—— 长会话的持久化记忆载体

动作：save / read / list / set_topic / prepare_discard / commit_discard / abort_discard
删除采用**两级式**（prepare → commit），压缩失败也不会丢页面。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..memory.notebook import Notebook
from .base import BaseTool, ParameterSchema, ToolCategory, ToolResult


class NotebookTool(BaseTool):
    """会话笔记本：把决定/结论落成页面，跨轮次持久"""

    name = 'NotebookTool'
    description = (
        '长会话记忆：把关键结论/约定写入笔记本页面（topic+content），后续轮次可读取；'
        '删除需两步（prepare 再 commit），避免误删'
    )
    category = ToolCategory.MEMORY
    #: 可写可删 → 按写类工具走审批
    risk_kind = 'write'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='save|read|list|set_topic|prepare_discard|commit_discard|abort_discard',
            allowed_values=('save', 'read', 'list', 'set_topic',
                            'prepare_discard', 'commit_discard', 'abort_discard'),
        ),
        ParameterSchema(name='topic', param_type='str', required=False,
                        description='页面主题（save/read/set_topic 用）', max_length=80),
        ParameterSchema(name='content', param_type='str', required=False,
                        description='页面内容（save 用）', max_length=200000),
        ParameterSchema(name='topics', param_type='list', required=False,
                        description='要删除的主题列表（prepare_discard 用）'),
        ParameterSchema(name='token', param_type='str', required=False,
                        description='删除计划令牌（commit_discard/abort_discard 用）', max_length=120),
    )

    def __init__(self, workdir: Path | str | None = None):
        super().__init__()
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.notebook = Notebook(self.workdir)

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get('action') or '').strip()
        self._increment_usage()

        allowed = ('save', 'read', 'list', 'set_topic',
                   'prepare_discard', 'commit_discard', 'abort_discard')
        if action not in allowed:
            return ToolResult(success=False, output="",
                              error=f"未知 action: {action or '(空)'}（支持 {'/'.join(allowed)}）",
                              exit_code=1)

        try:
            if action == 'save':
                topic = str(kwargs.get('topic') or '').strip()
                content = kwargs.get('content')
                if not topic:
                    return ToolResult(success=False, output="", error="save 需要 topic", exit_code=1)
                if content is None or str(content) == '':
                    return ToolResult(success=False, output="", error="save 需要 content", exit_code=1)
                slug = self.notebook.save_page(topic, str(content))
                return ToolResult(success=True,
                                  output=json.dumps({"saved": slug, "chars": len(str(content))},
                                                    ensure_ascii=False),
                                  metadata={"topic": slug})

            if action == 'read':
                topic = str(kwargs.get('topic') or '').strip()
                if not topic:
                    return ToolResult(success=False, output="", error="read 需要 topic", exit_code=1)
                content = self.notebook.read_page(topic)
                if content is None:
                    return ToolResult(success=False, output="",
                                      error=f"页面不存在: {topic}", exit_code=1)
                return ToolResult(success=True, output=content)

            if action == 'list':
                pages = self.notebook.list_pages()
                return ToolResult(
                    success=True,
                    output=json.dumps({"count": len(pages), "pages": pages,
                                       "active_topic": self.notebook.active_topic()},
                                      ensure_ascii=False, indent=2),
                    metadata={"count": len(pages)},
                )

            if action == 'set_topic':
                topic = str(kwargs.get('topic') or '').strip()
                if not topic:
                    return ToolResult(success=False, output="", error="set_topic 需要 topic", exit_code=1)
                result = self.notebook.set_active_topic(topic)
                return ToolResult(success=True,
                                  output=json.dumps(result, ensure_ascii=False, indent=2))

            if action == 'prepare_discard':
                topics = kwargs.get('topics') or []
                if not isinstance(topics, (list, tuple)) or not topics:
                    return ToolResult(success=False, output="",
                                      error="prepare_discard 需要非空 topics 列表", exit_code=1)
                plan = self.notebook.prepare_discard([str(t) for t in topics])
                return ToolResult(
                    success=True,
                    output=json.dumps({"token": plan.token, "will_delete": plan.topics,
                                       "note": "尚未删除；压缩成功后调用 commit_discard 才真删"},
                                      ensure_ascii=False, indent=2),
                    metadata={"token": plan.token, "count": len(plan.topics)},
                )

            if action == 'commit_discard':
                token = str(kwargs.get('token') or '').strip()
                if not token:
                    return ToolResult(success=False, output="",
                                      error="commit_discard 需要 token", exit_code=1)
                removed = self.notebook.commit_discard(token)
                return ToolResult(success=True,
                                  output=json.dumps({"deleted": removed}, ensure_ascii=False),
                                  metadata={"deleted": len(removed)})

            # abort_discard
            token = str(kwargs.get('token') or '').strip()
            if not token:
                return ToolResult(success=False, output="", error="abort_discard 需要 token", exit_code=1)
            self.notebook.abort_discard(token)
            return ToolResult(success=True, output=json.dumps({"aborted": token}, ensure_ascii=False))

        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1)
        except KeyError as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1)
        except OSError as e:
            return ToolResult(success=False, output="", error=f"笔记本读写失败: {e}", exit_code=1)


def get_notebook_tool(workdir: Path | str | None = None) -> BaseTool:
    return NotebookTool(workdir)
