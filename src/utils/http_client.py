"""
Enhanced HTTP Client - 增强 HTTP 客户端（整合自 New-API）
支持连接池、HTTP/2、流式转发、代理
适用于 LLM API 转发场景
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from loguru import logger


class EnhancedHTTPClient:
    """
    增强 HTTP 客户端（整合自 New-API）

    功能:
    - 全局连接池（max_connections=100, max_keepalive=20）
    - HTTP/2 支持
    - 流式请求（SSE 转发）
    - 代理支持
    - 超时配置
    """

    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        timeout: float = 60.0,
        http2: bool = True,
        proxy: str | None = None,
    ):
        """
        初始化客户端

        Args:
            max_connections: 最大连接数
            max_keepalive_connections: 最大保活连接数
            timeout: 超时时间（秒）
            http2: 是否启用 HTTP/2
            proxy: 代理 URL
        """
        self._timeout = httpx.Timeout(timeout=timeout)
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        self._http2 = http2
        self._proxy = proxy

        # 延迟创建客户端
        self._client: httpx.AsyncClient | None = None

        logger.info(
            f"增强 HTTP 客户端已初始化 "
            f"(max_connections={max_connections}, keepalive={max_keepalive_connections}, "
            f"http2={http2}, timeout={timeout}s)"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """
        获取或创建 HTTP 客户端（单例）

        Returns:
            httpx.AsyncClient 实例
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=self._limits,
                http2=self._http2,
                proxy=self._proxy,
                # 跟随重定向
                follow_redirects=True,
                # 验证 SSL
                verify=True,
            )
            logger.debug("创建新的 HTTP 客户端")

        return self._client

    async def forward_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        content: str | bytes | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """
        转发 HTTP 请求（普通模式）

        Args:
            method: HTTP 方法
            url: 目标 URL
            headers: 请求头
            json: JSON 请求体
            content: 原始请求体
            params: URL 参数
            timeout: 超时时间（覆盖默认）

        Returns:
            HTTP 响应
        """
        client = await self._get_client()

        request_timeout = self._timeout if timeout is None else httpx.Timeout(timeout=timeout)

        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                content=content,
                params=params,
                timeout=request_timeout,
            )

            logger.debug(
                f"HTTP 请求完成: {method} {url} "
                f"(status={response.status_code})"
            )

            return response

        except httpx.TimeoutException as e:
            logger.error(f"HTTP 请求超时: {method} {url} ({e})")
            raise
        except httpx.ConnectError as e:
            logger.error(f"HTTP 连接失败: {method} {url} ({e})")
            raise
        except Exception as e:
            logger.error(f"HTTP 请求异常: {method} {url} ({e})")
            raise

    async def stream_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        流式 HTTP 请求（SSE 转发）

        Args:
            method: HTTP 方法
            url: 目标 URL
            headers: 请求头
            json: JSON 请求体
            params: URL 参数
            timeout: 超时时间

        Yields:
            响应数据块
        """
        client = await self._get_client()
        request_timeout = self._timeout if timeout is None else httpx.Timeout(timeout=timeout)

        try:
            async with client.stream(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
                timeout=request_timeout,
            ) as response:
                logger.debug(
                    f"HTTP 流式请求开始: {method} {url} "
                    f"(status={response.status_code})"
                )

                async for chunk in response.aiter_bytes():
                    yield chunk

                logger.debug(f"HTTP 流式请求完成: {method} {url}")

        except httpx.TimeoutException as e:
            logger.error(f"HTTP 流式请求超时: {method} {url} ({e})")
            raise
        except Exception as e:
            logger.error(f"HTTP 流式请求异常: {method} {url} ({e})")
            raise

    @asynccontextmanager
    async def session(self):
        """
        上下文管理器：创建临时会话

        Yields:
            httpx.AsyncClient 实例
        """
        client = httpx.AsyncClient(
            timeout=self._timeout,
            limits=self._limits,
            http2=self._http2,
            proxy=self._proxy,
            follow_redirects=True,
        )

        try:
            yield client
        finally:
            await client.aclose()
            logger.debug("HTTP 会话已关闭")

    async def build_url(
        self,
        base_url: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> str:
        """
        构建完整 URL

        Args:
            base_url: 基础 URL
            path: 路径
            params: URL 参数

        Returns:
            完整 URL
        """
        # 移除尾部斜杠
        base_url = base_url.rstrip('/')

        # 添加路径
        if not path.startswith('/'):
            path = '/' + path

        url = f"{base_url}{path}"

        # 添加参数
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            url = f"{url}?{query_string}"

        return url

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("HTTP 客户端已关闭")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# 全局单例
_http_client: EnhancedHTTPClient | None = None


def get_http_client(
    max_connections: int = 100,
    max_keepalive_connections: int = 20,
    timeout: float = 60.0,
    http2: bool = True,
    proxy: str | None = None,
) -> EnhancedHTTPClient:
    """
    获取或创建增强 HTTP 客户端（单例）

    Args:
        max_connections: 最大连接数
        max_keepalive_connections: 最大保活连接数
        timeout: 超时时间
        http2: 是否启用 HTTP/2
        proxy: 代理 URL

    Returns:
        EnhancedHTTPClient 实例
    """
    global _http_client

    if _http_client is None:
        _http_client = EnhancedHTTPClient(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            timeout=timeout,
            http2=http2,
            proxy=proxy,
        )

    return _http_client


async def forward_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    **kwargs
) -> httpx.Response:
    """
    快捷函数：转发 HTTP 请求

    Args:
        method: HTTP 方法
        url: 目标 URL
        headers: 请求头
        json: JSON 请求体
        **kwargs: 其他参数

    Returns:
        HTTP 响应
    """
    client = get_http_client()
    return await client.forward_request(method, url, headers, json, **kwargs)


async def stream_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    **kwargs
) -> AsyncGenerator[bytes, None]:
    """
    快捷函数：流式 HTTP 请求

    Args:
        method: HTTP 方法
        url: 目标 URL
        headers: 请求头
        json: JSON 请求体
        **kwargs: 其他参数

    Yields:
        响应数据块
    """
    client = get_http_client()
    async for chunk in client.stream_request(method, url, headers, json, **kwargs):
        yield chunk
