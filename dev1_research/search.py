"""
Day 2 - Company Search Tool
dev1_research/search.py

Takes a company name → returns its official website URL.

Uses DuckDuckGo search (no API key needed) with disambiguation logic
to filter out directories, social media, and aggregator sites.

Usage:
    from dev1_research.search import find_company_website
    url = find_company_website("KFintech")
"""

import logging
import re
import time
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sites that are never the company's own website
EXCLUDED_DOMAINS = {
    # Social media
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com",
    # Directories / aggregators
    "crunchbase.com", "glassdoor.com", "indeed.com", "zoominfo.com",
    "bloomberg.com", "reuters.com", "businesswire.com", "prnewswire.com",
    "dnb.com", "manta.com", "yelp.com", "yellowpages.com",
    "ambitionbox.com", "tracxn.com", "owler.com", "justdial.com",
    "indiamart.com", "tradeindia.com",
    # Wiki / general
    "wikipedia.org", "wikimedia.org",
    # Job boards
    "naukri.com", "monsterindia.com", "timesjobs.com",
}


def _extract_domain(url: str) -> str:
    """Return base domain from a URL e.g. https://www.acme.com/about -> acme.com"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_excluded(url: str) -> bool:
    """Return True if this URL belongs to a directory or social site."""
    domain = _extract_domain(url)
    for excluded in EXCLUDED_DOMAINS:
        if domain == excluded or domain.endswith("." + excluded):
            return True
    return False


def _score_url(url: str, company_name: str) -> int:
    """
    Score a URL by how likely it is to be the company's official site.
    Higher = more likely official.
    """
    domain = _extract_domain(url)
    name_parts = re.findall(r"[a-z0-9]+", company_name.lower())
    significant = [p for p in name_parts if len(p) > 2]

    score = 0

    # Strong signal: company name appears in domain
    for part in significant:
        if part in domain:
            score += 10

    # Bonus: .com / .in domains (most Indian B2B companies use these)
    if domain.endswith(".com"):
        score += 3
    elif domain.endswith(".in"):
        score += 2

    # Bonus: short domain (official sites tend to be concise)
    if len(domain) < 20:
        score += 2

    # Penalty: long paths (home page preferred over deep pages)
    path = urlparse(url).path
    if path and path != "/" and len(path) > 30:
        score -= 2

    # Penalty: suspicious TLDs unlikely for B2B Indian companies
    suspicious_tlds = [".md", ".io", ".org", ".net", ".co.uk"]
    for tld in suspicious_tlds:
        if domain.endswith(tld):
            score -= 3

    return score


def find_company_website(
    company_name: str,
    max_results: int = 15,
    retries: int = 2,
    retry_delay: float = 2.0,
) -> str | None:
    """
    Given a company name, return its official website URL.

    Strategy:
    1. Run multiple queries with different phrasings
    2. Filter out excluded domains
    3. Score remaining candidates by domain relevance
    4. Return highest-scoring URL

    Args:
        company_name:  Name of the company e.g. "KFintech"
        max_results:   How many DDG results to fetch per query
        retries:       Number of retry attempts on rate limit
        retry_delay:   Seconds to wait between retries

    Returns:
        URL string if found, None if no suitable result found
    """
    # Multiple query phrasings — quoted name first for precision
    queries = [
        f'"{company_name}" official website',
        f"{company_name} official website",
        f"{company_name} homepage India",
    ]

    candidates = []

    with DDGS() as ddgs:
        for query in queries:
            logger.info(f"Searching: {query}")

            for attempt in range(retries + 1):
                try:
                    results = list(ddgs.text(query, max_results=max_results))
                    for r in results:
                        url = r.get("href", "")
                        if url and not _is_excluded(url):
                            candidates.append(url)
                    break  # success

                except DDGSException as e:
                    if attempt < retries:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"All retries failed for query '{query}': {e}")

            if candidates:
                break  # got results from this query, skip remaining queries

    if not candidates:
        logger.warning(f"No candidates found for: {company_name}")
        return None

    # Deduplicate by domain (keep first occurrence of each domain)
    seen_domains = set()
    unique_candidates = []
    for url in candidates:
        domain = _extract_domain(url)
        if domain not in seen_domains:
            seen_domains.add(domain)
            unique_candidates.append(url)

    # Score all candidates and pick the best
    scored = [(url, _score_url(url, company_name)) for url in unique_candidates]
    scored.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"Top 3 candidates for '{company_name}':")
    for url, score in scored[:3]:
        logger.info(f"  score={score:3d}  {url}")

    best_url, best_score = scored[0]

    # If best score is very low, we probably didn't find the right site
    if best_score < 3:
        logger.warning(f"Low confidence result (score={best_score}): {best_url}")

    return best_url


if __name__ == "__main__":
    test_companies = [
        "KFintech",
        "Premier Energies",
        "Tata Consultancy Services",
        "Parasakthi Cement",
    ]

    print("\nCompany Website Search Results")
    print("=" * 55)
    for company in test_companies:
        url = find_company_website(company)
        status = url if url else "NOT FOUND"
        print(f"\n{company:35s} -> {status}")
        print()