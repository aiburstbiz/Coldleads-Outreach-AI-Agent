"""
Day 7 — Module Testing (Dev1 side, in isolation from Dev2)

Runs the full research pipeline end-to-end:

    search.py -> scraper.py -> analyzer.py (real, Groq-backed) -> done

Recommendations are now invented directly by the analyzer (Groq),
tailored to each company — no separate fixed-catalog matching step.

NEW: run_best_of() runs the pipeline multiple times per company and
merges the results into one best-of report, since live web search
varies run to run (some runs surface more/different facts than others).

Usage:
    python day7_e2e_test.py "Company Name"
    python day7_e2e_test.py "Company One" "Company Two"

Run from the dev1_research/ folder:
    python day7_e2e_test.py "KFintech"
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("day7_e2e")

try:
    from search import find_company_website
except ImportError as e:
    raise ImportError(
        "Could not import find_company_website from search.py."
    ) from e

try:
    from scraper import scrape_company_website
except ImportError as e:
    raise ImportError(
        "Could not import scrape_company_website from scraper.py."
    ) from e


# ---------------------------------------------------------------------------
# STUB analyzer — TRUE last resort, only used if even Groq + external
# context find literally nothing at all.
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
    if scraped_site is None:
        return ""
    if hasattr(scraped_site, "all_text"):
        return scraped_site.all_text()
    if isinstance(scraped_site, str):
        return scraped_site
    return str(scraped_site)


def stub_analyze(company_name: str, website_url: str, scraped_site: Any) -> dict:
    """TRUE last-resort fallback — only reached if the real Groq analyzer
    (which already includes external news/LinkedIn context) fails or
    finds literally nothing."""
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

    summary_snippet = text.strip()[:280] or f"{company_name} - no scraped content or external signals available."

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
            "summary": f"[STUB FALLBACK] Heuristic analysis for {company_name}. "
                       f"Industry guessed as '{industry}'. Real analyzer found nothing usable.",
        },
        "recommended_services": [],  # stub can't invent tailored recommendations
    }


# ---------------------------------------------------------------------------
# End-to-end pipeline runner (single attempt)
# ---------------------------------------------------------------------------

def run_pipeline(company_name: str, use_stub: bool = False) -> Optional[dict]:
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

    # Stage 3: analyze - real Groq analyzer (uses external context even if
    # the site itself was blocked), invents tailored recommendations directly
    analysis = None
    if not use_stub:
        try:
            from analyzer import analyze_company
            result = analyze_company(company_name, scraped_site)
            analysis = result.model_dump() if hasattr(result, "model_dump") else result
            logger.info("[ANALYZE] Real analyzer succeeded for %s", company_name)
        except Exception as e:
            logger.error("[ANALYZE] Real analyzer failed for '%s': %s - falling back to stub.", company_name, e)

    if analysis is None:
        analysis = stub_analyze(company_name, website_url, scraped_site)

    logger.info("[ANALYZE] Industry: %s", analysis["about"]["industry"])

    # Stage 4: recommendations are already invented by the analyzer - just log
    recs = analysis.get("recommended_services", [])
    if recs:
        logger.info("[RECOMMEND] %d AI-invented services generated", len(recs))
    else:
        logger.warning("[RECOMMEND] No recommendations generated for '%s'", company_name)

    return analysis


# ---------------------------------------------------------------------------
# Best-of runner - runs the pipeline multiple times and merges results
# ---------------------------------------------------------------------------

def _merge_company_research(results: list[dict]) -> dict:
    """Merge multiple CompanyResearch dicts from repeated runs of the
    same company into one best-of result. For each field, prefers the
    most complete/non-null value found across all runs, and unions
    list fields (deduplicated) instead of just keeping one run's list.
    """
    if not results:
        return {}
    if len(results) == 1:
        return results[0]

    merged = dict(results[0])  # start from first run as base

    about_fields = ["summary", "industry", "founded", "size"]
    for field_name in about_fields:
        best = merged["about"].get(field_name)
        for r in results[1:]:
            candidate = r["about"].get(field_name)
            if candidate and (not best or len(str(candidate)) > len(str(best))):
                best = candidate
        merged["about"][field_name] = best

    for field_name in ["email", "phone", "address"]:
        best = merged["contact"].get(field_name)
        for r in results[1:]:
            candidate = r["contact"].get(field_name)
            if candidate and not best:
                best = candidate
        merged["contact"][field_name] = best

    def _union_list_of_str(key_path: list[str]) -> list:
        seen = []
        for r in results:
            obj = r
            for k in key_path[:-1]:
                obj = obj.get(k, {})
            items = obj.get(key_path[-1], [])
            for item in items:
                if item not in seen:
                    seen.append(item)
        return seen

    merged["products"] = _union_list_of_str(["products"])
    merged["services"] = _union_list_of_str(["services"])
    merged["contact"]["social_links"] = _union_list_of_str(["contact", "social_links"])
    merged["llm_analysis"]["pain_points"] = _union_list_of_str(["llm_analysis", "pain_points"])
    merged["llm_analysis"]["growth_signals"] = _union_list_of_str(["llm_analysis", "growth_signals"])
    merged["llm_analysis"]["tech_stack_hints"] = _union_list_of_str(["llm_analysis", "tech_stack_hints"])

    seen_labels = set()
    merged_snapshot = []
    for r in results:
        for stat in r.get("company_snapshot", []):
            label = stat.get("label", "")
            if label and label not in seen_labels:
                seen_labels.add(label)
                merged_snapshot.append(stat)
    merged["company_snapshot"] = merged_snapshot

    seen_titles = set()
    merged_news = []
    for r in results:
        for item in r.get("news", []):
            title = item.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                merged_news.append(item)
    merged["news"] = merged_news[:5]

    merged["recommended_services"] = max(
        (r.get("recommended_services", []) for r in results),
        key=len,
        default=[],
    )

    spotlights = [r.get("spotlight_use_case") for r in results if r.get("spotlight_use_case")]
    if spotlights:
        merged["spotlight_use_case"] = max(spotlights, key=lambda s: len(s.get("stages", [])))

    return merged


def run_best_of(company_name: str, attempts: int = 3, use_stub: bool = False) -> Optional[dict]:
    """Run the full pipeline multiple times for the same company and
    merge the results into one best-of report. Use this instead of
    run_pipeline() when you want the most complete result possible,
    since live web search varies run to run."""
    results = []
    for i in range(attempts):
        logger.info(f"--- Attempt {i + 1}/{attempts} for {company_name} ---")
        result = run_pipeline(company_name, use_stub=use_stub)
        if result:
            results.append(result)

    if not results:
        logger.error(f"All {attempts} attempts failed for '{company_name}'")
        return None

    merged = _merge_company_research(results)
    logger.info(f"Merged {len(results)} successful attempt(s) into final result for {company_name}")
    return merged


# ---------------------------------------------------------------------------
# Batch runner - now uses run_best_of by default
# ---------------------------------------------------------------------------

def run_batch(
    companies: list[str],
    output_dir: str = "day7_test_output",
    use_stub: bool = False,
    attempts: int = 3,
) -> None:
    out_path = Path(output_dir)
    out_path.mkdir(exist_ok=True)

    results = []
    for name in companies:
        result = run_best_of(name, attempts=attempts, use_stub=use_stub)
        if result:
            results.append(result)
            fname = out_path / f"{name.replace(' ', '_').lower()}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\n[OK] {name} -> {fname}")
            print(json.dumps(result.get("recommended_services", []), indent=2))
        else:
            print(f"\n[FAILED] {name} -> pipeline failed, see logs above")

    print(f"\n{'=' * 60}")
    print(f"Summary: {len(results)}/{len(companies)} companies succeeded")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        companies = sys.argv[1:]
    else:
        companies = [
            "KFintech",
            "Premier Energies",
            "Parasakthi Cement",
        ]
        print("No company name given as argument - running default test batch.")
        print('Tip: run it like  python day7_e2e_test.py "Company Name"\n')

    print("Running each company 3x and merging the best result from each attempt...")
    print("(This takes longer than a single run - roughly 3x the time and API calls.)\n")
    run_batch(companies, use_stub=False, attempts=3)