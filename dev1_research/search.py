"""
Day 2 - Company Search Tool (v3 - fixed scoring)
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
from difflib import SequenceMatcher
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
    # Financial data / stock / IPO platforms — NOT company websites
    "investing.com", "zerodha.com", "groww.in", "moneycontrol.com",
    "screener.in", "tickertape.in", "nseindia.com", "bseindia.com",
    "economictimes.indiatimes.com", "livemint.com",
    # B2B marketplaces / product listing aggregators
    "cementsbazaar.com", "industry-report.net", "tradeindia.com",
    "exportersindia.com", "alibaba.com",
    # Wiki / general
    "wikipedia.org", "wikimedia.org",
    # Job boards
    "naukri.com", "monsterindia.com", "timesjobs.com",
}

# Generic industry/category words that should NOT count as a strong name
# match on their own — they appear in tons of unrelated domains.
GENERIC_TERMS = {
    "cement", "energy", "energies", "power", "tech", "technologies",
    "solutions", "services", "group", "industries", "industry",
    "india", "global", "international", "company", "corp", "ltd",
    "limited", "pvt", "private",
}


def _extract_domain(url: str) -> str:
    """Return base domain from a URL e.g. https://www.acme.com/about -> acme.com"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_excluded(url: str) -> bool:
    """Return True if this URL belongs to a directory or aggregator site."""
    domain = _extract_domain(url)
    for excluded in EXCLUDED_DOMAINS:
        if domain == excluded or domain.endswith("." + excluded):
            return True
    return False


def _significant_name_parts(company_name: str) -> tuple[list[str], list[str]]:
    """Split company name into (distinctive_parts, generic_parts).

    Distinctive parts are the actual identifying words (e.g. "kfintech",
    "parasakthi") — these are what should drive a strong match.
    Generic parts (cement, energy, ltd, etc.) are common industry/legal
    words that show up in many unrelated domains and shouldn't alone
    justify a high score.
    """
    parts = [p for p in re.findall(r"[a-z0-9]+", company_name.lower()) if len(p) > 2]
    distinctive = [p for p in parts if p not in GENERIC_TERMS]
    generic = [p for p in parts if p in GENERIC_TERMS]
    return distinctive, generic


def _fuzzy_contains(word: str, domain: str, threshold: float = 0.82) -> bool:
    """Check if `word` appears in `domain`, allowing minor spelling
    variance (e.g. 'parasakthi' vs domain 'parasakticement' — missing
    an 'h'). Slides a same-length window across the domain and compares
    similarity; catches close transliteration differences without being
    loose enough to match unrelated words.
    """
    if word in domain:
        return True
    w_len = len(word)
    if w_len < 4:
        return False
    for i in range(len(domain) - w_len + 2):
        window = domain[i:i + w_len + 1]
        if not window:
            continue
        ratio = SequenceMatcher(None, word, window).ratio()
        if ratio >= threshold:
            return True
    return False


def _score_url(url: str, company_name: str) -> int:
    """
    Score a URL by how likely it is to be the company's official site.
    Higher = more likely official.

    Key fix (v3): distinctive name words (e.g. "kfintech", "parasakthi")
    are weighted far higher than generic industry words (e.g. "cement",
    "energy"), so a domain matching ONLY a generic word no longer
    outranks the real company name.
    """
    domain = _extract_domain(url)
    distinctive, generic = _significant_name_parts(company_name)

    score = 0

    # Strong signal: a DISTINCTIVE name part appears in the domain
    # (fuzzy match tolerates minor spelling variance, e.g. transliteration)
    distinctive_hits = sum(1 for part in distinctive if _fuzzy_contains(part, domain))
    score += distinctive_hits * 12

    # Weak signal: a generic industry word appears — small bonus only,
    # and only if it's not the sole basis for matching
    generic_hits = sum(1 for part in generic if part in domain)
    score += generic_hits * 2

    # If NO distinctive part matched at all, heavily penalize —
    # this is very likely the wrong company (e.g. a competitor,
    # aggregator, or unrelated site that just shares an industry word)
    if distinctive and distinctive_hits == 0:
        score -= 8

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
    min_confidence: int = 8,
) -> str | None:
    """
    Given a company name, return its official website URL.

    Strategy:
    1. Run multiple queries with different phrasings
    2. Filter out excluded domains
    3. Score remaining candidates by domain relevance (distinctive name
       match weighted far above generic industry-word match)
    4. Return highest-scoring URL, or None if confidence is too low

    Args:
        company_name:   Name of the company e.g. "KFintech"
        max_results:    How many DDG results to fetch per query
        retries:        Number of retry attempts on rate limit
        retry_delay:    Seconds to wait between retries
        min_confidence: Minimum score to accept a result at all — below
                         this, we'd rather return None than guess wrong

    Returns:
        URL string if found with reasonable confidence, else None
    """
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

    # Score all candidates and pick the best.
    # Tie-break: prefer a bare root domain (e.g. "kfintech.com") over a
    # subdomain (e.g. "mfs.kfintech.com"), and a shorter/root path over a
    # deep one — subdomains are often investor portals, login pages, or
    # other sub-products, not the main company site.
    def _sort_key(item):
        url, score = item
        domain = _extract_domain(url)
        subdomain_depth = domain.count(".") - 1  # kfintech.com -> 0, mfs.kfintech.com -> 1
        path = urlparse(url).path
        path_len = 0 if path in ("", "/") else len(path)
        return (-score, subdomain_depth, path_len)

    scored = [(url, _score_url(url, company_name)) for url in unique_candidates]
    scored.sort(key=_sort_key)

    logger.info(f"Top 3 candidates for '{company_name}':")
    for url, score in scored[:3]:
        logger.info(f"  score={score:3d}  {url}")

    best_url, best_score = scored[0]

    # Reject low-confidence results instead of silently returning a
    # likely-wrong URL — better to skip a company than poison downstream
    # scraping/analysis with the wrong site.
    if best_score < min_confidence:
        logger.warning(
            f"Low confidence result (score={best_score} < {min_confidence}) for "
            f"'{company_name}': {best_url} - treating as NOT FOUND."
        )
        return None

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
        status = url if url else "NOT FOUND (low confidence — check manually)"
        print(f"\n{company:35s} -> {status}")
        print()