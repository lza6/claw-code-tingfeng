"""示例插件 — 演示 clawd 插件契约的标准写法

功能：注册一个 echo 工具 + 注入一段 system prompt + expose 一个公共服务。
"""
from clawd_sample_plugin.service import EchoService


def setup(ctx) -> None:
    """clawd 插件入口：接收 PluginContext，完成全部注册"""
    from src.tools_runtime.tool_interface import BaseTool, ToolCallStatus, ToolResult

    class EchoTool(BaseTool):
        """回声工具（示例插件提供）"""

        def __init__(self, service):
            self._service = service
            super().__init__(name="sample_echo", description="示例插件: 原样返回输入文本")

        def execute(self, text: str = "", **kwargs) -> ToolResult:
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=self._service.transform(text),
            )

    # 1. 工具注册面
    ctx.register_tool(EchoTool(EchoService()))

    # 2. prompt 注入面
    ctx.inject_prompt("你有一个 sample_echo 工具可用于测试回声。")

    # 3. expose 公共服务（供其他插件 require）
    ctx.expose("echo", EchoService())

    # 4. 生命周期钩子
    ctx.on_shutdown(lambda: print("[sample-plugin] shutdown"))
