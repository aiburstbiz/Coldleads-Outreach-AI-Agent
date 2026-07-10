"""
dev1_research/graph_nodes.py

LangGraph nodes for Dev1's research pipeline, with an evaluator/critic
node after EVERY major step (search, scrape, analyze), a Level-2
fact-checking critic that verifies extracted facts against the original
source content before accepting the final result, and a final logo-fetch
step that populates a validated company logo URL (Hunter.io, no API key).

Two levels of critic:
    Level 1 (evaluate_analyze_node): "Is the output complete enough?"
        - split into BLOCKING checks (pain_points, industry, summary,
          company_snapshot — Groq-controllable, retrying genuinely helps)
          and NON-BLOCKING checks (contact info, news — gated by external
          search rate-limiting, retrying just burns quota for nothing)
    Level 2 (fact_check_node): "Is the output actually correct?"
        - re-sends source content + extracted facts to Groq
        - asks it to verify each fact-bearing field against the source
        - unverified/hallucinated facts get nulled out rather than
          risking a fabricated stat/contact detail reaching a client deck

Only fact-bearing fields are verified (founded, size, contact info,
company_snapshot, news, products, services, growth_signals,
tech_stack_hints). Analytical/inferred fields (pain_points,
recommended_services, spotlight_use_case) are NOT re-verified against
the source, since they are explicitly reasoned conclusions, not direct
extractions - flagging them as "not in source" would be a false positive
by design.

Flow:
    search -> evaluate_search -> [retry search | continue | fail]
    scrape -> evaluate_scrape -> [retry scrape | continue | fail]
    analyze -> evaluate_analyze -> [retry analyze | continue | accept_anyway]
    fact_check -> logo -> END   (logo runs once, after fact-check is done)

Usage (standalone test, no LangGraph needed):
    python graph_nodes.py "KFintech"

Usage (as part of the full LangGraph workflow, once wired with Dev2's
nodes in graph/workflow.py):
    from dev1_research.graph_nodes import build_dev1_subgraph
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, TypedDict

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("graph_nodes")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dev1_research.search import find_company_website
from dev1_research.scraper import scrape_company_website, ScrapedSite


# ---------------------------------------------------------------------------
# Shared state that flows through every node
# ---------------------------------------------------------------------------

class ResearchState(TypedDict, total=False):
    company_name: str
    website_url: Optional[str]
    scraped_site: Optional[dict]  # plain dict form (ScrapedSite.to_dict())
    source_text: Optional[str]    # the exact text (site + external context) sent to Groq for analysis - needed by fact_check_node to verify claims
    company_research: Optional[dict]  # CompanyResearch.model_dump(mode="json")

    # Tracking / control fields
    current_step: str
    error: Optional[str]
    search_attempts: int
    scrape_attempts: int
    analyze_attempts: int
    quality_notes: list[str]
    fact_check_notes: list[str]  # what the Level-2 critic found/corrected


MAX_RETRIES_PER_STEP = 2


def _init_state(company_name: str) -> ResearchState:
    return ResearchState(
        company_name=company_name,
        website_url=None,
        scraped_site=None,
        source_text=None,
        company_research=None,
        current_step="start",
        error=None,
        search_attempts=0,
        scrape_attempts=0,
        analyze_attempts=0,
        quality_notes=[],
        fact_check_notes=[],
    )


# ---------------------------------------------------------------------------
# STEP 1: search + evaluator
# ---------------------------------------------------------------------------

def search_node(state: ResearchState) -> ResearchState:
    state["search_attempts"] = state.get("search_attempts", 0) + 1
    company_name = state["company_name"]

    try:
        url = find_company_website(company_name)
        state["website_url"] = url
        state["error"] = None
        logger.info("[SEARCH attempt %d] %s -> %s", state["search_attempts"], company_name, url)
    except Exception as e:
        state["website_url"] = None
        state["error"] = f"search_exception: {e}"
        logger.error("[SEARCH attempt %d] Exception: %s", state["search_attempts"], e)

    return state


def evaluate_search_node(state: ResearchState) -> ResearchState:
    notes = state.setdefault("quality_notes", [])

    if state.get("error"):
        notes.append(f"search failed with exception: {state['error']}")
        state["current_step"] = "search_error"
        return state

    if not state.get("website_url"):
        notes.append("search found no confident website match")
        state["current_step"] = "search_not_found"
        return state

    notes.append(f"search OK: {state['website_url']}")
    state["current_step"] = "search_ok"
    return state


def route_after_search(state: ResearchState) -> str:
    if state["current_step"] == "search_ok":
        return "continue"
    if state["search_attempts"] < MAX_RETRIES_PER_STEP + 1:
        logger.warning("Retrying search (attempt %d)...", state["search_attempts"] + 1)
        return "retry"
    logger.error("Search failed after %d attempts - giving up on %s", state["search_attempts"], state["company_name"])
    return "fail"


# ---------------------------------------------------------------------------
# STEP 2: scrape + evaluator
# ---------------------------------------------------------------------------

def scrape_node(state: ResearchState) -> ResearchState:
    state["scrape_attempts"] = state.get("scrape_attempts", 0) + 1
    website_url = state["website_url"]

    try:
        site = scrape_company_website(website_url)
        state["scraped_site"] = site.to_dict()
        state["error"] = None
        ok_pages = [p["page_type"] for p in state["scraped_site"]["pages"] if p["success"]]
        logger.info("[SCRAPE attempt %d] OK pages: %s", state["scrape_attempts"], ok_pages)
    except Exception as e:
        state["scraped_site"] = None
        state["error"] = f"scrape_exception: {e}"
        logger.error("[SCRAPE attempt %d] Exception: %s", state["scrape_attempts"], e)

    return state


def evaluate_scrape_node(state: ResearchState) -> ResearchState:
    notes = state.setdefault("quality_notes", [])

    if state.get("error"):
        notes.append(f"scrape failed with exception: {state['error']}")
        state["current_step"] = "scrape_error"
        return state

    site_dict = state.get("scraped_site")
    ok_pages = [p for p in (site_dict.get("pages", []) if site_dict else []) if p.get("success")]

    if not ok_pages:
        notes.append("scrape got 0 successful pages (site may be bot-blocked) - "
                      "will rely on external search context in analyze step")
        state["current_step"] = "scrape_thin"
    else:
        notes.append(f"scrape OK: {len(ok_pages)} pages fetched")
        state["current_step"] = "scrape_ok"

    return state


def route_after_scrape(state: ResearchState) -> str:
    if state["current_step"] in ("scrape_ok", "scrape_thin"):
        return "continue"
    if state["scrape_attempts"] < MAX_RETRIES_PER_STEP + 1:
        logger.warning("Retrying scrape (attempt %d)...", state["scrape_attempts"] + 1)
        return "retry"
    logger.error("Scrape failed after %d attempts - giving up", state["scrape_attempts"])
    return "fail"


# ---------------------------------------------------------------------------
# STEP 3: analyze + Level-1 evaluator (completeness)
# ---------------------------------------------------------------------------

def analyze_node(state: ResearchState) -> ResearchState:
    state["analyze_attempts"] = state.get("analyze_attempts", 0) + 1
    company_name = state["company_name"]
    site_dict = state.get("scraped_site")

    try:
        from dev1_research.analyzer import analyze_company, _build_source_text
        site = ScrapedSite.from_dict(site_dict) if site_dict else ScrapedSite(base_url="")

        # Build and stash the exact source text used for analysis, so
        # fact_check_node can verify claims against the SAME content
        # Groq actually saw (not re-fetch it, which could differ run to run)
        source_text = _build_source_text(company_name, site)
        state["source_text"] = source_text

        result = analyze_company(company_name, site, source_text=source_text)
        state["company_research"] = result.model_dump(mode="json")
        state["error"] = None
        logger.info("[ANALYZE attempt %d] Industry: %s",
                    state["analyze_attempts"], state["company_research"]["about"]["industry"])
    except Exception as e:
        state["company_research"] = None
        state["error"] = f"analyze_exception: {e}"
        logger.error("[ANALYZE attempt %d] Exception: %s", state["analyze_attempts"], e)

    return state


def evaluate_analyze_node(state: ResearchState) -> ResearchState:
    """Level 1 critic: 'Is the output complete enough to use?'

    Split into two categories, since they have different root causes and
    different responses to retrying:
      - BLOCKING (pain_points, industry, summary, company_snapshot): these
        come from Groq's own reasoning on the content it was given.
        Retrying genuinely helps, since Groq can do better on a second pass.
      - NON-BLOCKING (contact info, news): these come from external search
        results, and are missing mainly due to DuckDuckGo rate-limiting,
        not Groq quality. Retrying doesn't fix a rate limit — it just
        burns extra Groq calls for the same result. Still logged as a
        warning so the gap is visible, but no longer forces a retry loop.
    """
    notes = state.setdefault("quality_notes", [])

    if state.get("error"):
        notes.append(f"analyze failed with exception: {state['error']}")
        state["current_step"] = "analyze_error"
        return state

    cr = state.get("company_research") or {}
    about = cr.get("about", {})
    llm = cr.get("llm_analysis", {})
    contact = cr.get("contact", {})

    # BLOCKING — Groq reasoning gaps, retrying genuinely helps
    blocking_issues = []
    if not llm.get("pain_points"):
        blocking_issues.append("no pain points found")
    if (about.get("industry") or "Unknown") == "Unknown":
        blocking_issues.append("industry unknown")
    if len(llm.get("summary", "")) < 40:
        blocking_issues.append("summary too short")
    if not cr.get("company_snapshot"):
        blocking_issues.append("no company snapshot stats")

    # NON-BLOCKING — external search gaps, retrying just burns quota
    warnings = []
    if not any([contact.get("email"), contact.get("phone"), contact.get("address")]):
        warnings.append("no contact info found (likely search rate-limiting, not a Groq issue)")
    if not cr.get("news"):
        warnings.append("no news items found (likely search rate-limiting, not a Groq issue)")

    if warnings:
        notes.append(f"non-blocking data gaps: {', '.join(warnings)}")

    if blocking_issues:
        notes.append(f"analysis quality issues: {', '.join(blocking_issues)}")
        state["current_step"] = "analyze_thin"
    else:
        notes.append("analysis OK (contact/news gaps, if any, are non-blocking)")
        state["current_step"] = "analyze_ok"

    return state


def route_after_analyze(state: ResearchState) -> str:
    if state["current_step"] == "analyze_ok":
        return "continue"
    if state["analyze_attempts"] < MAX_RETRIES_PER_STEP + 1:
        logger.warning("Retrying analyze (attempt %d)...", state["analyze_attempts"] + 1)
        return "retry"
    logger.warning(
        "Analyze still thin after %d attempts - proceeding to fact-check with best available result for %s",
        state["analyze_attempts"], state["company_name"],
    )
    return "accept_anyway"


# ---------------------------------------------------------------------------
# STEP 4: Level-2 critic - fact verification against source content
# ---------------------------------------------------------------------------

FACT_CHECK_PROMPT_TEMPLATE = """You are a fact-checking critic. You will be given SOURCE CONTENT (scraped
website text and external search snippets) and a set of EXTRACTED FACTS that were pulled from that content
by another AI. Your job is to verify each fact actually appears in (or is directly, unambiguously implied
by) the source content — not to judge whether it seems plausible.

