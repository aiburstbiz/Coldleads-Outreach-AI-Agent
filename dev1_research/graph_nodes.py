"""
dev1_research/graph_nodes.py

LangGraph nodes for Dev1's research pipeline, with an evaluator/critic
node after EVERY major step (search, scrape, analyze). Each evaluator
checks whether that step's output is good enough to continue, and can
route back to retry the same step (up to a max) instead of blindly
accepting weak results or failing outright.

v3: state now stores scraped_site as a plain dict (via ScrapedSite.to_dict())
instead of the raw dataclass object, and company_research uses
model_dump(mode="json") instead of model_dump() so the Priority enum
serializes as a plain string. This avoids the "unregistered type"
checkpoint warnings LangGraph's SQLite checkpointer raised for
ScrapedPage/ScrapedSite/Priority, which it flagged as becoming a hard
error in a future version.

Flow:
    search -> evaluate_search -> [retry search | continue | fail]
    scrape -> evaluate_scrape -> [retry scrape | continue | fail]
    analyze -> evaluate_analyze -> [retry analyze | continue | fail]

Usage (standalone test, no LangGraph needed):
    python graph_nodes.py "KFintech"

Usage (as part of the full LangGraph workflow, once wired with Dev2's
nodes in graph/workflow.py):
    from dev1_research.graph_nodes import build_dev1_subgraph
"""

from __future__ import annotations

import logging
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
    scraped_site: Optional[dict]  # plain dict form (ScrapedSite.to_dict()), NOT the raw object -
                                    # keeps LangGraph's checkpointer happy (no custom type registration needed)
    company_research: Optional[dict]  # CompanyResearch.model_dump(mode="json")

    # Tracking / control fields
    current_step: str
    error: Optional[str]
    search_attempts: int
    scrape_attempts: int
    analyze_attempts: int
    quality_notes: list[str]  # human-readable evaluator notes, for debugging


MAX_RETRIES_PER_STEP = 2  # retry up to 2 extra times (3 attempts total) before giving up


def _init_state(company_name: str) -> ResearchState:
    return ResearchState(
        company_name=company_name,
        website_url=None,
        scraped_site=None,
        company_research=None,
        current_step="start",
        error=None,
        search_attempts=0,
        scrape_attempts=0,
        analyze_attempts=0,
        quality_notes=[],
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
    """Quality check: did we get a confident, real website?"""
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
        # Store as a plain dict, not the raw ScrapedSite object - avoids
        # LangGraph checkpointer "unregistered type" serialization issues
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
    """Quality check: did we get any real content, or was everything blocked?

    NOTE: even 0 successful pages isn't necessarily fatal, since
    analyze_node's external search (news_search.py) can still produce a
    result. So this evaluator flags a WARNING rather than forcing a
    retry, unless scraping itself threw an exception.
    """
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
# STEP 3: analyze + evaluator
# ---------------------------------------------------------------------------

def analyze_node(state: ResearchState) -> ResearchState:
    state["analyze_attempts"] = state.get("analyze_attempts", 0) + 1
    company_name = state["company_name"]
    site_dict = state.get("scraped_site")

    try:
        from dev1_research.analyzer import analyze_company
        # Reconstruct the real ScrapedSite object only here, transiently -
        # analyze_company() needs its .all_text() / .base_url, but the
        # object itself never gets stored back into graph state.
        site = ScrapedSite.from_dict(site_dict) if site_dict else ScrapedSite(base_url="")
        result = analyze_company(company_name, site)
        # mode="json" converts the Priority enum (and datetime) to plain
        # strings, so nothing but built-in types end up in graph state
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
    """Quality check: is this analysis actually rich enough to pitch with?

    Checks a handful of concrete signals rather than just "did it not
    crash" - this is the evaluator most worth having, since a technically
    successful call can still return a thin, generic result.

    Also flags missing contact info and missing news items, not just
    pain points/industry/summary/snapshot - these previously slipped
    through as "analyze_ok" even when genuinely empty.
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

    issues = []
    if not llm.get("pain_points"):
        issues.append("no pain points found")
    if (about.get("industry") or "Unknown") == "Unknown":
        issues.append("industry unknown")
    if len(llm.get("summary", "")) < 40:
        issues.append("summary too short")
    if not cr.get("company_snapshot"):
        issues.append("no company snapshot stats")
    if not any([contact.get("email"), contact.get("phone"), contact.get("address")]):
        issues.append("no contact info found (email/phone/address all missing)")
    if not cr.get("news"):
        issues.append("no news items found")

    if issues:
        notes.append(f"analysis quality issues: {', '.join(issues)}")
        state["current_step"] = "analyze_thin"
    else:
        notes.append("analysis OK: rich result with pain points, industry, snapshot, contact, news")
        state["current_step"] = "analyze_ok"

    return state


def route_after_analyze(state: ResearchState) -> str:
    if state["current_step"] == "analyze_ok":
        return "continue"
    if state["analyze_attempts"] < MAX_RETRIES_PER_STEP + 1:
        logger.warning("Retrying analyze (attempt %d)...", state["analyze_attempts"] + 1)
        return "retry"
    logger.warning(
        "Analyze still thin after %d attempts - accepting best available result for %s",
        state["analyze_attempts"], state["company_name"],
    )
    return "accept_anyway"


# ---------------------------------------------------------------------------
# Build the LangGraph subgraph
# ---------------------------------------------------------------------------

def build_dev1_subgraph():
    """Builds and compiles the Dev1 portion of the graph:
    search -> evaluate -> (retry|continue|fail)
    scrape -> evaluate -> (retry|continue|fail)
    analyze -> evaluate -> (retry|continue|accept_anyway)

    Returns a compiled LangGraph app that can be run standalone, or
    imported and composed into the full graph/workflow.py with Dev2's
    nodes appended after this subgraph's END.
    """
    from langgraph.graph import StateGraph, END

    graph = StateGraph(ResearchState)

    graph.add_node("search", search_node)
    graph.add_node("evaluate_search", evaluate_search_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("evaluate_scrape", evaluate_scrape_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("evaluate_analyze", evaluate_analyze_node)

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
        {"retry": "analyze", "continue": END, "accept_anyway": END},
    )

    return graph.compile()


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from pathlib import Path

    company = sys.argv[1] if len(sys.argv) > 1 else "KFintech"

    app = build_dev1_subgraph()
    initial_state = _init_state(company)

    print(f"\nRunning Dev1 subgraph (with evaluators) for: {company}")
    print("=" * 60)

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("FINAL STATE SUMMARY")
    print("=" * 60)
    print(f"Final step        : {final_state['current_step']}")
    print(f"Search attempts    : {final_state['search_attempts']}")
    print(f"Scrape attempts    : {final_state['scrape_attempts']}")
    print(f"Analyze attempts   : {final_state['analyze_attempts']}")
    print(f"\nQuality notes (evaluator log):")
    for note in final_state.get("quality_notes", []):
        print(f"  - {note}")

    if final_state.get("company_research"):
        print(f"\nRecommended services:")
        print(json.dumps(final_state["company_research"].get("recommended_services", []), indent=2))

        out_dir = Path("graph_test_output")
        out_dir.mkdir(exist_ok=True)
        fname = out_dir / f"{company.replace(' ', '_').lower()}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(final_state["company_research"], f, indent=2, default=str)
        print(f"\nFull result saved to: {fname}")
    else:
        print("\nNo research result produced.")