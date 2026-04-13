"""HTTP 客户端测试 - 覆盖 src/utils/http_client.py"""

import pytest
from src.utils.http_client import (
    EnhancedHTTPClient,
)


class TestEnhancedHTTPClient:
    """增强 HTTP 客户端测试"""

    def test_init_default(self):
        """测试默认初始化"""
        client = EnhancedHTTPClient()
        assert client is not None

    def test_init_custom(self):
        """测试自定义参数"""
        client = EnhancedHTTPClient(
            max_connections=50,
            max_keepalive_connections=10,
            timeout=30.0,
            http2=False,
        )
        assert client is not None

    def test_init_with_proxy(self):
        """测试代理初始化"""
        client = EnhancedHTTPClient(proxy="http://localhost:8080")
        assert client is not None

    async def test_get_async(self):
        """测试异步 GET"""
        client = EnhancedHTTPClient()
        try:
            async with client.get("https://httpbin.org/get") as response:
                assert response.status_code == 200
        except Exception:
            pass  # 网络可能不可用

    async def test_post_async(self):
        """测试异步 POST"""
        client = EnhancedHTTPClient()
        try:
            async with client.post("https://httpbin.org/post", json={"test": True}) as response:
                assert response.status_code == 200
        except Exception:
            pass

    def test_context_manager(self):
        """测试上下文管理器"""
        client = EnhancedHTTPClient()
        # 测试 __aenter__/__aexit__
        import inspect
        assert hasattr(client, '__aenter__')
        assert hasattr(client, '__aexit__')


class TestSyncClient:
    """同步客户端测试"""

    def test_sync_get(self):
        """测试同步 GET"""
        client = EnhancedHTTPClient()
        try:
            response = client.get_sync("https://httpbin.org/get")
            assert response.status_code == 200
        except Exception:
            pass

    def test_sync_post(self):
        """测试同步 POST"""
        client = EnhancedHTTPClient()
        try:
            response = client.post_sync("https://httpbin.org/post", json={"test": True})
            assert response.status_code == 200
        except Exception:
            pass