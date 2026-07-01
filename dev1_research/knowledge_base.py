"""
Day 5 — Knowledge Base Retrieval

Loads AIBurst's own service catalog (aiburst_services.json) and, given a
company's research profile (from analyzer.py), returns the AIBurst services
most relevant to pitch — using keyword/tag matching (no external API calls,
no cost, no quota risk).

This module has ZERO dependency on Gemini — it works entirely offline.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_KB_PATH = Path(__file__).parent.parent / "shared" / "aiburst_services.json"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AIBurstService(BaseModel):
    id: str
    name: str
    description: str
    best_for: list[str] = Field(default_factory=list)
    pain_points_addressed: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class ServiceMatch(BaseModel):
    service: AIBurstService
    score: float
    matched_terms: list[str]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_services(path: Optional[Path] = None) -> list[AIBurstService]:
    """Load AIBurst's service catalog from disk."""
    kb_path = path or DEFAULT_KB_PATH
    if not kb_path.exists():
        raise FileNotFoundError(
            f"Knowledge base not found at {kb_path}. "
            "Make sure aiburst_services.json is in the shared/ folder."
        )
    with open(kb_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    services = [AIBurstService(**s) for s in data["services"]]
    logger.info("Loaded %d AIBurst services from knowledge base", len(services))
    return services


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _build_query_text(
    industry: str = "",
    pain_points: Optional[list[str]] = None,
    growth_signals: Optional[list[str]] = None,
    summary: str = "",
    products: Optional[list[str]] = None,
    services_offered: Optional[list[str]] = None,
) -> str:
    """Combine every relevant field from a company's research profile into
    one search blob."""
    parts = [
        industry,
        summary,
        " ".join(pain_points or []),
        " ".join(growth_signals or []),
        " ".join(products or []),
        " ".join(services_offered or []),
    ]
    return " ".join(p for p in parts if p)


def score_service(service: AIBurstService, query_tokens: set[str]) -> ServiceMatch:
    """Score one AIBurst service against a company's query tokens.

    Weighting:
      - keyword match: +3 each (these are the strongest signal terms)
      - pain_point phrase overlap: +2 each
      - best_for phrase overlap: +1 each
    """
    matched: list[str] = []
    score = 0.0

    for kw in service.keywords:
        kw_tokens = _tokenize(kw)
        if kw_tokens and kw_tokens.issubset(query_tokens):
            score += 3
            matched.append(kw)
        elif kw_tokens & query_tokens:
            score += 1
            matched.append(kw)

    for pp in service.pain_points_addressed:
        pp_tokens = _tokenize(pp)
        overlap = pp_tokens & query_tokens
        if overlap:
            score += 2 * (len(overlap) / max(len(pp_tokens), 1))
            matched.append(pp)

    for bf in service.best_for:
        bf_tokens = _tokenize(bf)
        overlap = bf_tokens & query_tokens
        if overlap:
            score += 1 * (len(overlap) / max(len(bf_tokens), 1))
            matched.append(bf)

    return ServiceMatch(service=service, score=round(score, 2), matched_terms=matched)


def retrieve_relevant_services(
    industry: str = "",
    pain_points: Optional[list[str]] = None,
    growth_signals: Optional[list[str]] = None,
    summary: str = "",
    products: Optional[list[str]] = None,
    services_offered: Optional[list[str]] = None,
    top_k: int = 3,
    kb_path: Optional[Path] = None,
) -> list[ServiceMatch]:
    """Main entry point. Given fields from a company's research profile
    (typically CompanyResearch.about + llm_analysis), return the top_k most
    relevant AIBurst services, ranked by score, score > 0 only.
    """
    services = load_services(kb_path)
    query_text = _build_query_text(
        industry, pain_points, growth_signals, summary, products, services_offered
    )
    query_tokens = _tokenize(query_text)

    if not query_tokens:
        logger.warning("Empty query — falling back to top services by catalog order")
        return [
            ServiceMatch(service=s, score=0.0, matched_terms=[])
            for s in services[:top_k]
        ]

    matches = [score_service(s, query_tokens) for s in services]
    matches = [m for m in matches if m.score > 0]
    matches.sort(key=lambda m: m.score, reverse=True)

    if not matches:
        logger.warning("No keyword matches found — returning empty list")
    return matches[:top_k]


def retrieve_from_company_research(company_research, top_k: int = 3) -> list[ServiceMatch]:
    """Convenience wrapper: takes a CompanyResearch pydantic object
    (from shared/schema.py, as produced by analyzer.py) directly."""
    about = company_research.about
    llm = company_research.llm_analysis
    return retrieve_relevant_services(
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
    matches = retrieve_relevant_services(
        industry="Solar manufacturing",
        pain_points=[
            "Manual quality control checks slow down production",
            "Audit certificate processing is error-prone",
        ],
        growth_signals=["Scaling from 3.6GW to 10GW capacity"],
        summary="Premier Energies is scaling solar cell and module manufacturing rapidly.",
        top_k=3,
    )
    for m in matches:
        print(f"  [{m.score}] {m.service.name} — matched: {m.matched_terms}")

    print()
    print("=" * 60)
    print("Test 2: B2B SaaS company with sales/lead gen pain points")
    print("=" * 60)
    matches = retrieve_relevant_services(
        industry="B2B SaaS",
        pain_points=["Sales team spends too much time on manual lead research"],
        growth_signals=["Recently raised Series A", "Expanding sales team"],
        summary="A fast-growing SaaS company looking to scale outbound sales.",
        top_k=3,
    )
    for m in matches:
        print(f"  [{m.score}] {m.service.name} — matched: {m.matched_terms}")

    print()
    print("=" * 60)
    print("Test 3: Empty/unknown company (fallback path)")
    print("=" * 60)
    matches = retrieve_relevant_services(top_k=3)
    for m in matches:
        print(f"  [{m.score}] {m.service.name}")