SOURCE CONTENT:
{source_text}

EXTRACTED FACTS TO VERIFY:
{facts_json}

For EACH fact listed, return "verified" if it clearly appears in the source content (exact match or very
close paraphrase), "unverified" if it does NOT appear anywhere in the source content, or cannot be
confirmed. Do not mark something "unverified" just because it seems surprising — only mark it unverified if
you genuinely cannot find it anywhere in the provided source content.

Return ONLY a JSON object with this exact structure, no markdown, no explanation:
{{
  "founded": "verified" or "unverified",
  "size": "verified" or "unverified",
  "email": "verified" or "unverified",
  "phone": "verified" or "unverified",
  "address": "verified" or "unverified",
  "snapshot_stats": ["verified" or "unverified", ...],
  "news_items": ["verified" or "unverified", ...],
  "products": ["verified" or "unverified", ...],
  "services": ["verified" or "unverified", ...],
  "growth_signals": ["verified" or "unverified", ...],
  "tech_stack_hints": ["verified" or "unverified", ...]
}}

Every array field above must have the SAME LENGTH and SAME ORDER as the corresponding facts listed below,
one verdict per item."""


def _build_facts_to_verify(cr: dict) -> dict:
    """Pull out just the fact-bearing fields worth verifying — not the
    analytical/inferred fields like pain_points or recommended_services,
    which are reasoned conclusions rather than direct extractions."""
    about = cr.get("about", {})
    contact = cr.get("contact", {})
    llm = cr.get("llm_analysis", {})
    return {
        "founded": about.get("founded"),
        "size": about.get("size"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "address": contact.get("address"),
        "snapshot_stats": [
            f"{s.get('label', '')}: {s.get('caption', '')}"
            for s in cr.get("company_snapshot", [])
        ],
        "news_items": [n.get("title", "") for n in cr.get("news", [])],
        "products": cr.get("products", []),
        "services": cr.get("services", []),
        "growth_signals": llm.get("growth_signals", []),
        "tech_stack_hints": llm.get("tech_stack_hints", []),
    }


def fact_check_node(state: ResearchState) -> ResearchState:
    """Level 2 critic: 'Is the output actually correct and grounded in
    real sources?' Re-sends the source content + extracted facts to Groq,
    asks it to verify each one, and removes/nulls out anything that
    couldn't be confirmed rather than risking a fabricated detail
    reaching a client deck. Runs once, after analyze is done retrying.

    Covers ALL fact-bearing fields: founded, size, contact info,
    company_snapshot, news, products, services, growth_signals,
    tech_stack_hints. Does NOT cover pain_points, recommended_services,
    or spotlight_use_case — those are analytical/inferred content, not
    direct extractions, so "must appear in source" doesn't apply to them
    the same way (that would need a different kind of relevance check,
    not a fact-check).

    Note: runs identically regardless of whether the preceding analyze
    step was accepted after 1 attempt or 3 (analyze_ok vs accept_anyway)
    — it just verifies whatever ended up in company_research at this
    point, with no dependency on retry count or which fields triggered
    a retry."""
    notes = state.setdefault("fact_check_notes", [])

    cr = state.get("company_research")
    source_text = state.get("source_text")

    if not cr:
        notes.append("skipped: no company_research to fact-check")
        return state

    if not source_text or not source_text.strip():
        notes.append("skipped: no source_text available to verify against")
        return state

    facts = _build_facts_to_verify(cr)

    has_any_fact = any([
        facts["founded"], facts["size"], facts["email"], facts["phone"],
        facts["address"], facts["snapshot_stats"], facts["news_items"],
        facts["products"], facts["services"], facts["growth_signals"],
        facts["tech_stack_hints"],
    ])
    if not has_any_fact:
        notes.append("skipped: no fact-bearing fields were extracted to verify")
        return state

    try:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        client = Groq(api_key=api_key)
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        trimmed_source = source_text[:14000] if len(source_text) > 14000 else source_text

        prompt = FACT_CHECK_PROMPT_TEMPLATE.format(
            source_text=trimmed_source,
            facts_json=json.dumps(facts, indent=2),
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise fact-checking assistant. Return ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        verdicts = json.loads(raw)

    except Exception as e:
        notes.append(f"fact-check call failed, skipping verification (keeping facts as-is): {e}")
        logger.warning("Fact-check node failed: %s", e)
        return state

    corrections = []
    about = cr.setdefault("about", {})
    contact = cr.setdefault("contact", {})
    llm = cr.setdefault("llm_analysis", {})

    if facts["founded"] and verdicts.get("founded") != "verified":
        corrections.append(f"founded ('{facts['founded']}') -> unverified, nulled")
        about["founded"] = None

    if facts["size"] and verdicts.get("size") != "verified":
        corrections.append(f"size ('{facts['size']}') -> unverified, nulled")
        about["size"] = None

    if facts["email"] and verdicts.get("email") != "verified":
        corrections.append(f"email ('{facts['email']}') -> unverified, nulled")
        contact["email"] = None

    if facts["phone"] and verdicts.get("phone") != "verified":
        corrections.append(f"phone ('{facts['phone']}') -> unverified, nulled")
        contact["phone"] = None

    if facts["address"] and verdicts.get("address") != "verified":
        corrections.append(f"address ('{facts['address']}') -> unverified, nulled")
        contact["address"] = None

    def _filter_list(field_key: str, cr_list_getter, cr_list_setter, label_fn=str):
        verdict_list = verdicts.get(field_key, [])
        original_list = cr_list_getter()
        if not verdict_list or len(verdict_list) != len(original_list):
            return
        kept = []
        for item, verdict in zip(original_list, verdict_list):
            if verdict == "verified":
                kept.append(item)
            else:
                corrections.append(f"{field_key} '{label_fn(item)}' -> unverified, removed")
        cr_list_setter(kept)

    _filter_list(
        "snapshot_stats",
        lambda: cr.get("company_snapshot", []),
        lambda kept: cr.__setitem__("company_snapshot", kept),
        label_fn=lambda s: s.get("label", ""),
    )
    _filter_list(
        "news_items",
        lambda: cr.get("news", []),
        lambda kept: cr.__setitem__("news", kept),
        label_fn=lambda n: n.get("title", ""),
    )
    _filter_list(
        "products",
        lambda: cr.get("products", []),
        lambda kept: cr.__setitem__("products", kept),
    )
    _filter_list(
        "services",
        lambda: cr.get("services", []),
        lambda kept: cr.__setitem__("services", kept),
    )
    _filter_list(
        "growth_signals",
        lambda: llm.get("growth_signals", []),
        lambda kept: llm.__setitem__("growth_signals", kept),
    )
    _filter_list(
        "tech_stack_hints",
        lambda: llm.get("tech_stack_hints", []),
        lambda kept: llm.__setitem__("tech_stack_hints", kept),
    )

    if corrections:
        notes.append(f"fact-check corrections applied: {'; '.join(corrections)}")
        logger.warning("[FACT-CHECK] Corrections applied: %s", corrections)
    else:
        notes.append("fact-check OK: all extracted facts verified against source")
        logger.info("[FACT-CHECK] All facts verified, no corrections needed")

    state["company_research"] = cr
    return state


# ---------------------------------------------------------------------------
# STEP 5: fetch + validate company logo URL (Hunter.io, no API key needed)
# ---------------------------------------------------------------------------

def logo_node(state: ResearchState) -> ResearchState:
    """Populates company_research['logo_url'] using Hunter.io's free logo
    API (https://logos.hunter.io/{domain}). Runs once, after fact_check,
    since it's a cheap single HEAD request with no need for retries.
    Leaves logo_url as None if the domain can't be resolved or Hunter
    doesn't have a logo indexed for it — Dev2's PPT code is expected to
    fall back to a placeholder or skip the logo element in that case."""
    cr = state.get("company_research")
    if not cr:
        return state

    from dev1_research.logo import get_logo_url

    website_url = cr.get("website_url", "")
    cr["logo_url"] = get_logo_url(website_url)
    state["company_research"] = cr

    logger.info("[LOGO] %s -> %s", website_url, cr["logo_url"] or "(none found)")
    return state


# ---------------------------------------------------------------------------
# Build the LangGraph subgraph
# ---------------------------------------------------------------------------

def build_dev1_subgraph():
    """Builds and compiles the Dev1 portion of the graph:
    search -> evaluate -> (retry|continue|fail)
    scrape -> evaluate -> (retry|continue|fail)
    analyze -> evaluate -> (retry|continue|accept_anyway)
    fact_check -> logo -> END   (Level-2 critic, then logo fetch, runs once each)
    """
    from langgraph.graph import StateGraph, END

    graph = StateGraph(ResearchState)

    graph.add_node("search", search_node)
    graph.add_node("evaluate_search", evaluate_search_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("evaluate_scrape", evaluate_scrape_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("evaluate_analyze", evaluate_analyze_node)
    graph.add_node("fact_check", fact_check_node)
    graph.add_node("logo", logo_node)

    graph.set_entry_point("search")

    graph.add_edge("search", "evaluate_search")
    graph.add_conditional_edges(
        "evaluate_search", route_after_search,
        {"retry": "search", "continue": "scrape", "fail": END},
    )

    graph.add_edge("scrape", "evaluate_scrape")
    graph.add_conditional_edges(
        "evaluate_scrape", route_after_scrape,
        {"retry": "scrape", "continue": "analyze", "fail": END},
    )

    graph.add_edge("analyze", "evaluate_analyze")
    graph.add_conditional_edges(
        "evaluate_analyze", route_after_analyze,
        {"retry": "analyze", "continue": "fact_check", "accept_anyway": "fact_check"},
    )

    graph.add_edge("fact_check", "logo")
    graph.add_edge("logo", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    from pathlib import Path

    company = sys.argv[1] if len(sys.argv) > 1 else "KFintech"

    app = build_dev1_subgraph()
    initial_state = _init_state(company)

    print(f"\nRunning Dev1 subgraph (with Level-1 + Level-2 critics + logo) for: {company}")
    print("=" * 60)

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("FINAL STATE SUMMARY")
    print("=" * 60)
    print(f"Final step        : {final_state['current_step']}")
    print(f"Search attempts    : {final_state['search_attempts']}")
    print(f"Scrape attempts    : {final_state['scrape_attempts']}")
    print(f"Analyze attempts   : {final_state['analyze_attempts']}")
    print(f"\nLevel-1 quality notes:")
    for note in final_state.get("quality_notes", []):
        print(f"  - {note}")
    print(f"\nLevel-2 fact-check notes:")
    for note in final_state.get("fact_check_notes", []):
        print(f"  - {note}")

    if final_state.get("company_research"):
        print(f"\nLogo URL: {final_state['company_research'].get('logo_url')}")
        print(f"\nRecommended services:")
        print(_json.dumps(final_state["company_research"].get("recommended_services", []), indent=2))

        out_dir = Path("graph_test_output")
        out_dir.mkdir(exist_ok=True)
        fname = out_dir / f"{company.replace(' ', '_').lower()}.json"
        with open(fname, "w", encoding="utf-8") as f:
            _json.dump(final_state["company_research"], f, indent=2, default=str)
        print(f"\nFull result saved to: {fname}")
    else:
        print("\nNo research result produced.")