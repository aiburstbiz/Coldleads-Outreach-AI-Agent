"""
Day 4 - Groq Analyzer (v9 - source_text extraction for fact-check reuse)
dev1_research/analyzer.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from groq import Groq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.schema import (
    About, CompanyResearch, Contact, LLMAnalysis,
    NewsItem, Priority, ProductOrService, RecommendedService,
    SnapshotStat, SpotlightStage, SpotlightUseCase,
)
from dev1_research.scraper import ScrapedSite
from dev1_research.news_search import get_external_context

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set. Add it to your .env file.")
    return Groq(api_key=api_key)


SYSTEM_PROMPT = """You are a B2B sales research analyst preparing content for a client-facing sales
presentation deck. You will be given scraped website content plus external news/LinkedIn/company-facts
search results. Your job is to extract structured, PRESENTATION-READY information and return ONLY valid
JSON — no explanation, no markdown, no backticks.

This output will be dropped directly into PowerPoint slides, so:
- Company snapshot stats must be concrete, quotable facts (numbers, names, scale) — not vague claims
- Pain points must be written as full, specific explanations (1-2 sentences each), not short phrases
- Solution reasons must be described in enough depth that a salesperson could read them aloud to a client
- The spotlight use case should be one genuinely compelling flagship idea, not a generic one
- "founded" and "size" must ALWAYS be returned as the actual JSON value null, or a plain string
  (e.g. "1994"), never as a number, never as the word "null" written as a string, never as a sentence
  like "not explicitly stated" or "unknown"

IMPORTANT on extraction bias: if a fact like founding year, employee count, headquarters, or revenue
appears ANYWHERE in the provided content — including in an external search snippet, even a partial or
imprecise mention — extract and report it. Do NOT default to null just because the fact isn't on the
company's own official page; search-result snippets (news articles, business directories, financial
profiles) are valid sources too. Only return null if the fact is genuinely absent from EVERY piece of
provided content. When multiple different values appear across sources for the same fact (e.g. different
founding years), pick the one from the most authoritative-looking source (an official filing, a major
financial database, a well-known business news outlet) over a casual blog or forum mention, and report
only that single value — never average or combine conflicting numbers, and never invent a value that
doesn't appear anywhere in the text.

CONSISTENCY CHECK: if you write a company_snapshot stat mentioning years in business/operation/experience
(e.g. "30+ Years"), and you would otherwise leave "founded" as null, instead calculate an approximate
founding year by working backward from that stat and the current year, and report that calculated year in
"founded" rather than leaving it null. Your own extracted facts should never contradict each other."""

def _build_prompt(company_name: str, scraped_text: str) -> str:
    return f"""Analyze the following content for the company "{company_name}" and extract structured,
presentation-ready data for a sales pitch deck.

SOURCE CONTENT:
{scraped_text}

Return a JSON object with EXACTLY this structure (no extra fields, no markdown):
{{
  "about": {{
    "summary": "3-5 sentence company summary with concrete specifics (what they do, who they serve, scale)",
    "industry": "primary industry/sector, or null if not clearly determinable",
    "founded": "founding year AS A STRING, e.g. '1994' — check ALL provided content including external search snippets, and back-calculate from any 'X years in business' stat, before returning null",
    "size": "employee count range AS A STRING, e.g. '500-1000', or the actual JSON null if genuinely not found — never the word null as a string, never a sentence"
  }},
  "company_snapshot": [
    {{"label": "short bold stat, e.g. '19+ Years' or '200,000+'", "caption": "5-10 word caption explaining the stat"}}
  ],
  "products": [
    {{"name": "product/brand name", "description": "1 full sentence explaining what this product actually does and who it's for — not just a name"}}
  ],
  "services": [
    {{"name": "service name", "description": "1 full sentence explaining what this service actually does for the client — not just a name"}}
  ],
  "contact": {{
    "email": "email address or null",
    "phone": "phone number or null",
    "address": "office address or null",
    "social_links": ["list of social media URLs"]
  }},
  "news": [
    {{"title": "news headline", "date": "date string or null", "summary": "1-2 sentence summary"}}
  ],
  "llm_analysis": {{
    "pain_points": [
      "A full 1-2 sentence explanation of a specific operational challenge, written like something a consultant would say in a pitch meeting, NOT a short keyword phrase"
    ],
    "growth_signals": ["list of signals that suggest the company is growing or expanding"],
    "tech_stack_hints": ["list of technologies, tools, or platforms mentioned or implied"],
    "summary": "3-5 sentence strategic summary: what the company does, where it is heading, and what it might need"
  }},
  "recommended_services": [
    {{
      "service": "short 3-5 word solution name",
      "reason": "1-2 full sentences describing EXACTLY what this solution would do for this specific company's operations",
      "priority": "high or medium or low"
    }}
  ],
  "spotlight_use_case": {{
    "title": "name of ONE flagship AI use case, the single most compelling idea for this company",
    "stages": [
      {{"stage": "short stage name, e.g. 'Ingest'", "description": "1 sentence describing this stage specific to this company"}},
      {{"stage": "e.g. 'Predict' or 'Analyze'", "description": "1 sentence"}},
      {{"stage": "e.g. 'Alert' or 'Act'", "description": "1 sentence"}},
      {{"stage": "e.g. 'Report'", "description": "1 sentence"}}
    ],
    "estimated_outcomes": ["3-4 short outcome phrases"]
  }}
}}

