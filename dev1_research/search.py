"""
Day 2 - Company Search Tool (v4 - acronym fix)
dev1_research/search.py
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

EXCLUDED_DOMAINS = {
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com",
    "crunchbase.com", "glassdoor.com", "indeed.com", "zoominfo.com",
    "bloomberg.com", "reuters.com", "businesswire.com", "prnewswire.com",
    "dnb.com", "manta.com", "yelp.com", "yellowpages.com",
    "ambitionbox.com", "tracxn.com", "owler.com", "justdial.com",
    "indiamart.com", "tradeindia.com",
    "investing.com", "zerodha.com", "groww.in", "moneycontrol.com",
    "screener.in", "tickertape.in", "nseindia.com", "bseindia.com",
    "economictimes.indiatimes.com", "livemint.com",
    "cementsbazaar.com", "industry-report.net", "tradeindia.com",
    "exportersindia.com", "alibaba.com",
    "consultancy.in", "consultancy.eu", "consultancy.uk", "consultancy.asia",
    "wikipedia.org", "wikimedia.org", "wikimint.com",
    "naukri.com", "monsterindia.com", "timesjobs.com",
}

GENERIC_TERMS = {
    "cement", "energy", "energies", "power", "tech", "technologies",
    "solutions", "services", "group", "industries", "industry",
    "india", "global", "international", "company", "corp", "ltd",
    "limited", "pvt", "private", "consultancy", "consulting",
}


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_excluded(url: str) -> bool:
    domain = _extract_domain(url)
    for excluded in EXCLUDED_DOMAINS:
        if domain == excluded or domain.endswith("." + excluded):
            return True
    return False


def _significant_name_parts(company_name: str) -> tuple[list[str], list[str]]:
    parts = [p for p in re.findall(r"[a-z0-9]+", company_name.lower()) if len(p) > 2]
    distinctive = [p for p in parts if p not in GENERIC_TERMS]
    generic = [p for p in parts if p in GENERIC_TERMS]
    return distinctive, generic


def _acronym(company_name: str) -> str:
    words = re.findall(r"[a-z0-9]+", company_name.lower())
    if len(words) < 2:
        return ""
    return "".join(w[0] for w in words if w)


def _fuzzy_contains(word: str, domain: str, threshold: float = 0.82) -> bool:
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
    domain = _extract_domain(url)
    distinctive, generic = _significant_name_parts(company_name)

    score = 0
    distinctive_hits = sum(1 for part in distinctive if _fuzzy_contains(part, domain))
    score += distinctive_hits * 12

    generic_hits = sum(1 for part in generic if part in domain)
    score += generic_hits * 2

    no_distinctive_match = bool(distinctive) and distinctive_hits == 0
    if no_distinctive_match:
        score -= 8

    acronym = _acronym(company_name)
    domain_root = domain.split(".")[0]
    if acronym and len(acronym) >= 2 and domain_root == acronym:
        score += 20
        if no_distinctive_match:
            score += 8

    if domain.endswith(".com"):
        score += 3
    elif domain.endswith(".in"):
        score += 2

    if len(domain) < 20:
        score += 2

    path = urlparse(url).path
    if path and path != "/" and len(path) > 30:
        score -= 2

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
                    break
                except DDGSException as e:
                    if attempt < retries:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"All retries failed for query '{query}': {e}")
            if candidates:
                break

    if not candidates:
        logger.warning(f"No candidates found for: {company_name}")
        return None

    seen_domains = set()
    unique_candidates = []
    for url in candidates:
        domain = _extract_domain(url)
        if domain not in seen_domains:
            seen_domains.add(domain)
            unique_candidates.append(url)

    def _sort_key(item):
        url, score = item
        domain = _extract_domain(url)
        subdomain_depth = domain.count(".") - 1
        path = urlparse(url).path
        path_len = 0 if path in ("", "/") else len(path)
        return (-score, subdomain_depth, path_len)

    scored = [(url, _score_url(url, company_name)) for url in unique_candidates]
    scored.sort(key=_sort_key)

    logger.info(f"Top 3 candidates for '{company_name}':")
    for url, score in scored[:3]:
        logger.info(f"  score={score:3d}  {url}")

    best_url, best_score = scored[0]

    # Prefer the clean root URL over a random deep/query-string page
    best_domain = _extract_domain(best_url)
    root_candidate = f"https://{best_domain}/"
    if best_url != root_candidate:
        for url, score in scored:
            if _extract_domain(url) == best_domain and url.rstrip("/") in (
                f"https://{best_domain}", f"https://www.{best_domain}"
            ):
                best_url = url
                break

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