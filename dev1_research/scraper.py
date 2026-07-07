"""
Day 3 - Website Scraper (v2 - full-site crawl, expanded block detection)
dev1_research/scraper.py
"""

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAGE_TYPE_KEYWORDS = {
    "about":       ["about", "about-us", "who-we-are", "overview", "our-story"],
    "services":    ["services", "solutions", "offerings", "what-we-do"],
    "products":    ["products", "product"],
    "case_study":  ["case-study", "case-studies", "success-stor", "customer-stor", "portfolio"],
    "blog_post":   ["blog/", "insights/", "articles/", "resources/"],
    "news":        ["news", "press", "media", "newsroom", "press-release"],
    "team":        ["team", "leadership", "management", "founders", "people"],
    "careers":     ["career", "careers", "jobs", "join-us"],
    "contact":     ["contact", "contact-us", "reach-us", "get-in-touch"],
    "industries":  ["industries", "industry", "sectors", "verticals"],
    "pricing":     ["pricing", "plans"],
    "faq":         ["faq", "faqs"],
}

SKIP_PATTERNS = [
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "cart", "checkout", "account", "privacy-policy", "terms-of-service",
    "terms-and-conditions", "cookie-policy", "sitemap", "wp-admin",
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4",
    "mailto:", "tel:", "javascript:", "#",
]

# Phrases that indicate a bot-block / error / WAF-rejection page rather than
# real content. If we see these (usually combined with a very short page),
# we treat the page as FAILED rather than feeding the block-message to the
# AI as if it were real company info.
BLOCKED_PAGE_SIGNS = [
    "403 forbidden", "access denied", "access to this page is forbidden",
    "just a moment", "attention required", "checking your browser",
    "enable javascript and cookies", "captcha", "cloudflare ray id",
    "are you a human", "unusual traffic", "bot detection",
    "404 not found", "page not found",
    "request rejected", "your support id is",          # generic WAF blocks (e.g. Akamai/F5)
    "the requested url was rejected",                   # variant phrasing
    "reference #", "error code:",                        # common WAF error-page fragments
]

NOISE_TAGS = [
    "script", "style", "noscript", "header", "footer",
    "nav", "aside", "form", "iframe", "svg", "img",
]

MAX_PAGES_PER_SITE = 40
MAX_TEXT_PER_PAGE = 4000


@dataclass
class ScrapedPage:
    url: str
    page_type: str
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

    def get_pages(self, page_type: str) -> list[ScrapedPage]:
        return [p for p in self.pages if p.page_type == page_type]

    def all_text(self) -> str:
        parts = []
        for p in self.pages:
            if p.success and p.text:
                parts.append(f"=== {p.page_type.upper()} PAGE ({p.url}) ===\n{p.text}")
        return "\n\n".join(parts)

    def failed_pages(self) -> list[ScrapedPage]:
        return [p for p in self.pages if not p.success]


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text.strip()


def _get_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else ""


def _get_base_domain(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _should_skip(url: str) -> bool:
    low = url.lower()
    return any(pat in low for pat in SKIP_PATTERNS)


def _classify_page(url: str, title: str) -> str:
    low = (url + " " + title).lower()
    for page_type, keywords in PAGE_TYPE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return page_type
    return "other"


def _is_blocked_content(text: str, html: str) -> bool:
    """Detect bot-block / WAF-rejection / error pages so we don't feed
    the block message to the AI as if it were real company content."""
    low = text.lower()
    if any(sign in low for sign in BLOCKED_PAGE_SIGNS):
        return True
    if len(text.strip()) < 40:
        return True
    return False


def _find_internal_links(html: str, current_url: str, base_domain: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a_tag in soup.find_all("a", href=True):
        full_url = urljoin(current_url, a_tag["href"])
        if not full_url.startswith(base_domain):
            continue
        if _should_skip(full_url):
            continue
        links.append(_normalize_url(full_url))
    return links


def _fetch_page(page: Page, url: str, timeout: int = 15000) -> tuple[str, str, bool, str]:
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        time.sleep(1.2)
        html = page.content()
        text = _clean_text(html)
        if _is_blocked_content(text, html):
            return html, text, False, "Blocked or error page detected"
        return html, text, True, ""
    except PlaywrightTimeout:
        return "", "", False, "Timeout"
    except Exception as e:
        return "", "", False, str(e)


def scrape_company_website(
    base_url: str,
    max_pages: int = MAX_PAGES_PER_SITE,
    max_text_per_page: int = MAX_TEXT_PER_PAGE,
) -> ScrapedSite:
    result = ScrapedSite(base_url=base_url)
    base_domain = _get_base_domain(base_url)

    visited: set[str] = set()
    queue: deque[str] = deque([_normalize_url(base_url)])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = context.new_page()

        pages_fetched = 0
        while queue and pages_fetched < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            page_type = "home" if pages_fetched == 0 else _classify_page(url, "")
            logger.info(f"Fetching [{page_type}]: {url}")

            html, text, success, error = _fetch_page(page, url)
            title = _get_title(html) if html else ""
            page_type = "home" if pages_fetched == 0 else _classify_page(url, title)

            scraped = ScrapedPage(
                url=url,
                page_type=page_type,
                title=title,
                text=text[:max_text_per_page] if text else "",
                success=success,
                error=error,
            )
            result.pages.append(scraped)
            pages_fetched += 1

            if not success:
                logger.warning(f"  -> FAILED [{page_type}]: {error}")
                if pages_fetched == 1:
                    logger.error(f"Home page failed to load: {base_url}")
                    break
                time.sleep(0.4)
                continue

            if html:
                new_links = _find_internal_links(html, url, base_domain)
                for link in new_links:
                    if link not in visited and link not in queue:
                        queue.append(link)

            time.sleep(0.4)

        browser.close()

    ok = [p.page_type for p in result.pages if p.success]
    failed = [p.page_type for p in result.pages if not p.success]
    logger.info(f"Scrape complete. Pages OK: {ok}")
    if failed:
        logger.info(f"Pages failed/blocked: {failed}")

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

    print(f"\nTotal pages visited: {len(site.pages)}")
    print(f"Successful: {len([p for p in site.pages if p.success])}")
    print(f"Failed/blocked: {len(site.failed_pages())}")