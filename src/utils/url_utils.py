"""URL Utilities - URL 处理工具

提供 URL 解析、验证、规范化等功能。

用法:
    from src.utils.url_utils import (
        is_valid_url,
        normalize_url,
        extract_urls,
        get_domain,
        is_same_domain,
    )

    if is_valid_url(url):
        normalized = normalize_url(url)
        domain = get_domain(normalized)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# URL 正则表达式
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE,
)


@dataclass
class ParsedURL:
    """解析后的 URL 信息"""
    original: str
    scheme: str
    netloc: str
    path: str
    params: str
    query: str
    fragment: str
    domain: str
    is_valid: bool


def is_valid_url(url: str) -> bool:
    """检查 URL 是否有效"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return False
    try:
        result = urlparse(url)
        return bool(result.scheme and result.netloc)
    except Exception:
        return False


def normalize_url(url: str, default_scheme: str = 'https') -> str:
    """规范化 URL"""
    if not url:
        return ''
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        if url.startswith('www.'):
            url = f'{default_scheme}://{url}'
        else:
            url = f'{default_scheme}://{url}'

    parsed = urlparse(url)

    # 规范化路径
    path = parsed.path
    if path and path != '/' and path.endswith('/'):
        path = path.rstrip('/')

    # 规范化域名
    netloc = parsed.netloc.lower()

    return urlunparse((
        parsed.scheme, netloc, path,
        parsed.params, parsed.query, parsed.fragment,
    ))


def extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL（去重保序）"""
    if not text:
        return []
    return list(dict.fromkeys(URL_PATTERN.findall(text)))


def get_domain(url: str) -> str:
    """获取 URL 的域名"""
    if not url:
        return ''
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ''


def is_same_domain(url1: str, url2: str) -> bool:
    """检查两个 URL 是否属于同一域名"""
    return get_domain(url1) == get_domain(url2)


def parse_url(url: str) -> ParsedURL:
    """解析 URL 并返回详细信息"""
    if not url:
        return ParsedURL('', '', '', '', '', '', '', '', False)
    try:
        parsed = urlparse(url)
        return ParsedURL(
            original=url, scheme=parsed.scheme, netloc=parsed.netloc,
            path=parsed.path, params=parsed.params, query=parsed.query,
            fragment=parsed.fragment, domain=parsed.netloc.lower(),
            is_valid=bool(parsed.scheme and parsed.netloc),
        )
    except Exception:
        return ParsedURL(url, '', '', '', '', '', '', '', False)


def get_url_path(url: str) -> str:
    """获取 URL 的路径部分"""
    try:
        path = urlparse(url).path
        return path or '/'
    except Exception:
        return '/'


def get_url_query(url: str) -> dict[str, str]:
    """获取 URL 的查询参数"""
    try:
        query = urlparse(url).query
        if not query:
            return {}
        params: dict[str, str] = {}
        for param in query.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                params[key] = value
            else:
                params[param] = ''
        return params
    except Exception:
        return {}


def build_url(
    base: str,
    path: str = '',
    params: dict[str, str] | None = None,
    fragment: str = '',
) -> str:
    """构建 URL"""
    try:
        parsed = urlparse(base)
        query = '&'.join(f'{k}={v}' for k, v in (params or {}).items())
        return urlunparse((
            parsed.scheme, parsed.netloc, path or parsed.path,
            parsed.params, query, fragment,
        ))
    except Exception:
        return base


def is_internal_link(url: str, base_url: str) -> bool:
    """检查 URL 是否是内部链接"""
    return is_same_domain(url, base_url)


def sanitize_url(url: str) -> str:
    """清理 URL，移除潜在的恶意内容"""
    if not url:
        return ''
    url = re.sub(r'[\x00-\x1f\x7f]', '', url)
    return normalize_url(url)


def get_file_extension(url: str) -> str:
    """从 URL 获取文件扩展名"""
    path = get_url_path(url)
    if '.' in path:
        return path.rsplit('.', 1)[-1].lower()
    return ''


def is_image_url(url: str) -> bool:
    """检查 URL 是否指向图片"""
    return get_file_extension(url) in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico')


def is_document_url(url: str) -> bool:
    """检查 URL 是否指向文档"""
    return get_file_extension(url) in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md')


def get_url_fingerprint(url: str) -> str:
    """获取 URL 的指纹（用于去重）"""
    return normalize_url(url)
