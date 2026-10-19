"""ScrapeTool SSRF 防护测试（P1-9）。"""
from __future__ import annotations

import socket

import pytest

from src.tools_runtime.scrape_tool import ScrapeTool, is_safe_url


@pytest.mark.parametrize('url', [
    'file:///etc/passwd',
    'data:text/html,<script>alert(1)</script>',
    'javascript:alert(1)',
    'chrome://settings',
    'about:blank',
    'http://localhost/',
    'http://localhost.localdomain/',
    'http://metadata.google.internal/',
    'http://127.0.0.1/',
    'http://127.0.0.2/',
    'http://10.0.0.1/',
    'http://172.16.0.1/',
    'http://192.168.1.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/',
    'http://0.0.0.0/',
])
def test_blocks_unsafe_urls(url):
    ok, reason = is_safe_url(url)
    assert ok is False, f'{url} 应被拒绝'
    assert reason


def test_allows_public_ip_literal():
    ok, reason = is_safe_url('https://93.184.216.34/')
    assert ok is True, reason


def test_allows_public_domain(monkeypatch):
    monkeypatch.setattr(
        socket, 'getaddrinfo',
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))],
    )
    ok, reason = is_safe_url('https://example.com/path')
    assert ok is True, reason


def test_blocks_domain_resolving_to_private(monkeypatch):
    monkeypatch.setattr(
        socket, 'getaddrinfo',
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 0))],
    )
    ok, reason = is_safe_url('https://evil.example/')
    assert ok is False
    assert '内网' in reason


def test_blocks_unresolvable_domain_by_default(monkeypatch):
    def _fail(*a, **k):
        raise OSError('no dns')

    monkeypatch.setattr(socket, 'getaddrinfo', _fail)
    ok, reason = is_safe_url('https://does-not-resolve.invalid/')
    assert ok is False
    assert '解析失败' in reason


def test_allow_private_env_opt_in(monkeypatch):
    monkeypatch.setenv('CLAWD_SCRAPE_ALLOW_PRIVATE', '1')
    ok, reason = is_safe_url('http://127.0.0.1:8080/')
    assert ok is True, reason


def test_scrape_tool_validate_uses_safe_url():
    tool = ScrapeTool()
    ok, reason = tool.validate(url='file:///etc/passwd')
    assert ok is False
    assert reason

    ok, reason = tool.validate(url='')
    assert ok is False


def test_validate_does_not_block_on_dns(monkeypatch):
    """validate 阶段不应做同步 DNS（避免阻塞事件循环）。"""
    def _fail(*a, **k):
        raise OSError('no dns')

    monkeypatch.setattr(socket, 'getaddrinfo', _fail)
    ok, reason = ScrapeTool().validate(url='https://example.com')
    assert ok is True, reason


def test_urllib_redirect_handler_blocks_private_target():
    import urllib.error
    import urllib.request

    from src.tools_runtime.scrape_tool import Scraper

    captured = {}

    class _Handler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            safe, reason = is_safe_url(newurl)
            if not safe:
                raise urllib.error.HTTPError(newurl, code, f'blocked redirect: {reason}', headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    handler = _Handler()
    captured['handler'] = handler
    assert isinstance(Scraper, type)
    req = urllib.request.Request('https://example.com/')
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(req, None, 302, 'Found', {}, 'http://169.254.169.254/latest/meta-data/')
