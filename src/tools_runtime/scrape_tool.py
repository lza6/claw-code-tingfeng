"""ScrapeTool - 网页内容抓取工具 — 从 Aider scrape.py 移植

支持从 URL 抓取网页内容并转换为 Markdown 格式。

后端（按优先级）:
1. Playwright（完整浏览器，支持 JavaScript）
2. httpx（轻量 HTTP 客户端）
3. urllib（标准库回退）

用法:
    tool = ScrapeTool()
    result = tool.execute(url='https://example.com')
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

# 用户代理字符串
USER_AGENT = 'ClawCode/1.0 (AI coding assistant) +https://github.com/clawd-code/claw-code'

_ALLOWED_SCHEMES = frozenset({'http', 'https'})
_BLOCKED_HOSTNAMES = frozenset({
    'localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback',
    'metadata.google.internal', 'metadata',
})


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """判断地址是否属于不可抓取范围（回环/私网/链路本地/保留/组播）。"""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_safe_url(url: str, check_dns: bool = True) -> tuple[bool, str]:
    """SSRF 防护：只允许访问公网 http/https URL。

    规则（参考 agent-browser 的安全模型）：
    - 仅 http/https；
    - 拒绝 localhost / 元数据域名；
    - 拒绝 IP 字面量中的回环、私网、链路本地、保留、组播地址；
    - 对域名做 DNS 解析，任一解析结果落入上述范围即拒绝；
    - 解析失败时**默认拒绝**（安全默认），除非显式放开私网。

    设置 `CLAWD_SCRAPE_ALLOW_PRIVATE=1` 可放开私网限制（仅供本地测试）。

    注意：`check_dns=False` 只用于 `ScrapeTool.validate` 的快速预检，
    **不是安全边界**；真正的 DNS/重定向拦截发生在 `Scraper.scrape`。
    """
    allow_private = os.environ.get('CLAWD_SCRAPE_ALLOW_PRIVATE', '').lower() in ('1', 'true', 'yes')

    try:
        parsed = urlparse(url)
    except ValueError:
        return False, 'URL 解析失败'

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, '仅允许 http:// 或 https:// URL'

    host = parsed.hostname
    if not host:
        return False, 'URL 缺少主机名'

    host_lower = host.lower().rstrip('.')
    if host_lower in _BLOCKED_HOSTNAMES:
        return False, f'禁止访问本地/元数据主机: {host}'
    if host_lower.endswith('.localhost') or host_lower.endswith('.local'):
        return False, f'禁止访问本地域: {host}'

    try:
        literal = ipaddress.ip_address(host_lower)
    except ValueError:
        literal = None

    if literal is not None:
        if not allow_private and _is_blocked_ip(literal):
            return False, f'禁止访问内网/保留地址: {host}'
        return True, ''

    if not check_dns:
        # 快速路径：只做协议/主机名/IP 字面量检查，供 validate 使用，
        # 避免在事件循环中同步 DNS 解析阻塞流式输出与心跳。
        return True, ''

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        return False, f'域名解析失败（安全默认拒绝）: {host}: {e}'

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not allow_private and _is_blocked_ip(ip):
            return False, f'域名解析到内网/保留地址: {host} -> {addr}'

    return True, ''


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib 重定向处理器：在跟随重定向前校验目标 URL。

    这是生产实现（不是测试副本）：`Scraper._scrape_with_urllib` 使用它。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe, reason = is_safe_url(newurl)
        if not safe:
            raise urllib.error.HTTPError(
                newurl, code, f'blocked redirect: {reason}', headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ==================== 网页抓取器 ====================

class Scraper:
    """网页抓取器 — 支持 Playwright 和 httpx 后端"""

    def __init__(self, verify_ssl: bool = True) -> None:
        self.verify_ssl = verify_ssl

    def scrape(self, url: str) -> str | None:
        """抓取 URL 内容并转换为 Markdown

        参数:
            url: 目标 URL

        返回:
            Markdown 格式的页面内容，或 None（失败）
        """
        safe, reason = is_safe_url(url)
        if not safe:
            logger.warning(f'拒绝抓取不安全的 URL: {url} ({reason})')
            return None

        # 尝试 Playwright
        try:
            content = self._scrape_with_playwright(url)
            if content:
                return content
        except Exception as e:
            logger.debug(f'Playwright 抓取失败: {e}')

        # 尝试 httpx
        try:
            content = self._scrape_with_httpx(url)
            if content:
                return content
        except Exception as e:
            logger.debug(f'httpx 抓取失败: {e}')

        # 尝试 urllib
        try:
            content = self._scrape_with_urllib(url)
            if content:
                return content
        except Exception as e:
            logger.debug(f'urllib 抓取失败: {e}')

        return None

    def _scrape_with_playwright(self, url: str) -> str | None:
        """使用 Playwright 抓取（在请求发出前拦截不安全重定向/子资源）"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()

                def _guard(route):
                    try:
                        safe, reason = is_safe_url(route.request.url)
                        if not safe:
                            logger.warning(
                                f'拦截不安全请求: {route.request.url} ({reason})'
                            )
                            route.abort()
                            return
                        route.continue_()
                    except Exception:
                        route.abort()

                page.route('**/*', _guard)
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                html = page.content()
            finally:
                browser.close()

        return self._html_to_markdown(html)

    def _scrape_with_httpx(self, url: str) -> str | None:
        """使用 httpx 抓取（手动逐跳校验重定向）"""
        import httpx

        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        with httpx.Client(
            verify=self.verify_ssl,
            follow_redirects=False,
            timeout=30.0,
        ) as client:
            current = url
            html = ''
            for _ in range(5):
                safe, reason = is_safe_url(current)
                if not safe:
                    logger.warning(f'拒绝抓取不安全的 URL: {current} ({reason})')
                    return None

                resp = client.get(current, headers=headers)
                if resp.is_redirect:
                    location = resp.headers.get('location')
                    if not location:
                        return None
                    current = str(httpx.URL(current).join(location))
                    continue

                resp.raise_for_status()
                html = resp.text
                break
            else:
                logger.warning(f'重定向次数过多，已拒绝: {url}')
                return None

        return self._html_to_markdown(html)

    def _scrape_with_urllib(self, url: str) -> str | None:
        """使用 urllib 抓取（标准库回退，重定向前置校验）"""
        headers = {'User-Agent': USER_AGENT}
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(SafeRedirectHandler())

        try:
            with opener.open(req, timeout=30) as resp:
                html = resp.read().decode('utf-8', errors='replace')
        except urllib.error.URLError:
            return None

        return self._html_to_markdown(html)

    def _html_to_markdown(self, html: str) -> str | None:
        """将 HTML 转换为 Markdown

        优先使用 pandoc，回退到 BeautifulSoup。
        """
        # 尝试 pandoc
        try:
            return self._convert_with_pandoc(html)
        except Exception:
            pass

        # 回退到 BeautifulSoup
        try:
            return self._convert_with_beautifulsoup(html)
        except Exception:
            pass

        return None

    def _convert_with_pandoc(self, html: str) -> str:
        """使用 pandoc 转换"""
        import subprocess

        result = subprocess.run(
            ['pandoc', '-f', 'html', '-t', 'markdown', '--wrap=none'],
            input=html.encode('utf-8'),
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f'pandoc failed: {result.stderr.decode()}')

        return result.stdout.decode('utf-8')

    def _convert_with_beautifulsoup(self, html: str) -> str:
        """使用 BeautifulSoup 简单提取文本"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')

        # 移除不需要的标签
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
            tag.decompose()

        # 提取文本
        text = soup.get_text('\n', strip=True)

        # 清理多余空行
        lines = [line for line in text.splitlines() if line.strip()]
        return '\n'.join(lines)


# ==================== URL 检测 ====================

def detect_urls(text: str) -> list[str]:
    """从文本中检测 URL

    参数:
        text: 输入文本

    返回:
        URL 列表
    """
    url_pattern = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+',
        re.IGNORECASE,
    )
    return list(set(url_pattern.findall(text)))


# ==================== ScrapeTool ====================

class ScrapeTool(BaseTool):
    """网页抓取工具"""


    risk_kind = 'exec'

    name = 'ScrapeTool'
    description = '从 URL 抓取网页内容并转换为 Markdown 格式'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='url',
            param_type='str',
            required=True,
            description='要抓取的 URL',
            min_length=10,
            max_length=2048,
        ),
        ParameterSchema(
            name='max_chars',
            param_type='int',
            required=False,
            description='最大返回字符数（默认 50000）',
            default=50000,
            min_value=1000,
            max_value=500000,
        ),
    )

    def __init__(self, verify_ssl: bool = True) -> None:
        self.verify_ssl = verify_ssl
        self._scraper = Scraper(verify_ssl=verify_ssl)

    def validate(self, **kwargs) -> tuple[bool, str]:
        url = kwargs.get('url', '')
        if not url:
            return False, 'URL 不能为空'
        # 校验阶段只做协议/主机名/IP 字面量检查；DNS 在真正抓取时解析，
        # 避免同步 getaddrinfo 阻塞事件循环。
        return is_safe_url(url, check_dns=False)

    def execute(self, **kwargs) -> ToolResult:
        url = kwargs.get('url', '')
        max_chars = kwargs.get('max_chars', 50000)

        is_valid, error_msg = self.validate(url=url)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        try:
            content = self._scraper.scrape(url)
            if not content:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'无法抓取 URL: {url}',
                    exit_code=1,
                )

            # 截断过长内容
            if len(content) > max_chars:
                content = content[:max_chars] + f'\n\n[内容已截断，共 {len(content)} 字符]'

            return ToolResult(
                success=True,
                output=content,
                exit_code=0,
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'抓取失败: {e}',
                exit_code=1,
            )
