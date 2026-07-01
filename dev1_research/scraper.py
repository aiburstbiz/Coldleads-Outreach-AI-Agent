"""
Day 3 - Website Scraper
dev1_research/scraper.py

Takes a company's base URL → visits key pages (home, about, products/services,
contact, news/blog) → returns clean text per section for Gemini to analyze.

Uses:
- Playwright  : handles JS-rendered / dynamic sites
- BeautifulSoup: parses raw HTML into clean readable text

Usage:
    from dev1_research.scraper import scrape_company_website
    result = scrape_company_website("https://www.kfintech.com")
"""

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page types we care about and keywords to find their URLs in nav menus
PAGE_TARGETS = {
    "about":    ["about", "about-us", "company", "who-we-are", "overview"],
    "services": ["services", "solutions", "offerings", "what-we-do", "products"],
    "contact":  ["contact", "contact-us", "reach-us", "get-in-touch"],
    "news":     ["news", "blog", "press", "media", "updates", "insights"],
}

# HTML tags that contain the main content (skip nav, footer, ads)
CONTENT_TAGS = ["main", "article", "section", "div"]

# Tags to strip entirely — boilerplate noise
NOISE_TAGS = [
    "script", "style", "noscript", "header", "footer",
    "nav", "aside", "form", "iframe", "svg", "img",
]


@dataclass
class ScrapedPage:
    url: str
    page_type: str          # "home", "about", "services", "contact", "news"
    title: str = ""
    text: str = ""
    success: bool = True
    error: str = ""


@dataclass
class ScrapedSite:
    base_url: str
    pages: list[ScrapedPage] = field(default_factory=list)

    def get_page(self, page_type: str) -> ScrapedPage | None:
        for p in self.pages:
            if p.page_type == page_type:
                return p
        return None

    def all_text(self) -> str:
        """Concatenate text from all pages — used as input to Gemini."""
        parts = []
        for p in self.pages:
            if p.text:
                parts.append(f"=== {p.page_type.upper()} PAGE ({p.url}) ===\n{p.text}")
        return "\n\n".join(parts)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clean_text(html: str) -> str:
    """
    Parse HTML and return clean readable text.
    Strips nav/footer/scripts, collapses whitespace.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy tags
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    # Extract text with single-space separator
    text = soup.get_text(separator=" ")

    # Collapse whitespace and blank lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    return text.strip()


def _get_title(html: str) -> str:
    """Extract page <title>."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else ""


def _get_base_domain(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _find_page_links(html: str, base_url: str) -> dict[str, str]:
    """
    Scan the page HTML for links matching our PAGE_TARGETS keywords.
    Returns dict of {page_type: full_url}.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_domain = _get_base_domain(base_url)
    found: dict[str, str] = {}

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"].lower().strip()
        link_text: str = a_tag.get_text(strip=True).lower()

        # Build absolute URL
        full_url = urljoin(base_url, a_tag["href"])

        # Only follow links on the same domain
        if not full_url.startswith(base_domain):
            continue

        for page_type, keywords in PAGE_TARGETS.items():
            if page_type in found:
                continue  # already found this type
            for keyword in keywords:
                if keyword in href or keyword in link_text:
                    found[page_type] = full_url
                    break

    return found


def _fetch_page(page: Page, url: str, page_type: str, timeout: int = 15000) -> ScrapedPage:
    """
    Fetch a single URL with Playwright and return a ScrapedPage.
    Waits for the network to be idle so JS-rendered content loads.
    """
    logger.info(f"Fetching [{page_type}]: {url}")
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        # Give JS a moment to render dynamic content
        time.sleep(1.5)
        html = page.content()
        return ScrapedPage(
            url=url,
            page_type=page_type,
            title=_get_title(html),
            text=_clean_text(html),
            success=True,
        )
    except PlaywrightTimeout:
        logger.warning(f"Timeout fetching {url}")
        return ScrapedPage(url=url, page_type=page_type, success=False, error="Timeout")
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")
        return ScrapedPage(url=url, page_type=page_type, success=False, error=str(e))


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_company_website(
    base_url: str,
    max_text_per_page: int = 3000,
) -> ScrapedSite:
    """
    Scrape a company website and return structured text from key pages.

    Steps:
    1. Load home page
    2. Discover links to about / services / contact / news pages
    3. Fetch each discovered page
    4. Return ScrapedSite with cleaned text per page

    Args:
        base_url:           Company's official website URL
        max_text_per_page:  Trim text to this many chars per page (keeps Gemini prompt size manageable)

    Returns:
        ScrapedSite with one ScrapedPage per discovered section
    """
    result = ScrapedSite(base_url=base_url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Step 1: fetch home page
        home = _fetch_page(page, base_url, "home")
        if home.text:
            home.text = home.text[:max_text_per_page]
        result.pages.append(home)

        if not home.success:
            logger.error(f"Could not load home page: {base_url}")
            browser.close()
            return result

        # Step 2: discover sub-page links from home page HTML
        html = page.content()
        discovered = _find_page_links(html, base_url)
        logger.info(f"Discovered pages: {list(discovered.keys())}")

        # Step 3: fetch each discovered page
        for page_type, url in discovered.items():
            scraped = _fetch_page(page, url, page_type)
            if scraped.text:
                scraped.text = scraped.text[:max_text_per_page]
            result.pages.append(scraped)
            time.sleep(0.5)  # polite crawl delay

        browser.close()

    logger.info(
        f"Scrape complete. Pages fetched: {[p.page_type for p in result.pages if p.success]}"
    )
    return result


if __name__ == "__main__":
    test_url = "https://www.kfintech.com"
    print(f"\nScraping: {test_url}")
    print("=" * 55)

    site = scrape_company_website(test_url)

    for p in site.pages:
        status = "OK" if p.success else f"FAILED ({p.error})"
        preview = p.text[:200].replace("\n", " ") if p.text else "(no text)"
        print(f"\n[{p.page_type.upper()}] {status}")
        print(f"  URL    : {p.url}")
        print(f"  Title  : {p.title}")
        print(f"  Preview: {preview}...")