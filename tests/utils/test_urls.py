"""Tests for src/utils/urls.py - URL constants."""
import pytest

from src.utils import urls


class TestUrlConstants:
    """Tests for URL constants."""

    def test_website_constant(self):
        """Test WEBSITE constant."""
        assert urls.WEBSITE == "https://aider.chat/"

    def test_doc_urls_is_dict(self):
        """Test DOC_URLS is a dictionary."""
        assert isinstance(urls.DOC_URLS, dict)
        assert len(urls.DOC_URLS) > 0

    def test_all_urls_start_with_https(self):
        """Test all URLs start with https."""
        for url in urls.DOC_URLS.values():
            assert url.startswith("https://")


class TestGetDocUrl:
    """Tests for get_doc_url function."""

    def test_get_valid_url(self):
        """Test getting a valid URL."""
        url = urls.get_doc_url("website")
        assert url == "https://aider.chat/"

    def test_get_invalid_url_returns_none(self):
        """Test getting invalid URL returns None."""
        result = urls.get_doc_url("invalid_key")
        assert result is None


class TestExports:
    """Tests for module exports."""

    def test_all_exports(self):
        """Test __all__ contains all expected values."""
        assert "WEBSITE" in urls.__all__
        assert "get_doc_url" in urls.__all__
        assert "DOC_URLS" in urls.__all__