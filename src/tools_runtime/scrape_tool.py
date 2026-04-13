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

import logging
import re

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

# 用户代理字符串
USER_AGENT = 'ClawCode/1.0 (AI coding assistant) +https://github.com/clawd-code/claw-code'


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
        """使用 Playwright 抓取"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                html = page.content()
            finally:
                browser.close()

        return self._html_to_markdown(html)

    def _scrape_with_httpx(self, url: str) -> str | None:
        """使用 httpx 抓取"""
        import httpx

        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        with httpx.Client(
            verify=self.verify_ssl,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        return self._html_to_markdown(html)

    def _scrape_with_urllib(self, url: str) -> str | None:
        """使用 urllib 抓取（标准库回退）"""
        import urllib.error
        import urllib.request

        headers = {'User-Agent': USER_AGENT}
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
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
        if not re.match(r'https?://', url):
            return False, 'URL 必须以 http:// 或 https:// 开头'
        return True, ''

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
