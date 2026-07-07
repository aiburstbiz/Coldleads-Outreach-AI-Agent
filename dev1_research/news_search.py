"""
Day 7.5 - Comprehensive External Web Research
dev1_research/news_search.py

Gathers broad external signal about a company from the web — not just
news, but founding facts, awards, funding history, leadership, and
notable clients — so the analyzer has enough real material to fill in
a full company snapshot and deck-ready details, not just a thin summary.

NOTE: This does NOT scrape LinkedIn directly — LinkedIn blocks
non-logged-in automated access. This only captures what search engines
have already indexed as public snippets.

Usage:
    from dev1_research.news_search import get_external_context
    context_text = get_external_context("KFintech", "kfintech.com")
"""

import logging
import time
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 400
MAX_RESULTS_PER_QUERY = 5


def _domain_of(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _search(query: str, max_results: int = MAX_RESULTS_PER_QUERY, retries: int = 2, delay: float = 1.5) -> list[dict]:
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except DDGSException as e:
            if attempt < retries:
                logger.warning(f"Search attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(delay)
            else:
                logger.error(f"Search failed for '{query}': {e}")
    return []


def _snippets_from(results: list[dict], own_domain: str = "", exclude_own: bool = True) -> list[str]:
    """Turn raw search results into clean 'Title: snippet (url)' lines,
    optionally excluding the company's own domain (already covered by
    the site scrape, so not needed here)."""
    lines = []
    for r in results:
        url = r.get("href", "")
        if exclude_own and own_domain and url and _domain_of(url) == own_domain:
            continue
        title = r.get("title", "")
        body = (r.get("body", "") or "")[:SNIPPET_MAX_CHARS]
        if title or body:
            lines.append(f"- {title}: {body} ({url})")
    return lines


# ── Individual research angles ───────────────────────────────────────────────

def find_company_news(company_name: str, own_domain: str = "") -> list[str]:
    results = _search(f'"{company_name}" news')
    return _snippets_from(results, own_domain)


def find_linkedin_snippet(company_name: str) -> list[str]:
    results = _search(f'"{company_name}" site:linkedin.com/company', max_results=3)
    lines = []
    for r in results:
        if "linkedin.com/company" in r.get("href", "").lower():
            title = r.get("title", "")
            body = (r.get("body", "") or "")[:SNIPPET_MAX_CHARS]
            lines.append(f"- {title}: {body} ({r.get('href', '')})")
    return lines


def find_company_facts(company_name: str, own_domain: str = "") -> list[str]:
    """Founding year, headquarters, employee count."""
    results = _search(f'"{company_name}" founded year employees headquarters')
    return _snippets_from(results, own_domain)


def find_awards_and_certifications(company_name: str, own_domain: str = "") -> list[str]:
    results = _search(f'"{company_name}" award certification recognition ISO')
    return _snippets_from(results, own_domain)


def find_funding_and_milestones(company_name: str, own_domain: str = "") -> list[str]:
    results = _search(f'"{company_name}" funding investors revenue milestone')
    return _snippets_from(results, own_domain)


def find_leadership_and_clients(company_name: str, own_domain: str = "") -> list[str]:
    results = _search(f'"{company_name}" founder CEO clients case study partnership')
    return _snippets_from(results, own_domain)


# ── Combined entry point ──────────────────────────────────────────────────────

def get_external_context(company_name: str, own_domain: str = "") -> str:
    """Run all research angles and combine into one formatted text block,
    ready to append to the scraped website text before sending to the
    analyzer. Never raises — external context is a bonus, not required.
    Each failed angle is skipped individually so one bad search doesn't
    block the others."""
    sections = [
        ("RECENT NEWS & EXTERNAL MENTIONS", lambda: find_company_news(company_name, own_domain)),
        ("LINKEDIN SNIPPET (public search index only)", lambda: find_linkedin_snippet(company_name)),
        ("COMPANY FACTS (founding year, size, HQ)", lambda: find_company_facts(company_name, own_domain)),
        ("AWARDS & CERTIFICATIONS", lambda: find_awards_and_certifications(company_name, own_domain)),
        ("FUNDING & MILESTONES", lambda: find_funding_and_milestones(company_name, own_domain)),
        ("LEADERSHIP & NOTABLE CLIENTS", lambda: find_leadership_and_clients(company_name, own_domain)),
    ]

    parts = []
    for label, fetch_fn in sections:
        try:
            lines = fetch_fn()
            if lines:
                parts.append(f"=== {label} ===\n" + "\n".join(lines))
        except Exception as e:
            logger.warning(f"'{label}' search failed for {company_name}: {e}")

    return "\n\n".join(parts)


if __name__ == "__main__":
    company = "KFintech"
    print(f"\nExternal context for: {company}")
    print("=" * 55)
    ctx = get_external_context(company, "kfintech.com")
    print(ctx if ctx else "(nothing found)")
    print(f"\nTotal length: {len(ctx)} chars")