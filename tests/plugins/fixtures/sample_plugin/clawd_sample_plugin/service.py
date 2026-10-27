"""示例插件的公共服务"""


class EchoService:
    def transform(self, text: str) -> str:
        return f"echo: {text}"