Rules:
- Return ONLY the JSON object, nothing else
- "founded" and "size" must be either a real string value or the actual JSON null — never the literal
  text "null", never "not explicitly stated", never "unknown" written as a string
- Before writing null for "founded", check company_snapshot for any "X years" stat and back-calculate the
  founding year from it if present — do not leave founded null while also stating years of experience
- Before writing null for "founded" or "size" more generally, re-scan the ENTIRE source content one more
  time (including every external search snippet section) — these facts are often buried in a news article,
  business directory listing, or financial profile snippet rather than the company's own homepage
- company_snapshot: include 4-6 concrete, quotable facts if the source supports them. If genuinely not
  found, return an empty array rather than inventing numbers.
- products / services: EVERY item must have both a "name" AND a "description" — never return a bare
  string, and never leave "description" empty. If the source content doesn't say what a product/service
  actually does, write the most reasonable one-sentence description you can infer from context (e.g. from
  the product name, the industry, or surrounding text) rather than omitting the description.
- pain_points: 3-5 items, each a REAL explanatory sentence or two — not a keyword phrase.
- recommended_services: 3-5 items, each "reason" a full descriptive sentence or two, specific to this
  company's actual operations.
- spotlight_use_case: pick the SINGLE most compelling recommended_services idea and expand it into an
  operational pipeline (typically 3-5 stages) with realistic estimated outcomes. If there isn't enough
  information to build a credible spotlight, return null for this field.
- news: include up to 5 recent items max
- Use EVERY relevant detail available in the source content — favor specific facts and named details
  over vague generalities throughout"""


def _to_str_or_none(value) -> str | None:
    """Safely coerce a value to a string, handling Groq occasionally
    returning numbers instead of strings for fields like 'founded' or
    'size'. Also treats the literal strings 'null', 'none', 'n/a',
    'not explicitly stated', 'not stated', 'unknown' (case-insensitive)
    as None, since Groq sometimes writes these instead of using real
    JSON null. Returns None if the value is missing/null/one of these."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ("null", "none", "n/a", "na", "not explicitly stated",
                         "not stated", "unknown", ""):
        return None
    return text


def _parse_product_or_service_list(items: list) -> list[ProductOrService]:
    """Parses products/services into ProductOrService(name, description)
    objects. Handles Groq occasionally returning a bare string instead of
    the requested {name, description} object — in that case the string
    becomes the name and description is left blank rather than the whole
    item being dropped."""
    parsed = []
    for item in items:
        if isinstance(item, dict):
            parsed.append(ProductOrService(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
            ))
        else:
            parsed.append(ProductOrService(name=str(item), description=""))
    return parsed


def _parse_response(company_name: str, website_url: str, raw: str) -> CompanyResearch:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    data = json.loads(clean)

    about_data = data.get("about", {})
    about = About(
        summary=about_data.get("summary", "") or "",
        industry=about_data.get("industry") or "Unknown",
        founded=_to_str_or_none(about_data.get("founded")),
        size=_to_str_or_none(about_data.get("size")),
    )

    company_snapshot = [
        SnapshotStat(label=str(s.get("label", "")), caption=str(s.get("caption", "")))
        for s in data.get("company_snapshot", [])
    ]

    contact_data = data.get("contact", {})
    contact = Contact(
        email=_to_str_or_none(contact_data.get("email")),
        phone=_to_str_or_none(contact_data.get("phone")),
        address=_to_str_or_none(contact_data.get("address")),
        social_links=contact_data.get("social_links", []),
    )

    news = [
        NewsItem(
            title=n.get("title", ""),
            date=_to_str_or_none(n.get("date")),
            summary=n.get("summary", ""),
        )
        for n in data.get("news", [])
    ]

    analysis_data = data.get("llm_analysis", {})
    llm_analysis = LLMAnalysis(
        pain_points=[str(p) for p in analysis_data.get("pain_points", [])],
        growth_signals=[str(g) for g in analysis_data.get("growth_signals", [])],
        tech_stack_hints=[str(t) for t in analysis_data.get("tech_stack_hints", [])],
        summary=analysis_data.get("summary", ""),
    )

    recommended = [
        RecommendedService(
            service=str(r.get("service", "")),
            reason=str(r.get("reason", "")),
            priority=Priority(r.get("priority", "medium")),
        )
        for r in data.get("recommended_services", [])
    ]

    spotlight_data = data.get("spotlight_use_case")
    spotlight_use_case = None
    if spotlight_data:
        stages = [
            SpotlightStage(stage=str(s.get("stage", "")), description=str(s.get("description", "")))
            for s in spotlight_data.get("stages", [])
        ]
        spotlight_use_case = SpotlightUseCase(
            title=str(spotlight_data.get("title", "")),
            stages=stages,
            estimated_outcomes=[str(o) for o in spotlight_data.get("estimated_outcomes", [])],
        )

    return CompanyResearch(
        company_name=company_name,
        website_url=website_url,
        scraped_at=datetime.now(timezone.utc),
        about=about,
        company_snapshot=company_snapshot,
        products=_parse_product_or_service_list(data.get("products", [])),
        services=_parse_product_or_service_list(data.get("services", [])),
        contact=contact,
        news=news,
        llm_analysis=llm_analysis,
        recommended_services=recommended,
        spotlight_use_case=spotlight_use_case,
    )


