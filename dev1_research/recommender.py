"""
Day 6 — Recommendation Engine

Wraps knowledge_base.py's keyword matches into the final `recommended_services`
shape defined in the JSON contract:

    { "service": "string", "reason": "string", "priority": "high | medium | low" }

Fully rule-based — no Gemini/API calls, no quota risk. Can run standalone
today while billing is being sorted out.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from knowledge_base import ServiceMatch, retrieve_relevant_services

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output model — matches the JSON contract's recommended_services field
# ---------------------------------------------------------------------------

class RecommendedService(BaseModel):
    service: str
    reason: str
    priority: str  # "high" | "medium" | "low"


# ---------------------------------------------------------------------------
# Priority assignment
# ---------------------------------------------------------------------------

def _assign_priority(score: float, max_score: float) -> str:
    """Convert a relative score into a priority tier.

    Relative to the top match in THIS company's result set, since raw scores
    aren't comparable across companies (different pain-point phrasing, etc.).
    """
    if max_score <= 0:
        return "low"
    ratio = score / max_score
    if ratio >= 0.6:
        return "high"
    elif ratio >= 0.3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Reason generation (rule-based, no LLM)
# ---------------------------------------------------------------------------

def _generate_reason(match: ServiceMatch) -> str:
    """Build a human-readable reason from matched terms.

    Prefers multi-word phrase matches (pain points / best_for entries) over
    single keywords, since they read more naturally in a sentence.
    """
    phrases = [t for t in match.matched_terms if " " in t]
    single_words = [t for t in match.matched_terms if " " not in t]

    if phrases:
        # Use up to 2 phrases, de-duplicated, most specific first (longest)
        top_phrases = sorted(set(phrases), key=len, reverse=True)[:2]
        joined = " and ".join(p[0].lower() + p[1:] for p in top_phrases)
        return f"Directly addresses {joined}."

    if single_words:
        top_words = sorted(set(single_words))[:3]
        return (
            f"Relevant based on matched signals: {', '.join(top_words)}."
        )

    # No matches at all (fallback case) — generic reason
    return f"{match.service.description}"


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def recommend_services(
    industry: str = "",
    pain_points: Optional[list[str]] = None,
    growth_signals: Optional[list[str]] = None,
    summary: str = "",
    products: Optional[list[str]] = None,
    services_offered: Optional[list[str]] = None,
    top_k: int = 3,
    kb_path: Optional[Path] = None,
) -> list[RecommendedService]:
    """Given a company's research profile fields, return the final
    recommended_services list ready to drop into the JSON contract."""
    matches = retrieve_relevant_services(
        industry=industry,
        pain_points=pain_points,
        growth_signals=growth_signals,
        summary=summary,
        products=products,
        services_offered=services_offered,
        top_k=top_k,
        kb_path=kb_path,
    )

    if not matches:
        logger.warning("No service matches found — returning empty recommendations")
        return []

    max_score = max(m.score for m in matches)

    recommendations = [
        RecommendedService(
            service=m.service.name,
            reason=_generate_reason(m),
            priority=_assign_priority(m.score, max_score),
        )
        for m in matches
    ]
    return recommendations


def recommend_from_company_research(company_research, top_k: int = 3) -> list[RecommendedService]:
    """Convenience wrapper: takes a CompanyResearch pydantic object
    (from shared/schema.py, as produced by analyzer.py) directly and
    returns the recommended_services list to attach to it."""
    about = company_research.about
    llm = company_research.llm_analysis
    return recommend_services(
        industry=about.industry or "",
        pain_points=llm.pain_points,
        growth_signals=llm.growth_signals,
        summary=f"{about.summary} {llm.summary}",
        products=company_research.products,
        services_offered=company_research.services,
        top_k=top_k,
    )


# ---------------------------------------------------------------------------
# Manual test (no Gemini / no network needed)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    print("=" * 60)
    print("Test 1: Manufacturing company with QC / audit pain points")
    print("=" * 60)
    recs = recommend_services(
        industry="Solar manufacturing",
        pain_points=[
            "Manual quality control checks slow down production",
            "Audit certificate processing is error-prone",
        ],
        growth_signals=["Scaling from 3.6GW to 10GW capacity"],
        summary="Premier Energies is scaling solar cell and module manufacturing rapidly.",
        top_k=3,
    )
    for r in recs:
        print(f"  [{r.priority.upper():6}] {r.service}")
        print(f"           {r.reason}")

    print()
    print("=" * 60)
    print("Test 2: B2B SaaS company with sales/lead gen pain points")
    print("=" * 60)
    recs = recommend_services(
        industry="B2B SaaS",
        pain_points=["Sales team spends too much time on manual lead research"],
        growth_signals=["Recently raised Series A", "Expanding sales team"],
        summary="A fast-growing SaaS company looking to scale outbound sales.",
        top_k=3,
    )
    for r in recs:
        print(f"  [{r.priority.upper():6}] {r.service}")
        print(f"           {r.reason}")

    print()
    print("=" * 60)
    print("Test 3: as JSON (what actually goes into the contract)")
    print("=" * 60)
    import json
    print(json.dumps([r.model_dump() for r in recs], indent=2))