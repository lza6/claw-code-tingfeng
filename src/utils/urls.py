"""URL Constants — Aider 文档 URL 常量（从 Aider urls.py 移植）

提供 Aider 文档链接的集中管理。

用法:
    from src.utils.urls import (
        WEBSITE,
        EDIT_FORMATS_URL,
        GIT_DOCS_URL,
    )

    print(WEBSITE)  # https://aider.chat/
"""
from __future__ import annotations

# Aider 网站
WEBSITE = "https://aider.chat/"

# 文档链接
ADD_ALL_FILES = "https://aider.chat/docs/faq.html#how-can-i-add-all-the-files-to-the-chat"
EDIT_ERRORS = "https://aider.chat/docs/troubleshooting/edit-errors.html"
GIT = "https://aider.chat/docs/git.html"
ENABLE_PLAYWRIGHT = "https://aider.chat/docs/install/optional.html#enable-playwright"
FAVICON = "https://aider.chat/assets/icons/favicon-32x32.png"
MODEL_WARNINGS = "https://aider.chat/docs/llms/warnings.html"
TOKEN_LIMITS = "https://aider.chat/docs/troubleshooting/token-limits.html"
LLMS = "https://aider.chat/docs/llms.html"
LARGE_REPOS = "https://aider.chat/docs/faq.html#can-i-use-aider-in-a-large-mono-repo"
GITHUB_ISSUES = "https://github.com/Aider-AI/aider/issues/new"
GIT_INDEX_VERSION = "https://github.com/Aider-AI/aider/issues/211"
INSTALL_PROPERLY = "https://aider.chat/docs/troubleshooting/imports.html"
ANALYTICS = "https://aider.chat/docs/more/analytics.html"
RELEASE_NOTES = "https://aider.chat/HISTORY.html#release-notes"
EDIT_FORMATS = "https://aider.chat/docs/more/edit-formats.html"
MODELS_AND_KEYS = "https://aider.chat/docs/troubleshooting/models-and-keys.html"


# 便捷访问
DOC_URLS = {
    "website": WEBSITE,
    "add_all_files": ADD_ALL_FILES,
    "edit_errors": EDIT_ERRORS,
    "git": GIT,
    "enable_playwright": ENABLE_PLAYWRIGHT,
    "model_warnings": MODEL_WARNINGS,
    "token_limits": TOKEN_LIMITS,
    "llms": LLMS,
    "large_repos": LARGE_REPOS,
    "github_issues": GITHUB_ISSUES,
    "analytics": ANALYTICS,
    "edit_formats": EDIT_FORMATS,
    "models_and_keys": MODELS_AND_KEYS,
}


def get_doc_url(key: str) -> str | None:
    """获取文档链接

    参数:
        key: 链接键名

    Returns:
        URL 字符串或 None
    """
    return DOC_URLS.get(key)


def open_doc(key: str) -> None:
    """在浏览器中打开文档链接

    参数:
        key: 链接键名
    """
    url = get_doc_url(key)
    if url:
        import webbrowser
        webbrowser.open(url)


# 导出
__all__ = [
    "ADD_ALL_FILES",
    "ANALYTICS",
    "DOC_URLS",
    "EDIT_ERRORS",
    "EDIT_FORMATS",
    "ENABLE_PLAYWRIGHT",
    "FAVICON",
    "GIT",
    "GITHUB_ISSUES",
    "GIT_INDEX_VERSION",
    "INSTALL_PROPERLY",
    "LARGE_REPOS",
    "LLMS",
    "MODELS_AND_KEYS",
    "MODEL_WARNINGS",
    "RELEASE_NOTES",
    "TOKEN_LIMITS",
    "WEBSITE",
    "get_doc_url",
    "open_doc",
]
