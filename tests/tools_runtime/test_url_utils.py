"""URL Utils 单元测试"""
from __future__ import annotations

import pytest

from src.utils.url_utils import (
    ParsedURL,
    build_url,
    extract_urls,
    get_domain,
    get_file_extension,
    get_url_fingerprint,
    get_url_path,
    get_url_query,
    is_document_url,
    is_image_url,
    is_internal_link,
    is_same_domain,
    is_valid_url,
    normalize_url,
    parse_url,
    sanitize_url,
)


class TestIsValidUrl:
    def test_valid_http(self):
        assert is_valid_url('http://example.com') is True

    def test_valid_https(self):
        assert is_valid_url('https://example.com') is True

    def test_no_scheme(self):
        assert is_valid_url('example.com') is False

    def test_empty(self):
        assert is_valid_url('') is False

    def test_none(self):
        assert is_valid_url(None) is False

    def test_ftp(self):
        assert is_valid_url('ftp://example.com') is False


class TestNormalizeUrl:
    def test_trailing_slash(self):
        result = normalize_url('https://example.com/path/')
        assert result == 'https://example.com/path'

    def test_root_slash_preserved(self):
        result = normalize_url('https://example.com/')
        # 根路径的斜杠被 urlparse 保留
        assert 'example.com' in result

    def test_www_prefix(self):
        result = normalize_url('www.example.com')
        assert result == 'https://www.example.com'

    def test_lowercase_domain(self):
        result = normalize_url('https://EXAMPLE.COM/Path')
        assert 'example.com' in result

    def test_empty(self):
        assert normalize_url('') == ''


class TestExtractUrls:
    def test_single_url(self):
        text = 'check https://example.com for more'
        urls = extract_urls(text)
        assert 'https://example.com' in urls

    def test_multiple_urls(self):
        text = 'a https://a.com b https://b.com c https://a.com'
        urls = extract_urls(text)
        assert len(urls) == 2  # deduplicated

    def test_no_urls(self):
        assert extract_urls('plain text') == []

    def test_empty(self):
        assert extract_urls('') == []


class TestGetDomain:
    def test_simple(self):
        assert get_domain('https://example.com/path') == 'example.com'

    def test_subdomain(self):
        assert get_domain('https://api.example.com') == 'api.example.com'

    def test_empty(self):
        assert get_domain('') == ''


class TestIsSameDomain:
    def test_same(self):
        assert is_same_domain('https://a.com/x', 'https://a.com/y') is True

    def test_different(self):
        assert is_same_domain('https://a.com', 'https://b.com') is False

    def test_case_insensitive(self):
        assert is_same_domain('https://A.com', 'https://a.com') is True


class TestParseUrl:
    def test_valid(self):
        result = parse_url('https://example.com/path?q=1#frag')
        assert result.is_valid is True
        assert result.scheme == 'https'
        assert result.domain == 'example.com'
        assert result.path == '/path'
        assert result.query == 'q=1'
        assert result.fragment == 'frag'

    def test_empty(self):
        result = parse_url('')
        assert result.is_valid is False


class TestGetUrlPath:
    def test_with_path(self):
        assert get_url_path('https://example.com/api/v1') == '/api/v1'

    def test_root(self):
        assert get_url_path('https://example.com') == '/'


class TestGetUrlQuery:
    def test_with_params(self):
        result = get_url_query('https://example.com?key=value&foo=bar')
        assert result['key'] == 'value'
        assert result['foo'] == 'bar'

    def test_no_params(self):
        assert get_url_query('https://example.com') == {}


class TestBuildUrl:
    def test_with_params(self):
        result = build_url('https://example.com', params={'key': 'value'})
        assert 'key=value' in result

    def test_with_path(self):
        result = build_url('https://example.com', path='/new/path')
        assert '/new/path' in result


class TestIsImageUrl:
    def test_jpg(self):
        assert is_image_url('https://example.com/photo.jpg') is True

    def test_png(self):
        assert is_image_url('https://example.com/image.png') is True

    def test_html(self):
        assert is_image_url('https://example.com/page.html') is False


class TestIsDocumentUrl:
    def test_pdf(self):
        assert is_document_url('https://example.com/doc.pdf') is True

    def test_md(self):
        assert is_document_url('https://example.com/readme.md') is True

    def test_py(self):
        assert is_document_url('https://example.com/code.py') is False


class TestSanitizeUrl:
    def test_removes_control_chars(self):
        url = 'https://example.com/path\x00evil'
        result = sanitize_url(url)
        assert '\x00' not in result


class TestGetFileExtension:
    def test_html(self):
        assert get_file_extension('https://example.com/page.html') == 'html'

    def test_no_ext(self):
        assert get_file_extension('https://example.com/path') == ''


class TestIsInternalLink:
    def test_same(self):
        assert is_internal_link('https://a.com/x', 'https://a.com') is True

    def test_different(self):
        assert is_internal_link('https://b.com', 'https://a.com') is False


class TestGetUrlFingerprint:
    def test_same_url(self):
        fp1 = get_url_fingerprint('https://Example.COM/path/')
        fp2 = get_url_fingerprint('https://example.com/path')
        assert fp1 == fp2
