"""
连接器模块 - 整合自 Onyx 的数据连接器

支持:
- 本地文件
- Web 抓取
- GitHub
- Slack (预留)
- Google Drive (预留)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConnectorType(str, Enum):
    """连接器类型"""
    FILE = "file"
    WEB = "web"
    GITHUB = "github"
    SLACK = "slack"
    NOTION = "notion"
    GOOGLE_DRIVE = "google_drive"
    CONFLUENCE = "confluence"
    CUSTOM = "custom"


@dataclass
class ConnectorConfig:
    """连接器配置"""
    connector_type: ConnectorType
    name: str
    source: str  # 数据源路径/URL
    enabled: bool = True
    # 认证
    auth_type: str | None = None
    credentials: dict[str, str] | None = None
    # 索引设置
    index_on_startup: bool = False
    refresh_rate_seconds: int = 3600
    # 过滤
    file_types: list[str] = field(default_factory=lambda: ["*"])
    exclude_patterns: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)


@dataclass
class ConnectorDocument:
    """连接器文档"""
    doc_id: str
    title: str
    content: str
    source: str
    connector_name: str
    mime_type: str | None = None
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """连接器基类"""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._documents: list[ConnectorDocument] = []

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    def load(self) -> list[ConnectorDocument]:
        """加载文档"""
        pass

    @abstractmethod
    def load_batch(self, batch_size: int = 100) -> list[ConnectorDocument]:
        """批量加载文档"""
        pass

    def test_connection(self) -> tuple[bool, str]:
        """测试连接"""
        return True, "OK"

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            "name": self.name,
            "type": self.config.connector_type.value,
            "document_count": len(self._documents),
        }


class FileConnector(BaseConnector):
    """本地文件连接器"""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._base_path = Path(config.source)

    def load(self) -> list[ConnectorDocument]:
        """加载本地文件"""
        from src.tools_runtime.file_processor import get_file_processor

        processor = get_file_processor()
        docs = []

        if not self._base_path.exists():
            logger.warning(f"路径不存在: {self._base_path}")
            return docs

        # 递归遍历文件
        for file_path in self._base_path.rglob("*"):
            if file_path.is_file() and processor.is_supported(file_path):
                chunks = processor.process_file(file_path)
                for chunk in chunks:
                    doc = ConnectorDocument(
                        doc_id=f"{self.name}:{file_path.name}",
                        title=file_path.name,
                        content=chunk.text,
                        source=str(file_path),
                        connector_name=self.name,
                    )
                    docs.append(doc)

        self._documents = docs
        return docs

    def load_batch(self, batch_size: int = 100) -> list[ConnectorDocument]:
        """批量加载"""
        if not self._documents:
            self.load()
        return self._documents[:batch_size]


class WebConnector(BaseConnector):
    """Web 连接器"""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)

    def load(self) -> list[ConnectorDocument]:
        """加载网页"""
        from src.utils.scrape import scrape_url

        docs = []
        url = self.config.source

        try:
            content = scrape_url(url)
            doc = ConnectorDocument(
                doc_id=f"{self.name}:{url}",
                title=url.split("/")[-1] or "index",
                content=content,
                source=url,
                connector_name=self.name,
            )
            docs.append(doc)
        except Exception as e:
            logger.error(f"抓取失败: {url}, error: {e}")

        self._documents = docs
        return docs

    def load_batch(self, batch_size: int = 100) -> list[ConnectorDocument]:
        """批量加载"""
        return self._documents[:batch_size]


class GitHubConnector(BaseConnector):
    """GitHub 连接器"""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._api = None

    def _ensure_client(self):
        """确保 GitHub 客户端已初始化"""
        if self._api is None:
            try:
                import requests
                self._api = requests
                self._token = self.config.credentials.get("token") if self.config.credentials else None
            except ImportError:
                logger.warning("requests 未安装")

    def load(self) -> list[ConnectorDocument]:
        """加载 GitHub 仓库"""
        self._ensure_client()
        docs = []

        # 解析 source: owner/repo[/path]
        parts = self.config.source.split("/")
        if len(parts) < 2:
            logger.error(f"无效的 GitHub 源: {self.config.source}")
            return docs

        owner, repo = parts[0], parts[1]
        path = "/".join(parts[2:]) if len(parts) > 2 else ""

        headers = {}
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        try:
            # 获取仓库内容
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            response = self._api.get(api_url, headers=headers)
            response.raise_for_status()

            contents = response.json()
            if isinstance(contents, list):
                for item in contents[:50]:  # 限制数量
                    if item.get("type") == "file":
                        # 获取文件内容
                        file_resp = self._api.get(item["download_url"])
                        doc = ConnectorDocument(
                            doc_id=f"{self.name}:{item['path']}",
                            title=item["name"],
                            content=file_resp.text,
                            source=item["html_url"],
                            connector_name=self.name,
                        )
                        docs.append(doc)
            else:
                # 单个文件
                doc = ConnectorDocument(
                    doc_id=f"{self.name}:{contents['path']}",
                    title=contents["name"],
                    content=contents.get("content", ""),
                    source=contents["html_url"],
                    connector_name=self.name,
                )
                docs.append(doc)

        except Exception as e:
            logger.error(f"GitHub 加载失败: {e}")

        self._documents = docs
        return docs

    def load_batch(self, batch_size: int = 100) -> list[ConnectorDocument]:
        """批量加载"""
        if not self._documents:
            self.load()
        return self._documents[:batch_size]


class ConnectorFactory:
    """连接器工厂"""

    _connectors: dict[str, BaseConnector] = {}

    @classmethod
    def create(cls, config: ConnectorConfig) -> BaseConnector:
        """创建连接器"""
        connector_type = config.connector_type

        if connector_type == ConnectorType.FILE:
            return FileConnector(config)
        elif connector_type == ConnectorType.WEB:
            return WebConnector(config)
        elif connector_type == ConnectorType.GITHUB:
            return GitHubConnector(config)
        else:
            logger.warning(f"不支持的连接器类型: {connector_type}")
            return FileConnector(config)  # 回退

    @classmethod
    def register(cls, name: str, connector: BaseConnector) -> None:
        """注册连接器"""
        cls._connectors[name] = connector

    @classmethod
    def get(cls, name: str) -> BaseConnector | None:
        """获取连接器"""
        return cls._connectors.get(name)

    @classmethod
    def list_connectors(cls) -> list[str]:
        """列出连接器"""
        return list(cls._connectors.keys())

    @classmethod
    def load_all(cls) -> list[ConnectorDocument]:
        """加载所有连接器的文档"""
        all_docs = []
        for connector in cls._connectors.values():
            try:
                docs = connector.load()
                all_docs.extend(docs)
            except Exception as e:
                logger.error(f"加载连接器失败: {connector.name}, error: {e}")
        return all_docs


# 便捷函数
def create_connector(
    connector_type: ConnectorType,
    name: str,
    source: str,
    **kwargs
) -> BaseConnector:
    """创建连接器"""
    config = ConnectorConfig(
        connector_type=connector_type,
        name=name,
        source=source,
        **kwargs
    )
    return ConnectorFactory.create(config)


def load_connector(name: str) -> list[ConnectorDocument]:
    """加载连接器文档"""
    connector = ConnectorFactory.get(name)
    if connector:
        return connector.load()
    return []