def _build_source_text(company_name: str, scraped_site: ScrapedSite) -> str:
    """Build the source text sent to Groq for analysis (site content +
    external context, trimmed to the 14000-char limit).

    Pages are reordered before concatenation so the highest-value pages
    (contact, about, home) always appear FIRST in the text — this means
    if the total content exceeds the 14000-char limit and something has
    to be cut, it's the lower-priority pages (blog posts, terms of use,
    generic "other" pages) that get trimmed, not the contact page where
    email/phone/address actually live. Without this, page order was
    whatever the crawler happened to visit first, and a contact page
    visited last (common, since it's often a footer link) could get cut
    entirely on content-heavy sites.

    Extracted as its own function so callers (like graph_nodes.py's
    fact_check_node) can build this ONCE and pass it into
    analyze_company(), avoiding a duplicate external search call if they
    also need the raw source text for verification purposes.
    """
    # Priority order: contact/about/home pages first (most likely to
    # contain email, phone, address, founding info), then everything
    # else in whatever order the crawler found it.
    PRIORITY_PAGE_TYPES = ["contact", "about", "home"]

    def _page_priority(page) -> int:
        try:
            return PRIORITY_PAGE_TYPES.index(page.page_type)
        except ValueError:
            return len(PRIORITY_PAGE_TYPES)  # everything else sorts after

    ordered_pages = sorted(
        [p for p in scraped_site.pages if p.success and p.text],
        key=_page_priority,
    )

    parts = [
        f"=== {p.page_type.upper()} PAGE ({p.url}) ===\n{p.text}"
        for p in ordered_pages
    ]
    scraped_text = "\n\n".join(parts)

    own_domain = urlparse(scraped_site.base_url).netloc.lower()
    if own_domain.startswith("www."):
        own_domain = own_domain[4:]

    external_context = ""
    try:
        external_context = get_external_context(company_name, own_domain)
    except Exception as e:
        logger.warning(f"External context search failed (continuing without it): {e}")

    if external_context:
        scraped_text = f"{scraped_text}\n\n{external_context}".strip()

    if len(scraped_text) > 14000:
        scraped_text = scraped_text[:14000] + "\n[content trimmed]"

    return scraped_text


def analyze_company(
    company_name: str,
    scraped_site: ScrapedSite,
    source_text: str | None = None,
) -> CompanyResearch:
    """
    Send scraped website content + external context to Groq and return
    a structured, presentation-ready CompanyResearch object.

    Args:
        company_name:  Company name e.g. "KFintech"
        scraped_site:  ScrapedSite returned by scraper.py (full-site crawl)
        source_text:   Optional pre-built source text (from _build_source_text()).
                        If provided, this is used directly instead of rebuilding
                        it internally — avoids a duplicate external search call
                        when the caller (e.g. graph_nodes.py) already built it
                        for its own purposes (like fact-checking afterward).
    """
    if source_text is None:
        source_text = _build_source_text(company_name, scraped_site)

    if not source_text.strip():
        raise ValueError(f"No scraped content or external signals available for {company_name}")

    logger.info(f"Sending {len(source_text)} chars to Groq for: {company_name}")

    client = _get_client()

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(company_name, source_text)},
        ],
        temperature=0.3,
        max_tokens=4500,
    )

    raw = response.choices[0].message.content
    logger.info("Groq response received, parsing...")

    try:
        result = _parse_response(company_name, scraped_site.base_url, raw)
        logger.info(f"Analysis complete for: {company_name}")
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse Groq response: {e}")
        logger.error(f"Raw response was:\n{raw}")
        raise


if __name__ == "__main__":
    from dev1_research.search import find_company_website
    from dev1_research.scraper import scrape_company_website

    company = "KFintech"

    print(f"\nRunning full pipeline for: {company}")
    print("=" * 55)

    print("\n[1/3] Searching for website...")
    url = find_company_website(company)
    print(f"  Found: {url}")

    print("\n[2/3] Scraping website (full site crawl)...")
    site = scrape_company_website(url)
    print(f"  Pages scraped: {[p.page_type for p in site.pages if p.success]}")

    print("\n[3/3] Analyzing with Groq (site + external context)...")
    result = analyze_company(company, site)

    print("\n✅ CompanyResearch output:")
    print(result.model_dump_json(indent=2))