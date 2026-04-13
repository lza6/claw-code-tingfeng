"""信息命令 - Aider 风格信息查询命令

此模块包含信息相关的命令:
- cmd_web: 搜索网页
- cmd_tokens: 查看 token 使用情况
- cmd_browse: 抓取网页
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aider_commands_base import AiderCommandHandler


def cmd_web(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """搜索网页

    用法: /web <search query>
    需要实现 scrape_tool
    """
    if not args.strip():
        return False, "用法: /web <search query>"

    # [汲取 GoalX] 优先尝试使用 Exa/WebSearch 插件
    # 尝试使用现有的 scrape_tool
    if self.engine_ref and hasattr(self.engine_ref, 'tools'):
        scrape_tool = self.engine_ref.tools.get('ScrapeTool')
        if scrape_tool:
            try:
                # 汲取 GoalX: 如果 query 以 http 开头，自动切换为 browse 模式
                if args.strip().startswith(('http://', 'https://')):
                    return cmd_browse(self, args.strip())
                result = scrape_tool.execute(command=f"search {args}")
                return True, result.output if result.success else result.error
            except Exception:
                pass

    return True, f"搜索: {args}\n\n提示: 需要配置 ScrapeTool 以启用网页搜索功能"


def cmd_tokens(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """查看当前上下文 token 使用情况

    用法: /tokens
    """
    if self.engine_ref and hasattr(self.engine_ref, 'token_tracker'):
        tracker = self.engine_ref.token_tracker
        return True, tracker.get_report()

    return True, """Token 使用报告:

上下文窗口使用情况:
  System:     ~2000 tokens
  Chat:       基于历史长度
  Files:      基于编辑文件大小
  Repo Map:   基于 map-tokens 设置

提示: 使用 /map auto 调整代码地图大小"""


def cmd_browse(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """抓取网页并转换为 Markdown

    用法: /browse <url>
    """
    url = args.strip()
    if not url:
        return False, "用法: /browse <url>"

    # 使用 scrape tool
    if self.engine_ref and hasattr(self.engine_ref, 'tools'):
        scrape_tool = self.engine_ref.tools.get('ScrapeTool')
        if scrape_tool:
            result = scrape_tool.execute(url=url)
            if result.success:
                return True, f"已抓取 {url}\n\n{result.output[:2000]}"
            return False, f"抓取失败: {result.error}"

    return True, f"搜索: {url}\n\n提示: 需要配置 ScrapeTool 以启用网页抓取功能"
