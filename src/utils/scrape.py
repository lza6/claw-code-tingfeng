"""Scrape - Web scraping from Aider

Adapted from aider/scrape.py
Provides: URL content extraction with Playwright/httpx fallback
"""

import re


def get_user_agent():
    """Get the user agent string."""
    try:
        from aider import __version__, urls
        return f"ClawdCode/{__version__} +{urls.website}"
    except ImportError:
        return "ClawdCode/1.0"


def check_playwright() -> tuple[bool, bool]:
    """Check if Playwright is available."""
    has_pip = False
    has_chromium = False

    try:
        from playwright.sync_api import sync_playwright
        has_pip = True
        try:
            with sync_playwright() as p:
                p.chromium.launch()
                has_chromium = True
        except Exception:
            pass
    except ImportError:
        pass

    return has_pip, has_chromium


def is_playwright_available() -> bool:
    """Check if Playwright is fully available."""
    has_pip, has_chromium = check_playwright()
    return has_pip and has_chromium


def install_playwright(io=None):
    """Install Playwright if requested."""
    has_pip, has_chromium = check_playwright()
    if has_pip and has_chromium:
        return True

    cmds = []
    if not has_pip:
        cmds.append("pip install playwright")
    if not has_chromium:
        cmds.append("python -m playwright install --with-deps chromium")

    text = f"""For better web scraping, install Playwright:

{' && '.join(cmds)}
"""
    if io:
        io.tool_output(text)
        if not io.confirm_ask("Install playwright?", default="y"):
            return None
    else:
        print(text)
        return None

    # Try to install
    try:
        import subprocess
        for cmd in cmds:
            subprocess.run(cmd.split(), check=True)
        return True
    except Exception as e:
        if io:
            io.tool_error(f"Install failed: {e}")
        return None


class Scraper:
    """Web content scraper with HTML to Markdown conversion."""

    pandoc_available = None
    playwright_available = None

    def __init__(self, print_error=None, playwright_available=None, verify_ssl=True):
        """
        Args:
            print_error: Function to print errors
            playwright_available: Override Playwright detection
            verify_ssl: Enable SSL verification
        """
        if print_error:
            self.print_error = print_error
        else:
            self.print_error = print

        self.playwright_available = playwright_available
        self.verify_ssl = verify_ssl
        self.user_agent = get_user_agent()

    def scrape(self, url: str) -> str | None:
        """Scrape URL and convert HTML to Markdown if needed."""
        if self.playwright_available:
            content, mime_type = self._scrape_with_playwright(url)
        else:
            content, mime_type = self._scrape_with_httpx(url)

        if not content:
            self.print_error(f"Failed to retrieve content from {url}")
            return None

        # Convert HTML to Markdown
        if (mime_type and mime_type.startswith("text/html")) or \
           (mime_type is None and self._looks_like_html(content)):
            self._ensure_pandoc()
            content = self._html_to_markdown(content)

        return content

    def _looks_like_html(self, content: str) -> bool:
        """Check if content appears to be HTML."""
        html_patterns = [
            r"<!DOCTYPE\s+html",
            r"<html",
            r"<head",
            r"<body",
            r"<div",
            r"<p>",
            r"<a\s+href=",
        ]
        return any(re.search(p, content, re.IGNORECASE) for p in html_patterns)

    def _scrape_with_playwright(self, url: str) -> tuple[str | None, str | None]:
        """Scrape using Playwright (headless Chrome)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.playwright_available = False
            return self._scrape_with_httpx(url)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(ignore_https_errors=not self.verify_ssl)
                page = context.new_page()

                # Set user agent
                user_agent = self.user_agent.replace("Headless", "").replace("headless", "")
                page.set_extra_http_headers({"User-Agent": user_agent})

                try:
                    page.goto(url, wait_until="networkidle", timeout=10000)
                except Exception as e:
                    self.print_error(f"Page load warning: {e}")

                content = page.content()
                mime_type = None

                browser.close()
                return content, mime_type

        except Exception as e:
            self.print_error(f"Playwright error: {e}")
            self.playwright_available = False
            return self._scrape_with_httpx(url)

    def _scrape_with_httpx(self, url: str) -> tuple[str | None, str | None]:
        """Scrape using httpx (fallback)."""
        try:
            import httpx
            headers = {"User-Agent": f"Mozilla/5.0 ({self.user_agent})"}
            with httpx.Client(
                headers=headers,
                verify=self.verify_ssl,
                follow_redirects=True,
                timeout=10.0
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text, response.headers.get("content-type", "").split(";")[0]
        except Exception as e:
            self.print_error(f"HTTP error: {e}")
            return None, None

    def _ensure_pandoc(self):
        """Ensure pandoc is available."""
        if self.pandoc_available is not None:
            return

        self.pandoc_available = False
        try:
            import pypandoc
            pypandoc.get_pandoc_version()
            self.pandoc_available = True
        except Exception:
            pass

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML to Markdown."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html

        soup = BeautifulSoup(html, "html.parser")
        soup = _slimdown_html(soup)

        if not self.pandoc_available:
            return str(soup)

        try:
            import pypandoc
            md = pypandoc.convert_text(str(soup), "markdown", format="html")
            # Clean up extra whitespace
            md = re.sub(r"</div>", "      ", md)
            md = re.sub(r"<div>", "     ", md)
            md = re.sub(r"\n\s*\n", "\n\n", md)
            return md
        except Exception:
            return str(soup)


def _slimdown_html(soup):
    """Remove unnecessary elements from HTML."""
    # Remove SVG and images
    for tag in soup.find_all("svg"):
        tag.decompose()
    if soup.img:
        soup.img.decompose()

    # Remove data: links
    for tag in soup.find_all(href=lambda x: x and x.startswith("data:")):
        tag.decompose()
    for tag in soup.find_all(src=lambda x: x and x.startswith("data:")):
        tag.decompose()

    # Keep only href attributes
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr != "href":
                tag.attrs.pop(attr, None)

    return soup


# Convenience function
_default_scraper = None


def scrape(url: str, verify_ssl: bool = True) -> str | None:
    """Quick scrape function using default scraper."""
    global _default_scraper
    if _default_scraper is None:
        _default_scraper = Scraper(playwright_available=is_playwright_available(), verify_ssl=verify_ssl)
    return _default_scraper.scrape(url)


__all__ = [
    "Scraper",
    "check_playwright",
    "install_playwright",
    "is_playwright_available",
    "scrape",
]
