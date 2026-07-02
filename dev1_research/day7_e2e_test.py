"""
Day 7 — Module Testing (Dev1 side, in isolation from Dev2)

Runs the full research pipeline end-to-end:

    search.py -> scraper.py -> [STUB analyzer] -> recommender.py

The Gemini call in analyzer.py is replaced here with `stub_analyze()`, a
rule-based heuristic extractor. This lets you prove the whole chain works
TODAY without needing Gemini billing sorted.

SWAP-IN LATER: once billing is fixed, replace the call to `stub_analyze()`
below with `analyzer.analyze_company()` from analyzer.py — nothing else in
this file needs to change, since both return the same field shapes.

Run from the dev1_research/ folder:
    python day7_e2e_test.py
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("day7_e2e")

# ---------------------------------------------------------------------------
# Imports from your own Day 2/3/5/6 modules
# NOTE: adjust function names below if yours differ slightly — the error
# message will tell you exactly what's missing.
# ---------------------------------------------------------------------------
try:
    from search import find_company_website
except ImportError as e:
    raise ImportError(
        "Could not import find_company_website from search.py. "
        "Check the actual function name in your search.py and update the "
        "import at the top of this file if it differs."
    ) from e

try:
    from scraper import scrape_company_website
except ImportError as e:
    raise ImportError(
        "Could not import scrape_company_website from scraper.py. "
        "Check the actual function name in your scraper.py and update the "
        "import at the top of this file if it differs."
    ) from e

from recommender import recommend_services


# ---------------------------------------------------------------------------
# STUB analyzer — heuristic, rule-based, zero API calls
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{7,}\d)")

INDUSTRY_KEYWORDS = {
    "Finance / Fintech": ["fintech", "registrar", "transfer agent", "kyc", "mutual fund", "banking"],
    "Manufacturing": ["manufactur", "factory", "plant", "production", "cement", "solar module", "cell"],
    "Energy": ["solar", "renewable", "energy", "power", "mw", "gw"],
    "B2B SaaS": ["saas", "software as a service", "subscription", "platform", "cloud software"],
    "IT Services": ["it services", "consulting", "outsourcing", "software development", "system integrat"],
}

PAIN_POINT_RULES = [
    (["certificate", "audit", "compliance", "quality control", "qc"],
     "Manual certificate/audit and quality-control review processes"),
    (["manual", "spreadsheet", "paperwork"],
     "Heavy reliance on manual, paperwork-driven processes"),
    (["lead", "sales", "outreach", "crm"],
     "Manual, unscaled sales outreach and lead research"),
    (["customer support", "helpdesk", "ticket"],
     "High-volume, repetitive customer support queries"),
    (["data entry", "erp", "integration"],
     "Disconnected systems requiring manual data entry"),
]

GROWTH_SIGNAL_RULES = [
    (["expansion", "expand", "new plant", "scaling", "scale up"], "Actively expanding operations/capacity"),
    (["ipo", "raised", "funding", "series a", "series b"], "Recent funding or public listing activity"),
    (["new product", "launch", "acquisition", "merger"], "Recent product launch or M&A activity"),
]


def _get_page_text(scraped_site: Any) -> str:
    """Pull all scraped text from a ScrapedSite object (scraper.py)."""
    if scraped_site is None:
        return ""
    if hasattr(scraped_site, "all_text"):
        return scraped_site.all_text()
    # fallbacks, just in case
    if isinstance(scraped_site, str):
        return scraped_site
    return str(scraped_site)


def _get_page(scraped_site: Any, page_type: str) -> Optional[str]:
    """Grab text from one specific page (e.g. 'contact') if available."""
    if scraped_site is not None and hasattr(scraped_site, "get_page"):
        page = scraped_site.get_page(page_type)
        return page.text if page and page.success else None
    return None


def stub_analyze(company_name: str, website_url: str, scraped_site: Any) -> dict:
    """Heuristic stand-in for Gemini's analyzer.analyze_company().
    Returns the same field shapes so it's a drop-in swap later."""
    text = _get_page_text(scraped_site)
    text_lower = text.lower()

    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)

    industry = "Unknown"
    for label, kws in INDUSTRY_KEYWORDS.items():
        if any(kw in text_lower for kw in kws):
            industry = label
            break

    pain_points = [desc for kws, desc in PAIN_POINT_RULES if any(k in text_lower for k in kws)]
    growth_signals = [desc for kws, desc in GROWTH_SIGNAL_RULES if any(k in text_lower for k in kws)]

    summary_snippet = text.strip()[:280] or f"{company_name} — no scraped content available."

    return {
        "company_name": company_name,
        "website_url": website_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "about": {
            "summary": summary_snippet,
            "industry": industry,
            "founded": None,
            "size": None,
        },
        "products": [],
        "services": [],
        "contact": {
            "email": email_match.group(0) if email_match else None,
            "phone": phone_match.group(0).strip() if phone_match else None,
            "address": None,
            "social_links": [],
        },
        "news": [],
        "llm_analysis": {
            "pain_points": pain_points,
            "growth_signals": growth_signals,
            "tech_stack_hints": [],
            "summary": f"[STUB] Heuristic analysis for {company_name}. "
                       f"Industry guessed as '{industry}' from scraped text. "
                       f"Replace with real Gemini output once billing is active.",
        },
    }


# ---------------------------------------------------------------------------
# End-to-end pipeline runner, with per-stage error handling
# ---------------------------------------------------------------------------

def run_pipeline(company_name: str, use_stub: bool = True) -> Optional[dict]:
    logger.info("=" * 60)
    logger.info("Running pipeline for: %s", company_name)
    logger.info("=" * 60)

    # Stage 1: search
    try:
        website_url = find_company_website(company_name)
        if not website_url:
            logger.error("[SEARCH] No website found for '%s' - skipping.", company_name)
            return None
        logger.info("[SEARCH] %s -> %s", company_name, website_url)
    except Exception as e:
        logger.error("[SEARCH] Failed for '%s': %s", company_name, e)
        return None

    # Stage 2: scrape
    try:
        scraped_site = scrape_company_website(website_url)
        logger.info("[SCRAPE] Success for %s", website_url)
    except Exception as e:
        logger.error("[SCRAPE] Failed for '%s' (%s): %s", company_name, website_url, e)
        return None

    # Stage 3: analyze (stub or real)
    try:
        if use_stub:
            analysis = stub_analyze(company_name, website_url, scraped_site)
        else:
            from analyzer import analyze_company  # real Gemini call
            result = analyze_company(company_name, scraped_site)
            analysis = result.model_dump() if hasattr(result, "model_dump") else result
        logger.info("[ANALYZE] Industry guessed: %s", analysis["about"]["industry"])
    except Exception as e:
        logger.error("[ANALYZE] Failed for '%s': %s", company_name, e)
        return None

    # Stage 4: recommend
    try:
        recs = recommend_services(
            industry=analysis["about"]["industry"],
            pain_points=analysis["llm_analysis"]["pain_points"],
            growth_signals=analysis["llm_analysis"]["growth_signals"],
            summary=f"{analysis['about']['summary']} {analysis['llm_analysis']['summary']}",
            products=analysis["products"],
            services_offered=analysis["services"],
            top_k=3,
        )
        analysis["recommended_services"] = [r.model_dump() for r in recs]
        logger.info("[RECOMMEND] %d services matched", len(recs))
    except Exception as e:
        logger.error("[RECOMMEND] Failed for '%s': %s", company_name, e)
        analysis["recommended_services"] = []

    return analysis


def run_batch(companies: list[str], output_dir: str = "day7_test_output") -> None:
    out_path = Path(output_dir)
    out_path.mkdir(exist_ok=True)

    results = []
    for name in companies:
        result = run_pipeline(name, use_stub=True)
        if result:
            results.append(result)
            fname = out_path / f"{name.replace(' ', '_').lower()}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n[OK] {name} -> {fname}")
            print(json.dumps(result["recommended_services"], indent=2))
        else:
            print(f"\n[FAILED] {name} -> pipeline failed, see logs above")

    print(f"\n{'=' * 60}")
    print(f"Day 7 summary: {len(results)}/{len(companies)} companies succeeded")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    test_companies = [
        "KFintech",
        "Premier Energies",
        "Parasakthi Cement",
    ]
    run_batch(test_companies)